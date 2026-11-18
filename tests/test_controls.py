"""Registry completeness tests for src/controls.py (T-03).

Every rule, every remediate-mapped rule id, every tune check and every
preset setting label must resolve to a registered control.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import controls
from src.controls import (
    CONTROLS,
    SETTING_TO_CONTROL,
    controls_by_kind,
    get_control,
    remediation_inventory,
    require_control,
    rule_control_ids,
)

# Rule ids remediate._actions_for_finding maps to actions (the rest of the
# registry is intentionally unmapped — planner skips them as guidance-less).
REMEDIATE_MAPPED_RULE_IDS = {
    "FW-001",
    "FW-002",
    "GK-001",
    "SEC-001",
    "SEC-002",
    "SEC-003",
    "NW-002",
    "SH-001",
    "SH-002",
    "TCC-001",
    "TCC-002",
    "ST-001",
    "ST-002",
}


def test_every_rule_resolves_to_registered_control() -> None:
    from src.rules import default_rules

    rule_ids = {rule.id for rule in default_rules()}
    registry_ids = set(rule_control_ids())
    assert rule_ids == registry_ids, (
        f"rules.py and controls.py disagree: rules-only={rule_ids - registry_ids}, "
        f"registry-only={registry_ids - rule_ids}"
    )


def test_every_remediate_mapped_rule_maps_to_a_control() -> None:
    registry_ids = set(rule_control_ids())
    missing = REMEDIATE_MAPPED_RULE_IDS - registry_ids
    assert not missing, f"remediate maps unknown rule ids: {sorted(missing)}"
    inventory = remediation_inventory()
    for rule_id in REMEDIATE_MAPPED_RULE_IDS:
        assert rule_id in inventory, f"{rule_id} has no remediation inventory entry"


def test_every_tune_check_resolves_to_registered_control() -> None:
    from src.tune import Tuner

    for domain, name, method, _detail in Tuner._HEALTH_CHECKS:
        check_id = method.replace("_check_", "")
        control = get_control(f"check.{check_id}")
        assert control is not None, f"tune check {check_id} is not registered"
        assert control.source == "tune"
        assert control.title == name


def test_every_preset_setting_label_is_registered() -> None:
    from src.presets import PRESETS

    labels = set()
    for preset in PRESETS.values():
        labels.update(preset["settings"].keys())
    unknown = labels - set(SETTING_TO_CONTROL)
    assert not unknown, f"preset labels missing from controls registry: {sorted(unknown)}"


def test_get_control_and_require_control() -> None:
    assert get_control("FW-001") is not None
    assert get_control("NOT-A-CONTROL") is None
    with pytest.raises(KeyError):
        require_control("NOT-A-CONTROL")


def test_registry_kinds_and_inventory() -> None:
    assert len(controls_by_kind("rule")) == 16
    checks = controls_by_kind("check")
    assert len(checks) == 20
    # Phase 4 utility-expansion checks (G-2..G-7, G-23; commit b811756)
    assert {"AI-LOCAL", "FSEC-HASH", "NW-EXFIL", "NW-P2P", "SYSTEM-FORK", "TCC-INPUT", "TSEC-KEY"} <= {c.id for c in checks}
    assert len(controls_by_kind("preset-setting")) == 7
    assert len(CONTROLS) == 43
    assert len(remediation_inventory()) == 16
