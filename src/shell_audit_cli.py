#!/usr/bin/env python3
"""Shell Audit & Repair - macOS developer shell environment auditor.

First-class Shell Audit & Repair capability for the MSP tool.
Integrates with the existing MSP CLI, TUI, rules engine, and fact collection.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.command import run_command, list_command, CommandResult
from src.facts import collect_facts, redact_facts
from src.rules import (
    Finding,
    Rule,
    SEVERITY_ORDER,
    findings_to_json,
    findings_to_table,
)
from src.shell_audit import (
    AuditFinding,
    audit_path_integrity,
    find_path_origins,
    audit_zstartup_semantics,
    audit_completion_system,
    audit_executable_shadowing,
    audit_symlink_integrity,
    audit_package_managers,
)


# ─── Helpers ──────────────────────────────────────────────────────────────

# Mapping from shell audit severity strings to numeric ranks.
# shell_audit.py uses: "ERROR", "WARNING", "NOTICE", "INFO", "SECURITY"
# rules.py uses: "info", "low", "medium", "high", "critical"
_SEVERITY_MAP: Dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
    # shell_audit.py severity strings
    "ERROR": 3,
    "WARNING": 2,
    "NOTICE": 1,
    "INFO": 0,
    "SECURITY": 3,
}


def _home() -> Path:
    """Return the user's home directory."""
    return Path.home()


def _detect_shell() -> str:
    """Detect the user's login shell."""
    shell = os.environ.get("SHELL", "")
    if "/zsh" in shell:
        return "zsh"
    elif "/bash" in shell:
        return "bash"
    return "unknown"


