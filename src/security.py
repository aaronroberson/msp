#!/usr/bin/env python3
"""Security settings module for msp CLI - lock, sleep, screen saver."""

import subprocess
import os
import sys

try:
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


class SecuritySettings:
    """Manage macOS security settings."""

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

    def lock_screen(self) -> bool:
        """Lock the screen immediately."""
        success, _ = self._run_cmd("/usr/bin/pmset displaysleepnow")
        if not success:
            success, _ = self._run_cmd("osascript -e 'tell application \"System Events\" to keystroke \"q\" using {command down, control down}'")
        return success

    def sleep_display(self) -> bool:
        """Put display to sleep."""
        success, _ = self._run_cmd("/usr/bin/pmset displaysleepnow")
        return success

    def sleep_computer(self) -> bool:
        """Put computer to sleep."""
        success, _ = self._run_cmd("pmset sleepnow")
        return success

    def get_display_settings(self) -> dict:
        """Get current display/screen saver settings."""
        settings = {}

        success, output = self._run_cmd("defaults -currentHost read com.apple.screensaver")
        if success and output:
            for line in output.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    settings[key.strip()] = value.strip()

        success, output = self._run_cmd("defaults -currentHost read com.apple.screensaver askForPassword")
        if success:
            settings['password_after_sleep'] = output.strip() == '1'

        success, output = self._run_cmd("defaults -currentHost read com.apple.screensaver askForPasswordDelay")
        if success:
            try:
                settings['password_delay'] = int(output.strip())
            except ValueError:
                settings['password_delay'] = 0

        return settings

    def get_energy_settings(self) -> dict:
        """Get energy/power settings."""
        settings = {}

        success, output = self._run_cmd("pmset -g")
        if success:
            for line in output.split('\n'):
                if 'sleep' in line.lower():
                    settings['sleep_on_power'] = line.strip()
                elif 'display sleep' in line.lower():
                    settings['display_sleep'] = line.strip()
                elif 'disksleep' in line.lower():
                    settings['disk_sleep'] = line.strip()
                elif 'standbydelay' in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        settings['standby_delay'] = parts[1]

        return settings

    def set_screen_lock(self, minutes: int = 5) -> bool:
        """Set screen to lock after X minutes."""
        self._run_cmd(f"defaults -currentHost write com.apple.screensaver idleTime {minutes * 60}")
        success, _ = self._run_cmd("killall Screensaver 2>/dev/null || true")
        return True

    def enable_password_after_sleep(self, delay: int = 0) -> bool:
        """Require password after sleep/screen saver."""
        self._run_cmd(f"defaults -currentHost write com.apple.screensaver askForPassword -int 1")
        self._run_cmd(f"defaults -currentHost write com.apple.screensaver askForPasswordDelay -int {delay}")
        return True

    def disable_password_after_sleep(self) -> bool:
        """Do not require password after sleep."""
        self._run_cmd("defaults -currentHost write com.apple.screensaver askForPassword -int 0")
        return True

    def set_display_sleep(self, minutes: int, power: bool = True) -> bool:
        """Set display sleep time in minutes."""
        success, _ = self._run_cmd(f"pmset -a displaysleep {minutes}")
        return success

    def get_firewall_connection_info(self) -> dict:
        """Get firewall and connection info."""
        info = {}

        success, output = self._run_cmd("/usr/libexec/ApplicationFirewall/socketfilterfw --getblockall")
        if success:
            info['block_all'] = "on" in output.lower()

        success, output = self._run_cmd("/usr/libexec/ApplicationFirewall/socketfilterfw --getloggingmode")
        if success:
            info['logging'] = output.strip()

        return info

    def show_status(self, json_output: bool = False) -> None:
        """Display security settings status."""
        display = self.get_display_settings()
        energy = self.get_energy_settings()
        fw = self.get_firewall_connection_info()

        if json_output:
            import json
            print(json.dumps({
                "display": display,
                "energy": energy,
                "firewall": fw
            }, indent=2))
            return

        if RICH_AVAILABLE and console:
            console.print("\n[bold]macOS Security Settings[/bold]\n")

            idle = display.get('idleTime', '0')
            idle_min = int(idle) // 60 if idle.isdigit() else 0
            console.print(f"[cyan]Screen Lock:[/cyan] {idle_min} minutes")

            pwd_delay = display.get('password_delay', 0)
            pwd_req = display.get('password_after_sleep', False)
            console.print(f"[cyan]Password after sleep:[/cyan] {'Yes' if pwd_req else 'No'} (delay: {pwd_delay}s)")

            disp_sleep = energy.get('display_sleep', 'Unknown')
            if 'display sleep' in disp_sleep.lower():
                parts = disp_sleep.split()
                for i, p in enumerate(parts):
                    if p.lower() == 'sleep' and i > 0:
                        console.print(f"[cyan]Display Sleep:[/cyan] {parts[i-1]} minutes")
                        break

            console.print(f"[cyan]Firewall logging:[/cyan] {fw.get('logging', 'Unknown')}")
            console.print(f"[cyan]Block all:[/cyan] {'Yes' if fw.get('block_all') else 'No'}")

            console.print()
        else:
            print("=== macOS Security Settings ===\n")
            print(f"Screen lock: {int(idle)//60 if idle.isdigit() else 0} min")
            print(f"Password after sleep: {pwd_req} (delay: {pwd_delay}s)")
            print(f"Display sleep: {energy.get('display_sleep', 'Unknown')}")

    def set_setting(self, key: str, value: str = None) -> bool:
        """Set a specific setting."""
        commands = {
            "lock-time": f"defaults -currentHost write com.apple.screensaver idleTime {int(value) * 60}",
            "password-delay": f"defaults -currentHost write com.apple.screensaver askForPasswordDelay -int {value}",
            "password-enable": "defaults -currentHost write com.apple.screensaver askForPassword -int 1",
            "password-disable": "defaults -currentHost write com.apple.screensaver askForPassword -int 0",
            "display-sleep": f"pmset -a displaysleep {value}",
        }

        if key in commands:
            success, _ = self._run_cmd(commands[key])
            if success:
                print(f"Set {key} = {value}")
            return success

        print(f"Unknown setting: {key}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Security Settings")
    parser.add_argument("action", choices=["status", "lock", "sleep", "set"])
    parser.add_argument("key", nargs="?", help="Setting key")
    parser.add_argument("value", nargs="?", help="Setting value")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose")

    args = parser.parse_args()
    ss = SecuritySettings(verbose=args.verbose)

    if args.action == "status":
        ss.show_status(json_output=args.json)
    elif args.action == "lock":
        ss.lock_screen()
    elif args.action == "sleep":
        ss.sleep_display()
    elif args.action == "set":
        if args.key:
            ss.set_setting(args.key, args.value)
        else:
            print("Usage: msp security set <key> [value]")


if __name__ == "__main__":
    main()