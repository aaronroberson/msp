"""Focused acceptance coverage for live TUI interactions and CLI adapters."""
import asyncio
import os
import subprocess
from pathlib import Path
from textual.widgets import Button

from src.network import NetworkMonitor
from src.startup import StartupManager
from src.tui_v2 import CommandBroker, MspTUI, REPO_ROOT, RUNNABLES, VIEWS, _requires_confirmation


def test_catalog_and_command_confirmations():
    assert len({view.id for view in VIEWS}) == len(VIEWS)
    assert all(view.columns and view.command for view in VIEWS if view.id != "runner")
    assert RUNNABLES
    assert _requires_confirmation(["net", "terminate", "--pid", "22"])
    assert _requires_confirmation(["firewall", "set", "enabled", "off"])
    assert _requires_confirmation(["startup", "agent-remove", "example.agent"])
    assert not _requires_confirmation(["firewall", "status"])
    assert not _requires_confirmation(["scan", "quick"])


def test_command_broker_argv_and_env():
    broker = CommandBroker("net inspect --pid 10 --json")
    assert broker.argv()[-5:] == ["net", "inspect", "--pid", "10", "--json"]
    assert broker.env()["PYTHONPATH"].split(os.pathsep)[0] == str(REPO_ROOT)


def test_privacy_page_renders_firewall_rules_and_links_to_firewall():
    from textual.widgets import DataTable

    from src.tui_pages.runtime import run_replay

    async def exercise():
        app = MspTUI(executor=run_replay)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause(0.1)
            app.switch_view_id("privacy")
            await app.workers.wait_for_complete()
            await pilot.pause(0.3)
            assert app.query_one("#nav-privacy").has_class("-active")
            page = app.query_one("#page-privacy-settings")
            rules = page.query_one("#table-workspace-main-2", DataTable)
            assert rules.row_count == 8
            assert [str(c) for c in rules.get_row_at(0)] == ["DeviceHub", "Allowed"]
            # rules are summarised in the heading and listed readably, never dumped as JSON
            heading = " ".join(str(label.render()) for label in page.query(".eyebrow"))
            assert "FIREWALL APP RULES 1 allowed · 7 blocked" in heading
            assert not any("{" in str(rules.get_row_at(i)) for i in range(rules.row_count))
            page.query_one("#link-workspace-main-2", Button).press()
            await pilot.pause(0.2)
            assert app._current_id == "firewall"
            assert app.query_one("#nav-firewall").has_class("-active")

    asyncio.run(exercise())


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
    from src.tui_pages.runtime import run_replay

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
        app = MspTUI(executor=run_replay)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.1)
            assert app.query_one("#nav-dashboard", Button).label == "Dashboard"
            assert app.query_one("#open-config", Button)
            app.switch_view_id("firewall")
            await app.workers.wait_for_complete()
            await pilot.pause(0.2)
            page = app.query_one("#page-security-firewall")
            assert page.query("Switch")                         # firewall toggles
            assert page.query_one("#form-workspace-aside-2-path")  # add-app path field
            assert app.query_one("#nav-firewall").has_class("-active")
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


def test_page_actions_confirm_run_then_refresh(monkeypatch):
    """In the shell a page action asks for confirmation, runs the exact argv
    through the command rail, then re-runs only the action's ``refreshes``."""
    import src.tui_v2 as tui_v2
    from src.tui_pages.runtime import run_replay

    lines, executed = [], []

    class RecordingBroker:
        def __init__(self, line):
            lines.append(line)

        def run(self):
            yield ("[exit 0 · 0.0s]", True, 0, 0.0)

        def kill(self):
            pass

    def executor(run_id, command, args):
        executed.append(run_id)
        return run_replay(run_id, command, args)

    monkeypatch.setattr(tui_v2, "CommandBroker", RecordingBroker)

    async def exercise():
        app = MspTUI(executor=executor)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            executed.clear()                               # the dashboard opened first
            app.switch_view_id("firewall")
            await app.workers.wait_for_complete()
            await pilot.pause(0.2)
            assert executed == ["fw"]
            page = app.query_one("#page-security-firewall")
            page.query_one("#form-workspace-aside-2-path").value = "/Applications/My App.app"
            page.query_one("#submit-workspace-aside-2", Button).press()
            await pilot.pause(0.1)
            confirm = app.screen
            assert "firewall app add '/Applications/My App.app'" in str(confirm.query_one("#confirm-command").render())
            assert "administrator password" in str(confirm.query_one("#confirm-description").render())
            await pilot.press("escape")                    # cancel: nothing runs
            await pilot.pause(0.1)
            assert lines == []
            page.query_one("#submit-workspace-aside-2", Button).press()
            await pilot.pause(0.1)
            await pilot.press("y")
            await app.workers.wait_for_complete()
            await pilot.pause(0.3)
            await app.workers.wait_for_complete()
            assert lines == ["firewall app add '/Applications/My App.app'"]
            assert executed == ["fw", "fw"]                # refreshed exactly its read

    asyncio.run(exercise())


def test_palette_lists_sidebar_screens_and_opens_the_firewall_add_form():
    from textual.widgets import Input

    from src.tui_pages.runtime import run_replay

    async def exercise():
        app = MspTUI(executor=run_replay)
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.2)
            app.open_palette()
            await pilot.pause(0.1)
            entries = app.screen.entries
            assert ("VIEW", "Privacy settings", "Open privacy settings screen", "view:privacy") in entries
            index = next(i for i, e in enumerate(entries) if e[3] == "form:firewall-app")
            app.screen.dismiss(index)
            await pilot.pause(0.3)
            assert app._current_id == "firewall"
            assert isinstance(app.focused, Input) and app.focused.id == "form-workspace-aside-2-path"

    asyncio.run(exercise())
