#!/usr/bin/env python3
"""Optional LLM reasoning support for macOS privacy evidence.

The module is dependency-free by default. Local providers (ollama, apfel)
require no SDK installs. Cloud-backed providers are optional and imported
lazily so the CLI remains usable offline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Protocol, Sequence
from urllib.request import Request, urlopen
from urllib.error import URLError

from src.command import (
    interactive_menu as cmd_interactive_menu,
    interactive_select as cmd_interactive_select,
    setup_completion,
    suggest_command,
)

try:
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


@contextmanager
def _spinner(message: str) -> Iterator[None]:
    """Show a spinner while work is in progress. Falls back to simple text."""
    if RICH_AVAILABLE:
        with Progress(SpinnerColumn(), TextColumn(f"[progress.description]{message}..."), transient=True) as p:
            p.add_task("", total=None)
            yield
    else:
        sys.stdout.write(f"\r\u23f3 {message}...")
        sys.stdout.flush()
        try:
            yield
        finally:
            sys.stdout.write("\r" + " " * 40 + "\r")
            sys.stdout.flush()


DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_APFEL_EXECUTABLE = "apfel"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:1.5b"


class LLMProvider(Protocol):
    """Provider contract used by LLMReasoner."""

    name: str

    def complete_json(self, prompt: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a JSON-compatible response for the supplied evidence."""


def _severity_rank(severity: Any) -> int:
    ranks = {
        "critical": 5,
        "high": 4,
        "medium": 3,
        "low": 2,
        "info": 1,
        "unknown": 0,
    }
    return ranks.get(str(severity or "unknown").lower(), 0)


def _normalize_findings(findings: Any) -> List[Mapping[str, Any]]:
    if isinstance(findings, Mapping):
        findings = findings.get("findings", [])
    if not isinstance(findings, list):
        return []
    return [item for item in findings if isinstance(item, Mapping)]


def _count_sections(value: Any) -> int:
    if isinstance(value, Mapping):
        return len(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value)
    return 1 if value is not None else 0


