#!/usr/bin/env python3
"""TCC privacy permissions module for msp CLI.

Reads macOS Transparency, Consent, and Control databases in read-only mode and
uses tccutil for supported reset operations. This module intentionally avoids
direct writes to TCC.db.
"""

import argparse
import base64
import json
import plistlib
import re
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.command import interactive_menu as cmd_menu, interactive_select, setup_completion, suggest_command

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


console = Console() if RICH_AVAILABLE else None

USER_DB = Path("~/Library/Application Support/com.apple.TCC/TCC.db").expanduser()
SYSTEM_DB = Path("/Library/Application Support/com.apple.TCC/TCC.db")


SERVICE_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "kTCCServiceCamera": {
        "name": "Camera",
        "description": "Camera access",
        "tccutil": "Camera",
        "aliases": "camera",
    },
    "kTCCServiceMicrophone": {
        "name": "Microphone",
        "description": "Microphone access",
        "tccutil": "Microphone",
        "aliases": "microphone mic",
    },
    "kTCCServiceScreenCapture": {
        "name": "Screen Recording",
        "description": "Screen capture/recording",
        "tccutil": "ScreenCapture",
        "aliases": "screen screencapture screenrecording screen-recording",
    },
    "kTCCServiceAccessibility": {
        "name": "Accessibility",
        "description": "Accessibility API access",
        "tccutil": "Accessibility",
        "aliases": "accessibility a11y",
    },
    "kTCCServiceAllFiles": {
        "name": "Full Disk Access",
        "description": "Full disk access",
        "tccutil": "AllFiles",
        "aliases": "fulldisk full-disk",
    },
    "kTCCServiceContacts": {
        "name": "Contacts",
        "description": "Contacts access",
        "tccutil": "AddressBook",
        "aliases": "contacts addressbook",
    },
    "kTCCServiceCalendars": {
        "name": "Calendars",
        "description": "Calendar access",
        "tccutil": "Calendar",
        "aliases": "calendars calendar",
    },
    "kTCCServiceReminders": {
        "name": "Reminders",
        "description": "Reminder access",
        "tccutil": "Reminders",
        "aliases": "reminders reminder",
    },
    "kTCCServicePhotos": {
        "name": "Photos",
        "description": "Photos library access",
        "tccutil": "Photos",
        "aliases": "photos photo",
    },
    "kTCCServiceBluetooth": {
        "name": "Bluetooth",
        "description": "Bluetooth access",
        "tccutil": "BluetoothAlways",
        "aliases": "bluetooth",
    },
    "kTCCServiceLocalNetwork": {
        "name": "Local Network",
        "description": "Local network access",
        "tccutil": "LocalNetwork",
        "aliases": "localnetwork local-network",
    },
    "kTCCServiceFilesAndFolders": {
        "name": "Files and Folders",
        "description": "File/folder access",
        "tccutil": "SystemPolicyDocumentsFolder",
        "aliases": "files filesandfolders files-and-folders",
    },
    "kTCCServiceSpeechRecognition": {
        "name": "Speech Recognition",
        "description": "Speech recognition",
        "tccutil": "SpeechRecognition",
        "aliases": "speech speechrecognition speech-recognition",
    },
    "kTCCServiceSiri": {
        "name": "Siri",
        "description": "Siri/Dictation",
        "tccutil": "Siri",
        "aliases": "siri dictation",
    },
    "kTCCServiceDeveloperTool": {
        "name": "Developer Tools",
        "description": "Developer tool access",
        "tccutil": "DeveloperTool",
        "aliases": "developer developertool developer-tool",
    },
    "kTCCServiceInputMonitoring": {
        "name": "Input Monitoring",
        "description": "Keyboard/mouse monitoring",
        "tccutil": "ListenEvent",
        "aliases": "input inputmonitoring input-monitoring listenevent",
    },
    "kTCCServiceSystemPolicyAllFiles": {
        "name": "System Policy All Files",
        "description": "System policy - all files",
        "tccutil": "SystemPolicyAllFiles",
        "aliases": "allfiles all-files systempolicyallfiles",
    },
    "kTCCServiceSystemPolicySysAdminFiles": {
        "name": "System Policy SysAdmin Files",
        "description": "System policy - sysadmin files",
        "tccutil": "SystemPolicySysAdminFiles",
        "aliases": "sysadmin sysadminfiles sys-admin-files",
    },
    "kTCCServiceSystemPolicyDesktopFolder": {
        "name": "Desktop Folder",
        "description": "Desktop folder access",
        "tccutil": "SystemPolicyDesktopFolder",
        "aliases": "desktop desktopfolder desktop-folder",
    },
    "kTCCServiceSystemPolicyDocumentsFolder": {
        "name": "Documents Folder",
        "description": "Documents folder access",
        "tccutil": "SystemPolicyDocumentsFolder",
        "aliases": "documents documentsfolder documents-folder",
    },
    "kTCCServiceSystemPolicyDownloadsFolder": {
        "name": "Downloads Folder",
        "description": "Downloads folder access",
        "tccutil": "SystemPolicyDownloadsFolder",
        "aliases": "downloads downloadsfolder downloads-folder",
    },
    "kTCCServiceSystemPolicyNetworkVolumes": {
        "name": "Network Volumes",
        "description": "Network volumes access",
        "tccutil": "SystemPolicyNetworkVolumes",
        "aliases": "networkvolumes network-volumes",
    },
    "kTCCServiceSystemPolicyRemovableVolumes": {
        "name": "Removable Volumes",
        "description": "Removable volumes access",
        "tccutil": "SystemPolicyRemovableVolumes",
        "aliases": "removable removablevolumes removable-volumes",
    },
}


