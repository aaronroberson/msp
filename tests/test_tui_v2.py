"""Focused acceptance coverage for live TUI interactions and CLI adapters."""
import asyncio
import os
import subprocess
from pathlib import Path
from textual.widgets import Button

from src.network import NetworkMonitor
from src.startup import StartupManager
from src.tui_v2 import CommandBroker, MspTUI, REPO_ROOT, RUNNABLES, VIEWS, _payload_rows, _requires_confirmation


def test_catalog_and_command_confirmations():
    assert len({view.id for view in VIEWS}) == len(VIEWS)
    assert all(view.columns and view.command for view in VIEWS if view.id not in {"dashboard", "runner"})
    assert RUNNABLES
    assert _requires_confirmation(["net", "terminate", "--pid", "22"])
    assert _requires_confirmation(["firewall", "set", "enabled", "off"])
    assert _requires_confirmation(["startup", "agent-remove", "example.agent"])
    assert not _requires_confirmation(["firewall", "status"])
    assert not _requires_confirmation(["scan", "quick"])


def test_firewall_payload_and_command_broker():
    rows = _payload_rows("firewall", {"enabled": True, "stealth_mode": False, "apps_output": "app record"})
    assert rows == [
        {"setting": "Enabled", "value": "On", "details": ""},
        {"setting": "Stealth Mode", "value": "Off", "details": ""},
        {"setting": "Application", "value": "Rule", "details": "app record"},
    ]
    broker = CommandBroker("net inspect --pid 10 --json")
    assert broker.argv()[-5:] == ["net", "inspect", "--pid", "10", "--json"]
    assert broker.env()["PYTHONPATH"].split(os.pathsep)[0] == str(REPO_ROOT)


def test_privacy_firewall_details_use_bullets():
    rows = _payload_rows("privacy", {"firewall": {
        "enabled": True, "stealth_mode": True, "block_all": False,
    }})
    assert rows[0]["details"] == "• Stealth Mode: True\n• Block All: False"


def test_firewall_mutations_use_fixed_argument_vectors(monkeypatch, tmp_path):
    import src.firewall as firewall

    calls = []

    def fake_run(argv, privileged=False):
        calls.append((argv, privileged))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(firewall, "_run", fake_run)
    assert firewall.set_option("stealth_mode", True)["ok"]
    stale_path = tmp_path / "uninstalled.app"
    assert firewall.app_action("remove", str(stale_path))["ok"]
    assert calls[0] == ([firewall.SOCKETFILTERFW, "--setstealthmode", "on"], True)
    assert calls[1] == ([firewall.SOCKETFILTERFW, "--remove", str(stale_path)], True)


def test_startup_agent_add_and_recoverable_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    executable = tmp_path / "app"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    manager = StartupManager()
    created = manager.add_agent("test.example", str(executable), ["--flag"])
    plist_path = Path(created["path"])
    assert plist_path.exists()
    monkeypatch.setattr(
        "src.startup.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", ""),
    )
    removed = manager.remove_agent("test.example")
    backup = Path(removed["backup"])
    assert not plist_path.exists()
    assert backup.exists()
    assert executable.exists()
    assert removed["executable_preserved"] is True


def test_terminate_process_uses_graceful_signal_and_wait(monkeypatch):
    sent = []
    checks = iter([None, None])

    def fake_kill(pid, signal_number):
        sent.append(signal_number)
        next(checks)

    monkeypatch.setattr("src.network.os.kill", fake_kill)
    monkeypatch.setattr("src.network.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        "src.network.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "S", ""),
    )
    result = NetworkMonitor().terminate_process(4242, confirmed=True)
    assert sent[0] != 0
    assert result["still_running"] is True


def test_app_exposes_firewall_and_startup_controls(monkeypatch):
    import src.tui_v2 as tui_v2

    class QuietBroker:
        def __init__(self, line):
            self.line = line

        def run(self):
            yield ("{}", False, None, 0.0)
            yield ("[exit 0 · 0.0s]", True, 0, 0.0)

        def kill(self):
            pass

    monkeypatch.setattr(tui_v2, "CommandBroker", QuietBroker)

    async def exercise():
        app = MspTUI()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.1)
            assert app.query_one("#nav-dashboard", Button).label == "Dashboard"
            assert app.query_one("#open-config", Button)
            app.switch_view_id("firewall")
            await pilot.pause()
            assert app.query_one("#firewall-enable")
            assert app.query_one("#firewall-app-path")
            assert app.query_one("#nav-privacy").has_class("-active")
            await pilot.press("7")
            await pilot.pause()
            assert app._current_id == "snapshots"
            await pilot.press("8")
            await pilot.pause()
            assert app._current_id == "firewall"
            app.switch_view_id("startup")
            await pilot.pause()
            assert app.query_one("#startup-login-add")
            assert app.query_one("#startup-agent-add")
            assert app.query_one("#startup-remove")

    asyncio.run(exercise())