def _detect_architecture() -> str:
    """Detect the system architecture."""
    try:
        result = subprocess.run(["uname", "-m"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            arch = result.stdout.strip()
            if "arm" in arch.lower() or "aarch" in arch.lower():
                return "arm64 (Apple Silicon)"
            elif "x86_64" in arch.lower() or "amd64" in arch.lower():
                return "x86_64 (Intel)"
    except Exception:
        pass
    return "unknown"


def _severity_rank(severity: str) -> int:
    """Convert severity string to numeric rank.
    
    Handles both MSP severity strings (info/low/medium/high/critical)
    and shell audit severity strings (ERROR/WARNING/NOTICE/INFO/SECURITY).
    """
    # First try the MSP SEVERITY_ORDER mapping
    rank = SEVERITY_ORDER.get(severity)
    if rank is not None:
        return rank
    # Then try the shell_audit mapping
    return _SEVERITY_MAP.get(severity, 0)


def _run_subprocess(
    cmd: list[str], timeout: int = 10, *, text: bool = True
) -> subprocess.CompletedProcess:
    """Run a subprocess command with consistent error handling."""
    return subprocess.run(cmd, capture_output=True, text=text, timeout=timeout)


# ─── Audit Finding → Finding conversion ────────────────────────────────

def _auditfinding_to_finding(finding: AuditFinding) -> Finding:
    """Convert an AuditFinding to an MSP Finding."""
    return Finding(
        rule_id=finding.id,
        title=finding.title,
        category=finding.category,
        severity=finding.severity,
        description=finding.summary,
        remediation=finding.recommended_state,
        profile="personal",
        evidence={},
    )


# ─── Audit Orchestration ────────────────────────────────────────────────

def _run_all_audits(
    home: Path,
    shells: Sequence[str],
    categories: Optional[Sequence[str]] = None,
) -> List[AuditFinding]:
    """Run selected audit functions and aggregate findings."""
    findings: List[AuditFinding] = []

    # Always audit PATH integrity
    try:
        path_str = os.environ.get("PATH", "")
        path_findings = audit_path_integrity(path_str, home)
        findings.extend(path_findings)
    except Exception as e:
        findings.append(AuditFinding(
            id="shell.audit.path_integrity_error",
            category="path",
            severity="info",
            title="PATH integrity audit error",
            summary=f"Could not audit PATH: {e}",
            evidence=f"Error: {e}",
            source_file="",
            line_numbers=(),
            current_state="audit error",
            recommended_state="Check PATH configuration manually",
            risk="low",
            repairability="auto_safe",
        ))

    # Audit PATH origins if zsh or bash
    if "zsh" in shells or "bash" in shells:
        try:
            origin_findings = find_path_origins(_detect_shell(), home)
            for shell_type, shell_findings in origin_findings.items():
                findings.extend(shell_findings)
        except Exception as e:
            findings.append(AuditFinding(
                id="shell.audit.path_origins_error",
                category="path",
                severity="info",
                title="PATH provenance audit error",
                summary=f"Could not audit PATH origins: {e}",
                evidence=f"Error: {e}",
                source_file="",
                line_numbers=(),
                current_state="audit error",
                recommended_state="Check startup files manually",
                risk="low",
                repairability="auto_safe",
            ))

    # Audit zsh startup semantics if zsh
    if "zsh" in shells:
        try:
            zsh_findings = audit_zstartup_semantics(home)
            findings.extend(zsh_findings)
        except Exception as e:
            findings.append(AuditFinding(
                id="shell.audit.zstartup_error",
                category="zsh_startup",
                severity="info",
                title="zsh startup semantics audit error",
                summary=f"Could not audit zsh startup: {e}",
                evidence=f"Error: {e}",
                source_file="",
                line_numbers=(),
                current_state="audit error",
                recommended_state="Check zsh startup files manually",
                risk="low",
                repairability="auto_safe",
            ))

    # Audit completion system if zshrc exists
    try:
        zshrc = home / ".zshrc"
        zprofile = home / ".zprofile"
        if zshrc.exists() or zprofile.exists():
            comp_findings = audit_completion_system(zshrc, zprofile)
            findings.extend(comp_findings)
    except Exception as e:
        findings.append(AuditFinding(
            id="shell.audit.completion_error",
            category="completion",
            severity="info",
            title="Completion system audit error",
            summary=f"Could not audit completion system: {e}",
            evidence=f"Error: {e}",
            source_file="",
            line_numbers=(),
            current_state="audit error",
            recommended_state="Check zshrc/zprofile manually",
            risk="low",
            repairability="auto_safe",
        ))

    # Audit executable shadowing for common tools
    try:
        tools = ["git", "ssh", "curl", "python3", "python", "node", "npm", "npx",
                 "pnpm", "yarn", "bun", "ruby", "gem", "go", "cargo", "rustc",
                 "java", "docker", "kubectl", "brew"]
        exec_findings = audit_executable_shadowing(tools, home)
        findings.extend(exec_findings)
    except Exception as e:
        findings.append(AuditFinding(
            id="shell.audit.executable_error",
            category="executable",
            severity="info",
            title="Executable shadowing audit error",
            summary=f"Could not audit executables: {e}",
            evidence=f"Error: {e}",
            source_file="",
            line_numbers=(),
            current_state="audit error",
            recommended_state="Check tool installations manually",
            risk="low",
            repairability="auto_safe",
        ))

    # Audit symlink integrity
    try:
        default_paths = [
            str(home / ".local/bin"),
            str(home / ".codex"),
            str(home / ".local/share"),
        ]
        symlink_findings = audit_symlink_integrity(default_paths, home)
        findings.extend(symlink_findings)
    except Exception as e:
        findings.append(AuditFinding(
            id="shell.audit.symlink_error",
            category="symlink",
            severity="info",
            title="Symlink integrity audit error",
            summary=f"Could not audit symlinks: {e}",
            evidence=f"Error: {e}",
            source_file="",
            line_numbers=(),
            current_state="audit error",
            recommended_state="Check symlinks manually",
            risk="low",
            repairability="auto_safe",
        ))

    # Audit package managers
    try:
        pkg_findings = audit_package_managers(home)
        findings.extend(pkg_findings)
    except Exception as e:
        findings.append(AuditFinding(
            id="shell.audit.package_error",
            category="package_manager",
            severity="info",
            title="Package manager audit error",
            summary=f"Could not audit package managers: {e}",
            evidence=f"Error: {e}",
            source_file="",
            line_numbers=(),
            current_state="audit error",
            recommended_state="Check package manager configurations manually",
            risk="low",
            repairability="auto_safe",
        ))

    # If specific categories requested, filter
    if categories:
        category_set = set(categories)
        filtered: List[AuditFinding] = []
        for f in findings:
            # Map category string to our filter
            cat_lower = f.category.lower()
            # Check if any requested category matches
            matched = False
            for c in category_set:
                if c in cat_lower or cat_lower in c or c == cat_lower:
                    matched = True
                    break
            if matched:
                filtered.append(f)
        findings = filtered

    return findings


# ─── Repair Orchestration ───────────────────────────────────────────────

# Startup files scanned when removing a concrete PATH entry.
_PATH_STARTUP_FILES = (
    ".zshrc",
    ".zprofile",
    ".zshenv",
    ".zlogin",
    ".bashrc",
    ".bash_profile",
    ".profile",
)

# PATH findings whose repair is removing one concrete entry from startup files.
_PATH_ENTRY_REPAIR_IDS = {
    "shell.path.duplicate_entry",
    "shell.path.empty_entry",
    "shell.path.nonexistent_dir",
    "shell.path.relative_entry",
    "shell.path.malformed_entry",
}

# Backups live under ~/.msp/backups/shell_audit/<timestamp>/.
_BACKUP_ROOT = Path.home() / ".msp" / "backups" / "shell_audit"

# Actual compinit invocations (never `autoload -Uz compinit`).
_COMPINIT_LINE_RE = re.compile(r"^[ \t]*compinit\b|&&[ \t]*compinit\b", re.IGNORECASE)


# Repair scopes accepted by --scope / the interactive menu.
_SCOPE_CHOICES = ("auto_safe", "guided", "advisory", "all")

# Internal class names produced by _classify_repairability.
_CLASS_NAMES = ("auto_safe", "guided", "advisory_only")

_SCOPE_ALIASES = {
    "advisory": "advisory_only",
    "advisory_only": "advisory_only",
    "auto_safe": "auto_safe",
    "guided": "guided",
}


def _normalize_scope(scope: Any) -> Optional[set]:
    """Convert a --scope value (or list of them) into a set of class names.

    Returns None for the legacy default, which means "every class except
    advisory_only" — the behaviour callers relied on before scopes existed.
    """
    if scope is None:
        return None
    if isinstance(scope, str):
        items = [scope]
    else:
        items = list(scope)
    allowed: set = set()
    for item in items:
        key = str(item).strip().lower().replace("-", "_")
        if key == "all":
            allowed.update(_CLASS_NAMES)
            continue
        mapped = _SCOPE_ALIASES.get(key)
        if mapped is None:
            raise ValueError(f"unknown repair scope: {item}")
        allowed.add(mapped)
    return allowed


def _scope_allows(scope: Any, repairability: str) -> bool:
    """True when `repairability` falls inside `scope` (None = legacy)."""
    allowed = _normalize_scope(scope)
    if allowed is None:
        return repairability != "advisory_only"
    return repairability in allowed


def _classify_repairability(
    severity: str,
    category: str,
    finding: Optional[AuditFinding] = None,
) -> str:
    """Classify a finding as auto_safe / guided / advisory_only.

    Prefers the audit's own declaration (`finding.repairability`) when given;
    otherwise falls back to the severity/category heuristic.
    """
    declared = getattr(finding, "repairability", None) if finding is not None else None
    if declared:
        mapped = str(declared).strip().lower().replace("-", "_")
        if mapped in ("auto_safe", "guided", "advisory_only"):
            return mapped
    sev_rank = _severity_rank(severity)
    if sev_rank >= _severity_rank("high"):
        return "guided"
    if category in ("symlink", "executable"):
        return "auto_safe"
    return "advisory_only"


def _backup_file(path: Path) -> Path:
    """Copy `path` into a timestamped backup dir; return the backup path."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = _BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / path.name
    if dest.exists():
        dest = backup_dir / f"{path.name}.{os.getpid()}"
    shutil.copy2(path, dest)
    return dest


def _validate_shell_script(path: Path) -> Tuple[bool, str]:
    """Run `zsh -n` on `path`. Returns (ok, error message).

    Gracefully passes if zsh is unavailable.
    """
    try:
        proc = subprocess.run(
            ["zsh", "-n", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "zsh syntax check timed out"
    if proc.returncode == 0:
        return True, ""
    err = (proc.stderr or proc.stdout or "syntax check failed").strip()
    return False, err.splitlines()[0] if err else "syntax check failed"


def _write_validated(path: Path, content: str) -> Tuple[bool, str]:
    """Atomically replace `path` with `content` after `zsh -n` validation.

    Returns (True, backup_path) on success or (False, reason) on failure,
    leaving the original file untouched on failure.
    """
    tmp = path.with_name(path.name + ".msp-new")
    try:
        tmp.write_text(content, encoding="utf-8")
    except OSError as e:
        return False, f"could not write temp file: {e}"
    ok, err = _validate_shell_script(tmp)
    if not ok:
        tmp.unlink(missing_ok=True)
        return False, f"validation failed ({err}); original kept"
    try:
        backup = _backup_file(path)
        os.replace(tmp, path)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        return False, f"could not replace {path.name}: {e}"
    return True, str(backup)


def _repair_duplicate_compinit(finding: AuditFinding) -> Tuple[bool, str]:
    """Comment out duplicate compinit invocations, keeping the first."""
    src = finding.source_file or ""
    path = Path(src).expanduser() if src else (_home() / ".zshrc")
    if not path.is_file():
        return False, f"manual: {finding.title} - source file not found"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, f"manual: cannot read {path}: {e}"
    lines = content.splitlines(keepends=True)
    hits = [i for i, line in enumerate(lines) if _COMPINIT_LINE_RE.search(line)]
    if len(hits) < 2:
        return False, f"already clean: no duplicate compinit in {path.name}"
    for i in hits[1:]:
        if not lines[i].lstrip().startswith("compinit"):
            return False, (
                f"manual: duplicate compinit on line {i + 1} of {path.name} "
                "is part of a compound command"
            )
    for i in hits[1:]:
        line = lines[i]
        ending = "\n" if line.endswith("\n") else ""
        body = line[: -len(ending)] if ending else line
        lines[i] = f"# msp: duplicate compinit disabled: {body.strip()}{ending}"
    ok, msg = _write_validated(path, "".join(lines))
    if not ok:
        return False, f"manual: {path.name}: {msg}"
    n = len(hits) - 1
    return True, f"disabled {n} duplicate compinit line(s) in {path.name} (backup: {msg})"


def _entry_from_finding(finding: AuditFinding) -> str:
    """Extract the concrete PATH entry quoted in a finding's current_state."""
    state = finding.current_state or ""
    m = re.search(r"'([^']+)'", state)
    if m:
        return m.group(1)
    m = re.search(r'"([^"]+)"', state)
    return m.group(1) if m else ""


def _remove_entry_from_line(line: str, entry: str) -> Optional[str]:
    """Return `line` minus one colon-delimited occurrence of `entry`,
    or None when the line does not carry the entry as its own component."""
    if f"{entry}:" in line:
        return line.replace(f"{entry}:", "", 1)
    if f":{entry}" in line:
        return line.replace(f":{entry}", "", 1)
    return None


def _repair_path_entry(finding: AuditFinding) -> Tuple[bool, str]:
    """Remove one concrete entry from PATH assignments in shell startup files."""
    entry = _entry_from_finding(finding)
    if not entry:
        return False, f"manual: {finding.title} - could not determine the entry to remove"
    if entry.startswith("$"):
        return False, (
            f"manual: {finding.title} - '{entry}' is a runtime value, "
            "not a literal startup-file entry"
        )
    home = _home()
    for name in _PATH_STARTUP_FILES:
        path = home / name
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = content.splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            if not re.search(r"(^|[ \t])PATH=", line) and "path=(" not in line:
                continue
            new_line = _remove_entry_from_line(line, entry)
            if new_line is not None and new_line != line:
                lines[i] = new_line
                changed = True
        if changed:
            ok, msg = _write_validated(path, "".join(lines))
            if not ok:
                return False, f"manual: {name}: {msg}"
            return True, (
                f"removed PATH entry '{entry}' from {name} (backup: {msg}; "
                "restart your shell so the audit reflects it)"
            )
    system_source = _where_is_path_entry(entry)
    if system_source:
        return False, (
            f"manual: '{entry}' comes from {system_source} "
            "(system path file; requires sudo to edit)"
        )
    return False, (
        f"manual: '{entry}' not found in startup-file PATH assignments "
        "- edit your shell config by hand"
    )


def _where_is_path_entry(entry: str) -> str:
    """Return the system path file that carries `entry`, or "" if none."""
    candidates = [Path("/etc/paths")]
    try:
        candidates.extend(sorted(Path("/etc/paths.d").iterdir()))
    except OSError:
        pass
    for candidate in candidates:
        try:
            if any(
                line.strip() == entry
                for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines()
            ):
                return str(candidate)
        except OSError:
            continue
    return ""


def _repair_dangling_symlink(finding: AuditFinding) -> Tuple[bool, str]:
    """Remove a symlink whose target no longer exists (logged for rollback)."""
    src = finding.source_file or ""
    if not src:
        return False, f"manual: {finding.title} - no symlink path recorded"
    path = Path(src).expanduser()
    if not path.is_symlink():
        return False, f"already clean: {path} is not a symlink"
    try:
        target = os.readlink(path)
    except OSError as e:
        return False, f"manual: cannot read {path}: {e}"
    resolved = Path(target) if os.path.isabs(target) else (path.parent / target)
    if resolved.exists():
        return False, f"already clean: {path} now resolves to {resolved}"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = _BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    log = backup_dir / "removed_symlinks.log"
    try:
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{path} -> {target}\n")
        path.unlink()
    except OSError as e:
        return False, f"manual: cannot remove {path}: {e}"
    return True, f"removed dangling symlink {path} -> {target} (log: {log})"


def _has_automated_repair(finding: AuditFinding) -> bool:
    """True when `_repair` has a real implementation for this finding.

    Used to decide whether a guided finding is worth an "apply?" prompt —
    offering to apply a repair the engine cannot perform is a lie.
    """
    fid = finding.id or ""
    if fid in ("shell.zsh.zshrc_duplicate_compinit", "shell.completion.duplicate_compinit"):
        return True
    if fid.startswith("shell.symlink.dangling_"):
        return True
    return fid in _PATH_ENTRY_REPAIR_IDS


def _repair(finding: AuditFinding, dry_run: bool) -> Tuple[bool, str]:
    """Execute (or preview) the repair for a non-advisory finding."""
    if dry_run:
        return True, f"[dry run] would fix: {finding.title} -> {finding.recommended_state}"
    fid = finding.id or ""
    if fid in ("shell.zsh.zshrc_duplicate_compinit", "shell.completion.duplicate_compinit"):
        return _repair_duplicate_compinit(finding)
    if fid.startswith("shell.symlink.dangling_"):
        return _repair_dangling_symlink(finding)
    if fid in _PATH_ENTRY_REPAIR_IDS:
        return _repair_path_entry(finding)
    return False, f"manual: {finding.title} -> {finding.recommended_state}"


def _apply_repair(
    finding: AuditFinding,
    dry_run: bool = True,
    confirm: bool = True,
    scope: Any = None,
) -> Tuple[bool, str]:
    """Apply a repair for a finding. Returns (success, message).

    `confirm` is retained for API compatibility: every file change is backed
    up and syntax-validated, so applying is safe without per-finding prompts.
    `scope` filters by repairability class; None keeps the legacy behaviour
    of refusing advisory-only findings.
    """
    repairability = _classify_repairability(finding.severity, finding.category, finding)
    if not _scope_allows(scope, repairability):
        if scope is None and repairability == "advisory_only":
            return False, f"advisory: {finding.title} - skipped"
        return False, f"out of scope: {finding.title} [{repairability}]"
    return _repair(finding, dry_run)


def _apply_auto_safe(
    finding: AuditFinding, dry_run: bool = True
) -> Tuple[bool, str]:
    """Apply an auto-safe repair."""
    return _repair(finding, dry_run)


def _apply_guided(
    finding: AuditFinding, dry_run: bool = True
) -> Tuple[bool, str]:
    """Apply a guided repair (backup + validation make it safe to run)."""
    return _repair(finding, dry_run)


def _apply_all_repairs(
    findings: List[AuditFinding],
    dry_run: bool = True,
    confirm: bool = True,
    scope: Any = None,
) -> List[Tuple[bool, str]]:
    """Apply repairs for all findings in `scope`.

    Returns list of (success, message) tuples.
    """
    results: List[Tuple[bool, str]] = []
    for finding in findings:
        results.append(
            _apply_repair(finding, dry_run=dry_run, confirm=confirm, scope=scope)
        )
    return results


def _report_results(
    results: Sequence[Tuple[bool, str]],
    stream: Optional[Any] = None,
) -> None:
    """Print a human-readable summary of repair results.

    Skips are bucketed by what actually happened instead of one lumped
    "skipped" count: manual work, advisory-only findings, and unchanged
    findings are different situations and are reported separately.
    """
    stream = stream if stream is not None else sys.stdout
    if not results:
        return
    applied = [
        m for ok, m in results
        if ok and not m.startswith(("[dry run]", "[DRY RUN]"))
    ]
    manual = [m for ok, m in results if not ok and m.startswith("manual:")]
    advisory = [m for ok, m in results if not ok and m.startswith("advisory:")]
    other = [
        m for ok, m in results
        if not ok and not m.startswith(("manual:", "advisory:"))
    ]

    parts = [f"{len(applied)} applied"]
    if manual:
        parts.append(f"{len(manual)} need manual attention")
    if advisory:
        parts.append(f"{len(advisory)} advisory")
    if other:
        parts.append(f"{len(other)} unchanged")
    print(f"\n\U0001f527 Repairs: {', '.join(parts)}", file=stream)

    for msg in applied[:6]:
        print(f"  \u2713 {msg}", file=stream)
    if len(applied) > 6:
        print(f"  \u2026 and {len(applied) - 6} more applied", file=stream)

    for msg in manual[:6]:
        print(f"  \u23ed {msg}", file=stream)
    if len(manual) > 6:
        print(f"  \u2026 and {len(manual) - 6} more need manual attention", file=stream)

    if advisory:
        print(
            f"  \u2139  {len(advisory)} advisory finding(s) left unchanged - "
            "rerun with --scope advisory to attempt them",
            file=stream,
        )
    for msg in other[:6]:
        print(f"  \u23ed {msg}", file=stream)
    if len(other) > 6:
        print(f"  \u2026 and {len(other) - 6} more unchanged", file=stream)


# ─── Guided & AI Repair Flows ─────────────────────────────────────────────

_MAX_DIFF_LINES = 40

# Interactive menu: key -> (scope, label). "3" is only offered with --ai.
_SCOPE_MENU: Tuple[Tuple[str, str, str], ...] = (
    ("1", "auto_safe", "auto-safe only"),
    ("2", "guided", "guided - confirm each"),
    ("3", "guided", "guided with AI - confirm each proposal"),
    ("4", "advisory", "advisory only"),
    ("5", "all", "all"),
)

_SCOPE_DEFAULT_KEY = {"auto_safe": "1", "guided": "2", "advisory": "4", "all": "5"}


def _ask(prompt: str, default: str = "n") -> str:
    """Read a single-letter answer; EOF/Ctrl-C maps to quitting."""
    try:
        raw = input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "q"
    answer = raw.strip().lower()
    return answer or default


def _scope_counts(findings: Sequence[AuditFinding]) -> Dict[str, int]:
    counts = {name: 0 for name in _CLASS_NAMES}
    for finding in findings:
        counts[_classify_repairability(finding.severity, finding.category, finding)] += 1
    return counts


def _scope_count_key(scope: str) -> str:
    """Map a --scope value onto the key _scope_counts uses."""
    return "advisory_only" if scope == "advisory" else scope


def _menu_scope(choice: str, use_ai: bool) -> Tuple[List[str], bool]:
    """Map a menu key to (scope, use_ai)."""
    if choice == "1":
        return ["auto_safe"], False
    if choice == "2":
        return ["guided"], False
    if choice == "3":
        return ["guided"], True
    if choice == "4":
        return ["advisory"], False
    return ["auto_safe", "guided", "advisory"], use_ai


def _allowed_ai_paths(finding: AuditFinding) -> List[Path]:
    """Startup files (plus the finding's own source file) the AI may edit."""
    home = _home()
    paths: List[Path] = []
    for name in _PATH_STARTUP_FILES:
        candidate = home / name
        if candidate.is_file():
            paths.append(candidate)
    src = str(getattr(finding, "source_file", "") or "")
    if src:
        try:
            resolved = Path(src).expanduser().resolve()
            resolved.relative_to(home.resolve())
        except (OSError, ValueError):
            return paths
        if resolved.is_file() and resolved not in paths:
            paths.append(resolved)
    return paths


def _propose_ai_repair(finding: AuditFinding) -> Tuple[Optional[Any], str]:
    """Ask the LLM for a line edit, or return (None, reason). Never raises."""
    try:
        from src.shell_audit_ai import propose_repair
    except Exception as exc:  # pragma: no cover - import guard
        return None, f"AI unavailable ({exc})"
    try:
        return propose_repair(finding, _allowed_ai_paths(finding))
    except Exception as exc:
        return None, f"AI unavailable ({exc})"


def _prepare_ai_proposal(
    finding: AuditFinding,
) -> Tuple[Optional[Any], Optional[Tuple[str, str]], str]:
    """Return (edit, (original, new_content), reason).

    The edit is fully validated against the file on disk before the user is
    asked to approve it, so an approval can never apply a broken proposal.
    """
    try:
        from src.shell_audit_ai import apply_line_edit
    except Exception as exc:  # pragma: no cover - import guard
        return None, None, f"AI unavailable ({exc})"

    edit, reason = _propose_ai_repair(finding)
    if edit is None:
        return None, None, reason
    try:
        original = edit.path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, None, f"cannot read {edit.path}: {exc}"
    new_content, why = apply_line_edit(original, edit)
    if new_content is None:
        return None, None, why
    return edit, (original, new_content), ""


def _render_diff(path: Path, old: str, new: str) -> str:
    """Render a unified diff, truncated to keep prompts readable."""
    diff = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=str(path),
            tofile=str(path),
            lineterm="",
        )
    )
    if not diff:
        return "      (no textual diff)"
    body = "\n".join(f"      {line}" for line in diff[:_MAX_DIFF_LINES])
    if len(diff) > _MAX_DIFF_LINES:
        body += f"\n      \u2026 and {len(diff) - _MAX_DIFF_LINES} more diff lines"
    return body


