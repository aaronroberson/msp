#!/usr/bin/env python3
"""Dependency manager for msp CLI."""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

from src.command import (
    setup_completion,
    suggest_command,
    interactive_menu as cmd_interactive_menu,
    interactive_select,
)

try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


class DepStatus(Enum):
    INSTALLED = "installed"
    MISSING = "missing"
    BROKEN = "broken"
    UNKNOWN = "unknown"


@dataclass
class Dependency:
    name: str
    description: str
    pkg_type: str
    required: bool
    auto_install: bool
    install_cmd: str
    verify_cmd: str
    path: Optional[str] = None
    status: DepStatus = DepStatus.UNKNOWN


class DependencyManager:
    """Manages msp dependencies."""

    def __init__(self, deps_file: str = None):
        if deps_file is None:
            deps_file = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "deps.json"
            )
        self.deps_file = deps_file
        self.deps = self._load_deps()

    def _load_deps(self) -> Dict[str, Any]:
        try:
            with open(self.deps_file, 'r') as f:
                data = json.load(f)
                return data.get("dependencies", {})
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _run_cmd(self, cmd: str, shell: bool = True) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd if shell else cmd.split(),
                shell=shell,
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def check_dep(self, name: str) -> DepStatus:
        """Check if a dependency is installed and working."""
        if name not in self.deps:
            return DepStatus.UNKNOWN

        dep = self.deps[name]

        if dep.get("type") == "cask":
            app_path = dep.get("path", "")
            if app_path:
                success, _ = self._run_cmd(f'test -f "{app_path}"')
                return DepStatus.INSTALLED if success else DepStatus.MISSING

        verify_cmd = dep.get("verify_cmd", "")
        if verify_cmd:
            success, output = self._run_cmd(verify_cmd)
            if success:
                return DepStatus.INSTALLED
            return DepStatus.MISSING

        return DepStatus.UNKNOWN

    def check_all(self) -> Dict[str, DepStatus]:
        """Check all dependencies."""
        results = {}
        for name in self.deps:
            results[name] = self.check_dep(name)
        return results

    def install_dep(self, name: str, force: bool = False) -> tuple[bool, str]:
        """Install a dependency."""
        if name not in self.deps:
            return False, f"Unknown dependency: {name}"

        dep = self.deps[name]
        install_cmd = dep.get("install_cmd", "")

        if not install_cmd:
            return False, f"No install command for {name}"

        print(f"Installing {name}...")
        success, output = self._run_cmd(install_cmd)

        if success:
            return True, f"Successfully installed {name}"
        return False, f"Failed to install {name}: {output}"

    def install_required(self) -> List[tuple[str, bool, str]]:
        """Install all required dependencies."""
        results = []
        for name, dep in self.deps.items():
            if dep.get("required", False) and dep.get("auto_install", False):
                status = self.check_dep(name)
                if status != DepStatus.INSTALLED:
                    success, msg = self.install_dep(name)
                    results.append((name, success, msg))
        return results

    def install_all(self) -> List[tuple[str, bool, str]]:
        """Install all dependencies."""
        results = []
        for name in self.deps:
            status = self.check_dep(name)
            if status != DepStatus.INSTALLED:
                success, msg = self.install_dep(name)
                results.append((name, success, msg))
        return results

    def _sort_results(self, results: Dict[str, DepStatus], sort_by: str) -> Dict[str, DepStatus]:
        """Sort results by the specified key."""
        if sort_by == "name":
            return dict(sorted(results.items(), key=lambda x: x[0].lower()))
        elif sort_by == "status":
            status_order = {"installed": 0, "missing": 1, "broken": 2, "unknown": 3}
            return dict(sorted(results.items(), key=lambda x: (status_order.get(x[1].value, 4), x[0].lower())))
        elif sort_by == "required":
            return dict(sorted(results.items(), key=lambda x: (0 if self.deps.get(x[0], {}).get("required") else 1, x[0].lower())))
        return results

    def status_table(self, json_output: bool = False, sort_by: str = "name") -> None:
        """Show dependency status table."""
        results = self.check_all()
        results = self._sort_results(results, sort_by)

        if json_output:
            output = {}
            for name, status in results.items():
                dep = self.deps[name]
                output[name] = {
                    "status": status.value,
                    "description": dep.get("description", ""),
                    "required": dep.get("required", False),
                }
            print(json.dumps(output, indent=2))
            return

        if RICH_AVAILABLE and console:
            table = Table(title="msp Dependencies")
            table.add_column("Package", style="cyan")
            table.add_column("Status", style="yellow")
            table.add_column("Description")
            table.add_column("Required", style="magenta")

            for name, status in results.items():
                dep = self.deps[name]
                status_color = "green" if status == DepStatus.INSTALLED else "red"
                status_str = f"[{status_color}]{status.value}[/{status_color}]"
                table.add_row(
                    name,
                    status_str,
                    dep.get("description", ""),
                    "Yes" if dep.get("required") else "No"
                )
            console.print(table)
        else:
            for name, status in results.items():
                dep = self.deps[name]
                req = "Required" if dep.get("required") else "Optional"
                print(f"[{status.value}] {name} - {req}")

    def _shell_startup_check(self) -> list[tuple[str, str, str]]:
        """Check shell startup performance. Returns list of (severity, title, detail)."""
        shell_issues: list[tuple[str, str, str]] = []
        def _parse_seconds(text: str) -> float:
            m = re.search(r"([\d.]+)\s*total", text)
            if m:
                return float(m.group(1))
            m = re.search(r"real\s+(?:(\d+)m)?([\d.]+)s", text, re.IGNORECASE)
            if m:
                return (float(m.group(1) or 0) * 60) + float(m.group(2))
            return 0.0

        try:
            ok, out = self._run_cmd("time ( zsh -i -c exit ) 2>&1")
            seconds = _parse_seconds(out)
            if seconds > 0:
                ms = seconds * 1000
                if ms > 500:
                    shell_issues.append(("HIGH", "Zsh startup is slow", f"{ms:.0f}ms (target: <150ms). Run 'msp tune profile'."))
                elif ms > 150:
                    shell_issues.append(("MEDIUM", "Zsh startup could be faster", f"{ms:.0f}ms (target: <150ms)."))
        except Exception:
            pass

        history = Path.home() / ".zsh_history"
        if history.exists():
            try:
                _, out = self._run_cmd(f"wc -l < {history}")
                lines = int(out.strip()) if out.strip().isdigit() else 0
                if lines > 100000:
                    shell_issues.append(("MEDIUM", "Large zsh history", f"{lines} lines affects startup/search speed."))
                _, file_out = self._run_cmd(f"file {history}")
                if "ASCII" not in file_out:
                    shell_issues.append(("HIGH", "Corrupted zsh history", "Run 'msp tune apply' to repair."))
            except Exception:
                pass

        zshrc = Path.home() / ".zshrc"
        if zshrc.exists():
            text = zshrc.read_text()
            dupes = len(re.findall(r"export PATH=.*antigravity", text)) - 1
            if dupes > 0:
                shell_issues.append(("LOW", "Duplicate PATH entries", f"{dupes} duplicate Antigravity IDE entries."))

        return shell_issues

    def doctor(self, verbose: bool = False) -> bool:
        """Run dependency check and fix issues."""
        print("Running msp doctor...\n")
        results = self.check_all()

        issues = []
        for name, status in results.items():
            if status != DepStatus.INSTALLED:
                dep = self.deps[name]
                if dep.get("required"):
                    issues.append((name, "required", dep))

        if issues:
            print(f"Missing required dependencies:\n")
            for name, req_type, dep in issues:
                print(f"  - {name}: {dep.get('description', '')}")
                print(f"    Install: {dep.get('install_cmd', 'N/A')}\n")
        else:
            print("  All required dependencies are installed.\n")

        # Shell performance checks
        shell_issues = self._shell_startup_check()
        if shell_issues:
            print("Shell performance:\n")
            for severity, title, detail in shell_issues:
                color = {"HIGH": "red", "MEDIUM": "yellow", "LOW": "cyan"}.get(severity, "white")
                if RICH_AVAILABLE:
                    print(f"  [{color}]{severity}[/{color}] {title}")
                else:
                    print(f"  [{severity}] {title}")
                print(f"       {detail}\n")
        else:
            print("  Shell performance: OK\n")

        if issues and not verbose:
            print("Run 'msp doctor --fix' to install missing dependencies.")

        return len(issues) == 0 and len(shell_issues) == 0

    def fix(self) -> bool:
        """Install missing required dependencies."""
        print("Installing missing required dependencies...\n")
        results = self.install_required()

        all_success = True
        for name, success, msg in results:
            status = "✓" if success else "✗"
            print(f"{status} {name}: {msg}")
            if not success:
                all_success = False

        return all_success