SERVICE_ALIASES: Dict[str, str] = {}
for service_key, info in SERVICE_DEFINITIONS.items():
    SERVICE_ALIASES[service_key.lower()] = service_key
    SERVICE_ALIASES[info["name"].lower()] = service_key
    SERVICE_ALIASES[info["tccutil"].lower()] = service_key
    for alias in info["aliases"].split():
        SERVICE_ALIASES[alias.lower()] = service_key


AUTH_VALUE_LABELS = {
    0: "not-determined",
    1: "denied",
    2: "allowed",
    3: "limited",
}


HIGH_RISK_SERVICES = {
    "kTCCServiceAccessibility": "Can control or observe other applications",
    "kTCCServiceScreenCapture": "Can capture screen contents",
    "kTCCServiceSystemPolicyAllFiles": "Can read protected user data",
    "kTCCServiceAllFiles": "Can read broad filesystem data",
    "kTCCServiceInputMonitoring": "Can monitor keyboard or mouse input",
    "kTCCServiceDeveloperTool": "Can control developer tooling and debugging",
}


@dataclass
class TCCEntry:
    source: str
    db_path: str
    service: str
    service_name: str
    client: str
    client_name: str
    client_type: str
    client_type_value: Optional[int]
    auth_value: Optional[int]
    auth_status: str
    allowed: bool
    prompt_count: Optional[int]
    last_modified: Optional[str]
    csreq: Optional[str]
    auth_reason: Optional[int] = None
    auth_version: Optional[int] = None
    policy_id: Optional[int] = None
    indirect_object_identifier: Optional[str] = None
    indirect_object_identifier_type: Optional[int] = None
    flags: Optional[int] = None
    last_reminded: Optional[str] = None