def _ai_is_fatal(reason: str) -> bool:
    """True when the provider itself failed, so later calls would too."""
    if not reason:
        return False
    return reason.startswith("AI unavailable") or " failed:" in reason


def _prompt_guided(
    index: int,
    total: int,
    finding: AuditFinding,
    edit: Optional[Any],
    preview: Optional[Tuple[str, str]],
    ai_reason: str = "",
) -> str:
    print(f"\n[{index}/{total}] {finding.title} ({finding.id})")
    print(f"      {finding.severity} / {finding.category} - {finding.summary}")
    print(f"      fix: {finding.recommended_state}")
    if edit is not None and preview is not None:
        print(_render_diff(edit.path, preview[0], preview[1]))
        print(
            f"      AI {edit.provider} ({edit.path.name} {edit.range_label}, "
            f"confidence {edit.confidence:.2f}): {edit.explanation}"
        )
        return _ask("      Apply this edit? [y]es/[n]o/[a]ll remaining/[q]uit: ")
    if ai_reason:
        print(f"      (AI: {ai_reason}; offering the built-in repair instead)")
    return _ask("      Apply repair? [y]es/[n]o/[a]ll remaining/[q]uit: ")


def _apply_ai_proposal(
    finding: AuditFinding, edit: Any, new_content: str
) -> Tuple[bool, str]:
    ok, msg = _write_validated(edit.path, new_content)
    if not ok:
        return False, f"manual: {finding.title} - {edit.path.name}: {msg}"
    return True, (
        f"{edit.path.name} {edit.range_label}: {edit.explanation} "
        f"(AI {edit.provider}, confidence {edit.confidence:.2f}; backup: {msg})"
    )


