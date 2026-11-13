#!/usr/bin/env python3
"""msp tune — Shell & system performance tuning.

Commands:
  check       Run all diagnostics (shell + system), show issues
  fix         Apply auto-fixes (--dry-run to preview). Modified files are
              backed up to ~/.msp/backups first: on failure every backup is
              restored (all-or-nothing); on success backups are kept and you
              are offered cleanup (interactive) or told how to remove them.
  top         Show top CPU/memory processes, memory pressure, and load
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.command import setup_completion

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None

HOME = Path.home()
ZSH_HISTORY = HOME / ".zsh_history"
ZSHRC = HOME / ".zshrc"
ZSH_DIR = HOME / ".zsh"
NVM_SH = HOME / ".nvm" / "nvm.sh"
BACKUP_DIR = HOME / ".msp" / "backups"


@dataclass
class Finding:
    domain: str
    severity: str
    title: str
    description: str
    fixable: bool
    fix_cmd: str = ""
    detail: str = ""


def _run(cmd: str | list[str], timeout: int = 30, shell: bool = True) -> tuple[int, str]:
    try:
        if shell:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        else:
            r = subprocess.run(
                cmd, shell=False, capture_output=True, text=True, timeout=timeout,
                stderr=subprocess.DEVNULL,
            )
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return -1, "timed out"
    except Exception as e:
        return -1, str(e)


def _parse_seconds(text: str) -> float:
    m = re.search(r"([\d.]+)\s*total", text)
    if m:
        return float(m.group(1))
    m = re.search(r"real\s+(?:(\d+)m)?([\d.]+)s", text, re.IGNORECASE)
    if m:
        return (float(m.group(1) or 0) * 60) + float(m.group(2))
    return 0.0


def _fmt_ms(milliseconds: float) -> str:
    return f"{milliseconds:.0f}ms"


def _fmt_gb(bytes_val: int) -> str:
    return f"{bytes_val / 1_000_000_000:.1f}GB"


def _tb(rows: list[tuple[str, str, str]], title: str = "") -> None:
    if RICH_AVAILABLE and console:
        t = Table(title=title)
        t.add_column("Check", style="cyan")
        t.add_column("Value", style="yellow")
        for label, value, _ in rows:
            t.add_row(label, value)
        console.print(t)
    else:
        if title:
            print(f"── {title} ──")
        for label, value, _ in rows:
            print(f"  {label}: {value}")


class Tuner:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.findings: list[Finding] = []
        # (target, backup) pairs created during the current fix run.
        self.backups: list[tuple[Path, Path]] = []

    # ── check ──────────────────────────────────────────────

    def check(self, json_output: bool = False) -> list[Finding]:
        self.findings = []
        self._check_zsh_startup()
        self._check_zsh_nvm()
        self._check_zsh_history()
        self._check_zsh_path_dupes()
        self._check_zsh_async()
        self._check_zsh_brew()
        self._check_disk()
        self._check_memory()
        self._check_brew()
        self._check_docker()
        self._check_cache()
        self._check_launch_daemons()

        if json_output:
            print(json.dumps([{
                "domain": f.domain, "severity": f.severity,
                "title": f.title, "description": f.description,
                "fixable": f.fixable,
            } for f in self.findings], indent=2))
        else:
            self._print_check()
        return self.findings

    def _print_check(self) -> None:
        if not self.findings:
            print("No issues found.")
            return
        colors = {"high": "red", "medium": "yellow", "low": "cyan"}
        if RICH_AVAILABLE and console:
            table = Table(title="Tune Results")
            table.add_column("Domain", style="bold")
            table.add_column("Issue", style="cyan")
            for f in self.findings:
                c = colors.get(f.severity, "white")
                table.add_row(f"[{c}]{f.domain}[/{c}]", f.title)
            console.print(table)
            print()
            for f in self.findings:
                c = colors.get(f.severity, "white")
                console.print(f"  [{c}]{f.severity.upper()}[/{c}] [{c}]{f.domain}[/{c}] {f.title}")
                console.print(f"       {f.description}")
                if f.fixable:
                    console.print("       → msp tune fix")
                console.print()
        else:
            for f in self.findings:
                print(f"[{f.severity.upper()}] [{f.domain}] {f.title}")
                print(f"  {f.description}")
                if f.fixable:
                    print(f"  → msp tune fix")
                print()

    # ── zsh checks ──

    def _check_zsh_startup(self) -> None:
        _, out = _run("time ( zsh -i -c exit ) 2>&1")
        ms = _parse_seconds(out) * 1000
        if ms < 1:
            return
        severity = "high" if ms > 500 else "medium"
        self.findings.append(Finding(
            domain="zsh", severity=severity,
            title=f"Startup: {_fmt_ms(ms)} (target <150ms)",
            description=f"Interactive zsh takes {_fmt_ms(ms)}. " +
                        ("Lazy-load NVM, trim history, or audit oh-my-zsh plugins." if ms > 150 else ""),
            fixable=False,
        ))

    def _check_zsh_nvm(self) -> None:
        if not NVM_SH.exists() or not ZSHRC.exists():
            return
        if "nvm.sh" in ZSHRC.read_text() and "Lazy" not in ZSHRC.read_text():
            self.findings.append(Finding(
                domain="zsh", severity="high",
                title="NVM loaded eagerly",
                description="nvm.sh sourced on every shell start (+200-400ms). Use lazy-load stubs.",
                fixable=True, fix_cmd="nvm_lazy",
            ))

    def _check_zsh_history(self) -> None:
        if not ZSH_HISTORY.exists():
            return
        _, out = _run(f"wc -l < {ZSH_HISTORY}")
        lines = int(out.strip()) if out.strip().isdigit() else 0
        if lines > 100000:
            self.findings.append(Finding(
                domain="zsh", severity="medium",
                title=f"History: {lines} lines",
                description="Large history slows compinit and search.",
                fixable=True, fix_cmd="history_trim",
            ))
        rc, file_out = _run(f"file {ZSH_HISTORY}")
        if rc == 0 and "ASCII" not in file_out:
            self.findings.append(Finding(
                domain="zsh", severity="high",
                title="History file corrupted",
                description=f"Type: {file_out.strip()}. Extract with 'strings'.",
                fixable=True, fix_cmd="history_repair",
            ))

    def _check_zsh_path_dupes(self) -> None:
        if not ZSHRC.exists():
            return
        text = ZSHRC.read_text()
        entries = []
        for m in re.finditer(r'^export\s+PATH=.*["\']?(.*?)["\']?\s*$', text, re.M):
            for p in m.group(1).split(":"):
                e = p.strip().strip("'\"")
                if e:
                    entries.append(e)
        seen = set()
        dups = 0
        for e in entries:
            if e in seen:
                dups += 1
            else:
                seen.add(e)
        if dups:
            self.findings.append(Finding(
                domain="zsh", severity="low",
                title=f"PATH: {dups} duplicate entries",
                description="Repeated PATH exports waste startup time.",
                fixable=False,
            ))

    def _check_zsh_async(self) -> None:
        if not ZSHRC.exists():
            return
        text = ZSHRC.read_text()
        if "zsh-autosuggestions" in text and "ZSH_AUTOSUGGEST_USE_ASYNC" not in text:
            self.findings.append(Finding(
                domain="zsh", severity="medium",
                title="Auto-suggestions blocking prompt",
                description="zsh-autosuggestions loaded without ZSH_AUTOSUGGEST_USE_ASYNC=1.",
                fixable=True, fix_cmd="async",
            ))

    def _check_zsh_brew(self) -> None:
        if not ZSHRC.exists():
            return
        text = ZSHRC.read_text()
        if "brew shellenv" in text and "HOMEBREW_PREFIX" not in text:
            self.findings.append(Finding(
                domain="zsh", severity="medium",
                title="brew shellenv runs every time",
                description="eval $(brew shellenv) on every shell start. Guard with HOMEBREW_PREFIX check.",
                fixable=True, fix_cmd="brew_shellenv",
            ))

    # ── system checks ──

    def _check_disk(self) -> None:
        rc, out = _run("df -g / 2>/dev/null | tail -1")
        parts = out.split()
        if len(parts) >= 4:
            try:
                used_pct = int(parts[4].rstrip("%"))
                free_gb = int(parts[3])
                if used_pct > 85:
                    self.findings.append(Finding(
                        domain="disk", severity="high",
                        title=f"Disk: {used_pct}% used ({free_gb}GB free)",
                        description=f"Boot volume is {used_pct}% full. Free space affects system performance.",
                        fixable=False,
                    ))
            except (ValueError, IndexError):
                pass

    def _check_memory(self) -> None:
        rc, out = _run("memory_pressure 2>/dev/null | head -5")
        if not out:
            rc, out = _run("vm_stat 2>/dev/null | head -10")
        pressure_match = re.search(r"System-wide memory free percentage:\s*(\d+)", out)
        if pressure_match:
            pct = int(pressure_match.group(1))
            if pct < 20:
                self.findings.append(Finding(
                    domain="memory", severity="high",
                    title=f"Memory pressure: {pct}% free",
                    description="Low available memory. Check for memory leaks in active processes.",
                    fixable=False,
                ))

        rc, out = _run(["sysctl", "vm.swapusage"], shell=False)
        swap_match = re.search(r"used = (\d+\.?\d*)([KMGT])", out)
        if swap_match:
            val = float(swap_match.group(1))
            unit = swap_match.group(2)
            multipliers = {"K": 1, "M": 1000, "G": 1000000, "T": 1000000000}
            used_mb = val * multipliers.get(unit, 1) / 1000
            if used_mb > 2000:
                self.findings.append(Finding(
                    domain="memory", severity="medium",
                    title=f"Swap: {used_mb:.0f}MB used",
                    description="High swap usage indicates memory pressure. Consider closing apps or adding RAM.",
                    fixable=False,
                ))

    def _check_brew(self) -> None:
        rc, out = _run("brew cleanup --dry-run 2>&1")
        if rc == 0 and out.strip():
            lines = [l for l in out.splitlines() if l.strip() and "Would remove" in l]
            if lines:
                total_bytes = 0
                for l in lines:
                    m = re.search(r"\(([\d.]+)\s*([KMGT])", l)
                    if m:
                        val = float(m.group(1))
                        unit = m.group(2)
                        mult = {"K": 1_000, "M": 1_000_000, "G": 1_000_000_000, "T": 1_000_000_000_000}
                        total_bytes += int(val * mult.get(unit, 1))
                self.findings.append(Finding(
                    domain="brew", severity="low",
                    title=f"Cleanup: {len(lines)} stale bottles ({_fmt_gb(total_bytes)} reclaimable)",
                    description="Run 'brew cleanup' to free space.",
                    fixable=False,
                ))

    def _check_docker(self) -> None:
        rc, out = _run("docker system df --format '{{.Type}} {{.Size}} {{.Reclaimable}}' 2>/dev/null")
        if rc == 0 and out.strip():
            reclaimable = 0
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0] == "Images":
                    reclaimable += _parse_size(parts[2])
            if reclaimable > 1_000_000_000:
                self.findings.append(Finding(
                    domain="docker", severity="low",
                    title=f"Docker: {_fmt_gb(reclaimable)} reclaimable",
                    description="Run 'docker system prune' to clean up.",
                    fixable=False,
                ))

    def _check_cache(self) -> None:
        _, out = _run("du -sh ~/Library/Caches 2>/dev/null | cut -f1")
        cache_size = out.strip()
        if not cache_size or cache_size == "timed out":
            return
        self.findings.append(Finding(
            domain="system", severity="low",
            title=f"User caches: ~{cache_size}",
            description=f"Cache directory at ~/Library/Caches. Contents are safe to remove.",
            fixable=False,
        ))

    def _check_launch_daemons(self) -> None:
        _, out = _run("launchctl list 2>/dev/null | grep -v 'com.apple' | wc -l")
        count = int(out.strip()) if out.strip().isdigit() else 0
        if count > 50:
            self.findings.append(Finding(
                domain="system", severity="low",
                title=f"Launch agents: {count} non-Apple",
                description=f"{count} third-party launch agents/daemons registered. Each adds to boot time.",
                fixable=False,
            ))

    # ── top ────────────────────────────────────────────────

    def top(self, json_output: bool = False) -> dict[str, Any]:
        """Show top CPU/memory processes, memory pressure, and load average."""
        cmd = (
            "echo '=== TOP CPU ==='; "
            "ps axo pcpu,pmem,comm -r | head -12; "
            "echo '=== TOP MEM ==='; "
            "ps axo pmem,comm -m | head -12; "
            "echo '=== PRESSURE ==='; "
            "memory_pressure -Q 2>/dev/null; "
            "echo '=== LOAD ==='; "
            "uptime"
        )
        rc, out = _run(cmd)
        result = {
            "command": cmd,
            "returncode": rc,
            "output": out,
        }
        if json_output:
            print(json.dumps(result, indent=2))
        else:
            print(out)
        return result

    # ── backups ────────────────────────────────────────────

    def _make_backup(self, target: Path, dry: bool = False) -> Path:
        """Back up `target` into BACKUP_DIR before a destructive write.

        Raises on failure so the caller can abort rather than edit a file
        with no rollback path. Records (target, backup) for this run so a
        later failure can restore every modified file (all-or-nothing).
        Returns the backup path (placeholder path in dry mode).
        """
        if not target.exists():
            raise FileNotFoundError(f"{target} does not exist")
        if dry:
            return BACKUP_DIR / f"{target.name}.<timestamp>.bak"
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = BACKUP_DIR / f"{target.name}.{stamp}.bak"
            n = 1
            while backup.exists():
                backup = BACKUP_DIR / f"{target.name}.{stamp}.{n}.bak"
                n += 1
            shutil.copy2(target, backup)
        except Exception:
            raise
        self.backups.append((target, backup))
        return backup

    def _restore(self, target: Path, backup: Path) -> bool:
        try:
            shutil.copy2(backup, target)
            return True
        except Exception:
            return False

    def _rollback(self) -> list[dict[str, str]]:
        """Restore every backup recorded this run; delete backups after a
        successful restore. Returns a report for failed-run summaries."""
        rolled: list[dict[str, str]] = []
        for target, backup in self.backups:
            if self._restore(target, backup):
                rolled.append({"file": str(target), "restored_from": str(backup)})
                backup.unlink(missing_ok=True)
            else:
                rolled.append({"file": str(target), "restored_from": str(backup),
                               "status": "restore-failed", "backup_kept": str(backup)})
        self.backups.clear()
        return rolled

    def _cleanup_backups(self, delete: bool) -> list[str]:
        """Delete or keep this run's backups; returns the affected paths."""
        paths = [str(backup) for _, backup in self.backups]
        if delete:
            for _, backup in self.backups:
                backup.unlink(missing_ok=True)
        self.backups.clear()
        return paths

    def _prompt_backup_cleanup(self, json_output: bool) -> None:
        """On success: offer to delete backups (TTY only); otherwise report
        where they are and how to restore them."""
        if not self.backups:
            return
        if json_output or not sys.stdin.isatty() or not sys.stdout.isatty():
            kept = self._cleanup_backups(delete=False)
            print("Backups kept — verify the fixes, then remove manually:")
            for p in kept:
                print(f"  {p}")
            return
        try:
            from src.command import interactive_select
            choice = interactive_select(
                [
                    ("keep", "Keep backups (recommended)", "Leave copies in ~/.msp/backups"),
                    ("delete", "Delete backups", "Fixes verified; remove backup copies"),
                ],
                title="Fixes applied successfully. Delete backups?",
            )
        except Exception:
            choice = None  # e.g. raw-mode failure: fall back to keeping them
        delete = bool(choice) and choice[0] == "delete"
        handled = self._cleanup_backups(delete=delete)
        if delete:
            print(f"Deleted {len(handled)} backup(s).")
        else:
            print("Backups kept — verify the fixes, then remove manually:")
            for p in handled:
                print(f"  {p}")

    def _print_fix_summary(self, results: list[dict[str, Any]]) -> None:
        if not results:
            return
        colors = {"applied": "green", "failed": "red", "skipped": "yellow", "dry-run": "cyan"}
        for r in results:
            status = r.get("status", "unknown")
            c = colors.get(status, "white")
            title = r.get("finding") or r.get("fix", "")
            plain = f"  {status.upper():<8} {title}"
            if r.get("detail"):
                plain += f" ({r['detail']})"
            if RICH_AVAILABLE and console:
                console.print(f"  [{c}]{status.upper():<8}[/] {title}")
            else:
                print(plain)
            if r.get("backup"):
                plain = f"           backup: {r['backup']}"
                (console.print if RICH_AVAILABLE and console else print)(plain)
            if r.get("rolled_back"):
                plain = (f"           rolled back {len(r['rolled_back'])} file(s): "
                         + ", ".join(Path(x["file"]).name for x in r["rolled_back"]))
                (console.print if RICH_AVAILABLE and console else print)(plain)

    # ── fix ────────────────────────────────────────────────

    def fix(self, dry_run: bool = False, json_output: bool = False) -> list[dict[str, Any]]:
        self.check(json_output=False)
        results: list[dict[str, Any]] = []
        self.backups = []
        zshrc_lines = ZSHRC.read_text().splitlines(keepends=True) if ZSHRC.exists() else []

        fix_map: dict[str, Any] = {
            "nvm_lazy": self._fix_nvm,
            "history_trim": self._fix_history_trim,
            "history_repair": self._fix_history_repair,
            "async": self._fix_async,
            "brew_shellenv": self._fix_brew_shellenv,
        }

        zshrc_dirty = False
        for f in self.findings:
            if not f.fixable or not f.fix_cmd:
                continue
            handler = fix_map.get(f.fix_cmd)
            if not handler:
                continue
            try:
                result = handler(zshrc_lines, dry_run)
            except Exception as e:
                # All-or-nothing: restore every file touched this run and stop.
                rolled = self._rollback()
                zshrc_lines = ZSHRC.read_text().splitlines(keepends=True) if ZSHRC.exists() else []
                zshrc_dirty = False
                result: dict[str, Any] = {"fix": f.fix_cmd, "status": "failed", "reason": str(e)}
                if rolled:
                    result["rolled_back"] = rolled
                result["finding"] = f.title
                results.append(result)
                break
            result["finding"] = f.title
            results.append(result)
            if result.get("dirty_zshrc"):
                zshrc_dirty = True
            if dry_run:
                print(f"  [DRY-RUN] {f.title}")

        if not dry_run and zshrc_dirty and ZSHRC.exists():
            write_result: dict[str, Any] = {}
            try:
                backup = self._make_backup(ZSHRC)
            except Exception as e:
                rolled = self._rollback()
                write_result = {"fix": "zshrc_write", "status": "failed",
                                "finding": f"Rewrite {ZSHRC}",
                                "reason": f"backup failed: {e}"}
                if rolled:
                    write_result["rolled_back"] = rolled
            else:
                if self._write_zshrc(zshrc_lines):
                    write_result = {"fix": "zshrc_write", "status": "applied",
                                    "finding": f"Rewrite {ZSHRC}",
                                    "path": str(ZSHRC), "backup": str(backup)}
                else:
                    rolled = self._rollback()
                    write_result = {"fix": "zshrc_write", "status": "failed",
                                    "finding": f"Rewrite {ZSHRC}",
                                    "reason": "write failed; restored from backup"}
                    if rolled:
                        write_result["rolled_back"] = rolled
            results.append(write_result)

        if not dry_run:
            self._print_fix_summary(results)
            if not any(r.get("status") == "failed" for r in results):
                self._prompt_backup_cleanup(json_output)

        if json_output:
            print(json.dumps(results, indent=2))
        return results

    def _write_zshrc(self, lines: list[str]) -> bool:
        if not ZSHRC.exists():
            return False
        try:
            ZSHRC.write_text("".join(lines))
            return True
        except Exception:
            return False

    def _has(self, lines: list[str], pattern: str) -> bool:
        return any(pattern in l for l in lines)

    def _fix_nvm(self, lines: list[str], dry: bool) -> dict:
        if self._has(lines, "Lazy"):
            return {"fix": "nvm_lazy", "status": "skipped", "reason": "already lazy"}
        for i, line in enumerate(lines):
            if "source" not in line or "nvm.sh" not in line:
                continue
            if i > 0 and "Lazy" in lines[i - 1]:
                continue
            indent = line[:len(line) - len(line.lstrip())]
            block = (
                f"{indent}# Lazy-load NVM\n"
                f"{indent}export NVM_DIR=\"$HOME/.nvm\"\n"
                f"{indent}if [ -s \"$NVM_DIR/nvm.sh\" ]; then\n"
                f"{indent}  nvm()   {{ unset -f nvm node npm npx yarn pnpm; . \"$NVM_DIR/nvm.sh\"; nvm \"$@\"; }}\n"
                f"{indent}  node()  {{ unset -f nvm node npm npx yarn pnpm; . \"$NVM_DIR/nvm.sh\"; node \"$@\"; }}\n"
                f"{indent}  npm()   {{ unset -f nvm node npm npx yarn pnpm; . \"$NVM_DIR/nvm.sh\"; npm \"$@\"; }}\n"
                f"{indent}  npx()   {{ unset -f nvm node npm npx yarn pnpm; . \"$NVM_DIR/nvm.sh\"; npx \"$@\"; }}\n"
                f"{indent}  yarn()  {{ unset -f nvm node npm npx yarn pnpm; . \"$NVM_DIR/nvm.sh\"; yarn \"$@\"; }}\n"
                f"{indent}  pnpm()  {{ unset -f nvm node npm npx yarn pnpm; . \"$NVM_DIR/nvm.sh\"; pnpm \"$@\"; }}\n"
                f"{indent}fi\n"
            )
            lines[i] = block if not dry else lines[i]
            return {"fix": "nvm_lazy", "status": "applied" if not dry else "dry-run", "dirty_zshrc": True}
        return {"fix": "nvm_lazy", "status": "skipped", "reason": "not found"}

    def _fix_history_trim(self, lines: list[str], dry: bool) -> dict:
        if not ZSH_HISTORY.exists():
            return {"fix": "history_trim", "status": "skipped", "reason": "no file"}
        if dry:
            return {"fix": "history_trim", "status": "dry-run"}
        hl = ZSH_HISTORY.read_text().splitlines()
        if len(hl) > 10000:
            backup = self._make_backup(ZSH_HISTORY)
            ZSH_HISTORY.write_text("\n".join(hl[-10000:]) + "\n")
            return {"fix": "history_trim", "status": "applied",
                    "detail": f"{len(hl)}→10000", "backup": str(backup)}
        return {"fix": "history_trim", "status": "skipped", "reason": f"{len(hl)} lines OK"}

    def _fix_history_repair(self, lines: list[str], dry: bool) -> dict:
        if not ZSH_HISTORY.exists():
            return {"fix": "history_repair", "status": "skipped", "reason": "no file"}
        if dry:
            return {"fix": "history_repair", "status": "dry-run"}
        backup = self._make_backup(ZSH_HISTORY)
        rc, _ = _run(f"strings {backup} > {ZSH_HISTORY}")
        if rc == 0:
            return {"fix": "history_repair", "status": "applied", "backup": str(backup)}
        raise RuntimeError(f"strings extraction failed (rc={rc}); history restored from backup")

    def _fix_async(self, lines: list[str], dry: bool) -> dict:
        if self._has(lines, "ZSH_AUTOSUGGEST_USE_ASYNC"):
            return {"fix": "async", "status": "skipped", "reason": "already set"}
        for i, line in enumerate(lines):
            if "oh-my-zsh.sh" in line:
                lines.insert(i + 1, "ZSH_AUTOSUGGEST_USE_ASYNC=1\n")
                return {"fix": "async", "status": "applied" if not dry else "dry-run", "dirty_zshrc": True}
        return {"fix": "async", "status": "skipped", "reason": "oh-my-zsh.sh not found"}

    def _fix_brew_shellenv(self, lines: list[str], dry: bool) -> dict:
        if self._has(lines, "HOMEBREW_PREFIX"):
            return {"fix": "brew_shellenv", "status": "skipped", "reason": "already guarded"}
        for i, line in enumerate(lines):
            if "brew shellenv" in line:
                indent = line[:len(line) - len(line.lstrip())]
                guarded = (
                    f"{indent}if [ -z \"$HOMEBREW_PREFIX\" ]; then\n"
                    f"{indent}  {line.rstrip()}\n"
                    f"{indent}fi\n"
                )
                lines[i] = guarded if not dry else lines[i]
                return {"fix": "brew_shellenv", "status": "applied" if not dry else "dry-run", "dirty_zshrc": True}
        return {"fix": "brew_shellenv", "status": "skipped", "reason": "not found"}