class LocalHeuristicProvider:
    """Offline provider that summarizes evidence without calling an LLM."""

    name = "local_heuristic"

    def complete_json(self, prompt: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        del prompt
        facts = payload.get("facts", {})
        findings = _normalize_findings(payload.get("findings", []))
        plan = payload.get("plan")

        by_severity: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        for finding in findings:
            severity = str(finding.get("severity", "unknown")).lower()
            category = str(finding.get("category", "uncategorized") or "uncategorized")
            by_severity[severity] = by_severity.get(severity, 0) + 1
            by_category[category] = by_category.get(category, 0) + 1

        sorted_findings = sorted(findings, key=lambda item: _severity_rank(item.get("severity")), reverse=True)
        top_titles = [str(item.get("title") or item.get("rule_id") or "Untitled finding") for item in sorted_findings[:3]]
        critical_or_high = sum(
            1 for item in findings if str(item.get("severity", "")).lower() in {"critical", "high"}
        )
        fact_sections = _count_sections(facts)

        if critical_or_high:
            risk_level = "high"
        elif by_severity.get("medium", 0):
            risk_level = "medium"
        elif findings:
            risk_level = "low"
        else:
            risk_level = "low"

        next_steps: List[str] = []
        if sorted_findings:
            next_steps.append("Review highest-severity findings and confirm the evidence on the host.")
            if plan:
                next_steps.append("Generate a dry-run remediation plan before applying any changes.")
            else:
                next_steps.append("Create a remediation plan for findings with supported fixes.")
        else:
            next_steps.append("Keep the current baseline and rerun interrogation after system changes.")
        next_steps.append("Export an evidence report for audit history and drift comparison.")

        return {
            "summary": (
                f"Reviewed {fact_sections} fact sections and {len(findings)} findings. "
                f"Top concerns: {', '.join(top_titles) if top_titles else 'none detected'}."
            ),
            "risk_assessment": {
                "level": risk_level,
                "by_severity": by_severity,
                "by_category": by_category,
                "critical_or_high_findings": critical_or_high,
            },
            "recommended_next_steps": next_steps,
            "confidence": 0.72 if findings else 0.64,
        }


@dataclass
class ApfelProvider:
    """Provider that delegates reasoning to an installed Apfel executable."""

    executable: Optional[str] = None
    timeout: int = 45
    name: str = "apfel"

    def __post_init__(self) -> None:
        if self.executable is None:
            self.executable = os.environ.get("APFEL_EXECUTABLE", DEFAULT_APFEL_EXECUTABLE)

    @classmethod
    def available(cls) -> bool:
        executable = os.environ.get("APFEL_EXECUTABLE", DEFAULT_APFEL_EXECUTABLE)
        return shutil.which(executable) is not None

    def complete_json(self, prompt: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.executable or shutil.which(self.executable) is None:
            raise RuntimeError("apfel executable is not available")

        request = {"prompt": prompt, "payload": payload}
        completed = subprocess.run(
            [self.executable, "reason", "--json"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "apfel provider failed")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("apfel provider returned invalid JSON") from exc
        if not isinstance(result, Mapping):
            raise RuntimeError("apfel provider returned a non-object JSON response")
        return result


@dataclass
class OllamaProvider:
    """Local provider that calls Ollama's REST API for structured reasoning.

    Zero external dependencies — uses stdlib urllib only.
    Supports JSON mode for guaranteed structured output.
    Uses qwen2.5-coder:1.5b by default — ultra-small (~1GB RAM, runs on any Mac).
    If Ollama is unavailable or crashes, falls back to apfel / local heuristic.
    """

    base_url: str = DEFAULT_OLLAMA_BASE_URL
    model: str = DEFAULT_OLLAMA_MODEL
    timeout: int = 60
    model_timeout: int = 30
    name: str = "ollama"

    def __post_init__(self) -> None:
        self.base_url = os.environ.get("OLLAMA_BASE_URL", self.base_url).rstrip("/")
        self.model = os.environ.get("OLLAMA_MODEL", self.model)

    @classmethod
    def available(cls) -> bool:
        base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        req = Request(f"{base_url}/api/tags", method="GET")
        req.add_header("Accept", "application/json")
        try:
            with urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except (URLError, OSError):
            return False

    def _confirm_model_loaded(self) -> None:
        """Check if the model exists on the server before sending a chat request.
        Prevents Ollama from silently crashing when loading a model that won't fit.
        """
        req = Request(f"{self.base_url}/api/tags", method="GET")
        req.add_header("Accept", "application/json")
        try:
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama not reachable: {exc}") from exc

        models = data.get("models", [])
        model_names = [m.get("name", "") for m in models]
        if not any(self.model in name for name in model_names):
            raise RuntimeError(
                f"Ollama model '{self.model}' not found. "
                f"Run: ollama pull {self.model}"
                f"\nAvailable: {', '.join(model_names[:5]) or 'none'}"
            )

    def complete_json(self, prompt: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self._confirm_model_loaded()

        url = f"{self.base_url}/api/chat"
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a macOS privacy and security analyst. "
                    "Return only a valid JSON object. "
                    "Do not include markdown fences, explanations, or extra text."
                ),
            },
            {
                "role": "user",
                "content": prompt + "\n\nEvidence JSON:\n" + json.dumps(payload, sort_keys=True),
            },
        ]
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_ctx": 2048,
            },
        }).encode("utf-8")

        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")

        with _spinner(f"Ollama ({self.model})"):
            try:
                with urlopen(req, timeout=self.model_timeout) as resp:
                    response_data = json.loads(resp.read().decode("utf-8"))
            except URLError as exc:
                raise RuntimeError(f"Ollama request failed: {exc.reason}") from exc
            except (json.JSONDecodeError, OSError) as exc:
                raise RuntimeError(f"Ollama response error: {exc}") from exc

        raw = response_data.get("message", {}).get("content", "")
        if not raw:
            raise RuntimeError("Ollama returned an empty response")

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Ollama returned non-JSON content: {raw[:200]}"
            ) from exc

        if not isinstance(result, Mapping):
            raise RuntimeError("Ollama returned a non-object JSON response")
        return result


@dataclass
class OpenAIProvider:
    """Optional OpenAI provider using the SDK only when configured."""

    api_key: Optional[str] = None
    model: Optional[str] = None
    name: str = "openai"

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    def _client(self) -> Any:
        api_key = self.api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError("openai package is not installed") from exc
        return OpenAI(api_key=api_key)

    def complete_json(self, prompt: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        client = self._client()
        model = self.model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a macOS privacy and security analyst. "
                        "Return only a compact JSON object."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt + "\n\nEvidence JSON:\n" + json.dumps(payload, sort_keys=True),
                },
            ]
        try:
            response = client.responses.create(
                model=model,
                input=messages,
                text={"format": {"type": "json_object"}},
            )
        except TypeError:
            response = client.responses.create(
                model=model,
                input=messages,
                response_format={"type": "json_object"},
            )
        text = getattr(response, "output_text", "")
        if not text:
            raise RuntimeError("OpenAI provider returned no text")
        result = json.loads(text)
        if not isinstance(result, Mapping):
            raise RuntimeError("OpenAI provider returned a non-object JSON response")
        return result


def choose_provider(preferred: Optional[str] = None) -> LLMProvider:
    """Select an available provider without requiring cloud dependencies.

    Priority order: explicit choice > env var > auto
    Auto order: ollama (local) > apfel (Apple Intel.) > openai (cloud) > local heuristic
    """

    provider = (preferred or os.environ.get("MSP_LLM_PROVIDER") or "auto").lower()
    if provider in {"local", "local_heuristic", "heuristic"}:
        return LocalHeuristicProvider()
    if provider == "ollama":
        return OllamaProvider()
    if provider == "apfel":
        return ApfelProvider()
    if provider == "openai":
        return OpenAIProvider()
    if provider != "auto":
        raise ValueError(f"unknown LLM provider: {preferred}")
    if OllamaProvider.available():
        return OllamaProvider()
    if ApfelProvider.available():
        return ApfelProvider()
    if OpenAIProvider.available():
        return OpenAIProvider()
    return LocalHeuristicProvider()


