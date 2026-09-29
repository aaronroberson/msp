#!/usr/bin/env python3
"""AI-assisted repair proposals for shell audit findings.

The LLM never writes files itself. It returns a *line range edit* for a single
allow-listed startup file, and the caller applies it through the same
backup + `zsh -n` validation path used by every other repair.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Cap on how much file content is handed to the model (providers such as
# Ollama run with a ~2k token context).
MAX_CONTEXT_CHARS = 6000

PROMPT = (
    "Repair exactly one shell-startup finding by editing a single file. "
    "Return one JSON object with keys: action, path, start_line, end_line, "
    "replacement, explanation, confidence. "
    'action is "edit" or "no_change". '
    "path must be one of the allowed paths listed in the payload. "
    "start_line and end_line are 1-based inclusive line numbers referring to "
    "the supplied file content; replacement is the full text that replaces "
    "those lines (use an empty string to delete them). "
    "Change nothing that is unrelated to the finding, never reorder unrelated "
    'lines, and never move secrets into the file. If the finding cannot be '
    "fixed by editing this one file, or you are not certain, return "
    '{"action": "no_change", "explanation": "<why>"} instead of guessing.'
)


@dataclass(frozen=True)
class LineEdit:
    """A validated, not-yet-applied edit to a single startup file."""

    path: Path
    start_line: int
    end_line: int
    replacement: str
    explanation: str
    provider: str
    confidence: float

    @property
    def range_label(self) -> str:
        if self.start_line == self.end_line:
            return f"line {self.start_line}"
        return f"lines {self.start_line}-{self.end_line}"


def _as_line_number(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, confidence))


def _finding_payload(
    finding: Any, allowed_paths: Sequence[Path], context_path: Path, content: str
) -> Dict[str, Any]:
    return {
        "finding": {
            "id": getattr(finding, "id", ""),
            "category": getattr(finding, "category", ""),
            "severity": getattr(finding, "severity", ""),
            "title": getattr(finding, "title", ""),
            "summary": getattr(finding, "summary", ""),
            "current_state": getattr(finding, "current_state", ""),
            "recommended_state": getattr(finding, "recommended_state", ""),
            "source_file": getattr(finding, "source_file", ""),
        },
        "allowed_paths": [str(p) for p in allowed_paths],
        "file": {
            "path": str(context_path),
            "content": content,
            "truncated": len(content) >= MAX_CONTEXT_CHARS,
        },
    }


def apply_line_edit(content: str, edit: LineEdit) -> Tuple[Optional[str], str]:
    """Return `content` with `edit` applied, or (None, reason) when rejected."""
    lines = content.splitlines(keepends=True)
    if edit.start_line < 1 or edit.end_line < edit.start_line:
        return None, f"invalid line range {edit.start_line}-{edit.end_line}"
    if edit.end_line > len(lines):
        return None, (
            f"line range {edit.range_label} exceeds file length ({len(lines)} lines)"
        )
    replacement = edit.replacement
    if replacement and not replacement.endswith("\n"):
        replacement += "\n"
    new_content = (
        "".join(lines[: edit.start_line - 1])
        + replacement
        + "".join(lines[edit.end_line :])
    )
    if new_content == content:
        return None, "proposal makes no effective change"
    return new_content, ""


def _parse_proposal(
    result: Mapping[str, Any],
    allowed: Mapping[str, Path],
    context_path: Path,
    content: str,
    provider_name: str,
) -> Tuple[Optional[LineEdit], str]:
    action = str(result.get("action", "")).strip().lower()
    explanation = str(result.get("explanation") or "").strip()
    if action != "edit":
        return None, explanation or "model declined to edit the file"

    raw_path = str(result.get("path") or "").strip()
    if not raw_path:
        return None, "proposal did not name a file"
    resolved = Path(raw_path).expanduser()
    target = allowed.get(str(resolved)) or allowed.get(str(resolved.resolve()))
    if target is None:
        return None, f"proposal targets a path outside the allow-list: {raw_path}"

    start_line = _as_line_number(result.get("start_line"))
    end_line = _as_line_number(result.get("end_line"))
    if start_line is None or end_line is None:
        return None, "proposal line range is not numeric"

    edit = LineEdit(
        path=target,
        start_line=start_line,
        end_line=end_line,
        replacement=str(result.get("replacement") or ""),
        explanation=explanation or f"edited {target.name} {start_line}-{end_line}",
        provider=provider_name,
        confidence=_clamp_confidence(result.get("confidence")),
    )

    # The model may only edit the file whose content it was shown.
    if target != context_path:
        return None, "proposal targets a different file than the one supplied"

    new_content, reason = apply_line_edit(content, edit)
    if new_content is None:
        return None, reason
    return edit, ""


def propose_repair(
    finding: Any,
    allowed_paths: Sequence[Path],
    provider: Any = None,
) -> Tuple[Optional[LineEdit], str]:
    """Ask the configured LLM for a line-edit repair.

    Returns (edit, "") on success or (None, human-readable reason). Never
    raises: an unavailable provider, a refused answer, or an invalid proposal
    all degrade to a manual-repair reason so callers stay honest.
    """
    files = [p for p in allowed_paths if p.is_file()]
    if not files:
        return None, "no startup file available to edit"

    preferred = Path(str(getattr(finding, "source_file", "") or "")).expanduser()
    context_path = preferred if preferred in files else files[0]
    try:
        content = context_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"cannot read {context_path}: {exc}"

    shown = content[:MAX_CONTEXT_CHARS]

    try:
        from src import llm
    except Exception as exc:  # pragma: no cover - import guard
        return None, f"AI unavailable ({exc})"

    if provider is None:
        try:
            provider = llm.choose_provider()
        except Exception as exc:
            return None, f"AI unavailable ({exc})"

    if isinstance(provider, llm.LocalHeuristicProvider):
        return None, (
            "no LLM provider available (start `ollama serve` and "
            "`ollama pull qwen2.5-coder:1.5b`, or set OPENAI_API_KEY)"
        )

    provider_name = str(getattr(provider, "name", "llm"))
    prompt = PROMPT
    payload = _finding_payload(finding, files, context_path, shown)
    try:
        result = provider.complete_json(prompt, payload)
    except Exception as exc:
        return None, f"AI provider {provider_name} failed: {exc}"

    if not isinstance(result, Mapping):
        return None, f"AI provider {provider_name} returned a non-object response"

    allowed_map = {str(p): p for p in files}
    for path in files:
        try:
            allowed_map[str(path.resolve())] = path
        except OSError:
            continue

    edit, reason = _parse_proposal(result, allowed_map, context_path, content, provider_name)
    if edit is None:
        return None, f"AI proposal rejected ({reason})"
    return edit, ""


def proposal_to_json(edit: LineEdit) -> Dict[str, Any]:
    """Serialize a proposal for --json consumers / debugging."""
    return {
        "path": str(edit.path),
        "start_line": edit.start_line,
        "end_line": edit.end_line,
        "replacement": edit.replacement,
        "explanation": edit.explanation,
        "provider": edit.provider,
        "confidence": edit.confidence,
    }


__all__ = [
    "MAX_CONTEXT_CHARS",
    "PROMPT",
    "LineEdit",
    "apply_line_edit",
    "propose_repair",
    "proposal_to_json",
]
