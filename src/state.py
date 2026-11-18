"""Central registry of persistent state locations used by msp.

Every path the tool reads or writes under ``~/.msp`` is declared here
exactly once. Modules must resolve state through this module instead of
constructing literal ``~/.msp`` paths, so the layout stays documented,
versioned, and migratable from one place.

Layout (version 1):

    ~/.msp/
        scans/latest.json              canonical scan bundle (scanner)
        reports/                       scan reports (scanner, privacy_settings)
        backups/                       tune backups (tune)
        backups/shell_audit/           shell audit backups (shell_audit_cli)
        baselines/                     fswatch + chain baselines
        snapshots/                     snapshot manager archives (snapshot)
        settings.json                  snapshot watch settings (snapshot)
        snapshot_watch.pid             snapshot watcher pid file
        snapshot_watch_config.json     snapshot watcher config
        chains.json                    chain definitions (chain)
        config.toml                    CLI configuration (errors)
        ai_config.json                 AI provider configuration (ai)
        state/                         run state, ledgers (future phases)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

STATE_VERSION = 1

_LAYOUT_MARKER = "layout.json"


def msp_home() -> Path:
    """Root state directory (``~/.msp``).

    ``MSP_HOME`` overrides the root so tests and tools can operate on an
    isolated layout without touching the user's real state.
    """
    override = os.environ.get("MSP_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".msp"


def scans_dir() -> Path:
    return msp_home() / "scans"


def latest_scan_bundle() -> Path:
    return scans_dir() / "latest.json"


def reports_dir() -> Path:
    return msp_home() / "reports"


def backups_dir() -> Path:
    return msp_home() / "backups"


def shell_audit_backup_dir() -> Path:
    return backups_dir() / "shell_audit"


def baselines_dir() -> Path:
    return msp_home() / "baselines"


def snapshots_dir() -> Path:
    return msp_home() / "snapshots"


def settings_file() -> Path:
    return msp_home() / "settings.json"


def snapshot_watch_pid_file() -> Path:
    return msp_home() / "snapshot_watch.pid"


def snapshot_watch_config_file() -> Path:
    return msp_home() / "snapshot_watch_config.json"


def chains_file() -> Path:
    return msp_home() / "chains.json"


def config_file() -> Path:
    return msp_home() / "config.toml"


def ai_config_file() -> Path:
    return msp_home() / "ai_config.json"


def state_dir() -> Path:
    return msp_home() / "state"


def approval_ledger_file() -> Path:
    """Append-only JSONL ledger for approval-gate tokens and decisions."""
    return state_dir() / "approval_ledger.jsonl"


ALL_DIRS = (
    scans_dir,
    reports_dir,
    backups_dir,
    shell_audit_backup_dir,
    baselines_dir,
    snapshots_dir,
    state_dir,
)


def ensure_dirs() -> None:
    """Create the standard directory skeleton (idempotent)."""
    for get_dir in ALL_DIRS:
        get_dir().mkdir(parents=True, exist_ok=True)


def write_layout_marker() -> Path:
    """Record the layout version in ``~/.msp/layout.json`` (idempotent)."""
    path = msp_home() / _LAYOUT_MARKER
    msp_home().mkdir(parents=True, exist_ok=True)
    payload = {"state_version": STATE_VERSION}
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    if existing.get("state_version") != STATE_VERSION:
        previous = existing.get("state_version")
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        _migrate(previous, STATE_VERSION)
    return path


def _migrate(from_version, to_version) -> None:
    """Hook for future layout migrations (currently a no-op)."""
    return None