def _parse_size(s: str) -> int:
    """Parse a size string like '1.5GB' or '500MB' into bytes."""
    m = re.match(r"([\d.]+)\s*([KMGT])B?", s.strip())
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2)
    return int(val * {"K": 1_000, "M": 1_000_000, "G": 1_000_000_000, "T": 1_000_000_000_000}[unit])


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="msp tune - Shell & system performance tuning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  msp tune check          Run all diagnostics
  msp tune check --json   Machine-readable output
  msp tune fix            Apply all auto-fixes (backs up modified files first)
  msp tune fix --dry-run  Preview fixes

Fixes that modify files (~/.zshrc, ~/.zsh_history) create timestamped
backups in ~/.msp/backups first. On failure every backup is restored;
on success backups are kept and you are offered cleanup.
        """,
    )
    p.add_argument("action", nargs="?", choices=["check", "fix", "top", ""], help="check | fix | top (omit for interactive)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--dry-run", action="store_true", help="Preview fixes")
    p.add_argument("--verbose", action="store_true", help="Verbose")
    return p


def interactive_menu(tuner: Tuner, json_output: bool = False):
    from src.command import interactive_menu as cmd_menu
    while True:
        action = cmd_menu([
            ("1", "check", "Run all diagnostics"),
            ("2", "fix", "Apply auto-fixes"),
            ("3", "top", "Show top CPU/memory, pressure, load"),
        ], title="msp tune")
        if action is None:
            break
        if action == "check":
            tuner.check(json_output=json_output)
        elif action == "fix":
            tuner.fix(dry_run=False, json_output=json_output)
        elif action == "top":
            tuner.top(json_output=json_output)
        print()


def main(argv: Optional[Sequence[str]] = None) -> int:
    if (argv is None and len(sys.argv) <= 1) or (argv is not None and len(argv) == 0):
        interactive_menu(Tuner())
        return 0
    parser = _build_parser()
    setup_completion(parser)
    args = parser.parse_args(argv)
    tuner = Tuner(verbose=args.verbose)
    if not args.action:
        interactive_menu(tuner, args.json)
    elif args.action == "check":
        tuner.check(json_output=args.json)
    elif args.action == "fix":
        tuner.fix(dry_run=args.dry_run, json_output=args.json)
    elif args.action == "top":
        tuner.top(json_output=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
