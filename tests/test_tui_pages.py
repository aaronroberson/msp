"""Manifest page renderer (Phase 1 prototype): Security > Firewall in replay mode."""
import asyncio

import src.tui_pages as pages
from src.tui_pages.preview import PagePreviewApp
from textual.widgets import Button, DataTable, Static


def test_firewall_page_renders_from_one_run_and_only_previews_actions(monkeypatch):
    calls = []
    real_execute = pages.execute

    def counting_execute(run_id, command, **kw):
        calls.append(command.id)
        return real_execute(run_id, command, **kw)

    monkeypatch.setattr("src.tui_pages.preview.execute", counting_execute)
    ran = []
    monkeypatch.setattr("subprocess.run", lambda *a, **k: ran.append(a) or (_ for _ in ()).throw(AssertionError("no command may run")))

    async def exercise():
        app = PagePreviewApp("security.firewall", replay=True)
        async with app.run_test(size=(150, 44)) as pilot:
            await pilot.pause(0.2)
            # one `firewall status` run feeds strip, settings and table
            assert calls == ["firewall.status"]
            assert app.query_one(DataTable).row_count == 8
            app.query_one(DataTable).focus()
            await pilot.press("down")
            await pilot.pause(0.1)
            visible = {b.id for b in app.query(Button) if b.display}
            assert "act-firewall_app-block" not in visible  # the selected rule is already blocked
            await pilot.click("#act-firewall_app-unblock")
            await pilot.pause(0.1)
            preview = str(app.query_one("#action-preview", Static).render())
            assert "msp firewall app unblock" in preview and "nothing executed" in preview

    asyncio.run(exercise())
    assert ran == []
