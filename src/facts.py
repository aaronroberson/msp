#!/usr/bin/env python3
"""Normalized macOS privacy and security fact collection.

This module is the read-only collection layer for a future ``msp interrogate``
command. It adapts existing modules into the fact paths consumed by
``src.rules`` and records collection failures instead of aborting.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import io
import json
import os
import platform
import re
import socket
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.command import setup_completion, suggest_command

try:
    from .network import NetworkMonitor
    from .privacy_settings import PrivacySettingsManager
    from .security import SecuritySettings
    from .sharing import SharingManager
    from .startup import StartupManager
    from .tcc import TCCManager
except ImportError:  # pragma: no cover - supports direct execution as src/facts.py
    from network import NetworkMonitor
    from privacy_settings import PrivacySettingsManager
    from security import SecuritySettings
    from sharing import SharingManager
    from startup import StartupManager
    from tcc import TCCManager


DEFAULT_SECTIONS = ("privacy_settings", "network", "startup", "sharing", "security", "tcc")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


class FactCollector:
    """Collect normalized facts from existing modules without changing state."""

    def __init__(self, redact: bool = True):
        self.redact = redact
        self.errors: List[Dict[str, str]] = []

    def collect(self, sections: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        selected = self._normalize_sections(sections)
        facts = self._empty_facts()

        for section in selected:
            collector = getattr(self, f"_collect_{section}", None)
            if collector is None:
                self._record_error(section, "unknown", f"Unknown section: {section}")
                continue
            self._safe_collect(section, collector, facts)

        facts["metadata"]["sections"] = selected
        facts["metadata"]["redacted"] = self.redact
        facts["errors"] = list(self.errors)
        return redact_facts(facts) if self.redact else facts

    def _empty_facts(self) -> Dict[str, Any]:
        return {
            "metadata": collect_host_metadata(),
            "errors": [],
            "firewall": {},
            "filevault": {},
            "gatekeeper": {},
            "sharing": {"enabled": None, "share_points": [], "services": {}, "guest_enabled_services": []},
            "tcc": {"high_risk_grants": [], "allowed": {}, "denied": {}, "errors": []},
            "startup": {"items": [], "unsigned_items": [], "suspicious_items": []},
            "network": {"listeners": [], "exposed_services": [], "connections": [], "services": {}},
            "security_settings": {},
        }

    def _normalize_sections(self, sections: Optional[Iterable[str]]) -> List[str]:
        if sections is None:
            return list(DEFAULT_SECTIONS)
        normalized: List[str] = []
        for section in sections:
            for part in str(section).split(","):
                name = part.strip().replace("-", "_")
                if name:
                    normalized.append(name)
        return normalized or list(DEFAULT_SECTIONS)

    def _safe_collect(self, section: str, collector: Callable[[Dict[str, Any]], None], facts: Dict[str, Any]) -> None:
        try:
            with _suppress_module_output():
                collector(facts)
        except Exception as exc:  # fail-soft collector boundary
            self._record_error(section, collector.__name__, str(exc))

    def _record_error(self, section: str, collector: str, message: str) -> None:
        self.errors.append({"section": section, "collector": collector, "message": message})

    def _collect_privacy_settings(self, facts: Dict[str, Any]) -> None:
        manager = PrivacySettingsManager()
        self._merge_mapping(facts["firewall"], manager.get_firewall_status())
        facts["firewall"]["stealth"] = facts["firewall"].get("stealth_mode")
        self._merge_mapping(facts["filevault"], manager.get_filevault_status())
        self._merge_mapping(facts["gatekeeper"], manager.get_gatekeeper_status())

        try:
            services = manager.get_listening_services()
            facts["network"]["services"] = _network_services_from_privacy_settings(services)
        except Exception as exc:
            self._record_error("privacy_settings", "get_listening_services", str(exc))

        try:
            settings = manager.get_security_settings()
            _merge_security_settings(facts["security_settings"], settings)
        except Exception as exc:
            self._record_error("privacy_settings", "get_security_settings", str(exc))

    def _collect_network(self, facts: Dict[str, Any]) -> None:
        monitor = NetworkMonitor()
        listeners = [_connection_to_dict(item) for item in monitor.list_listening(json_output=False)]
        connections = [_connection_to_dict(item) for item in monitor.list_established(json_output=False)]
        normalized_listeners = [_normalize_listener(item) for item in listeners]
        facts["network"]["listeners"] = normalized_listeners
        facts["network"]["connections"] = [_normalize_connection(item) for item in connections]
        facts["network"]["exposed_services"] = [
            item for item in normalized_listeners if _is_exposed_host(item.get("host"))
        ]
        facts["network"]["services"].update(_network_services_from_listeners(normalized_listeners))

    def _collect_startup(self, facts: Dict[str, Any]) -> None:
        manager = StartupManager()
        inventory = manager.comprehensive_inventory(json_output=False)
        items = _flatten_startup_inventory(inventory)
        audit_findings = manager.audit(json_output=False)
        comprehensive_findings = manager.comprehensive_audit(json_output=False)
        suspicious = list(audit_findings or []) + list(comprehensive_findings or [])
        facts["startup"]["items"] = items
        facts["startup"]["suspicious_items"] = suspicious
        facts["startup"]["unsigned_items"] = [
            item for item in suspicious if _contains_reason(item, "unsigned")
        ]

    def _collect_sharing(self, facts: Dict[str, Any]) -> None:
        status = SharingManager().get_sharing_status()
        services = dict(status.get("services") or {})
        share_points = list(status.get("share_points") or [])
        facts["sharing"] = {
            "enabled": bool(status.get("sharing_enabled")),
            "share_points": share_points,
            "services": services,
            "guest_enabled_services": _guest_enabled_services(services, share_points),
        }
        facts["network"]["services"].update(_network_services_from_sharing(services))

    def _collect_security(self, facts: Dict[str, Any]) -> None:
        manager = SecuritySettings()
        display = manager.get_display_settings()
        _merge_security_settings(facts["security_settings"], display)
        try:
            self._merge_mapping(facts["firewall"], manager.get_firewall_connection_info())
        except Exception as exc:
            self._record_error("security", "get_firewall_connection_info", str(exc))

    def _collect_tcc(self, facts: Dict[str, Any]) -> None:
        manager = TCCManager(scope="both")
        high_risk = manager.audit(json_output=False)
        allowed, denied = _group_tcc_permissions(manager.list_permissions(json_output=False))
        facts["tcc"] = {
            "high_risk_grants": list(high_risk or []),
            "allowed": allowed,
            "denied": denied,
            "errors": list(getattr(manager, "errors", []) or []),
        }
        for error in facts["tcc"]["errors"]:
            self._record_error("tcc", "TCCManager", str(error))

    def _merge_mapping(self, target: Dict[str, Any], value: Any) -> None:
        if isinstance(value, Mapping):
            target.update(value)


def collect_facts(sections: Optional[Iterable[str]] = None, redact: bool = True) -> Dict[str, Any]:
    """Collect normalized facts for audit rules."""

    return FactCollector(redact=redact).collect(sections=sections)


def collect_host_metadata() -> Dict[str, Any]:
    """Return non-privileged host metadata for an evidence bundle."""

    return {
        "schema": "msp.facts.v1",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }


def facts_to_json(facts: Mapping[str, Any], indent: int = 2) -> str:
    """Serialize facts as stable JSON."""

    return json.dumps(facts, indent=indent, sort_keys=True)


def write_facts(facts: Mapping[str, Any], output: Optional[str] = None) -> None:
    rendered = facts_to_json(facts)
    if output:
        Path(output).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


def redact_facts(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """Redact host/user/IP details while preserving rule-relevant structure."""

    return _redact_value(_to_plain_data(facts), current_user=getpass.getuser())


def _to_plain_data(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {key: _to_plain_data(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_to_plain_data(item) for item in value]
    return value


def _redact_value(value: Any, current_user: str = "") -> Any:
    if isinstance(value, Mapping):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"hostname", "user"}:
                redacted[key] = "<redacted>"
            elif lowered in {"path", "db_path"}:
                redacted[key] = _redact_string(str(item), current_user=current_user)
            elif lowered in {"local", "remote", "local_addr", "remote_addr", "host"}:
                redacted[key] = _redact_endpoint(str(item))
            else:
                redacted[key] = _redact_value(item, current_user=current_user)
        return redacted
    if isinstance(value, list):
        return [_redact_value(item, current_user=current_user) for item in value]
    if isinstance(value, str):
        return _redact_string(value, current_user=current_user)
    return value


def _redact_string(value: str, current_user: str = "") -> str:
    redacted = value
    if current_user:
        redacted = redacted.replace(f"/Users/{current_user}", "/Users/<redacted>")
        redacted = redacted.replace(current_user, "<redacted>")
    return _IPV4_RE.sub("<ip>", redacted)


def _redact_endpoint(value: str) -> str:
    if not value:
        return value
    host, port = _split_host_port(value)
    if not host or host in {"*", "localhost", "127.0.0.1", "::1"}:
        return value
    return f"<ip>:{port}" if port else "<ip>"


def _connection_to_dict(value: Any) -> Dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _normalize_listener(item: Mapping[str, Any]) -> Dict[str, Any]:
    local = str(item.get("local") or item.get("local_addr") or "")
    host, port = _split_host_port(local)
    return {
        "process": item.get("process"),
        "pid": _maybe_int(item.get("pid")),
        "user": item.get("user"),
        "local": local,
        "host": host,
        "port": _maybe_int(port),
        "state": item.get("state", "LISTEN"),
        "protocol": item.get("protocol", "TCP"),
    }


def _normalize_connection(item: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "process": item.get("process"),
        "pid": _maybe_int(item.get("pid")),
        "user": item.get("user"),
        "local": item.get("local") or item.get("local_addr"),
        "remote": item.get("remote") or item.get("remote_addr"),
        "state": item.get("state", "ESTABLISHED"),
        "protocol": item.get("protocol", "TCP"),
    }


def _split_host_port(endpoint: str) -> Tuple[str, Optional[str]]:
    endpoint = endpoint.strip()
    if not endpoint:
        return "", None
    if "->" in endpoint:
        endpoint = endpoint.split("->", 1)[0]
    if endpoint.startswith("[") and "]:" in endpoint:
        host, port = endpoint[1:].split("]:", 1)
        return host, port
    if ":" in endpoint:
        host, port = endpoint.rsplit(":", 1)
        return host or "*", port
    return endpoint, None


def _maybe_int(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _is_exposed_host(host: Any) -> bool:
    host_value = str(host or "").strip().lower()
    return host_value not in {"", "localhost", "127.0.0.1", "::1", "[::1]"}


def _network_services_from_listeners(listeners: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    services: Dict[str, Any] = {}
    for item in listeners:
        service = _service_name_for_port(item.get("port"))
        if service:
            services[service] = {
                "enabled": True,
                "port": item.get("port"),
                "process": item.get("process"),
                "host": item.get("host"),
            }
    return services


def _network_services_from_privacy_settings(services: Any) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if not isinstance(services, Sequence) or isinstance(services, (str, bytes)):
        return normalized
    for item in services:
        if not isinstance(item, Mapping):
            continue
        name = _service_name_for_port(item.get("port")) or str(item.get("process", "")).lower()
        if name:
            normalized[name] = dict(item)
            normalized[name]["enabled"] = True
    return normalized


def _network_services_from_sharing(services: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = {}
    aliases = {"sftp": "ssh", "sshd": "ssh", "smbd": "smb", "afpd": "afp", "ftpd": "ftp"}
    for name, enabled in services.items():
        normalized[aliases.get(str(name).lower(), str(name).lower())] = {"enabled": bool(enabled)}
    return normalized


def _service_name_for_port(port: Any) -> Optional[str]:
    try:
        numeric = int(port)
    except (TypeError, ValueError):
        return None
    return {
        22: "ssh",
        548: "afp",
        445: "smb",
        5900: "vnc",
        80: "http",
        443: "https",
        21: "ftp",
    }.get(numeric)


def _flatten_startup_inventory(inventory: Any) -> List[Dict[str, Any]]:
    if not isinstance(inventory, Mapping):
        return []
    flattened: List[Dict[str, Any]] = []
    for section, rows in inventory.items():
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            for row in rows:
                if isinstance(row, Mapping):
                    item = dict(row)
                else:
                    item = {"value": row}
                item.setdefault("section", section)
                flattened.append(item)
    return flattened


def _contains_reason(item: Mapping[str, Any], needle: str) -> bool:
    haystack = " ".join(str(reason) for reason in item.get("reasons", []))
    haystack += " " + str(item.get("reason", ""))
    return needle.lower() in haystack.lower()


def _group_tcc_permissions(entries: Any) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]]:
    allowed: Dict[str, List[Dict[str, Any]]] = {}
    denied: Dict[str, List[Dict[str, Any]]] = {}
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return allowed, denied
    for entry in entries:
        item = _to_plain_data(entry)
        if not isinstance(item, Mapping):
            continue
        service = str(item.get("service") or item.get("service_name") or "unknown")
        target = allowed if item.get("allowed") else denied
        aliases = {service}
        if service.startswith("kTCCService"):
            aliases.add(service.replace("kTCCService", ""))
        for alias in aliases:
            target.setdefault(alias, []).append(dict(item))
    return allowed, denied


def _guest_enabled_services(services: Mapping[str, Any], share_points: Sequence[Mapping[str, Any]]) -> List[Any]:
    enabled = [name for name, value in services.items() if str(name).lower().startswith("guest") and bool(value)]
    for share in share_points:
        guest = share.get("guest_access")
        if str(guest).strip().lower() in {"1", "true", "yes", "on", "enabled"}:
            enabled.append(share.get("name") or share.get("path") or True)
    return enabled


def _merge_security_settings(target: Dict[str, Any], settings: Mapping[str, Any]) -> None:
    if not isinstance(settings, Mapping):
        return
    if "password_after_sleep" in settings:
        target["password_after_sleep"] = bool(settings["password_after_sleep"])
    if "password_required" in settings and "password_after_sleep" not in target:
        target["password_after_sleep"] = bool(settings["password_required"])
    if "password_delay" in settings:
        target["password_delay"] = _maybe_int(settings["password_delay"])
    idle = settings.get("idleTime", settings.get("idle_time"))
    if idle is not None:
        seconds = _maybe_int(idle)
        if isinstance(seconds, int):
            target["screen_lock_minutes"] = seconds // 60


@contextlib.contextmanager
def _suppress_module_output() -> Any:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        yield


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect normalized macOS privacy facts.")
    parser.add_argument("--json", action="store_true", help="Print full facts as JSON.")
    parser.add_argument("--output", help="Write JSON facts to a file.")
    parser.add_argument(
        "--sections",
        help=f"Comma-separated sections to collect. Default: {','.join(DEFAULT_SECTIONS)}",
    )
    parser.add_argument("--no-redact", action="store_true", help="Do not redact host/user/IP details.")
    return parser


def interactive_menu() -> None:
    """Interactive menu for fact collection."""
    sections = list(DEFAULT_SECTIONS)
    redact = True

    while True:
        print("\n" + "=" * 60)
        print("       Interrogate - Fact Collection")
        print("=" * 60)
        print("  1. Collect all facts")
        print("  2. Select sections to collect")
        print(f"  3. Toggle redaction [{'on' if redact else 'off'}]")
        print("  4. Save to file")
        print("  q. Back to main menu")
        print("=" * 60)

        choice = input("\nSelect action [1-4, q]: ").strip().lower()

        if choice in ("q", "quit"):
            break

        if choice == "1":
            print("\nCollecting facts across all sections...")
            facts = collect_facts(sections=None, redact=redact)
            write_facts(facts)
            input("\nPress Enter to continue...")
        elif choice == "2":
            print(f"\nCurrent sections: {', '.join(sections)}")
            print("Available sections:")
            for i, sec in enumerate(DEFAULT_SECTIONS, 1):
                marker = " *" if sec in sections else ""
                print(f"  {i}. {sec}{marker}")
            sel = input("\nSelect sections to include (comma-separated numbers, or 'all'): ").strip()
            if sel.lower() == "all":
                sections = list(DEFAULT_SECTIONS)
            elif sel:
                indices = []
                for part in sel.split(","):
                    part = part.strip()
                    if part.isdigit() and 1 <= int(part) <= len(DEFAULT_SECTIONS):
                        indices.append(int(part) - 1)
                if indices:
                    sections = [DEFAULT_SECTIONS[i] for i in indices]
            print(f"\nCollecting facts for: {', '.join(sections)}")
            facts = collect_facts(sections=sections, redact=redact)
            write_facts(facts)
            input("\nPress Enter to continue...")
        elif choice == "3":
            redact = not redact
            print(f"Redaction {'on' if redact else 'off'}")
        elif choice == "4":
            facts = collect_facts(sections=None, redact=redact)
            path = input("Output file path: ").strip()
            if path:
                write_facts(facts, output=path)
                print(f"Facts written to {path}")
            else:
                print("No path specified")
            input("\nPress Enter to continue...")
        else:
            print("Invalid choice")


def main(argv: Optional[Sequence[str]] = None) -> int:
    if (argv is None and len(sys.argv) <= 1) or (argv is not None and len(argv) == 0):
        interactive_menu()
        return 0
    parser = _build_parser()
    setup_completion(parser)
    args = parser.parse_args(argv)
    sections = args.sections.split(",") if args.sections else None
    facts = collect_facts(sections=sections, redact=not args.no_redact)

    if args.output:
        write_facts(facts, args.output)
    if args.json or not args.output:
        write_facts(facts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
