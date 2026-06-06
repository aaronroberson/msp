import json
import sys
import unittest

from src.command import CommandResult, list_command, run_command


class CommandTest(unittest.TestCase):
    def test_command_result_is_json_serializable(self):
        result = CommandResult(command=["echo", "ok"], returncode=0, stdout="ok\n")

        payload = result.to_dict()

        self.assertIs(payload["success"], True)
        self.assertEqual(payload["output"], "ok\n")
        self.assertEqual(json.loads(json.dumps(payload))["command"], ["echo", "ok"])

    def test_list_command_runs_without_shell(self):
        result = list_command([sys.executable, "-c", "print('ok')"])

        self.assertIs(result.success, True)
        self.assertEqual(result.stdout, "ok\n")
        self.assertEqual(result.command, [sys.executable, "-c", "print('ok')"])

    def test_shell_command_string_migration_path(self):
        result = run_command(f"{sys.executable} -c \"print('shell-ok')\"", shell=True)

        self.assertIs(result.success, True)
        self.assertEqual(result.stdout, "shell-ok\n")

    def test_timeout_returns_consistent_error_result(self):
        result = list_command(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout=0.1,
        )

        self.assertIs(result.success, False)
        self.assertEqual(result.returncode, 124)
        self.assertIs(result.timed_out, True)
        self.assertEqual(result.error, "Command timed out")

    def test_dry_run_does_not_execute_command(self):
        result = list_command(
            [sys.executable, "-c", "raise SystemExit(99)"],
            dry_run=True,
        )

        self.assertIs(result.success, True)
        self.assertIs(result.dry_run, True)
        self.assertEqual(result.returncode, 0)

    def test_sudo_prefix_is_applied_to_list_commands(self):
        result = list_command(["launchctl", "list"], sudo=True, dry_run=True)

        self.assertEqual(result.command, ["sudo", "launchctl", "list"])

    def test_sensitive_values_and_ips_are_redacted_from_result(self):
        result = list_command(
            [
                sys.executable,
                "-c",
                "print('token=secret-value ip=192.168.1.10')",
            ],
            sensitive_values=["secret-value"],
        )

        self.assertNotIn("secret-value", result.stdout)
        self.assertNotIn("192.168.1.10", result.stdout)
        self.assertEqual(result.stdout.count("[REDACTED]"), 2)

    def test_sensitive_values_are_redacted_from_command_display(self):
        result = list_command(
            [sys.executable, "-c", "print('hidden')", "--token", "secret-value"],
            sensitive_values=["secret-value"],
            dry_run=True,
        )

        self.assertEqual(result.command[-1], "[REDACTED]")

    def test_missing_executable_returns_error_result(self):
        result = list_command(["definitely-not-a-real-command"])

        self.assertIs(result.success, False)
        self.assertEqual(result.returncode, 127)
        self.assertEqual(result.error, "FileNotFoundError")


if __name__ == "__main__":
    unittest.main()
