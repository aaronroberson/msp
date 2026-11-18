"""Tests for the canonical finding schema v2 and its adapters."""

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import schema
from src.schema import (
    BUNDLE_SCHEMA_VERSION,
    FINDING_SCHEMA_VERSION,
    FindingV2,
    canonicalize_check,
    canonicalize_checks,
    finding_v2_from_check,
    finding_v2_from_remediation_result,
    finding_v2_from_rules_finding,
    finding_v2_from_scanner_finding,
    finding_v2_from_tune_finding,
    is_v2_finding,
)


def test_round_trip_to_dict_from_dict() -> None:
    f = FindingV2(
        title="Firewall off",
        category="firewall",
        severity="high",
        description="The application firewall is disabled.",
        recommendation="Enable it.",
        control_id="FW-001",
        evidence_refs=("lsof:1",),
        provenance={"collector": "tune"},
    )
    d = f.to_dict()
    assert d["schema_version"] == FINDING_SCHEMA_VERSION
    assert d["evidence_refs"] == ("lsof:1",)  # dataclass truth; json.dumps serializes tuples as arrays
    back = FindingV2.from_dict(d)
    assert back == f


def test_from_dict_unknown_keys_go_to_data() -> None:
    d = {
        "title": "t",
        "category": "c",
        "severity": "low",
        "some_future_field": "x",
    }
    f = FindingV2.from_dict(d)
    assert f.title == "t"
    assert f.data["some_future_field"] == "x"


def test_is_v2_finding() -> None:
    assert is_v2_finding({"schema_version": "2.0"})
    assert not is_v2_finding({"schema_version": "1.0"})
    assert not is_v2_finding({})


def test_adapter_from_scanner_finding() -> None:
    from src.scanner import Finding as ScannerFinding

    f = ScannerFinding(
        severity="medium",
        category="permissions",
        item="sudoers writable",
        description="d",
        recommendation="r",
        data={"path": "/etc/sudoers"},
    )
    v2 = finding_v2_from_scanner_finding(f)
    d = v2.to_dict()
    assert v2.title == "sudoers writable"
    assert v2.category == "permissions"
    assert v2.data["path"] == "/etc/sudoers"
    assert "item" not in d  # item alias is added by the caller in scanner.py, not the adapter
    assert d["schema_version"] == FINDING_SCHEMA_VERSION


def test_adapter_from_rules_finding() -> None:
    from src.rules import Finding as RulesFinding

    f = RulesFinding(
        rule_id="FW-001",
        title="Firewall disabled",
        category="firewall",
        severity="high",
        description="d",
        remediation="r",
        profile="default",
        evidence_paths=("/tmp/evidence",),
        cis="5.1",
        references=("https://example.com",),
        tags=("network",),
    )
    v2 = finding_v2_from_rules_finding(f)
    d = v2.to_dict()
    assert v2.control_id == "FW-001"
    assert v2.evidence_refs == ("/tmp/evidence",)
    assert v2.provenance["profile"] == "default"
    assert "cis:5.1" in v2.references
    assert "https://example.com" in v2.references
    assert "rule_id" not in d  # rule_id alias is added by Finding.to_v2, not the adapter
    # to_v2 on the real dataclass adds the alias remediate.plan_from_findings needs.
    v2_alias = f.to_v2()
    assert v2_alias["rule_id"] == "FW-001"
    assert v2_alias["schema_version"] == FINDING_SCHEMA_VERSION


def test_adapter_from_tune_finding() -> None:
    from src.tune import Finding as TuneFinding

    f = TuneFinding(
        domain="tcc",
        severity="low",
        title="TCC reads incomplete",
        description="TCC.db not readable",
        fixable=False,
        fix_cmd="",
        detail="needs FDA",
        check_id="tcc_consistency",
    )
    v2 = finding_v2_from_tune_finding(f)
    assert v2.control_id == "tcc_consistency"
    assert v2.category == "tcc"
    assert v2.fixable is False
    # detail lands in description, fix_cmd in recommendation (not data).
    assert v2.description == "needs FDA"
    assert v2.recommendation == ""


