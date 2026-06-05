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
        status = {"enabled": False, "stealth_mode": False, "allows_signed": False, "allows_signed_app": False, "exceptions": [], "incoming_allowed": 0, "outgoing_allowed": 0}

        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate")
        if success and "enabled" in output.lower():
            status["enabled"] = True

        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode")
        if success and "is on" in output.lower():
            status["stealth_mode"] = True

        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --getallowsigned")
        if success and "on" in output.lower():
            status["allows_signed"] = True

        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --getallowsignedapp")
        if success and "on" in output.lower():
            status["allows_signed_app"] = True

        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --listapps")
        if success:
            for line in output.split('\n'):
                if 'ALLOWED' in line.upper() or 'ENABLED' in line.upper():
                    parts = line.split()
                    if len(parts) >= 3:
                        status["exceptions"].append({
                            "name": ' '.join(parts[:-1]),
                            "status": parts[-1] if parts[-1] in ('ON', 'OFF') else 'ON'
                        })

        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --getincoming")
        if success:
            status["incoming_allowed"] = "deny" not in output.lower() and "allow" in output.lower()

        success, output = self.run_command("/usr/libexec/ApplicationFirewall/socketfilterfw --getoutgoing")
        if success:
            status["outgoing_allowed"] = "deny" not in output.lower()

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

    def get_last_scan_info(self) -> Dict[str, Any]:
        """Get info about last security scan."""
        report_dir = os.path.expanduser("~/.msp/reports")
        status = {"last_scan": None, "report_path": None, "scan_count": 0}

        if os.path.exists(report_dir):
            reports = [f for f in os.listdir(report_dir) if f.endswith('.json')]
            status["scan_count"] = len(reports)
            if reports:
                reports.sort(key=lambda x: os.path.getmtime(os.path.join(report_dir, x)), reverse=True)
                latest = reports[0]
                status["last_scan"] = datetime.fromtimestamp(os.path.getmtime(os.path.join(report_dir, latest))).isoformat()
                status["report_path"] = os.path.join(report_dir, latest)

        return status

    def get_snapshot_watch_status(self) -> Dict[str, Any]:
        """Check if snapshot watch is active."""
        watch_pid_file = os.path.expanduser("~/.msp/snapshot_watch.pid")
        status = {"enabled": False, "snapshot_name": None, "auto_restore": False}

        if os.path.exists(watch_pid_file):
            try:
                with open(watch_pid_file, 'r') as f:
                    pid = int(f.read().strip())
                    if os.path.exists(f"/proc/{pid}" if sys.platform == 'linux' else f"/bin/ps -p {pid} > /dev/null 2>&1"):
                        status["enabled"] = True
            except (ValueError, IOError):
                pass

            try:
                config_path = os.path.expanduser("~/.msp/snapshot_watch_config.json")
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                        status["snapshot_name"] = config.get("snapshot_name")
                        status["auto_restore"] = config.get("auto_restore", False)
            except (json.JSONDecodeError, IOError):
                pass

        return status

    def get_listening_services(self) -> List[Dict[str, Any]]:
        """Get services with listening ports and established connections."""
        services = []
        seen = set()

        success, output = self.run_command("lsof -iTCP -sTCP:LISTEN -nP 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        proc = parts[0]
                        pid = int(parts[1])
                        host_port = parts[8]

                        if ':' in host_port:
                            port = host_port.split(':')[-1]

                            if pid not in seen:
                                seen.add(pid)
                                services.append({
                                    "process": proc,
                                    "pid": pid,
                                    "port": port,
                                    "type": "listening",
                                    "risk": self._assess_risk(proc, port, "listening")
                                })
                    except (ValueError, IndexError):
                        pass

        success, output = self.run_command("lsof -iTCP -sTCP:ESTABLISHED -nP 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        proc = parts[0]
                        pid = int(parts[1])
                        host_port = parts[8]

                        if ':' in host_port:
                            port = host_port.split(':')[-1]
                            remote = parts[9] if len(parts) > 9 else ""

                            if pid not in seen:
                                seen.add(pid)
                                services.append({
                                    "process": proc,
                                    "pid": pid,
                                    "port": port,
                                    "type": "established",
                                    "remote": remote,
                                    "risk": self._assess_risk(proc, port, "established")
                                })
                    except (ValueError, IndexError):
                        pass

        return services

    def _assess_risk(self, process: str, port: str, conn_type: str) -> str:
        """Assess risk level of a service."""
        high_risk = ["apache", "httpd", "nginx", "mysql", "postgres", "redis", "mongodb", "ftp", "telnet", "rsh", "rlogin"]
        medium_risk = ["ssh", "vnc", "rdp", "samba", "nfs"]
        low_risk = ["localhost", "127.0.0.1"]

        proc_lower = process.lower()

        if proc_lower in high_risk:
            return "HIGH"
        if proc_lower in medium_risk:
            return "MEDIUM"
        if conn_type == "listening" and port not in ("22", "443", "993", "995", "465", "587"):
            return "REVIEW"
        return "LOW"

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

    def _sort_settings(self, settings: List["PrivacySetting"], sort_by: str) -> List["PrivacySetting"]:
        """Sort settings by the specified key."""
        if sort_by == "name":
            return sorted(settings, key=lambda x: x.name.lower())
        elif sort_by == "category":
            return sorted(settings, key=lambda x: (x.category.value, x.name.lower()))
        elif sort_by == "state":
            return sorted(settings, key=lambda x: (self.get_current_state(x).value, x.name.lower()))
        return settings

    def list_settings(self, category: Optional[str] = None, json_output: bool = False, sort_by: str = "name") -> None:
        """List all available settings."""
        settings = self.SETTINGS

        if category:
            cat = next((c for c in SettingCategory if c.value.lower() == category.lower()), None)
            if cat:
                settings = [s for s in settings if s.category == cat]

        settings = self._sort_settings(settings, sort_by)

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

    def _sort_services(self, services: List[Dict[str, str]], sort_by: str) -> List[Dict[str, str]]:
        """Sort services by the specified key."""
        if sort_by == "name":
            return sorted(services, key=lambda x: x.get("name", "").lower())
        elif sort_by == "status":
            return sorted(services, key=lambda x: x.get("status", ""))
        elif sort_by == "pid":
            return sorted(services, key=lambda x: int(x.get("pid", 0)) if x.get("pid", "").lstrip("-").isdigit() else 0)
        return services

    def list_services(self, json_output: bool = False, sort_by: str = "name") -> None:
        """List running services."""
        services = self._sort_services(self.get_launchd_services(), sort_by)

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
            "last_scan": self.get_last_scan_info(),
            "snapshot_watch": self.get_snapshot_watch_status(),
            "listening_services": self.get_listening_services(),
            "sharing": self.get_sharing_status(),
            "security": self.get_security_settings(),
        }

        if json_output:
            print(json.dumps(status, indent=2))
            return

        if not RICH_AVAILABLE or not console:
            self._print_status_text(status)
            return

        console.print("\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]")
        console.print("[bold]macOS Privacy & Security Status[/bold]")
        console.print("[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n")

        fw = status["firewall"]
        console.print("[bold yellow]FIREWALL[/bold yellow]")
        console.print(f"  Firewall: {'[green]Enabled[/green]' if fw.get('enabled') else '[red]Disabled[/red]'}")
        console.print(f"  Stealth Mode: {'[green]Enabled[/green]' if fw.get('stealth_mode') else '[red]Disabled[/red]'}")
        console.print(f"  Auto-allow signed: {'Yes' if fw.get('allows_signed') else 'No'}")
        console.print(f"  Auto-allow downloaded: {'Yes' if fw.get('allows_signed_app') else 'No'}")
        console.print(f"  Incoming: {'[red]Allowed[/red]' if fw.get('incoming_allowed') else '[green]Blocked[/green]'}")
        console.print(f"  Outgoing: {'[red]Allowed[/red]' if fw.get('outgoing_allowed') else '[green]Blocked[/green]'}")
        exceptions = fw.get('exceptions', [])
        console.print(f"  Exceptions: {len(exceptions)} app(s)" if exceptions else f"  Exceptions: [green]None[/green]")

        fv = status["filevault"]
        console.print(f"\n[bold yellow]ENCRYPTION[/bold yellow]")
        console.print(f"  FileVault: {'[green]Enabled[/green]' if fv.get('enabled') else '[red]Disabled[/red]'}")

        gk = status["gatekeeper"]
        console.print(f"\n[bold yellow]APP SECURITY[/bold yellow]")
        console.print(f"  Gatekeeper: {'[green]Enabled[/green]' if gk.get('enabled') else '[red]Disabled[/red]'}")

        bt = status["bluetooth"]
        console.print(f"\n[bold yellow]WIRELESS[/bold yellow]")
        console.print(f"  Bluetooth: {'[yellow]Enabled[/yellow]' if bt.get('enabled') else '[green]Disabled[/green]'}")

        cp = status["captive_portal"]
        console.print(f"  Captive Portal Probe: {'[red]Enabled[/red] (risk)' if cp.get('enabled') else '[green]Disabled[/green]'}")

        sharing = status["sharing"]
        console.print(f"\n[bold yellow]SHARING[/bold yellow]")
        console.print(f"  Sharing daemon: {'[yellow]Running[/yellow]' if sharing.get('sharing_enabled') else '[green]Stopped[/green]'}")
        shares = sharing.get('share_points', [])
        if shares:
            console.print(f"  Share points: [yellow]{len(shares)}[/yellow]")
            for share in shares:
                guest = "[red]GUEST[/red]" if share.get("guest_access") == "1" else ""
                console.print(f"    - {share.get('name', 'Unknown')} {guest}")
        else:
            console.print(f"  Share points: [green]None[/green]")

        services = status["listening_services"]
        console.print(f"\n[bold yellow]NETWORK SERVICES (WITH CONNECTIONS)[/bold yellow]")
        if services:
            high_risk = [s for s in services if s.get('risk') == 'HIGH']
            med_risk = [s for s in services if s.get('risk') == 'MEDIUM']
            other = [s for s in services if s.get('risk') not in ('HIGH', 'MEDIUM')]

            if high_risk:
                console.print(f"  [bold red]HIGH RISK:[/bold red]")
                for s in high_risk[:10]:
                    console.print(f"    - {s['process']} (PID {s['pid']}) port {s['port']} [{s['type']}]")
                if len(high_risk) > 10:
                    console.print(f"    ... and {len(high_risk) - 10} more")

            if med_risk:
                console.print(f"  [bold yellow]MEDIUM RISK:[/bold yellow]")
                for s in med_risk[:10]:
                    console.print(f"    - {s['process']} (PID {s['pid']}) port {s['port']} [{s['type']}]")
                if len(med_risk) > 10:
                    console.print(f"    ... and {len(med_risk) - 10} more")

            if other:
                console.print(f"  [green]Low risk:[/green] {len(other)} service(s)")
        else:
            console.print(f"  [green]No listening services[/green]")

        sec = status["security"]
        console.print(f"\n[bold yellow]SCREEN LOCK[/bold yellow]")
        idle = sec.get('idle_time', 0)
        idle_min = int(idle) // 60 if str(idle).isdigit() else 0
        console.print(f"  Lock after: {idle_min} min")
        console.print(f"  Password required: {'[green]Yes[/green]' if sec.get('password_required') else '[red]No[/red]'}")

        scan = status["last_scan"]
        console.print(f"\n[bold yellow]SECURITY SCAN[/bold yellow]")
        if scan.get("last_scan"):
            from datetime import datetime
            scan_time = datetime.fromisoformat(scan["last_scan"])
            console.print(f"  Last scan: {scan_time.strftime('%Y-%m-%d %H:%M')}")
            console.print(f"  Reports: {scan.get('scan_count', 0)}")
        else:
            console.print(f"  Last scan: [yellow]Never[/yellow]")

        watch = status["snapshot_watch"]
        console.print(f"\n[bold yellow]SNAPSHOT WATCH[/bold yellow]")
        console.print(f"  Status: {'[green]Active[/green]' if watch.get('enabled') else '[dim]Inactive[/dim]'}")
        if watch.get("snapshot_name"):
            console.print(f"  Monitoring: {watch['snapshot_name']}")
            console.print(f"  Auto-restore: {'On' if watch.get('auto_restore') else 'Off'}")

        console.print()

    def _print_status_text(self, status: dict) -> None:
        """Plain text status output."""
        print("=== macOS Privacy & Security Status ===\n")

        fw = status['firewall']
        print(f"FIREWALL")
        print(f"  Enabled: {fw.get('enabled')}, Stealth: {fw.get('stealth_mode')}")
        print(f"  Exceptions: {len(fw.get('exceptions', []))}")

        print(f"\nENCRYPTION")
        print(f"  FileVault: {status['filevault'].get('enabled')}")

        print(f"\nSHARING")
        print(f"  Daemon: {'running' if status['sharing'].get('sharing_enabled') else 'stopped'}")
        print(f"  Share points: {len(status['sharing'].get('share_points', []))}")

        services = status['listening_services']
        high = [s for s in services if s.get('risk') == 'HIGH']
        print(f"\nNETWORK SERVICES")
        print(f"  High risk: {len(high)}")
        for s in high[:5]:
            print(f"    - {s['process']} port {s['port']}")

        sec = status['security']
        print(f"\nSCREEN LOCK")
        print(f"  Idle time: {int(sec.get('idle_time', 0)) // 60} min")
        print(f"  Password required: {sec.get('password_required')}")

        scan = status['last_scan']
        print(f"\nLAST SCAN: {scan.get('last_scan') or 'Never'}")

    def get_sharing_status(self) -> Dict[str, Any]:
        """Get sharing status."""
        status = {"sharing_enabled": False, "share_points": []}
        success, output = self.run_command("launchctl list | grep -i sharing")
        if success and output.strip():
            status["sharing_enabled"] = True

        success, output = self.run_command("sharing -l")
        if success and output:
            shares = []
            current = {}
            for line in output.split('\n'):
                line = line.strip()
                if ':' in line:
                    key, val = line.split(':', 1)
                    current[key.strip().lower()] = val.strip()
                elif not line and current:
                    shares.append(current)
                    current = {}
            if current:
                shares.append(current)
            status["share_points"] = shares

        return status

    def get_security_settings(self) -> Dict[str, Any]:
        """Get security settings (screen lock, etc)."""
        settings = {"idle_time": 0, "password_required": False}

        success, output = self.run_command("defaults -currentHost read com.apple.screensaver idleTime 2>/dev/null")
        if success:
            settings["idle_time"] = output.strip()

        success, output = self.run_command("defaults -currentHost read com.apple.screensaver askForPassword 2>/dev/null")
        if success:
            settings["password_required"] = output.strip() == "1"

        return settings


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

    def list_presets(self, json_output: bool = False, sort_by: str = "name") -> None:
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


def interactive_menu():
    """Interactive menu for privacy/security settings."""
    manager = PrivacySettingsManager(verbose="-v" in sys.argv or "--verbose" in sys.argv)
    preset_manager = PresetManager(manager)
    sort_by = "name"
    json_output = "--json" in sys.argv

    actions = [
        ("1", "list", "List all privacy/security settings"),
        ("2", "status", "Show comprehensive security status"),
        ("3", "enable", "Enable a privacy/security setting"),
        ("4", "disable", "Disable a privacy/security setting"),
        ("5", "preset-list", "List available presets"),
        ("6", "preset-apply", "Apply a preset configuration"),
        ("7", "services", "List running services"),
        ("q", "quit", "Exit"),
    ]

    while True:
        print("\n" + "=" * 60)
        print("       macOS Privacy & Security - Interactive Mode")
        print("=" * 60)
        print(f"  Sort: [{'name' if sort_by == 'name' else sort_by}]  (press 's' to change)")
        print("-" * 60)
        for key, action, desc in actions:
            print(f"  {key:>2}. {action:<16} - {desc}")
        print("=" * 60)

        choice = input("\nSelect action [1-7, s, q]: ").strip().lower()

        if choice == "q" or choice == "quit":
            print("Goodbye!")
            break

        if choice == "s":
            sort_keys = ["name", "category", "state"]
            print(f"\nCurrent sort: {sort_by}")
            for i, k in enumerate(sort_keys, 1):
                marker = " *" if k == sort_by else ""
                print(f"  {i}. {k}{marker}")
            s_choice = input(f"\nSelect sort [1-{len(sort_keys)}]: ").strip()
            if s_choice.isdigit() and 1 <= int(s_choice) <= len(sort_keys):
                sort_by = sort_keys[int(s_choice) - 1]
            continue

        action_map = {
            "1": "list",
            "2": "status",
            "3": "enable",
            "4": "disable",
            "5": "preset-list",
            "6": "preset-apply",
            "7": "services",
        }

        if choice in action_map:
            action = action_map[choice]
        elif choice in [a[1] for a in actions]:
            action = choice
        else:
            print(f"Invalid choice: {choice}")
            continue

        if action == "list":
            manager.list_settings(json_output=json_output, sort_by=sort_by)
        elif action == "status":
            manager.get_status(json_output=json_output)
        elif action == "enable":
            print("\nAvailable settings:")
            for i, s in enumerate(manager.SETTINGS, 1):
                print(f"  {i}. {s.name}")
            setting_idx = input("\nSetting number: ").strip()
            if setting_idx.isdigit() and 1 <= int(setting_idx) <= len(manager.SETTINGS):
                setting = manager.SETTINGS[int(setting_idx) - 1]
                if manager.enable_setting(setting):
                    print(f"Enabled: {setting.name}")
                else:
                    print(f"Failed to enable: {setting.name}")
            else:
                print("Invalid selection")
        elif action == "disable":
            print("\nAvailable settings:")
            for i, s in enumerate(manager.SETTINGS, 1):
                print(f"  {i}. {s.name}")
            setting_idx = input("\nSetting number: ").strip()
            if setting_idx.isdigit() and 1 <= int(setting_idx) <= len(manager.SETTINGS):
                setting = manager.SETTINGS[int(setting_idx) - 1]
                if manager.disable_setting(setting):
                    print(f"Disabled: {setting.name}")
                else:
                    print(f"Failed to disable: {setting.name}")
            else:
                print("Invalid selection")
        elif action == "preset-list":
            preset_manager.list_presets(json_output=json_output)
        elif action == "preset-apply":
            print("\nAvailable presets:")
            for pid, p in preset_manager.PRESETS.items():
                print(f"  {pid} - {p['name']}")
            pid = input("\nPreset ID: ").strip()
            dry_run = input("Dry run? (y/N): ").strip().lower() == "y"
            if pid:
                preset_manager.apply_preset(pid, dry_run=dry_run)
            else:
                print("No preset specified")
        elif action == "services":
            manager.list_services(json_output=json_output, sort_by=sort_by)

        input("\nPress Enter to continue...")


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
    parser.add_argument("--sort", choices=["name", "category", "state"], help="Sort by: name, category, state")

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
    sort_by = args.sort or "name"

    if not args.command:
        interactive_menu()
        return

    if args.command == "list":
        manager.list_settings(category=args.category, json_output=args.json, sort_by=sort_by)
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