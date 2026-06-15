import io
import json
import unittest
from contextlib import redirect_stdout

from src import workflows


class FakeReasoner:
    def analyze(self, facts=None, findings=None, plan=None):
        return {
            "summary": "workflow reasoning",
            "risk_assessment": {"level": "info"},
            "recommended_next_steps": ["review plan"],
            "confidence": 0.8,
            "provider": "fake",
        }


class WorkflowsTest(unittest.TestCase):
    def test_builtin_workflows_exist(self):
        rows = workflows.list_workflows()
        ids = {row["id"] for row in rows}

        self.assertEqual(ids, {"daily", "incident", "harden", "evidence"})
        self.assertTrue(all(int(row["steps"]) > 0 for row in rows))

    def test_show_workflow_contains_ordered_cli_concepts(self):
        workflow = workflows.get_workflow("incident")
        concepts = [step.concept for step in workflow.steps]

        self.assertEqual(concepts[0], "interrogate")
        self.assertIn("audit", concepts)
        self.assertIn("reason", concepts)
        self.assertIn("remediate plan", concepts)
        self.assertIn("report", concepts)

    def test_run_workflow_returns_non_destructive_plan(self):
        result = workflows.run_workflow("harden", reasoner=FakeReasoner())

        self.assertEqual(result["schema_version"], "1.0")
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["destructive_actions_allowed"])
        self.assertEqual(result["reasoning"]["provider"], "fake")
        self.assertTrue(all(step["will_execute"] is False for step in result["steps"]))
        self.assertTrue(all(step["status"] == "planned" for step in result["steps"]))

    def test_run_workflow_can_skip_reasoning(self):
        result = workflows.run_workflow("daily", include_reasoning=False)

        self.assertNotIn("reasoning", result)

    def test_unknown_workflow_raises(self):
        with self.assertRaises(ValueError):
            workflows.get_workflow("missing")

    def test_cli_list_json(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = workflows.main(["list", "--json"])

        payload = json.loads(stream.getvalue())
        self.assertEqual(code, 0)
        self.assertIn("workflows", payload)
        self.assertEqual(payload["schema_version"], "1.0")

    def test_cli_show_text(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = workflows.main(["show", "daily"])

        output = stream.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Daily Privacy Check", output)
        self.assertIn("msp interrogate", output)

    def test_cli_run_json_no_reason(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = workflows.main(["run", "evidence", "--json", "--no-reason"])

        payload = json.loads(stream.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["workflow"]["id"], "evidence")
        self.assertNotIn("reasoning", payload)
        self.assertTrue(payload["dry_run"])


if __name__ == "__main__":
    unittest.main()