class TCCManager:
    """Read and reset macOS TCC privacy permissions."""

    def __init__(
        self,
        scope: str = "both",
        db_path: Optional[str] = None,
        verbose: bool = False,
    ):
        self.scope = scope
        self.db_path = Path(db_path).expanduser() if db_path else None
        self.verbose = verbose
        self.errors: List[Dict[str, str]] = []

    def list_permissions(
        self,
        service: Optional[str] = None,
        client: Optional[str] = None,
        json_output: bool = False,
        sort_by: str = "service",
    ) -> List[TCCEntry]:
        """List TCC permissions from selected databases."""
        entries = self._collect_entries(service=service, client=client)
        entries = self._sort_entries(entries, sort_by)
        self._print_entries(entries, json_output=json_output)
        return entries

    def show(
        self,
        service: str,
        client: Optional[str] = None,
        json_output: bool = False,
    ) -> List[TCCEntry]:
        """Show permissions for a specific service."""
        return self.list_permissions(
            service=service,
            client=client,
            json_output=json_output,
            sort_by="client",
        )

    def audit(self, json_output: bool = False, sort_by: str = "service") -> List[Dict[str, Any]]:
        """Find high-risk allowed TCC permissions."""
        entries = self._collect_entries()
        findings: List[Dict[str, Any]] = []

        for entry in entries:
            if not entry.allowed or entry.service not in HIGH_RISK_SERVICES:
                continue

            findings.append({
                "risk": "HIGH" if entry.service in {
                    "kTCCServiceAccessibility",
                    "kTCCServiceInputMonitoring",
                    "kTCCServiceSystemPolicyAllFiles",
                    "kTCCServiceAllFiles",
                } else "MEDIUM",
                "service": entry.service,
                "service_name": entry.service_name,
                "client": entry.client,
                "client_name": entry.client_name,
                "source": entry.source,
                "reason": HIGH_RISK_SERVICES[entry.service],
                "last_modified": entry.last_modified,
            })

        findings = self._sort_findings(findings, sort_by)

        if json_output:
            self._print_json({"findings": findings, "errors": self.errors})
            return findings

        if RICH_AVAILABLE and console:
            table = Table(title="TCC Privacy Audit")
            table.add_column("Risk", style="red")
            table.add_column("Service", style="cyan")
            table.add_column("Client", style="green")
            table.add_column("Source", style="magenta")
            table.add_column("Reason")
            for finding in findings:
                table.add_row(
                    finding["risk"],
                    finding["service_name"],
                    finding["client_name"] or finding["client"],
                    finding["source"],
                    finding["reason"],
                )
            console.print(table)
        else:
            print(f"{'Risk':<8} {'Service':<28} {'Client':<42} {'Source':<8} Reason")
            print("-" * 110)
            for finding in findings:
                print(
                    f"{finding['risk']:<8} "
                    f"{finding['service_name']:<28} "
                    f"{(finding['client_name'] or finding['client'])[:42]:<42} "
                    f"{finding['source']:<8} "
                    f"{finding['reason']}"
                )

        self._print_errors()
        return findings

    def backup(self, output: Optional[str] = None, json_output: bool = False) -> Dict[str, Any]:
        """Export readable TCC entries to JSON."""
        entries = self._collect_entries()
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scope": self.scope,
            "databases": [str(path) for _, path in self._database_paths()],
            "permissions": [asdict(entry) for entry in entries],
            "errors": self.errors,
        }

        if output:
            output_path = Path(output).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            if json_output:
                self._print_json({"output": str(output_path), **payload})
            else:
                print(f"Backed up {len(entries)} permission record(s) to {output_path}")
                self._print_errors()
            return payload

        self._print_json(payload)
        return payload

    def reset(
        self,
        service: str,
        client: Optional[str] = None,
        json_output: bool = False,
    ) -> bool:
        """Reset TCC permissions via tccutil."""
        service_key = self.resolve_service(service)
        tccutil_service = SERVICE_DEFINITIONS[service_key]["tccutil"]
        cmd = ["tccutil", "reset", tccutil_service]
        if client:
            cmd.append(client)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            success = result.returncode == 0
            payload = {
                "success": success,
                "command": cmd,
                "service": service_key,
                "client": client,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
            if json_output:
                self._print_json(payload)
            elif success:
                target = f" for {client}" if client else ""
                print(f"Reset {SERVICE_DEFINITIONS[service_key]['name']}{target}")
            else:
                print(result.stderr.strip() or "tccutil reset failed", file=sys.stderr)
            return success
        except FileNotFoundError:
            message = "tccutil not found. This command is only available on macOS."
        except subprocess.TimeoutExpired:
            message = "tccutil reset timed out"
        except Exception as exc:
            message = str(exc)

        if json_output:
            self._print_json({
                "success": False,
                "service": service_key,
                "client": client,
                "error": message,
            })
        else:
            print(f"Error: {message}", file=sys.stderr)
        return False

    def grant(self, service: str, client: str, json_output: bool = False) -> bool:
        """Conservative placeholder: direct grants are not supported."""
        return self._unsupported_write("grant", service, client, json_output)

    def revoke(self, service: str, client: str, json_output: bool = False) -> bool:
        """Conservative placeholder: direct revokes are not supported."""
        return self._unsupported_write("revoke", service, client, json_output)

    def restore(self, file_path: str, json_output: bool = False) -> bool:
        """Conservative placeholder: direct TCC restores are not supported."""
        payload = {
            "success": False,
            "file": file_path,
            "error": "restore is not supported because this module does not write TCC.db directly",
        }
        if json_output:
            self._print_json(payload)
        else:
            print(f"Error: {payload['error']}", file=sys.stderr)
        return False

    def resolve_service(self, service: str) -> str:
        """Resolve service aliases to canonical kTCCService names."""
        key = service.strip().lower()
        if key in SERVICE_ALIASES:
            return SERVICE_ALIASES[key]

        available = ", ".join(sorted(self.short_service_aliases()))
        raise ValueError(f"Unknown TCC service: {service}. Valid aliases: {available}")

    def short_service_aliases(self) -> List[str]:
        """Return user-facing service aliases."""
        aliases = []
        for info in SERVICE_DEFINITIONS.values():
            aliases.append(info["aliases"].split()[0])
        return aliases

    def _unsupported_write(
        self,
        action: str,
        service: str,
        client: str,
        json_output: bool,
    ) -> bool:
        try:
            service_key = self.resolve_service(service)
        except ValueError as exc:
            if json_output:
                self._print_json({"success": False, "error": str(exc)})
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return False

        payload = {
            "success": False,
            "action": action,
            "service": service_key,
            "client": client,
            "error": (
                f"{action} is not supported. macOS does not provide a supported "
                "CLI for granting or denying TCC permissions; use reset or MDM profiles."
            ),
        }
        if json_output:
            self._print_json(payload)
        else:
            print(f"Error: {payload['error']}", file=sys.stderr)
        return False

    def _collect_entries(
        self,
        service: Optional[str] = None,
        client: Optional[str] = None,
    ) -> List[TCCEntry]:
        self.errors = []

        service_key = self.resolve_service(service) if service else None
        entries: List[TCCEntry] = []
        for source, db_path in self._database_paths():
            entries.extend(self._read_database(source, db_path, service_key, client))
        return entries

    def _database_paths(self) -> List[Tuple[str, Path]]:
        if self.db_path:
            return [("custom", self.db_path)]
        if self.scope == "user":
            return [("user", USER_DB)]
        if self.scope == "system":
            return [("system", SYSTEM_DB)]
        return [("user", USER_DB), ("system", SYSTEM_DB)]

    def _read_database(
        self,
        source: str,
        db_path: Path,
        service: Optional[str],
        client: Optional[str],
    ) -> List[TCCEntry]:
        if not db_path.exists():
            self._record_error(source, db_path, "not_found", "TCC database not found")
            return []

        try:
            uri = f"file:{db_path}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=10) as conn:
                conn.row_factory = sqlite3.Row
                columns = self._access_columns(conn)
                if not columns:
                    self._record_error(source, db_path, "schema", "access table not found")
                    return []

                query, params = self._build_query(columns, service, client)
                rows = conn.execute(query, params).fetchall()
                return [self._row_to_entry(source, db_path, row, columns) for row in rows]
        except sqlite3.DatabaseError as exc:
            message = str(exc)
            denied_markers = (
                "unable to open database file",
                "authorization denied",
                "not authorized",
                "permission denied",
                "operation not permitted",
            )
            kind = "permission_denied" if any(marker in message.lower() for marker in denied_markers) else "sqlite"
            suggestion = "Try running with sudo for the system TCC database." if source == "system" else None
            self._record_error(source, db_path, kind, message, suggestion=suggestion)
        except PermissionError as exc:
            suggestion = "Try running with sudo for the system TCC database." if source == "system" else None
            self._record_error(source, db_path, "permission_denied", str(exc), suggestion=suggestion)
        except Exception as exc:
            self._record_error(source, db_path, "error", str(exc))
        return []

    def _access_columns(self, conn: sqlite3.Connection) -> List[str]:
        try:
            rows = conn.execute("PRAGMA table_info(access)").fetchall()
        except sqlite3.DatabaseError:
            return []
        return [row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows]

    def _build_query(
        self,
        columns: List[str],
        service: Optional[str],
        client: Optional[str],
    ) -> Tuple[str, List[str]]:
        select_columns = [
            "service",
            "client",
            "client_type",
            "auth_value",
            "allowed",
            "auth_reason",
            "auth_version",
            "csreq",
            "policy_id",
            "indirect_object_identifier",
            "indirect_object_identifier_type",
            "flags",
            "last_modified",
            "last_reminded",
            "prompt_count",
        ]
        selected = [column for column in select_columns if column in columns]
        if "service" not in selected or "client" not in selected:
            selected = ["*"]

        clauses = []
        params: List[str] = []
        if service and "service" in columns:
            clauses.append("service = ?")
            params.append(service)
        if client and "client" in columns:
            clauses.append("client LIKE ?")
            params.append(f"%{client}%")

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        order = " ORDER BY service, client" if "service" in columns and "client" in columns else ""
        return f"SELECT {', '.join(selected)} FROM access{where}{order}", params

    def _row_to_entry(
        self,
        source: str,
        db_path: Path,
        row: sqlite3.Row,
        columns: Iterable[str],
    ) -> TCCEntry:
        column_set = set(columns)
        service = self._get(row, "service")
        client = self._get(row, "client") or ""
        client_type_value = self._get(row, "client_type")
        raw_auth_value = self._get(row, "auth_value")
        raw_allowed = self._get(row, "allowed")

        auth_value = self._normalize_auth_value(raw_auth_value, raw_allowed)
        allowed = auth_value == 2 if auth_value is not None else bool(raw_allowed)
        csreq = self._encode_blob(self._get(row, "csreq")) if "csreq" in column_set else None

        return TCCEntry(
            source=source,
            db_path=str(db_path),
            service=service,
            service_name=SERVICE_DEFINITIONS.get(service, {}).get("name", service),
            client=client,
            client_name=self._client_name(client, client_type_value),
            client_type=self._client_type_label(client_type_value),
            client_type_value=client_type_value,
            auth_value=auth_value,
            auth_status=AUTH_VALUE_LABELS.get(auth_value, "unknown"),
            allowed=allowed,
            prompt_count=self._get(row, "prompt_count"),
            last_modified=self._timestamp(self._get(row, "last_modified")),
            csreq=csreq,
            auth_reason=self._get(row, "auth_reason"),
            auth_version=self._get(row, "auth_version"),
            policy_id=self._get(row, "policy_id"),
            indirect_object_identifier=self._get(row, "indirect_object_identifier"),
            indirect_object_identifier_type=self._get(row, "indirect_object_identifier_type"),
            flags=self._get(row, "flags"),
            last_reminded=self._timestamp(self._get(row, "last_reminded")),
        )

    def _normalize_auth_value(self, auth_value: Any, allowed: Any) -> Optional[int]:
        if auth_value is not None:
            try:
                return int(auth_value)
            except (TypeError, ValueError):
                return None
        if allowed is None:
            return None
        try:
            return 2 if int(allowed) else 1
        except (TypeError, ValueError):
            return None

    def _client_type_label(self, value: Any) -> str:
        try:
            client_type = int(value)
        except (TypeError, ValueError):
            return "unknown"
        if client_type == 0:
            return "bundle"
        if client_type == 1:
            return "path"
        return f"unknown-{client_type}"

    def _client_name(self, client: str, client_type: Any) -> str:
        if not client:
            return ""
        if self._client_type_label(client_type) == "path":
            return Path(client).name
        return self._bundle_display_name(client) or client

    def _bundle_display_name(self, bundle_id: str) -> Optional[str]:
        app_path = self._find_bundle_path(bundle_id)
        if not app_path:
            return None
        info_plist = app_path / "Contents" / "Info.plist"
        try:
            with info_plist.open("rb") as handle:
                info = plistlib.load(handle)
            return (
                info.get("CFBundleDisplayName")
                or info.get("CFBundleName")
                or app_path.stem
            )
        except Exception:
            return app_path.stem

    def _find_bundle_path(self, bundle_id: str) -> Optional[Path]:
        search_roots = [
            Path("/Applications"),
            Path("/System/Applications"),
            Path("/System/Library/CoreServices"),
            Path.home() / "Applications",
        ]
        for root in search_roots:
            if not root.exists():
                continue
            try:
                for app_path in root.glob("*.app"):
                    info_plist = app_path / "Contents" / "Info.plist"
                    if not info_plist.exists():
                        continue
                    try:
                        with info_plist.open("rb") as handle:
                            info = plistlib.load(handle)
                        if info.get("CFBundleIdentifier") == bundle_id:
                            return app_path
                    except Exception:
                        continue
            except PermissionError:
                continue
        return None

    def _timestamp(self, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None

    def _encode_blob(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, bytes):
            return base64.b64encode(value).decode("ascii")
        if isinstance(value, str):
            return value
        return base64.b64encode(bytes(value)).decode("ascii")

    def _get(self, row: sqlite3.Row, key: str) -> Any:
        try:
            return row[key]
        except (KeyError, IndexError):
            return None

    def _sort_entries(self, entries: List[TCCEntry], sort_by: str) -> List[TCCEntry]:
        if sort_by == "service":
            return sorted(entries, key=lambda item: (item.service_name.lower(), item.client.lower()))
        if sort_by == "client":
            return sorted(entries, key=lambda item: (item.client.lower(), item.service_name.lower()))
        if sort_by == "client_name":
            return sorted(entries, key=lambda item: (item.client_name.lower(), item.service_name.lower()))
        if sort_by == "allowed":
            return sorted(entries, key=lambda item: (not item.allowed, item.service_name.lower(), item.client.lower()))
        if sort_by == "prompt_count":
            return sorted(entries, key=lambda item: (item.prompt_count is None, item.prompt_count or 0))
        if sort_by == "last_modified":
            return sorted(entries, key=lambda item: item.last_modified or "")
        return entries

    def _sort_findings(self, findings: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
        if sort_by == "client":
            return sorted(findings, key=lambda item: item["client"].lower())
        if sort_by == "client_name":
            return sorted(findings, key=lambda item: item["client_name"].lower())
        if sort_by == "last_modified":
            return sorted(findings, key=lambda item: item["last_modified"] or "")
        if sort_by == "allowed":
            return sorted(findings, key=lambda item: item["risk"])
        return sorted(findings, key=lambda item: (item["service_name"].lower(), item["client"].lower()))

    def _print_entries(self, entries: List[TCCEntry], json_output: bool = False) -> None:
        if json_output:
            permissions = [asdict(entry) for entry in entries]
            self._print_json({"permissions": permissions, "errors": self.errors} if self.errors else permissions)
            return

        if RICH_AVAILABLE and console:
            table = Table(title="TCC Privacy Permissions")
            table.add_column("Service", style="cyan")
            table.add_column("Client", style="green")
            table.add_column("Status", style="yellow")
            table.add_column("Type")
            table.add_column("Source", style="magenta")
            table.add_column("Modified")
            for entry in entries:
                table.add_row(
                    entry.service_name,
                    entry.client_name or entry.client,
                    entry.auth_status,
                    entry.client_type,
                    entry.source,
                    entry.last_modified or "-",
                )
            console.print(table)
        else:
            print(f"{'Service':<28} {'Client':<42} {'Status':<16} {'Type':<8} {'Source':<8} Modified")
            print("-" * 112)
            for entry in entries:
                print(
                    f"{entry.service_name:<28} "
                    f"{(entry.client_name or entry.client)[:42]:<42} "
                    f"{entry.auth_status:<16} "
                    f"{entry.client_type:<8} "
                    f"{entry.source:<8} "
                    f"{entry.last_modified or '-'}"
                )
        self._print_errors()

    def _print_json(self, payload: Any) -> None:
        print(json.dumps(payload, indent=2))

    def _record_error(
        self,
        source: str,
        db_path: Path,
        kind: str,
        message: str,
        suggestion: Optional[str] = None,
    ) -> None:
        error = {
            "source": source,
            "db_path": str(db_path),
            "type": kind,
            "message": message,
        }
        if suggestion:
            error["suggestion"] = suggestion
        self.errors.append(error)
        if self.verbose:
            print(f"[{source}] {kind}: {message}", file=sys.stderr)

    def _print_errors(self) -> None:
        for error in self.errors:
            message = f"Warning: {error['source']} TCC database: {error['message']}"
            if error.get("suggestion"):
                message += f" {error['suggestion']}"
            print(message, file=sys.stderr)


def valid_bundle_id(value: str) -> bool:
    """Return True when value looks like a bundle identifier or executable path."""
    if value.startswith("/"):
        return True
    return bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9][A-Za-z0-9_-]*)+$", value))


def interactive_menu(manager: TCCManager, json_output: bool = False) -> None:
    """Interactive menu for TCC management."""
    current_sort = "service"

    while True:
        action = cmd_menu([
            ("list", "list", "List all permissions"),
            ("show", "show", "Show permissions for a service"),
            ("reset", "reset", "Reset permissions via tccutil"),
            ("backup", "backup", "Backup TCC database to JSON"),
            ("audit", "audit", "Audit high-risk permissions"),
            ("grant", "grant", "Grant a permission (unsupported)"),
            ("revoke", "revoke", "Revoke a permission (unsupported)"),
            ("restore", "restore", "Restore TCC from backup (unsupported)"),
            ("sort", "sort", f"Change sort (current: {current_sort})"),
        ], title="TCC Manager - Interactive Mode")

        if action is None:
            break

        if action == "sort":
            sort_opts = ["service", "client", "client_name", "allowed", "prompt_count", "last_modified"]
            items = [(s, s, None) for s in sort_opts]
            result = interactive_select(items, title=f"Sort by (current: {current_sort})")
            if result:
                current_sort = result[0]
            continue

        try:
            if action == "list":
                service = input("Service filter (blank for all): ").strip() or None
                client = input("Client filter (blank for all): ").strip() or None
                manager.list_permissions(service=service, client=client, json_output=json_output, sort_by=current_sort)
            elif action == "show":
                service = input("Service: ").strip()
                client = input("Client filter (blank for all): ").strip() or None
                if service:
                    manager.show(service, client=client, json_output=json_output)
            elif action == "reset":
                service = input("Service: ").strip()
                client = input("Bundle ID/path (blank for all apps): ").strip() or None
                if service:
                    manager.reset(service, client=client, json_output=json_output)
            elif action == "backup":
                output = input("Output file (blank to print JSON): ").strip() or None
                manager.backup(output=output, json_output=json_output)
            elif action == "audit":
                manager.audit(json_output=json_output, sort_by=current_sort)
            elif action == "grant":
                service = input("Service: ").strip()
                client = input("Bundle ID or path: ").strip()
                if service and client:
                    manager.grant(service, client, json_output=json_output)
                else:
                    print("Service and client required for grant")
            elif action == "revoke":
                service = input("Service: ").strip()
                client = input("Bundle ID or path: ").strip()
                if service and client:
                    manager.revoke(service, client, json_output=json_output)
                else:
                    print("Service and client required for revoke")
            elif action == "restore":
                file_path = input("Backup file path: ").strip()
                if file_path:
                    manager.restore(file_path, json_output=json_output)
                else:
                    print("File path required for restore")
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)

        input("\nPress Enter to continue...")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="msp TCC Privacy Permissions Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  %(prog)s list --service camera
  %(prog)s show microphone --client com.apple.Terminal --json
  %(prog)s audit --sort client_name
  %(prog)s backup --output tcc-backup.json
  %(prog)s reset camera com.example.App
        """,
    )
    parser.add_argument("action", nargs="?", choices=["list", "show", "grant", "revoke", "reset", "backup", "restore", "audit"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("service", nargs="?", help="TCC service name or alias")
    parser.add_argument("client", nargs="?", help="Bundle ID or path client")
    parser.add_argument("--service", dest="service_filter", help="Filter list by TCC service name or alias")
    parser.add_argument("--client", dest="client_filter", help="Filter list/show by bundle ID or path")
    parser.add_argument("--type", choices=["allow", "deny"], default="allow", help="Compatibility only; grant/revoke are not supported")
    parser.add_argument("--output", help="Backup output JSON file")
    parser.add_argument("--scope", choices=["user", "system", "both"], default="both", help="TCC database scope")
    parser.add_argument("--db-path", help="Read a specific TCC.db path")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--sort", choices=["service", "client", "client_name", "allowed", "prompt_count", "last_modified"], default="service", help="Sort by service, client, client_name, allowed, prompt_count, last_modified")
    setup_completion(parser)
    args = parser.parse_args()

    manager = TCCManager(scope=args.scope, db_path=args.db_path, verbose=args.verbose)

    if not args.action:
        interactive_menu(manager, args.json)
        return

    try:
        if args.action == "list":
            manager.list_permissions(
                service=args.service_filter,
                client=args.client_filter,
                json_output=args.json,
                sort_by=args.sort,
            )
        elif args.action == "show":
            service = args.service or args.service_filter
            if not service:
                print("Error: service required for show", file=sys.stderr)
                sys.exit(1)
            manager.show(service, client=args.client_filter or args.client, json_output=args.json)
        elif args.action == "reset":
            if not args.service:
                print("Error: service required for reset", file=sys.stderr)
                sys.exit(1)
            if args.client and not valid_bundle_id(args.client):
                print(f"Warning: client does not look like a bundle ID or path: {args.client}", file=sys.stderr)
            if not manager.reset(args.service, client=args.client, json_output=args.json):
                sys.exit(1)
        elif args.action == "backup":
            manager.backup(output=args.output, json_output=args.json)
        elif args.action == "audit":
            manager.audit(json_output=args.json, sort_by=args.sort)
        elif args.action == "grant":
            if not args.service or not args.client:
                print("Error: service and client required for grant", file=sys.stderr)
                sys.exit(1)
            if not manager.grant(args.service, args.client, json_output=args.json):
                sys.exit(1)
        elif args.action == "revoke":
            if not args.service or not args.client:
                print("Error: service and client required for revoke", file=sys.stderr)
                sys.exit(1)
            if not manager.revoke(args.service, args.client, json_output=args.json):
                sys.exit(1)
        elif args.action == "restore":
            restore_file = args.service
            if not restore_file:
                print("Error: file required for restore", file=sys.stderr)
                sys.exit(1)
            if not manager.restore(restore_file, json_output=args.json):
                sys.exit(1)
    except ValueError as exc:
        if args.json:
            print(json.dumps({"success": False, "error": str(exc)}, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
