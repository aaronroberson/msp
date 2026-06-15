import json
import tempfile
import unittest
from pathlib import Path

from src.command import CommandResult
from src.remediate import (
    RemediationAction,
    RemediationPlan,
    RemediationPlanner,
    main,
)


class RemediationTest(unittest.TestCase):
    def test_plans_firewall_action_from_finding(self):
        planner = RemediationPlanner()

        plan = planner.plan_from_findings([{"rule_id": "FW-001"}])

        self.assertEqual(len(plan.actions), 1)
        action = plan.actions[0]
        self.assertEqual(action.finding_id, "FW-001")
        self.assertEqual(action.safety, "medium")
        self.assertTrue(action.requires_sudo)
        self.assertEqual(
            action.command,
            ["/usr/libexec/ApplicationFirewall/socketfilterfw", "--setglobalstate", "on"],
        )
        self.assertEqual(
            action.rollback_command,
            ["/usr/libexec/ApplicationFirewall/socketfilterfw", "--setglobalstate", "off"],
        )

    def test_plan_respects_max_safety(self):
        planner = RemediationPlanner()

        plan = planner.plan_from_findings(
            [{"rule_id": "TCC-002"}],
            max_safety="medium",
        )

        self.assertEqual(plan.actions, [])
        self.assertEqual(plan.skipped_findings[0]["rule_id"], "TCC-002")

    def test_apply_defaults_to_dry_run(self):
        calls = []

        def fake_executor(*args, **kwargs):
            calls.append((args, kwargs))
            return CommandResult(command=["unused"], returncode=0)

        planner = RemediationPlanner(executor=fake_executor)
        plan = planner.plan_from_findings([{"rule_id": "GK-001"}])

        results = planner.apply_plan(plan)

        self.assertEqual(calls, [])
        self.assertEqual(results[0].status, "dry_run")
        self.assertTrue(results[0].dry_run)
        self.assertEqual(results[0].command_result["command"], ["spctl", "--master-enable"])

    def test_apply_executes_low_risk_command_when_requested(self):
        calls = []

        def fake_executor(command, **kwargs):
            calls.append((command, kwargs))
            return CommandResult(command=list(command), returncode=0)

        planner = RemediationPlanner(executor=fake_executor)
        plan = planner.plan_from_findings([{"rule_id": "SEC-002"}])

        results = planner.apply_plan(plan, apply=True)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][0], "defaults")
        self.assertFalse(calls[0][1]["sudo"])
        self.assertEqual(results[0].status, "applied")
        self.assertFalse(results[0].dry_run)

    def test_high_risk_action_requires_explicit_override(self):
        calls = []

        def fake_executor(command, **kwargs):
            calls.append(command)
            return CommandResult(command=list(command), returncode=0)

        planner = RemediationPlanner(executor=fake_executor)
        plan = planner.plan_from_findings([{"rule_id": "TCC-002"}])

        blocked = planner.apply_plan(plan, apply=True)
        allowed = planner.apply_plan(plan, apply=True, allow_high_risk=True)

        self.assertEqual(blocked[0].status, "skipped")
        self.assertEqual(allowed[0].status, "applied")
        self.assertEqual(calls, [["tccutil", "reset", "ScreenCapture"]])

    def test_guidance_actions_are_not_executed(self):
        calls = []
        planner = RemediationPlanner(
            executor=lambda command, **kwargs: calls.append(command)
        )
        plan = planner.plan_from_findings([{"rule_id": "SH-001"}])

        results = planner.apply_plan(plan, apply=True)

        self.assertEqual(calls, [])
        self.assertEqual(results[0].status, "guidance")
        self.assertIn("System Settings", results[0].message)

    def test_tcc_high_risk_grants_create_service_reset_actions(self):
        finding = {
            "rule_id": "TCC-001",
            "evidence": {
                "tcc.high_risk_grants": [
                    {"service": "kTCCServiceScreenCapture"},
                    {"service": "SystemPolicyAllFiles"},
                ]
            },
        }
        planner = RemediationPlanner()

        plan = planner.plan_from_findings([finding])
        commands = {tuple(action.command) for action in plan.actions}

        self.assertEqual(len(plan.actions), 2)
        self.assertIn(("tccutil", "reset", "ScreenCapture"), commands)
        self.assertIn(("tccutil", "reset", "SystemPolicyAllFiles"), commands)

    def test_plan_round_trips_json(self):
        plan = RemediationPlan(
            actions=[
                RemediationAction(
                    id="sec_002_password_delay_zero",
                    finding_id="SEC-002",
                    title="Set delay",
                    description="Set delay to zero.",
                    safety="low",
                    command=["defaults", "write", "domain", "key", "-int", "0"],
                )
            ]
        )

        loaded = RemediationPlan.from_dict(json.loads(plan.to_json()))

        self.assertEqual(loaded.actions[0].id, plan.actions[0].id)
        self.assertEqual(loaded.actions[0].command, plan.actions[0].command)

    def test_cli_plan_writes_json_output(self):
        findings = {"findings": [{"rule_id": "FW-002"}]}
        with tempfile.TemporaryDirectory() as tmp:
            findings_path = Path(tmp) / "findings.json"
            output_path = Path(tmp) / "plan.json"
            findings_path.write_text(json.dumps(findings), encoding="utf-8")

            exit_code = main(["plan", str(findings_path), "--json", "--output", str(output_path)])

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["actions"][0]["finding_id"], "FW-002")

    def test_cli_apply_without_apply_is_dry_run(self):
        plan = RemediationPlan(
            actions=[
                RemediationAction(
                    id="fw_002_enable_stealth",
                    finding_id="FW-002",
                    title="Enable stealth",
                    description="Enable stealth mode.",
                    safety="low",
                    command=[
                        "/usr/libexec/ApplicationFirewall/socketfilterfw",
                        "--setstealthmode",
                        "on",
                    ],
                    requires_sudo=True,
                )
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = Path(tmp) / "plan.json"
            output_path = Path(tmp) / "results.json"
            plan_path.write_text(plan.to_json(), encoding="utf-8")

            exit_code = main(["apply", str(plan_path), "--json", "--output", str(output_path)])

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["results"][0]["status"], "dry_run")


if __name__ == "__main__":
    unittest.main()