def _guided_repair(
    findings: Sequence[AuditFinding],
    *,
    use_ai: bool = False,
    interactive: bool = True,
) -> List[Tuple[bool, str]]:
    """Walk guided findings one at a time, prompting before each change.

    Findings with no implemented repair are reported as manual without
    offering an "apply?" prompt that could never succeed.
    """
    results: List[Tuple[bool, str]] = []
    apply_all = False
    ai_blocked = ""
    total = len(findings)
    for index, finding in enumerate(findings, start=1):
        edit: Optional[Any] = None
        preview: Optional[Tuple[str, str]] = None
        reason = ""
        if use_ai:
            if ai_blocked:
                # A provider-level failure already happened; don't stall every
                # remaining finding on another timeout.
                reason = ai_blocked
            else:
                edit, preview, reason = _prepare_ai_proposal(finding)
                if edit is None and _ai_is_fatal(reason):
                    ai_blocked = reason
        if edit is None and not _has_automated_repair(finding):
            results.append(
                (False, f"manual: {finding.title} - {reason or finding.recommended_state}")
            )
            continue
        if interactive and not apply_all:
            choice = _prompt_guided(index, total, finding, edit, preview, reason)
            if choice == "q":
                results.append((False, f"skipped: {finding.title} - stopped by user"))
                results.extend(
                    (False, f"skipped: {later.title} - not reviewed")
                    for later in findings[index:]
                )
                return results
            if choice == "a":
                apply_all = True
            elif choice != "y":
                results.append((False, f"skipped: {finding.title} - declined"))
                continue
        if edit is not None and preview is not None:
            results.append(_apply_ai_proposal(finding, edit, preview[1]))
        else:
            results.append(_repair(finding, dry_run=False))
    return results


