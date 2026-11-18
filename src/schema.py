"""Canonical finding schema v2.

Every collector (scanner, rules, tune checks, remediation results) adapts
its native shape into ``FindingV2`` here, and scan-bundle check entries are
canonicalized with provenance/evidence/incomplete/verified metadata. The
schema is additive over the v1 flat bundle entries: legacy keys are
preserved so existing consumers (doctor, fix_permission_issues, TUI) keep
working; new consumers can rely on the v2 fields.

This module imports nothing from the collectors — adapters are duck-typed
so the dependency direction stays collector → schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

FINDING_SCHEMA_VERSION = "2.0"
BUNDLE_SCHEMA_VERSION = "2.0"
BUNDLE_SCHEMA_LEGACY = "1.0"

VALID_SEVERITIES = ("ok", "n/a", "low", "medium", "high", "critical")


@dataclass
class FindingV2:
    """Canonical finding across all collectors."""

    title: str = ""
    category: str = ""
    severity: str = ""
    status: Optional[str] = None
    description: str = ""
    recommendation: str = ""
    control_id: Optional[str] = None
    check_id: str = ""
    fixable: bool = False
    fix_cmd: str = ""
    incomplete: bool = False
    incomplete_reason: str = ""
    verified: Optional[bool] = None
    evidence_refs: Tuple[str, ...] = ()
    evidence: Dict[str, Any] = field(default_factory=dict)
    references: Tuple[str, ...] = ()
    provenance: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = FINDING_SCHEMA_VERSION
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "FindingV2":
        """Tolerant parse: known fields populate dataclass, unknown keys
        are preserved under ``data``."""
        known = set(FindingV2.__dataclass_fields__) | {"schema_version"}
        kwargs: Dict[str, Any] = {}
        extras: Dict[str, Any] = {}
        for key, value in (payload or {}).items():
            if key in ("schema_version",):
                continue
            if key in known:
                if key == "evidence_refs":
                    value = tuple(value or ())
                elif key == "references":
                    value = tuple(value or ())
                kwargs[key] = value
            else:
                extras[key] = value
        finding = cls(**kwargs)
        finding.data.update(extras)
        return finding


def is_v2_finding(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == FINDING_SCHEMA_VERSION
    )


def _provenance_extra(provenance: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return dict(provenance or {})


def finding_v2_from_scanner_finding(
    f: Any, provenance: Optional[Dict[str, Any]] = None
) -> FindingV2:
    """scanner.Finding (severity/category/item/description/recommendation/
    data) → FindingV2. ``item`` becomes ``title``; ``data`` is preserved."""
    return FindingV2(
        title=getattr(f, "item", "") or "",
        category=getattr(f, "category", "") or "",
        severity=getattr(f, "severity", "") or "",
        description=getattr(f, "description", "") or "",
        recommendation=getattr(f, "recommendation", "") or "",
        evidence={},
        provenance=_provenance_extra(provenance),
        data=dict(getattr(f, "data", None) or {}),
    )


def finding_v2_from_rules_finding(
    f: Any, provenance: Optional[Dict[str, Any]] = None
) -> FindingV2:
    """rules.Finding (a concrete rule failure) → FindingV2."""
    references = list(getattr(f, "references", None) or [])
    for key in ("cis", "nist", "stig"):
        value = getattr(f, key, None)
        if value:
            references.append(f"{key}:{value}")
    prov = _provenance_extra(provenance)
    profile = getattr(f, "profile", None)
    if profile:
        prov.setdefault("profile", profile)
    return FindingV2(
        title=getattr(f, "title", "") or "",
        category=getattr(f, "category", "") or "",
        severity=getattr(f, "severity", "") or "",
        description=getattr(f, "description", "") or "",
        recommendation=getattr(f, "remediation", "") or "",
        control_id=getattr(f, "rule_id", None),
        evidence_refs=tuple(getattr(f, "evidence_paths", None) or ()),
        evidence=dict(getattr(f, "evidence", None) or {}),
        references=tuple(references),
        provenance=prov,
        data={"tags": list(getattr(f, "tags", None) or [])},
    )


def finding_v2_from_tune_finding(
    f: Any, provenance: Optional[Dict[str, Any]] = None
) -> FindingV2:
    """tune.Tuner check finding → FindingV2 (domain/check_id kept)."""
    return FindingV2(
        title=getattr(f, "title", "") or getattr(f, "name", "") or "",
        category=getattr(f, "domain", "") or "",
        severity=getattr(f, "severity", "") or "",
        status=getattr(f, "status", None),
        description=getattr(f, "detail", "") or getattr(f, "description", "") or "",
        recommendation=getattr(f, "fix_cmd", "") or getattr(f, "recommendation", "") or "",
        control_id=getattr(f, "check_id", None) or getattr(f, "rule_id", None),
        check_id=getattr(f, "check_id", "") or "",
        fixable=bool(getattr(f, "fixable", False)),
        fix_cmd=getattr(f, "fix_cmd", "") or "",
        provenance=_provenance_extra(provenance),
        data=dict(getattr(f, "data", None) or {}),
    )


def finding_v2_from_check(entry: Dict[str, Any]) -> FindingV2:
    """Legacy flat bundle check entry → FindingV2.

    n/a entries are marked incomplete with the detail as reason, making
    silent collector degradation explicit (TCC without FDA, missing
    helpers, …).
    """
    status = entry.get("status")
    detail = entry.get("detail") or ""
    incomplete = status == "n/a"
    return FindingV2(
        title=entry.get("title") or entry.get("name") or "",
        category=entry.get("domain") or "",
        severity=status if isinstance(status, str) and status != "n/a" else "",
        status=status,
        description=detail,
        recommendation=entry.get("fix_cmd") or "",
        control_id=entry.get("control_id"),
        check_id=entry.get("name") or "",
        fixable=bool(entry.get("fixable", False)),
        fix_cmd=entry.get("fix_cmd") or "",
        incomplete=incomplete,
        incomplete_reason=detail if incomplete else "",
        verified=entry.get("verified"),
        evidence_refs=tuple(entry.get("evidence_refs") or ()),
        provenance=dict(entry.get("provenance") or {}),
        data={k: v for k, v in entry.items()
              if k not in ("title", "name", "domain", "status", "detail",
                           "fixable", "fix_cmd", "control_id", "evidence_refs",
                           "provenance", "verified", "incomplete",
                           "incomplete_reason", "schema_version")},
    )


def finding_v2_from_remediation_result(
    result: Any, action: Any = None
) -> FindingV2:
    """RemediationResult → FindingV2.

    ``verified`` is intentionally None: apply_plan only reports exit
    codes today and performs no re-verification, so claiming a verified
    state here would be dishonest. The executor (Phase 2) fills it in
    once verify() steps exist.
    """
    action_metadata = dict(getattr(action, "metadata", None) or {})
    return FindingV2(
        title=getattr(action, "title", "") or "",
        category="remediation",
        severity="",
        status=getattr(result, "status", None),
        description=getattr(result, "message", "") or "",
        control_id=getattr(result, "finding_id", None),
        check_id=getattr(result, "action_id", "") or "",
        data={
            "remediation_status": getattr(result, "status", None),
            "dry_run": bool(getattr(result, "dry_run", False)),
            "rollback": getattr(result, "rollback", None),
            **({"action_metadata": action_metadata} if action_metadata else {}),
        },
    )


def canonicalize_check(
    entry: Dict[str, Any],
    *,
    collector: str = "",
    args: Optional[Iterable[str]] = None,
    timestamp: str = "",
) -> Dict[str, Any]:
    """Extend a flat v1 bundle check entry with v2 metadata (additive).

    Preserves every legacy key so fix_permission_issues' domain/fixable/
    fix_cmd contract keeps working; adds control_id, evidence_refs,
    provenance, incomplete(+reason), verified.
    """
    canonical = dict(entry)
    status = canonical.get("status")
    incomplete = status == "n/a"
    canonical.setdefault("control_id", canonical.get("name"))
    canonical.setdefault("evidence_refs", [])
    canonical["provenance"] = {
        "collector": collector or canonical.get("domain", ""),
        "args": list(args or []),
        "timestamp": timestamp,
    }
    canonical["incomplete"] = incomplete
    canonical["incomplete_reason"] = (
        (canonical.get("detail") or "") if incomplete else ""
    )
    canonical.setdefault("verified", None)
    canonical["schema_version"] = FINDING_SCHEMA_VERSION
    return canonical


def canonicalize_checks(
    checks: Iterable[Dict[str, Any]],
    *,
    collector: str = "",
    args: Optional[Iterable[str]] = None,
    timestamp: str = "",
) -> List[Dict[str, Any]]:
    return [
        canonicalize_check(c, collector=collector, args=args, timestamp=timestamp)
        for c in checks
    ]
