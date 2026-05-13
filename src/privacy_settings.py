#!/usr/bin/env python3
"""
macos-privacy-cli: A CLI tool for managing macOS privacy and security settings.

This tool allows you to:
- List all available privacy and security settings
- View current values of settings
- Update settings based on security best practices
- Apply preset configurations from security guides (drduh, term7)

Shell Completion:
  To enable tab completion in zsh, add the completion script to your .zshrc:
  
  Add to ~/.zshrc:
    # msp completion
    _msp_complete() {
        local cur prev opts
        COMPREPLY=()
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]}"
        
        local commands="list status enable disable services preset"
        local preset_cmds="list apply save delete"
        local presets="basic paranoid drduh term7 nist"
        local settings="Application\ Firewall Firewall\ Stealth\ Mode Gatekeeper FileVault\ Encryption Captive\ Portal\ Probe"
        local categories="Firewall Privacy Security Services DNS Telemetry System"
        
        case "${prev}" in
            msp)
                COMPREPLY=($(compgen -W "${commands}" -- ${cur}))
                return 0
                ;;
            list)
                COMPREPLY=($(compgen -W "--category --json" -- ${cur}))
                return 0
                ;;
            enable|disable)
                COMPREPLY=($(compgen -W "${settings}" -- ${cur}))
                return 0
                ;;
            preset)
                COMPREPLY=($(compgen -W "${preset_cmds}" -- ${cur}))
                return 0
                ;;
            apply)
                COMPREPLY=($(compgen -W "${presets} --dry-run" -- ${cur}))
                return 0
                ;;
            services)
                COMPREPLY=($(compgen -W "list --json" -- ${cur}))
                return 0
                ;;
            --category)
                COMPREPLY=($(compgen -W "${categories}" -- ${cur}))
                return 0
                ;;
            save|delete)
                COMPREPLY=($(compgen -W "${presets}" -- ${cur}))
                return 0
                ;;
        esac
    }
    complete -F _msp_complete msp
"""

import argparse
import subprocess
import json
import os
import sys
import shlex
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any, Callable
from enum import Enum

try:
    from argcomplete import warn
    ARGCOMPLETE_AVAILABLE = True
except ImportError:
    ARGCOMPLETE_AVAILABLE = False

try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


console = Console() if RICH_AVAILABLE else None


class SettingCategory(Enum):
    FIREWALL = "Firewall"
    PRIVACY = "Privacy"
    SECURITY = "Security"
    SERVICES = "Services"
    DNS = "DNS"
    TELEMETRY = "Telemetry"
    SYSTEM = "System"


class SettingState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


@dataclass
class PrivacySetting:
    name: str
    category: SettingCategory
    description: str
    command: str
    check_command: str
    enable_value: str
    disable_value: str
    requires_root: bool = True
    applies_to: str = "all"


