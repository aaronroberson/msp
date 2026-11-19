"""Page components (plan §4.1). Generic: everything page-specific comes from
the slot's ``props`` and from ``labels.toml``, never from code.

Every slot component subclasses ``SlotComponent`` and is constructed empty
(loading); ``PageView`` calls ``set_data`` when its run finishes, so slow runs
never block the page and each run's result fills every slot bound to it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import jmespath
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, OptionList, Static, Switch
from textual.widgets.option_list import Option

from src.tui_manifest import CommandSpec, PageSpec, RunSpec, SlotSpec

SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")
SEVERITY_STYLE = {
    "critical": "bold #FF7B72", "high": "bold #F85149", "medium": "bold #D29922",
    "low": "#58A6FF", "info": "#8B949E",
}

# ------------------------------------------------------------------ context


@dataclass
class PageContext:
    """What components may consult: the page, commands and display labels."""

    page: PageSpec
    commands: Dict[str, CommandSpec]
    labels: Dict[str, Dict[str, str]]
    runs: Dict[str, RunSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.runs = {run.id: run for run in self.page.runs}

    def field_label(self, key: str, slot: Optional[SlotSpec] = None) -> str:
        override = (slot.props.get("labels", {}) if slot else {}).get(key)
        return override or self.labels["fields"].get(key) or key.replace("_", " ").capitalize()

    def value_label(self, value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "On" if value else "Off"
        return self.labels["values"].get(str(value), str(value))

    def command_for(self, run_id: str) -> Optional[CommandSpec]:
        run = self.runs.get(run_id)
        return self.commands.get(run.command) if run else None


_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def fill_args(template: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve ``{row.path}`` / ``{key}`` / ``{state}`` placeholders against ``scope``."""

    def lookup(path: str) -> Any:
        value: Any = scope
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        return value

    filled: Dict[str, Any] = {}
    for name, raw in template.items():
        if isinstance(raw, str):
            whole = _PLACEHOLDER.fullmatch(raw)
            filled[name] = lookup(whole.group(1)) if whole else _PLACEHOLDER.sub(lambda m: str(lookup(m.group(1)) or ""), raw)
        else:
            filled[name] = raw
    return filled


def choice_allows(command: Optional[CommandSpec], args: Dict[str, Any]) -> bool:
    """False when an argument value is outside the command's declared choices."""
    if command is None:
        return False
    for spec in command.args:
        value = args.get(spec.name)
        if spec.choices and value is not None and str(value) not in spec.choices:
            return False
        if spec.required and value in (None, ""):
            return False
    return True


# ----------------------------------------------------------------- messages


class ActionRequested(Message):
    """A component asks to run an action (``run_id``) with these args."""

    def __init__(self, run_id: str, args: Dict[str, Any]) -> None:
        super().__init__()
        self.run_id, self.args = run_id, args


class RowSelected(Message):
    def __init__(self, slot_key: str, row: Dict[str, Any]) -> None:
        super().__init__()
        self.slot_key, self.row = slot_key, row


class OpenPage(Message):
    def __init__(self, page_id: str) -> None:
        super().__init__()
        self.page_id = page_id


class SeverityFilter(Message):
    def __init__(self, target: str, severity: Optional[str]) -> None:
        super().__init__()
        self.target, self.severity = target, severity


# ------------------------------------------------------------- base classes


class SlotComponent(Vertical):
    """A component bound to one slot. ``data`` is the slot's projected value."""

    PANEL = True

    def __init__(self, slot: SlotSpec, ctx: PageContext, **kw: Any) -> None:
        classes = " ".join(filter(None, ["slot", "panel" if self.PANEL else "", kw.pop("classes", "")]))
        super().__init__(classes=classes, **kw)
        self.slot, self.ctx = slot, ctx
        self.slot_key = f"{slot.region}#{slot.order}"
        self.data: Any = None
        self.loaded = False
        self.failure: Optional[str] = None
        self.busy = False
        if slot.props.get("span") == 2:
            self.add_class("span-2")

    @property
    def title(self) -> str:
        return str(self.slot.props.get("title", "")).upper()

    def set_data(self, data: Any, failure: Optional[str] = None) -> None:
        self.data, self.failure, self.loaded = data, failure, True
        self.refresh(recompose=True)

    def set_busy(self, busy: bool) -> None:
        """Show that newer data is on its way (the shown data stays until it lands)."""
        if busy != self.busy:
            self.busy = busy
            self.refresh(recompose=True)

    def heading(self, summary: str = "") -> ComposeResult:
        link = self.slot.props.get("link")
        if not (self.title or link or self.busy):
            return
        with Horizontal(classes="slot-heading"):
            yield Label(" ".join(filter(None, [self.title, summary])), classes="eyebrow")
            if self.busy:
                yield Label(str(self.slot.props.get("busy_label", "⟳ updating…")), classes="busy")
            if link:
                yield Button(f"{self.slot.props.get('link_label', 'View all')} →", id=f"link-{self._dom_key()}",
                             classes="quiet-action link", name=link)

    def placeholder(self) -> Optional[Widget]:
        if self.failure:
            return Static(f"Unavailable: {self.failure}", classes="empty-note")
        if not self.loaded:
            return Static("Loading…", classes="empty-note")
        return None

    def _dom_key(self) -> str:
        return self.slot_key.replace(".", "-").replace("#", "-")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("link") and event.button.name:
            event.stop()
            self.post_message(OpenPage(event.button.name))


