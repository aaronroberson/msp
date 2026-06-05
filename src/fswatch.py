#!/usr/bin/env python3
"""File system watcher module for msp CLI."""

import os
import json
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


@dataclass
class FileEvent:
    path: str
    event_type: str
    timestamp: str
    process: Optional[str] = None


class FileWatcher:
    """Monitor file system events."""

    SYSTEM_DIRS = [
        "/Library/LaunchAgents",
        "/Library/LaunchDaemons",
        "/Library/Application Support",
        "/usr/local/bin",
        "/etc",
    ]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._running = False
        self._events = []

    def _run_cmd(self, cmd: str, sudo: bool = False) -> tuple[bool, str]:
        try:
            if sudo:
                cmd = f"sudo {cmd}"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=120
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def watch(self, path: str, recursive: bool = True, timeout: Optional[int] = None) -> None:
        """Watch a directory for changes using fswatch."""
        if not os.path.exists(path):
            print(f"Path does not exist: {path}")
            return

        print(f"Watching: {path}")
        print("Press Ctrl+C to stop...\n")

        recursive_flag = "-r" if recursive else ""
        cmd = f"fswatch {recursive_flag} -x -o {path}"

        try:
            proc = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, text=True
            )

            event_flags = {
                "Created": "📄",
                "Updated": "✏️",
                "Removed": "🗑️",
                "Renamed": "📝",
                "OwnerModified": "👤",
                "AttributeModified": "⚙️",
                "Mount": "🔗",
                "Unmount": "🔓",
            }

            while True:
                line = proc.stdout.readline()
                if not line:
                    break

                parts = line.strip().split(None, 1)
                if len(parts) >= 2:
                    flags, file_path = parts
                    flag_list = []
                    for flag in flags.split("|"):
                        flag_list.append(event_flags.get(flag, flag))

                    print(f"{' | '.join(flag_list)} {file_path}")

        except KeyboardInterrupt:
            print("\nStopped.")
            proc.terminate()

    def _sort_events(self, events: List, sort_by: str, event_type: str = "recent") -> List:
        """Sort events by the specified key."""
        if event_type == "recent":
            if sort_by == "timestamp":
                return sorted(events, key=lambda x: x["timestamp"])
            elif sort_by == "call":
                return sorted(events, key=lambda x: x["call"])
            elif sort_by == "process":
                return sorted(events, key=lambda x: x["process"])
            elif sort_by == "path":
                return sorted(events, key=lambda x: x["path"])
        elif event_type == "new":
            if sort_by == "path":
                return sorted(events)
            elif sort_by == "age":
                # Already sorted by age from find command
                return events
        elif event_type == "audit":
            if sort_by == "path":
                return sorted(events, key=lambda x: x["path"])
            elif sort_by == "directory":
                return sorted(events, key=lambda x: x["directory"])
            elif sort_by == "warning":
                return sorted(events, key=lambda x: x.get("warning", ""))
        return events

    def recent(self, seconds: int = 60, json_output: bool = False, sort_by: str = "timestamp") -> List[Dict[str, str]]:
        """Show recent file system events using fs_usage."""
        print(f"Monitoring file system for {seconds} seconds...")

        cmd = f"sudo fs_usage -f filesys -t {seconds} 2>/dev/null"

        success, output = self._run_cmd(cmd, sudo=True)

        events = []
        if success and output.strip():
            for line in output.strip().split('\n'):
                parts = line.split(None, 6)
                if len(parts) >= 5:
                    events.append({
                        "timestamp": parts[0],
                        "call": parts[2] if len(parts) > 2 else "",
                        "process": parts[3] if len(parts) > 3 else "",
                        "path": parts[4] if len(parts) > 4 else "",
                    })

        events = self._sort_events(events, sort_by, event_type="recent")

        if json_output:
            print(json.dumps(events, indent=2))
            return events

        if RICH_AVAILABLE and console:
            table = Table(title=f"Recent File System Events (Last {seconds}s)")
            table.add_column("Time", style="cyan")
            table.add_column("Call", style="yellow")
            table.add_column("Process", style="green")
            table.add_column("Path", style="magenta")

            for e in events[-50:]:
                table.add_row(e["timestamp"], e["call"], e["process"], e["path"][:60])
            console.print(table)
        else:
            for e in events[-30:]:
                print(f"{e['timestamp']} {e['call']:<10} {e['process']:<15} {e['path'][:50]}")

        return events

    def watch_system(self, timeout: Optional[int] = None) -> None:
        """Watch system directories for changes."""
        print("Watching system directories...")
        print("Press Ctrl+C to stop...\n")

        cmd = "sudo fs_usage -f filesys 2>/dev/null"
        if timeout:
            cmd = f"timeout {timeout} {cmd}"

        try:
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, text=True)

            system_paths = ["/Library", "/etc", "/System", "/usr/local"]
            important_events = []

            for line in proc.stdout:
                for sp in system_paths:
                    if sp in line:
                        parts = line.strip().split(None, 6)
                        if len(parts) >= 5:
                            event = f"{parts[0]} {parts[2]:<10} {parts[3]:<15} {parts[4]}"
                            print(event)

        except KeyboardInterrupt:
            print("\nStopped.")
            proc.terminate()

    def find_new(self, directory: str = None, days: int = 1, json_output: bool = False, sort_by: str = "path") -> List[str]:
        """Find recently created files in directory."""
        if directory is None:
            directories = [
                "/Library/LaunchAgents",
                "/Library/LaunchDaemons",
                "/Applications",
                "/usr/local/bin",
            ]
        else:
            directories = [directory]

        new_files = []
        for d in directories:
            if os.path.exists(d):
                success, output = self._run_cmd(
                    f"find '{d}' -type f -mtime -{days} 2>/dev/null"
                )
                if success and output.strip():
                    for f in output.strip().split('\n'):
                        if f:
                            new_files.append(f)

        new_files = self._sort_events(new_files, sort_by, event_type="new")

        if json_output:
            print(json.dumps(new_files, indent=2))
            return new_files

        if new_files:
            if RICH_AVAILABLE and console:
                table = Table(title=f"Recently Created Files (Last {days} day(s))")
                table.add_column("Path", style="cyan")
                for f in new_files:
                    table.add_row(f)
                console.print(table)
            else:
                print(f"Recent files (last {days} day(s)):")
                for f in new_files:
                    print(f"  {f}")
        else:
            print(f"No files created in the last {days} day(s).")

        return new_files

    def diff_config(self, file_path: str) -> bool:
        """Show differences from last known state of a config file."""
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return False

        baseline_dir = os.path.expanduser("~/.msp/baselines")
        os.makedirs(baseline_dir, exist_ok=True)

        baseline_file = os.path.join(
            baseline_dir,
            file_path.replace("/", "_").replace(".", "_") + ".baseline"
        )

        if os.path.exists(baseline_file):
            print(f"Baseline exists. Comparing...")
            success, current = self._run_cmd(f"cat '{file_path}'")
            success2, baseline_content = self._run_cmd(f"cat '{baseline_file}'")

            if success and success2:
                import difflib
                current_lines = current.splitlines(keepends=True)
                baseline_lines = baseline_content.splitlines(keepends=True)

                diff = list(difflib.unified_diff(
                    baseline_lines, current_lines,
                    fromfile="baseline", tofile="current"
                ))

                if diff:
                    print("Changes detected:")
                    for line in diff[:50]:
                        print(line, end="")
                else:
                    print("No changes detected.")

            confirm = input("Update baseline? [y/N] ")
            if confirm.lower() == 'y':
                self._run_cmd(f"cp '{file_path}' '{baseline_file}'")
                print("Baseline updated.")
        else:
            print("No baseline. Creating...")
            self._run_cmd(f"cp '{file_path}' '{baseline_file}'")
            print(f"Baseline created at {baseline_file}")

        return True

    def audit(self, json_output: bool = False, sort_by: str = "path") -> List[Dict[str, Any]]:
        """Audit system directories for suspicious changes."""
        print("Auditing system directories for suspicious changes...")

        suspicious = []
        directories = [
            "/Library/LaunchAgents",
            "/Library/LaunchDaemons",
            "/usr/local/bin",
            "/tmp",
        ]

        for directory in directories:
            if os.path.exists(directory):
                success, output = self._run_cmd(
                    f"find '{directory}' -type f -mtime -7 2>/dev/null"
                )
                if success and output.strip():
                    for f in output.strip().split('\n'):
                        if f:
                            item = {
                                "path": f,
                                "directory": directory,
                                "age_days": "<7"
                            }

                            if not f.endswith(".plist"):
                                item["warning"] = "Non-plist in Launch directory"
                                suspicious.append(item)
                            else:
                                success2, sig = self._run_cmd(
                                    f"codesign -dvvv '{f}' 2>/dev/null"
                                )
                                if success2 and "not signed" in sig.lower():
                                    item["warning"] = "Unsigned plist"
                                    suspicious.append(item)

        suspicious = self._sort_events(suspicious, sort_by, event_type="audit")

        if json_output:
            print(json.dumps(suspicious, indent=2))
            return suspicious

        if suspicious:
            if RICH_AVAILABLE and console:
                table = Table(title="Suspicious File System Changes")
                table.add_column("Path", style="red")
                table.add_column("Directory", style="yellow")
                table.add_column("Warning", style="magenta")
                for item in suspicious:
                    table.add_row(item["path"][:50], item["directory"], item.get("warning", ""))
                console.print(table)
            else:
                print("Suspicious changes found:")
                for item in suspicious:
                    print(f"  {item['path']}")
                    if "warning" in item:
                        print(f"    Warning: {item['warning']}")
        else:
            print("No suspicious changes found.")

        return suspicious