class PrivacySettingsManager:
    """Manager for macOS privacy and security settings."""

    SETTINGS: List[PrivacySetting] = [
        # Firewall Settings
        PrivacySetting(
            name="Application Firewall",
            category=SettingCategory.FIREWALL,
            description="Built-in macOS firewall - blocks incoming connections",
            command="/usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate",
            check_command="/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate",
            enable_value="on",
            disable_value="off",
        ),
        PrivacySetting(
            name="Firewall Stealth Mode",
            category=SettingCategory.FIREWALL,
            description="Prevents computer from responding to ICMP ping and closed port probes",
            command="/usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode",
            check_command="/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode",
            enable_value="on",
            disable_value="off",
        ),
        PrivacySetting(
            name="Signed App Auto-Allow",
            category=SettingCategory.FIREWALL,
            description="Automatically allow signed applications (Apple-signed apps always allowed)",
            command="/usr/libexec/ApplicationFirewall/socketfilterfw --setallowsigned",
            check_command="/usr/libexec/ApplicationFirewall/socketfilterfw --getallowsigned",
            enable_value="on",
            disable_value="off",
            requires_root=False,
        ),
        PrivacySetting(
            name="Signed App Downloaded Auto-Allow",
            category=SettingCategory.FIREWALL,
            description="Automatically allow downloaded signed applications",
            command="/usr/libexec/ApplicationFirewall/socketfilterfw --setallowsignedapp",
            check_command="/usr/libexec/ApplicationFirewall/socketfilterfw --getallowsignedapp",
            enable_value="on",
            disable_value="off",
            requires_root=False,
        ),

        # Privacy Settings
        PrivacySetting(
            name="Location Services",
            category=SettingCategory.PRIVACY,
            description="Location-based services for apps",
            command="defaults write /var/db/locationd/Library/LaunchDaemons/com.apple.locationd.plist",
            check_command="defaults read /var/db/locationd/Library/LaunchDaemons/com.apple.locationd.plist",
            enable_value="",
            disable_value="",
        ),
        PrivacySetting(
            name="Diagnostics & Usage Data",
            category=SettingCategory.PRIVACY,
            description="Send diagnostic data to Apple",
            command="defaults write /Library/Application\\ Support/CrashReporter/DiagnosticReportsHistory",
            check_command="defaults read /Library/Application\\ Support/CrashReporter/DiagnosticReportsHistory",
            enable_value="",
            disable_value="",
        ),
        PrivacySetting(
            name="Spotlight Suggestions",
            category=SettingCategory.TELEMETRY,
            description="Send search queries to Apple for Spotlight Suggestions",
            command="defaults write com.apple.spotlight hasUsedSavedSearches",
            check_command="defaults read com.apple.spotlight hasUsedSavedSearches",
            enable_value="",
            disable_value="",
            requires_root=False,
        ),
        PrivacySetting(
            name="Siri Suggestions",
            category=SettingCategory.TELEMETRY,
            description="Siri learns from usage patterns and sends data to Apple",
            command="defaults write com.apple.assistant.useSiriData",
            check_command="defaults read com.apple.assistant.useSiriData",
            enable_value="",
            disable_value="",
            requires_root=False,
        ),

        # System Settings
        PrivacySetting(
            name="FileVault Encryption",
            category=SettingCategory.SECURITY,
            description="Full disk encryption - protects data at rest",
            command="fdesetup enable",
            check_command="fdesetup status",
            enable_value="",
            disable_value="",
        ),
        PrivacySetting(
            name="Gatekeeper",
            category=SettingCategory.SECURITY,
            description="App signature verification before execution",
            command="spctl --enable",
            check_command="spctl --status",
            enable_value="",
            disable_value="",
        ),
        PrivacySetting(
            name="System Integrity Protection",
            category=SettingCategory.SECURITY,
            description="Prevents modification of protected system files (requires recovery mode to check)",
            command="csrutil status",
            check_command="csrutil status",
            enable_value="",
            disable_value="",
        ),

        # DNS Settings
        PrivacySetting(
            name="Captive Portal Probe",
            category=SettingCategory.DNS,
            description="Automatic network probe on new connections (security risk)",
            command="defaults write /Library/Preferences/SystemConfiguration/com.apple.captive.control Active -bool",
            check_command="defaults read /Library/Preferences/SystemConfiguration/com.apple.captive.control Active",
            enable_value="false",
            disable_value="false",
        ),

        # Services
        PrivacySetting(
            name="Remote Management (ARD)",
            category=SettingCategory.SERVICES,
            description="Apple Remote Desktop - allows remote access",
            command="sudo /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart",
            check_command="sudo /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart -target",
            enable_value="",
            disable_value="",
        ),
        PrivacySetting(
            name="Bluetooth",
            category=SettingCategory.SERVICES,
            description="Bluetooth wireless connection",
            command="blueutil",
            check_command="blueutil power",
            enable_value="1",
            disable_value="0",
        ),
    ]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.presets_dir = os.path.join(os.path.dirname(__file__), "presets")

    def run_command(self, cmd: str, shell: bool = True, capture: bool = True) -> tuple[bool, str]:
        """Run a shell command and return success status and output."""
        try:
            if self.verbose:
                print(f"Running: {cmd}")
            result = subprocess.run(
                cmd if shell else cmd.split(),
                shell=shell,
                capture_output=capture,
                text=True
            )
            return result.returncode == 0, result.stdout + result.stderr
        except Exception as e:
            return False, str(e)

    def get_firewall_status(self) -> Dict[str, Any]:
        """Get detailed firewall status."""
        status = {"enabled": False, "stealth_mode": False, "allows_signed": False}
        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate")
        if success and "enabled" in output.lower():
            status["enabled"] = True

        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode")
        if success and "is on" in output.lower():
            status["stealth_mode"] = True

        return status

    def get_filevault_status(self) -> Dict[str, Any]:
        """Get FileVault encryption status."""
        status = {"enabled": False, "encrypted": False}
        success, output = self.run_command("fdesetup status")
        if success:
            status["enabled"] = "FileVault is On" in output
            status["encrypted"] = "Convert" in output or "On" in output
            if "Encrypted" in output:
                status["encrypted"] = True
        return status

    def get_gatekeeper_status(self) -> Dict[str, Any]:
        """Get Gatekeeper status."""
        status = {"enabled": False}
        success, output = self.run_command("spctl --status")
        if success:
            status["enabled"] = "assessments enabled" in output
        return status

    def get_bluetooth_status(self) -> Dict[str, Any]:
        """Get Bluetooth status."""
        status = {"enabled": False}
        success, output = self.run_command("blueutil power")
        if success and "1" in output:
            status["enabled"] = True
        return status

    def get_captive_portal_status(self) -> Dict[str, Any]:
        """Get Captive Portal probe status."""
        status = {"enabled": True}
        success, output = self.run_command("defaults read /Library/Preferences/SystemConfiguration/com.apple.captive.control Active")
        if success:
            status["enabled"] = "true" in output.lower()
        return status

    def get_launchd_services(self) -> List[Dict[str, str]]:
        """Get list of launchd services and their status."""
        services = []
        success, output = self.run_command("launchctl list | grep -v com.apple")
        if success:
            for line in output.strip().split('\n'):
                if line:
                    parts = line.split()
                    if len(parts) >= 3:
                        services.append({
                            "pid": parts[0],
                            "status": parts[1],
                            "name": ' '.join(parts[2:])
                        })
        return services

    def get_current_state(self, setting: PrivacySetting) -> SettingState:
        """Check current state of a setting."""
        if "firewall" in setting.name.lower():
            if setting.name == "Application Firewall":
                status = self.get_firewall_status()
                return SettingState.ENABLED if status.get("enabled") else SettingState.DISABLED
            elif setting.name == "Firewall Stealth Mode":
                status = self.get_firewall_status()
                return SettingState.ENABLED if status.get("stealth_mode") else SettingState.DISABLED
        elif "filevault" in setting.name.lower():
            status = self.get_filevault_status()
            return SettingState.ENABLED if status.get("enabled") else SettingState.DISABLED
        elif "gatekeeper" in setting.name.lower():
            status = self.get_gatekeeper_status()
            return SettingState.ENABLED if status.get("enabled") else SettingState.DISABLED
        elif "bluetooth" in setting.name.lower():
            status = self.get_bluetooth_status()
            return SettingState.ENABLED if status.get("enabled") else SettingState.DISABLED
        elif "captive" in setting.name.lower():
            status = self.get_captive_portal_status()
            return SettingState.ENABLED if status.get("enabled") else SettingState.DISABLED
        return SettingState.UNKNOWN

    def enable_setting(self, setting: PrivacySetting) -> bool:
        """Enable a specific setting."""
        if setting.name == "Application Firewall":
            success, _ = self.run_command("sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on")
            if success:
                self.run_command("sudo pkill -HUP socketfilterfw")
            return success
        elif setting.name == "Firewall Stealth Mode":
            success, _ = self.run_command("sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode on")
            if success:
                self.run_command("sudo pkill -HUP socketfilterfw")
            return success
        elif setting.name == "Captive Portal Probe":
            success, _ = self.run_command("sudo defaults write /Library/Preferences/SystemConfiguration/com.apple.captive.control Active -bool false")
            return success
        return False

    def disable_setting(self, setting: PrivacySetting) -> bool:
        """Disable a specific setting."""
        if setting.name == "Application Firewall":
            success, _ = self.run_command("sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate off")
            if success:
                self.run_command("sudo pkill -HUP socketfilterfw")
            return success
        elif setting.name == "Firewall Stealth Mode":
            success, _ = self.run_command("sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setstealthmode off")
            if success:
                self.run_command("sudo pkill -HUP socketfilterfw")
            return success
        elif setting.name == "Captive Portal Probe":
            success, _ = self.run_command("sudo defaults write /Library/Preferences/SystemConfiguration/com.apple.captive.control Active -bool true")
            return success
        return False

    def list_settings(self, category: Optional[str] = None, json_output: bool = False) -> None:
        """List all available settings."""
        settings = self.SETTINGS

        if category:
            cat = next((c for c in SettingCategory if c.value.lower() == category.lower()), None)
            if cat:
                settings = [s for s in settings if s.category == cat]

        if json_output:
            output = []
            for s in settings:
                state = self.get_current_state(s)
                output.append({
                    "name": s.name,
                    "category": s.category.value,
                    "description": s.description,
                    "state": state.value,
                    "requires_root": s.requires_root
                })
            print(json.dumps(output, indent=2))
        elif RICH_AVAILABLE and console:
            table = Table(title="macOS Privacy & Security Settings")
            table.add_column("Setting", style="cyan")
            table.add_column("Category", style="magenta")
            table.add_column("State", style="yellow")
            table.add_column("Description")

            for s in settings:
                state = self.get_current_state(s)
                state_color = "green" if state == SettingState.ENABLED else "red" if state == SettingState.DISABLED else "yellow"
                table.add_row(
                    s.name,
                    s.category.value,
                    f"[{state_color}]{state.value}[/{state_color}]",
                    s.description
                )
            console.print(table)
        else:
            for s in settings:
                state = self.get_current_state(s)
                state_str = f"[{state.value}]"
                print(f"{state_str} {s.name} ({s.category.value})")
                print(f"    {s.description}")

    def list_services(self, json_output: bool = False) -> None:
        """List running services."""
        services = self.get_launchd_services()

        if json_output:
            print(json.dumps(services, indent=2))
        elif RICH_AVAILABLE and console:
            table = Table(title="Running LaunchD Services")
            table.add_column("PID")
            table.add_column("Status")
            table.add_column("Name", style="cyan")

            for s in services:
                table.add_row(s["pid"], s["status"], s["name"])
            console.print(table)
        else:
            for s in services:
                print(f"{s['pid']:>8} {s['status']:>6}  {s['name']}")

    def get_status(self, json_output: bool = False) -> None:
        """Get comprehensive status of all privacy/security settings."""
        status = {
            "firewall": self.get_firewall_status(),
            "filevault": self.get_filevault_status(),
            "gatekeeper": self.get_gatekeeper_status(),
            "bluetooth": self.get_bluetooth_status(),
            "captive_portal": self.get_captive_portal_status(),
        }

        if json_output:
            print(json.dumps(status, indent=2))
        elif RICH_AVAILABLE and console:
            console.print("\n[bold]macOS Privacy & Security Status[/bold]\n")

            fw = status["firewall"]
            console.print(f"[cyan]Firewall:[/cyan] {'Enabled' if fw.get('enabled') else 'Disabled'}")
            console.print(f"  Stealth Mode: {'Enabled' if fw.get('stealth_mode') else 'Disabled'}")

            fv = status["filevault"]
            console.print(f"[cyan]FileVault:[/cyan] {'Enabled' if fv.get('enabled') else 'Disabled'}")

            gk = status["gatekeeper"]
            console.print(f"[cyan]Gatekeeper:[/cyan] {'Enabled' if gk.get('enabled') else 'Disabled'}")

            bt = status["bluetooth"]
            console.print(f"[cyan]Bluetooth:[/cyan] {'Enabled' if bt.get('enabled') else 'Disabled'}")

            cp = status["captive_portal"]
            console.print(f"[cyan]Captive Portal Probe:[/cyan] {'Enabled' if cp.get('enabled') else 'Disabled'}")
            console.print()
        else:
            print("=== macOS Privacy & Security Status ===\n")
            print(f"Firewall: {status['firewall']}")
            print(f"FileVault: {status['filevault']}")
            print(f"Gatekeeper: {status['gatekeeper']}")
            print(f"Bluetooth: {status['bluetooth']}")
            print(f"Captive Portal: {status['captive_portal']}")


