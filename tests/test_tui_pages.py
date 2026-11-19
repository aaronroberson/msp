"""Manifest pages: scheduler semantics and the Firewall page in replay mode."""
import asyncio

import pytest
from textual.widgets import Button, DataTable, Static, Switch

from src.tui_manifest import PageSpec, load_commands, load_pages
from src.tui_pages.components import fill_args
from src.tui_pages.preview import PagePreviewApp
from src.tui_pages.runtime import RunResult, RunScheduler, build_argv, run_replay


def _counting_executor(calls):
    def executor(run_id, command, args):
        calls.append(run_id)
        return run_replay(run_id, command, args)
    return executor


def _page(runs):
    return PageSpec.model_validate({
        "page": {"id": "t.page", "concern": "overview", "title": "T", "order": 1, "template": "explorer"},
        "runs": runs,
    })


# ---------------------------------------------------------------- scheduler


def test_scheduler_waves_respect_order_wave_and_dependencies():
    page = _page([
        {"id": "a", "command": "net.list", "order": 1},
        {"id": "b", "command": "net.established", "order": 1},
        {"id": "c", "command": "startup.managed", "order": 1, "depends_on": ["a"]},
        {"id": "d", "command": "doctor", "order": 2},
    ])
    scheduler = RunScheduler(page, load_commands(), lambda *a: None)
    assert scheduler.waves(["a", "b", "c", "d"]) == [["a", "b"], ["c", "d"]]


def test_each_run_executes_once_and_refreshes_rerun_exactly_the_named_runs():
    page = load_pages()["security.firewall"]
    calls = []
    scheduler = RunScheduler(page, load_commands(), _counting_executor(calls))
    scheduler.open()
    scheduler.open()            # cached: a second visit-open does not re-execute
    assert calls == ["fw"]
    assert scheduler.refresh_targets("rule") == ["fw"]
    scheduler.execute(scheduler.refresh_targets("rule"), force=True)
    assert calls == ["fw", "fw"]


def test_scheduler_refuses_to_execute_mutations():
    page = load_pages()["security.firewall"]
    scheduler = RunScheduler(page, load_commands(), lambda *a: pytest.fail("must not run"))
    with pytest.raises(PermissionError):
        scheduler.execute(["toggle"])


def test_args_fill_from_row_and_build_the_exact_argv():
    commands = load_commands()
    args = {**fill_args({"path": "{row.path}"}, {"row": {"path": "/Applications/A b.app"}}), "operation": "block"}
    assert build_argv(commands["firewall.app"], args) == ["firewall", "app", "block", "/Applications/A b.app"]


# ------------------------------------------------------------ firewall page


def test_firewall_page_renders_from_one_run_and_only_previews_actions(monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("no command may run"))

    async def exercise():
        app = PagePreviewApp("security.firewall", executor=_counting_executor(calls))
        async with app.run_test(size=(150, 50)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause(0.2)
            # one `firewall status` run feeds strip, settings and table
            assert calls == ["fw"]
            table = app.query_one(DataTable)
            assert table.row_count == 8
            assert [str(c) for c in table.get_row_at(0)] == ["DeviceHub", "Allowed"]   # allowed first
            table.focus()
            await pilot.press("down")
            await pilot.pause(0.2)
            visible = {b.id for b in app.query(Button) if b.display}
            assert "act-rule-block" not in visible and "act-rule-unblock" in visible  # already blocked
            assert "act-rule-add" not in visible
            await pilot.click("#act-rule-unblock")
            await pilot.pause(0.1)
            preview = str(app.query_one("#action-preview", Static).render())
            assert "msp firewall app unblock /System/Library/Frameworks/AddressBook.framework" in preview
            assert "nothing executed" in preview and "administrator password" in preview
            switch = app.query(Switch).first()
            switch.toggle()
            await pilot.pause(0.1)
            assert "msp firewall set enabled off" in str(app.query_one("#action-preview", Static).render())
            assert calls == ["fw"]   # previews never execute

    asyncio.run(exercise())
