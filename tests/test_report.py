import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import report


class ReportTest(unittest.TestCase):
    def sample_facts(self):
        return {
            "network": {
                "listeners": [
                    {"process": "server", "host": "192.168.1.10", "port": 8080},
                ]
            },
            "service_config": {
                "api_token": "abc123",
                "password": "secret",
            },
        }

    def sample_findings(self):
        return {
            "findings": [
                {
                    "rule_id": "FW-001",
                    "title": "Firewall disabled",
                    "category": "firewall",
                    "severity": "high",
                    "remediation": "Enable the application firewall.",
                    "evidence": {"host": "10.0.0.5"},
                },
                {
                    "rule_id": "NET-001",
                    "title": "Service exposed",
                    "category": "network",
                    "severity": "medium",
                    "remediation": "Restrict listener binding.",
                },
            ]
        }

    def test_build_bundle_adds_metadata_summary_and_redacts(self):
        with mock.patch("src.report.utc_now", return_value="2026-06-06T00:00:00+00:00"):
            with mock.patch("src.report.host_metadata", return_value={"hostname": "host", "system": "Darwin"}):
                bundle = report.build_bundle(self.sample_facts(), self.sample_findings())

        self.assertEqual(bundle["schema_version"], "1.0")
        self.assertEqual(bundle["generated_at"], "2026-06-06T00:00:00+00:00")
        self.assertEqual(bundle["summary"]["total_findings"], 2)
        self.assertEqual(bundle["summary"]["by_severity"]["high"], 1)
        self.assertEqual(bundle["summary"]["by_category"]["network"], 1)
        self.assertEqual(bundle["facts"]["network"]["listeners"][0]["host"], "[REDACTED_IP]")
        self.assertEqual(bundle["facts"]["service_config"]["api_token"], "[REDACTED]")
        self.assertEqual(bundle["facts"]["service_config"]["password"], "[REDACTED]")
        self.assertEqual(bundle["findings"][0]["evidence"]["host"], "[REDACTED_IP]")

    def test_top_findings_are_sorted_by_severity(self):
        findings = [
            {"rule_id": "LOW", "severity": "low", "category": "x", "title": "low"},
            {"rule_id": "CRIT", "severity": "critical", "category": "x", "title": "critical"},
            {"rule_id": "HIGH", "severity": "high", "category": "x", "title": "high"},
        ]

        top = report.top_findings(findings)

        self.assertEqual([item["rule_id"] for item in top], ["CRIT", "HIGH", "LOW"])

    def test_render_json_and_markdown_include_expected_sections(self):
        bundle = {
            "schema_version": "1.0",
            "generated_at": "2026-06-06T00:00:00+00:00",
            "host": {"hostname": "host", "system": "Darwin", "release": "25.0.0"},
            "summary": {
                "total_findings": 1,
                "by_severity": {"critical": 0, "high": 1},
                "by_category": {"firewall": 1},
            },
            "top_findings": [
                {
                    "severity": "high",
                    "rule_id": "FW-001",
                    "category": "firewall",
                    "title": "Firewall disabled",
                    "remediation": "Enable firewall.",
                }
            ],
            "facts": {},
            "findings": [],
        }

        json_payload = json.loads(report.render_json(bundle))
        markdown = report.render_markdown(bundle)

        self.assertEqual(json_payload["schema_version"], "1.0")
        self.assertIn("# macOS Privacy Evidence Report", markdown)
        self.assertIn("## Findings By Severity", markdown)
        self.assertIn("FW-001", markdown)
        self.assertIn("Enable firewall.", markdown)

    def test_cli_writes_json_output_with_optional_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facts_path = tmp_path / "facts.json"
            findings_path = tmp_path / "findings.json"
            plan_path = tmp_path / "plan.json"
            output_path = tmp_path / "bundle.json"
            facts_path.write_text(json.dumps(self.sample_facts()), encoding="utf-8")
            findings_path.write_text(json.dumps(self.sample_findings()), encoding="utf-8")
            plan_path.write_text(json.dumps({"actions": [{"command": "echo", "token": "abc"}]}), encoding="utf-8")

            code = report.main(
                [
                    "--facts",
                    str(facts_path),
                    "--findings",
                    str(findings_path),
                    "--plan",
                    str(plan_path),
                    "--format",
                    "json",
                    "--output",
                    str(output_path),
                ]
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertIn("remediation_plan", payload)
            self.assertEqual(payload["remediation_plan"]["actions"][0]["token"], "[REDACTED]")

    def test_cli_writes_markdown_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facts_path = tmp_path / "facts.json"
            findings_path = tmp_path / "findings.json"
            output_path = tmp_path / "report.md"
            facts_path.write_text(json.dumps({}), encoding="utf-8")
            findings_path.write_text(json.dumps(self.sample_findings()), encoding="utf-8")

            code = report.main(
                [
                    "--facts",
                    str(facts_path),
                    "--findings",
                    str(findings_path),
                    "--format",
                    "md",
                    "--output",
                    str(output_path),
                ]
            )

            markdown = output_path.read_text(encoding="utf-8")
            self.assertEqual(code, 0)
            self.assertIn("# macOS Privacy Evidence Report", markdown)
            self.assertIn("FW-001", markdown)

    def test_invalid_findings_shape_raises(self):
        with self.assertRaises(ValueError):
            report.normalize_findings({"findings": {"not": "a list"}})


if __name__ == "__main__":
    unittest.main()
