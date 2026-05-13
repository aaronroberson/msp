#!/usr/bin/env python3
"""Sharing management module for msp CLI."""

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

    def show_status(self, json_output: bool = False) -> None:
        """Display sharing status."""
        status = self.get_sharing_status()

        if json_output:
            print(status)
            return

        if RICH_AVAILABLE and console:
            console.print("\n[bold]macOS Sharing Status[/bold]\n")

            console.print(f"[cyan]Sharing Daemon:[/cyan] {'Running' if status.get('sharing_enabled') else 'Stopped'}")

            console.print(f"\n[cyan]Active Services:[/cyan]")
            for svc, active in status.get('services', {}).items():
                state = "[green]Running[/green]" if active else "[red]Stopped[/red]"
                console.print(f"  {svc}: {state}")

            shares = status.get('share_points', [])
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Sharing Manager")
    parser.add_argument("action", choices=["list", "status", "disable", "disable-guest", "enable", "stop-all"])
    parser.add_argument("name", nargs="?", help="Share name or path")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose")

    args = parser.parse_args()
    manager = SharingManager(verbose=args.verbose)

    if args.action in ("list", "status"):
        manager.show_status(json_output=args.json)

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