def _select_scope(
    findings: Sequence[AuditFinding], scope: Any
) -> List[AuditFinding]:
    """Keep only findings whose repairability class is inside `scope`."""
    return [
        f
        for f in findings
        if _scope_allows(scope, _classify_repairability(f.severity, f.category, f))
    ]


def _apply_fix(
    findings: Sequence[AuditFinding],
    *,
    scope: Any,
    use_ai: bool = False,
    interactive: bool = False,
) -> List[Tuple[bool, str]]:
    """Apply repairs, routing guided findings through the confirm loop."""
    results: List[Tuple[bool, str]] = []
    guided: List[AuditFinding] = []
    for finding in findings:
        repairability = _classify_repairability(
            finding.severity, finding.category, finding
        )
        if repairability == "guided" and (interactive or use_ai):
            guided.append(finding)
        else:
            results.append(
                _apply_repair(finding, dry_run=False, confirm=False, scope=scope)
            )
    if guided:
        results.extend(_guided_repair(guided, use_ai=use_ai, interactive=interactive))
    return results


def _report_outcome(
    results: Sequence[Tuple[bool, str]],
    *,
    scope: Any,
    unattempted: int = 0,
    stream: Optional[Any] = None,
) -> None:
    """Report results plus a note about findings excluded by --scope."""
    stream = stream if stream is not None else sys.stdout
    if results:
        _report_results(results, stream=stream)
    else:
        print(
            f"\n\U0001f527 Repairs: 0 applied - nothing in scope '{scope}' to repair",
            file=stream,
        )
    if unattempted > 0:
        print(
            f"  \u2139  {unattempted} finding(s) outside --scope {scope} were not "
            "attempted (try --scope guided, --scope advisory or --scope all)",
            file=stream,
        )


