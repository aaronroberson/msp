"""Unit tests for evidence-based status verdicts in PrivacySettings (T-04).

Fixtures use real socketfilterfw / fdesetup output shapes captured on macOS.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.privacy_settings import PrivacySettingsManager

SOCKETFILTERFW = "/usr/libexec/ApplicationFirewall/socketfilterfw"

SAMPLE_LISTAPPS = (
    "Total number of apps = 3 \n"
    "1 : /Applications/Xcode.app/Contents/Applications/DeviceHub.app/Contents/MacOS/DeviceHub \n"
    "             (Allow incoming connections)\n"
    "2 : /System/Applications/Messages.app/Contents/MacOS/Messages \n"
    "             (Block incoming connections)\n"
    "3 : /Applications/Studio by Spotify Labs.app \n"
    "             (Allow incoming connections)\n"
)


def fake_run_command_factory(outputs):
    """Map command strings to (success, output) pairs, like the real subprocess."""
    def fake_run_command(self, cmd, shell=False, capture=True):
        return outputs[cmd]

    return fake_run_command


class FirewallStatusTests(unittest.TestCase):
    def test_firewall_enabled_all_verdicts(self):
        outputs = {
            f"{SOCKETFILTERFW} --getglobalstate": (True, "Firewall is enabled. (State = 1)"),
            f"{SOCKETFILTERFW} --getstealthmode": (True, "Firewall stealth mode is on"),
            f"{SOCKETFILTERFW} --getallowsigned": (True, "Automatically allow built-in signed software ENABLED."),
            f"{SOCKETFILTERFW} --listapps": (True, SAMPLE_LISTAPPS),
        }
        with patch.object(
            PrivacySettingsManager, "run_command", fake_run_command_factory(outputs)
        ):
            fw = PrivacySettingsManager().get_firewall_status()
        self.assertTrue(fw["enabled"])
        self.assertTrue(fw["stealth_mode"])
        # "ENABLED." verdict — the old "on" substring verdict reported False here.
        self.assertTrue(fw["allows_signed"])
        self.assertEqual(
            fw["exceptions"],
            [
                {"name": "DeviceHub", "status": "ALLOW"},
                {"name": "Messages", "status": "BLOCK"},
                {"name": "Studio by Spotify Labs.app", "status": "ALLOW"},
            ],
        )

    def test_firewall_disabled_outputs_report_false(self):
        outputs = {
            f"{SOCKETFILTERFW} --getglobalstate": (True, "Firewall is disabled. (State = 0)"),
            f"{SOCKETFILTERFW} --getstealthmode": (True, "Firewall stealth mode is off"),
            f"{SOCKETFILTERFW} --getallowsigned": (True, "Automatically allow built-in signed software DISABLED."),
            f"{SOCKETFILTERFW} --listapps": (True, "Total number of apps = 0 \n"),
        }
        with patch.object(
            PrivacySettingsManager, "run_command", fake_run_command_factory(outputs)
        ):
            fw = PrivacySettingsManager().get_firewall_status()
        self.assertFalse(fw["enabled"])
        self.assertFalse(fw["stealth_mode"])
        self.assertFalse(fw["allows_signed"])
        self.assertEqual(fw["exceptions"], [])

    def test_no_invalid_flag_queries_remain(self):
        seen = []

        def fake_run_command(self, cmd, shell=False, capture=True):
            seen.append(cmd)
            return (True, "")

        with patch.object(PrivacySettingsManager, "run_command", fake_run_command):
            PrivacySettingsManager().get_firewall_status()
        self.assertFalse(any("--getallowsignedapp" in c for c in seen))
        self.assertFalse(any("--getincoming" in c for c in seen))
        self.assertFalse(any("--getoutgoing" in c for c in seen))


class FileVaultStatusTests(unittest.TestCase):
    def test_filevault_on(self):
        outputs = {"fdesetup status": (True, "FileVault is On.\n")}
        with patch.object(
            PrivacySettingsManager, "run_command", fake_run_command_factory(outputs)
        ):
            status = PrivacySettingsManager().get_filevault_status()
        self.assertTrue(status["enabled"])
        self.assertTrue(status["encrypted"])

    def test_filevault_on_but_conversion_in_progress(self):
        outputs = {
            "fdesetup status": (
                True,
                "FileVault is On.\nEncryption in progress: Percent (0%)\n",
            )
        }
        with patch.object(
            PrivacySettingsManager, "run_command", fake_run_command_factory(outputs)
        ):
            status = PrivacySettingsManager().get_filevault_status()
        self.assertTrue(status["enabled"])
        # Mid-conversion is NOT fully encrypted — the old "Convert"→True verdict lied.
        self.assertFalse(status["encrypted"])

    def test_filevault_off(self):
        outputs = {"fdesetup status": (True, "FileVault is Off.\n")}
        with patch.object(
            PrivacySettingsManager, "run_command", fake_run_command_factory(outputs)
        ):
            status = PrivacySettingsManager().get_filevault_status()
        self.assertFalse(status["enabled"])
        self.assertFalse(status["encrypted"])


class RunCommandArgvTests(unittest.TestCase):
    def test_run_command_splits_and_uses_shell_false(self):
        settings = PrivacySettingsManager()
        with patch("src.privacy_settings.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "ok"
            mock_run.return_value.stderr = ""
            success, output = settings.run_command(
                "fdesetup status -verbose 'quoted arg'"
            )
        self.assertTrue(success)
        self.assertEqual(output, "ok")
        mock_run.assert_called_once_with(
            ["fdesetup", "status", "-verbose", "quoted arg"],
            shell=False,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