def _coerce_reasoning(result: Mapping[str, Any], provider_name: str) -> Dict[str, Any]:
    steps = result.get("recommended_next_steps", [])
    if isinstance(steps, str):
        steps = [steps]
    if not isinstance(steps, list):
        steps = []

    confidence = result.get("confidence", 0.5)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.5
    confidence_value = max(0.0, min(1.0, confidence_value))

    risk = result.get("risk_assessment", {})
    if not isinstance(risk, Mapping):
        risk = {"level": str(risk)}

    return {
        "summary": str(result.get("summary", "No reasoning summary returned.")),
        "risk_assessment": dict(risk),
        "recommended_next_steps": [str(item) for item in steps],
        "confidence": confidence_value,
        "provider": str(result.get("provider") or provider_name),
    }


class LLMReasoner:
    """Structured reasoning facade over facts, findings, and remediation plans."""

    def __init__(self, provider: Optional[LLMProvider] = None, provider_name: Optional[str] = None):
        self.provider = provider or choose_provider(provider_name)

    def analyze(
        self,
        facts: Optional[Mapping[str, Any]] = None,
        findings: Optional[Any] = None,
        plan: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "facts": facts or {},
            "findings": findings or [],
            "plan": plan or {},
        }
        prompt = (
            "Analyze the macOS privacy evidence. Return JSON with summary, "
            "risk_assessment, recommended_next_steps, confidence."
        )
        result = self.provider.complete_json(prompt, payload)
        return _coerce_reasoning(result, self.provider.name)


def analyze(
    facts: Optional[Mapping[str, Any]] = None,
    findings: Optional[Any] = None,
    plan: Optional[Mapping[str, Any]] = None,
    provider: Optional[LLMProvider] = None,
    provider_name: Optional[str] = None,
) -> Dict[str, Any]:
    return LLMReasoner(provider=provider, provider_name=provider_name).analyze(facts, findings, plan)


def _load_json(path: Optional[str], default: Any) -> Any:
    if not path:
        return default
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reason over macOS privacy evidence.")
    parser.add_argument("--facts", help="Facts JSON file.")
    parser.add_argument("--findings", help="Findings JSON file.")
    parser.add_argument("--plan", help="Remediation plan JSON file.")
    parser.add_argument("--provider", choices=["auto", "local", "ollama", "apfel", "openai"], default="auto")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--output", help="Write reasoning output to a file.")
    return parser


def interactive_menu() -> None:
    """Interactive menu for LLM reasoning."""
    from .facts import collect_facts

    facts = {}
    findings = []

    while True:
        action = cmd_interactive_menu([
            ("1", "Collect fresh facts & run analysis", None),
            ("2", "Load facts from file", None),
            ("3", "Select provider", None),
        ], title="Reason - LLM Privacy Analysis")

        if action is None:
            break

        if action == "1":
            print("\nCollecting system facts...")
            try:
                facts = collect_facts(redact=False)
                providers = ["auto", "local", "ollama", "apfel", "openai"]
                items = [(p, p, None) for p in providers]
                result = cmd_interactive_select(items, title="Select provider")
                provider = result[0] if result else "auto"
                print(f"\nAnalyzing with provider: {provider}")
                result = analyze(facts=facts, findings=findings, provider_name=provider)
                print(json.dumps(result, indent=2, sort_keys=True))
            except Exception as e:
                print(f"Error: {e}")
            input("\nPress Enter to continue...")
        elif action == "2":
            path = input("Path to facts JSON file: ").strip()
            if path:
                try:
                    facts = _load_json(path, {})
                    print(f"Loaded facts from {path}")
                except Exception as e:
                    print(f"Error: {e}")
            input("\nPress Enter to continue...")
        elif action == "3":
            providers = ["auto", "local", "ollama", "apfel", "openai"]
            items = [(p, p, None) for p in providers]
            result = cmd_interactive_select(items, title="Select provider")
            if result:
                provider = result[0]
                print(f"\nAnalyzing with provider: {provider}")
                try:
                    result = analyze(facts=facts, findings=findings, provider_name=provider)
                    print(json.dumps(result, indent=2, sort_keys=True))
                except Exception as e:
                    print(f"Error: {e}")
            input("\nPress Enter to continue...")


def main(argv: Optional[Sequence[str]] = None) -> int:
    if len(sys.argv) <= 1:
        interactive_menu()
        return 0
    parser = _build_parser()
    setup_completion(parser)
    args = parser.parse_args(argv)
    try:
        result = analyze(
            facts=_load_json(args.facts, {}),
            findings=_load_json(args.findings, []),
            plan=_load_json(args.plan, {}),
            provider_name=args.provider,
        )
        rendered = json.dumps(result, indent=2, sort_keys=True)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        if args.json or not args.output:
            print(rendered)
        return 0
    except Exception as exc:
        print(f"reason: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
