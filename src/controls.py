"""Control registry — the single index of everything the tool can see, fix,
or configure.

This is the T-03 seed: it is authoritative for *membership* (which control
ids exist), for the remediation inventory (which rule ids have conservative
remediations and at what safety), for the preset setting -> control mapping,
and for the scanner-check inventory. Per-control display metadata (titles,
descriptions, fact predicates) stays with the collector modules for now;
consolidating it lives here is the Phase 1 presets-as-workflow work.

Import direction: collectors (rules, remediate, tune, presets) resolve
through this module; this module imports nothing from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Control:
    """One addressable control id across the tool."""

    id: str
    title: str
    kind: str  # "rule" | "check" | "preset-setting"
    category: str = ""
    severity: Optional[str] = None
    remediation_id: Optional[str] = None
    remediation_safety: Optional[str] = None
    requires_sudo: bool = False
    source: str = ""
    references: Tuple[str, ...] = field(default_factory=tuple)


# ── rule-backed controls (16 rules in rules.default_rules()) ──────────
# severity/category/title/remediation_id/references mirror rules.default_rules();
# remediation_safety/requires_sudo mirror the mapped action in
# remediate.RemediationPlanner._actions_for_finding (None = guidance-only/skipped).
_RULE_CONTROLS = (
    Control("FW-001", "Application firewall is disabled", "rule", "firewall",
            "high", "firewall.enable", "medium", True, "rules",
            ("cis:CIS Apple macOS Firewall", "nist:CM-7, SC-7", "stig:APPL-14-002021")),
    Control("FW-002", "Stealth mode is disabled", "rule", "firewall",
            "medium", "firewall.stealth.enable", "low", True, "rules",
            ("cis:CIS Apple macOS Firewall", "nist:SC-7")),
    Control("FV-001", "FileVault is disabled", "rule", "filevault",
            "critical", "filevault.enable.guidance", None, False, "rules",
            ("cis:CIS Apple macOS FileVault", "nist:SC-28", "stig:APPL-14-005020")),
    Control("GK-001", "Gatekeeper is disabled", "rule", "gatekeeper",
            "high", "gatekeeper.enable", "medium", True, "rules",
            ("cis:CIS Apple macOS Gatekeeper", "nist:SI-7", "stig:APPL-14-002060")),
    Control("SH-001", "File sharing is enabled", "rule", "sharing",
            "medium", "sharing.disable_all", "medium", False, "rules",
            ("cis:CIS Apple macOS Sharing", "nist:CM-7, SC-7")),
    Control("SH-002", "Guest sharing access is enabled", "rule", "sharing",
            "high", "sharing.disable_all", "medium", False, "rules",
            ("cis:CIS Apple macOS Sharing", "nist:CM-7, SC-7")),
    Control("TCC-001", "High-risk privacy grants are present", "rule", "tcc",
            "high", "tcc.review_high_risk", None, False, "rules",
            ("cis:CIS Apple macOS Privacy Preferences Policy Control", "nist:AC-6")),
    Control("TCC-002", "Screen Recording permissions are granted", "rule", "tcc",
            "medium", "tcc.reset_screen_capture", "high", False, "rules",
            ("cis:CIS Apple macOS Privacy Preferences Policy Control", "nist:AC-6")),
    Control("ST-001", "Unsigned startup items are present", "rule", "startup",
            "high", "startup.review_unsigned", "high", False, "rules",
            ("cis:CIS Apple macOS System Integrity", "nist:CM-6, SI-7")),
    Control("ST-002", "Suspicious startup items are present", "rule", "startup",
            "critical", "startup.review_suspicious", "high", False, "rules",
            ("nist:SI-4, SI-7",)),
    Control("NW-001", "Public listening services are present", "rule", "network",
            "medium", "network.review_exposed_services", None, False, "rules",
            ("cis:CIS Apple macOS Network Services", "nist:CM-7, SC-7")),
    Control("NW-002", "Remote login service is active", "rule", "network",
            "medium", "remote_login.disable", "medium", True, "rules",
            ("cis:CIS Apple macOS Remote Login", "nist:AC-17", "stig:APPL-14-004040")),
    Control("SEC-001", "Password after sleep is disabled", "rule", "security_settings",
            "high", "security.password_after_sleep.enable", "low", False, "rules",
            ("cis:CIS Apple macOS Screen Saver", "nist:AC-11", "stig:APPL-14-000060")),
    Control("SEC-002", "Password-after-sleep delay is too long", "rule", "security_settings",
            "medium", "security.password_delay.set_zero", "low", False, "rules",
            ("cis:CIS Apple macOS Screen Saver", "nist:AC-11")),
    Control("SEC-003", "Screen lock timeout is too long", "rule", "security_settings",
            "medium", "security.screen_lock.set_profile", "low", False, "rules",
            ("cis:CIS Apple macOS Screen Saver", "nist:AC-11")),
    Control("DEV-001", "Developer ports are exposed", "rule", "network",
            "low", "network.review_developer_ports", None, False, "rules",
            ("nist:CM-7, SC-7",)),
)

# ── scanner-check controls (tune.Tuner._HEALTH_CHECKS + permissions) ──
_CHECK_CONTROLS = (
    Control("check.zsh_startup", "Zsh startup time", "check", "shell", source="tune"),
    Control("check.zsh_nvm", "NVM loading", "check", "shell", source="tune"),
    Control("check.zsh_history", "Zsh history", "check", "shell", source="tune"),
    Control("check.zsh_path_dupes", "Shell config", "check", "shell", source="tune"),
    Control("check.zsh_async", "Zsh autosuggestions", "check", "shell", source="tune"),
    Control("check.zsh_brew", "Homebrew shellenv", "check", "shell", source="tune"),
    Control("check.disk", "Disk space", "check", "system", source="tune"),
    Control("check.memory", "Memory", "check", "system", source="tune"),
    Control("check.brew", "Homebrew cleanup", "check", "system", source="tune"),
    Control("check.docker", "Docker disk usage", "check", "system", source="tune"),
    Control("check.cache", "User caches", "check", "system", source="tune"),
    Control("check.launch_daemons", "Launch agents", "check", "system", source="tune"),
    Control("check.file_permissions", "File permissions", "check", "permissions", source="scanner.permissions"),
)

# ── preset setting labels -> rule/control ids (privacy_settings domain) ──
_PRESET_SETTING_CONTROLS = (
    Control("setting.Application Firewall", "Application Firewall", "preset-setting", "firewall",
            remediation_id="firewall.enable", source="presets"),
    Control("setting.Firewall Stealth Mode", "Firewall Stealth Mode", "preset-setting", "firewall",
            remediation_id="firewall.stealth.enable", source="presets"),
    Control("setting.Gatekeeper", "Gatekeeper", "preset-setting", "gatekeeper",
            remediation_id="gatekeeper.enable", source="presets"),
    Control("setting.Captive Portal Probe", "Captive Portal Probe", "preset-setting", "network",
            source="presets"),
    Control("setting.Signed App Auto-Allow", "Signed App Auto-Allow", "preset-setting", "firewall",
            source="presets"),
    Control("setting.Signed App Downloaded Auto-Allow", "Signed App Downloaded Auto-Allow",
            "preset-setting", "firewall", source="presets"),
    Control("setting.FileVault Encryption", "FileVault Encryption", "preset-setting", "filevault",
            remediation_id="filevault.enable.guidance", source="presets"),
)

CONTROLS: Dict[str, Control] = {
    c.id: c for c in (*_RULE_CONTROLS, *_CHECK_CONTROLS, *_PRESET_SETTING_CONTROLS)
}

# Preset setting label -> the control id governing it.
SETTING_TO_CONTROL: Dict[str, str] = {
    c.title: c.id for c in _PRESET_SETTING_CONTROLS
}


def get_control(control_id: str) -> Optional[Control]:
    return CONTROLS.get(control_id)


def require_control(control_id: str) -> Control:
    control = CONTROLS.get(control_id)
    if control is None:
        raise KeyError(
            f"Unknown control id: {control_id!r}. Register it in src/controls.py "
            "or fix the caller."
        )
    return control


def control_ids() -> Tuple[str, ...]:
    return tuple(CONTROLS)


def controls_by_kind(kind: str) -> Tuple[Control, ...]:
    return tuple(c for c in CONTROLS.values() if c.kind == kind)


def rule_control_ids() -> Tuple[str, ...]:
    return tuple(c.id for c in controls_by_kind("rule"))


def remediation_inventory() -> Dict[str, Dict[str, Optional[str]]]:
    """rule_id -> remediation summary for every rule control."""
    return {
        c.id: {
            "remediation_id": c.remediation_id,
            "safety": c.remediation_safety,
            "requires_sudo": "yes" if c.requires_sudo else "no",
        }
        for c in controls_by_kind("rule")
    }
