"""PageView: the page frame (plan §4.1) for one manifest page.

Lays out header → notice → strip → workspace (main/aside, or a card grid) →
action line, mounts every slot empty, then executes the page's ``on_open``
runs in a thread worker. As each run finishes, only the slots bound to it
re-render. Actions on mutating commands are previewed (Phase 1); manual read
runs (e.g. ``scan quick``) execute and then re-run their ``refreshes``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import jmespath
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Label, Static

from src.tui_manifest import CommandSpec, PageSpec, SlotSpec, TemplateSpec
from src.tui_pages.components import (
    COMPONENTS, ActionRequested, FindingList, PageContext, RecordInspector, RowSelected,
    SeverityFilter, SlotComponent,
)
from src.tui_pages.runtime import Executor, RunResult, RunScheduler, preview_command


class RunStarted(Message):
    def __init__(self, page_id: str, run_id: str, line: str) -> None:
        super().__init__()
        self.page_id, self.run_id, self.line = page_id, run_id, line


class RunFinished(Message):
    def __init__(self, page_id: str, result: RunResult) -> None:
        super().__init__()
        self.page_id, self.result = page_id, result


class ActionPreviewed(Message):
    def __init__(self, page_id: str, line: str) -> None:
        super().__init__()
        self.page_id, self.line = page_id, line


class PageView(VerticalScroll):
    """One manifest page. ``executor`` decides live vs replay execution."""

    def __init__(self, page: PageSpec, commands: Dict[str, CommandSpec], template: TemplateSpec,
                 labels: Dict[str, Dict[str, str]], executor: Executor, **kw: Any) -> None:
        super().__init__(id=kw.pop("id", f"page-{page.page.id.replace('.', '-')}"), classes="manifest-page", **kw)
        self.page, self.template = page, template
        self.ctx = PageContext(page, commands, labels)
        self.scheduler = RunScheduler(page, commands, executor)
        self.slots: Dict[str, SlotComponent] = {}
        self.pending: set = set()
        # Set by the shell to execute actions (confirm → run → refreshes).
        # Without one, actions are previewed only.
        self.action_handler: Optional[Callable[["PageView", str, CommandSpec, Dict[str, Any]], None]] = None

    # -- layout --------------------------------------------------------

    def _component(self, slot: SlotSpec) -> SlotComponent:
        cls = COMPONENTS.get(slot.component)
        if cls is None:
            raise KeyError(f"{self.page.page.id}: component {slot.component} is not implemented yet")
        widget = cls(slot, self.ctx)
        self.slots[widget.slot_key] = widget
        return widget

    def compose(self) -> ComposeResult:
        meta = self.page.page
        with Horizontal(classes="page-header"):
            yield Label(meta.title, classes="page-title")
            yield Label(self.ctx.labels["concerns"].get(meta.concern, meta.concern).upper(), classes="page-meta", id="page-meta")
            for run_id in self.scheduler.manual_runs():
                command = self.scheduler.command(run_id)
                yield Button(self.page_props_label(run_id, command), id=f"run-{run_id}", classes="header-action")
            yield Button("Refresh", id="page-refresh", classes="header-action")
        yield Vertical(id="page-notices")
        by_region: Dict[str, List[SlotSpec]] = {}
        for slot in self.page.slots:
            by_region.setdefault(slot.region, []).append(slot)
        for slot in by_region.get("notice", []):
            yield self._component(slot)
        if by_region.get("strip"):
            with Horizontal(classes="strip-region"):
                for slot in by_region["strip"]:
                    yield self._component(slot)
        if self.template.layout == "grid":
            with Vertical(classes="workspace grid"):
                for slot in by_region.get("workspace.main", []):
                    yield self._component(slot)
        else:
            with Horizontal(classes="workspace split"):
                with Vertical(classes="main"):
                    for slot in by_region.get("workspace.main", []):
                        yield self._component(slot)
                if by_region.get("workspace.aside"):
                    with Vertical(classes="aside"):
                        for slot in by_region["workspace.aside"]:
                            yield self._component(slot)
        preview = Static("", id="action-preview", classes="preview")
        preview.display = False
        yield preview

    def page_props_label(self, run_id: str, command: CommandSpec) -> str:
        return f"Run {' '.join(command.argv)}" + (" ⏱" if command.long_running else "")

    # -- runs ----------------------------------------------------------

    def on_mount(self) -> None:
        self.start(self.scheduler.triggered("on_open"))

    def start(self, run_ids: List[str], *, force: bool = False) -> None:
        if not run_ids:
            return
        self.pending.update(run_ids)
        self._show_progress()

        def work() -> None:
            self.scheduler.execute(
                run_ids, force=force,
                on_start=lambda rid: self.app.call_from_thread(self._started, rid),
                on_result=lambda result: self.app.call_from_thread(self._deliver, result),
            )

        self.run_worker(work, thread=True, group=f"runs-{self.page.page.id}", exit_on_error=False)

    def _started(self, run_id: str) -> None:
        line = "msp " + " ".join(self.scheduler.command(run_id).argv)
        self.post_message(RunStarted(self.page.page.id, run_id, line))

    def _render_run(self, result: RunResult) -> None:
        for slot in self.page.slots:
            if slot.run != result.run_id:
                continue
            widget = self.slots[f"{slot.region}#{slot.order}"]
            widget.set_data(None if result.failure else self._project(slot, result), result.failure)

    def rerender(self) -> None:
        """Redraw every slot from cached results (e.g. undo a cancelled toggle)."""
        for result in self.scheduler.results.values():
            self._render_run(result)

    def _deliver(self, result: RunResult) -> None:
        self.pending.discard(result.run_id)
        self._render_run(result)
        self._show_progress()
        self._show_source()
        self.post_message(RunFinished(self.page.page.id, result))
        targets = [r for r in self.scheduler.refresh_targets(result.run_id) if self.scheduler.command(r).risk == "read"]
        if targets and self.scheduler.runs[result.run_id].trigger == "manual" and not result.failure:
            self.start(targets, force=True)

    @staticmethod
    def _project(slot: SlotSpec, result: RunResult) -> Any:
        if slot.facet:
            return result.errors
        return jmespath.search(slot.select, result.data) if slot.select else result.data

    def _show_progress(self) -> None:
        notices = self.query_one("#page-notices", Vertical)
        notices.remove_children()
        failures = [r for r in self.scheduler.results.values() if r.failure and r.run_id not in self.pending]
        lines = [Static(f"✗ msp {' '.join(r.command.argv)}: {r.failure}", classes="notice") for r in failures]
        if self.pending:
            running = ", ".join("msp " + " ".join(self.scheduler.command(r).argv) for r in sorted(self.pending))
            lines.append(Static(f"⟳ running {running}", classes="progress"))
        if lines:
            notices.mount(*lines)

    def _show_source(self) -> None:
        sources = sorted({r.source for r in self.scheduler.results.values() if not r.failure})
        concern = self.ctx.labels["concerns"].get(self.page.page.concern, self.page.page.concern).upper()
        suffix = " · replayed fixtures" if sources == ["replay"] else ""
        self.query_one("#page-meta", Label).update(concern + suffix)

    def refresh_page(self) -> None:
        shown = list(dict.fromkeys(self.scheduler.triggered("on_open") + list(self.scheduler.results)))
        self.start(shown, force=True)

    # -- interaction ---------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "page-refresh":
            event.stop()
            self.refresh_page()
        elif button_id.startswith("run-"):
            event.stop()
            self.start([button_id.removeprefix("run-")], force=True)

    def on_row_selected(self, message: RowSelected) -> None:
        message.stop()
        for widget in self.slots.values():
            if isinstance(widget, RecordInspector) and widget.slot.follows == message.slot_key:
                widget.show(message.row)

    def on_severity_filter(self, message: SeverityFilter) -> None:
        message.stop()
        target = self.slots.get(message.target)
        if isinstance(target, FindingList):
            target.filter(message.severity)

    def on_action_requested(self, message: ActionRequested) -> None:
        message.stop()
        command = self.ctx.command_for(message.run_id)
        if command is None:
            return
        if self.action_handler is not None:
            self.action_handler(self, message.run_id, command, message.args)
            return
        line = preview_command(command, message.args)
        badge = " · needs administrator password" if command.needs_root else ""
        preview = self.query_one("#action-preview", Static)
        preview.update(f"Would run (preview only, nothing executed{badge}):  {line}")
        preview.display = True
        self.post_message(ActionPreviewed(self.page.page.id, line))


PAGE_CSS = """
.manifest-page { padding: 0 1; height: 1fr; }
.page-header { height: 3; align: left middle; }
.page-title { text-style: bold; color: #F0F6FC; width: 1fr; }
.page-meta { color: #8B949E; margin-right: 2; }
.header-action { height: 3; margin-left: 1; }
#page-notices { height: auto; }
.notice { background: #2D1416; color: #F85149; padding: 0 1; margin-bottom: 1; height: auto; }
.progress { background: #161B22; color: #58A6FF; padding: 0 1; margin-bottom: 1; height: auto; }
.strip-region { height: auto; margin-bottom: 1; }
.strip-region > .slot { width: auto; margin-right: 1; }
.strip { height: 3; width: auto; }
.pill { border: solid #30363D; background: #161B22; width: auto; height: 3; padding: 0 1; margin-right: 1; }
.pill-label { color: #8B949E; text-style: bold; margin-right: 2; }
.state-on { color: #3FB950; text-style: bold; }
.state-off { color: #F85149; text-style: bold; }
.state-unknown { color: #8B949E; }
.kpi { border: solid #30363D; background: #161B22; width: auto; min-width: 18; height: 4; padding: 0 1; margin-right: 1; }
.kpi-value { color: #F0F6FC; text-style: bold; }
.chip { height: 3; min-width: 8; margin-right: 1; }
.chip.-active { border: solid #58A6FF; color: #58A6FF; }
.slot { height: auto; }
.panel { border: solid #30363D; background: #161B22; padding: 0 1; height: auto; margin-bottom: 1; }
.workspace { height: auto; }
.workspace.grid { layout: grid; grid-size: 2; grid-columns: 2fr 1fr; grid-gutter: 0 1; height: auto; }
.workspace.grid .span-2 { column-span: 2; }
.workspace.split .main { width: 2fr; height: auto; }
.workspace.split .aside { width: 1fr; height: auto; margin-left: 1; }
.slot-heading { height: auto; margin-bottom: 1; }
.slot-heading .eyebrow { width: 1fr; }
.eyebrow { color: #8B949E; text-style: bold; }
.empty-note { color: #8B949E; height: auto; }
.link { height: 1; min-width: 10; border: none; background: transparent; color: #58A6FF; }
.toggle-row { height: auto; min-height: 3; }
.toggle-text { width: 1fr; height: auto; padding-top: 1; }
.toggle-detail { color: #8B949E; }
.toggle-unknown { padding-top: 1; }
.slot DataTable { height: auto; max-height: 18; border: none; }
.inspector-body { color: #C9D1D9; margin: 1 0; }
.row-actions { height: 3; }
.row-actions Button { margin-right: 1; min-width: 10; }
.form-submit { margin-top: 1; }
.slot Input, .slot Select { margin-top: 1; }
.preview { color: #58A6FF; background: #161B22; height: auto; padding: 0 1; }
"""
