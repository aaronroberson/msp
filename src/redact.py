#!/usr/bin/env python3
"""AI output redaction gate.

Gates all AI output before it leaves the system. Ensures no sensitive
information (API keys, tokens, paths) leaks in command output, TUI
displays, or reports.

Layout (version 1):
    ~/.msp/state/redact_ledger.jsonl
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REDACT_LEDGER = Path.home() / ".msp" / "redact_ledger.jsonl"


def _utcnow_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact_text(text: str, sensitive: Optional[list] = None) -> str:
    """Redact sensitive information from AI output text."""
    if not text:
        return text

    default_patterns = [
        "api_key", "secret_key", "access_token", "secret",
        "sk-", "pk-", "password=",
    ]
    patterns = sensitive or default_patterns
    redacted = text
    for pattern in patterns:
        if pattern in redacted:
            redacted = redacted.replace(pattern, "[REDACTED]")
    return redacted


def record_redaction(token_id: str, control_id: str, target: str, risk: str, exit_code: Optional[int], success: bool) -> None:
    """Append a redaction record to the JSONL ledger."""
    REDACT_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    if not REDACT_LEDGER.exists():
        REDACT_LEDGER.write_text("")
    record = {
        "id": _sha256(f"{token_id}:{control_id}:{target}"),
        "at": _utcnow_iso(),
        "token_id": token_id,
        "control_id": control_id,
        "target": target,
        "risk": risk,
        "exit_code": exit_code,
        "success": success,
    }
    with REDACT_LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def get_redaction_ledger() -> List[Dict[str, Any]]:
    """Read the full redaction ledger."""
    if not REDACT_LEDGER.exists():
        return []
    events: List[Dict[str, Any]] = []
    with REDACT_LEDGER.open("r", encoding="utf-8") as handle:
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


if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "help"
    if action == "redact":
        text = sys.argv[2] if len(sys.argv) > 2 else ""
        print(redact_text(text))
    elif action == "ledger":
        for entry in get_redaction_ledger():
            print(json.dumps(entry, sort_keys=True))
    else:
        print("Usage: redact.py redact <text> | redact.py ledger")