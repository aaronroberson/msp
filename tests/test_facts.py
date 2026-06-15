import json
import os
import tempfile
import unittest
from dataclasses import dataclass
from unittest.mock import Mock, patch

from src import facts


@dataclass
class FakeListener:
    process: str
    pid: int
    user: str
    local_addr: str
    remote_addr: str
    state: str
    protocol: str = "TCP"


class FactsTest(unittest.TestCase):
    def test_collect_facts_normalizes_rule_engine_paths(self):
        with self._patched_collectors() as mocks:
            result = facts.collect_facts(redact=False)

        self.assertFalse(result["firewall"]["enabled"])
        self.assertFalse(result["firewall"]["stealth"])
        self.assertFalse(result["filevault"]["enabled"])
        self.assertTrue(result["gatekeeper"]["enabled"])
        self.assertTrue(result["sharing"]["enabled"])
        self.assertEqual(result["security_settings"]["password_after_sleep"], False)
        self.assertEqual(result["security_settings"]["password_delay"], 120)
        self.assertEqual(result["security_settings"]["screen_lock_minutes"], 20)

        self.assertEqual(result["network"]["listeners"][0]["port"], 3000)
        self.assertEqual(result["network"]["listeners"][1]["host"], "127.0.0.1")
        self.assertEqual(len(result["network"]["exposed_services"]), 1)
        self.assertEqual(result["network"]["services"]["ssh"]["enabled"], True)

        self.assertEqual(len(result["startup"]["items"]), 1)
        self.assertEqual(len(result["startup"]["suspicious_items"]), 2)
        self.assertEqual(result["startup"]["unsigned_items"][0]["item"], "unsigned.agent")

        self.assertEqual(result["tcc"]["high_risk_grants"][0]["service"], "kTCCServiceAllFiles")
        self.assertIn("AllFiles", result["tcc"]["allowed"])
        self.assertIn("Camera", result["tcc"]["denied"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(mocks["privacy"].get_firewall_status.call_count, 1)

    def test_sections_limits_collection(self):
        with self._patched_collectors() as mocks:
            result = facts.collect_facts(sections=["network"], redact=False)

        self.assertEqual(result["metadata"]["sections"], ["network"])
        self.assertEqual(len(result["network"]["listeners"]), 2)
        self.assertEqual(mocks["network"].list_listening.call_count, 1)
        self.assertEqual(mocks["privacy"].get_firewall_status.call_count, 0)

    def test_fail_soft_records_errors_and_keeps_shape(self):
        with self._patched_collectors() as mocks:
            mocks["privacy"].get_firewall_status.side_effect = RuntimeError("boom")
            result = facts.collect_facts(sections=["privacy_settings", "sharing"], redact=False)

        self.assertEqual(result["firewall"], {})
        self.assertTrue(result["sharing"]["enabled"])
        self.assertEqual(result["errors"][0]["section"], "privacy_settings")
        self.assertIn("boom", result["errors"][0]["message"])

    def test_redaction_masks_metadata_paths_and_remote_ips(self):
        sample = {
            "metadata": {"hostname": "local-mac", "user": "alice"},
            "network": {"connections": [{"remote": "203.0.113.10:443"}]},
            "startup": {"items": [{"path": "/Users/alice/Library/LaunchAgents/a.plist"}]},
        }

        with patch("src.facts.getpass.getuser", return_value="alice"):
            redacted = facts.redact_facts(sample)

        self.assertEqual(redacted["metadata"]["hostname"], "<redacted>")
        self.assertEqual(redacted["metadata"]["user"], "<redacted>")
        self.assertEqual(redacted["network"]["connections"][0]["remote"], "<ip>:443")
        self.assertEqual(redacted["startup"]["items"][0]["path"], "/Users/<redacted>/Library/LaunchAgents/a.plist")

    def test_facts_to_json_sorts_keys(self):
        payload = json.loads(facts.facts_to_json({"b": 1, "a": 2}))

        self.assertEqual(payload, {"a": 2, "b": 1})

    def test_main_writes_output_file(self):
        with self._patched_collectors(), tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "facts.json")
            code = facts.main(["--sections", "network", "--output", output])

            self.assertEqual(code, 0)
            with open(output, "r", encoding="utf-8") as handle:
                payload = json.loads(handle.read())

        self.assertEqual(payload["metadata"]["sections"], ["network"])
        self.assertIn("listeners", payload["network"])

    def _patched_collectors(self):
        return _CollectorPatches(self)


class _CollectorPatches:
    def __init__(self, test_case):
        self.test_case = test_case
        self.patchers = []
        self.mocks = {}

    def __enter__(self):
        privacy = Mock()
        privacy.get_firewall_status.return_value = {"enabled": False, "stealth_mode": False}
        privacy.get_filevault_status.return_value = {"enabled": False, "encrypted": False}
        privacy.get_gatekeeper_status.return_value = {"enabled": True}
        privacy.get_listening_services.return_value = [{"process": "sshd", "pid": 9, "port": "22", "type": "listening"}]
        privacy.get_security_settings.return_value = {"idle_time": "1200", "password_required": False}

        network = Mock()
        network.list_listening.return_value = [
            FakeListener("node", 123, "alice", "0.0.0.0:3000", "", "LISTEN"),
            FakeListener("redis", 456, "alice", "127.0.0.1:6379", "", "LISTEN"),
        ]
        network.list_established.return_value = [
            {"process": "Safari", "pid": "777", "user": "alice", "local": "10.0.0.4:51500", "remote": "203.0.113.10:443"}
        ]

        startup = Mock()
        startup.comprehensive_inventory.return_value = {
            "launch_plists": [{"label": "unsigned.agent", "path": "/tmp/agent.plist"}],
            "cron": [],
        }
        startup.audit.return_value = [{"item": "unsigned.agent", "risk": "HIGH", "reasons": ["Unsigned binary"]}]
        startup.comprehensive_audit.return_value = [{"item": "tmp.agent", "risk": "REVIEW", "reasons": ["Temporary location"]}]

        sharing = Mock()
        sharing.get_sharing_status.return_value = {
            "sharing_enabled": True,
            "share_points": [{"name": "Public", "guest_access": "0"}],
            "services": {"sftp": True, "smbd": False},
        }

        security = Mock()
        security.get_display_settings.return_value = {
            "password_after_sleep": False,
            "password_delay": 120,
            "idleTime": "1200",
        }
        security.get_firewall_connection_info.return_value = {"block_all": False}

        tcc = Mock()
        tcc.errors = []
        tcc.audit.return_value = [{"service": "kTCCServiceAllFiles", "client": "Terminal", "risk": "HIGH"}]
        tcc.list_permissions.return_value = [
            {
                "service": "kTCCServiceAllFiles",
                "client": "Terminal",
                "allowed": True,
            },
            {
                "service": "kTCCServiceCamera",
                "client": "Zoom",
                "allowed": False,
            },
        ]

        patches = [
            ("PrivacySettingsManager", privacy),
            ("NetworkMonitor", network),
            ("StartupManager", startup),
            ("SharingManager", sharing),
            ("SecuritySettings", security),
            ("TCCManager", tcc),
        ]
        for name, instance in patches:
            patcher = patch(f"src.facts.{name}", return_value=instance)
            self.patchers.append(patcher)
            patcher.start()
            self.mocks[name] = instance

        self.mocks = {
            "privacy": privacy,
            "network": network,
            "startup": startup,
            "sharing": sharing,
            "security": security,
            "tcc": tcc,
        }
        return self.mocks

    def __exit__(self, exc_type, exc, tb):
        for patcher in reversed(self.patchers):
            patcher.stop()


if __name__ == "__main__":
    unittest.main()
