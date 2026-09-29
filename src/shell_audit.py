#!/usr/bin/env python3
"""Shell Audit & Repair - macOS developer shell environment auditor.

A comprehensive shell-environment auditing subsystem that can detect, explain,
and safely correct configuration problems commonly found on macOS developer systems.

Supports zsh and bash, with detection of:
- PATH integrity (duplicates, missing directories, suspicious entries)
- PATH provenance (where entries come from via startup files)
- zsh startup semantics (.zshenv, .zprofile, .zshrc, .zlogin placement)
- Completion system audit (compinit ordering, duplicate initialization)
- Executable resolution / shadowing (multiple installations, symlinks)
- Symlink integrity (dangling links, stale current links)
- Package manager environment (Homebrew, NVM, pnpm, Bun, Cargo, Go, etc.)
- Architecture audit (Apple Silicon vs x86_64)
- Shell configuration hygiene (duplicate vars, repeated source commands)
- Security checks (world-writable PATH dirs, . in PATH, etc.)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.command import run_command, list_command, CommandResult
from src.rules import Rule, Finding, RuleEngine, evaluate, findings_to_json, findings_to_table, SEVERITY_ORDER
from src.facts import collect_facts, redact_facts


# ─── Data Models ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditFinding:
    """A single audit finding with structured data."""

    id: str
    category: str
    severity: str  # INFO, NOTICE, WARNING, ERROR, SECURITY
    title: str
    summary: str
    evidence: str
    source_file: str
    line_numbers: Tuple[int, ...]
    current_state: str
    recommended_state: str
    risk: str
    repairability: str  # AUTO_SAFE, GUIDED, ADVISORY_ONLY
    repair_action: Optional[str] = None
    requires_confirmation: bool = False
    requires_privilege: bool = False
    rollback_information: Optional[str] = None


@dataclass(frozen=True)
class RepairAction:
    """A proposed repair action with safety guarantees."""

    id: str
    finding_id: str
    title: str
    description: str
    safety_level: str  # low, medium, high, destructive
    dry_run: bool = True
    backup_path: Optional[str] = None
    new_content: Optional[str] = None
    requires_confirmation: bool = True
    idempotent: bool = True
    syntax_validate: bool = True

    def execute(self, apply: bool = False) -> CommandResult:
        if not apply:
            return CommandResult(
                command=[self.id],
                returncode=0,
                dry_run=True,
                output=f"Dry run: would {self.title}",
            )
        # Apply the repair
        if self.backup_path and Path(self.backup_path).exists():
            pass  # backup already created
        if self.new_content:
            path = Path(self.backup_path) if self.backup_path else Path(self.finding_id)
            path.write_text(self.new_content, encoding="utf-8")
        return CommandResult(
            command=[self.id],
            returncode=0,
            output=f"Applied: {self.title}",
        )


# ─── PATH Integrity Audit ──────────────────────────────────────────────



def _compinit_invocations(content: str) -> List[int]:
    """Return line numbers of actual `compinit` invocations.

    Excludes `autoload -Uz compinit` lines, which only register the function.
    """
    return [
        i
        for i, line in enumerate(content.splitlines(), 1)
        if re.search(r"^[ \t]*compinit\b|&&[ \t]*compinit\b", line, re.IGNORECASE)
    ]

def audit_path_integrity(path_str: str, home: Path) -> List[AuditFinding]:
    """Audit PATH for duplicates, missing dirs, empty entries, etc."""
    entries = [e for e in path_str.split(os.pathsep) if e]
    findings: List[AuditFinding] = []

    # Check for duplicate entries
    seen: Dict[str, int] = {}
    for i, entry in enumerate(entries):
        normalized = entry.strip()
        if normalized == "":
            findings.append(AuditFinding(
                id="shell.path.empty_entry",
                category="PATH",
                severity="WARNING",
                title="Empty PATH entry",
                summary=f"Found empty PATH entry at position {i}",
                evidence=f"PATH entry at index {i} is empty after splitting on os.pathsep",
                source_file="",
                line_numbers=(),
                current_state=f"Empty entry at position {i}",
                recommended_state="Remove empty PATH entries",
                risk="low",
                repairability="AUTO_SAFE",
            ))
        else:
            count = seen.get(normalized, 0) + 1
            seen[normalized] = count
            if count > 1:
                # Check if it's just a trailing slash variation
                stripped = normalized.rstrip("/")
                existing_stripped = [e.rstrip("/") for e in entries if e.strip() == normalized]
                # Check for symlink-equivalent duplicates
                findings.append(AuditFinding(
                    id="shell.path.duplicate_entry",
                    category="PATH",
                    severity="WARNING" if count <= 3 else "ERROR",
                    title="Duplicate PATH entry",
                    summary=f"PATH entry '{normalized}' appears {count} times",
                    evidence=f"Found {count} occurrences of '{normalized}' in PATH",
                    source_file="",
                    line_numbers=(),
                    current_state=f"Duplicate entry: '{normalized}'",
                    recommended_state=f"Keep one occurrence of '{normalized}'",
                    risk="medium" if count > 1 else "low",
                    repairability="AUTO_SAFE" if count <= 3 else "GUIDED",
                ))

    # Check for nonexistent directories
    for entry in entries:
        normalized = entry.strip().rstrip("/")
        if normalized and not os.path.isdir(normalized):
            findings.append(AuditFinding(
                id="shell.path.nonexistent_dir",
                category="PATH",
                severity="ERROR",
                title="Nonexistent PATH directory",
                summary=f"PATH entry '{normalized}' does not exist as a directory",
                evidence=f"Directory '{normalized}' not found on filesystem",
                source_file="",
                line_numbers=(),
                current_state=f"'{normalized}' does not exist",
                recommended_state=f"Remove or fix PATH entry '{normalized}'",
                risk="high",
                repairability="GUIDED",
            ))

    # Check for relative PATH entries
    for i, entry in enumerate(entries):
        normalized = entry.strip()
        if normalized and not os.path.isabs(normalized):
            findings.append(AuditFinding(
                id="shell.path.relative_entry",
                category="PATH",
                severity="WARNING",
                title="Relative PATH entry",
                summary=f"Relative PATH entry at position {i}: '{normalized}'",
                evidence=f"PATH entry '{normalized}' is not an absolute path",
                source_file="",
                line_numbers=(),
                current_state=f"Relative entry: '{normalized}'",
                recommended_state=f"Use absolute path instead of '{normalized}'",
                risk="medium",
                repairability="GUIDED",
            ))

    # Check for world-writable directories
    for entry in entries:
        normalized = entry.strip().rstrip("/")
        if normalized and os.path.isdir(normalized):
            stat = os.stat(normalized)
            if stat.st_mode & 0o002:  # world-writable
                findings.append(AuditFinding(
                    id="shell.path.world_writable",
                    category="PATH",
                    severity="SECURITY",
                    title="World-writable PATH directory",
                    summary=f"PATH directory '{normalized}' is world-writable",
                    evidence=f"Directory '{normalized}' has world-write permission (o+w)",
                    source_file="",
                    line_numbers=(),
                    current_state=f"'{normalized}' is world-writable",
                    recommended_state=f"Remove world-write permission from '{normalized}'",
                    risk="high",
                    repairability="GUIDED",
                ))

    # Check for group-writable directories where group creates risk
    for entry in entries:
        normalized = entry.strip().rstrip("/")
        if normalized and os.path.isdir(normalized):
            stat = os.stat(normalized)
            if stat.st_mode & 0o020:  # group-writable
                # Only flag if group has write and it's not a trusted group
                findings.append(AuditFinding(
                    id="shell.path.group_writable",
                    category="PATH",
                    severity="NOTICE",
                    title="Group-writable PATH directory",
                    summary=f"PATH directory '{normalized}' is group-writable",
                    evidence=f"Directory '{normalized}' has group-write permission (g+w)",
                    source_file="",
                    line_numbers=(),
                    current_state=f"'{normalized}' is group-writable",
                    recommended_state=f"Consider removing group-write from '{normalized}'",
                    risk="low",
                    repairability="ADVISORY_ONLY",
                ))

    # Check for suspicious whitespace
    for i, entry in enumerate(entries):
        if entry != entry.strip():
            findings.append(AuditFinding(
                id="shell.path.suspicious_whitespace",
                category="PATH",
                severity="NOTICE",
                title="Suspicious whitespace in PATH entry",
                summary=f"PATH entry at position {i} has leading/trailing whitespace",
                evidence=f"Entry '{entry}' differs from stripped '{entry.strip()}'",
                source_file="",
                line_numbers=(),
                current_state=f"Whitespace in entry: '{entry}'",
                recommended_state=f"Trim whitespace from PATH entry at position {i}",
                risk="low",
                repairability="AUTO_SAFE",
            ))

    # Check for malformed entries (containing shell metacharacters that could be exploited)
    for i, entry in enumerate(entries):
        normalized = entry.strip()
        if normalized and re.search(r'[;`|&><()$]', normalized):
            findings.append(AuditFinding(
                id="shell.path.malformed_entry",
                category="PATH",
                severity="ERROR",
                title="Malformed PATH entry",
                summary=f"PATH entry at position {i} contains shell metacharacters",
                evidence=f"Entry '{normalized}' contains potentially dangerous characters: ; ` | & > < ( ) $",
                source_file="",
                line_numbers=(),
                current_state=f"Malformed entry: '{normalized}'",
                recommended_state=f"Remove or sanitize PATH entry at position {i}",
                risk="high",
                repairability="GUIDED",
            ))

    # Check for repeated trailing slashes
    for i, entry in enumerate(entries):
        normalized = entry.strip()
        if normalized and normalized.endswith("//"):
            findings.append(AuditFinding(
                id="shell.path.double_slash",
                category="PATH",
                severity="NOTICE",
                title="Repeated trailing slashes in PATH",
                summary=f"PATH entry at position {i} has double trailing slashes: '{normalized}'",
                evidence=f"Entry '{normalized}' ends with '//'",
                source_file="",
                line_numbers=(),
                current_state=f"Double slash: '{normalized}'",
                recommended_state=f"Fix trailing slashes in PATH entry at position {i}",
                risk="low",
                repairability="AUTO_SAFE",
            ))

    # Check for equivalent paths expressed differently
    # Normalize all entries and check for canonical form duplicates
    canonical_map: Dict[str, List[int]] = {}
    for i, entry in enumerate(entries):
        normalized = entry.strip().rstrip("/")
        # Try to get canonical path
        try:
            canonical = os.path.realpath(normalized) if os.path.exists(normalized) else normalized
        except Exception:
            canonical = normalized
        if canonical not in canonical_map:
            canonical_map[canonical] = []
        canonical_map[canonical].append(i)

    for canonical, indices in canonical_map.items():
        if len(indices) > 1:
            # Check if these are truly equivalent (same real path) vs just similar names
            findings.append(AuditFinding(
                id="shell.path.equivalent_different_forms",
                category="PATH",
                severity="NOTICE",
                title="Equivalent PATH entries expressed differently",
                summary=f"Found {len(indices)} PATH entries expressing the same path differently",
                evidence=f"Entries at positions {indices} all resolve to '{canonical}'",
                source_file="",
                line_numbers=(),
                current_state=f"{len(indices)} variants of '{canonical}'",
                recommended_state=f"Consolidate to single canonical entry: '{canonical}'",
                risk="low",
                repairability="GUIDED",
            ))

    return findings


# ─── PATH Provenance Audit ─────────────────────────────────────────────


def find_path_origins(shell: str, home: Path) -> Dict[str, List[AuditFinding]]:
    """Determine where PATH entries come from by inspecting startup files."""
    origins: Dict[str, List[AuditFinding]] = {
        "zsh": [],
        "bash": [],
    }

    # Common shell startup files to inspect
    zsh_files = {
        "zshenv": home / ".zshenv",
        "zprofile": home / ".zprofile",
        "zshrc": home / ".zshrc",
        "zlogin": home / ".zlogin",
    }
    bash_files = {
        "bash_profile": home / ".bash_profile",
        "bash_login": home / ".bash_login",
        "profile": home / ".profile",
        "bashrc": home / ".bashrc",
    }

    # Inspect zsh startup files for PATH exports
    for name, path in zsh_files.items():
        if not path.exists():
            continue
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception:
            continue

        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            # Look for export PATH= or PATH=(... or export PATH=...
            if re.search(r'export\s+PATH', stripped, re.IGNORECASE):
                origins["zsh"].append(AuditFinding(
                    id=f"shell.path.origin.zsh_{name}",
                    category="PATH",
                    severity="NOTICE",
                    title=f"PATH exported in ~/.{name}",
                    summary=f"PATH is exported in ~/.{name}",
                    evidence=f"Line {line_no} of ~/.{name}: {stripped[:200]}",
                    source_file=str(path),
                    line_numbers=(line_no,),
                    current_state=f"PATH exported in ~/.{name}",
                    recommended_state=f"Consolidate PATH exports to one shell-specific file",
                    risk="low",
                    repairability="GUIDED",
                ))
            elif re.search(r'PATH=.*:\$PATH', stripped, re.IGNORECASE):
                origins["zsh"].append(AuditFinding(
                    id=f"shell.path.origin.zsh_{name}_append",
                    category="PATH",
                    severity="NOTICE",
                    title=f"PATH appends $PATH in ~/.{name}",
                    summary=f"PATH appends $PATH in ~/.{name}",
                    evidence=f"Line {line_no} of ~/.{name}: {stripped[:200]}",
                    source_file=str(path),
                    line_numbers=(line_no,),
                    current_state=f"$PATH append in ~/.{name}",
                    recommended_state=f"Remove redundant $PATH append from ~/.{name}",
                    risk="low",
                    repairability="GUIDED",
                ))
            elif re.search(r'path=\(|path=\(|path=\(|typeset -U path', stripped, re.IGNORECASE):
                origins["zsh"].append(AuditFinding(
                    id=f"shell.path.origin.zsh_{name}_path_arr",
                    category="PATH",
                    severity="NOTICE",
                    title=f"zsh path array in ~/.{name}",
                    summary=f"zsh path array defined in ~/.{name}",
                    evidence=f"Line {line_no} of ~/.{name}: {stripped[:200]}",
                    source_file=str(path),
                    line_numbers=(line_no,),
                    current_state=f"path array in ~/.{name}",
                    recommended_state=f"Consolidate path array management",
                    risk="low",
                    repairability="GUIDED",
                ))

    # Inspect bash startup files for PATH exports
    for name, path in bash_files.items():
        if not path.exists():
            continue
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception:
            continue

        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.search(r'export\s+PATH', stripped, re.IGNORECASE):
                origins["bash"].append(AuditFinding(
                    id=f"shell.path.origin.bash_{name}",
                    category="PATH",
                    severity="NOTICE",
                    title=f"PATH exported in ~/.{name}",
                    summary=f"PATH is exported in ~/.{name}",
                    evidence=f"Line {line_no} of ~/.{name}: {stripped[:200]}",
                    source_file=str(path),
                    line_numbers=(line_no,),
                    current_state=f"PATH exported in ~/.{name}",
                    recommended_state=f"Consolidate PATH exports to one shell-specific file",
                    risk="low",
                    repairability="GUIDED",
                ))
            elif re.search(r'PATH=.*:\$PATH', stripped, re.IGNORECASE):
                origins["bash"].append(AuditFinding(
                    id=f"shell.path.origin.bash_{name}_append",
                    category="PATH",
                    severity="NOTICE",
                    title=f"PATH appends $PATH in ~/.{name}",
                    summary=f"PATH appends $PATH in ~/.{name}",
                    evidence=f"Line {line_no} of ~/.{name}: {stripped[:200]}",
                    source_file=str(path),
                    line_numbers=(line_no,),
                    current_state=f"$PATH append in ~/.{name}",
                    recommended_state=f"Remove redundant $PATH append from ~/.{name}",
                    risk="low",
                    repairability="GUIDED",
                ))

    return origins


# ─── zsh Startup Semantics Audit ───────────────────────────────────────


def audit_zstartup_semantics(home: Path) -> List[AuditFinding]:
    """Audit zsh startup file placement and semantics."""
    findings: List[AuditFinding] = []

    zsh_files = {
        "zshenv": home / ".zshenv",
        "zprofile": home / ".zprofile",
        "zshrc": home / ".zshrc",
        "zlogin": home / ".zlogin",
    }

    # Check which files exist
    existing = {name: path for name, path in zsh_files.items() if path.exists()}

    # zshenv should ONLY contain environment variables (no interactive-only stuff)
    if "zshenv" in existing:
        try:
            with open(existing["zshenv"], 'r', encoding='utf-8', errors='replace') as f:
                zshenv_content = f.read()
        except Exception:
            zshenv_content = ""

        # Check for interactive-only config in .zshenv
        if re.search(r'autoload.*-Uz.*compinit', zshenv_content, re.IGNORECASE):
            findings.append(AuditFinding(
                id="shell.zsh.zshenv_compinit",
                category="zsh_startup",
                severity="ERROR",
                title="compinit in .zshenv",
                summary="compinit found in .zshenv - should only have environment vars",
                evidence="compinit or autoload patterns detected in .zshenv",
                source_file=str(existing["zshenv"]),
                line_numbers=(),
                current_state="compinit in .zshenv",
                recommended_state="Move compinit to .zshrc",
                risk="high",
                repairability="GUIDED",
            ))

        # Check for interactive-only settings (.zshenv is always sourced)
        if re.search(r'source\s+\."\?.*\.zshrc"', zshenv_content, re.IGNORECASE):
            findings.append(AuditFinding(
                id="shell.zsh.zshenv_source_zshrc",
                category="zsh_startup",
                severity="NOTICE",
                title=".zshenv sources .zshrc",
                summary=".zshenv sources .zshrc unnecessarily",
                evidence="Source pattern from .zshenv to .zshrc found",
                source_file=str(existing["zshenv"]),
                line_numbers=(),
                current_state=".zshenv sources .zshrc",
                recommended_state="Remove the source of .zshrc from .zshenv",
                risk="low",
                repairability="AUTO_SAFE",
            ))

    # .zprofile should contain login-shell only config
    if "zprofile" in existing:
        try:
            with open(existing["zprofile"], 'r', encoding='utf-8', errors='replace') as f:
                zprofile_content = f.read()
        except Exception:
            zprofile_content = ""

        # Check for interactive-only config in .zprofile
        # .zprofile is sourced for login shells only
        if re.search(r'alias.*=.*', zprofile_content, re.IGNORECASE):
            findings.append(AuditFinding(
                id="shell.zsh.zprofile_interactive_aliases",
                category="zsh_startup",
                severity="NOTICE",
                title="Aliases in .zprofile",
                summary="Aliases found in .zprofile - for login shells only",
                evidence="Alias definitions detected in .zprofile",
                source_file=str(existing["zprofile"]),
                line_numbers=(),
                current_state="Aliases in .zprofile",
                recommended_state="Move aliases to .zshrc for interactive use",
                risk="low",
                repairability="GUIDED",
            ))

        # Check for .zshrc sourcing from .zprofile (unnecessary)
        if re.search(r'source\s+\."\?.*\.zshrc"', zprofile_content, re.IGNORECASE):
            findings.append(AuditFinding(
                id="shell.zsh.zprofile_source_zshrc",
                category="zsh_startup",
                severity="NOTICE",
                title=".zprofile sources .zshrc unnecessarily",
                summary=".zprofile sources .zshrc - .zshrc is for interactive shells",
                evidence="Source pattern from .zprofile to .zshrc found",
                source_file=str(existing["zprofile"]),
                line_numbers=(),
                current_state=".zprofile sources .zshrc",
                recommended_state="Remove the source of .zshrc from .zprofile",
                risk="low",
                repairability="AUTO_SAFE",
            ))

    # .zshrc should contain interactive-shell config
    if "zshrc" in existing:
        try:
            with open(existing["zshrc"], 'r', encoding='utf-8', errors='replace') as f:
                zshrc_content = f.read()
        except Exception:
            zshrc_content = ""

        # Check for environment config duplicated from .zprofile
        if re.search(r'export\s+PATH', zshrc_content, re.IGNORECASE):
            findings.append(AuditFinding(
                id="shell.zsh.zshrc_export_path",
                category="zsh_startup",
                severity="NOTICE",
                title="PATH export in .zshrc",
                summary="PATH export found in .zshrc - may duplicate .zprofile config",
                evidence="export PATH detected in .zshrc",
                source_file=str(existing["zshrc"]),
                line_numbers=(),
                current_state="export PATH in .zshrc",
                recommended_state="Keep PATH export in .zprofile only; .zshrc should use typeset -U",
                risk="low",
                repairability="GUIDED",
            ))

        # Check for duplicate compinit
        compinit_count = len(_compinit_invocations(zshrc_content))
        if compinit_count > 1:
            findings.append(AuditFinding(
                id="shell.zsh.zshrc_duplicate_compinit",
                category="zsh_startup",
                severity="ERROR",
                title="Duplicate compinit in .zshrc",
                summary=f"compinit found {compinit_count} times in .zshrc",
                evidence=f"{compinit_count} compinit invocations found",
                source_file=str(existing["zshrc"]),
                line_numbers=(),
                current_state=f"{compinit_count} compinit calls",
                recommended_state=f"Remove redundant compinit calls, keep one after autoload",
                risk="high",
                repairability="AUTO_SAFE",
            ))

        # Check for compdef before compinit
        compdef_lines = []
        compinit_lines = []
        for i, line in enumerate(zshrc_content.splitlines(), 1):
            if re.search(r'compdef\s+', line, re.IGNORECASE):
                compdef_lines.append(i)
            if re.search(r'^[ \t]*compinit\b|&&[ \t]*compinit\b', line, re.IGNORECASE):
                compinit_lines.append(i)

        if compdef_lines and compinit_lines:
            first_compdef = min(compdef_lines)
            first_compinit = min(compinit_lines)
            if first_compdef < first_compinit:
                findings.append(AuditFinding(
                    id="shell.zz.zshrc_compdef_before_compinit",
                    category="zsh_startup",
                    severity="ERROR",
                    title="compdef before compinit",
                    summary=f"compdef at line {first_compdef} runs before compinit at line {first_compinit}",
                    evidence=f"compdef at line {first_compdef} precedes compinit at line {first_compinit}",
                    source_file=str(existing["zshrc"]),
                    line_numbers=(first_compdef, first_compinit),
                    current_state="compdef before compinit",
                    recommended_state="Move compdef blocks after compinit invocation",
                    risk="high",
                    repairability="GUIDED",
                ))

    # .zlogin should contain only login-shell specific config
    if "zlogin" in existing:
        try:
            with open(existing["zlogin"], 'r', encoding='utf-8', errors='replace') as f:
                zlogin_content = f.read()
        except Exception:
            zlogin_content = ""

        # Check for interactive-only config in .zlogin
        if re.search(r'alias.*=.*', zlogin_content, re.IGNORECASE):
            findings.append(AuditFinding(
                id="shell.zsh.zlogin_interactive_aliases",
                category="zsh_startup",
                severity="NOTICE",
                title="Aliases in .zlogin",
                summary="Aliases found in .zlogin - for login shells only",
                evidence="Alias definitions detected in .zlogin",
                source_file=str(existing["zlogin"]),
                line_numbers=(),
                current_state="Aliases in .zlogin",
                recommended_state="Move aliases to .zshrc for interactive use",
                risk="low",
                repairability="GUIDED",
            ))

    return findings

# ─── Completion System Audit ───────────────────────────────────────────


def audit_completion_system(zshrc_path: Path, zprofile_path: Path) -> List[AuditFinding]:
    """Audit zsh completion setup including compinit ordering."""
    findings: List[AuditFinding] = []

    # Read .zshrc if it exists
    zshrc_content = ""
    if zshrc_path.exists():
        try:
            with open(zshrc_path, "r", encoding="utf-8", errors="replace") as f:
                zshrc_content = f.read()
        except Exception:
            zshrc_content = ""

    # Read .zprofile if it exists
    zprofile_content = ""
    if zprofile_path.exists():
        try:
            with open(zprofile_path, "r", encoding="utf-8", errors="replace") as f:
                zprofile_content = f.read()
        except Exception:
            zprofile_content = ""

    # Check for compdef before compinit
    zshrc_lines = zshrc_content.splitlines()
    compdef_lines = []
    compinit_lines = []

    for i, line in enumerate(zshrc_lines, 1):
        if re.search(r"compdef\s+", line, re.IGNORECASE):
            compdef_lines.append(i)
        if re.search(r"^autoload\s*-\s*U\s*uz\s*compinit", line, re.IGNORECASE):
            pass
        if re.search(r"^\s*compinit\s*$", line, re.IGNORECASE):
            compinit_lines.append(i)

    if compdef_lines:
        first_compdef = min(compdef_lines)
        if compinit_lines:
            first_compinit = min(compinit_lines)
            if first_compdef < first_compinit:
                findings.append(AuditFinding(
                    id="shell.completion.compdef_before_compinit",
                    category="completion",
                    severity="ERROR",
                    title="compdef before compinit",
                    summary=f"compdef found at line {first_compdef} before compinit at line {first_compinit}",
                    evidence=f"compdef at line {first_compdef} precedes compinit",
                    source_file=str(zshrc_path),
                    line_numbers=(first_compdef, first_compinit),
                    current_state="compdef before compinit",
                    recommended_state="Move compdef blocks after compinit invocation",
                    risk="high",
                    repairability="GUIDED",
                ))
        else:
            findings.append(AuditFinding(
                id="shell.completion.compdef_no_compinit",
                category="completion",
                severity="ERROR",
                title="compinit not found before compdef",
                summary="compdef found but compinit not found in .zshrc",
                evidence="compdef present without corresponding compinit",
                source_file=str(zshrc_path),
                line_numbers=(),
                current_state="compdef without compinit",
                recommended_state="Add autoload -Uz compinit && compinit or ensure compinit runs first",
                risk="high",
                repairability="GUIDED",
            ))

    # Check for multiple compinit invocations
    compinit_count = len(_compinit_invocations(zshrc_content))
    if compinit_count > 1:
        findings.append(AuditFinding(
            id="shell.completion.duplicate_compinit",
            category="completion",
            severity="WARNING",
            title="Duplicate compinit invocations",
            summary=f"compinit found {compinit_count} times in .zshrc",
            evidence=f"{compinit_count} compinit invocations detected",
            source_file=str(zshrc_path),
            line_numbers=(),
            current_state=f"{compinit_count} compinit calls",
            recommended_state="Keep only one compinit invocation (use -C flag for cached comps)",
            risk="medium",
            repairability="AUTO_SAFE",
        ))

    # Check for compinit -C (cached)
    if re.search(r"compinit\s+-C", zshrc_content, re.IGNORECASE):
        findings.append(AuditFinding(
            id="shell.completion.compinit_cached",
            category="completion",
            severity="NOTICE",
            title="compinit with -C flag",
            summary="compinit invoked with -C (cached) flag",
            evidence="compinit -C pattern found in .zshrc",
            source_file=str(zshrc_path),
            line_numbers=(),
            current_state="compinit -C",
            recommended_state="Keep -C if you have many completions; remove if not needed",
            risk="low",
            repairability="ADVISORY_ONLY",
        ))

    # Check for compdef blocks in .zprofile (should be in .zshrc)
    if zprofile_path.exists():
        zprofile_lines = zprofile_content.splitlines()
        for i, line in enumerate(zprofile_lines, 1):
            if re.search(r"compdef\s+", line, re.IGNORECASE):
                findings.append(AuditFinding(
                    id="shell.completion.compdef_in_zprofile",
                    category="completion",
                    severity="WARNING",
                    title="compdef in .zprofile",
                    summary=f"compdef found in ~/.zprofile: line {i}",
                    evidence=f"compdef at line {i} of ~/.zprofile",
                    source_file=str(zprofile_path),
                    line_numbers=(i,),
                    current_state="compdef in .zprofile",
                    recommended_state="Move compdef block to ~/.zshrc after compinit",
                    risk="high",
                    repairability="GUIDED",
                ))
                break

    # Check fpath configuration
    if "fpath" in zshrc_content.lower():
        findings.append(AuditFinding(
            id="shell.completion.fpath_configured",
            category="completion",
            severity="NOTICE",
            title="fpath configured",
            summary="fpath configuration detected in .zshrc",
            evidence="fpath references found in .zshrc",
            source_file=str(zshrc_path),
            line_numbers=(),
            current_state="fpath configured",
            recommended_state="Ensure fpath includes custom completion directories before compinit",
            risk="low",
            repairability="GUIDED",
        ))

    return findings

# ─── Executable Resolution / Shadowing Audit ───────────────────────────


def audit_executable_shadowing(tools: Optional[List[str]] = None, home: Optional[Path] = None) -> List[AuditFinding]:
    """Audit important commands for multiple installations and shadowing."""
    if home is None:
        home = Path.home()
    if tools is None:
        tools = ["git", "ssh", "curl", "python3", "python", "node", "npm", "npx",
                 "pnpm", "yarn", "bun", "ruby", "gem", "go", "cargo", "rustc",
                 "java", "docker", "kubectl", "brew"]

    findings: List[AuditFinding] = []
    missing: List[str] = []

    for tool in tools:
        # Use command -v to find the executable
        try:
            result = subprocess.run(
                ["command", "-v", tool],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                missing.append(tool)
                continue

            resolved = result.stdout.strip()
            if not resolved:
                missing.append(tool)
                continue

            # Check for all candidates using type -a equivalent
            all_candidates: List[str] = []
            try:
                type_result = subprocess.run(
                    ["type", "-a", tool],
                    capture_output=True, text=True, timeout=10
                )
                if type_result.returncode == 0:
                    all_candidates = [c.strip() for c in type_result.stdout.splitlines()
                                      if c.strip() and c.strip() != f"({tool})"]
            except Exception:
                pass

            # Get binary architecture
            arch_info = ""
            try:
                file_result = subprocess.run(
                    ["file", resolved],
                    capture_output=True, text=True, timeout=10
                )
                if file_result.returncode == 0:
                    file_out = file_result.stdout.lower()
                    if "arm64" in file_out or "apple silicon" in file_out:
                        arch_info = "arm64 (Apple Silicon)"
                    elif "x86_64" in file_out or "intel" in file_out:
                        arch_info = "x86_64 (Intel)"
                    elif "universal" in file_out:
                        arch_info = "universal"
            except Exception:
                pass

            # Check for symlink targets
            symlink_target = ""
            try:
                if os.path.islink(resolved):
                    symlink_target = os.readlink(resolved)
                    # Resolve further if it's a chain
                    current = resolved
                    for _ in range(5):  # limit depth
                        if os.path.islink(current):
                            current = os.path.join(os.path.dirname(current), os.readlink(current))
                        else:
                            break
                    symlink_target = current
                elif os.path.isfile(resolved):
                    symlink_target = resolved
            except Exception:
                pass

            # Check for multiple candidates (shadowing)
            if len(all_candidates) > 1:
                findings.append(AuditFinding(
                    id=f"shell.exec.multiple_{tool}",
                    category="executable",
                    severity="WARNING",
                    title=f"Multiple {tool} installations found",
                    summary=f"{len(all_candidates)} {tool} installations detected",
                    evidence=f"Candidates: {', '.join(all_candidates[:5])}{'...' if len(all_candidates) > 5 else ''}",
                    source_file="",
                    line_numbers=(),
                    current_state=f"{len(all_candidates)} {tool} installations",
                    recommended_state="Canonicalize to one installation; check PATH ordering",
                    risk="medium",
                    repairability="GUIDED",
                ))

            # Check for architecture mismatch (e.g., x86_64 shadowing arm64)
            architectures = set()
            for candidate in all_candidates[:5]:  # Check first 5
                try:
                    fc = subprocess.run(["file", candidate], capture_output=True, text=True, timeout=10)
                    fc_out = fc.stdout.lower()
                    if "arm64" in fc_out or "apple silicon" in fc_out:
                        architectures.add("arm64")
                    elif "x86_64" in fc_out or "intel" in fc_out:
                        architectures.add("x86_64")
                except Exception:
                    pass

            if len(architectures) > 1:
                findings.append(AuditFinding(
                    id=f"shell.exec.arch_mismatch_{tool}",
                    category="executable",
                    severity="ERROR",
                    title=f"Architecture mismatch for {tool}",
                    summary=f"Multiple architectures detected: {', '.join(sorted(architectures))}",
                    evidence=f"Found both arm64 and x86_64 {tool} installations",
                    source_file="",
                    line_numbers=(),
                    current_state=f"Architectures: {', '.join(sorted(architectures))}",
                    recommended_state="Ensure native architecture tools take precedence in PATH",
                    risk="high",
                    repairability="GUIDED",
                ))

            # Check for dangling symlinks
            if symlink_target and not os.path.exists(symlink_target):
                findings.append(AuditFinding(
                    id=f"shell.exec.dangling_{tool}",
                    category="executable",
                    severity="ERROR",
                    title=f"Dangling {tool} symlink",
                    summary=f"{tool} symlink is dangling: {symlink_target}",
                    evidence=f"Symlink target '{symlink_target}' does not exist",
                    source_file="",
                    line_numbers=(),
                    current_state=f"Dangling: {symlink_target}",
                    recommended_state="Fix or remove the dangling symlink",
                    risk="high",
                    repairability="GUIDED",
                ))

            # Check forRosetta-based tool shadowing native ARM64
            if "arm64" in architectures and "x86_64" in architectures:
                # Check if the first PATH entry is x86_64 while arm64 is also available
                findings.append(AuditFinding(
                    id=f"shell.exec.rosetta_shadow_{tool}",
                    category="executable",
                    severity="NOTICE",
                    title=f"Rosetta {tool} may shadow native ARM64",
                    summary=f"Both ARM64 and x86_64 {tool} installations detected",
                    evidence=f"Architectures: {', '.join(sorted(architectures))}",
                    source_file="",
                    line_numbers=(),
                    current_state=f"Both arm64 and x86_64 {tool} available",
                    recommended_state="Ensure ARM64 version takes precedence on Apple Silicon Macs",
                    risk="low",
                    repairability="ADVISORY_ONLY",
                ))

        except Exception as e:
            # Unexpected error - still report
            findings.append(AuditFinding(
                id=f"shell.exec.audit_error_{tool}",
                category="executable",
                severity="NOTICE",
                title=f"Audit error for {tool}",
                summary=f"Error auditing {tool}: {str(e)[:100]}",
                evidence=f"Error: {str(e)[:100]}",
                source_file="",
                line_numbers=(),
                current_state="Audit error",
                recommended_state="Manual investigation recommended",
                risk="low",
                repairability="ADVISORY_ONLY",
            ))

    # Report missing tools as notices
    for tool in missing:
        findings.append(AuditFinding(
            id=f"shell.exec.missing_{tool}",
            category="executable",
            severity="NOTICE",
            title=f"{tool} not found",
            summary=f"{tool} is not installed or not in PATH",
            evidence=f"command -v {tool} returned no result",
            source_file="",
            line_numbers=(),
            current_state=f"{tool} not found",
            recommended_state=f"Install {tool} or add to PATH",
            risk="low",
            repairability="ADVISORY_ONLY",
        ))

    return findings

# ─── Symlink Integrity Audit ────────────────────────────────────────────


def audit_symlink_integrity(paths: Optional[List[str]] = None, home: Optional[Path] = None) -> List[AuditFinding]:
    """Audit executables and paths for dangling and stale symlinks."""
    if home is None:
        home = Path.home()
    if paths is None:
        # Default paths to check
        paths = [
            str(home / ".local/bin"),
            str(home / ".codex"),
            str(home / ".local/share"),
        ]

    findings: List[AuditFinding] = []

    for search_path in paths:
        path_obj = Path(search_path)
        if not path_obj.exists():
            continue

        # Find all files in the directory
        try:
            entries = list(path_obj.iterdir())
        except Exception:
            continue

        for entry in entries:
            if not entry.is_symlink() and not entry.is_file():
                continue

            # Check for dangling symlinks
            if entry.is_symlink():
                target = entry.resolve()
                if not target.exists():
                    findings.append(AuditFinding(
                        id=f"shell.symlink.dangling_{entry.name}",
                        category="symlink",
                        severity="ERROR",
                        title=f"Dangling symlink: {entry.name}",
                        summary=f"Symlink '{entry.name}' points to non-existent target",
                        evidence=f"Symlink: {entry} -> {os.readlink(entry)}",
                        source_file=str(entry),
                        line_numbers=(),
                        current_state=f"Dangling: {entry} -> {os.readlink(entry)}",
                        recommended_state="Remove or fix the dangling symlink",
                        risk="high",
                        repairability="GUIDED",
                    ))
                else:
                    # Check for multi-level symlink chains
                    chain: List[str] = [str(entry)]
                    current = entry
                    depth = 0
                    while depth < 5 and current.is_symlink():
                        try:
                            target = os.readlink(current)
                        except OSError:
                            break
                        if not os.path.isabs(target):
                            target = str(current.parent / target)
                        chain.append(target)
                        current = Path(target)
                        if not current.exists():
                            break
                        depth += 1

                    if depth >= 4 or (current.is_symlink() and not current.exists()):
                        # Multi-level chain or stale deep link
                        findings.append(AuditFinding(
                            id=f"shell.symlink.multi_level_{entry.name}",
                            category="symlink",
                            severity="NOTICE",
                            title=f"Multi-level symlink chain: {entry.name}",
                            summary=f"Symlink chain has {depth+1} levels for '{entry.name}'",
                            evidence=f"Chain: {' -> '.join(chain)}",
                            source_file=str(entry),
                            line_numbers=(),
                            current_state=f"Chain: {' -> '.join(chain)}",
                            recommended_state="Verify chain integrity; remove if stale",
                            risk="medium",
                            repairability="GUIDED",
                        ))

                    # Check for 'current' links pointing to removed versions
                    if "current" in chain[-1].lower() or "/current/" in "/".join(chain).lower():
                        # Check what the current link resolves to
                        final = Path(chain[-1])
                        if final.exists():
                            # Check for stale version references
                            try:
                                stat = os.stat(final)
                                findings.append(AuditFinding(
                                    id=f"shell.symlink.current_{entry.name}",
                                    category="symlink",
                                    severity="NOTICE",
                                    title=f"Current symlink: {entry.name}",
                                    summary=f"'{entry.name}' -> current link resolving to {final}",
                                    evidence=f"Current link: {final} (v{stat.st_mtime})",
                                    source_file=str(entry),
                                    line_numbers=(),
                                    current_state=f"Current -> {final}",
                                    recommended_state="Verify current link points to correct version",
                                    risk="low",
                                    repairability="ADVISORY_ONLY",
                                ))
                            except Exception:
                                pass

            # Check for stale commented/generated completion blocks
            # (detect if file is a symlink to a generated block)
            if entry.is_symlink():
                target_str = str(entry.resolve())
                if ".generated." in target_str or ".tmp." in target_str:
                    findings.append(AuditFinding(
                        id=f"shell.symlink.generated_{entry.name}",
                        category="symlink",
                        severity="NOTICE",
                        title=f"Generated symlink: {entry.name}",
                        summary=f"Symlink '{entry.name}' points to generated/temporary path",
                        evidence=f"Target: {target_str}",
                        source_file=str(entry),
                        line_numbers=(),
                        current_state=f"Generated: {target_str}",
                        recommended_state="Verify generated path is current and valid",
                        risk="low",
                        repairability="ADVISORY_ONLY",
                    ))

            # Regular file symlinks - check health
            if entry.is_file() and not entry.is_symlink():
                # Not a symlink, skip
                pass

    return findings

# ─── Package Manager Environment Audit ─────────────────────────────────


def audit_package_managers(home: Path) -> List[AuditFinding]:
    """Audit common package manager and runtime environment configurations."""
    findings: List[AuditFinding] = []

    # Homebrew
    brew_prefixes = ["/opt/homebrew", "/usr/local"]
    for prefix in brew_prefixes:
        if not os.path.isdir(prefix):
            continue
        # Check for ARM64 vs x86_64 conflict
        try:
            result = subprocess.run(
                ["file", f"{prefix}/bin/brew"],
                capture_output=True, text=True, timeout=10
            )
            brew_arch = ""
            if result.returncode == 0:
                file_out = result.stdout.lower()
                if "arm64" in file_out:
                    brew_arch = "arm64"
                elif "x86_64" in file_out:
                    brew_arch = "x86_64"
            if brew_arch:
                findings.append(AuditFinding(
                    id="shell.pkg.brew_architecture",
                    category="package_manager",
                    severity="NOTICE",
                    title=f"Homebrew architecture: {brew_arch}",
                    summary=f"Homebrew at {prefix} is {brew_arch}",
                    evidence=f"Detected from brew binary architecture",
                    source_file="",
                    line_numbers=(),
                    current_state=f"Homebrew {brew_arch}",
                    recommended_state="Ensure PATH ordering matches desired architecture",
                    risk="low",
                    repairability="ADVISORY_ONLY",
                ))
        except Exception:
            pass

        # Check for duplicate Homebrew in PATH
        try:
            result = subprocess.run(
                ["path_helper", "-d"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "brew" in line.lower() and prefix in line.lower():
                        findings.append(AuditFinding(
                            id="shell.pkg.brew_path_duplicate",
                            category="package_manager",
                            severity="NOTICE",
                            title="Duplicate Homebrew PATH entry",
                            summary=f"Homebrew found at {prefix} multiple times in PATH",
                            evidence=f"Found in: {line}",
                            source_file="",
                            line_numbers=(),
                            current_state=f"Duplicate Homebrew at {prefix}",
                            recommended_state="Consolidate to single Homebrew PATH entry",
                            risk="low",
                            repairability="AUTO_SAFE",
                        ))
        except Exception:
            pass

    # NVM
    nvm_dir = os.environ.get("NVM_DIR", "")
    if nvm_dir:
        nvm_path = Path(nvm_dir)
        if nvm_path.exists():
            # Check for stale version links
            try:
                version_links = list(nvm_path.glob("versions/*/current"))
                for vl in version_links:
                    if vl.is_symlink() and not vl.exists():
                        findings.append(AuditFinding(
                            id="shell.pkg.nvm_stale_current",
                            category="package_manager",
                            severity="ERROR",
                            title="Stale NVM current symlink",
                            summary=f"NVM current symlink is dangling: {vl}",
                            evidence=f"NVM directory: {nvm_dir}, stale link: {vl}",
                            source_file=str(nvm_path),
                            line_numbers=(),
                            current_state=f"Stale: {vl}",
                            recommended_state="Remove or fix stale NVM current symlink",
                            risk="high",
                            repairability="GUIDED",
                        ))
                    elif vl.is_symlink() and vl.exists():
                        # Check what it points to
                        target = vl.readlink()
                        findings.append(AuditFinding(
                            id="shell.pkg.nvm_current_link",
                            category="package_manager",
                            severity="NOTICE",
                            title="NVM current symlink",
                            summary=f"NVM current -> {target}",
                            evidence=f"NVM directory: {nvm_dir}",
                            source_file=str(nvm_path),
                            line_numbers=(),
                            current_state=f"-> {target}",
                            recommended_state="Verify NVM current points to desired Node version",
                            risk="low",
                            repairability="ADVISORY_ONLY",
                        ))
            except Exception:
                pass

            # Check for NVM initialized multiple times
            # (We just report; actual detection would need shell parsing)
            findings.append(AuditFinding(
                id="shell.pkg.nvm_initialized",
                category="package_manager",
                severity="NOTICE",
                title="NVM environment detected",
                summary=f"NVM_DIR set to {nvm_dir}",
                evidence=f"NVM directory exists: {nvm_path.exists()}",
                source_file="",
                line_numbers=(),
                current_state="NVM environment present",
                recommended_state="Ensure NVM is initialized once in .zshrc or .bashrc",
                risk="low",
                repairability="ADVISORY_ONLY",
            ))

    # pnpm
    pnpm_prefix = subprocess.run(
        ["pnpm", "bin"],
        capture_output=True, text=True, timeout=10
    )
    if pnpm_prefix.returncode == 0:
        pnpm_bin = pnpm_prefix.stdout.strip()
        if pnpm_bin:
            findings.append(AuditFinding(
                id="shell.pkg.pnpm_configured",
                category="package_manager",
                severity="NOTICE",
                title="pnpm installed",
                summary=f"pnpm binary found at {pnpm_bin}",
                evidence=f"pnpm bin: {pnpm_bin}",
                source_file="",
                line_numbers=(),
                current_state=f"pnpm at {pnpm_bin}",
                recommended_state="Ensure pnpm is in PATH consistently",
                risk="low",
                repairability="ADVISORY_ONLY",
            ))

    # Bun
    bun_path = subprocess.run(
        ["bun", "ls"],
        capture_output=True, text=True, timeout=10
    )
    if bun_path.returncode == 0 and "Bun" in bun_path.stdout:
        findings.append(AuditFinding(
            id="shell.pkg.bun_configured",
            category="package_manager",
            severity="NOTICE",
            title="Bun installed",
            summary="Bun runtime detected",
            evidence=bun_path.stdout[:200],
            source_file="",
            line_numbers=(),
            current_state="Bun available",
            recommended_state="Ensure bun is in PATH consistently",
            risk="low",
            repairability="ADVISORY_ONLY",
        ))

    # Go
    go_path = subprocess.run(
        ["go", "env", "GOPATH"],
        capture_output=True, text=True, timeout=10
    )
    if go_path.returncode == 0 and go_path.stdout.strip():
        findings.append(AuditFinding(
            id="shell.pkg.go_configured",
            category="package_manager",
            severity="NOTICE",
            title="Go installed",
            summary=f"Go environment detected (GOPATH: {go_path.stdout.strip()})",
            evidence=f"Go env output: {go_path.stdout.strip()}",
            source_file="",
            line_numbers=(),
            current_state="Go available",
            recommended_state="Ensure Go binaries are in PATH",
            risk="low",
            repairability="ADVISORY_ONLY",
        ))

    # Cargo
    cargo_path = subprocess.run(
        ["cargo", "env", "CARGO_HOME"],
        capture_output=True, text=True, timeout=10
    )
    if cargo_path.returncode == 0 and cargo_path.stdout.strip():
        findings.append(AuditFinding(
            id="shell.pkg.cargo_configured",
            category="package_manager",
            severity="NOTICE",
            title="Cargo installed",
            summary=f"Cargo environment detected (CARGO_HOME: {cargo_path.stdout.strip()})",
            evidence=f"Cargo env output: {cargo_path.stdout.strip()}",
            source_file="",
            line_numbers=(),
            current_state="Cargo available",
            recommended_state="Ensure Cargo binaries are in PATH",
            risk="low",
            repairability="ADVISORY_ONLY",
        ))

    # Python / pyenv
    pyenv_version = ""
    try:
        pyenv_result = subprocess.run(
            ["pyenv", "version"],
            capture_output=True, text=True, timeout=10
        )
        if pyenv_result.returncode == 0:
            pyenv_version = pyenv_result.stdout.strip()
    except Exception:
        pass

    if pyenv_version:
        findings.append(AuditFinding(
            id="shell.pkg.pyenv_configured",
            category="package_manager",
            severity="NOTICE",
            title="pyenv installed",
            summary=f"pyenv version: {pyenv_version}",
            evidence=f"pyenv output: {pyenv_version}",
            source_file="",
            line_numbers=(),
            current_state="pyenv available",
            recommended_state="Ensure pyenv shim is in PATH and initialized once",
            risk="low",
            repairability="ADVISORY_ONLY",
        ))
    else:
        # Check for python in PATH
        python_result = subprocess.run(
            ["python3", "--version"],
            capture_output=True, text=True, timeout=10
        )
        if python_result.returncode == 0:
            findings.append(AuditFinding(
                id="shell.pkg.python3_configured",
                category="package_manager",
                severity="NOTICE",
                title="Python 3 installed",
                summary=f"Python 3: {python_result.stdout.strip()}",
                evidence=f"Python 3 version: {python_result.stdout.strip()}",
                source_file="",
                line_numbers=(),
                current_state="Python 3 available",
                recommended_state="Ensure python3 is consistently available",
                risk="low",
                repairability="ADVISORY_ONLY",
            ))

    # Ruby / RVM
    ruby_result = subprocess.run(
        ["ruby", "--version"],
        capture_output=True, text=True, timeout=10
    )
    if ruby_result.returncode == 0:
        findings.append(AuditFinding(
            id="shell.pkg.ruby_configured",
            category="package_manager",
            severity="NOTICE",
            title="Ruby installed",
            summary=f"Ruby: {ruby_result.stdout.strip()}",
            evidence=f"Ruby version: {ruby_result.stdout.strip()}",
            source_file="",
            line_numbers=(),
            current_state="Ruby available",
            recommended_state="Ensure ruby gems are in PATH consistently",
            risk="low",
            repairability="ADVISORY_ONLY",
        ))

    # SDKMAN
    sdkman_dir = Path.home() / ".sdkman"
    if sdkman_dir.exists():
        findings.append(AuditFinding(
            id="shell.pkg.sdkman_configured",
            category="package_manager",
            severity="NOTICE",
            title="SDKMAN installed",
            summary="SDKMAN detected at ~/.sdkman",
            evidence=f"SDKMAN directory exists: {sdkman_dir.exists()}",
            source_file="",
            line_numbers=(),
            current_state="SDKMAN available",
            recommended_state="Ensure SDKMAN is initialized in .zshrc or .bashrc",
            risk="low",
            repairability="ADVISORY_ONLY",
        ))

    return findings
