"""Tests for preset wiring: single source of truth, nist availability, FileVault honesty."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.presets import PRESETS as SOURCE_PRESETS  # noqa: E402
from src.privacy_settings import PresetManager, PrivacySettingsManager, SettingState  # noqa: E402


@pytest.fixture
def manager() -> PrivacySettingsManager:
    return PrivacySettingsManager()


@pytest.fixture
def preset_manager(manager: PrivacySettingsManager) -> PresetManager:
    return PresetManager(manager)


def test_presets_single_source_of_truth(preset_manager: PresetManager) -> None:
    assert preset_manager.PRESETS is SOURCE_PRESETS


def test_five_presets_including_nist(preset_manager: PresetManager) -> None:
    assert set(preset_manager.PRESETS) == {"basic", "paranoid", "drduh", "term7", "nist"}
    assert preset_manager.PRESETS["nist"]["settings"].get("FileVault Encryption") is True


def test_preset_entries_have_display_fields(preset_manager: PresetManager) -> None:
    for preset_id, preset in preset_manager.PRESETS.items():
        assert isinstance(preset["name"], str) and preset["name"]
        assert isinstance(preset["description"], str) and preset["description"]
        assert isinstance(preset["settings"], dict)
        for value in preset["settings"].values():
            assert isinstance(value, bool), f"{preset_id} settings must be booleans"


def test_builtin_presets_cannot_be_deleted(preset_manager: PresetManager) -> None:
    for preset_id in ["basic", "paranoid", "drduh", "term7", "nist"]:
        assert preset_manager.delete_preset(preset_id) is False
        assert preset_id in preset_manager.PRESETS


def test_nist_preset_applies_with_filevault_skip(
    preset_manager: PresetManager, capsys: pytest.CaptureFixture
) -> None:
    """FileVault enable must be an honest skip with guidance, not a doomed fdesetup call."""
    called = {"enable": 0, "filevault_attempts": 0}

    def fake_enable(setting):  # type: ignore[no-untyped-def]
        called["enable"] += 1
        if setting.name == "FileVault Encryption":
            called["filevault_attempts"] += 1
        return False

    preset_manager.manager.enable_setting = fake_enable  # type: ignore[method-assign]
    preset_manager.manager.get_current_state = lambda setting: SettingState.DISABLED  # type: ignore[method-assign]

    assert preset_manager.apply_preset("nist") is True
    out = capsys.readouterr().out
    assert "[SKIP] FileVault" in out
    assert "System Settings" in out
    assert "[FAIL] Could not enable FileVault Encryption" not in out
    # FileVault must never reach enable_setting — the skip happens before any attempt
    assert called["filevault_attempts"] == 0


def test_nist_preset_dry_run_never_enables(
    preset_manager: PresetManager, capsys: pytest.CaptureFixture
) -> None:
    preset_manager.manager.enable_setting = lambda setting: False  # type: ignore[method-assign]
    preset_manager.manager.disable_setting = lambda setting: False  # type: ignore[method-assign]
    preset_manager.manager.get_current_state = lambda setting: SettingState.DISABLED  # type: ignore[method-assign]

    assert preset_manager.apply_preset("nist", dry_run=True) is True
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out
    assert "[SKIP] FileVault" not in out


def test_unknown_preset_rejected(preset_manager: PresetManager, capsys: pytest.CaptureFixture) -> None:
    assert preset_manager.apply_preset("does-not-exist") is False
    assert "Unknown preset" in capsys.readouterr().out


def test_no_dead_presets_dir_attribute(manager: PrivacySettingsManager) -> None:
    assert not hasattr(manager, "presets_dir")
