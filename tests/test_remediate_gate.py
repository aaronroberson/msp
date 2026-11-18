"""Integration tests: the approval gate wired into remediation and doctor fix."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.command import CommandResult
from src.main import doctor_fix_gate
from src.gate import Gate, _sha256
from src.remediate import RemediationAction, RemediationPlan, RemediationPlanner, main as remediate_main


def _action(action_id, finding_id, safety, command):
    return RemediationAction(
        id=action_id,
        finding_id=finding_id,
        title=action_id,
        description=action_id,
        safety=safety,
        command=command,
    )


def _plan(actions):
    return RemediationPlan(actions=actions)


class ApplyPlanGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self._tmp.name) / "approval_ledger.jsonl"
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def _executor(self, command, sudo=False, dry_run=False, timeout=60):
        self.calls.append(list(command))
        return CommandResult(command=list(command), returncode=0)

    def _planner(self):
        return RemediationPlanner(executor=self._executor)

    def test_gateless_apply_is_legacy(self):
        plan = _plan([_action("fw_enable", "FW-001", "medium", ["echo", "fw"])])
        results = self._planner().apply_plan(plan, apply=True)
        self.assertEqual(results[0].status, "applied")
        self.assertEqual(self.calls, [["echo", "fw"]])

    def test_confirm_action_without_token_requires_approval(self):
        plan = _plan(
            [
                _action("lock_timeout", "SEC-003", "low", ["echo", "low"]),
                _action("fw_enable", "FW-001", "medium", ["echo", "confirm"]),
            ]
        )
        gate = Gate(ledger_path=self.ledger)
        results = self._planner().apply_plan(plan, apply=True, gate=gate)
        by_id = {r.action_id: r for r in results}
        self.assertEqual(by_id["lock_timeout"].status, "applied")
        self.assertEqual(by_id["fw_enable"].status, "requires_approval")
        self.assertIn("approval", by_id["fw_enable"].message.lower())
        self.assertEqual(self.calls, [["echo", "low"]])

    def test_valid_token_authorizes_confirm_action(self):
        plan = _plan([_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])])
        gate = Gate(ledger_path=self.ledger)
        payload = gate.approve("FW-001", "echo confirm")
        results = self._planner().apply_plan(
            plan, apply=True, gate=gate, tokens=[payload["token"]]
        )
        self.assertEqual(results[0].status, "applied")
        self.assertEqual(self.calls, [["echo", "confirm"]])

    def test_expired_token_does_not_authorize(self):
        plan = _plan([_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])])
        gate = Gate(ledger_path=self.ledger)
        payload = gate.approve("FW-001", "echo confirm", ttl_seconds=-1)
        results = self._planner().apply_plan(
            plan, apply=True, gate=gate, tokens=[payload["token"]]
        )
        self.assertEqual(results[0].status, "requires_approval")
        self.assertIn("expired", results[0].message)
        self.assertEqual(self.calls, [])

    def test_wrong_target_token_does_not_authorize(self):
        plan = _plan([_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])])
        gate = Gate(ledger_path=self.ledger)
        payload = gate.approve("FW-001", "echo something-else")
        results = self._planner().apply_plan(
            plan, apply=True, gate=gate, tokens=[payload["token"]]
        )
        self.assertEqual(results[0].status, "requires_approval")
        self.assertEqual(self.calls, [])

    def test_prompt_yes_authorizes_confirm_action(self):
        plan = _plan([_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])])
        gate = Gate(ledger_path=self.ledger)
        results = self._planner().apply_plan(
            plan, apply=True, gate=gate, prompt=lambda question: True
        )
        self.assertEqual(results[0].status, "applied")
        self.assertEqual(self.calls, [["echo", "confirm"]])

    def test_prompt_no_requires_approval(self):
        plan = _plan([_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])])
        gate = Gate(ledger_path=self.ledger)
        results = self._planner().apply_plan(
            plan, apply=True, gate=gate, prompt=lambda question: False
        )
        self.assertEqual(results[0].status, "requires_approval")
        self.assertEqual(self.calls, [])

    def test_dangerous_action_requires_token_even_with_prompt(self):
        plan = _plan([_action("tcc_reset", "TCC-001", "high", ["echo", "dangerous"])])
        gate = Gate(ledger_path=self.ledger)
        results = self._planner().apply_plan(
            plan,
            apply=True,
            allow_high_risk=True,
            gate=gate,
            prompt=lambda question: True,
        )
        self.assertEqual(results[0].status, "requires_approval")
        self.assertEqual(self.calls, [])

    def test_dangerous_action_token_allows(self):
        plan = _plan([_action("tcc_reset", "TCC-001", "high", ["echo", "dangerous"])])
        gate = Gate(ledger_path=self.ledger)
        payload = gate.approve("TCC-001", "echo dangerous")
        results = self._planner().apply_plan(
            plan, apply=True, allow_high_risk=True, gate=gate, tokens=[payload["token"]]
        )
        self.assertEqual(results[0].status, "applied")
        self.assertEqual(self.calls, [["echo", "dangerous"]])

    def test_dry_run_is_never_gated(self):
        plan = _plan([_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])])
        gate = Gate(ledger_path=self.ledger)
        results = self._planner().apply_plan(plan, apply=False, gate=gate)
        self.assertEqual(results[0].status, "dry_run")
        self.assertEqual(self.calls, [])


class RemediateCliGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self._tmp.name) / "approval_ledger.jsonl"
        self._env_patch = mock.patch.dict("os.environ", {"MSP_HOME": self._tmp.name})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def _write_plan(self, actions):
        plan = _plan(actions)
        path = Path(self._tmp.name) / "plan.json"
        path.write_text(plan.to_json())
        return path

    def test_cli_apply_without_token_exits_2_on_confirm(self):
        path = self._write_plan(
            [_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])]
        )
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            code = remediate_main(["apply", str(path), "--apply"])
        self.assertEqual(code, 2)

    def test_cli_apply_bare_yes_exits_2_on_confirm(self):
        path = self._write_plan(
            [_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])]
        )
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            code = remediate_main(["apply", str(path), "--apply", "--yes"])
        self.assertEqual(code, 2)

    def test_cli_apply_with_token_exits_0(self):
        path = self._write_plan(
            [_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])]
        )
        gate = Gate()
        payload = gate.approve("FW-001", "echo confirm")
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            code = remediate_main(["apply", str(path), "--apply", "--yes", payload["token"]])
        self.assertEqual(code, 0)

    def test_cli_apply_high_risk_without_token_exits_2(self):
        path = self._write_plan(
            [_action("tcc_reset", "TCC-001", "high", ["echo", "dangerous"])]
        )
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            code = remediate_main(
                ["apply", str(path), "--apply", "--allow-high-risk"]
            )
        self.assertEqual(code, 2)

    def test_cli_approve_mints_bound_token(self):
        path = self._write_plan(
            [_action("fw_enable", "FW-001", "medium", ["echo", "confirm"])]
        )
        captured = io.StringIO()
        with mock.patch("sys.stdout", captured):
            code = remediate_main(["approve", str(path), "--action", "fw_enable"])
        self.assertEqual(code, 0)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["control_id"], "FW-001")
        self.assertEqual(payload["target"], "echo confirm")
        self.assertTrue(payload["token"])
        ledger_text = (Path(self._tmp.name) / "state" / "approval_ledger.jsonl").read_text()
        self.assertNotIn(payload["token"], ledger_text)
        self.assertIn(_sha256(payload["token"]), ledger_text)
        self.assertIn("token_hash", ledger_text)


class DoctorFixGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env_patch = mock.patch.dict("os.environ", {"MSP_HOME": self._tmp.name})
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        self._tmp.cleanup()

    def test_dry_run_never_gated(self):
        self.assertTrue(doctor_fix_gate(["--dry-run"], stream=io.StringIO()))

    def test_non_tty_without_token_refused(self):
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            captured = io.StringIO()
            allowed = doctor_fix_gate([], stream=captured)
        self.assertFalse(allowed)
        payload = json.loads(captured.getvalue())
        self.assertEqual(payload["status"], "requires_approval")
        self.assertEqual(payload["control_id"], "doctor.fix")

    def test_bare_yes_refused_non_tty(self):
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            allowed = doctor_fix_gate(["--yes"], stream=io.StringIO())
        self.assertFalse(allowed)

    def test_valid_token_allows(self):
        gate = Gate()
        payload = gate.approve("doctor.fix", "doctor fix")
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            allowed = doctor_fix_gate(["--yes", payload["token"]], stream=io.StringIO())
        self.assertTrue(allowed)

    def test_interactive_yes_allows(self):
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = True
            with mock.patch("builtins.input", return_value="y"):
                allowed = doctor_fix_gate([], stream=io.StringIO())
        self.assertTrue(allowed)

    def test_interactive_no_refused(self):
        with mock.patch.object(sys, "stdin") as fake_stdin:
            fake_stdin.isatty.return_value = True
            with mock.patch("builtins.input", return_value="n"):
                allowed = doctor_fix_gate([], stream=io.StringIO())
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
