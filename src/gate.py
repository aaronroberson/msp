#!/usr/bin/env python3
"""Engine-enforced approval gate for mutating operations.

Every mutating path (remediation apply, workflow executor, doctor fix) must
pass through :class:`Gate` before executing. The gate classifies actions into
risk classes and refuses anything it cannot authorize:

- ``read`` and ``safe_write`` are never blocked (auto-allowed and logged).
- ``confirm`` requires interactive consent (a caller-obtained y/N answer) or a
  valid approval token.
- ``dangerous`` always requires a valid approval token; interactive consent
  alone is never sufficient.

Approval tokens are short-lived and bound to ``(control_id, target)``. The
append-only ledger under ``~/.msp/state/approval_ledger.jsonl`` records
approved/consumed/denied events and stores only the SHA-256 hash of each
token, never the token itself.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src import state

RISK_CLASSES = ("read", "safe_write", "confirm", "dangerous")

RISK_EXIT_CODES = {"allowed": 0, "requires_interactive": 2, "requires_token": 2, "refused": 2}

DEFAULT_TOKEN_TTL_SECONDS = 300


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GateDecision:
    """Outcome of a gate check; ``allowed`` is the only authorization signal."""

    allowed: bool
    status: str
    message: str = ""

    @property
    def exit_code(self) -> int:
        return RISK_EXIT_CODES[self.status]


class Gate:
    """Approval gate with a JSONL ledger and target-bound short-lived tokens."""

    def __init__(self, ledger_path: Optional[Path] = None) -> None:
        self.ledger_path = Path(ledger_path) if ledger_path else state.approval_ledger_file()
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    # -- ledger helpers ----------------------------------------------------

    def _append_event(self, event: Dict[str, Any]) -> None:
        event["at"] = _utcnow_iso()
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _read_events(self) -> List[Dict[str, Any]]:
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

    # -- token lifecycle ---------------------------------------------------

    def approve(
        self,
        control_id: str,
        target: str,
        *,
        ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
        run_id: str = "",
        risk: str = "dangerous",
    ) -> Dict[str, Any]:
        """Mint a target-bound approval token and record it (hashed) in the ledger."""
        if risk not in RISK_CLASSES:
            raise ValueError(f"Unknown risk class: {risk}")
        token = secrets.token_urlsafe(32)
        token_id = uuid.uuid4().hex
        created = time.time()
        expires = created + max(0, ttl_seconds)
        payload = {
            "token": token,
            "token_id": token_id,
            "control_id": control_id,
            "target": target,
            "target_hash": _sha256(target),
            "run_id": run_id,
            "risk": risk,
            "expires_at": expires,
            "expires_at_iso": datetime.fromtimestamp(expires, tz=timezone.utc).isoformat(),
        }
        self._append_event(
            {
                "event": "approved",
                "token_id": token_id,
                "token_hash": _sha256(token),
                "control_id": control_id,
                "target_hash": _sha256(target),
                "run_id": run_id,
                "risk": risk,
                "created_at_epoch": created,
                "expires_at": expires,
                "expires_at_iso": payload["expires_at_iso"],
            }
        )
        return payload

    def validate(
        self,
        token: str,
        control_id: str,
        target: str,
        *,
        run_id: str = "",
    ) -> GateDecision:
        """Check a token against (control_id, target); consume it on success."""
        token_hash = _sha256(token)
        target_hash = _sha256(target)
        approved: Optional[Dict[str, Any]] = None
        for event in self._read_events():
            if event.get("event") != "approved" or event.get("token_hash") != token_hash:
                continue
            approved = event
            break
        if approved is None:
            decision = GateDecision(False, "refused", "Unknown approval token.")
            self._append_event(
                {"event": "denied", "reason": "unknown_token", "control_id": control_id, "target_hash": target_hash}
            )
            return decision
        if _is_consumed(self._read_events(), approved.get("token_id", "")):
            self._append_event(
                {"event": "denied", "reason": "already_consumed", "token_id": approved.get("token_id", "")}
            )
            return GateDecision(False, "refused", "Approval token already used.")
        if time.time() > float(approved.get("expires_at", 0)):
            self._append_event(
                {"event": "denied", "reason": "expired", "token_id": approved.get("token_id", "")}
            )
            return GateDecision(False, "refused", "Approval token expired.")
        if approved.get("target_hash") != target_hash:
            self._append_event(
                {"event": "denied", "reason": "target_mismatch", "token_id": approved.get("token_id", "")}
            )
            return GateDecision(False, "refused", "Approval token does not match this target.")
        if approved.get("control_id") != control_id:
            self._append_event(
                {"event": "denied", "reason": "control_mismatch", "token_id": approved.get("token_id", "")}
            )
            return GateDecision(False, "refused", "Approval token does not match this control.")
        approved_run = str(approved.get("run_id") or "")
        if approved_run and run_id and approved_run != run_id:
            self._append_event(
                {"event": "denied", "reason": "run_mismatch", "token_id": approved.get("token_id", "")}
            )
            return GateDecision(False, "refused", "Approval token does not match this run.")
        self._append_event(
            {"event": "consumed", "token_id": approved.get("token_id", ""), "control_id": control_id}
        )
        return GateDecision(True, "allowed", "Approval token accepted.")

    # -- risk-class decision ------------------------------------------------

    def decide(
        self,
        *,
        risk_class: str,
        control_id: str = "",
        target: str = "",
        token: Optional[str] = None,
        interactive: bool = False,
    ) -> GateDecision:
        """Authorize a risk class for (control_id, target).

        ``read``/``safe_write`` are auto-allowed (and logged). ``confirm`` may
        be satisfied by a valid token or by ``interactive=True`` (the caller
        must have obtained an actual y/N answer). ``dangerous`` requires a
        valid token regardless of interactivity.
        """
        if risk_class not in RISK_CLASSES:
            raise ValueError(f"Unknown risk class: {risk_class}")
        if risk_class in {"read", "safe_write"}:
            self._append_event(
                {"event": "auto_allowed", "risk_class": risk_class, "control_id": control_id}
            )
            return GateDecision(True, "allowed", f"{risk_class} actions are auto-allowed.")
        if token:
            decision = self.validate(token, control_id, target)
            if decision.allowed:
                return decision
            return decision
        if risk_class == "confirm" and interactive:
            self._append_event({"event": "interactive_allowed", "control_id": control_id})
            return GateDecision(True, "allowed", "Interactive consent provided.")
        message = (
            "Requires interactive confirmation or an approval token."
            if risk_class == "confirm"
            else "Requires an approval token."
        )
        self._append_event(
            {"event": "denied", "reason": f"{risk_class}_unauthorized", "control_id": control_id}
        )
        return GateDecision(False, "requires_interactive" if risk_class == "confirm" else "refused", message)


def _is_consumed(events: List[Dict[str, Any]], token_id: str) -> bool:
    return any(event.get("event") == "consumed" and event.get("token_id") == token_id for event in events)