def test_adapter_from_check_na_is_incomplete() -> None:
    entry = {
        "domain": "tcc",
        "name": "tcc_consistency",
        "status": "n/a",
        "title": "TCC reads incomplete",
        "detail": "Full Disk Access not granted",
        "fixable": False,
        "fix_cmd": "",
    }
    v2 = finding_v2_from_check(entry)
    assert v2.incomplete is True
    assert v2.incomplete_reason == "Full Disk Access not granted"
    # Legacy entries carry no control_id until canonicalize_check runs.
    assert v2.control_id is None
    assert v2.check_id == "tcc_consistency"

    ok = finding_v2_from_check(
        {
            "domain": "firewall",
            "name": "firewall_enabled",
            "status": "high",
            "title": "Firewall disabled",
            "detail": "off",
            "fixable": True,
            "fix_cmd": "socketfilterfw --setglobalstate on",
        }
    )
    assert ok.incomplete is False
    assert ok.incomplete_reason == ""
    assert ok.fix_cmd == "socketfilterfw --setglobalstate on"


def test_canonicalize_check_preserves_flat_keys() -> None:
    entry = {
        "domain": "permissions",
        "name": "sudoers_writeable",
        "status": "medium",
        "title": "sudoers is writable",
        "detail": "mode 0777",
        "fixable": True,
        "fix_cmd": "chmod 0440 /etc/sudoers",
    }
    c = canonicalize_check(
        entry,
        collector="scanner.permissions",
        args=["msp", "scan"],
        timestamp="2026-11-17T00:00:00",
    )
    # Legacy flat keys consumed by fix_permission_issues must survive.
    assert c["domain"] == "permissions"
    assert c["fixable"] is True
    assert c["fix_cmd"].startswith("chmod ")
    assert c["status"] == "medium"
    # v2 additions.
    assert c["control_id"] == "sudoers_writeable"
    assert c["evidence_refs"] == []
    assert c["provenance"]["collector"] == "scanner.permissions"
    assert c["provenance"]["args"] == ["msp", "scan"]
    assert c["provenance"]["timestamp"] == "2026-11-17T00:00:00"
    assert c["incomplete"] is False
    assert c["incomplete_reason"] == ""
    assert c["verified"] is None
    assert c["schema_version"] == BUNDLE_SCHEMA_VERSION


def test_canonicalize_check_respects_explicit_control_id() -> None:
    entry = {
        "domain": "firewall",
        "name": "fw",
        "status": "high",
        "title": "t",
        "detail": "d",
        "fixable": False,
        "fix_cmd": "",
        "control_id": "FW-001",
    }
    c = canonicalize_check(entry, collector="tune", args=[], timestamp="")
    assert c["control_id"] == "FW-001"


def test_canonicalize_checks_bulk() -> None:
    out = canonicalize_checks(
        [{"domain": "d", "name": "n", "status": "ok", "title": "t", "detail": "x", "fixable": False, "fix_cmd": ""}],
        collector="tune",
        args=["a"],
        timestamp="t",
    )
    assert len(out) == 1
    assert out[0]["provenance"]["collector"] == "tune"


def test_remediation_result_adapter_verified_is_none() -> None:
    fake = types.SimpleNamespace(
        action_id="fw_001_enable_firewall",
        finding_id="FW-001",
        status="applied",
        dry_run=False,
        command_result=types.SimpleNamespace(success=True),
        message="ok",
        rollback={"status": "not_needed"},
    )
    v2 = finding_v2_from_remediation_result(fake)
    assert v2.verified is None  # no post-apply re-verification exists yet
    assert v2.data["remediation_status"] == "applied"
    assert v2.data["dry_run"] is False


def test_legacy_bundle_still_readable_after_bump(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MSP_HOME", str(tmp_path))
    from src.scanner import read_latest_scan, scan_bundle_path

    bundle = {
        "schema": "1.0",
        "timestamp": "2026-01-01T00:00:00",
        "mode": "full",
        "checks": [
            {"domain": "firewall", "name": "x", "status": "high", "title": "t", "detail": "d", "fixable": False, "fix_cmd": ""}
        ],
    }
    path = scan_bundle_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle) + "\n", encoding="utf-8")

    payload = read_latest_scan()
    assert payload is not None
    assert payload["schema"] == "1.0"
    assert payload["checks"][0]["name"] == "x"
    # Legacy entries convert to v2 with incomplete semantics for n/a.
    v2 = finding_v2_from_check(payload["checks"][0])
    assert v2.title == "t"


def test_current_bundle_schema_constant() -> None:
    from src.scanner import SCAN_BUNDLE_SCHEMA

    assert SCAN_BUNDLE_SCHEMA == BUNDLE_SCHEMA_VERSION == "2.0"
