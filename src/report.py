"""Evidence bundle and Markdown report generation.

This module intentionally has no dependency on the rest of the CLI. It accepts
already-collected facts, audit findings, and an optional remediation plan, then
emits a redacted evidence bundle as JSON or a human-readable Markdown report.
"""

from __future__ import annotations

import argparse
import copy
import json
import platform
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from src.command import interactive_menu as cmd_menu, interactive_select, setup_completion, suggest_command


BUNDLE_SCHEMA_VERSION = "1.0"
TOP_FINDING_LIMIT = 10

SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
    "unknown": 5,
}

SENSITIVE_FIELD_PATTERNS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "access_key",
    "auth",
    "authorization",
    "credential",
    "cookie",
    "session",
)

IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
IPV6_RE = re.compile(
    r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def host_metadata() -> Dict[str, str]:
    return {
        "hostname": socket.gethostname(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_output(path: str, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(pattern in normalized for pattern in SENSITIVE_FIELD_PATTERNS)


def _redact_string(value: str) -> str:
    redacted = IPV4_RE.sub("[REDACTED_IP]", value)
    redacted = IPV6_RE.sub("[REDACTED_IP]", redacted)
    return redacted


def redact(value: Any) -> Any:
    """Return a deep-redacted copy of JSON-like data."""

    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return copy.deepcopy(value)


def normalize_findings(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, Mapping):
        findings = payload.get("findings", [])
    else:
        findings = payload
    if not isinstance(findings, list):
        raise ValueError("findings JSON must be a list or contain a 'findings' list")
    normalized = []
    for item in findings:
        if not isinstance(item, Mapping):
            raise ValueError("each finding must be an object")
        normalized.append(dict(item))
    return normalized


def severity_rank(finding: Mapping[str, Any]) -> int:
    severity = str(finding.get("severity", "unknown")).lower()
    return SEVERITY_ORDER.get(severity, SEVERITY_ORDER["unknown"])


def summarize_findings(findings: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(findings)
    by_severity = {severity: 0 for severity in SEVERITY_ORDER}
    by_category: Dict[str, int] = {}
    for finding in rows:
        severity = str(finding.get("severity", "unknown")).lower()
        if severity not in by_severity:
            severity = "unknown"
        category = str(finding.get("category", "uncategorized") or "uncategorized")
        by_severity[severity] += 1
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "total_findings": len(rows),
        "by_severity": by_severity,
        "by_category": dict(sorted(by_category.items())),
    }


def top_findings(findings: Sequence[Mapping[str, Any]], limit: int = TOP_FINDING_LIMIT) -> List[Dict[str, Any]]:
    sorted_findings = sorted(findings, key=severity_rank)
    top: List[Dict[str, Any]] = []
    for finding in sorted_findings[:limit]:
        top.append(
            {
                "severity": finding.get("severity", "unknown"),
                "rule_id": finding.get("rule_id", ""),
                "title": finding.get("title", ""),
                "category": finding.get("category", ""),
                "remediation": finding.get("remediation", ""),
                "remediation_id": finding.get("remediation_id"),
            }
        )
    return top


def build_bundle(facts: Any, findings_payload: Any, plan: Optional[Any] = None) -> Dict[str, Any]:
    findings = normalize_findings(findings_payload)
    redacted_findings = redact(findings)
    if not isinstance(redacted_findings, list):
        raise ValueError("redacted findings must remain a list")

    bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "host": redact(host_metadata()),
        "summary": summarize_findings(redacted_findings),
        "top_findings": top_findings(redacted_findings),
        "facts": redact(facts),
        "findings": redacted_findings,
    }
    if plan is not None:
        bundle["remediation_plan"] = redact(plan)
    return bundle


def render_json(bundle: Mapping[str, Any]) -> str:
    return json.dumps(bundle, indent=2, sort_keys=True) + "\n"


def _md_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _render_count_table(title: str, counts: Mapping[str, int]) -> List[str]:
    lines = [f"## {title}", "", "| Name | Count |", "| --- | ---: |"]
    for name, count in counts.items():
        lines.append(f"| {_md_escape(name)} | {count} |")
    lines.append("")
    return lines


def render_markdown(bundle: Mapping[str, Any]) -> str:
    summary = bundle.get("summary", {})
    host = bundle.get("host", {})
    lines = [
        "# macOS Privacy Evidence Report",
        "",
        f"- Generated at: `{_md_escape(bundle.get('generated_at'))}`",
        f"- Bundle schema: `{_md_escape(bundle.get('schema_version'))}`",
        f"- Host: `{_md_escape(host.get('hostname', 'unknown'))}`",
        f"- Platform: `{_md_escape(host.get('system', 'unknown'))} {_md_escape(host.get('release', ''))}`",
        f"- Total findings: `{_md_escape(summary.get('total_findings', 0))}`",
        "",
    ]

    lines.extend(_render_count_table("Findings By Severity", summary.get("by_severity", {})))
    lines.extend(_render_count_table("Findings By Category", summary.get("by_category", {})))

    lines.extend(
        [
            "## Top Findings",
            "",
            "| Severity | Rule | Category | Finding | Remediation |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for finding in bundle.get("top_findings", []):
        lines.append(
            "| {severity} | {rule_id} | {category} | {title} | {remediation} |".format(
                severity=_md_escape(finding.get("severity", "unknown")).upper(),
                rule_id=_md_escape(finding.get("rule_id", "")),
                category=_md_escape(finding.get("category", "")),
                title=_md_escape(finding.get("title", "")),
                remediation=_md_escape(finding.get("remediation", "")),
            )
        )
    lines.append("")

    if "remediation_plan" in bundle:
        lines.extend(["## Remediation Plan", "", "```json", json.dumps(bundle["remediation_plan"], indent=2, sort_keys=True), "```", ""])

    lines.extend(["## Evidence Bundle", "", "```json", render_json(bundle).rstrip(), "```", ""])
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate redacted macOS privacy evidence reports.")
    parser.add_argument("--facts", required=True, help="Path to facts JSON")
    parser.add_argument("--findings", required=True, help="Path to findings JSON")
    parser.add_argument("--plan", help="Optional remediation plan JSON")
    parser.add_argument("--format", choices=("json", "md"), required=True, help="Output format")
    parser.add_argument("--output", required=True, help="Output file path")
    return parser


def interactive_menu() -> None:
    """Interactive menu for evidence report generation."""
    from .facts import collect_facts, facts_to_json
    from .rules import evaluate as rules_evaluate, findings_to_json

    while True:
        action = cmd_menu([
            ("full", "Full chain", "Interrogate, audit, then generate report"),
            ("load", "Load files", "Load facts + findings from JSON files"),
        ], title="Report - Evidence Report Generator")

        if action is None:
            break

        if action == "full":
            print("\nCollecting system facts...")
            try:
                facts = collect_facts(redact=False)
                print("Evaluating with personal profile...")
                findings = rules_evaluate(facts, profile="personal")
                fmt_result = interactive_select([
                    ("json", "JSON", None),
                    ("md", "Markdown", None),
                ], title="Select format")
                fmt = fmt_result[0] if fmt_result else "md"
                output = input("Output file path: ").strip()
                if output:
                    bundle = build_bundle(facts, findings, None)
                    content = render_json(bundle) if fmt == "json" else render_markdown(bundle)
                    write_output(output, content)
                    print(f"Report written to {output}")
                else:
                    print("No output path specified")
            except Exception as e:
                print(f"Error: {e}")
            input("\nPress Enter to continue...")
        elif action == "load":
            facts_path = input("Path to facts JSON: ").strip()
            findings_path = input("Path to findings JSON: ").strip()
            plan_path = input("Path to remediation plan (optional): ").strip() or None
            if facts_path and findings_path:
                try:
                    facts = load_json(facts_path)
                    findings = load_json(findings_path)
                    plan = load_json(plan_path) if plan_path else None
                    fmt_result = interactive_select([
                        ("json", "JSON", None),
                        ("md", "Markdown", None),
                    ], title="Select format")
                    fmt = fmt_result[0] if fmt_result else "md"
                    output = input("Output file path: ").strip()
                    if output:
                        bundle = build_bundle(facts, findings, plan)
                        content = render_json(bundle) if fmt == "json" else render_markdown(bundle)
                        write_output(output, content)
                        print(f"Report written to {output}")
                except Exception as e:
                    print(f"Error: {e}")
            input("\nPress Enter to continue...")


def main(argv: Optional[Sequence[str]] = None) -> int:
    if (argv is None and len(sys.argv) <= 1) or (argv is not None and len(argv) == 0):
        interactive_menu()
        return 0
    parser = _build_parser()
    setup_completion(parser)
    args = parser.parse_args(argv)

    try:
        facts = load_json(args.facts)
        findings = load_json(args.findings)
        plan = load_json(args.plan) if args.plan else None
        bundle = build_bundle(facts, findings, plan)
        content = render_json(bundle) if args.format == "json" else render_markdown(bundle)
        write_output(args.output, content)
    except Exception as exc:  # pragma: no cover - exact argparse stderr is not useful here
        print(f"msp-report: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
