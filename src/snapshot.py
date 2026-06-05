#!/usr/bin/env python3
"""Snapshot module for msp CLI - save/restore/watch security settings."""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime

try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


@dataclass
class SnapshotSettings:
    firewall: bool
    firewall_stealth: bool
    gatekeeper: bool
    filevault: bool
    captive_portal: bool
    bluetooth: bool


@dataclass
class Snapshot:
    version: str
    timestamp: str
    hostname: str
    os_version: str
    settings: Dict[str, Any]
    custom_settings: Dict[str, Any]


class SnapshotManager:
    """Manage security setting snapshots."""

    SNAPSHOT_DIR = os.path.expanduser("~/.msp/snapshots")
    DEFAULT_SNAPSHOT = "default"

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        os.makedirs(self.SNAPSHOT_DIR, exist_ok=True)

    def _run_cmd(self, cmd: str, sudo: bool = False) -> tuple[bool, str]:
        try:
            if sudo:
                cmd = f"sudo {cmd}"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    def _get_hostname(self) -> str:
        success, output = self._run_cmd("hostname")
        return output.strip() if success else "unknown"

    def _get_os_version(self) -> str:
        success, output = self._run_cmd("sw_vers -productVersion")
        return output.strip() if success else "unknown"

    def _check_firewall(self) -> bool:
        success, output = self._run_cmd(
            "/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate"
        )
        return success and "enabled" in output.lower()

    def _check_stealth(self) -> bool:
        success, output = self._run_cmd(
            "/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode"
        )
        return success and "is on" in output.lower()

    def _check_gatekeeper(self) -> bool:
        success, output = self._run_cmd("spctl --status")
        return success and "assessments enabled" in output

    def _check_filevault(self) -> bool:
        success, output = self._run_cmd("fdesetup status")
        return success and "FileVault is On" in output

    def _check_captive_portal(self) -> bool:
        success, output = self._run_cmd(
            "defaults read /Library/Preferences/SystemConfiguration/com.apple.captive.control Active"
        )
        return success and "true" in output.lower()

    def _check_bluetooth(self) -> bool:
        success, output = self._run_cmd("blueutil power")
        return success and "1" in output

    def capture(self, name: str = None, include_network: bool = False,
                include_startup: bool = False, include_custom: bool = True) -> str:
        """Capture current system state to a snapshot."""
        if name is None:
            name = datetime.now().strftime("%Y%m%d_%H%M%S")

        snapshot_path = os.path.join(self.SNAPSHOT_DIR, f"{name}.json")

        snapshot = {
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "hostname": self._get_hostname(),
            "os_version": self._get_os_version(),
            "settings": {
                "firewall": self._check_firewall(),
                "firewall_stealth": self._check_stealth(),
                "gatekeeper": self._check_gatekeeper(),
                "filevault": self._check_filevault(),
                "captive_portal": self._check_captive_portal(),
                "bluetooth": self._check_bluetooth(),
            },
            "network": {},
            "startup": {},
            "custom_settings": {},
        }

        if include_network:
            snapshot["network"] = self._capture_network()

        if include_startup:
            snapshot["startup"] = self._capture_startup()

        if include_custom:
            snapshot["custom_settings"] = self._load_custom_settings()

        with open(snapshot_path, 'w') as f:
            json.dump(snapshot, f, indent=2)

        print(f"Snapshot saved: {snapshot_path}")
        return snapshot_path

    def _capture_network(self) -> Dict[str, Any]:
        """Capture network state."""
        network = {"listening": [], "established": []}

        success, output = self._run_cmd("lsof -iTCP -sTCP:LISTEN -nP 2>/dev/null | tail -n +2")
        if success and output.strip():
            for line in output.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        network["listening"].append({
                            "process": parts[0],
                            "pid": int(parts[1]),
                            "port": parts[8].split(":")[-1] if ":" in parts[8] else parts[8],
                        })
                    except (ValueError, IndexError):
                        pass

        return network

    def _capture_startup(self) -> List[str]:
        """Capture startup items."""
        items = []
        success, output = self._run_cmd("launchctl list 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    items.append(parts[2])
        return items

    def _load_custom_settings(self) -> Dict[str, Any]:
        """Load custom settings from config."""
        config_path = os.path.join(os.path.expanduser("~/.msp"), "settings.json")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    return json.load(f)
            except json.JSONDecodeError:
                pass
        return {}

    def _sort_snapshots(self, snapshots: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
        """Sort snapshots by the specified key."""
        if sort_by == "name":
            return sorted(snapshots, key=lambda x: x["name"].lower())
        elif sort_by == "timestamp":
            return sorted(snapshots, key=lambda x: x["timestamp"], reverse=True)
        elif sort_by == "hostname":
            return sorted(snapshots, key=lambda x: x["hostname"].lower())
        return snapshots

    def list_snapshots(self, json_output: bool = False, sort_by: str = "timestamp") -> List[Dict[str, Any]]:
        """List all available snapshots."""
        snapshots = []

        for f in os.listdir(self.SNAPSHOT_DIR):
            if f.endswith('.json'):
                path = os.path.join(self.SNAPSHOT_DIR, f)
                with open(path, 'r') as fp:
                    try:
                        data = json.load(fp)
                        snapshots.append({
                            "name": f.replace('.json', ''),
                            "path": path,
                            "timestamp": data.get("timestamp", "unknown"),
                            "hostname": data.get("hostname", "unknown"),
                            "settings": data.get("settings", {}),
                        })
                    except json.JSONDecodeError:
                        pass

        snapshots = self._sort_snapshots(snapshots, sort_by)

        if json_output:
            print(json.dumps(snapshots, indent=2))
            return snapshots

        if RICH_AVAILABLE and console:
            table = Table(title="Snapshots")
            table.add_column("Name", style="cyan")
            table.add_column("Timestamp", style="green")
            table.add_column("Hostname", style="yellow")
            table.add_column("Settings", style="magenta")

            for s in snapshots:
                settings = s["settings"]
                setting_str = ", ".join(f"{k}: {v}" for k, v in settings.items())
                table.add_row(s["name"], s["timestamp"][:19], s["hostname"], setting_str[:60])
            console.print(table)
        else:
            for s in snapshots:
                print(f"{s['name']}: {s['timestamp']} ({s['hostname']})")

        return snapshots

    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """Load a snapshot."""
        path = os.path.join(self.SNAPSHOT_DIR, f"{name}.json")
        if not os.path.exists(path):
            print(f"Snapshot not found: {name}")
            return None

        with open(path, 'r') as f:
            return json.load(f)

    def diff(self, name: str, json_output: bool = False) -> List[Dict[str, Any]]:
        """Compare current state to a snapshot."""
        snapshot = self.load(name)
        if not snapshot:
            return []

        current = {
            "firewall": self._check_firewall(),
            "firewall_stealth": self._check_stealth(),
            "gatekeeper": self._check_gatekeeper(),
            "filevault": self._check_filevault(),
            "captive_portal": self._check_captive_portal(),
            "bluetooth": self._check_bluetooth(),
        }

        diffs = []
        for key in snapshot.get("settings", {}):
            snap_val = snapshot["settings"].get(key)
            curr_val = current.get(key)
            if snap_val != curr_val:
                diffs.append({
                    "setting": key,
                    "snapshot_value": snap_val,
                    "current_value": curr_val,
                    "status": "changed"
                })

        if json_output:
            print(json.dumps(diffs, indent=2))
            return diffs

        if diffs:
            if RICH_AVAILABLE and console:
                table = Table(title=f"Differences from {name}")
                table.add_column("Setting", style="cyan")
                table.add_column("Snapshot", style="yellow")
                table.add_column("Current", style="red")
                for d in diffs:
                    table.add_row(d["setting"], str(d["snapshot_value"]), str(d["current_value"]))
                console.print(table)
            else:
                print(f"\nDifferences from {name}:")
                for d in diffs:
                    print(f"  {d['setting']}: snapshot={d['snapshot_value']}, current={d['current_value']}")
        else:
            print("No differences - system matches snapshot")

        return diffs

    def restore(self, name: str, dry_run: bool = False, force: bool = False) -> bool:
        """Restore settings from a snapshot."""
        snapshot = self.load(name)
        if not snapshot:
            return False

        settings = snapshot.get("settings", {})
        restored = []
        failed = []

        check_methods = {
            "firewall": self._check_firewall,
            "firewall_stealth": self._check_stealth,
            "gatekeeper": self._check_gatekeeper,
            "filevault": self._check_filevault,
            "captive_portal": self._check_captive_portal,
            "bluetooth": self._check_bluetooth,
        }

        print(f"Restoring settings from: {name}")
        if dry_run:
            print("(DRY RUN - no changes made)")

        for setting, desired in settings.items():
            check_fn = check_methods.get(setting)
            if not check_fn:
                print(f"  {setting}: no check method, skipping")
                continue

            current = check_fn()

            if current == desired:
                print(f"  {setting}: already correct ({current})")
                continue

            if dry_run:
                print(f"  {setting}: would change {current} -> {desired}")
                restored.append(setting)
                continue

            success = self._apply_setting(setting, desired)
            if success:
                print(f"  {setting}: restored to {desired}")
                restored.append(setting)
            else:
                print(f"  {setting}: FAILED to restore")
                failed.append(setting)

        if failed:
            print(f"\nFailed to restore: {', '.join(failed)}")
            return False

        if dry_run:
            print(f"\nWould restore: {', '.join(restored)}")
        else:
            print(f"\nRestored: {', '.join(restored)}")
        return True

    def _apply_setting(self, setting: str, value: bool) -> bool:
        """Apply a single setting."""
        if setting == "firewall":
            cmd = f"/usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate {'on' if value else 'off'}"
            success, _ = self._run_cmd(cmd, sudo=True)
            if success:
                self._run_cmd("sudo pkill -HUP socketfilterfw", sudo=True)
            return success

        elif setting == "firewall_stealth":
            cmd = f"/usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode {'on' if value else 'off'}"
            success, _ = self._run_cmd(cmd, sudo=True)
            if success:
                self._run_cmd("sudo pkill -HUP socketfilterfw", sudo=True)
            return success

        elif setting == "captive_portal":
            cmd = f"defaults write /Library/Preferences/SystemConfiguration/com.apple.captive.control Active -bool {'true' if value else 'false'}"
            return self._run_cmd(cmd, sudo=True)[0]

        elif setting == "bluetooth":
            cmd = f"blueutil --power {'1' if value else '0'}"
            return self._run_cmd(cmd)[0]

        return False

    def watch(self, name: str, interval: int = 300, auto_restore: bool = False) -> None:
        """Watch a snapshot and ensure system matches."""
        snapshot = self.load(name)
        if not snapshot:
            return

        watch_pid_file = os.path.expanduser("~/.msp/snapshot_watch.pid")
        watch_config_file = os.path.expanduser("~/.msp/snapshot_watch_config.json")

        with open(watch_pid_file, 'w') as f:
            f.write(str(os.getpid()))

        with open(watch_config_file, 'w') as f:
            json.dump({
                "snapshot_name": name,
                "auto_restore": auto_restore,
                "interval": interval,
                "started_at": datetime.now().isoformat()
            }, f)

        print(f"Watching snapshot: {name}")
        print(f"Checking every {interval} seconds")
        print(f"Auto-restore: {'enabled' if auto_restore else 'disabled'}")
        print("Press Ctrl+C to stop\n")

        try:
            while True:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Checking...")

                diffs = self.diff(name)
                if not diffs:
                    print("  ✓ System matches snapshot")
                else:
                    print(f"  Found {len(diffs)} difference(s)")

                    if auto_restore:
                        print("  Auto-restoring...")
                        self.restore(name)
                    else:
                        print("  Run 'msp snapshot restore {name}' to fix")

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\nStopped watching.")
        finally:
            for f in [watch_pid_file, watch_config_file]:
                if os.path.exists(f):
                    os.remove(f)

    def delete(self, name: str) -> bool:
        """Delete a snapshot."""
        path = os.path.join(self.SNAPSHOT_DIR, f"{name}.json")
        if not os.path.exists(path):
            print(f"Snapshot not found: {name}")
            return False

        os.remove(path)
        print(f"Deleted: {name}")
        return True


def interactive_menu(manager: SnapshotManager, json_output: bool = False):
    """Interactive menu for snapshot manager."""
    actions = [
        ("1", "capture", "Capture current system state"),
        ("2", "list", "List all snapshots"),
        ("3", "diff", "Compare current state to snapshot"),
        ("4", "restore", "Restore settings from snapshot"),
        ("5", "watch", "Watch snapshot for drift"),
        ("6", "delete", "Delete a snapshot"),
        ("q", "quit", "Exit"),
    ]

    sort_options = {
        "list": ["name", "timestamp", "hostname"],
    }
    current_sort = {"list": "timestamp"}

    while True:
        print("\n" + "=" * 60)
        print("       Snapshot Manager - Interactive Mode")
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
            "1": "capture",
            "2": "list",
            "3": "diff",
            "4": "restore",
            "5": "watch",
            "6": "delete",
        }

        if choice in action_map:
            action = action_map[choice]
        elif choice in [a[1] for a in actions]:
            action = choice
        else:
            print(f"Invalid choice: {choice}")
            continue

        if action == "capture":
            name = input("Snapshot name (default: timestamp): ").strip()
            name = name or datetime.now().strftime("%Y%m%d_%H%M%S")
            include_net = input("Include network state? [y/N]: ").strip().lower() == 'y'
            include_startup = input("Include startup items? [y/N]: ").strip().lower() == 'y'
            manager.capture(name=name, include_network=include_net, include_startup=include_startup)
        elif action == "list":
            manager.list_snapshots(json_output=json_output, sort_by=current_sort["list"])
        elif action == "diff":
            name = input("Snapshot name: ").strip()
            if name:
                manager.diff(name, json_output=json_output)
            else:
                print("Snapshot name required")
        elif action == "restore":
            name = input("Snapshot name: ").strip()
            if name:
                dry_run = input("Dry run? [y/N]: ").strip().lower() == 'y'
                manager.restore(name, dry_run=dry_run)
            else:
                print("Snapshot name required")
        elif action == "watch":
            name = input("Snapshot name [default]: ").strip() or "default"
            interval = input("Interval seconds [300]: ").strip()
            interval = int(interval) if interval.isdigit() else 300
            auto_restore = input("Auto-restore on drift? [y/N]: ").strip().lower() == 'y'
            manager.watch(name, interval=interval, auto_restore=auto_restore)
        elif action == "delete":
            name = input("Snapshot name: ").strip()
            if name:
                manager.delete(name)
            else:
                print("Snapshot name required")

        input("\nPress Enter to continue...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Snapshot Manager")
    parser.add_argument("action", nargs="?", choices=["capture", "list", "diff", "restore", "watch", "delete"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("name", nargs="?", help="Snapshot name")
    parser.add_argument("--interval", type=int, default=300, help="Watch interval in seconds")
    parser.add_argument("--auto-restore", action="store_true", help="Auto-restore on drift")
    parser.add_argument("--include-network", action="store_true", help="Include network state")
    parser.add_argument("--include-startup", action="store_true", help="Include startup items")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--sort", choices=["name", "timestamp", "hostname"], help="Sort by: name, timestamp, hostname")
    args = parser.parse_args()

    manager = SnapshotManager(verbose=args.verbose)

    if not args.action:
        interactive_menu(manager, args.json)
        return

    if args.action == "capture":
        name = args.name or datetime.now().strftime("%Y%m%d_%H%M%S")
        manager.capture(
            name=name,
            include_network=args.include_network,
            include_startup=args.include_startup
        )

    elif args.action == "list":
        manager.list_snapshots(json_output=args.json, sort_by=args.sort or "timestamp")

    elif args.action == "diff":
        if not args.name:
            print("Error: snapshot name required")
            sys.exit(1)
        manager.diff(args.name, json_output=args.json)

    elif args.action == "restore":
        if not args.name:
            print("Error: snapshot name required")
            sys.exit(1)
        manager.restore(args.name, dry_run=args.dry_run, force=args.force)

    elif args.action == "watch":
        name = args.name or "default"
        manager.watch(name, interval=args.interval, auto_restore=args.auto_restore)

    elif args.action == "delete":
        if not args.name:
            print("Error: snapshot name required")
            sys.exit(1)
        manager.delete(args.name)


if __name__ == "__main__":
    main()
