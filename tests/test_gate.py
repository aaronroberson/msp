"""Unit tests for the engine-enforced approval gate (src/gate.py)."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from src.gate import Gate, _sha256


class GateTokenTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self._tmp.name) / "approval_ledger.jsonl"
        self.gate = Gate(ledger_path=self.ledger)

    def tearDown(self):
        self._tmp.cleanup()

    def test_approve_validate_roundtrip_allowed_and_consumed(self):
        payload = self.gate.approve("FW-001", "socketfilterfw --setglobalstate on")
        token = payload["token"]
        self.assertTrue(token)
        decision = self.gate.validate(token, "FW-001", "socketfilterfw --setglobalstate on")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, "allowed")
        events = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        kinds = [event["event"] for event in events]
        self.assertIn("approved", kinds)
        self.assertIn("consumed", kinds)
        # The raw token must never be stored in the ledger.
        self.assertNotIn(token, self.ledger.read_text())
        token_hashes = [event.get("token_hash") for event in events if event["event"] == "approved"]
        self.assertEqual(token_hashes, [_sha256(token)])

    def test_expired_token_refused(self):
        payload = self.gate.approve("FW-001", "cmd", ttl_seconds=-1)
        decision = self.gate.validate(payload["token"], "FW-001", "cmd")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "refused")
        self.assertIn("expired", decision.message)

    def test_target_mismatch_refused(self):
        payload = self.gate.approve("FW-001", "cmd-a")
        decision = self.gate.validate(payload["token"], "FW-001", "cmd-b")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "refused")
        self.assertIn("target", decision.message)

    def test_control_mismatch_refused(self):
        payload = self.gate.approve("FW-001", "cmd-a")
        decision = self.gate.validate(payload["token"], "FW-002", "cmd-a")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "refused")
        self.assertIn("control", decision.message)

    def test_run_mismatch_refused(self):
        payload = self.gate.approve("FW-001", "cmd-a", run_id="run-1")
        decision = self.gate.validate(payload["token"], "FW-001", "cmd-a", run_id="run-2")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "refused")

    def test_token_single_use(self):
        payload = self.gate.approve("FW-001", "cmd-a")
        first = self.gate.validate(payload["token"], "FW-001", "cmd-a")
        self.assertTrue(first.allowed)
        second = self.gate.validate(payload["token"], "FW-001", "cmd-a")
        self.assertFalse(second.allowed)
        self.assertIn("already used", second.message)

    def test_unknown_token_refused(self):
        decision = self.gate.validate("not-a-real-token", "FW-001", "cmd-a")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "refused")
        self.assertIn("Unknown", decision.message)

    def test_run_id_bound_token_matches_same_run(self):
        payload = self.gate.approve("FW-001", "cmd-a", run_id="run-1")
        decision = self.gate.validate(payload["token"], "FW-001", "cmd-a", run_id="run-1")
        self.assertTrue(decision.allowed)


class GateDecideTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.gate = Gate(ledger_path=Path(self._tmp.name) / "ledger.jsonl")

    def tearDown(self):
        self._tmp.cleanup()

    def test_read_and_safe_write_auto_allowed(self):
        for risk in ("read", "safe_write"):
            decision = self.gate.decide(risk_class=risk, control_id="C-1", target="t")
            self.assertTrue(decision.allowed, risk)

    def test_confirm_requires_token_or_interactive(self):
        decision = self.gate.decide(risk_class="confirm", control_id="C-1", target="t")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "requires_interactive")
        self.assertEqual(decision.exit_code, 2)

    def test_confirm_interactive_consent_allowed(self):
        decision = self.gate.decide(
            risk_class="confirm", control_id="C-1", target="t", interactive=True
        )
        self.assertTrue(decision.allowed)

    def test_confirm_valid_token_allowed_without_interactivity(self):
        payload = self.gate.approve("C-1", "t")
        decision = self.gate.decide(
            risk_class="confirm", control_id="C-1", target="t", token=payload["token"]
        )
        self.assertTrue(decision.allowed)

    def test_confirm_bad_token_refused_even_interactive(self):
        self.gate.approve("C-1", "t")
        decision = self.gate.decide(
            risk_class="confirm", control_id="C-1", target="t", token="wrong", interactive=True
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "refused")

    def test_dangerous_requires_token_even_interactive(self):
        decision = self.gate.decide(
            risk_class="dangerous", control_id="C-1", target="t", interactive=True
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "refused")
        self.assertIn("token", decision.message)

    def test_dangerous_valid_token_allowed(self):
        payload = self.gate.approve("C-1", "t")
        decision = self.gate.decide(
            risk_class="dangerous", control_id="C-1", target="t", token=payload["token"]
        )
        self.assertTrue(decision.allowed)

    def test_unknown_risk_class_raises(self):
        with self.assertRaises(ValueError):
            self.gate.decide(risk_class="yolo")

    def test_expiry_is_enforced_over_wall_clock(self):
        payload = self.gate.approve("C-1", "t", ttl_seconds=1)
        # Tamper with the ledger expiry to simulate the passage of time.
        events = [json.loads(line) for line in self.gate.ledger_path.read_text().splitlines()]
        events[0]["expires_at"] = time.time() - 5
        self.gate.ledger_path.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        )
        decision = self.gate.validate(payload["token"], "C-1", "t")
        self.assertFalse(decision.allowed)
        self.assertIn("expired", decision.message)


if __name__ == "__main__":
    unittest.main()