# --------------------------------------------------------------- notice


class NoticeBanner(SlotComponent):
    PANEL = False

    def compose(self) -> ComposeResult:
        errors = self.data or []
        self.display = bool(errors)
        if errors:
            text = "\n".join(f"⚠ {e.get('error') or e.get('message') or json.dumps(e)}" for e in errors)
            yield Static(text, classes="notice")


# ---------------------------------------------------------------- strip


class StatusStrip(SlotComponent):
    PANEL = False

    def __init__(self, slot: SlotSpec, ctx: PageContext, **kw: Any) -> None:
        super().__init__(slot, ctx, classes="status-strip", **kw)

    def compose(self) -> ComposeResult:
        # one row of content-sized pills; props.columns wraps them onto an even grid
        columns = self.slot.props.get("columns")
        strip = Horizontal(classes="strip grid-strip" if columns else "strip")
        if columns:
            self.add_class("wraps")
            strip.styles.grid_size_columns = int(columns)
        with strip:
            if not self.loaded or self.failure:
                yield Label("…" if not self.failure else "status unavailable", classes="pill-label")
                return
            for key, value in (self.data or {}).items():
                state = "on" if value is True else "off" if value is False else "unknown"
                with Horizontal(classes="pill"):
                    yield Label(self.ctx.field_label(key, self.slot).upper(), classes="pill-label")
                    yield Label({"on": "ON", "off": "OFF"}.get(state, self.ctx.value_label(value) if not isinstance(value, bool) else "—"),
                                classes=f"pill-state state-{state}")


class KPICell(SlotComponent):
    PANEL = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="pill kpi"):
            yield Label(self.title or "", classes="pill-label")
            value = "…" if not self.loaded else "—" if self.failure or self.data is None else str(self.data)
            yield Label(value, classes="kpi-value")


