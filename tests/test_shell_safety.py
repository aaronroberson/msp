"""Untrusted paths and names must never reach a shell.

Scans read file paths and process names from the machine being inspected; a
crafted name (``x'; rm -rf ~; '``) must not execute when msp scans it.
"""
import re
from pathlib import Path

from src.scanner import SecurityScanner

SRC = Path(__file__).resolve().parents[1] / "src"
QUOTED_INTERPOLATION = re.compile(r"""_run_cmd\(f["'][^"']*'\{""")


def test_no_shell_command_interpolates_a_quoted_value():
    offenders = [
        f"{path.relative_to(SRC.parent)}:{number}"
        for path in SRC.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if QUOTED_INTERPOLATION.search(line)
    ]
    assert offenders == [], "use the argv-list form of _run_cmd for paths/names: " + ", ".join(offenders)


def test_hostile_paths_are_not_executed(tmp_path):
    marker = tmp_path / "pwned"
    hostile = f"/tmp/x'; touch {marker}; echo '"
    scanner = SecurityScanner()
    scanner._is_apple_signed(hostile)
    scanner.signature_info(hostile)
    scanner.verify_app(hostile)
    assert not marker.exists()


def test_argv_mode_runs_without_a_shell(monkeypatch):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "out", "err"

    monkeypatch.setattr("src.scanner.subprocess.run", lambda argv, **kw: calls.append((argv, kw)) or Done())
    ok, output = SecurityScanner()._run_cmd(["codesign", "-dvvv", "/a b"], stderr=False)
    argv, kwargs = calls[0]
    assert argv == ["codesign", "-dvvv", "/a b"] and not kwargs.get("shell")
    assert (ok, output) == (True, "out")
