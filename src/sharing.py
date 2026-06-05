#!/usr/bin/env python3
"""Sharing management module for msp CLI."""

import json
import subprocess
import os
import sys
from typing import List, Dict, Any, Optional

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


class SharingManager:
    """Manage macOS sharing services."""

    SHARING_TYPES = {
        "smb": "SMB (Windows sharing)",
        "afp": "AFP (Apple File Sharing)",
        "ftp": "FTP",
        "sftp": "SFTP (Secure FTP)",
    }

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
        except Exception as e:
            return False, str(e)

    def list_share_points(self) -> List[Dict[str, Any]]:
        """List all configured share points."""
        shares = []
        success, output = self._run_cmd("sharing -l")

        if success and output:
            current_share = {}
            for line in output.split('\n'):
                line = line.strip()
                if not line:
                    if current_share:
                        shares.append(current_share)
                        current_share = {}
                    continue

                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower().replace(' ', '_')
                    value = value.strip()
                    current_share[key] = value

            if current_share:
                shares.append(current_share)

        return shares

    def get_sharing_status(self) -> Dict[str, Any]:
        """Get overall sharing status."""
        status = {
            "sharing_enabled": False,
            "share_points": [],
            "services": {}
        }

        success, output = self._run_cmd("launchctl list | grep -E '(smb|afp|sharing)'")
        if success and "sharing" in output.lower():
            status["sharing_enabled"] = True

        status["share_points"] = self.list_share_points()

        for svc in ["com.apple.smbd", "com.apple.afpd", "com.apple.ftpd"]:
            svc_name = svc.split('.')[-1]
            success, output = self._run_cmd(f"launchctl list | grep {svc_name}")
            status["services"][svc_name] = success and output.strip() != ""

        return status

    def disable_share(self, share_name: str) -> bool:
        """Disable a share point by name."""
        shares = self.list_share_points()
        for share in shares:
            if share.get("name", "").lower() == share_name.lower():
                path = share.get("path", "")
                if path:
                    success, _ = self._run_cmd(f"sharing -r '{path}'", sudo=True)
                    if success:
                        print(f"Disabled: {share_name}")
                        return True
        print(f"Share not found: {share_name}")
        return False

    def disable_guest_access(self, share_name: str = None) -> bool:
        """Disable guest access for a share or all shares."""
        if share_name:
            shares = [s for s in self.list_share_points() if s.get("name", "").lower() == share_name.lower()]
        else:
            shares = self.list_share_points()

        for share in shares:
            guest = share.get("guest_access", "0")
            if guest == "1":
                path = share.get("path", "")
                if path:
                    self._run_cmd(f"sharing -e '{path}' -g no", sudo=True)
                    print(f"Guest disabled: {share.get('name', path)}")

        return True

    def disable_all_sharing(self) -> bool:
        """Disable all sharing services."""
        services = [
            "sudo launchctl unload /System/Library/LaunchDaemons/com.apple.smbd.plist",
            "sudo launchctl unload /System/Library/LaunchDaemons/com.apple.afpd.plist",
        ]

        for svc in services:
            self._run_cmd(svc)

        self.disable_guest_access()
        print("All sharing services disabled")
        return True

    def enable_share(self, path: str, name: str = None, guest: bool = False) -> bool:
        """Enable sharing for a path."""
        if not os.path.exists(path):
            print(f"Path does not exist: {path}")
            return False

        if name is None:
            name = os.path.basename(path)

        cmd = f"sharing -s '{path}' -n '{name}'"
        if guest:
            cmd += " -g on"
        else:
            cmd += " -g off"

        success, output = self._run_cmd(cmd, sudo=True)
        if success:
            print(f"Shared: {name} at {path}")
            return True
        else:
            print(f"Failed: {output}")
            return False

    def _sort_shares(self, shares: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
        """Sort shares by the specified key."""
        if sort_by == "name":
            return sorted(shares, key=lambda x: x.get("name", "").lower())
        elif sort_by == "path":
            return sorted(shares, key=lambda x: x.get("path", "").lower())
        elif sort_by == "guest":
            return sorted(shares, key=lambda x: x.get("guest_access", "0"), reverse=True)
        elif sort_by == "readonly":
            return sorted(shares, key=lambda x: x.get("read_only", "0"), reverse=True)
        return shares

    def show_status(self, json_output: bool = False, sort_by: str = "name") -> None:
        """Display sharing status."""
        status = self.get_sharing_status()

        if json_output:
            print(status)
            return

        shares = self._sort_shares(status.get('share_points', []), sort_by)

        if RICH_AVAILABLE and console:
            console.print("\n[bold]macOS Sharing Status[/bold]\n")

            console.print(f"[cyan]Sharing Daemon:[/cyan] {'Running' if status.get('sharing_enabled') else 'Stopped'}")

            console.print(f"\n[cyan]Active Services:[/cyan]")
            for svc, active in status.get('services', {}).items():
                state = "[green]Running[/green]" if active else "[red]Stopped[/red]"
                console.print(f"  {svc}: {state}")

            console.print(f"\n[cyan]Share Points ({len(shares)}):[/cyan]")

            if shares:
                table = Table()
                table.add_column("Name", style="cyan")
                table.add_column("Path")
                table.add_column("Guest", style="yellow")
                table.add_column("Read-only")

                for share in shares:
                    guest = "[green]Yes[/green]" if share.get("guest_access") == "1" else "[red]No[/red]"
                    ro = "[green]Yes[/green]" if share.get("read-only") == "1" else "[red]No[/red]"
                    table.add_row(
                        share.get("name", "Unknown"),
                        share.get("path", "Unknown"),
                        guest,
                        ro
                    )
                console.print(table)
            else:
                console.print("  No share points configured")

            console.print()
        else:
            print("=== macOS Sharing Status ===\n")
            print(f"Sharing: {'Enabled' if status.get('sharing_enabled') else 'Disabled'}")
            for svc, active in status.get('services', {}).items():
                print(f"  {svc}: {'on' if active else 'off'}")
            print(f"\nShare Points: {len(shares)}")
            for share in shares:
                guest = "guest" if share.get("guest_access") == "1" else "no-guest"
                print(f"  - {share.get('name')}: {share.get('path')} ({guest})")


def interactive_menu(manager: SharingManager, json_output: bool = False):
    """Interactive menu for sharing manager."""
    actions = [
        ("1", "list", "List share points and status"),
        ("2", "disable", "Disable a share"),
        ("3", "disable-guest", "Disable guest access"),
        ("4", "enable", "Enable sharing for a path"),
        ("5", "stop-all", "Disable all sharing services"),
        ("q", "quit", "Exit"),
    ]

    sort_options = {
        "list": ["name", "path", "guest", "readonly"],
    }
    current_sort = {"list": "name"}

    while True:
        print("\n" + "=" * 60)
        print("       Sharing Manager - Interactive Mode")
        print("=" * 60)
        for key, action, desc in actions:
            print(f"  {key:>2}. {action:<12} - {desc}")
        print("  s. sort      - Change sort order")
        print("=" * 60)

        choice = input("\nSelect action [1-5, s, q]: ").strip().lower()

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
            "1": "list",
            "2": "disable",
            "3": "disable-guest",
            "4": "enable",
            "5": "stop-all",
        }

        if choice in action_map:
            action = action_map[choice]
        elif choice in [a[1] for a in actions]:
            action = choice
        else:
            print(f"Invalid choice: {choice}")
            continue

        if action == "list":
            manager.show_status(json_output=json_output, sort_by=current_sort["list"])
        elif action == "disable":
            name = input("Share name to disable: ").strip()
            if name:
                manager.disable_share(name)
            else:
                print("Share name required")
        elif action == "disable-guest":
            name = input("Share name (optional, Enter for all): ").strip() or None
            manager.disable_guest_access(name)
        elif action == "enable":
            path = input("Path to share: ").strip()
            if path:
                name = input("Share name (optional): ").strip() or None
                guest = input("Allow guest access? [y/N]: ").strip().lower() == 'y'
                manager.enable_share(path, name=name, guest=guest)
            else:
                print("Path required")
        elif action == "stop-all":
            confirm = input("Disable ALL sharing services? [y/N]: ").strip().lower()
            if confirm == 'y':
                manager.disable_all_sharing()
            else:
                print("Cancelled")

        input("\nPress Enter to continue...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Sharing Manager")
    parser.add_argument("action", nargs="?", choices=["list", "status", "disable", "disable-guest", "enable", "stop-all"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("name", nargs="?", help="Share name or path")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--sort", choices=["name", "path", "guest", "readonly"], help="Sort by: name, path, guest, readonly")
    args = parser.parse_args()

    manager = SharingManager(verbose=args.verbose)

    if not args.action:
        interactive_menu(manager, args.json)
        return

    if args.action in ("list", "status"):
        manager.show_status(json_output=args.json, sort_by=args.sort or "name")

    elif args.action == "disable":
        if not args.name:
            print("Usage: msp sharing disable <name>")
        else:
            manager.disable_share(args.name)

    elif args.action == "disable-guest":
        manager.disable_guest_access(args.name)

    elif args.action == "enable":
        if not args.name:
            print("Usage: msp sharing enable <path>")
        else:
            manager.enable_share(args.name)

    elif args.action == "stop-all":
        print("Disabling all sharing services and guest access...")
        manager.disable_all_sharing()


if __name__ == "__main__":
    main()