class SeverityChips(SlotComponent):
    PANEL = False

    def compose(self) -> ComposeResult:
        counts = {level: 0 for level in SEVERITY_ORDER}
        for row in self.data or []:
            level = str(row.get("severity", "info")).lower()
            counts[level] = counts.get(level, 0) + 1
        with Horizontal(classes="chips"):
            yield Button(f"All {sum(counts.values())}", name="", classes="chip -active")
            for level in SEVERITY_ORDER:
                if counts.get(level):
                    yield Button(f"{level.capitalize()} {counts[level]}", name=level, classes=f"chip sev-{level}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not event.button.has_class("chip"):
            return
        event.stop()
        for chip in self.query(".chip"):
            chip.set_class(chip is event.button, "-active")
        self.post_message(SeverityFilter(str(self.slot.props.get("filters", "")), event.button.name or None))


# ------------------------------------------------------------------ main


class SettingsPanel(SlotComponent):
    """Toggles from an item of booleans, or from a collection of records with
    an on/off state (``props.key``/``props.state``/``props.on_value``).

    ``props.on`` / ``props.off`` = ``{ run = "...", args = {...} }`` name the
    action to request; ``{key}`` and ``{state}`` (on/off) fill its args. A
    switch is disabled when the resulting args fall outside the command's
    declared choices, so the UI never offers what the CLI would reject.
    """

    def _items(self) -> List[Tuple[str, Optional[bool], str]]:
        props = self.slot.props
        if isinstance(self.data, dict):
            return [(k, v if isinstance(v, bool) else None, "") for k, v in self.data.items()]
        key, state, on_value = props.get("key", "name"), props.get("state", "state"), props.get("on_value", "enabled")
        detail = props.get("detail")
        rows = []
        for row in self.data or []:
            raw = row.get(state)
            value = raw if isinstance(raw, bool) else None if raw in (None, "unknown") else raw == on_value
            rows.append((str(row.get(key)), value, str(row.get(detail, "")) if detail else ""))
        return rows

    def _action(self, key: str, value: bool) -> Tuple[Optional[str], Dict[str, Any], bool]:
        spec = self.slot.props.get("on" if value else "off")
        if not isinstance(spec, dict):
            return None, {}, False
        args = fill_args(spec.get("args", {}), {"key": key, "state": "on" if value else "off"})
        return spec["run"], args, choice_allows(self.ctx.command_for(spec["run"]), args)

    def compose(self) -> ComposeResult:
        yield from self.heading()
        placeholder = self.placeholder()
        if placeholder:
            yield placeholder
            return
        for index, (key, value, detail) in enumerate(self._items()):
            with Horizontal(classes="toggle-row"):
                with Vertical(classes="toggle-text"):
                    yield Label(self.ctx.field_label(key, self.slot) if isinstance(self.data, dict) else key, classes="toggle-label")
                    if detail:
                        yield Label(detail, classes="toggle-detail")
                if value is None:
                    yield Label("Unknown", classes="state-unknown toggle-unknown")
                    continue
                _, _, allowed = self._action(key, not value)
                yield Switch(value=value, name=key, id=f"toggle-{self._dom_key()}-{index}", disabled=not allowed,
                             tooltip=None if allowed else "The CLI has no command to change this setting")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        event.stop()
        run_id, args, allowed = self._action(event.switch.name or "", event.value)
        if run_id and allowed:
            self.post_message(ActionRequested(run_id, args))


def _sort_rows(rows: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    for key in reversed(keys):
        desc = key.startswith("-")
        name = key.lstrip("-")
        rows = sorted(rows, key=lambda r: (r.get(name) is None, str(r.get(name, "")).lower()), reverse=desc)
    return rows


class RecordTable(SlotComponent):
    """Rows of records. props: title, columns, sort_by, limit, count_by, link, filter."""

    def _rows(self) -> List[Dict[str, Any]]:
        rows = [r for r in (self.data or []) if isinstance(r, dict)] if isinstance(self.data, list) else \
            [self.data] if isinstance(self.data, dict) else []
        return _sort_rows(rows, list(self.slot.props.get("sort_by", [])))

    def _summary(self, rows: List[Dict[str, Any]]) -> str:
        count_by = self.slot.props.get("count_by")
        if not count_by:
            return f" {len(rows)}" if self.loaded and not self.failure else ""
        counts: Dict[str, int] = {}
        for row in rows:
            counts[str(row.get(count_by, ""))] = counts.get(str(row.get(count_by, "")), 0) + 1
        return " · ".join(f"{n} {self.ctx.value_label(k).lower()}" for k, n in counts.items())

    def compose(self) -> ComposeResult:
        rows = self._rows()
        yield from self.heading(self._summary(rows))
        placeholder = self.placeholder()
        if placeholder:
            yield placeholder
            return
        if not rows:
            yield Static(self.slot.props.get("empty", "No records returned"), classes="empty-note")
            return
        limit = self.slot.props.get("limit")
        self._shown = rows[:limit] if limit else rows
        columns = list(self.slot.props.get("columns") or list(rows[0]))
        table = DataTable(cursor_type="row", zebra_stripes=True, id=f"table-{self._dom_key()}")
        for column in columns:
            table.add_column(self.ctx.field_label(column, self.slot).upper() if self.slot.props.get("compact") else self.ctx.field_label(column, self.slot), key=column)
        for index, row in enumerate(self._shown):
            table.add_row(*[_cell(self.ctx, row.get(c)) for c in columns], key=str(index))
        if self.slot.props.get("height"):
            table.styles.height = int(self.slot.props["height"])
        yield table

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None and event.row_key.value is not None:
            event.stop()
            self.post_message(RowSelected(self.slot_key, self._shown[int(event.row_key.value)]))


def _cell(ctx: PageContext, value: Any, width: int = 60) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value)
    text = ctx.value_label(value) if value is None or isinstance(value, (bool, str)) else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


class FindingList(SlotComponent):
    """Findings sorted by severity. props: title, limit, columns (after severity), link."""

    severity: Optional[str] = None

    def _rows(self) -> List[Dict[str, Any]]:
        rows = [r for r in (self.data or []) if isinstance(r, dict)]
        rank = {level: i for i, level in enumerate(SEVERITY_ORDER)}
        rows = sorted(rows, key=lambda r: rank.get(str(r.get("severity", "")).lower(), len(rank)))
        if self.severity:
            rows = [r for r in rows if str(r.get("severity", "")).lower() == self.severity]
        return rows

    def compose(self) -> ComposeResult:
        rows = self._rows()
        yield from self.heading(f"{len(rows)}" if self.loaded and not self.failure else "")
        placeholder = self.placeholder()
        if placeholder:
            yield placeholder
            return
        if not rows:
            yield Static(self.slot.props.get("empty", "No findings"), classes="empty-note")
            return
        limit = self.slot.props.get("limit")
        self._shown = rows[:limit] if limit else rows
        columns = ["severity", *self.slot.props.get("columns", ["title", "category"])]
        table = DataTable(cursor_type="row", id=f"table-{self._dom_key()}")
        for column in columns:
            table.add_column(self.ctx.field_label(column, self.slot).upper(), key=column)
        for index, row in enumerate(self._shown):
            level = str(row.get("severity", "")).lower()
            cells: List[Any] = [Text(level.upper() or "—", style=SEVERITY_STYLE.get(level, "#8B949E"))]
            cells += [_cell(self.ctx, row.get(c), 50) for c in columns[1:]]
            table.add_row(*cells, key=str(index))
        yield table

    def filter(self, severity: Optional[str]) -> None:
        self.severity = severity
        self.refresh(recompose=True)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None and event.row_key.value is not None:
            event.stop()
            self.post_message(RowSelected(self.slot_key, self._shown[int(event.row_key.value)]))


class DefinitionCatalog(SlotComponent):
    """Named definitions (workflows, presets, providers). props: name, description."""

    def compose(self) -> ComposeResult:
        rows = [r for r in (self.data or []) if isinstance(r, dict)]
        yield from self.heading(f"{len(rows)}" if self.loaded and not self.failure else "")
        placeholder = self.placeholder()
        if placeholder:
            yield placeholder
            return
        name_key = self.slot.props.get("name", "name")
        desc_key = self.slot.props.get("description", "description")
        self._rows = rows
        yield OptionList(*[Option(Text.assemble((str(r.get(name_key, "")), "bold"), "\n", (str(r.get(desc_key, "") or ""), "#8B949E")), id=str(i))
                           for i, r in enumerate(rows)], id=f"catalog-{self._dom_key()}")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id is not None:
            event.stop()
            self.post_message(RowSelected(self.slot_key, self._rows[int(event.option.id)]))


# ----------------------------------------------------------------- aside


class RecordInspector(SlotComponent):
    """Shows the row selected in the slot it ``follows`` plus row actions.

    Row actions come from ``slot.row_actions``: one button per choice of the
    command argument named by ``props.choice`` (minus ``props.skip``), or one
    button per run. The run's ``args`` template fills ``{row.<field>}``.
    ``props.hide_when`` maps a button to a JMESPath test on the row.
    """

    def __init__(self, slot: SlotSpec, ctx: PageContext, **kw: Any) -> None:
        super().__init__(slot, ctx, **kw)
        self.row: Dict[str, Any] = {}
        self.loaded = True

    def _buttons(self) -> List[Tuple[str, str, Dict[str, Any], bool]]:
        """(label, run_id, extra args, danger) for every row action."""
        props = self.slot.props
        choice_name = props.get("choice")
        danger = set(props.get("danger", []))
        buttons = []
        for run_id in self.slot.row_actions:
            command = self.ctx.command_for(run_id)
            if command is None:
                continue
            spec = next((a for a in command.args if a.name == choice_name), None) if choice_name else None
            if spec and spec.choices:
                for choice in spec.choices:
                    if choice not in props.get("skip", []):
                        buttons.append((choice, run_id, {choice_name: choice}, choice in danger or command.risk == "dangerous"))
            else:
                buttons.append((props.get("labels", {}).get(run_id, command.id.split(".")[-1]), run_id, {}, command.risk == "dangerous"))
        return buttons

    def compose(self) -> ComposeResult:
        yield Label(self.title or "SELECTED", classes="eyebrow")
        fields = self.slot.props.get("fields")
        if not self.row:
            yield Static(self.slot.props.get("empty", "Select a row."), classes="inspector-body")
        else:
            keys = fields or [k for k, v in self.row.items() if not isinstance(v, (dict, list))]
            body = "\n".join(f"{self.ctx.field_label(k, self.slot):<12} {_cell(self.ctx, self.row.get(k), 200)}" for k in keys)
            yield Static(body, classes="inspector-body")
        buttons = self._buttons()
        if buttons:
            hide_when = self.slot.props.get("hide_when", {})
            with Horizontal(classes="row-actions"):
                for index, (label, run_id, extra, danger) in enumerate(buttons):
                    test = hide_when.get(label)
                    hidden = bool(self.row) and bool(test) and bool(jmespath.search(test, self.row))
                    button = Button(label.capitalize(), id=f"act-{run_id}-{label}", name=str(index),
                                    variant="error" if danger else "default", disabled=not self.row)
                    button.display = not hidden
                    yield button

    def show(self, row: Dict[str, Any]) -> None:
        self.row = row
        self.refresh(recompose=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not event.button.id or not event.button.id.startswith("act-") or not self.row:
            return
        event.stop()
        label, run_id, extra, _ = self._buttons()[int(event.button.name or 0)]
        run = self.ctx.runs[run_id]
        args = {**fill_args(run.args, {"row": self.row}), **extra}
        self.post_message(ActionRequested(run_id, args))


class ActionForm(SlotComponent):
    """Arguments for one action: ``slot.actions[0]``.

    props: title, fields (arg names to ask for; default: all without a fixed
    value), fixed (arg values set by the page, e.g. ``operation = "add"``),
    submit (button label), placeholders (per field).
    """

    def __init__(self, slot: SlotSpec, ctx: PageContext, **kw: Any) -> None:
        super().__init__(slot, ctx, **kw)
        self.loaded = True
        self.run_id = slot.actions[0] if slot.actions else ""

    def compose(self) -> ComposeResult:
        from textual.widgets import Select

        props = self.slot.props
        command = self.ctx.command_for(self.run_id)
        yield Label(self.title or "ACTION", classes="eyebrow")
        if command is None:
            yield Static("No action configured.", classes="empty-note")
            return
        fixed = props.get("fixed", {})
        wanted = props.get("fields") or [a.name for a in command.args if a.name not in fixed]
        placeholders = props.get("placeholders", {})
        for spec in command.args:
            if spec.name not in wanted:
                continue
            field_id = f"form-{self._dom_key()}-{spec.name}"
            if spec.choices:
                yield Select([(c, c) for c in spec.choices], id=field_id, prompt=self.ctx.field_label(spec.name, self.slot))
            else:
                yield Input(placeholder=placeholders.get(spec.name, self.ctx.field_label(spec.name, self.slot)), id=field_id)
        yield Button(props.get("submit", "Run"), id=f"submit-{self._dom_key()}", classes="form-submit",
                     variant="error" if command.risk == "dangerous" else "primary")
        yield Static("", classes="form-error empty-note")

    def values(self) -> Dict[str, Any]:
        from textual.widgets import Select

        command = self.ctx.command_for(self.run_id)
        args: Dict[str, Any] = dict(self.slot.props.get("fixed", {}))
        for spec in command.args if command else []:
            nodes = self.query(f"#form-{self._dom_key()}-{spec.name}")
            if not nodes:
                continue
            node = nodes.first()
            value = node.value if not isinstance(node, Select) else (None if node.value == Select.BLANK else node.value)
            if isinstance(value, str):
                value = value.strip()
            if value not in (None, ""):
                args[spec.name] = value
        return args

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not (event.button.id or "").startswith("submit-"):
            return
        event.stop()
        args = self.values()
        missing = [a.name for a in self.ctx.command_for(self.run_id).args if a.required and a.name not in args]
        error = self.query_one(".form-error", Static)
        if missing:
            error.update("Required: " + ", ".join(self.ctx.field_label(m, self.slot) for m in missing))
            return
        error.update("")
        self.post_message(ActionRequested(self.run_id, args))


COMPONENTS = {
    cls.__name__: cls
    for cls in (NoticeBanner, StatusStrip, KPICell, SeverityChips, SettingsPanel, RecordTable,
                FindingList, DefinitionCatalog, RecordInspector, ActionForm)
}
