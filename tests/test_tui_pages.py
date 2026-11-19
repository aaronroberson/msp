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


def test_dashboard_scans_in_background_and_refreshes_saved_findings():
    """Saved findings show at once; `scan quick` runs in the background with the
    card marked as scanning; when it finishes `doctor` re-reads the saved scan.
    A revisit repeats the fast reads but not the scan."""
    import threading

    from src.tui_pages.page import PageView

    calls, release = [], threading.Event()

    def executor(run_id, command, args):
        calls.append(run_id)
        if run_id == "scan":
            release.wait(5)
        return run_replay(run_id, command, args)

    async def exercise():
        app = PagePreviewApp("overview.dashboard", executor=executor)
        async with app.run_test(size=(160, 45)) as pilot:
            page = app.query_one(PageView)
            for _ in range(50):
                await pilot.pause(0.05)
                if "doctor" in page.scheduler.results and "scan" in page.pending:
                    break
            findings = page.slots["workspace.main#3"]
            assert findings.loaded and findings.busy            # saved results shown, scan running
            assert "scanning" in " ".join(str(l.render()) for l in findings.query(".busy"))
            assert sorted(calls) == ["connections", "doctor", "listening", "scan", "startup", "status"]
            release.set()
            for _ in range(50):
                await pilot.pause(0.05)
                if calls.count("doctor") == 2 and not page.pending:
                    break
            await app.workers.wait_for_complete()
            assert calls.count("doctor") == 2 and not findings.busy  # re-read after the scan
            calls.clear()
            page.refresh_page(include_long=False)               # what a revisit does
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            assert "scan" not in calls and "doctor" in calls

    asyncio.run(exercise())


# ------------------------------------------------- tabs, selection, outbound


def _network_app(calls, **kw):
    def executor(run_id, command, args):
        calls.append((run_id, dict(args)))
        return run_replay(run_id, command, args)
    return PagePreviewApp("monitoring.network", executor=executor, **kw)


def test_tabs_run_their_reads_when_first_shown_and_show_only_their_slots():
    from src.tui_pages.page import PageView
    calls = []

    async def exercise():
        app = _network_app(calls)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            page = app.query_one(PageView)
            assert [c[0] for c in calls if not c[0].startswith("inspect_")] == ["listening"]
            assert page.slots["workspace.main#1"].display and not page.slots["workspace.main#2"].display
            page.query_one("#tab-established", Button).press()
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            assert [c[0] for c in calls if not c[0].startswith("inspect_")] == ["listening", "established"]
            assert page.slots["workspace.main#2"].display and not page.slots["workspace.main#1"].display
            page.query_one("#tab-listening", Button).press()       # cached: no re-run
            await pilot.pause(0.2)
            assert [c[0] for c in calls if not c[0].startswith("inspect_")] == ["listening", "established"]

    asyncio.run(exercise())


def test_selecting_a_row_inspects_that_rows_process():
    from src.tui_pages.page import PageView
    calls = []

    async def exercise():
        app = _network_app(calls)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            page = app.query_one(PageView)
            table = page.query_one("#table-workspace-main-1", DataTable)
            table.focus()
            await pilot.press("down", "down", "down", "down")       # debounced: only the last row runs
            await pilot.pause(0.5)
            await app.workers.wait_for_complete()
            await pilot.pause(0.2)
            inspects = [c[1]["pid"] for c in calls if c[0] == "inspect_listening"]
            shown = page.slots["workspace.main#1"]._shown
            # the row the cursor stopped on is inspected; the row it only passed
            # over is skipped (debounce). Row 0 may be inspected as the table loads.
            passed_over = {r["pid"] for r in shown[1:4]} - {shown[0]["pid"], shown[4]["pid"]}
            assert passed_over and inspects[-1] == shown[4]["pid"]
            assert not passed_over & set(inspects)
            inspector = page.slots["workspace.aside#1"]
            assert inspector.row.get("pid") and inspector.query("#act-terminate-terminate") and inspector.query("#act-kill-kill")

    asyncio.run(exercise())


def test_outbound_reads_never_run_automatically_and_are_previewed_without_a_shell():
    from src.tui_pages.page import PageView
    calls = []

    async def exercise():
        app = _network_app(calls)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            page = app.query_one(PageView)
            page.show_tab("neighbours")
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            page.query_one("#run-hosts", Button).press()             # sends traffic: preview only here
            await pilot.pause(0.1)
            assert "hosts" not in [c[0] for c in calls]
            assert "msp net hosts" in str(page.query_one("#action-preview", Static).render())
            page.refresh_page()
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            assert "hosts" not in [c[0] for c in calls] and "lookup" not in [c[0] for c in calls]

    asyncio.run(exercise())


def test_pages_may_not_run_outbound_commands_automatically():
    from src.tui_manifest import check_pages, load_labels, load_templates
    page = load_pages()["monitoring.network"].model_dump()
    next(r for r in page["runs"] if r["id"] == "hosts")["trigger"] = "on_view:neighbours"
    problems = check_pages({"p": PageSpec.model_validate(page)}, load_templates(), load_labels(), commands=load_commands())
    assert any("sends network traffic; it must be manual" in p for p in problems)


@pytest.mark.parametrize("mutate", [
    lambda p: next(r for r in p["runs"] if r["id"] == "arp").update(trigger="on_view:nowhere"),
    lambda p: next(r for r in p["runs"] if r["id"] == "inspect_listening").update(trigger="on_select:workspace.main#9"),
    lambda p: next(r for r in p["runs"] if r["id"] == "arp").update(trigger="sometimes"),
    lambda p: p["slots"][0].update(tab="nowhere"),
])
def test_triggers_and_tabs_must_reference_declared_things(mutate):
    from pydantic import ValidationError
    page = load_pages()["monitoring.network"].model_dump()
    mutate(page)
    with pytest.raises(ValidationError):
        PageSpec.model_validate(page)


def test_returning_to_a_loaded_tab_leaves_nothing_pending():
    """Re-showing a tab whose run is cached must not mark it running forever."""
    from src.tui_pages.page import PageView
    calls = []

    async def exercise():
        app = _network_app(calls)
        async with app.run_test(size=(170, 50)) as pilot:
            await pilot.pause(0.2)
            await app.workers.wait_for_complete()
            page = app.query_one(PageView)
            page.show_tab("listening")                              # already loaded
            await pilot.pause(0.2)
            assert page.pending == set()
            assert not page.query("#page-notices .progress")

    asyncio.run(exercise())
