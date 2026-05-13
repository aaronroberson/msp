#!/usr/bin/env python3
"""Dependency manager for msp CLI."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any

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

    def status_table(self, json_output: bool = False) -> None:
        """Show dependency status table."""
        results = self.check_all()

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

        if not issues:
            print("All required dependencies are installed.")
            return True

        print(f"Found {len(issues)} missing required dependencies:\n")
        for name, req_type, dep in issues:
            print(f"  - {name}: {dep.get('description', '')}")
            print(f"    Install: {dep.get('install_cmd', 'N/A')}\n")

        if not verbose:
            print("Run 'msp doctor --fix' to install missing dependencies.")

        return False

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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Dependency Manager")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues")
    parser.add_argument("--install", metavar="PKG", help="Install specific package")
    parser.add_argument("--check", metavar="PKG", help="Check specific package")
    args = parser.parse_args()

    manager = DependencyManager()

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
        manager.status_table(json_output=args.json)


if __name__ == "__main__":
    main()