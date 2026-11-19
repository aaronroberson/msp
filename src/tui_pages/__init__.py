"""Render manifest pages (src/tui_manifest/pages/*.toml) as Textual screens.

Phase 1 starting point (plan §4). A page lists runs and slots; this module:

1. executes each run's command once (live via the CLI, or replayed from its
   committed fixture) and validates the output against the command's contract;
2. projects each slot's data with its JMESPath ``select``;
3. renders the slot's component in its region, in composition order
   (header → notice → strip → workspace.main / workspace.aside → dock);
4. wires ``follows``: selecting a row in a main slot drives the aside.

Mutating actions are *previewed only* (the exact command is shown, nothing
runs); confirmation and askpass arrive in Phase 3.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import jmespath
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, Static, Switch

from src.schemas import validate_output
from src.tui_manifest import (
    REGION_ORDER, REPO, CommandSpec, PageSpec, SlotSpec, command_envelope,
)

# ---------------------------------------------------------------- run execution


@dataclass
class RunResult:
    run_id: str
    command: CommandSpec
    data: Any = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "live"          # live | replay
    failure: Optional[str] = None


def _first_json(text: str) -> Any:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char in "[{":
            try:
                return decoder.raw_decode(text[index:])[0]
            except json.JSONDecodeError:
                continue
    return None


def execute(run_id: str, command: CommandSpec, *, replay: bool, timeout: int = 120) -> RunResult:
    """Run a read command once and return its validated envelope data."""
    if replay:
        envelope, status = command_envelope(command)
        if envelope is None:
            return RunResult(run_id, command, source="replay", failure=f"no replayable fixture ({status})")
        dumped = envelope.model_dump(mode="json")
        return RunResult(run_id, command, dumped["data"], dumped.get("errors", []), source="replay")
    argv = [sys.executable, str(REPO / "src" / "main.py"), "--json", *command.argv]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, cwd=REPO)
    except subprocess.TimeoutExpired:
        return RunResult(run_id, command, failure=f"timed out after {timeout}s")
    raw = _first_json(proc.stdout)
    if raw is None and command.encoding in {"text", "lines", "exit"}:
        raw = proc.stdout
    try:
        envelope = validate_output(raw, command.emits, **command.normalize_kwargs(proc.returncode))
    except Exception as exc:  # contract violation: show it, never guess
        return RunResult(run_id, command, failure=f"output broke its contract: {str(exc).splitlines()[0]}")
    dumped = envelope.model_dump(mode="json")
    return RunResult(run_id, command, dumped["data"], dumped.get("errors", []))


def preview_command(command: CommandSpec, args: Dict[str, Any]) -> str:
    """The exact CLI line an action would run (shown instead of running it)."""
    tokens = ["msp", *command.argv]
    for spec in command.args:
        value = args.get(spec.name)
        if value in (None, "", False):
            continue
        if spec.option:
            tokens += [spec.option] if spec.kind == "flag" else [spec.option, str(value)]
        else:
            tokens.append(str(value))
    return " ".join(tokens)


# ------------------------------------------------------------------ components

LABELS = {
    "enabled": "Firewall", "stealth_mode": "Stealth mode", "block_all": "Block all incoming",
    "allows_signed": "Allow Apple-signed software", "allows_signed_app": "Allow downloaded signed apps",
}


def label_for(key: str) -> str:
    return LABELS.get(key, key.replace("_", " ").capitalize())


class ActionPreview(Message):
    def __init__(self, line: str) -> None:
        super().__init__()
        self.line = line


class RowSelected(Message):
    def __init__(self, slot_key: str, row: Dict[str, Any]) -> None:
        super().__init__()
        self.slot_key = slot_key
        self.row = row


class NoticeBanner(Static):
    def __init__(self, errors: List[Dict[str, Any]], **kw: Any) -> None:
        text = "\n".join(f"⚠ {e.get('error') or e.get('message') or json.dumps(e)}" for e in errors)
        super().__init__(text, classes="notice", **kw)
        self.display = bool(errors)


class StatusStrip(Horizontal):
    def __init__(self, data: Dict[str, Any], **kw: Any) -> None:
        super().__init__(classes="strip", **kw)
        self._data = data

    def compose(self) -> ComposeResult:
        for key, value in self._data.items():
            state = "on" if value is True else "off" if value is False else "unknown"
            with Horizontal(classes="pill"):
                yield Label(label_for(key).upper(), classes="pill-label")
                yield Label({"on": "ON", "off": "OFF", "unknown": "—"}[state], classes=f"pill-state state-{state}")


class SettingsPanel(Vertical):
    def __init__(self, data: Dict[str, Any], action: Optional[CommandSpec], **kw: Any) -> None:
        super().__init__(classes="panel settings", **kw)
        self._data, self._action = data, action

    def compose(self) -> ComposeResult:
        yield Label("SETTINGS", classes="eyebrow")
        for key, value in self._data.items():
            with Horizontal(classes="toggle-row"):
                yield Label(label_for(key), classes="toggle-label")
                yield Switch(value=bool(value), id=f"toggle-{key}", disabled=self._action is None)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if self._action is None:
            return
        key = (event.switch.id or "").removeprefix("toggle-")
        line = preview_command(self._action, {"option": key, "value": "on" if event.value else "off"})
        self.post_message(ActionPreview(line))


class RecordTable(Vertical):
    def __init__(self, rows: List[Dict[str, Any]], columns: List[str], slot_key: str, **kw: Any) -> None:
        super().__init__(classes="panel table", **kw)
        self._rows, self._slot_key = rows, slot_key
        self._columns = columns or (list(rows[0]) if rows else [])

    def compose(self) -> ComposeResult:
        counts: Dict[str, int] = {}
        for row in self._rows:
            status = str(row.get("status", ""))
            counts[status] = counts.get(status, 0) + 1
        summary = " · ".join(f"{n} {k.lower() or 'other'}" for k, n in sorted(counts.items()))
        yield Label(f"APPLICATION RULES  {summary}", classes="eyebrow")
        table = DataTable(cursor_type="row", zebra_stripes=True)
        for column in self._columns:
            table.add_column(label_for(column), key=column)
        for index, row in enumerate(sorted(self._rows, key=lambda r: (r.get("status") != "ALLOW", str(r.get("name", "")).lower()))):
            table.add_row(*[str(row.get(c, "")) for c in self._columns], key=str(index))
        self._sorted = sorted(self._rows, key=lambda r: (r.get("status") != "ALLOW", str(r.get("name", "")).lower()))
        yield table

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None and event.row_key.value is not None:
            self.post_message(RowSelected(self._slot_key, self._sorted[int(event.row_key.value)]))


class RecordInspector(Vertical):
    def __init__(self, row_actions: List[CommandSpec], **kw: Any) -> None:
        super().__init__(classes="panel inspector", **kw)
        self._actions = row_actions
        self._row: Dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Label("SELECTED", classes="eyebrow")
        yield Static("Select a row.", id="inspector-body", classes="inspector-body")
        with Horizontal(classes="row-actions"):
            for command in self._actions:
                choices = next((a.choices for a in command.args if a.name == "operation"), [])
                for operation in choices or [""]:
                    if operation == "add":
                        continue  # 'add' takes a new path, not the selected row
                    yield Button(operation.capitalize() or command.id, id=f"act-{command.id}-{operation}".replace(".", "_"),
                                 variant="error" if operation in {"remove", "block"} else "default")

    # actions that make no sense for the selected row's current state
    HIDE_WHEN = {"block": {"BLOCK"}, "unblock": {"ALLOW"}}

    def show(self, row: Dict[str, Any]) -> None:
        self._row = row
        body = "\n".join(f"{label_for(k):<10} {v}" for k, v in row.items())
        self.query_one("#inspector-body", Static).update(body)
        status = str(row.get("status", ""))
        for button in self.query(Button):
            operation = (button.id or "").rsplit("-", 1)[-1]
            button.display = status not in self.HIDE_WHEN.get(operation, set())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self._row:
            return
        operation = (event.button.id or "").rsplit("-", 1)[-1]
        for command in self._actions:
            self.post_message(ActionPreview(preview_command(command, {"operation": operation, "path": self._row.get("path", "")})))


# ------------------------------------------------------------------- page view


class PageView(VerticalScroll):
    """Lays out a PageSpec's slots by region using the given run results."""

    def __init__(self, page: PageSpec, commands: Dict[str, CommandSpec], results: Dict[str, RunResult], **kw: Any) -> None:
        super().__init__(id="page", **kw)
        self.page, self.commands, self.results = page, commands, results
        self._inspectors: Dict[str, RecordInspector] = {}

    def _project(self, slot: SlotSpec) -> Any:
        result = self.results[slot.run] if slot.run else None
        if result is None or result.failure:
            return None
        if slot.facet:
            return result.errors
        return jmespath.search(slot.select, result.data) if slot.select else result.data

    def _action(self, run_id: str) -> Optional[CommandSpec]:
        run = next((r for r in self.page.runs if r.id == run_id), None)
        return self.commands.get(run.command) if run else None

    def _build(self, slot: SlotSpec) -> Widget:
        data = self._project(slot)
        slot_key = f"{slot.region}#{slot.order}"
        if slot.component == "NoticeBanner":
            return NoticeBanner(data or [])
        if slot.component == "StatusStrip":
            return StatusStrip(data or {})
        if slot.component == "SettingsPanel":
            return SettingsPanel(data or {}, self._action(slot.actions[0]) if slot.actions else None)
        if slot.component == "RecordTable":
            return RecordTable(data or [], slot.props.get("columns", []), slot_key)
        if slot.component == "RecordInspector":
            inspector = RecordInspector([c for c in (self._action(r) for r in slot.row_actions) if c])
            self._inspectors[slot.follows or ""] = inspector
            return inspector
        return Static(f"[{slot.component} not implemented in the prototype]")

    def compose(self) -> ComposeResult:
        failures = [r for r in self.results.values() if r.failure]
        sources = sorted({r.source for r in self.results.values() if not r.failure})
        with Horizontal(id="page-header"):
            yield Label(self.page.page.title, id="page-title")
            yield Label(f"{self.page.page.concern.upper()} · {' / '.join(sources) or 'no data'}", id="page-meta")
        for failure in failures:
            yield Static(f"✗ {failure.command.id}: {failure.failure}", classes="notice")
        by_region: Dict[str, List[SlotSpec]] = {region: [] for region in REGION_ORDER}
        for slot in self.page.slots:
            by_region[slot.region].append(slot)
        for region in ("header", "notice", "strip"):
            for slot in by_region[region]:
                yield self._build(slot)
        with Horizontal(id="workspace"):
            with Vertical(id="main"):
                for slot in by_region["workspace.main"]:
                    yield self._build(slot)
            if by_region["workspace.aside"]:
                with Vertical(id="aside"):
                    for slot in by_region["workspace.aside"]:
                        yield self._build(slot)
        yield Static("", id="action-preview", classes="preview")

    def on_row_selected(self, message: RowSelected) -> None:
        inspector = self._inspectors.get(message.slot_key)
        if inspector:
            inspector.show(message.row)

    def on_action_preview(self, message: ActionPreview) -> None:
        self.query_one("#action-preview", Static).update(f"Would run (preview only, nothing executed):  {message.line}")


