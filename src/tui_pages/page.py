"""PageView: the page frame (plan §4.1) for one manifest page.

Lays out header → notice → strip → workspace (main/aside, or a card grid) →
action line, mounts every slot empty, then executes the page's ``on_open``
runs in a thread worker. As each run finishes, only the slots bound to it
re-render.

Triggers: ``on_open`` (page opens), ``on_view:<tab>`` (tab first shown),
``on_select:<slot>`` (row highlighted; ``{row.*}`` args), ``manual`` (header
button), ``on_action`` (button/form/toggle). Read actions execute directly;
reads that send traffic or data to an AI provider, and all mutations, go to
``action_handler`` (the shell confirms them) or are previewed without one.
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
    SeverityFilter, SlotComponent, fill_args,
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
        self.tab: Optional[str] = page.tabs[0].id if page.tabs else None
        self._select_timer: Any = None

    # -- layout --------------------------------------------------------

    def _component(self, slot: SlotSpec) -> SlotComponent:
        cls = COMPONENTS.get(slot.component)
        if cls is None:
            raise KeyError(f"{self.page.page.id}: component {slot.component} is not implemented yet")
        widget = cls(slot, self.ctx)
        run = self.ctx.runs.get(slot.run or "")
        if run and (run.trigger in ("manual", "on_action") or run.trigger.startswith("on_select:")):
            widget.idle_text = slot.props.get("empty", "Not run yet.")   # runs only when asked
        if run and run.id in self._slot_runs:
            widget.run_button = self._run_label(run.id)                  # run it from its own panel
        tab = self.page.slot_tab(slot)
        widget.display = tab is None or tab == self.tab
        self.slots[widget.slot_key] = widget
        return widget

    def compose(self) -> ComposeResult:
        meta = self.page.page
        with Horizontal(classes="page-header"):
            yield Label(meta.title, classes="page-title")
            yield Label(self._meta_text(), classes="page-meta" + (" fallback-badge" if meta.fallback else ""), id="page-meta")
            for run_id in self.scheduler.manual_runs():
                if run_id not in self._slot_runs:   # runs with a panel get their button there
                    yield Button(self._run_label(run_id, header=True), id=f"run-{run_id}", classes="header-action")
            yield Button("Refresh", id="page-refresh", classes="header-action")
        if self.page.tabs:
            with Horizontal(classes="view-tabs"):
                for tab in self.page.tabs:
                    yield Button(tab.title, id=f"tab-{tab.id}", classes="view-tab" + (" -active" if tab.id == self.tab else ""))
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

    @property
    def _slot_runs(self) -> set:
        """Manual runs whose output has a titled panel: the button lives in that panel."""
        manual = set(self.scheduler.manual_runs())
        return {s.run for s in self.page.slots if s.run in manual and s.props.get("title")}

    def _run_label(self, run_id: str, header: bool = False) -> str:
        # ⏱ slow · ↗ sends network traffic or data to an AI provider (asks first)
        command = self.scheduler.command(run_id)
        name = f"Run {' '.join(command.argv)}" if header else "Run"
        return name + (" ⏱" if command.long_running else "") + (" ↗" if self.scheduler.outbound(run_id) else "")

    # -- runs ----------------------------------------------------------

    def on_mount(self) -> None:
        self.start(self.scheduler.triggered("on_open") + self._tab_runs())

    def _run_tab(self, run_id: str) -> Optional[str]:
        slot = next((s for s in self.page.slots if s.run == run_id), None)
        return self.page.slot_tab(slot) if slot else None

    def _tab_runs(self) -> List[str]:
        return self.scheduler.triggered(f"on_view:{self.tab}") if self.tab else []

    def show_tab(self, tab_id: str) -> None:
        """Switch view tab: show its slots, run its reads the first time it is shown."""
        self.tab = tab_id
        for button in self.query(".view-tab"):
            button.set_class(button.id == f"tab-{tab_id}", "-active")
        for slot in self.page.slots:
            tab = self.page.slot_tab(slot)
            self.slots[f"{slot.region}#{slot.order}"].display = tab is None or tab == tab_id
        self.start(self._tab_runs())

    def start(self, run_ids: List[str], *, force: bool = False, args: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        # never duplicate an in-flight run; a cached run is only re-run when forced (the
        # scheduler skips it, so marking it pending would leave "running…" up forever)
        run_ids = [r for r in run_ids if r not in self.pending and (force or r not in self.scheduler.results)]
        if not run_ids:
            return
        self.pending.update(run_ids)
        self._show_progress()
        self._show_busy()

        def work() -> None:
            self.scheduler.execute(
                run_ids, force=force, args=args,
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
        self.post_message(RunFinished(self.page.page.id, result))
        # A read run that refreshes others (a scan rewrites the saved results
        # `doctor` reads) re-runs them; mutations' refreshes are the shell's job.
        targets = self.refreshable(result.run_id)
        if targets and self.scheduler.command(result.run_id).risk == "read" and not result.failure:
            self.start(targets, force=True)
        self._show_progress()
        self._show_source()
        self._show_busy()

    def refreshable(self, run_id: str) -> List[str]:
        """Reads to re-run after ``run_id``: its ``refreshes`` that are already on
        screen (never-shown tabs load when shown; outbound runs are never resent)."""
        return [r for r in self.scheduler.refresh_targets(run_id)
                if self.scheduler.command(r).risk == "read" and r in self.scheduler.results
                and not self.scheduler.outbound(r)]

    def _show_busy(self) -> None:
        """Mark slots whose data is being replaced: their own run is pending, or a
        pending run will refresh it (the findings card while a scan runs)."""
        for slot in self.page.slots:
            if not slot.run:
                continue
            refreshing = any(r in self.pending for r in self.scheduler.refreshed_by(slot.run))
            reloading = slot.run in self.pending and slot.run in self.scheduler.results  # first load shows "Loading…"
            self.slots[f"{slot.region}#{slot.order}"].set_busy(refreshing or reloading)

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
        self.query_one("#page-meta", Label).update(self._meta_text(sources == ["replay"]))

    def _meta_text(self, replayed: bool = False) -> str:
        if self.page.page.fallback:
            meta = "AUTO-GENERATED · NOT YET DESIGNED"
        else:
            meta = self.ctx.labels["concerns"].get(self.page.page.concern, self.page.page.concern).upper()
        return meta + (" · replayed fixtures" if replayed else "")

    def refresh_page(self, include_long: bool = True) -> None:
        """Re-run what the page shows. A revisit passes ``include_long=False`` so
        it does not repeat a slow run (a scan); Refresh and its button do."""
        executed = [r for r in self.scheduler.results
                    if not self.scheduler.outbound(r)          # never resend traffic or data unasked
                    and self._run_tab(r) in (None, self.tab)]  # other tabs refresh when shown
        shown = list(dict.fromkeys(self.scheduler.triggered("on_open") + self._tab_runs() + executed))
        if not include_long:
            shown = [r for r in shown if not self.scheduler.command(r).long_running]
        self.start(shown, force=True)

    # -- interaction ---------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "page-refresh":
            event.stop()
            self.refresh_page()
        elif button_id.startswith("tab-"):
            event.stop()
            self.show_tab(button_id.removeprefix("tab-"))
        elif button_id.startswith("run-"):
            event.stop()
            self.request(button_id.removeprefix("run-"), {})

    def on_row_selected(self, message: RowSelected) -> None:
        message.stop()
        for widget in self.slots.values():
            # follows one slot ("workspace.main#2") or every slot of a region ("workspace.main")
            if isinstance(widget, RecordInspector) and widget.slot.follows in (message.slot_key, message.slot_key.split("#")[0]):
                widget.show(message.row)
        runs = self.scheduler.triggered(f"on_select:{message.slot_key}")
        if not runs:
            return
        args = {r: fill_args(self.scheduler.runs[r].args, {"row": message.row}) for r in runs}
        if self._select_timer is not None:
            self._select_timer.stop()
        # debounce: moving the cursor quickly through a table runs only the last row
        self._select_timer = self.set_timer(0.25, lambda: self.start(runs, force=True, args=args))

    def on_severity_filter(self, message: SeverityFilter) -> None:
        message.stop()
        target = self.slots.get(message.target)
        if isinstance(target, FindingList):
            target.filter(message.severity)

    def on_action_requested(self, message: ActionRequested) -> None:
        message.stop()
        self.request(message.run_id, message.args)

    def request(self, run_id: str, args: Dict[str, Any]) -> None:
        """A button, form or toggle asked for ``run_id``. Plain reads run now;
        outbound reads and mutations are confirmed by the shell (or previewed)."""
        command = self.ctx.command_for(run_id)
        if command is None:
            return
        self._reveal(run_id)
        if command.risk == "read" and not self.scheduler.outbound(run_id):
            self.start([run_id], force=True, args={run_id: args})
            return
        self._confirm_or_preview(run_id, command, args)

    def _reveal(self, run_id: str) -> None:
        """A requested run whose output lives on another tab switches to that tab."""
        tab = self._run_tab(run_id)
        if tab and tab != self.tab:
            self.show_tab(tab)

    def _confirm_or_preview(self, run_id: str, command: CommandSpec, args: Dict[str, Any]) -> None:
        if self.action_handler is not None:
            self.action_handler(self, run_id, command, args)
            return
        line = preview_command(command, args)
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
.fallback-badge { color: #D29922; text-style: bold; }
.view-tabs { height: 1; margin-bottom: 1; border-bottom: none; }
.view-tab { height: 1; min-width: 0; width: auto; border: none; background: transparent; color: #8B949E; padding: 0 1; margin-right: 0; }
.view-tab:hover { background: #161B22; color: #F0F6FC; border: none; }
.view-tab:focus { border: none; text-style: underline; }
.view-tab.-active { background: #1F2B3A; color: #58A6FF; text-style: bold; border: none; }
.report-body { height: auto; }
.report-text { color: #C9D1D9; }
#page-notices { height: auto; }
.notice { background: #2D1416; color: #F85149; padding: 0 1; margin-bottom: 1; height: auto; }
.progress { background: #161B22; color: #58A6FF; padding: 0 1; margin-bottom: 1; height: auto; }
.strip-region { height: auto; margin-bottom: 1; }
.strip-region > .slot { width: auto; margin-right: 1; }
.strip-region > .slot.status-strip.wraps { width: 1fr; max-width: 100; }
.strip { height: 3; width: auto; }
.grid-strip { height: auto; width: 1fr; layout: grid; grid-gutter: 0 1; }
.pill { border: solid #30363D; background: #161B22; width: auto; height: 3; padding: 0 1; margin-right: 0; }
.grid-strip .pill { width: 1fr; margin-right: 0; }
.pill-label { color: #8B949E; text-style: bold; margin-right: 2; }
.state-on { color: #3FB950; text-style: bold; }
.state-off { color: #F85149; text-style: bold; }
.state-unknown { color: #8B949E; }
.kpi-value { color: #F0F6FC; text-style: bold; }
.chips { height: 3; width: auto; }
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
.busy { color: #58A6FF; width: auto; margin-right: 2; }
.eyebrow { color: #8B949E; text-style: bold; }
.empty-note { color: #8B949E; height: auto; }
.link { height: 1; min-width: 10; border: none; background: transparent; color: #58A6FF; }
.toggle-row { height: auto; min-height: 3; }
.toggle-text { width: 1fr; height: auto; padding-top: 1; }
.toggle-detail { color: #8B949E; }
.toggle-unknown { padding-top: 1; }
.slot DataTable { height: auto; max-height: 18; border: none; }
.inspector-body { color: #C9D1D9; margin: 1 0; }
.row-actions { height: auto; layout: grid; grid-size: 2; grid-gutter: 0 1; }
.slot-run { height: 1; min-width: 8; border: none; background: #1F2B3A; color: #58A6FF; margin-left: 1; }
.row-actions Button { width: 100%; min-width: 8; }
.form-submit { margin-top: 1; }
.slot Input, .slot Select { margin-top: 1; }
.preview { color: #58A6FF; background: #161B22; height: auto; padding: 0 1; }
"""
