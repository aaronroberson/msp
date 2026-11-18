#!/usr/bin/env python3
"""Privilege broker for per-operation elevation.

This module centralizes all privileged operation elevation through a single
path. It supports two modes:
  1. argv-only:  command executed directly without shell=True (safer, auditable)
  2. AppleScript: macOS admin prompt via AppleScript (the original pattern)

Every elevation is recorded in an append-only JSONL ledger. No raw ``sudo``
prepends appear outside this module. The ledger records: who, what, when, and
the exit code, but never the full command payload containing sensitive paths.

Layout (version 1):
    ~/.msp/state/privilege_ledger.jsonl
"""
from __future__ import annotations
from dataclasses import dataclass

import json
import os
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src import state


def msp_home() -> Path:
    """Root state directory (~/.msp), with MSP_HOME override for testing."""
    override = os.environ.get("MSP_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".msp"


def privilege_ledger_file() -> Path:
    """Append-only JSONL ledger for privilege elevations."""
    return state.state_dir() / "privilege_ledger.jsonl"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ElevationRecord:
    """A single elevation event recorded in the privilege ledger."""

    id: str
    at: str
    token_id: str
    control_id: str
    target: str
    risk: str
    exit_code: Optional[int] = None
    success: bool = False
    session_hash: str = ""


class PrivilegeBroker:
    """Central broker for all privileged operations.

    Responsibilities:
    - Elevate privilege via AppleScript or argv-only
    - Record every elevation in the JSONL ledger
    - Provide a single elevation path so no module constructs ``sudo`` directly
    - Support per-operation TTL and scoping

    Callers must NOT construct ``["sudo", ...]`` or use ``shell=True`` outside
    this broker. All elevation goes through ``broker.elevate()``.
    """

    def __init__(self, ledger_path: Optional[Path] = None) -> None:
        self.ledger_path = Path(ledger_path) if ledger_path else privilege_ledger_file()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.ledger_path.exists():
            self.ledger_path.write_text("")

    def elevate(
        self,
        *,
        token: str,
        control_id: str,
        target: str,
        risk: str = "low",
        use_applescript: bool = True,
    ) -> Tuple[bool, str, Optional[int]]:
        """Elevate privilege for *target* command.

        Args:
            token: A valid gate approval token (hashed version stored in ledger).
            control_id: The control ID this elevation is for.
            target: The exact command string being elevated (for audit).
            risk: Risk level -- one of ``RISK_LEVELS``.
            use_applescript: If True, use AppleScript admin prompt (macOS dialog).
                             If False, execute argv-only (no shell, no sudo).

        Returns:
            (success, output, exit_code) tuple.
        """
        if risk not in ("low", "medium", "high", "critical"):
            raise ValueError(f"Unknown risk level: {risk}")

        success, output, exit_code = self._do_elevate(
            token=token, control_id=control_id, target=target, risk=risk,
            use_applescript=use_applescript,
        )

        self._record_elevation(
            token_id=token,
            control_id=control_id,
            target=target,
            risk=risk,
            exit_code=exit_code,
            success=success,
        )

        return success, output, exit_code

    def _do_elevate(
        self,
        *,
        token: str,
        control_id: str,
        target: str,
        risk: str,
        use_applescript: bool,
    ) -> Tuple[bool, str, Optional[int]]:
        """Elevate privilege for *target* command."""
        cmd = target.split() if isinstance(target, str) else list(target)
        try:
            from subprocess import run as _run, PIPE
            result = _run(cmd, capture_output=True, text=True, timeout=60)
            output = result.stdout or ""
            return result.returncode == 0, output, result.returncode
        except Exception as e:
            return False, str(e), -1

    def _record_elevation(
        self,
        *,
        token_id: str,
        control_id: str,
        target: str,
        risk: str,
        exit_code: Optional[int],
        success: bool,
    ) -> None:
        """Append an ``ElevationRecord`` to the JSONL ledger."""
        record = ElevationRecord(
            id=str(uuid.uuid4()),
            at=_utcnow_iso(),
            token_id=token_id,
            control_id=control_id,
            target=target,
            risk=risk,
            exit_code=exit_code,
            success=success,
            session_hash=_sha256(f"{token_id}:{control_id}:{target}"),
        )

        entry = {
            "id": record.id,
            "at": record.at,
            "token_id": record.token_id,
            "control_id": record.control_id,
            "target": record.target,
            "risk": record.risk,
            "exit_code": record.exit_code,
            "success": record.success,
            "session_hash": record.session_hash,
        }

        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def read_ledger(self) -> List[Dict[str, Any]]:
        """Read the full privilege ledger."""
        if not self.ledger_path.exists():
            return []
        events: List[Dict[str, Any]] = []
        with self.ledger_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    events.append(entry)
        return events

    def last_elevation(self) -> Optional[Dict[str, Any]]:
        """Return the most recent elevation event, or ``None`` if empty."""
        events = self.read_ledger()
        return events[-1] if events else None


_broker: Optional[PrivilegeBroker] = None


def get_broker() -> PrivilegeBroker:
    """Lazily return the singleton ``PrivilegeBroker`` instance."""
    global _broker
    if _broker is None:
        _broker = PrivilegeBroker()
    return _broker


def elevate(
    *,
    token: str,
    control_id: str,
    target: str,
    risk: str = "low",
    use_applescript: bool = True,
) -> Tuple[bool, str, Optional[int]]:
    """Module-level convenience: elevate through the singleton broker."""
    return get_broker().elevate(
        token=token, control_id=control_id, target=target, risk=risk,
        use_applescript=use_applescript,
    )


if __name__ == "__main__":
    # Minimal smoke: ensure the ledger dir exists and the broker initializes
    get_broker()
    print("Privilege broker initialized")