PAGE_CSS = """
Screen { background: #0D1117; color: #C9D1D9; }
#page { padding: 0 1; }
#page-header { height: 2; }
#page-title { text-style: bold; color: #F0F6FC; width: 1fr; }
#page-meta { color: #8B949E; }
.notice { background: #2D1416; color: #F85149; padding: 0 1; margin-bottom: 1; height: auto; }
.strip { height: 3; margin-bottom: 1; }
.pill { border: solid #30363D; background: #161B22; width: auto; height: 3; padding: 0 1; margin-right: 1; }
.pill-label { color: #8B949E; text-style: bold; margin-right: 2; }
.state-on { color: #3FB950; text-style: bold; }
.state-off { color: #F85149; text-style: bold; }
.state-unknown { color: #8B949E; }
#workspace { height: auto; }
#main { width: 2fr; height: auto; }
#aside { width: 1fr; height: auto; margin-left: 1; }
.panel { border: solid #30363D; background: #161B22; padding: 0 1; height: auto; margin-bottom: 1; }
.eyebrow { color: #8B949E; text-style: bold; margin-bottom: 1; }
.toggle-row { height: 3; }
.toggle-label { width: 1fr; padding-top: 1; }
.table DataTable { height: 16; }
.inspector-body { color: #C9D1D9; margin-bottom: 1; }
.row-actions { height: 3; }
.row-actions Button { margin-right: 1; min-width: 10; }
.preview { dock: bottom; color: #58A6FF; background: #161B22; height: auto; padding: 0 1; }
"""