def interactive_menu(watcher: FileWatcher, json_output: bool = False):
    """Interactive menu for file system watcher."""
    actions = [
        ("1", "watch", "Watch a directory for changes"),
        ("2", "recent", "Show recent file system events"),
        ("3", "system", "Watch system directories"),
        ("4", "new", "Find recently created files"),
        ("5", "diff", "Diff config file from baseline"),
        ("6", "audit", "Audit system directories for suspicious changes"),
        ("q", "quit", "Exit"),
    ]

    sort_options = {
        "recent": ["timestamp", "call", "process", "path"],
        "new": ["path", "age"],
        "audit": ["path", "directory", "warning"],
    }
    current_sort = {"recent": "timestamp", "new": "path", "audit": "path"}

    while True:
        print("\n" + "=" * 60)
        print("       File System Watcher - Interactive Mode")
        print("=" * 60)
        for key, action, desc in actions:
            print(f"  {key:>2}. {action:<12} - {desc}")
        print("  s. sort      - Change sort order")
        print("=" * 60)

        choice = input("\nSelect action [1-6, s, q]: ").strip().lower()

        if choice == "q" or choice == "quit":
            print("Goodbye!")
            break

        if choice == "s" or choice == "sort":
            print("\nSelect command to change sort for:")
            sortable_actions = [a for a in actions if a[1] in sort_options]
            for i, (key, action_name, desc) in enumerate(sortable_actions, 1):
                print(f"  {i}. {desc} (current: {current_sort[action_name]})")
            cmd_choice = input(f"\nSelect [1-{len(sortable_actions)}]: ").strip()
            try:
                cmd_idx = int(cmd_choice) - 1
                if 0 <= cmd_idx < len(sortable_actions):
                    cmd = sortable_actions[cmd_idx][1]
                    opts = sort_options[cmd]
                    print(f"\nSort options for {sortable_actions[cmd_idx][2]}:")
                    for i, opt in enumerate(opts, 1):
                        marker = " *" if opt == current_sort[cmd] else ""
                        print(f"  {i}. {opt}{marker}")
                    sort_choice = input(f"\nSelect sort [1-{len(opts)}]: ").strip()
                    idx = int(sort_choice) - 1
                    if 0 <= idx < len(opts):
                        current_sort[cmd] = opts[idx]
                        print(f"Sort set to: {current_sort[cmd]}")
                    else:
                        print("Invalid choice")
                else:
                    print("Invalid choice")
            except ValueError:
                print("Invalid choice")
            continue

        action_map = {
            "1": "watch",
            "2": "recent",
            "3": "system",
            "4": "new",
            "5": "diff",
            "6": "audit",
        }

        if choice in action_map:
            action = action_map[choice]
        elif choice in [a[1] for a in actions]:
            action = choice
        else:
            print(f"Invalid choice: {choice}")
            continue

        if action == "watch":
            path = input("Path to watch: ").strip()
            if path:
                watcher.watch(path)
            else:
                print("Path required")
        elif action == "recent":
            seconds = input("Seconds to monitor [60]: ").strip()
            seconds = int(seconds) if seconds.isdigit() else 60
            watcher.recent(seconds=seconds, json_output=json_output, sort_by=current_sort["recent"])
        elif action == "system":
            watcher.watch_system()
        elif action == "new":
            directory = input("Directory to search (default: system dirs): ").strip() or None
            days = input("Days back [1]: ").strip()
            days = int(days) if days.isdigit() else 1
            watcher.find_new(directory=directory, days=days, json_output=json_output, sort_by=current_sort["new"])
        elif action == "diff":
            path = input("File path to diff: ").strip()
            if path:
                watcher.diff_config(path)
            else:
                print("Path required")
        elif action == "audit":
            watcher.audit(json_output=json_output, sort_by=current_sort["audit"])

        input("\nPress Enter to continue...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp File System Watcher")
    parser.add_argument("action", nargs="?", choices=["watch", "recent", "system", "new", "diff", "audit"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("path", nargs="?", help="Path to watch or diff")
    parser.add_argument("--seconds", type=int, default=60, help="Seconds for recent command")
    parser.add_argument("--days", type=int, default=1, help="Days for new files")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--sort", choices=["timestamp", "call", "process", "path", "age", "directory", "warning"], help="Sort by: timestamp, call, process, path, age, directory, warning")
    args = parser.parse_args()

    watcher = FileWatcher(verbose=args.verbose)

    if not args.action:
        interactive_menu(watcher, args.json)
        return

    if args.action == "watch":
        if not args.path:
            print("Error: path required for watch")
            sys.exit(1)
        watcher.watch(args.path)
    elif args.action == "recent":
        watcher.recent(seconds=args.seconds, json_output=args.json, sort_by=args.sort or "timestamp")
    elif args.action == "system":
        watcher.watch_system()
    elif args.action == "new":
        watcher.find_new(directory=args.path, days=args.days, json_output=args.json, sort_by=args.sort or "path")
    elif args.action == "diff":
        if not args.path:
            print("Error: path required for diff")
            sys.exit(1)
        watcher.diff_config(args.path)
    elif args.action == "audit":
        watcher.audit(json_output=args.json, sort_by=args.sort or "path")


if __name__ == "__main__":
    main()