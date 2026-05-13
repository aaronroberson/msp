#!/usr/bin/env python3
"""Startup item manager for msp CLI."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


@dataclass
class StartupItem:
    name: str
    label: str
    path: str
    type: str
    status: str
    pid: Optional[int] = None
    user: Optional[str] = None


class StartupManager:
    """Manage macOS startup items."""

    LAUNCH_AGENT_PATHS = [
        os.path.expanduser("~/Library/LaunchAgents"),
        "/Library/LaunchAgents",
        "/System/Library/LaunchAgents",
    ]

    LAUNCH_DAEMON_PATHS = [
        "/Library/LaunchDaemons",
        "/System/Library/LaunchDaemons",
    ]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def _run_cmd(self, cmd: str, sudo: bool = False) -> tuple[bool, str]:
        try:
            if sudo:
                cmd = f"sudo {cmd}"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _read_plist_label(self, plist_path: str) -> Optional[str]:
        try:
            success, output = self._run_cmd(f"defaults read '{plist_path}' Label 2>/dev/null")
            if success and output.strip():
                return output.strip()
        except Exception:
            pass
        return os.path.basename(plist_path).replace(".plist", "")

    def list_all(self, json_output: bool = False) -> List[StartupItem]:
        """List all startup items."""
        items = []

        success, output = self._run_cmd("launchctl list 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    try:
                        pid = int(parts[0]) if parts[0] != "-" else None
                        status = parts[1]
                        label = parts[2]
                        item = StartupItem(
                            name=label.split(".")[-1] if "." in label else label,
                            label=label,
                            path="",
                            type="launchd",
                            status=status,
                            pid=pid
                        )
                        items.append(item)
                    except (ValueError, IndexError):
                        continue

        if json_output:
            print(json.dumps([{
                "name": i.name,
                "label": i.label,
                "path": i.path,
                "type": i.type,
                "status": i.status,
                "pid": i.pid
            } for i in items], indent=2))
            return items

        if RICH_AVAILABLE and console:
            table = Table(title="Startup Items")
            table.add_column("Name", style="cyan")
            table.add_column("Label", style="green")
            table.add_column("PID", style="yellow")
            table.add_column("Status")

            for item in items:
                table.add_row(
                    item.name[:30],
                    item.label[:40],
                    str(item.pid) if item.pid else "-",
                    item.status
                )
            console.print(table)
        else:
            print(f"{'Name':<30} {'Label':<50} {'PID':<8} {'Status'}")
            print("-" * 100)
            for item in items:
                print(f"{item.name:<30} {item.label:<50} {str(item.pid) if item.pid else '-':<8} {item.status}")

        return items

    def list_agents(self, json_output: bool = False) -> List[StartupItem]:
        """List user launch agents only."""
        items = []

        for path in [os.path.expanduser("~/Library/LaunchAgents"), "/Library/LaunchAgents"]:
            if os.path.exists(path):
                for f in os.listdir(path):
                    if f.endswith('.plist'):
                        plist_path = os.path.join(path, f)
                        label = self._read_plist_label(plist_path)
                        item = StartupItem(
                            name=f.replace('.plist', ''),
                            label=label or f.replace('.plist', ''),
                            path=plist_path,
                            type="agent",
                            status="unknown"
                        )
                        items.append(item)

        if json_output:
            print(json.dumps([{"name": i.name, "label": i.label, "path": i.path} for i in items], indent=2))
            return items

        if RICH_AVAILABLE and console:
            table = Table(title="User Launch Agents")
            table.add_column("Name", style="cyan")
            table.add_column("Label", style="green")
            table.add_column("Path", style="magenta")
            for item in items:
                table.add_row(item.name, item.label, item.path)
            console.print(table)
        else:
            for item in items:
                print(f"{item.name}: {item.label} -> {item.path}")

        return items

    def list_daemons(self, json_output: bool = False) -> List[StartupItem]:
        """List system daemons only."""
        items = []

        for path in self.LAUNCH_DAEMON_PATHS:
            if os.path.exists(path):
                for f in os.listdir(path):
                    if f.endswith('.plist'):
                        plist_path = os.path.join(path, f)
                        label = self._read_plist_label(plist_path)
                        item = StartupItem(
                            name=f.replace('.plist', ''),
                            label=label or f.replace('.plist', ''),
                            path=plist_path,
                            type="daemon",
                            status="unknown"
                        )
                        items.append(item)

        if json_output:
            print(json.dumps([{"name": i.name, "label": i.label, "path": i.path} for i in items], indent=2))
            return items

        if RICH_AVAILABLE and console:
            table = Table(title="System LaunchDaemons")
            table.add_column("Name", style="cyan")
            table.add_column("Label", style="green")
            table.add_column("Path", style="magenta")
            for item in items:
                table.add_row(item.name, item.label, item.path)
            console.print(table)
        else:
            for item in items:
                print(f"{item.name}: {item.label} -> {item.path}")

        return items

    def list_cron(self, json_output: bool = False) -> List[Dict[str, str]]:
        """List cron jobs."""
        success, output = self._run_cmd("crontab -l 2>/dev/null")

        jobs = []
        if success and output.strip():
            for line in output.strip().split('\n'):
                if line and not line.startswith("#"):
                    jobs.append({"entry": line})

        if json_output:
            print(json.dumps(jobs, indent=2))
            return jobs

        if not jobs:
            print("No cron jobs")
        else:
            print("Cron jobs:")
            for job in jobs:
                print(f"  {job['entry']}")

        return jobs

    def disable(self, label: str, force: bool = False) -> bool:
        """Disable a startup item."""
        user_domain = f"gui/{os.getuid()}"

        success, _ = self._run_cmd(f"launchctl bootout {user_domain}/{label} 2>/dev/null")
        if success:
            print(f"Disabled: {label}")
            return True

        success, _ = self._run_cmd(f"sudo launchctl bootout system/{label} 2>/dev/null", sudo=True)
        if success:
            print(f"Disabled (system): {label}")
            return True

        print(f"Could not disable: {label}")
        return False

    def enable(self, label: str) -> bool:
        """Enable a startup item."""
        user_domain = f"gui/{os.getuid()}"

        success, _ = self._run_cmd(f"launchctl bootstrap {user_domain} {label} 2>/dev/null")
        if success:
            print(f"Enabled: {label}")
            return True

        print(f"Could not enable: {label}")
        return False

    def audit(self, json_output: bool = False) -> List[Dict[str, Any]]:
        """Audit startup items for suspicious entries."""
        items = self.list_all()
        suspicious = []

        SUSPICIOUS_PATTERNS = [
            "update", "helper", "agent", "daemon", "service",
            "monitor", "scanner", "sync", "backup", "cloud"
        ]

        KNOWN_GOOD = [
            "com.apple.", "org.freedesktop.", "com.google.",
            "com.microsoft.", "com.adobe.", "com.1password.",
        ]

        for item in items:
            is_suspicious = False
            reasons = []

            label_lower = item.label.lower()

            if not any(item.label.startswith(good) for good in KNOWN_GOOD):
                if any(pat in label_lower for pat in SUSPICIOUS_PATTERNS):
                    is_suspicious = True
                    reasons.append("Contains suspicious keyword")

            if not item.path and item.type == "launchd":
                success, _ = self._run_cmd(f"launchctl print {item.label} 2>/dev/null")
                if not success:
                    is_suspicious = True
                    reasons.append("Cannot retrieve path")

            if item.pid and item.pid > 0:
                success, output = self._run_cmd(f"codesign -dvvv -p {item.pid} 2>/dev/null")
                if success and "not signed" in output.lower():
                    is_suspicious = True
                    reasons.append("Unsigned binary")

            if is_suspicious:
                suspicious.append({
                    "item": item.label,
                    "reasons": reasons,
                    "pid": item.pid,
                    "status": item.status
                })

        if json_output:
            print(json.dumps(suspicious, indent=2))
            return suspicious

        if suspicious:
            if RICH_AVAILABLE and console:
                table = Table(title="Suspicious Startup Items")
                table.add_column("Label", style="red")
                table.add_column("PID", style="yellow")
                table.add_column("Reasons", style="magenta")
                for item in suspicious:
                    table.add_row(item["item"], str(item["pid"]) or "-", ", ".join(item["reasons"]))
                console.print(table)
            else:
                print("Suspicious startup items found:")
                for item in suspicious:
                    print(f"  - {item['item']} (PID: {item['pid']})")
                    for r in item["reasons"]:
                        print(f"    * {r}")
        else:
            print("No suspicious startup items found.")

        return suspicious


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Startup Manager")
    parser.add_argument("action", choices=["list", "agents", "daemons", "cron", "disable", "enable", "audit"])
    parser.add_argument("label", nargs="?", help="Label to enable/disable")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    manager = StartupManager(verbose=args.verbose)

    if args.action == "list":
        manager.list_all(json_output=args.json)
    elif args.action == "agents":
        manager.list_agents(json_output=args.json)
    elif args.action == "daemons":
        manager.list_daemons(json_output=args.json)
    elif args.action == "cron":
        manager.list_cron(json_output=args.json)
    elif args.action == "disable":
        if not args.label:
            print("Error: label required for disable")
            sys.exit(1)
        manager.disable(args.label, force=args.force)
    elif args.action == "enable":
        if not args.label:
            print("Error: label required for enable")
            sys.exit(1)
        manager.enable(args.label)
    elif args.action == "audit":
        manager.audit(json_output=args.json)


if __name__ == "__main__":
    main()