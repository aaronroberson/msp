#!/usr/bin/env python3
"""Lightweight audit rule engine for normalized macOS privacy facts.

The engine is intentionally dependency-free and side-effect free: callers pass
already-collected facts, rules evaluate those facts, and findings can be
rendered as JSON or a small table.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from src.command import (
    interactive_menu as cmd_interactive_menu,
    interactive_select as cmd_interactive_select,
    setup_completion,
    suggest_command,
)

try:
    from rich.console import Console
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    Console = None
    Table = None
    RICH_AVAILABLE = False


Facts = Mapping[str, Any]
Predicate = Callable[[Facts], bool]


SEVERITY_ORDER = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


PROFILE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "personal": {
        "description": "Balanced privacy and security checks for an individual Mac.",
        "minimum_severity": "low",
        "categories": [
            "firewall",
            "filevault",
            "gatekeeper",
            "sharing",
            "tcc",
            "startup",
            "network",
            "security_settings",
        ],
    },
    "developer": {
        "description": "Personal baseline with developer-machine exposure checks.",
        "minimum_severity": "low",
        "categories": [
            "firewall",
            "filevault",
            "gatekeeper",
            "sharing",
            "tcc",
            "startup",
            "network",
            "security_settings",
        ],
    },
    "enterprise": {
        "description": "Stricter baseline suitable for managed business devices.",
        "minimum_severity": "medium",
        "categories": [
            "firewall",
            "filevault",
            "gatekeeper",
            "sharing",
            "tcc",
            "startup",
            "network",
            "security_settings",
        ],
    },
    "high_security": {
        "description": "Conservative baseline for sensitive or high-risk systems.",
        "minimum_severity": "low",
        "categories": [
            "firewall",
            "filevault",
            "gatekeeper",
            "sharing",
            "tcc",
            "startup",
            "network",
            "security_settings",
        ],
    },
}


def get_path(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    """Read a dotted path from nested mappings/lists.

    List indexes are supported with numeric path components, for example
    ``network.listeners.0.port``.
    """

    current: Any = data
    for part in path.split("."):
        if isinstance(current, Mapping):
            if part not in current:
                return default
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, (str, bytes)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
        else:
            return default
    return current


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _contains_any(values: Any, candidates: Sequence[Any]) -> bool:
    if values is None:
        return False
    if isinstance(values, Mapping):
        values = values.keys()
    if isinstance(values, str):
        values = [values]
    try:
        return any(item in values for item in candidates)
    except TypeError:
        return False


def _list_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, Mapping):
        return len(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value)
    return 1


def _path_exists(facts: Facts, path: str) -> bool:
    sentinel = object()
    return get_path(facts, path, sentinel) is not sentinel


def _service_enabled(facts: Facts, path: str) -> bool:
    value = get_path(facts, path)
    if isinstance(value, Mapping):
        for key in ("enabled", "running", "active", "allowed"):
            if key in value:
                return _as_bool(value[key])
    return _as_bool(value)


@dataclass(frozen=True)
class Rule:
    """A reusable audit rule over normalized fact dictionaries."""

    id: str
    title: str
    category: str
    severity: str
    description: str
    remediation: str
    predicate: Predicate = field(repr=False, compare=False)
    profiles: Sequence[str] = field(default_factory=lambda: tuple(PROFILE_DEFINITIONS))
    remediation_id: Optional[str] = None
    evidence_paths: Sequence[str] = field(default_factory=tuple)
    cis: Optional[str] = None
    nist: Optional[str] = None
    stig: Optional[str] = None
    references: Sequence[str] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITY_ORDER:
            raise ValueError(f"Unknown severity for {self.id}: {self.severity}")
        unknown_profiles = set(self.profiles) - set(PROFILE_DEFINITIONS)
        if unknown_profiles:
            raise ValueError(f"Unknown profiles for {self.id}: {sorted(unknown_profiles)}")

    def applies_to_profile(self, profile: str) -> bool:
        return profile in self.profiles

    def evaluate(self, facts: Facts, profile: str = "personal") -> Optional["Finding"]:
        if not self.applies_to_profile(profile):
            return None
        if self.predicate(facts):
            evidence = self.extract_evidence(facts)
            return Finding.from_rule(self, profile=profile, evidence=evidence)
        return None

    def extract_evidence(self, facts: Facts) -> Dict[str, Any]:
        """Return compact evidence values for common rule categories."""

        evidence_paths = {
            "firewall": ["firewall.enabled", "firewall.block_all", "firewall.stealth"],
            "filevault": ["filevault.enabled", "filevault.status"],
            "gatekeeper": ["gatekeeper.enabled", "gatekeeper.status"],
            "sharing": ["sharing.enabled", "sharing.services", "sharing.share_points"],
            "tcc": ["tcc.denied", "tcc.allowed", "tcc.high_risk_grants"],
            "startup": ["startup.items", "startup.unsigned_items", "startup.suspicious_items"],
            "network": ["network.listeners", "network.exposed_services", "network.connections"],
            "security_settings": [
                "security_settings.password_after_sleep",
                "security_settings.password_delay",
                "security_settings.screen_lock_minutes",
            ],
        }
        evidence: Dict[str, Any] = {}
        paths = tuple(self.evidence_paths) or tuple(evidence_paths.get(self.category, []))
        for path in paths:
            value = get_path(facts, path)
            if value is not None:
                evidence[path] = value
        return evidence


@dataclass(frozen=True)
class Finding:
    """A concrete rule failure."""

    rule_id: str
    title: str
    category: str
    severity: str
    description: str
    remediation: str
    profile: str
    remediation_id: Optional[str] = None
    evidence_paths: Sequence[str] = field(default_factory=tuple)
    cis: Optional[str] = None
    nist: Optional[str] = None
    stig: Optional[str] = None
    references: Sequence[str] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)
    evidence: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_rule(cls, rule: Rule, profile: str, evidence: Optional[Dict[str, Any]] = None) -> "Finding":
        return cls(
            rule_id=rule.id,
            title=rule.title,
            category=rule.category,
            severity=rule.severity,
            description=rule.description,
            remediation=rule.remediation,
            profile=profile,
            remediation_id=rule.remediation_id,
            evidence_paths=tuple(rule.evidence_paths),
            cis=rule.cis,
            nist=rule.nist,
            stig=rule.stig,
            references=tuple(rule.references),
            tags=tuple(rule.tags),
            evidence=evidence or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RuleEngine:
    """Evaluate audit rules against normalized facts."""

    def __init__(self, rules: Optional[Iterable[Rule]] = None):
        self.rules = list(rules if rules is not None else default_rules())

    def evaluate(
        self,
        facts: Facts,
        profile: str = "personal",
        categories: Optional[Iterable[str]] = None,
        minimum_severity: Optional[str] = None,
    ) -> List[Finding]:
        if profile not in PROFILE_DEFINITIONS:
            raise ValueError(f"Unknown profile: {profile}")

        profile_def = PROFILE_DEFINITIONS[profile]
        allowed_categories = set(categories or profile_def["categories"])
        min_severity = minimum_severity or profile_def.get("minimum_severity", "info")
        min_rank = SEVERITY_ORDER[min_severity]
        facts_with_profile = dict(facts)
        facts_with_profile["_profile"] = profile

        findings: List[Finding] = []
        for rule in self.rules:
            if rule.category not in allowed_categories:
                continue
            if SEVERITY_ORDER[rule.severity] < min_rank:
                continue
            finding = rule.evaluate(facts_with_profile, profile=profile)
            if finding:
                findings.append(finding)

        return sorted(
            findings,
            key=lambda item: (-SEVERITY_ORDER[item.severity], item.category, item.rule_id),
        )

    def rules_for_profile(self, profile: str) -> List[Rule]:
        if profile not in PROFILE_DEFINITIONS:
            raise ValueError(f"Unknown profile: {profile}")
        return [rule for rule in self.rules if rule.applies_to_profile(profile)]


def rule(
    rule_id: str,
    title: str,
    category: str,
    severity: str,
    description: str,
    remediation: str,
    predicate: Predicate,
    profiles: Sequence[str] = tuple(PROFILE_DEFINITIONS),
    remediation_id: Optional[str] = None,
    evidence_paths: Sequence[str] = (),
    cis: Optional[str] = None,
    nist: Optional[str] = None,
    stig: Optional[str] = None,
    references: Sequence[str] = (),
    tags: Sequence[str] = (),
) -> Rule:
    """Factory used by built-ins and callers that want concise rule creation."""

    return Rule(
        id=rule_id,
        title=title,
        category=category,
        severity=severity,
        description=description,
        remediation=remediation,
        predicate=predicate,
        profiles=tuple(profiles),
        remediation_id=remediation_id,
        evidence_paths=tuple(evidence_paths),
        cis=cis,
        nist=nist,
        stig=stig,
        references=tuple(references),
        tags=tuple(tags),
    )


def default_rules() -> List[Rule]:
    """Return built-in rules for common macOS privacy and security facts."""

    all_profiles = tuple(PROFILE_DEFINITIONS)
    strict_profiles = ("enterprise", "high_security")
    developer_plus = ("developer", "enterprise", "high_security")

    return [
        rule(
            "FW-001",
            "Application firewall is disabled",
            "firewall",
            "high",
            "The macOS application firewall is not enabled.",
            "Enable the application firewall.",
            lambda f: _path_exists(f, "firewall.enabled")
            and not _as_bool(get_path(f, "firewall.enabled")),
            profiles=all_profiles,
            remediation_id="firewall.enable",
            evidence_paths=("firewall.enabled",),
            cis="CIS Apple macOS Firewall",
            nist="CM-7, SC-7",
            stig="APPL-14-002021",
        ),
        rule(
            "FW-002",
            "Stealth mode is disabled",
            "firewall",
            "medium",
            "Stealth mode reduces responses to unsolicited network probes.",
            "Enable firewall stealth mode.",
            lambda f: get_path(f, "firewall.stealth") is not None
            and not _as_bool(get_path(f, "firewall.stealth")),
            profiles=strict_profiles,
            remediation_id="firewall.stealth.enable",
            evidence_paths=("firewall.stealth",),
            cis="CIS Apple macOS Firewall",
            nist="SC-7",
        ),
        rule(
            "FV-001",
            "FileVault is disabled",
            "filevault",
            "critical",
            "Full-disk encryption is not enabled.",
            "Enable FileVault and escrow the recovery key where appropriate.",
            lambda f: _path_exists(f, "filevault.enabled")
            and not _as_bool(get_path(f, "filevault.enabled")),
            profiles=all_profiles,
            remediation_id="filevault.enable.guidance",
            evidence_paths=("filevault.enabled",),
            cis="CIS Apple macOS FileVault",
            nist="SC-28",
            stig="APPL-14-005020",
        ),
        rule(
            "GK-001",
            "Gatekeeper is disabled",
            "gatekeeper",
            "high",
            "Gatekeeper is not enforcing app assessment.",
            "Enable Gatekeeper with spctl.",
            lambda f: get_path(f, "gatekeeper.enabled") is not None
            and not _as_bool(get_path(f, "gatekeeper.enabled")),
            profiles=all_profiles,
            remediation_id="gatekeeper.enable",
            evidence_paths=("gatekeeper.enabled",),
            cis="CIS Apple macOS Gatekeeper",
            nist="SI-7",
            stig="APPL-14-002060",
        ),
        rule(
            "SH-001",
            "File sharing is enabled",
            "sharing",
            "medium",
            "Sharing services increase local-network exposure.",
            "Disable unneeded sharing services and remove unused share points.",
            lambda f: _as_bool(get_path(f, "sharing.enabled"))
            or _list_count(get_path(f, "sharing.share_points")) > 0,
            profiles=("personal", "enterprise", "high_security"),
            remediation_id="sharing.disable_all",
            evidence_paths=("sharing.enabled", "sharing.share_points"),
            cis="CIS Apple macOS Sharing",
            nist="CM-7, SC-7",
        ),
        rule(
            "SH-002",
            "Guest sharing access is enabled",
            "sharing",
            "high",
            "Guest sharing allows access without a named local account.",
            "Disable guest access for all share points.",
            lambda f: _contains_any(get_path(f, "sharing.guest_enabled_services"), [True, "true", "on", "enabled"])
            or any(
                _as_bool(item.get("guest_access"))
                for item in get_path(f, "sharing.share_points", [])
                if isinstance(item, Mapping)
            ),
            profiles=all_profiles,
            remediation_id="sharing.disable_guest",
            evidence_paths=("sharing.guest_enabled_services", "sharing.share_points"),
            cis="CIS Apple macOS Sharing",
            nist="AC-2, AC-3",
        ),
        rule(
            "TCC-001",
            "High-risk privacy grants are present",
            "tcc",
            "high",
            "One or more apps have sensitive TCC permissions.",
            "Review camera, microphone, screen recording, accessibility, and full disk access grants.",
            lambda f: _list_count(get_path(f, "tcc.high_risk_grants")) > 0,
            profiles=all_profiles,
            remediation_id="tcc.review_high_risk",
            evidence_paths=("tcc.high_risk_grants",),
            cis="CIS Apple macOS Privacy Preferences Policy Control",
            nist="AC-6",
        ),
        rule(
            "TCC-002",
            "Screen Recording permissions are granted",
            "tcc",
            "medium",
            "Screen Recording grants can expose sensitive on-screen data.",
            "Remove Screen Recording access from apps that do not require it.",
            lambda f: _list_count(get_path(f, "tcc.allowed.ScreenCapture")) > 0
            or _list_count(get_path(f, "tcc.allowed.kTCCServiceScreenCapture")) > 0,
            profiles=strict_profiles,
            remediation_id="tcc.reset_screen_capture",
            evidence_paths=("tcc.allowed.ScreenCapture", "tcc.allowed.kTCCServiceScreenCapture"),
            cis="CIS Apple macOS Privacy Preferences Policy Control",
            nist="AC-6",
        ),
        rule(
            "ST-001",
            "Unsigned startup items are present",
            "startup",
            "high",
            "Unsigned startup items can indicate risky persistence.",
            "Investigate unsigned startup items and remove unauthorized entries.",
            lambda f: _list_count(get_path(f, "startup.unsigned_items")) > 0,
            profiles=all_profiles,
            remediation_id="startup.review_unsigned",
            evidence_paths=("startup.unsigned_items",),
            cis="CIS Apple macOS System Integrity",
            nist="CM-6, SI-7",
        ),
        rule(
            "ST-002",
            "Suspicious startup items are present",
            "startup",
            "critical",
            "Suspicious persistence entries were found.",
            "Quarantine the host if needed, then investigate and remove suspicious persistence.",
            lambda f: _list_count(get_path(f, "startup.suspicious_items")) > 0,
            profiles=all_profiles,
            remediation_id="startup.review_suspicious",
            evidence_paths=("startup.suspicious_items",),
            nist="SI-4, SI-7",
        ),
        rule(
            "NW-001",
            "Public listening services are present",
            "network",
            "medium",
            "A process is listening on a non-loopback interface.",
            "Confirm each listener is expected and restrict it to localhost where possible.",
            lambda f: _list_count(get_path(f, "network.exposed_services")) > 0,
            profiles=all_profiles,
            remediation_id="network.review_exposed_services",
            evidence_paths=("network.exposed_services",),
            cis="CIS Apple macOS Network Services",
            nist="CM-7, SC-7",
        ),
        rule(
            "NW-002",
            "Remote login service is active",
            "network",
            "medium",
            "SSH or remote login appears to be active.",
            "Disable remote login unless it is explicitly required.",
            lambda f: _service_enabled(f, "network.services.ssh")
            or _service_enabled(f, "sharing.services.ssh")
            or _service_enabled(f, "sharing.services.sftp"),
            profiles=("personal", "enterprise", "high_security"),
            remediation_id="remote_login.disable",
            evidence_paths=("network.services.ssh", "sharing.services.ssh", "sharing.services.sftp"),
            cis="CIS Apple macOS Remote Login",
            nist="AC-17",
            stig="APPL-14-004040",
        ),
        rule(
            "SEC-001",
            "Password after sleep is disabled",
            "security_settings",
            "high",
            "The system does not require a password after sleep or screen saver.",
            "Require a password immediately after sleep or screen saver.",
            lambda f: get_path(f, "security_settings.password_after_sleep") is not None
            and not _as_bool(get_path(f, "security_settings.password_after_sleep")),
            profiles=all_profiles,
            remediation_id="security.password_after_sleep.enable",
            evidence_paths=("security_settings.password_after_sleep",),
            cis="CIS Apple macOS Screen Saver",
            nist="AC-11",
            stig="APPL-14-000060",
        ),
        rule(
            "SEC-002",
            "Password-after-sleep delay is too long",
            "security_settings",
            "medium",
            "The password prompt delay after sleep or screen saver exceeds the selected profile.",
            "Set password-after-sleep delay to 0 seconds for stricter profiles or under 60 seconds for personal use.",
            lambda f: _password_delay_exceeds_profile(f),
            profiles=all_profiles,
            remediation_id="security.password_delay.set_zero",
            evidence_paths=("security_settings.password_delay",),
            cis="CIS Apple macOS Screen Saver",
            nist="AC-11",
        ),
        rule(
            "SEC-003",
            "Screen lock timeout is too long",
            "security_settings",
            "medium",
            "The screen lock timeout exceeds the selected profile.",
            "Reduce screen lock timeout to match the selected baseline.",
            lambda f: _screen_lock_exceeds_profile(f),
            profiles=all_profiles,
            remediation_id="security.screen_lock.set_profile",
            evidence_paths=("security_settings.screen_lock_minutes",),
            cis="CIS Apple macOS Screen Saver",
            nist="AC-11",
        ),
        rule(
            "DEV-001",
            "Developer ports are exposed",
            "network",
            "low",
            "Common development ports are listening on a public interface.",
            "Bind local development services to 127.0.0.1 or restrict access with the firewall.",
            lambda f: _has_exposed_developer_port(f),
            profiles=developer_plus,
            remediation_id="network.review_developer_ports",
            evidence_paths=("network.exposed_services",),
            nist="CM-7, SC-7",
            tags=("developer",),
        ),
    ]


def _password_delay_exceeds_profile(facts: Facts) -> bool:
    delay = get_path(facts, "security_settings.password_delay")
    profile = str(get_path(facts, "_profile", "personal"))
    if delay is None:
        return False
    try:
        delay_value = int(delay)
    except (TypeError, ValueError):
        return True
    max_delay = 0 if profile in {"enterprise", "high_security"} else 60
    return delay_value > max_delay


def _screen_lock_exceeds_profile(facts: Facts) -> bool:
    timeout = get_path(facts, "security_settings.screen_lock_minutes")
    profile = str(get_path(facts, "_profile", "personal"))
    if timeout is None:
        return False
    try:
        timeout_value = int(timeout)
    except (TypeError, ValueError):
        return True
    max_timeout = {"personal": 15, "developer": 15, "enterprise": 10, "high_security": 5}.get(profile, 15)
    return timeout_value > max_timeout


def _has_exposed_developer_port(facts: Facts) -> bool:
    developer_ports = {3000, 3001, 5000, 5173, 8000, 8080, 9229}
    services = get_path(facts, "network.exposed_services", [])
    if not isinstance(services, Sequence) or isinstance(services, (str, bytes)):
        return False
    for service in services:
        if not isinstance(service, Mapping):
            continue
        try:
            port = int(service.get("port", 0))
        except (TypeError, ValueError):
            continue
        if port in developer_ports:
            return True
    return False


def evaluate(
    facts: Facts,
    profile: str = "personal",
    rules: Optional[Iterable[Rule]] = None,
    categories: Optional[Iterable[str]] = None,
    minimum_severity: Optional[str] = None,
) -> List[Finding]:
    """Convenience wrapper around ``RuleEngine.evaluate``."""

    return RuleEngine(rules).evaluate(
        facts,
        profile=profile,
        categories=categories,
        minimum_severity=minimum_severity,
    )


def findings_to_json(findings: Iterable[Finding], indent: int = 2) -> str:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "findings": [finding.to_dict() for finding in findings],
    }
    return json.dumps(payload, indent=indent, sort_keys=True)


def findings_to_table(findings: Iterable[Finding], use_rich: Optional[bool] = None) -> str:
    """Render findings as a rich table when available, otherwise plain text."""

    rows = list(findings)
    rich_enabled = RICH_AVAILABLE if use_rich is None else use_rich and RICH_AVAILABLE
    if rich_enabled and Console and Table:
        table = Table(title="Audit Findings")
        table.add_column("Severity")
        table.add_column("Rule")
        table.add_column("Category")
        table.add_column("Title")
        for item in rows:
            table.add_row(item.severity.upper(), item.rule_id, item.category, item.title)
        console = Console(file=io.StringIO(), record=True)
        console.print(table)
        return console.export_text()

    if not rows:
        return "No findings."

    headers = ("Severity", "Rule", "Category", "Title")
    rendered_rows = [(f.severity.upper(), f.rule_id, f.category, f.title) for f in rows]
    widths = [
        max(len(str(row[index])) for row in [headers, *rendered_rows])
        for index in range(len(headers))
    ]
    line = "  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    separator = "  ".join("-" * width for width in widths)
    body = [
        "  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row))
        for row in rendered_rows
    ]
    return "\n".join([line, separator, *body])


def summarize(findings: Iterable[Finding]) -> Dict[str, Any]:
    rows = list(findings)
    by_severity = {severity: 0 for severity in SEVERITY_ORDER}
    by_category: Dict[str, int] = {}
    for finding in rows:
        by_severity[finding.severity] += 1
        by_category[finding.category] = by_category.get(finding.category, 0) + 1
    return {
        "count": len(rows),
        "by_severity": by_severity,
        "by_category": by_category,
    }


def load_facts(path: str) -> Dict[str, Any]:
    if path == "-":
        if sys.stdin.isatty():
            print("Error: audit requires facts from stdin or a file.", file=sys.stderr)
            print("Usage: msp interrogate --json | msp audit", file=sys.stderr)
            print("       msp audit facts.json", file=sys.stderr)
            sys.exit(1)
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate macOS privacy facts with built-in audit rules.")
    parser.add_argument("facts", nargs="?", default="-", help="Path to facts JSON, or '-' for stdin.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_DEFINITIONS),
        default="personal",
        help="Built-in audit profile to evaluate.",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format.",
    )
    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        help="Limit evaluation to a category. May be repeated.",
    )
    parser.add_argument(
        "--minimum-severity",
        choices=sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get),
        help="Override the profile minimum severity.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Print built-in profile definitions and exit.",
    )
    return parser


def interactive_menu() -> None:
    """Interactive menu for security audit."""
    from .facts import collect_facts

    while True:
        action = cmd_interactive_menu([
            ("1", "Collect fresh facts & run audit", None),
            ("2", "Load facts from file & run audit", None),
            ("3", "List available profiles", None),
        ], title="Audit - Security Rule Evaluation")

        if action is None:
            break

        if action == "1":
            print("\nCollecting system facts...")
            facts = collect_facts(redact=False)
            profiles = sorted(PROFILE_DEFINITIONS)
            items = [(p, p, None) for p in profiles]
            result = cmd_interactive_select(items, title="Select profile")
            profile = result[0] if result else "personal"
            print(f"\nEvaluating against profile: {profile}")
            findings = evaluate(facts, profile=profile)
            if findings:
                print(findings_to_table(findings))
            else:
                print("No findings.")
            input("\nPress Enter to continue...")
        elif action == "2":
            path = input("Path to facts JSON file: ").strip()
            if path:
                try:
                    facts = load_facts(path)
                    profiles = sorted(PROFILE_DEFINITIONS)
                    items = [(p, p, None) for p in profiles]
                    result = cmd_interactive_select(items, title="Select profile")
                    profile = result[0] if result else "personal"
                    findings = evaluate(facts, profile=profile)
                    if findings:
                        print(findings_to_table(findings))
                    else:
                        print("No findings.")
                except Exception as e:
                    print(f"Error: {e}")
            input("\nPress Enter to continue...")
        elif action == "3":
            print("\nAvailable profiles:")
            for pid, pdef in PROFILE_DEFINITIONS.items():
                print(f"\n  {pid}: {pdef.get('description', '')}")
            input("\nPress Enter to continue...")


def main(argv: Optional[Sequence[str]] = None) -> int:
    if (argv is None and len(sys.argv) <= 1) or (argv is not None and len(argv) == 0):
        interactive_menu()
        return 0
    parser = _build_parser()
    setup_completion(parser)
    args = parser.parse_args(argv)

    if args.list_profiles:
        print(json.dumps(PROFILE_DEFINITIONS, indent=2, sort_keys=True))
        return 0

    facts = load_facts(args.facts)
    findings = evaluate(
        facts,
        profile=args.profile,
        categories=args.categories,
        minimum_severity=args.minimum_severity,
    )

    if args.format == "json":
        print(findings_to_json(findings))
    else:
        print(findings_to_table(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