class PresetManager:
    """Manager for security preset configurations."""

    PRESETS = {
        "basic": {
            "name": "Basic Security",
            "description": "Essential security settings for everyday use",
            "settings": {
                "Application Firewall": True,
                "Firewall Stealth Mode": True,
                "Gatekeeper": True,
            }
        },
        "paranoid": {
            "name": "Paranoid Security",
            "description": "Maximum privacy with reduced functionality",
            "settings": {
                "Application Firewall": True,
                "Firewall Stealth Mode": True,
                "Gatekeeper": True,
                "Captive Portal Probe": False,
                "Signed App Auto-Allow": False,
                "Signed App Downloaded Auto-Allow": False,
            }
        },
        "drduh": {
            "name": "drduh Guide Recommendations",
            "description": "Settings based on github.com/drduh/macOS-Security-and-Privacy-Guide",
            "settings": {
                "Application Firewall": True,
                "Firewall Stealth Mode": True,
                "Gatekeeper": True,
                "Captive Portal Probe": False,
            }
        },
        "term7": {
            "name": "term7 Guide Recommendations",
            "description": "Settings based on github.com/term7/MacOS-Privacy-and-Security-Enhancements",
            "settings": {
                "Application Firewall": True,
                "Firewall Stealth Mode": True,
                "Gatekeeper": True,
                "Captive Portal Probe": False,
                "Signed App Auto-Allow": False,
                "Signed App Downloaded Auto-Allow": False,
            }
        }
    }

    def __init__(self, settings_manager: PrivacySettingsManager):
        self.manager = settings_manager

    def list_presets(self, json_output: bool = False) -> None:
        """List available presets."""
        if json_output:
            print(json.dumps(self.PRESETS, indent=2, default=str))
        elif RICH_AVAILABLE and console:
            table = Table(title="Available Security Presets")
            table.add_column("ID", style="cyan")
            table.add_column("Name", style="green")
            table.add_column("Description")

            for pid, preset in self.PRESETS.items():
                table.add_row(pid, preset["name"], preset["description"])
            console.print(table)
        else:
            for pid, preset in self.PRESETS.items():
                print(f"[{pid}] {preset['name']}")
                print(f"    {preset['description']}")
                print()

    def apply_preset(self, preset_id: str, dry_run: bool = False) -> bool:
        """Apply a preset configuration."""
        if preset_id not in self.PRESETS:
            print(f"Unknown preset: {preset_id}")
            return False

        preset = self.PRESETS[preset_id]
        print(f"Applying preset: {preset['name']}")
        print(f"Description: {preset['description']}\n")

        settings_by_name = {s.name: s for s in self.manager.SETTINGS}

        for setting_name, enable in preset["settings"].items():
            if setting_name not in settings_by_name:
                print(f"  [SKIP] Unknown setting: {setting_name}")
                continue

            setting = settings_by_name[setting_name]
            current_state = self.manager.get_current_state(setting)
            target_state = "enable" if enable else "disable"

            if current_state.value == target_state:
                print(f"  [OK] {setting_name} is already {target_state}d")
                continue

            if dry_run:
                print(f"  [DRY-RUN] Would {target_state} {setting_name}")
                continue

            if enable:
                success = self.manager.enable_setting(setting)
            else:
                success = self.manager.disable_setting(setting)

            if success:
                print(f"  [OK] {target_state}d {setting_name}")
            else:
                print(f"  [FAIL] Could not {target_state} {setting_name}")

        return True

    def save_preset(self, preset_id: str, settings: Dict[str, bool], name: str, description: str) -> bool:
        """Save a custom preset."""
        self.PRESETS[preset_id] = {
            "name": name,
            "description": description,
            "settings": settings
        }
        print(f"Saved preset: {preset_id}")
        return True

    def delete_preset(self, preset_id: str) -> bool:
        """Delete a custom preset."""
        if preset_id in ["basic", "paranoid", "drduh", "term7"]:
            print(f"Cannot delete built-in preset: {preset_id}")
            return False

        if preset_id in self.PRESETS:
            del self.PRESETS[preset_id]
            print(f"Deleted preset: {preset_id}")
            return True

        print(f"Preset not found: {preset_id}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="macOS Privacy & Security CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                              List all settings
  %(prog)s status                            Show current security status
  %(prog)s enable "Application Firewall"     Enable a setting
  %(prog)s disable "Firewall Stealth Mode"    Disable a setting
  %(prog)s preset list                       List available presets
  %(prog)s preset apply basic                Apply a preset
  %(prog)s preset apply paranoid --dry-run   Preview preset changes
  %(prog)s services list                     List running services

Presets:
  basic     - Essential security (firewall, stealth mode, gatekeeper)
  paranoid  - Maximum privacy with reduced functionality
  drduh     - Based on drduh's security guide
  term7     - Based on term7's privacy enhancements guide
        """
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="JSON output")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List command
    list_parser = subparsers.add_parser("list", help="List privacy/security settings")
    list_parser.add_argument("--category", help="Filter by category (Firewall, Privacy, Security, Services, DNS, Telemetry, System)")

    # Status command
    subparsers.add_parser("status", help="Show current security status")

    # Enable command
    enable_parser = subparsers.add_parser("enable", help="Enable a setting")
    enable_parser.add_argument("setting", help="Name of the setting to enable",
                               choices=["Application Firewall", "Firewall Stealth Mode", "Gatekeeper", "FileVault Encryption", "Captive Portal Probe", "Bluetooth"])

    # Disable command
    disable_parser = subparsers.add_parser("disable", help="Disable a setting")
    disable_parser.add_argument("setting", help="Name of the setting to disable",
                                choices=["Application Firewall", "Firewall Stealth Mode", "Captive Portal Probe", "Bluetooth"])

    # Services command
    services_parser = subparsers.add_parser("services", help="Manage services")
    services_parser.add_argument("action", nargs="?", default="list", choices=["list"])

    # Preset command
    preset_parser = subparsers.add_parser("preset", help="Manage presets")
    preset_parser.add_argument("action", choices=["list", "apply", "save", "delete"])
    preset_parser.add_argument("name", nargs="?", help="Preset name or ID",
                              choices=["basic", "paranoid", "drduh", "term7", "nist"])
    preset_parser.add_argument("--dry-run", action="store_true", help="Show what would be changed")
    preset_parser.add_argument("--settings", help="JSON settings for save action")
    preset_parser.add_argument("--description", help="Description for save action")

    args = parser.parse_args()

    if ARGCOMPLETE_AVAILABLE:
        try:
            import argcomplete
            argcomplete.autocomplete(parser)
        except Exception:
            pass

    manager = PrivacySettingsManager(verbose=args.verbose)
    preset_manager = PresetManager(manager)

    if args.command == "list":
        manager.list_settings(category=args.category, json_output=args.json)
    elif args.command == "status":
        manager.get_status(json_output=args.json)
    elif args.command == "enable":
        setting = next((s for s in manager.SETTINGS if s.name == args.setting), None)
        if setting:
            if manager.enable_setting(setting):
                print(f"Enabled: {setting.name}")
            else:
                print(f"Failed to enable: {setting.name}")
                sys.exit(1)
        else:
            print(f"Unknown setting: {args.setting}")
            sys.exit(1)
    elif args.command == "disable":
        setting = next((s for s in manager.SETTINGS if s.name == args.setting), None)
        if setting:
            if manager.disable_setting(setting):
                print(f"Disabled: {setting.name}")
            else:
                print(f"Failed to disable: {setting.name}")
                sys.exit(1)
        else:
            print(f"Unknown setting: {args.setting}")
            sys.exit(1)
    elif args.command == "services":
        if args.action == "list":
            manager.list_services(json_output=args.json)
    elif args.command == "preset":
        if args.action == "list":
            preset_manager.list_presets(json_output=args.json)
        elif args.action == "apply":
            if not args.name:
                print("Please specify a preset name")
                sys.exit(1)
            preset_manager.apply_preset(args.name, dry_run=args.dry_run)
        elif args.action == "save":
            if not args.name or not args.settings:
                print("Please provide name and --settings")
                sys.exit(1)
            import json
            try:
                settings = json.loads(args.settings)
                preset_manager.save_preset(args.name, settings, args.name, args.description or "")
            except json.JSONDecodeError:
                print("Invalid JSON in --settings")
                sys.exit(1)
        elif args.action == "delete":
            if not args.name:
                print("Please specify a preset name")
                sys.exit(1)
            preset_manager.delete_preset(args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()