def interactive_menu(manager: DependencyManager, json_output: bool = False):
    """Interactive menu for dependency manager."""
    actions = [
        ("1", "status", "Show all dependency status"),
        ("2", "check", "Check a specific package"),
        ("3", "install", "Install a package"),
        ("4", "fix", "Install missing required deps"),
        ("5", "install-all", "Install all missing packages"),
    ]

    sort_options = ["name", "status", "required"]
    current_sort = "name"

    while True:
        action = cmd_interactive_menu([
            ("1", "status", "Show all dependency status"),
            ("2", "check", "Check a specific package"),
            ("3", "install", "Install a package"),
            ("4", "fix", "Install missing required deps"),
            ("5", "install-all", "Install all missing packages"),
            ("s", "sort", f"Change sort order (current: {current_sort})"),
        ], title="Dependency Manager - Interactive Mode")

        if action is None:
            print("Goodbye!")
            break

        if action == "s":
            sort_items = [(o, o + (" *" if o == current_sort else ""), None) for o in sort_options]
            sort_val = interactive_select(sort_items, title="Sort options")
            if sort_val:
                current_sort = sort_val[0]
                print(f"Sort set to: {current_sort}")
            continue

        if action == "status":
            manager.status_table(json_output=json_output, sort_by=current_sort)
        elif action == "check":
            name = input("Package name: ").strip()
            if name:
                status = manager.check_dep(name)
                print(f"{name}: {status.value}")
            else:
                print("Package name required")
        elif action == "install":
            name = input("Package name: ").strip()
            if name:
                success, msg = manager.install_dep(name)
                print(msg)
            else:
                print("Package name required")
        elif action == "fix":
            manager.fix()
        elif action == "install-all":
            results = manager.install_all()
            for name, success, msg in results:
                print(f"{'✓' if success else '✗'} {name}: {msg}")

        input("\nPress Enter to continue...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Dependency Manager")
    parser.add_argument("action", nargs="?", choices=["status", "check", "install", "fix", "install-all", ""], help="Action to perform (omit for interactive mode)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues")
    parser.add_argument("--install", metavar="PKG", help="Install specific package")
    parser.add_argument("--check", metavar="PKG", help="Check specific package")
    parser.add_argument("--sort", choices=["name", "status", "required"], help="Sort by: name, status, required")
    setup_completion(parser)
    args = parser.parse_args()

    manager = DependencyManager()

    if not args.action or args.action == "":
        interactive_menu(manager, args.json)
        return

    if args.check:
        status = manager.check_dep(args.check)
        print(f"{args.check}: {status.value}")
        sys.exit(0 if status == DepStatus.INSTALLED else 1)

    if args.install:
        success, msg = manager.install_dep(args.install)
        print(msg)
        sys.exit(0 if success else 1)

    if args.fix:
        manager.fix()
    else:
        manager.status_table(json_output=args.json, sort_by=args.sort or "name")


if __name__ == "__main__":
    main()