def _interactive_repair_menu(
    findings: Sequence[AuditFinding],
    *,
    use_ai: bool,
    default_scope: str,
    interactive: bool = True,
) -> None:
    """Ask which repair scope to run, then run it."""
    counts = _scope_counts(findings)
    total = len(findings)
    if not total:
        print("No findings to repair.")
        return

    print(
        f"\n\U0001f527 {total} findings - {counts['auto_safe']} auto-safe, "
        f"{counts['guided']} guided, {counts['advisory_only']} advisory."
    )
    print("\nChoose repair scope:")
    visible = []
    for key, scope, label in _SCOPE_MENU:
        if key == "3" and not use_ai:
            continue
        count = total if scope == "all" else counts.get(_scope_count_key(scope), 0)
        visible.append(key)
        print(f"  {key}) {label:<36} {count} findings")
    print("  n) nothing")

    default_key = _SCOPE_DEFAULT_KEY.get(default_scope, "1")
    valid = set(visible) | {"n", "no", "q"}
    choice = ""
    for _ in range(3):
        answer = _ask(f"Choice [{default_key}]: ", default=default_key)
        if answer in valid:
            choice = answer
            break
        print("  Please choose one of the listed options.")
    else:
        print("No changes applied.")
        return

    if choice in ("n", "no", "q"):
        print("No changes applied. Re-run with --fix to apply without prompting.")
        return

    scope, ai = _menu_scope(choice, use_ai)
    selected = _select_scope(findings, scope)
    if not selected:
        print(f"Nothing in scope '{scope}' to repair.")
        return
    results = _apply_fix(
        selected, scope=scope, use_ai=ai, interactive=interactive
    )
    _report_outcome(results, scope=scope)


