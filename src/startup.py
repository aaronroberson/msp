#!/usr/bin/env python3
"""Startup item manager for msp CLI."""

import json
import os
import plistlib
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from pathlib import Path

from src.command import setup_completion, suggest_command

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
    metadata: Optional[Dict[str, Any]] = None


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

    def _safe_listdir(self, path: str) -> List[str]:
        """Return directory entries without raising on missing or protected paths."""
        try:
            return sorted(os.listdir(path)) if os.path.isdir(path) else []
        except Exception:
            return []

    def _command_exists(self, command: str) -> bool:
        success, _ = self._run_cmd(f"command -v {shlex.quote(command)} >/dev/null 2>&1")
        return success

    def _file_record(self, path: str, item_type: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build a compact, JSON-safe file inventory record."""
        record = {
            "type": item_type,
            "path": path,
            "exists": os.path.exists(path),
        }
        try:
            stat = os.stat(path)
            record.update({
                "mode": oct(stat.st_mode & 0o7777),
                "uid": stat.st_uid,
                "gid": stat.st_gid,
                "size": stat.st_size,
                "modified": int(stat.st_mtime),
                "executable": bool(stat.st_mode & 0o111),
            })
        except Exception:
            pass
        if extra:
            record.update(extra)
        return record

    def _read_plist_metadata(self, plist_path: str) -> Dict[str, Any]:
        """Read launchd plist metadata used for startup inventory."""
        metadata: Dict[str, Any] = {
            "label": os.path.basename(plist_path).replace(".plist", ""),
            "program": None,
            "program_arguments": [],
            "run_at_load": None,
            "keep_alive": None,
            "disabled": None,
        }
        try:
            with open(plist_path, "rb") as plist_file:
                data = plistlib.load(plist_file)
            metadata.update({
                "label": data.get("Label") or metadata["label"],
                "program": data.get("Program"),
                "program_arguments": data.get("ProgramArguments") or [],
                "run_at_load": data.get("RunAtLoad"),
                "keep_alive": data.get("KeepAlive"),
                "disabled": data.get("Disabled"),
                "working_directory": data.get("WorkingDirectory"),
                "start_interval": data.get("StartInterval"),
                "start_calendar_interval": data.get("StartCalendarInterval"),
                "mach_services": sorted((data.get("MachServices") or {}).keys()),
                "sockets": sorted((data.get("Sockets") or {}).keys()),
                "watch_paths": data.get("WatchPaths") or [],
                "queue_directories": data.get("QueueDirectories") or [],
                "standard_out_path": data.get("StandardOutPath"),
                "standard_error_path": data.get("StandardErrorPath"),
            })
        except Exception as e:
            metadata["read_error"] = str(e)
        return metadata

    def _collect_launch_plist_inventory(self) -> List[Dict[str, Any]]:
        """Collect LaunchAgent/LaunchDaemon plist metadata across known locations."""
        inventory = []
        path_types = [
            *(("launch_agent", path) for path in self.LAUNCH_AGENT_PATHS),
            *(("launch_daemon", path) for path in self.LAUNCH_DAEMON_PATHS),
        ]
        for item_type, directory in path_types:
            for filename in self._safe_listdir(directory):
                if not filename.endswith(".plist"):
                    continue
                path = os.path.join(directory, filename)
                metadata = self._read_plist_metadata(path)
                record = self._file_record(path, item_type, metadata)
                record["name"] = filename.replace(".plist", "")
                record["location"] = directory
                inventory.append(record)
        return inventory

    def _collect_agents(self) -> List[StartupItem]:
        """Collect user agents without printing."""
        items = []
        user_paths = [
            os.path.expanduser("~/Library/LaunchAgents"),
            "/Library/LaunchAgents"
        ]
        for path in user_paths:
            if os.path.exists(path):
                for f in os.listdir(path):
                    if f.endswith('.plist'):
                        plist_path = os.path.join(path, f)
                        metadata = self._read_plist_metadata(plist_path)
                        label = metadata.get("label") or self._read_plist_label(plist_path)
                        item = StartupItem(
                            name=f.replace('.plist', ''),
                            label=label or f.replace('.plist', ''),
                            path=plist_path,
                            type="agent",
                            status="unknown",
                            metadata=metadata
                        )
                        items.append(item)
        return items

    def _collect_daemons(self) -> List[StartupItem]:
        """Collect system daemons without printing."""
        items = []
        for path in self.LAUNCH_DAEMON_PATHS:
            if os.path.exists(path):
                for f in os.listdir(path):
                    if f.endswith('.plist'):
                        plist_path = os.path.join(path, f)
                        metadata = self._read_plist_metadata(plist_path)
                        label = metadata.get("label") or self._read_plist_label(plist_path)
                        item = StartupItem(
                            name=f.replace('.plist', ''),
                            label=label or f.replace('.plist', ''),
                            path=plist_path,
                            type="daemon",
                            status="unknown",
                            metadata=metadata
                        )
                        items.append(item)
        return items

    def _collect_launchd_items(self) -> List[StartupItem]:
        """Collect launchd items without printing."""
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
        return items

    def _get_all_items(self) -> List[StartupItem]:
        """Get all startup items without printing."""
        items = []
        items.extend(self._collect_agents())
        items.extend(self._collect_daemons())
        items.extend(self._collect_launchd_items())
        return items

    def list_all(self, json_output: bool = False, sort_by: str = "name") -> List[StartupItem]:
        """List all startup items."""
        items = self._get_all_items()

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

        items = self._sort_items(items, sort_by)

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

    def _sort_items(self, items: List[StartupItem], sort_by: str) -> List[StartupItem]:
        """Sort items by the specified key."""
        if sort_by == "name":
            return sorted(items, key=lambda x: x.name.lower())
        elif sort_by == "label":
            return sorted(items, key=lambda x: x.label.lower())
        elif sort_by == "pid":
            return sorted(items, key=lambda x: x.pid if x.pid else 0)
        elif sort_by == "type":
            return sorted(items, key=lambda x: (x.type, x.name.lower()))
        elif sort_by == "path":
            return sorted(items, key=lambda x: (x.path or "").lower())
        elif sort_by == "status":
            return sorted(items, key=lambda x: (x.status or "").lower())
        return items

    def list_agents(self, json_output: bool = False, sort_by: str = "name") -> List[StartupItem]:
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

        items = self._sort_items(items, sort_by)

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

    def list_daemons(self, json_output: bool = False, sort_by: str = "name") -> List[StartupItem]:
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

        items = self._sort_items(items, sort_by)

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

    def collect_login_items(self) -> List[Dict[str, Any]]:
        """Collect user login items through System Events when osascript is available."""
        if not self._command_exists("osascript"):
            return []

        script = "\n".join([
            'tell application "System Events"',
            "set rows to {}",
            "repeat with loginItem in login items",
            "set itemName to name of loginItem",
            'set itemPath to ""',
            "try",
            "set itemPath to path of loginItem",
            "end try",
            "set itemHidden to hidden of loginItem",
            "set end of rows to itemName & tab & itemPath & tab & itemHidden",
            "end repeat",
            "set AppleScript's text item delimiters to linefeed",
            "return rows as text",
            "end tell",
        ])
        success, output = self._run_cmd(f"osascript -e {shlex.quote(script)} 2>/dev/null")
        items = []
        if not success or not output.strip():
            return items

        for line in output.strip().splitlines():
            parts = line.split("\t")
            if not parts or not parts[0]:
                continue
            items.append({
                "type": "login_item",
                "name": parts[0],
                "path": parts[1] if len(parts) > 1 else "",
                "hidden": (parts[2].lower() == "true") if len(parts) > 2 else None,
                "source": "System Events",
            })
        return items

    def collect_cron_inventory(self) -> List[Dict[str, Any]]:
        """Collect user and system cron-style startup entries."""
        inventory: List[Dict[str, Any]] = []

        success, output = self._run_cmd("crontab -l 2>/dev/null")
        if success and output.strip():
            for line_no, line in enumerate(output.splitlines(), 1):
                entry = line.strip()
                if entry and not entry.startswith("#"):
                    inventory.append({
                        "type": "user_crontab",
                        "path": "crontab",
                        "line": line_no,
                        "entry": entry,
                    })

        cron_files = ["/etc/crontab"]
        cron_dirs = ["/etc/cron.d"]
        for directory in cron_dirs:
            for filename in self._safe_listdir(directory):
                cron_files.append(os.path.join(directory, filename))

        for path in cron_files:
            if not os.path.exists(path):
                continue
            record = self._file_record(path, "cron_file")
            entries = []
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as cron_file:
                    for line_no, line in enumerate(cron_file, 1):
                        entry = line.strip()
                        if entry and not entry.startswith("#"):
                            entries.append({"line": line_no, "entry": entry})
            except Exception as e:
                record["read_error"] = str(e)
            record["entries"] = entries
            inventory.append(record)

        return inventory

    def collect_periodic_inventory(self) -> List[Dict[str, Any]]:
        """Collect periodic scripts used by periodic(8)."""
        inventory = []
        roots = [
            "/etc/periodic",
            "/usr/local/etc/periodic",
            "/opt/homebrew/etc/periodic",
        ]
        for root in roots:
            for cadence in ("daily", "weekly", "monthly"):
                directory = os.path.join(root, cadence)
                for filename in self._safe_listdir(directory):
                    path = os.path.join(directory, filename)
                    if os.path.isfile(path):
                        inventory.append(self._file_record(path, "periodic_script", {
                            "name": filename,
                            "cadence": cadence,
                            "location": directory,
                        }))
        return inventory

    def collect_shell_profile_inventory(self) -> List[Dict[str, Any]]:
        """Collect shell startup profile files that can launch commands at login/shell start."""
        home = str(Path.home())
        paths = [
            os.path.join(home, ".zprofile"),
            os.path.join(home, ".zshrc"),
            os.path.join(home, ".zlogin"),
            os.path.join(home, ".zshenv"),
            os.path.join(home, ".bash_profile"),
            os.path.join(home, ".bashrc"),
            os.path.join(home, ".profile"),
            os.path.join(home, ".config/fish/config.fish"),
            "/etc/profile",
            "/etc/bashrc",
            "/etc/zprofile",
            "/etc/zshrc",
            "/etc/zshenv",
            "/etc/fish/config.fish",
        ]
        inventory = []
        suspicious_tokens = ("launchctl", "osascript", "curl ", "wget ", "nc ", "python ", "python3 ")
        for path in paths:
            if not os.path.exists(path):
                continue
            record = self._file_record(path, "shell_profile")
            matches = []
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as profile:
                    for line_no, line in enumerate(profile, 1):
                        stripped = line.strip()
                        if not stripped or stripped.startswith("#"):
                            continue
                        lower = stripped.lower()
                        if any(token in lower for token in suspicious_tokens):
                            matches.append({"line": line_no, "entry": stripped[:300]})
            except Exception as e:
                record["read_error"] = str(e)
            record["notable_entries"] = matches
            inventory.append(record)
        return inventory

    def collect_privileged_helper_inventory(self) -> List[Dict[str, Any]]:
        """Collect privileged helper tools installed outside launchd plist directories."""
        inventory = []
        for directory in ["/Library/PrivilegedHelperTools", "/System/Library/PrivilegedHelperTools"]:
            for filename in self._safe_listdir(directory):
                path = os.path.join(directory, filename)
                if os.path.isfile(path):
                    inventory.append(self._file_record(path, "privileged_helper", {
                        "name": filename,
                        "location": directory,
                    }))
        return inventory

    def collect_system_extension_inventory(self) -> List[Dict[str, Any]]:
        """Collect system extensions when systemextensionsctl is available."""
        if not self._command_exists("systemextensionsctl"):
            return []
        success, output = self._run_cmd("systemextensionsctl list 2>/dev/null")
        if not success or not output.strip():
            return []

        inventory = []
        current_team = None
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("systemextensionsctl", "---")):
                continue
            if line.endswith(":") and "[" not in line:
                current_team = line.rstrip(":")
                continue
            if "[" in line and "]" in line:
                state = line[line.find("[") + 1:line.find("]")]
                remainder = line[line.find("]") + 1:].strip()
                parts = remainder.split()
                bundle_id = parts[0] if parts else ""
                version = parts[1].strip("()") if len(parts) > 1 and parts[1].startswith("(") else ""
                inventory.append({
                    "type": "system_extension",
                    "team": current_team,
                    "state": state,
                    "bundle_id": bundle_id,
                    "version": version,
                    "raw": line,
                })
            else:
                inventory.append({"type": "system_extension", "team": current_team, "raw": line})
        return inventory

    def collect_kernel_extension_inventory(self) -> List[Dict[str, Any]]:
        """Collect loaded kernel extensions through kmutil or kextstat when available."""
        if self._command_exists("kmutil"):
            success, output = self._run_cmd("kmutil showloaded 2>/dev/null")
            source = "kmutil showloaded"
        elif self._command_exists("kextstat"):
            success, output = self._run_cmd("kextstat 2>/dev/null")
            source = "kextstat"
        else:
            return []

        if not success or not output.strip():
            return []

        inventory = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or line.lower().startswith(("index", "no variant")):
                continue
            bundle_id = ""
            for token in line.split():
                if "." in token and not token.replace(".", "").isdigit():
                    bundle_id = token.strip("<>()")
                    break
            inventory.append({
                "type": "kernel_extension",
                "bundle_id": bundle_id,
                "source": source,
                "raw": line,
            })
        return inventory

    def collect_background_item_inventory(self) -> List[Dict[str, Any]]:
        """Collect background items when macOS exposes them through sfltool."""
        if not self._command_exists("sfltool"):
            return []

        commands = [
            ("sfltool dumpbtm 2>/dev/null", "sfltool dumpbtm"),
            ("sfltool dumpbtm -j 2>/dev/null", "sfltool dumpbtm -j"),
        ]
        for command, source in commands:
            success, output = self._run_cmd(command)
            if not success or not output.strip():
                continue
            try:
                parsed = json.loads(output)
                return [{"type": "background_items", "source": source, "items": parsed}]
            except Exception:
                return [
                    {"type": "background_item", "source": source, "raw": line.strip()}
                    for line in output.splitlines()
                    if line.strip()
                ]
        return []

    def comprehensive_inventory(self, json_output: bool = False) -> Dict[str, Any]:
        """Collect a broad startup/persistence inventory without changing system state."""
        inventory = {
            "launch_plists": self._collect_launch_plist_inventory(),
            "login_items": self.collect_login_items(),
            "cron": self.collect_cron_inventory(),
            "periodic": self.collect_periodic_inventory(),
            "shell_profiles": self.collect_shell_profile_inventory(),
            "privileged_helpers": self.collect_privileged_helper_inventory(),
            "system_extensions": self.collect_system_extension_inventory(),
            "kernel_extensions": self.collect_kernel_extension_inventory(),
            "background_items": self.collect_background_item_inventory(),
        }

        if json_output:
            print(json.dumps(inventory, indent=2))
        return inventory

    def comprehensive_audit(self, json_output: bool = False) -> List[Dict[str, Any]]:
        """Audit expanded startup/persistence inventory for review-worthy entries."""
        inventory = self.comprehensive_inventory(json_output=False)
        findings: List[Dict[str, Any]] = []
        writable_locations = ("/tmp/", "/private/tmp/", "/var/tmp/", "/Users/Shared/")
        network_tokens = ("curl ", "wget ", "nc ", "ncat ", "socat ", "osascript", "python ", "python3 ")

        for item in inventory["launch_plists"]:
            reasons = []
            label = item.get("label") or item.get("name") or ""
            path = item.get("path") or ""
            is_apple_system_item = label.startswith("com.apple.") or path.startswith("/System/")
            program = item.get("program") or ""
            program_args = " ".join(str(arg) for arg in item.get("program_arguments") or [])
            command_text = f"{program} {program_args}".strip()
            if not is_apple_system_item and any(command_text.startswith(location) or location in command_text for location in writable_locations):
                reasons.append("Launch plist references a user-writable or temporary location")
            if not is_apple_system_item and item.get("run_at_load") is True and item.get("keep_alive"):
                reasons.append("Runs at load and is configured to stay alive")
            if not is_apple_system_item and any(token in command_text.lower() for token in network_tokens):
                reasons.append("Launch plist command includes network/script execution tooling")
            if not is_apple_system_item and item.get("read_error"):
                reasons.append("Could not parse plist")
            if reasons:
                findings.append({
                    "risk": "REVIEW",
                    "section": "launch_plists",
                    "item": label or path,
                    "path": path,
                    "reasons": reasons,
                })

        for item in inventory["cron"]:
            entries = item.get("entries") or [{"entry": item.get("entry", "")}]
            for entry in entries:
                text = entry.get("entry", "").lower()
                reasons = []
                if any(token in text for token in network_tokens):
                    reasons.append("Cron entry includes network/script execution tooling")
                if any(location in text for location in writable_locations):
                    reasons.append("Cron entry references a user-writable or temporary location")
                if reasons:
                    findings.append({
                        "risk": "REVIEW",
                        "section": "cron",
                        "item": item.get("path"),
                        "line": entry.get("line") or item.get("line"),
                        "reasons": reasons,
                    })

        for item in inventory["periodic"]:
            if item.get("path", "").startswith(("/usr/local/", "/opt/homebrew/")):
                findings.append({
                    "risk": "LOW",
                    "section": "periodic",
                    "item": item.get("name"),
                    "path": item.get("path"),
                    "reasons": ["Third-party periodic script runs on a schedule"],
                })

        for item in inventory["shell_profiles"]:
            if item.get("notable_entries"):
                findings.append({
                    "risk": "REVIEW",
                    "section": "shell_profiles",
                    "item": item.get("path"),
                    "path": item.get("path"),
                    "reasons": ["Shell profile contains command patterns worth reviewing"],
                    "entries": item.get("notable_entries"),
                })

        for item in inventory["privileged_helpers"]:
            if item.get("path", "").startswith("/Library/PrivilegedHelperTools"):
                findings.append({
                    "risk": "LOW",
                    "section": "privileged_helpers",
                    "item": item.get("name"),
                    "path": item.get("path"),
                    "reasons": ["Third-party privileged helper tool is installed"],
                })

        for item in inventory["system_extensions"]:
            if "activated" in str(item.get("state", "")).lower() or item.get("bundle_id"):
                findings.append({
                    "risk": "LOW",
                    "section": "system_extensions",
                    "item": item.get("bundle_id") or item.get("raw"),
                    "reasons": ["System extension is present"],
                    "raw": item.get("raw"),
                })

        for item in inventory["kernel_extensions"]:
            bundle_id = item.get("bundle_id") or ""
            if bundle_id and not bundle_id.startswith("com.apple."):
                findings.append({
                    "risk": "REVIEW",
                    "section": "kernel_extensions",
                    "item": bundle_id,
                    "reasons": ["Non-Apple kernel extension is loaded"],
                    "raw": item.get("raw"),
                })

        for item in inventory["background_items"]:
            findings.append({
                "risk": "LOW",
                "section": "background_items",
                "item": item.get("source"),
                "reasons": ["Background item data is discoverable and should be reviewed"],
                "raw": item.get("raw"),
            })

        findings.sort(key=lambda x: {"HIGH": 0, "MEDIUM": 1, "REVIEW": 2, "LOW": 3}.get(x.get("risk"), 4))

        if json_output:
            print(json.dumps(findings, indent=2))
            return findings

        if not findings:
            print("✓ No expanded startup/persistence findings found.")
            return findings

        print("=== Comprehensive Startup/Persistence Audit ===\n")
        for finding in findings:
            print(f"[{finding.get('risk')}] {finding.get('section')}: {finding.get('item')}")
            for reason in finding.get("reasons", []):
                print(f"  - {reason}")
            if finding.get("path"):
                print(f"  Path: {finding['path']}")
        return findings

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

    def list_running(self, json_output: bool = False, sort_by: str = "pid") -> List[StartupItem]:
        """List currently running launchd items with PIDs."""
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
                        if pid and pid > 0:
                            item = StartupItem(
                                name=label.split(".")[-1] if "." in label else label,
                                label=label,
                                path="",
                                type="launchd",
                                status="running",
                                pid=pid
                            )
                            items.append(item)
                    except (ValueError, IndexError):
                        continue

        items = self._sort_items(items, sort_by)

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
            table = Table(title="Running Daemons")
            table.add_column("Name", style="cyan")
            table.add_column("Label", style="green")
            table.add_column("PID", style="yellow")
            table.add_column("Status", style="green")
            for item in items:
                table.add_row(item.name[:30], item.label[:50], str(item.pid), item.status)
            console.print(table)
        else:
            print(f"{'Name':<30} {'Label':<50} {'PID':<8} {'Status'}")
            print("-" * 100)
            for item in items:
                print(f"{item.name:<30} {item.label:<50} {str(item.pid):<8} {item.status}")

        return items

    def list_disabled(self, json_output: bool = False, sort_by: str = "type") -> List[StartupItem]:
        """List plist files that exist but are not currently running."""
        all_items = self._get_all_items()
        running_labels = set()

        success, output = self._run_cmd("launchctl list 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    running_labels.add(parts[2])

        disabled = [i for i in all_items if i.label not in running_labels and i.path]

        disabled = self._sort_items(disabled, sort_by)

        if json_output:
            print(json.dumps([{
                "name": i.name,
                "label": i.label,
                "path": i.path,
                "type": i.type,
                "status": "disabled"
            } for i in disabled], indent=2))
            return disabled

        if RICH_AVAILABLE and console:
            table = Table(title="Disabled Daemons (plist exists, not running)")
            table.add_column("Name", style="cyan")
            table.add_column("Label", style="green")
            table.add_column("Path", style="magenta")
            table.add_column("Type", style="yellow")
            for item in disabled:
                table.add_row(item.name[:30], item.label[:50], item.path[:60], item.type)
            console.print(table)
        else:
            print(f"{'Name':<30} {'Label':<50} {'Path':<60} {'Type'}")
            print("-" * 150)
            for item in disabled:
                print(f"{item.name:<30} {item.label:<50} {item.path:<60} {item.type}")

        return disabled

    def pause(self, label: str) -> bool:
        """Pause/stop a running daemon."""
        user_domain = f"gui/{os.getuid()}"

        success, _ = self._run_cmd(f"launchctl bootout {user_domain}/{label} 2>/dev/null")
        if success:
            print(f"Paused: {label}")
            return True

        success, _ = self._run_cmd(f"sudo launchctl bootout system/{label} 2>/dev/null", sudo=True)
        if success:
            print(f"Paused (system): {label}")
            return True

        print(f"Could not pause: {label}")
        return False

    def start(self, label: str) -> bool:
        """Start a disabled daemon by loading its plist."""
        plist_path = None

        for path in self.LAUNCH_AGENT_PATHS + self.LAUNCH_DAEMON_PATHS:
            if os.path.exists(path):
                for f in os.listdir(path):
                    if f.endswith('.plist'):
                        full_path = os.path.join(path, f)
                        try:
                            success, output = self._run_cmd(f"defaults read '{full_path}' Label 2>/dev/null")
                            if success and output.strip() == label:
                                plist_path = full_path
                                break
                        except Exception:
                            pass
                if plist_path:
                    break

        if not plist_path:
            print(f"Could not find plist for: {label}")
            return False

        is_daemon = plist_path.startswith("/Library/LaunchDaemons") or plist_path.startswith("/System/Library/LaunchDaemons")

        if is_daemon:
            success, _ = self._run_cmd(f"sudo launchctl bootstrap system/{plist_path} 2>/dev/null", sudo=True)
        else:
            user_domain = f"gui/{os.getuid()}"
            success, _ = self._run_cmd(f"launchctl bootstrap {user_domain} {plist_path} 2>/dev/null")

        if success:
            print(f"Started: {label}")
            return True

        print(f"Could not start: {label}")
        return False

    def audit(self, json_output: bool = False, level: str = "all") -> List[Dict[str, Any]]:
        """Audit startup items for suspicious entries."""
        items = self._get_all_items()
        results = []

        SUSPICIOUS_PATTERNS = {
            "HIGH": [
                "keylogger", "keystroke", "clipboard", "screenrec",
                "cryptominer", "crypto", "miner", "botnet",
                "rat", "trojan", "backdoor", "rootkit", "keylog",
            ],
            "MEDIUM": [
                "telemetry", "analytics", "tracking", "phonehome",
                "remote", "control", "admin", "vnc", "rdp",
                "screenshot", "webcam", "camera", "microphone",
            ],
            "LOW": [
                "updater", "update_check", "autoupdate", "crashreporter",
                "feedback", "diagnostic", "usage",
            ]
        }

        KNOWN_GOOD_PREFIXES = [
            "com.apple.", "com.apple.softwareupdate.",
            "com.google.", "com.google.Chrome.", "com.google.GoogleUpdater.",
            "com.microsoft.", "com.microsoft.teams.", "com.microsoft.OneDrive.",
            "com.adobe.", "com.adobe.acc.", "com.adobe.Creative-Cloud.",
            "com.1password.", "com.agilebits.",
            "com.slack.", "com.zoom.", "com.docker.",
            "com.spotify.", "com.valvesoftware.", "com.riotgames.",
            "com.sublimetext.", "com.jetbrains.", "com.vscode.",
            "com.docker.", "com.visualstudio.", "com.nodejs.",
            "com.github.", "com.slackhq.", "com.figma.",
            "org.freedesktop.", "org.gnome.", "org.kde.",
            "io.bottle.", "io.flask.", "io.pypi.",
            "com.amazon.", "com.netflix.", "com.facebook.",
            "com.twitter.", "com.discord.", "com.telegram.",
            "com.wireguard.", "com MullvadVPN.",
            "homebrew.mxcl.", "io.munki.",
        ]

        KNOWN_GOOD_NAMES = [
            "Spotify", "Slack", "Teams", "Zoom", "Chrome", "Firefox",
            "Docker", "Visual Studio", "VSCode", "1Password", "Figma",
            "Dropbox", "OneDrive", "iTerm", "Rectangle", "Raycast",
            "Hammerspoon", "BetterTouchTool", "KeyboardMaestro",
        ]

        for item in items:
            risk_level = "LOW"
            reasons = []

            label_lower = item.label.lower()

            for pat in SUSPICIOUS_PATTERNS["HIGH"]:
                if pat in label_lower:
                    risk_level = "HIGH"
                    reasons.append(f"Contains '{pat}'")
                    break

            if risk_level != "HIGH":
                for pat in SUSPICIOUS_PATTERNS["MEDIUM"]:
                    if pat in label_lower:
                        risk_level = "MEDIUM"
                        reasons.append(f"Contains '{pat}'")
                        break

            for good in KNOWN_GOOD_PREFIXES:
                if item.label.startswith(good):
                    risk_level = "OK"
                    break

            for name in KNOWN_GOOD_NAMES:
                if name.lower() in label_lower:
                    risk_level = "OK"
                    break

            if item.pid and item.pid > 0:
                success, output = self._run_cmd(f"codesign -dvvv '{item.path}' 2>/dev/null")
                if success and "not signed" in output.lower():
                    if risk_level == "OK":
                        risk_level = "REVIEW"
                    reasons.append("Unsigned binary")

            if item.path and os.path.exists(item.path):
                if os.access(item.path, os.X_OK):
                    if not os.stat(item.path).st_mode & 0o111:
                        if risk_level not in ("OK", "REVIEW"):
                            reasons.append("Not executable")

            if risk_level != "OK" and risk_level != "LOW" and reasons:
                results.append({
                    "item": item.label,
                    "risk": risk_level,
                    "reasons": reasons,
                    "pid": item.pid,
                    "status": item.status,
                    "path": item.path
                })

        results.sort(key=lambda x: {"HIGH": 0, "MEDIUM": 1, "REVIEW": 2, "LOW": 3, "OK": 4}[x.get("risk", "LOW")])

        if json_output:
            print(json.dumps(results, indent=2))
            return results

        if not results:
            print("✓ No concerning startup items found.")
            return results

        if RICH_AVAILABLE and console:
            console.print("\n[bold]Startup Items Audit[/bold]\n")

            high = [r for r in results if r.get("risk") == "HIGH"]
            med = [r for r in results if r.get("risk") == "MEDIUM"]
            review = [r for r in results if r.get("risk") == "REVIEW"]

            if high:
                console.print("[bold red]⚠ HIGH RISK:[/bold red]")
                for r in high:
                    console.print(f"  • {r['item']}")
                    for reason in r['reasons']:
                        console.print(f"    └ {reason}")
                    if r.get('path'):
                        console.print(f"    └ {r['path'][:60]}...")

            if med:
                console.print("\n[bold yellow]⚡ MEDIUM RISK:[/bold yellow]")
                for r in med:
                    console.print(f"  • {r['item']}")
                    for reason in r['reasons']:
                        console.print(f"    └ {reason}")

            if review:
                console.print("\n[bold cyan]🔍 REVIEW:[/bold cyan]")
                for r in review:
                    console.print(f"  • {r['item']}")
                    for reason in r['reasons']:
                        console.print(f"    └ {reason}")

            console.print(f"\n[dim]Run 'msp startup audit --json' for full details[/dim]")
        else:
            print("=== Startup Items Audit ===\n")
            for r in results:
                print(f"[{r.get('risk')}] {r['item']}")
                for reason in r.get('reasons', []):
                    print(f"  - {reason}")

        return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Startup Manager")
    parser.add_argument("action", nargs="?", choices=["list", "agents", "daemons", "cron", "disable", "enable", "audit", "summary", "search", "running", "disabled", "pause", "start", "inventory", "comprehensive-audit"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("label", nargs="?", help="Label to enable/disable/pause/start")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--sort", choices=["name", "label", "pid", "type", "path", "status"], default="name", help="Sort by: name, label, pid, type, path, status")
    setup_completion(parser)
    args = parser.parse_args()

    manager = StartupManager(verbose=args.verbose)

    if not args.action:
        interactive_menu(manager, args.json)
        return

    if args.action == "list":
        manager.list_all(json_output=args.json, sort_by=args.sort)
    elif args.action == "agents":
        manager.list_agents(json_output=args.json, sort_by=args.sort)
    elif args.action == "daemons":
        manager.list_daemons(json_output=args.json, sort_by=args.sort)
    elif args.action == "cron":
        manager.list_cron(json_output=args.json)
    elif args.action == "running":
        manager.list_running(json_output=args.json, sort_by=args.sort)
    elif args.action == "disabled":
        manager.list_disabled(json_output=args.json, sort_by=args.sort)
    elif args.action == "inventory":
        manager.comprehensive_inventory(json_output=True)
    elif args.action == "comprehensive-audit":
        manager.comprehensive_audit(json_output=args.json)
    elif args.action == "pause":
        if not args.label:
            print("Error: label required for pause")
            sys.exit(1)
        manager.pause(args.label)
    elif args.action == "start":
        if not args.label:
            print("Error: label required for start")
            sys.exit(1)
        manager.start(args.label)
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
        interactive = "--interactive" in sys.argv or "-i" in sys.argv

        results = manager.audit(json_output=args.json)

        if results and not args.json:
            print(f"\nFound {len(results)} item(s) to review.")
            if interactive:
                print("\n[bold]Interactive mode - review each item?[/bold]")
                for r in results:
                    console.print(f"\n[{r['risk']}] {r['item']}")
                    for reason in r.get('reasons', []):
                        console.print(f"  └ {reason}")
                    if r.get('path'):
                        console.print(f"  Path: {r['path']}")

                    action = input("  Action? [d]isable, [s]kip, [q]uit: ").strip().lower()
                    if action == 'd':
                        manager.disable(r['item'], force=True)
                    elif action == 'q':
                        break

    elif args.action == "summary":
        results = manager.audit(json_output=True)

        high = [r for r in results if r.get("risk") == "HIGH"]
        med = [r for r in results if r.get("risk") == "MEDIUM"]
        review = [r for r in results if r.get("risk") == "REVIEW"]

        console.print("\n[bold]Startup Items Summary[/bold]\n")
        console.print(f"[red]HIGH risk:[/red] {len(high)}")
        if high:
            for r in high[:5]:
                console.print(f"  • {r['item']}")
            if len(high) > 5:
                console.print(f"  ... and {len(high)-5} more")

        console.print(f"\n[yellow]MEDIUM risk:[/yellow] {len(med)}")
        if med:
            for r in med[:5]:
                console.print(f"  • {r['item']}")
            if len(med) > 5:
                console.print(f"  ... and {len(med)-5} more")

        console.print(f"\n[cyan]REVIEW:[/cyan] {len(review)}")
        if review:
            for r in review[:5]:
                console.print(f"  • {r['item']}")
            if len(review) > 5:
                console.print(f"  ... and {len(review)-5} more")

        console.print(f"\n[dim]Total: {len(results)} items need attention[/dim]")
        console.print("[dim]Run 'msp startup audit --interactive' to review and disable[/dim]")

    elif args.action == "search":
        if not args.label:
            print("Usage: msp startup search <term>")
            sys.exit(1)
        search_term = args.label.lower()
        items = manager._get_all_items()
        matches = [i for i in items if search_term in i.label.lower() or search_term in i.name.lower()]
        console.print(f"\n[bold]Found {len(matches)} items matching '{args.label}'[/bold]\n")
        for item in matches:
            console.print(f"  • {item.label}")
            console.print(f"    Name: {item.name}, PID: {item.pid or '-'}, Status: {item.status}")
        console.print("\n[dim]Use 'msp startup disable <label>' to disable[/dim]")


def interactive_menu(manager: StartupManager, json_output: bool = False):
    """Interactive menu for startup management."""
    actions = [
        ("1", "list", "List all startup items"),
        ("2", "running", "List running daemons (with PIDs)"),
        ("3", "disabled", "List disabled daemons (plist exists, not running)"),
        ("4", "agents", "List user launch agents only"),
        ("5", "daemons", "List system launch daemons only"),
        ("6", "cron", "List cron jobs"),
        ("7", "audit", "Audit for suspicious items"),
        ("8", "summary", "Quick risk summary"),
        ("9", "search", "Search items by name/label"),
        ("10", "pause", "Pause a running daemon"),
        ("11", "start", "Start a disabled daemon"),
        ("12", "disable", "Disable a startup item"),
        ("13", "enable", "Enable a startup item"),
        ("14", "inventory", "Full startup/persistence inventory"),
        ("15", "comprehensive-audit", "Audit all startup items deeply"),
        ("q", "quit", "Exit"),
    ]

    sort_options = ["name", "label", "pid", "type", "path", "status"]
    current_sort = "name"

    while True:
        print("\n" + "=" * 60)
        print("       Startup Manager - Interactive Mode")
        print(f"       Current sort: {current_sort}")
        print("=" * 60)
        for key, action, desc in actions:
            print(f"  {key:>2}. {action:<20} - {desc}")
        print("  s. sort      - Change sort order")
        print("=" * 60)

        choice = input("\nSelect action [1-15, s, q]: ").strip().lower()

        if choice == "q" or choice == "quit":
            print("Goodbye!")
            break

        if choice == "s" or choice == "sort":
            print("\nSort options:")
            for i, opt in enumerate(sort_options, 1):
                marker = " *" if opt == current_sort else ""
                print(f"  {i}. {opt}{marker}")
            sort_choice = input("\nSelect sort [1-6]: ").strip()
            try:
                idx = int(sort_choice) - 1
                if 0 <= idx < len(sort_options):
                    current_sort = sort_options[idx]
                    print(f"Sort set to: {current_sort}")
                else:
                    print("Invalid choice")
            except ValueError:
                print("Invalid choice")
            continue

        action_map = {
            "1": "list",
            "2": "running",
            "3": "disabled",
            "4": "agents",
            "5": "daemons",
            "6": "cron",
            "7": "audit",
            "8": "summary",
            "9": "search",
            "10": "pause",
            "11": "start",
            "12": "disable",
            "13": "enable",
            "14": "inventory",
            "15": "comprehensive-audit",
        }

        if choice in action_map:
            action = action_map[choice]
        elif choice in [a[1] for a in actions]:
            action = choice
        else:
            print(f"Invalid choice: {choice}")
            continue

        if action == "list":
            manager.list_all(json_output=json_output, sort_by=current_sort)
        elif action == "running":
            manager.list_running(json_output=json_output, sort_by=current_sort)
        elif action == "disabled":
            manager.list_disabled(json_output=json_output, sort_by=current_sort)
        elif action == "agents":
            manager.list_agents(json_output=json_output, sort_by=current_sort)
        elif action == "daemons":
            manager.list_daemons(json_output=json_output, sort_by=current_sort)
        elif action == "cron":
            manager.list_cron(json_output=json_output)
        elif action == "audit":
            results = manager.audit(json_output=json_output)
            if results and not json_output:
                print(f"\nFound {len(results)} item(s) to review.")
                for r in results:
                    print(f"\n[{r['risk']}] {r['item']}")
                    for reason in r.get('reasons', []):
                        print(f"  └ {reason}")
                    if r.get('path'):
                        print(f"  Path: {r['path']}")

                    action = input("  Action? [d]isable, [s]kip, [q]uit: ").strip().lower()
                    if action == 'd':
                        manager.disable(r['item'], force=True)
                    elif action == 'q':
                        break
        elif action == "summary":
            results = manager.audit(json_output=True)
            high = [r for r in results if r.get("risk") == "HIGH"]
            med = [r for r in results if r.get("risk") == "MEDIUM"]
            review = [r for r in results if r.get("risk") == "REVIEW"]

            print("\n=== Startup Items Summary ===\n")
            print(f"HIGH risk: {len(high)}")
            if high:
                for r in high[:5]:
                    print(f"  • {r['item']}")
                if len(high) > 5:
                    print(f"  ... and {len(high)-5} more")

            print(f"\nMEDIUM risk: {len(med)}")
            if med:
                for r in med[:5]:
                    print(f"  • {r['item']}")
                if len(med) > 5:
                    print(f"  ... and {len(med)-5} more")

            print(f"\nREVIEW: {len(review)}")
            if review:
                for r in review[:5]:
                    print(f"  • {r['item']}")
                if len(review) > 5:
                    print(f"  ... and {len(review)-5} more")

            print(f"\nTotal: {len(results)} items need attention")
        elif action == "search":
            term = input("Search term: ").strip()
            if term:
                search_term = term.lower()
                items = manager._get_all_items()
                matches = [i for i in items if search_term in i.label.lower() or search_term in i.name.lower()]
                print(f"\nFound {len(matches)} items matching '{term}'\n")
                for item in matches:
                    print(f"  • {item.label}")
                    print(f"    Name: {item.name}, PID: {item.pid or '-'}, Status: {item.status}")
                print("\nUse 'disable' action to disable an item")
        elif action in ("pause", "start", "disable", "enable"):
            label = input(f"Label to {action}: ").strip()
            if label:
                if action == "pause":
                    manager.pause(label)
                elif action == "start":
                    manager.start(label)
                elif action == "disable":
                    manager.disable(label, force=True)
                elif action == "enable":
                    manager.enable(label)
            else:
                print("Label required")
        elif action == "inventory":
            manager.comprehensive_inventory(json_output=json_output)
        elif action == "comprehensive-audit":
            results = manager.comprehensive_audit(json_output=json_output)
            if results and not json_output:
                print(f"\nFound {len(results)} item(s) requiring review.")
                for r in results:
                    print(f"\n[{r.get('risk', 'INFO')}] {r['item']}")
                    for reason in r.get('reasons', []):
                        print(f"  └ {reason}")
        else:
            print(f"Unknown action: {action}")

        input("\nPress Enter to continue...")

if __name__ == "__main__":
    main()
