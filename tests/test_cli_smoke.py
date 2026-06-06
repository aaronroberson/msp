import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    env = os.environ.copy()
    env["PYTHONPYCACHEPREFIX"] = "/private/tmp/msp_pycache_tests"
    return subprocess.run(
        [sys.executable, str(ROOT / "main.py"), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


class CLISmokeTest(unittest.TestCase):
    def test_help_smoke(self):
        result = run_cli("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("macOS Security & Privacy CLI", result.stdout)

    def test_unknown_command_smoke(self):
        result = run_cli("definitely-not-a-command")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Unknown command", result.stdout)

    def test_snapshot_capture_flag_does_not_depend_on_json(self):
        from src.snapshot import SnapshotManager

        captured = {}

        def fake_capture(self, **kwargs):
            captured.update(kwargs)
            return "/tmp/baseline.json"

        import main

        with patch.object(SnapshotManager, "capture", fake_capture), patch.object(
            sys,
            "argv",
            ["msp", "snapshot", "capture", "baseline", "--include-network"],
        ):
            main.main()

        self.assertEqual(captured["name"], "baseline")
        self.assertIs(captured["include_network"], True)
        self.assertIs(captured["include_startup"], False)


if __name__ == "__main__":
    unittest.main()
