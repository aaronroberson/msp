import json
import unittest

from src.rules import (
    PROFILE_DEFINITIONS,
    RuleEngine,
    evaluate,
    findings_to_json,
    findings_to_table,
    get_path,
)


class RulesTest(unittest.TestCase):
    def test_get_path_reads_nested_mappings_and_lists(self):
        facts = {"network": {"listeners": [{"port": 22}]}}

        self.assertEqual(get_path(facts, "network.listeners.0.port"), 22)
        self.assertEqual(get_path(facts, "network.listeners.1.port", "missing"), "missing")

    def test_evaluate_returns_expected_core_findings(self):
        facts = {
            "firewall": {"enabled": False},
            "filevault": {"enabled": False},
            "gatekeeper": {"enabled": True},
            "sharing": {"enabled": False, "share_points": []},
            "startup": {"unsigned_items": [{"path": "/tmp/agent.plist"}]},
            "security_settings": {"password_after_sleep": False},
        }

        findings = evaluate(facts, profile="personal")
        rule_ids = {finding.rule_id for finding in findings}

        self.assertTrue({"FW-001", "FV-001", "ST-001", "SEC-001"} <= rule_ids)
        self.assertNotIn("GK-001", rule_ids)

    def test_missing_sections_do_not_create_findings(self):
        findings = evaluate({}, profile="personal")

        self.assertEqual(findings, [])

    def test_enterprise_profile_filters_low_severity_by_default(self):
        facts = {
            "network": {
                "exposed_services": [
                    {"process": "node", "host": "0.0.0.0", "port": 3000},
                ]
            }
        }

        findings = evaluate(facts, profile="enterprise")
        rule_ids = {finding.rule_id for finding in findings}

        self.assertIn("NW-001", rule_ids)
        self.assertNotIn("DEV-001", rule_ids)

    def test_minimum_severity_can_include_low_developer_findings(self):
        facts = {
            "network": {
                "exposed_services": [
                    {"process": "node", "host": "0.0.0.0", "port": 3000},
                ]
            }
        }

        findings = evaluate(facts, profile="developer", minimum_severity="low")
        rule_ids = {finding.rule_id for finding in findings}

        self.assertIn("DEV-001", rule_ids)

    def test_framework_metadata_is_preserved(self):
        facts = {"filevault": {"enabled": False}}

        findings = evaluate(facts, profile="personal")
        filevault = next(finding for finding in findings if finding.rule_id == "FV-001")

        self.assertTrue(filevault.cis)
        self.assertTrue(filevault.nist)
        self.assertTrue(filevault.stig)
        self.assertEqual(filevault.remediation_id, "filevault.enable.guidance")
        self.assertEqual(tuple(filevault.evidence_paths), ("filevault.enabled",))

    def test_remediation_metadata_is_emitted_in_json(self):
        facts = {"firewall": {"enabled": False}}

        payload = json.loads(findings_to_json(evaluate(facts)))
        finding = payload["findings"][0]

        self.assertEqual(finding["rule_id"], "FW-001")
        self.assertEqual(finding["remediation_id"], "firewall.enable")
        self.assertEqual(finding["evidence_paths"], ["firewall.enabled"])

    def test_output_helpers_render_json_and_plain_table(self):
        facts = {"firewall": {"enabled": False}}
        findings = evaluate(facts)

        payload = json.loads(findings_to_json(findings))
        table = findings_to_table(findings, use_rich=False)

        self.assertEqual(payload["findings"][0]["rule_id"], "FW-001")
        self.assertIn("FW-001", table)
        self.assertIn("Severity", table)

    def test_profile_definitions_have_rules(self):
        engine = RuleEngine()

        for profile in PROFILE_DEFINITIONS:
            self.assertTrue(engine.rules_for_profile(profile))


if __name__ == "__main__":
    unittest.main()