# ─── CLI Entry Point ────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main entry point for msp shell audit command.

    Usage:
        msp shell audit                    Run comprehensive shell audit
        msp shell audit --verbose          Verbose output with details
        msp shell audit --json             JSON output
        msp shell audit --dry-run          Show findings without applying fixes
        msp shell audit --fix              Apply auto-safe repairs
        msp shell audit --fix --scope all  Apply every repair class
        msp shell audit --ai               Offer guided-with-AI repairs in the menu
        msp shell repair                   Re-audit and apply repairs for --scope
        msp shell repair --dry-run         Show repairs without applying
    """
    parser = argparse.ArgumentParser(
        description="MSP Shell Audit & Repair - macOS developer shell environment auditor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  msp shell audit                    Run comprehensive shell audit
  msp shell audit --verbose          Verbose output with details
  msp shell audit --json             JSON output
  msp shell audit --dry-run          Show findings only, no changes
  msp shell audit --fix              Apply auto-safe repairs (no prompts)
  msp shell audit --fix --scope all  Apply auto-safe + guided + advisory
  msp shell audit --ai               Add the guided-with-AI option to the menu
  msp shell repair                   Re-audit and apply repairs for --scope

Scopes (--scope):
  auto_safe   Backed-up, syntax-validated repairs that need no decisions
  guided      Repairs that need a decision - confirmed one at a time
  advisory    Findings normally left alone; --scope advisory attempts them
  all         Everything above

Examples:
  msp shell audit                         Run full audit, then pick a scope
  msp shell audit --fix                   Apply auto-safe repairs only
  msp shell audit --fix --dry-run         Preview repairs only
  msp shell audit --scope guided --ai     AI proposes, you approve each edit
  msp shell audit --profile personal      Run audit with personal profile
"""
    )

    parser.add_argument(
        "--verbose", action="store_true", help="Verbose output with details"
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON output"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Show findings only, without prompting to apply fixes",
    )
    parser.add_argument(
        "--fix",
        action="store_false",
        dest="dry_run",
        help="Apply repairs for --scope without prompting (default: auto_safe)",
    )
    parser.add_argument(
        "--profile",
        choices=["personal", "developer", "enterprise", "high_security"],
        default="personal",
        help="Audit profile (default: personal)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write findings to file instead of stdout",
    )
    parser.add_argument(
        "--fix-only",
        action="store_true",
        default=False,
        help="Only apply repairs, skip audit",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=["path", "zsh_startup", "completion", "executable", "symlink", "package_manager"],
        default=None,
        help="Audit categories to include (default: all)",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        default=False,
        help="Skip confirmation prompts for guided repairs",
    )
    parser.add_argument(
        "--scope",
        choices=list(_SCOPE_CHOICES),
        default="auto_safe",
        help=(
            "Repair class to apply with --fix, and the default menu choice "
            "(default: auto_safe)"
        ),
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        default=False,
        help="Offer guided-with-AI repairs (the model proposes each edit, you approve)",
    )


    args = parser.parse_args(list(argv) if argv is not None else None)

    # Determine home directory and shell
    home = _home()
    shell_name = _detect_shell()

    # --fix-only: audit then apply, without the interactive menu
    if args.fix_only:
        if not args.json:
            print("Auditing shell environment...")
        findings = _run_all_audits(
            home=home, shells=[shell_name], categories=args.categories
        )
        # Filter by profile severity
        min_severity = _severity_rank(args.profile)
        filtered = [
            f for f in findings
            if _severity_rank(f.severity) >= min_severity
        ]
        # Convert to MSP Finding for output utilities
        msp_findings = [_auditfinding_to_finding(f) for f in filtered]

        # Output findings first so the repair report reads as the outcome
        if args.json:
            output = json.dumps(
                [f.__dict__ for f in msp_findings], indent=2, default=str
            )
            if args.output:
                Path(args.output).write_text(output)
            else:
                print(output)
        else:
            if msp_findings:
                print(findings_to_table(msp_findings))
            else:
                print("No findings matching the selected profile.")

        # Apply repairs (fix-only implies --fix unless --dry-run is explicit)
        if args.dry_run is not True:
            selected = _select_scope(filtered, args.scope)
            results = _apply_fix(
                selected, scope=args.scope, use_ai=args.ai, interactive=False
            )
            _report_outcome(
                results,
                scope=args.scope,
                unattempted=len(filtered) - len(selected),
                stream=sys.stderr if args.json else None,
            )
        else:
            print("Dry run: no changes applied.", file=sys.stderr)
        return 0

    # Run audit
    if args.verbose:
        print(f"\n🔍 MSP Shell Audit")
        print(f"   Shell: {shell_name}")
        print(f"   Architecture: {_detect_architecture()}")
        print(f"   Home: {home}")
        print()

    findings = _run_all_audits(
        home=home,
        shells=[shell_name],
        categories=args.categories,
    )

    # Filter by severity profile
    profile = args.profile
    min_severity = _severity_rank(profile)
    filtered = [
        f for f in findings
        if _severity_rank(f.severity) >= min_severity
    ]

    # Sort by severity then category then ID
    filtered.sort(key=lambda f: (-_severity_rank(f.severity), f.category, f.id))

    # Convert to MSP Finding for output utilities
    msp_findings = [_auditfinding_to_finding(f) for f in filtered]

    # Output findings
    if args.json:
        output = json.dumps(
            [f.__dict__ for f in msp_findings], indent=2, default=str
        )
        if args.output:
            Path(args.output).write_text(output)
        else:
            print(output)
    else:
        if msp_findings:
            print(findings_to_table(msp_findings))
        else:
            print("No findings matching the selected profile.")

    if args.dry_run is False:
        # --fix flag was used (sets dry_run to False via action='store_false').
        # Applies --scope (auto-safe by default) with no prompts.
        selected = _select_scope(filtered, args.scope)
        results = _apply_fix(
            selected, scope=args.scope, use_ai=args.ai, interactive=False
        )
        _report_outcome(
            results,
            scope=args.scope,
            unattempted=len(filtered) - len(selected),
            stream=sys.stderr if args.json else None,
        )
    elif args.dry_run is True:
        # Explicit --dry-run: show findings only, no prompt
        print("Dry run: no changes applied. Re-run without --dry-run to review repairs, or use --fix to apply.", file=sys.stderr)
    elif args.json:
        # JSON output must stay machine-readable: never prompt interactively
        print("Re-run with --fix to apply safe repairs.", file=sys.stderr)
    else:
        # Default (no flags): show findings, then choose a repair scope
        _interactive_repair_menu(
            filtered,
            use_ai=args.ai,
            default_scope=args.scope,
            interactive=not args.no_confirm,
        )

    return 0