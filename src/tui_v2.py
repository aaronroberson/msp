#!/usr/bin/env python3
"""
msp TUI v2 — terminal console for the macOS Security & Privacy CLI.

An opencode-style Textual client:

* compact numbered navigation for overview, findings, network, startup,
  permissions, privacy, and snapshots
* command palette (ctrl+p) to fuzzy-jump to any view or runnable CLI verb
* command runner (ctrl+r) that executes ``msp <verb> <args>`` as a subprocess
  and streams its output into a scrollable log

The engine stays the CLI; this module only drives it. Launch with ``msp tui``
(``msp tui --v1`` for the legacy dashboard).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Tuple, Union

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets.option_list import Option
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    OptionList,
    RichLog,
    Static,
)
from rich.text import Text

REPO_ROOT = Path(__file__).resolve().parent.parent


# Verbs that can change system state; the runner asks for confirmation first.
DANGEROUS_VERBS = frozenset({"remediate"})


def _requires_confirmation(tokens: list[str]) -> bool:
    """Identify CLI paths that can alter system or stored state."""
    if not tokens:
        return False
    command = tokens[0].lower()
    args = [token.lower() for token in tokens[1:]]
    if command in DANGEROUS_VERBS:
        return True
    if command in {"enable", "disable", "restore"}:
        return True
    if command == "net":
        return bool(args and args[0] in {"kill", "terminate"})
    if command == "startup":
        return bool(args and args[0] in {"disable", "enable", "remove", "add", "login-add", "login-remove", "agent-add", "agent-remove", "agent-enable", "agent-disable"})
    if command == "firewall":
        return bool(args and args[0] in {"set", "app"})
    if command == "preset":
        return bool(args and args[0] in {"apply", "restore", "delete"})
    if command == "workflow":
        return bool(args and args[0] not in {"list", "show", "help"})
    if command == "tune":
        return bool(args and args[0] in {"fix", "apply", "enable", "disable"})
    if command == "privacy_settings":
        return bool(args and args[0] in {"enable", "disable", "set", "apply", "preset"})
    if command == "config":
        return bool(args and args[0] == "set")
    if command == "snapshot":
        return bool(args and args[0] in {"restore", "delete", "capture"}) or "--auto-restore" in args
    if command == "security":
        return bool(args and args[0] in {"lock", "sleep", "computer-sleep", "set"})
    if command == "sharing":
        return bool(args and args[0] in {"enable", "disable", "disable-guest", "stop-all"})
    if command == "tcc":
        return bool(args and args[0] in {"reset", "revoke"})
    return False

# Catalog of runnable CLI verbs offered by the runner / palette.
RUNNABLES: list[dict[str, str]] = [
    {"verb": "scan quick --json", "title": "Run: scan quick", "desc": "Quick security scan (JSON)"},
    {"verb": "scan deep --json", "title": "Run: scan deep", "desc": "Deep security scan (JSON)"},
    {"verb": "interrogate", "title": "Run: interrogate", "desc": "Deep system fact gathering"},
    {"verb": "audit", "title": "Run: audit", "desc": "Best-practice audit rules"},
    {"verb": "net", "title": "Run: net", "desc": "Network connection audit"},
    {"verb": "net camsweep --json", "title": "Run: net camsweep", "desc": "Sweep LAN for hidden cameras"},
    {"verb": "tcc list --json", "title": "Run: tcc list", "desc": "TCC permission dump"},
    {"verb": "report", "title": "Run: report", "desc": "Generate a security report"},
    {"verb": "doctor", "title": "Run: doctor", "desc": "Dependency doctor"},
    {"verb": "net list", "title": "Run: net list", "desc": "Listening network ports"},
    {"verb": "startup managed --json", "title": "Run: startup managed", "desc": "Current-user Login Items and LaunchAgents"},
    {"verb": "startup login-items --json", "title": "Run: startup login-items", "desc": "Current-user Login Items"},
    {"verb": "fswatch recent 60", "title": "Run: fswatch recent", "desc": "Recent file events"},
    {"verb": "traffic summary", "title": "Run: traffic summary", "desc": "Network traffic summary"},
    {"verb": "snapshot list --json", "title": "Run: snapshot list", "desc": "Stored security snapshots"},
    {"verb": "sharing status", "title": "Run: sharing status", "desc": "File sharing status"},
    {"verb": "security status", "title": "Run: security status", "desc": "Security settings status"},
    {"verb": "workflow list", "title": "Run: workflow list", "desc": "Available workflows"},
    {"verb": "tune check", "title": "Run: tune check", "desc": "System diagnostics"},
    {"verb": "forensics", "title": "Run: forensics", "desc": "Forensics command help"},
    {"verb": "config list", "title": "Run: config list", "desc": "Current CLI configuration"},
    {"verb": "preset list", "title": "Run: preset list", "desc": "Available privacy presets"},
    {"verb": "tcc audit --json", "title": "Run: tcc audit", "desc": "High-risk TCC grants"},
    {"verb": "scan suspicious --json", "title": "Run: scan suspicious", "desc": "Heuristic suspicious activity scan"},
    {"verb": "deps status", "title": "Run: deps status", "desc": "Dependency status"},
    {"verb": "reason --help", "title": "Run: reason help", "desc": "Evidence reasoning options"},
    {"verb": "remediate plan --help", "title": "Run: remediate help", "desc": "Remediation planning options"},
    {"verb": "chain --help", "title": "Run: chain help", "desc": "Command chain options"},
    {"verb": "privacy_settings status", "title": "Run: privacy settings", "desc": "Privacy controls status"},
    {"verb": "firewall status", "title": "Run: firewall status", "desc": "Firewall settings and application rules"},
    {"verb": "firewall set enabled on", "title": "Enable firewall", "desc": "Turn on the macOS firewall"},
    {"verb": "firewall set enabled off", "title": "Disable firewall", "desc": "Turn off the macOS firewall"},
    {"verb": "firewall set stealth_mode on", "title": "Enable stealth mode", "desc": "Enable firewall stealth mode"},
    {"verb": "firewall set stealth_mode off", "title": "Disable stealth mode", "desc": "Disable firewall stealth mode"},
    {"verb": "firewall set block_all on", "title": "Block all incoming connections", "desc": "Enable block all in firewall"},
    {"verb": "firewall set block_all off", "title": "Allow firewall exceptions", "desc": "Disable block all in firewall"},
    {"verb": "firewall set allows_signed on", "title": "Allow signed software", "desc": "Allow Apple signed software"},
    {"verb": "firewall set allows_signed_app on", "title": "Allow downloaded signed apps", "desc": "Allow downloaded signed apps"},
    {"verb": "startup inventory", "title": "Run: startup inventory", "desc": "Inspect login items and launch agents"},
    {"verb": "ai --help", "title": "Run: ai help", "desc": "AI analysis options"},
]


# --------------------------------------------------------------------------
# CLI payload helpers
# --------------------------------------------------------------------------

def _cell(row: Any, key: str, default: str = "-") -> str:
    if isinstance(row, dict):
        value = row.get(key, default)
    else:
        value = getattr(row, key, default)
    if value is None:
        return default
    return str(value)


def _trunc(value: Any, width: int) -> str:
    text = str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


@dataclass(frozen=True)
class ViewSpec:
    id: str
    title: str
    columns: tuple[str, ...] = ()
    command: Optional[str] = None


VIEWS: list[ViewSpec] = [
    ViewSpec("dashboard", "Overview"),
    ViewSpec("runner", "Commands"),
    ViewSpec("findings", "Findings", ("severity", "category", "item", "description"), "scan quick --json"),
    ViewSpec("listening", "Listening sockets", ("process", "pid", "user", "protocol", "local", "state"), "net list --json"),
    ViewSpec("established", "Established connections", ("process", "pid", "user", "local", "remote"), "net established --json"),
    ViewSpec("startup", "Startup", ("label", "type", "path", "status"), "startup managed --json"),
    ViewSpec("tcc", "Permissions", ("service", "client", "auth", "source", "last_modified"), "tcc list --json"),
    ViewSpec("privacy", "Privacy", ("setting", "status", "details"), "status --json"),
    ViewSpec("firewall", "Firewall", ("setting", "value", "details"), "firewall status"),
    ViewSpec("snapshots", "Snapshots", ("name", "timestamp", "firewall", "gatekeeper", "filevault"), "snapshot list --json"),
]

NAV_VIEWS: tuple[str, ...] = (
    "dashboard", "findings", "listening", "startup", "tcc", "privacy", "snapshots"
)
DASHBOARD_COMMANDS: tuple[str, ...] = (
    "status --json", "net list --json", "net established --json", "startup managed --json", "scan quick --json"
)


def view_by_id(view_id: str) -> Optional[ViewSpec]:
    return next((view for view in VIEWS if view.id == view_id), None)


def _extract_json(lines: Iterable[str]) -> Any:
    """Find a JSON payload in CLI output that may include a human progress line."""
    text = "\n".join(lines)
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
            if isinstance(value, (dict, list)):
                return value
        except json.JSONDecodeError:
            continue
    return None


def _payload_rows(view_id: str, payload: Any) -> list[dict[str, Any]]:
    """Normalize real CLI JSON into the table columns for a view."""
    if view_id == "findings":
        values = payload if isinstance(payload, list) else payload.get("findings", []) if isinstance(payload, dict) else []
        return [{**row, "severity": str(row.get("severity", "")).upper()} for row in values if isinstance(row, dict)]
    if view_id in {"listening", "established"}:
        values = payload if isinstance(payload, list) else payload.get("connections", []) if isinstance(payload, dict) else []
        rows = []
        for item in values:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            local = row.get("local", row.get("local_addr"))
            if local is not None:
                row["local"] = local
                row["port"] = str(local).rsplit(":", 1)[-1]
            remote = row.get("remote", row.get("remote_addr"))
            if remote is not None:
                row["remote"] = remote
            rows.append(row)
        return rows
    if view_id == "startup":
        values = payload if isinstance(payload, list) else payload.get("items", []) if isinstance(payload, dict) else []
        return [dict(row) for row in values if isinstance(row, dict)]
    if view_id == "tcc":
        values = payload.get("permissions", []) if isinstance(payload, dict) else payload
        return [
            {
                **row,
                "service": row.get("service_name", row.get("service", "")),
                "client": row.get("client_name") or row.get("client", ""),
                "auth": row.get("auth_status", row.get("auth_value", row.get("authorization", ""))),
            }
            for row in values if isinstance(row, dict)
        ] if isinstance(values, list) else []
    if view_id == "privacy" and isinstance(payload, dict):
        rows = []
        for key in ("firewall", "gatekeeper", "filevault"):
            value = payload.get(key)
            if isinstance(value, dict):
                enabled = value.get("enabled")
                rows.append({
                    "setting": key.title(),
                    "status": "Enabled" if enabled is True else "Disabled" if enabled is False else "Unavailable",
                    "details": "\n".join(
                        f"• {name.replace('_', ' ').title()}: {detail}"
                        for name, detail in value.items()
                        if name != "enabled" and detail not in (None, "", [], {})
                    ),
                })
        return rows
    if view_id == "firewall" and isinstance(payload, dict):
        rows = [
            {"setting": name.replace("_", " ").title(), "value": "On" if value is True else "Off" if value is False else "Unavailable", "details": ""}
            for name, value in payload.items() if name in {"enabled", "stealth_mode", "block_all", "allows_signed", "allows_signed_app"}
        ]
        app_lines = payload.get("apps_output", "")
        if isinstance(app_lines, str):
            rows.extend({"setting": "Application", "value": "Rule", "details": line.strip()} for line in app_lines.splitlines() if line.strip() and not line.lower().startswith("total number"))
        return rows
    if view_id == "snapshots":
        values = payload if isinstance(payload, list) else payload.get("snapshots", []) if isinstance(payload, dict) else []
        rows = []
        for item in values:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
            for name in ("firewall", "gatekeeper", "filevault"):
                row[name] = settings.get(name, "")
            rows.append(row)
        return rows
    return []


# --------------------------------------------------------------------------
# Command broker: run `msp` verbs as a subprocess
# --------------------------------------------------------------------------

class CommandBroker:
    """Spawns ``python -m src.main <args…>`` and streams combined output."""

    def __init__(self, line: str) -> None:
        self.line = line.strip()
        self.proc: Optional[subprocess.Popen] = None

    def argv(self) -> list[str]:
        tokens = shlex.split(self.line)
        if tokens and Path(tokens[0]).name == "msp":
            tokens.pop(0)
        return [sys.executable, "-m", "src.main", *tokens]

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        parts = [str(REPO_ROOT), *[p for p in existing.split(os.pathsep) if p]]
        env["PYTHONPATH"] = os.pathsep.join(parts)
        return env

    def run(self) -> Iterator[Tuple[str, bool, Optional[int], float]]:
        """Yield ``(line, done, returncode, duration)`` while output streams."""
        started = time.monotonic()
        if not self.line:
            yield ("Empty command.", True, None, 0.0)
            return
        try:
            self.proc = subprocess.Popen(
                self.argv(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env=self.env(),
                cwd=str(REPO_ROOT),
            )
        except Exception as exc:  # pragma: no cover - defensive
            yield (f"Failed to spawn: {exc}", True, None, time.monotonic() - started)
            return
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        for raw in proc.stdout:
            yield (raw.rstrip("\n"), False, None, time.monotonic() - started)
        rc = proc.wait()
        duration = time.monotonic() - started
        yield (f"[exit {rc} · {duration:.1f}s]", True, rc, duration)

    def kill(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Panes
# --------------------------------------------------------------------------

class DashboardPane(Vertical):
    """Overview populated only from the commands shown in the runner."""

    def __init__(self) -> None:
        super().__init__(id="pane-dashboard")

    def compose(self) -> ComposeResult:
        yield Label("Overview", classes="screen-title")
        with Horizontal(id="security-cards", classes="dashboard-row"):
            for name in ("firewall", "gatekeeper", "filevault"):
                with Vertical(classes="security-card"):
                    with Horizontal(classes="card-heading"):
                        yield Label(name.upper(), classes="eyebrow")
                        yield Label("—", id=f"card-{name}-state", classes="state-pill")
                    yield Label("", id=f"card-{name}-details", classes="card-details")
                    yield Button("Inspect", id=f"inspect-{name}", classes="quiet-action")
        with Horizontal(id="overview-middle", classes="dashboard-row"):
            with Vertical(id="overview-sockets", classes="dashboard-panel wide-panel"):
                with Horizontal(classes="panel-heading"):
                    yield Label("TOP LISTENING SOCKETS", classes="eyebrow")
                    yield Button("View network →", id="card-listening", classes="quiet-action")
                yield DataTable(id="overview-listening", cursor_type="row")
                yield Label("", id="overview-listening-empty", classes="empty-note")
            with Vertical(id="overview-activity", classes="dashboard-panel narrow-panel"):
                yield Label("SYSTEM ACTIVITY", classes="eyebrow")
                yield Static("", id="activity-summary")
        with Horizontal(id="overview-lower", classes="dashboard-row"):
            with Vertical(id="overview-findings", classes="dashboard-panel wide-panel"):
                with Horizontal(classes="panel-heading"):
                    yield Label("RECENT FINDINGS", classes="eyebrow")
                    yield Button("Manage findings →", id="card-findings", classes="quiet-action")
                yield DataTable(id="overview-findings-table", cursor_type="row")
                yield Label("", id="overview-findings-empty", classes="empty-note")
            with Vertical(id="overview-startup", classes="dashboard-panel narrow-panel"):
                with Horizontal(classes="panel-heading"):
                    yield Label("STARTUP ITEMS", classes="eyebrow")
                    yield Button("View all →", id="card-startup", classes="quiet-action")
                yield Static("", id="startup-summary")
                yield DataTable(id="overview-startup-table", cursor_type="row")
                yield Label("", id="overview-startup-empty", classes="empty-note")
        yield Label("", id="overview-note")

    def on_mount(self) -> None:
        self.query_one("#overview-listening", DataTable).add_columns("PROTO", "BIND ADDRESS", "PROCESS", "PID")
        self.query_one("#overview-findings-table", DataTable).add_columns("SEV", "CATEGORY", "ITEM")
        self.query_one("#overview-startup-table", DataTable).add_columns("LABEL", "KIND", "STATUS")

    def show_data(self, results: dict[str, tuple[int, list[str]]]) -> None:
        status_payload = _extract_json(results.get("status --json", (1, []))[1])
        if not isinstance(status_payload, dict):
            self.query_one("#overview-note", Label).update("Status data is unavailable. See command output below.")
            return
        for name in ("firewall", "gatekeeper", "filevault"):
            item = status_payload.get(name)
            enabled = item.get("enabled") if isinstance(item, dict) else None
            value = "Enabled" if enabled is True else "Disabled" if enabled is False else "Unavailable"
            state_label = self.query_one(f"#card-{name}-state", Label)
            state_label.update(value.upper())
            state_label.set_class(enabled is True, "state-enabled")
            state_label.set_class(enabled is False, "state-disabled")
            state_label.set_class(enabled is None, "state-unavailable")
            details = []
            if isinstance(item, dict):
                for field, detail in item.items():
                    if field == "enabled" or detail in (None, "", [], {}):
                        continue
                    if isinstance(detail, bool):
                        detail = "On" if detail else "Off"
                    details.append(f"{field.replace('_', ' ').title()}: {detail}")
            self.query_one(f"#card-{name}-details", Label).update("\n".join(details[:3]))
        for table_id, command, view_id, columns, limit in (
            ("#overview-listening", "net list --json", "listening", ("protocol", "local", "process", "pid"), 5),
            ("#overview-findings-table", "scan quick --json", "findings", ("severity", "category", "item"), 3),
            ("#overview-startup-table", "startup managed --json", "startup", ("name", "type", "status"), 4),
        ):
            table = self.query_one(table_id, DataTable)
            table.clear()
            code, lines = results.get(command, (1, []))
            payload = _extract_json(lines)
            rows = _payload_rows(view_id, payload) if code == 0 else []
            for row in rows[:limit]:
                cells: list[Any] = [_trunc(_cell(row, column), 44) for column in columns]
                if view_id == "findings" and cells:
                    level = str(row.get("severity", "")).upper()
                    cells[0] = Text(cells[0], style={"HIGH": "bold #FF3B30", "WARN": "bold #FF9F0A", "WARNING": "bold #FF9F0A", "INFO": "#0A84FF"}.get(level, "#8E93A0"))
                table.add_row(*cells)
            note_id = {"listening": "#overview-listening-empty", "findings": "#overview-findings-empty", "startup": "#overview-startup-empty"}.get(view_id)
            if note_id:
                total_count = len(rows)
                self.query_one(note_id, Label).update("No records returned" if code == 0 and total_count == 0 else "Unavailable" if code != 0 else "")
        counts = []
        for command, label, view_id in (("net list --json", "Listening sockets", "listening"), ("net established --json", "Connections", "established"), ("startup managed --json", "Startup items", "startup")):
            code, lines = results.get(command, (1, []))
            payload = _extract_json(lines)
            rows = _payload_rows(view_id, payload) if code == 0 else []
            counts.append(f"{label}\n{len(rows) if code == 0 else 'Unavailable'}")
        self.query_one("#activity-summary", Static).update("\n\n".join(counts))
        startup_code, startup_lines = results.get("startup managed --json", (1, []))
        startup_payload = _extract_json(startup_lines)
        startup_rows = _payload_rows("startup", startup_payload) if startup_code == 0 else []
        self.query_one("#startup-summary", Static).update(f"{len(startup_rows)} items" if startup_code == 0 else "Unavailable")
        findings_code, findings_lines = results.get("scan quick --json", (1, []))
        self.query_one("#overview-note", Label).update("Live data" if findings_code == 0 and startup_code == 0 else "Some live data is unavailable. See command output below.")


class TablePane(Vertical):
    """Data table backed by one real CLI JSON command."""

    BINDINGS = [("/", "toggle_filter", "Filter"), ("r", "refresh", "Refresh"), ("enter", "open_detail", "Detail")]

    def __init__(self, spec: ViewSpec, app_ref: "MspTUI") -> None:
        super().__init__(id=f"pane-{spec.id}")
        self.spec = spec
        self._app_ref = app_ref
        self._all_rows: list[dict[str, Any]] = []
        self._filter_term = ""
        self._severity = "all"
        self._selected_row: Optional[dict[str, Any]] = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-toolbar"):
            title = "Network" if self.spec.id in {"listening", "established"} else self.spec.title
            yield Label(title, classes="screen-title")
            yield Button("Refresh", id="refresh-view")
        if self.spec.id in {"listening", "established"}:
            with Horizontal(id="network-tabs"):
                yield Button("Listening sockets", id="network-listening")
                yield Button("Established connections", id="network-established")
        if self.spec.id == "findings":
            with Horizontal(id="finding-filter-row"):
                yield Input(placeholder="Filter findings", id="filter-findings")
                for level in ("all", "high", "warn", "info"):
                    yield Button(level.title(), id=f"severity-{level}")
            with Horizontal(id="findings-layout"):
                yield DataTable(id="table-findings", cursor_type="row")
                with Vertical(id="finding-inspector", classes="dashboard-panel"):
                    yield Label("RECORD INSPECTION", classes="eyebrow")
                    yield Static("Select a finding to inspect its live details.", id="finding-detail", markup=False)
        elif self.spec.id in {"listening", "established", "startup"}:
            if self.spec.id == "startup":
                with Vertical(id="startup-intro", classes="dashboard-panel"):
                    yield Label("CURRENT USER STARTUP ITEMS", classes="eyebrow")
                    yield Static("Login Items and LaunchAgents", id="startup-inventory-summary", markup=False)
                with Horizontal(id="startup-add-form"):
                    yield Input(placeholder="App or executable path…", id="startup-path")
                    yield Input(placeholder="LaunchAgent label or Login Item name…", id="startup-name")
                    yield Button("Add Login Item", id="startup-login-add", variant="primary")
                    yield Button("Add LaunchAgent", id="startup-agent-add")
                    yield Button("Remove selected", id="startup-remove", variant="error")
                yield Input(placeholder="Filter items", id="filter-startup")
            with Horizontal(id="record-layout"):
                yield DataTable(id=f"table-{self.spec.id}", cursor_type="row")
                with Vertical(id="row-inspector", classes="dashboard-panel"):
                    yield Label("SELECTED ITEM", classes="eyebrow")
                    yield Static("Select a row to inspect available actions.", id="row-detail", markup=False)
                    with Horizontal(id="row-actions"):
                        if self.spec.id in {"listening", "established"}:
                            yield Button("Inspect process", id="inspect-process")
                            yield Button("Stop process", id="stop-process", variant="error")
                        elif self.spec.id == "startup":
                            yield Button("Disable item", id="disable-startup", variant="warning")
                            yield Button("Enable item", id="enable-startup")
        elif self.spec.id == "firewall":
            with Vertical(id="firewall-actions"):
                with Horizontal():
                    yield Button("Enable firewall", id="firewall-enable", variant="primary")
                    yield Button("Disable firewall", id="firewall-disable", variant="error")
                with Horizontal():
                    yield Button("Stealth on", id="firewall-stealth-on")
                    yield Button("Stealth off", id="firewall-stealth-off")
                    yield Button("Block all on", id="firewall-block-on")
                    yield Button("Block all off", id="firewall-block-off")
                with Horizontal():
                    yield Button("Signed software on", id="firewall-signed-on")
                    yield Button("Signed software off", id="firewall-signed-off")
                    yield Button("Downloaded apps on", id="firewall-signed-app-on")
                    yield Button("Downloaded apps off", id="firewall-signed-app-off")
            yield Input(placeholder="Application path…", id="firewall-app-path")
            with Horizontal(id="firewall-app-actions"):
                yield Button("Add app", id="firewall-app-add", variant="primary")
                yield Button("Remove app", id="firewall-app-remove", variant="error")
                yield Button("Block app", id="firewall-app-block")
                yield Button("Allow app", id="firewall-app-unblock")
            yield DataTable(id="table-firewall", cursor_type="row")
        elif self.spec.id == "privacy":
            with Horizontal(id="privacy-cards", classes="dashboard-row"):
                for name in ("firewall", "gatekeeper", "filevault"):
                    with Vertical(classes="security-card privacy-card"):
                        yield Label(name.upper(), classes="eyebrow")
                        yield Label("—", id=f"privacy-{name}-state", classes="state-pill")
            yield Static("", id=f"privacy-{name}-details", markup=False)
        else:
            if self.spec.id == "startup":
                with Vertical(id="startup-intro", classes="dashboard-panel"):
                    yield Label("STARTUP ITEMS & PERSISTENCE INVENTORY", classes="eyebrow")
                    yield Static("", id="startup-inventory-summary", markup=False)
            elif self.spec.id == "tcc":
                with Vertical(id="tcc-intro", classes="dashboard-panel"):
                    yield Label("TCC PRIVACY PERMISSIONS", classes="eyebrow")
                    yield Static("", id="tcc-summary", markup=False)
            elif self.spec.id == "snapshots":
                with Horizontal(id="snapshot-intro", classes="dashboard-panel"):
                    with Vertical():
                        yield Label("SECURITY STATE SNAPSHOTS", classes="eyebrow")
                        yield Static("Saved snapshots on this system", markup=False)
                    yield Button("Capture snapshot", id="capture-snapshot", variant="primary")
            yield Input(placeholder="Filter rows", id=f"filter-{self.spec.id}")
            yield DataTable(id=f"table-{self.spec.id}", cursor_type="row")
        yield Label("", id=f"status-{self.spec.id}")

    def on_mount(self) -> None:
        for box in self.query(Input):
            box.display = box.id in {"firewall-app-path", "startup-path", "startup-name"}
        if self.spec.id == "findings":
            table = self.query_one("#table-findings", DataTable)
            for column, title in zip(self.spec.columns, ("SEV", "CATEGORY", "ITEM", "DESCRIPTION")):
                table.add_column(title, key=column)
        elif self.spec.id != "privacy":
            table = self.query_one(DataTable)
            for column in self.spec.columns:
                table.add_column(column.replace("_", " ").title(), key=column)
        for view_id, button_id in (("listening", "network-listening"), ("established", "network-established")):
            if self.spec.id in {"listening", "established"}:
                self.query_one(f"#{button_id}", Button).set_class(view_id == self.spec.id, "-active")

    def data_ready(self, rows: list[dict[str, Any]]) -> None:
        self._all_rows = rows
        if self.spec.id == "startup":
            agents = sum(row.get("type") == "agent" for row in rows)
            login_items = sum(row.get("type") == "login_item" for row in rows)
            self.query_one("#startup-inventory-summary", Static).update(f"{login_items} Login Items · {agents} LaunchAgents · current user")
        elif self.spec.id == "tcc":
            self.query_one("#tcc-summary", Static).update(f"{len(rows)} permission records returned by the TCC query")
        elif self.spec.id == "findings":
            counts = {"all": len(rows), "high": 0, "warn": 0, "info": 0}
            for row in rows:
                severity = str(row.get("severity", "")).lower()
                key = "warn" if severity in {"warn", "warning"} else severity
                if key in counts:
                    counts[key] += 1
            for key, count in counts.items():
                title = "All" if key == "all" else "Warn" if key == "warn" else key.title()
                self.query_one(f"#severity-{key}", Button).label = f"{title} ({count})"
        elif self.spec.id == "privacy":
            by_name = {row.get("setting", "").lower(): row for row in rows}
            for name in ("firewall", "gatekeeper", "filevault"):
                row = by_name.get(name, {})
                state = str(row.get("status", "Unavailable"))
                state_label = self.query_one(f"#privacy-{name}-state", Label)
                state_label.update(state.upper())
                state_label.set_class(state == "Enabled", "state-enabled")
                state_label.set_class(state == "Disabled", "state-disabled")
                state_label.set_class(state == "Unavailable", "state-unavailable")
                self.query_one(f"#privacy-{name}-details", Static).update(str(row.get("details", "")))
        elif self.spec.id == "firewall":
            self._all_rows = rows
        self._redraw()
        self._refresh_status()

    def data_failed(self, error: str) -> None:
        self.query_one(f"#status-{self.spec.id}", Label).update(f"Unavailable · {_trunc(error, 90)}")

    def data_notice(self, notice: str) -> None:
        self.query_one(f"#status-{self.spec.id}", Label).update(_trunc(notice, 100))

    def _visible_rows(self) -> list[tuple[int, dict[str, Any]]]:
        term = self._filter_term.lower()
        selected = getattr(self, "_severity", "all")
        return [
            (i, row) for i, row in enumerate(self._all_rows)
            if (not term or term in json.dumps(row, default=str).lower())
            and (
                self.spec.id != "findings" or selected == "all"
                or ("warn" if str(row.get("severity", "")).lower() in {"warn", "warning"} else str(row.get("severity", "")).lower()) == selected
            )
        ]

    def _redraw(self) -> None:
        if self.spec.id == "privacy":
            return
        table = self.query_one(DataTable)
        table.clear()
        for index, row in self._visible_rows():
            cells = [_trunc(_cell(row, name), 64) for name in self.spec.columns]
            table.add_row(*cells, key=index)

    def _refresh_status(self) -> None:
        total = len(self._all_rows)
        message = "No rows returned" if total == 0 else f"{len(self._visible_rows())} of {total} rows"
        self.query_one(f"#status-{self.spec.id}", Label).update(message)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {f"filter-{self.spec.id}", "filter-findings"}:
            self._filter_term = event.value
            self._redraw()
            self._refresh_status()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == f"filter-{self.spec.id}":
            self.query_one(DataTable).focus()

    def action_toggle_filter(self) -> None:
        if self.spec.id in {"privacy", "firewall"}:
            return
        box = self.query_one(Input)
        box.display = True
        box.focus()

    def action_refresh(self) -> None:
        self._app_ref.refresh_current()

    def action_open_detail(self) -> None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return
        key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key
        if key is not None:
            index = int(key.value)
            if 0 <= index < len(self._all_rows):
                self._app_ref.open_detail(self.spec, index, self._all_rows[index])

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        try:
            index = int(event.row_key.value)
        except (TypeError, ValueError):
            return
        if not 0 <= index < len(self._all_rows):
            return
        row = self._all_rows[index]
        if self.spec.id == "findings":
            detail = "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in row.items() if value not in (None, ""))
            self.query_one("#finding-detail", Static).update(detail)
        elif self.spec.id in {"listening", "established", "startup"}:
            self._selected_row = row
            detail = "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in row.items() if value not in (None, ""))
            self.query_one("#row-detail", Static).update(detail or "No details available")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("severity-"):
            self._severity = button_id.removeprefix("severity-")
            self._redraw()
            self._refresh_status()
            for level in ("all", "high", "warn", "info"):
                self.query_one(f"#severity-{level}", Button).set_class(level == self._severity, "-active")


class RunnerPane(Vertical):
    """Compact history of commands executed through the shared runner."""

    def __init__(self, app_ref: "MspTUI") -> None:
        super().__init__(id="pane-runner")
        self._app_ref = app_ref

    def compose(self) -> ComposeResult:
        yield Label("Commands", classes="screen-title")
        yield Label("QUICK COMMANDS", classes="eyebrow")
        with Horizontal(id="command-presets"):
            yield Button("msp status --json", id="preset-status")
            yield Button("msp net list --json", id="preset-network")
            yield Button("msp scan quick --json", id="preset-scan")
            yield Button("msp startup audit --json", id="preset-startup")
        yield DataTable(id="history-table", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Command", "Result", "Time")
        for command, code, elapsed in self._app_ref.command_history:
            self.add_history(command, f"exit {code}", elapsed)

    def add_history(self, command: str, result: str, elapsed: float) -> None:
        table = self.query_one(DataTable)
        table.add_row(command, result, f"{elapsed:.1f}s")


class PaletteScreen(ModalScreen):
    """Searchable palette modeled on the supplied compact selection dialog."""

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("down", "focus_options", "Select"),
        ("up", "focus_options", "Select"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[tuple[str, str, str, str]] = []
        for view in VIEWS:
            self.entries.append(("VIEW", view.title, f"Open {view.title.lower()} screen", f"view:{view.id}"))
        for runnable in RUNNABLES:
            self.entries.append(("CMD", "msp " + runnable["verb"], runnable["desc"], "run:" + runnable["verb"]))
        self.entries.extend([
            ("ACTION", "Add firewall app rule…", "Open the firewall application controls", "form:firewall-app"),
            ("ACTION", "Add Login Item…", "Open current-user startup controls", "form:startup-login"),
            ("ACTION", "Add LaunchAgent…", "Open current-user startup controls", "form:startup-agent"),
        ])
        self.entries.append(("HELP", "Keyboard shortcuts", "Key reference and navigation", "help:"))
        self.visible_entries = list(range(len(self.entries)))

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-dialog"):
            with Horizontal(id="palette-search-row"):
                yield Static("›", classes="palette-chevron")
                yield Input(placeholder="Search screens, commands, or help…", id="palette-search")
                yield Label("Esc", classes="keycap")
            yield OptionList(id="palette-options")
            yield Label("↑ / ↓ Select   ·   Enter Open", id="palette-footer")

    def on_mount(self) -> None:
        self._render_options("")
        self.query_one("#palette-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "palette-search":
            self._render_options(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "palette-search" and self.visible_entries:
            self.dismiss(self.visible_entries[0])

    def _render_options(self, query: str) -> None:
        terms = query.strip().lower().split()
        self.visible_entries = [
            index for index, entry in enumerate(self.entries)
            if all(term in " ".join(entry).lower() for term in terms)
        ]
        options = self.query_one("#palette-options", OptionList)
        options.clear_options()
        for index in self.visible_entries:
            category, title, description, payload = self.entries[index]
            tag = "Needs confirm" if payload.startswith("run:") and _requires_confirmation(shlex.split(payload[4:])) else category
            options.add_option(Option(f"{tag:<12} {title}\n              {description}", id=str(index)))
        if self.visible_entries:
            options.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            self.dismiss(int(event.option.id))
        except (TypeError, ValueError):
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_focus_options(self) -> None:
        options = self.query_one("#palette-options", OptionList)
        options.focus()


# --------------------------------------------------------------------------
# Modal screens
# --------------------------------------------------------------------------

class DetailScreen(ModalScreen):
    """Full record view; q / esc dismisses."""

    BINDINGS = [("q", "dismiss_screen", "Close"), ("escape", "dismiss_screen", "Close")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Static(self._title, id="detail-title", markup=False),
            Static(self._body, id="detail-body", markup=False),
            id="detail-dialog",
        )

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen):
    """y / Enter confirm; n / esc cancel."""

    BINDINGS = [
        ("y", "confirm", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-body"):
            yield Label("Run this command?", classes="screen-title")
            yield Static("This command can change system settings or saved data.", id="confirm-description", markup=False)
            yield Static(f"$ msp {self.message}", id="confirm-command", markup=False)
            with Horizontal(id="confirm-actions"):
                yield Button("Cancel", id="cancel-confirm")
                yield Button("Run", id="accept-confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "accept-confirm")

    def on_mount(self) -> None:
        self.query_one("#accept-confirm", Button).focus()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfigScreen(ModalScreen):
    """Edit a persisted msp configuration value from any view."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="config-dialog"):
            yield Label("Update CLI setting", classes="screen-title")
            yield Static("Use section.key, for example general.timeout", markup=False)
            yield Input(placeholder="section.key", id="config-key")
            yield Input(placeholder="Value", id="config-value")
            with Horizontal(id="config-actions"):
                yield Button("Cancel", id="cancel-config")
                yield Button("Save setting", id="save-config", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#config-key", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-config":
            self.dismiss(None)
            return
        key = self.query_one("#config-key", Input).value.strip()
        value = self.query_one("#config-value", Input).value
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+", key)
            or not value.strip()
            or any(char in value for char in '\\"\r\n')
        ):
            self.notify("Enter a section.key and a value without quotes or line breaks", severity="warning")
            return
        self.dismiss((key, value))

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen):
    """Keybinding reference; q / esc dismisses."""

    BINDINGS = [("q", "dismiss_screen", "Close"), ("escape", "dismiss_screen", "Close")]

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Static(
                "[b]Keyboard shortcuts[/b]\n\n"
                "  [b]Ctrl+P[/b]   Search screens and commands\n"
                "  [b]Ctrl+R[/b]   Open command history\n"
                "  [b]Ctrl+C[/b]   Stop a running command\n"
                "  [b]/[/b]        Filter a table\n"
                "  [b]R[/b]        Refresh the current screen\n"
                "  [b]Enter[/b]    Open a row\n"
                "  [b]Q[/b]        Quit\n",
                id="help-body",
            )
        )

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------
# Main app
# --------------------------------------------------------------------------

class MspTUI(App[None]):
    """msp console with live CLI views and a persistent command runner."""

    CSS = """
    Screen { background: #0C1322; color: #F2F4F8; }
    Footer { background: #111827; }
    Button {
        min-width: 8;
        height: 3;
        padding: 0 1;
        border: solid #2D323A;
        background: #111827;
        color: #F2F4F8;
        text-style: none;
    }
    Button:hover { background: #1A2233; border: solid #8E93A0; color: #F0F6FC; }
    Button:focus { border: solid #0A84FF; color: #0A84FF; }
    Button.-primary { background: #0A84FF; border: solid #0A84FF; color: #0C1322; text-style: bold; }
    Button.-primary:hover { background: #66A5FF; border: solid #66A5FF; color: #0C1322; }
    Button.-success { background: #14251A; border: solid #2C6B3F; color: #34C759; }
    Button.-warning { background: #241E12; border: solid #6D5422; color: #FF9F0A; }
    Button.-error { background: #261719; border: solid #6E3037; color: #FF3B30; }
    Button.-error:hover { background: #3A1D21; border: solid #FF3B30; color: #FF6B63; }
    Button:disabled { background: #0C1322; border: solid #1A2233; color: #484F58; }
    #brandbar { height: 2; padding: 0 1; background: #111827; border-bottom: solid #2D323A; }
    #brand-left { width: 1fr; color: #8E93A0; }
    #brand-right { width: auto; color: #8E93A0; }
    #brandbar Button { height: 2; min-width: 10; border: none; background: transparent; color: #AAC7FF; }
    #nav { height: 3; padding: 0 1; background: #111827; border-bottom: solid #2D323A; }
    #nav Button { min-width: 9; height: 3; border: solid #2D323A; background: #111827; color: #8E93A0; padding: 0 1; }
    #nav Button.-active { color: #0C1322; text-style: bold; border: solid #0A84FF; background: #0A84FF; }
    #page { height: 1fr; padding: 0 1; }
    .screen-title { height: 1; text-style: bold; color: #F2F4F8; }
    .screen-toolbar { height: 3; align: left middle; }
    .screen-toolbar Button { dock: right; }
    .dashboard-row { height: 1fr; min-height: 5; margin-bottom: 1; }
    #security-cards { height: 6; min-height: 6; }
    .security-card { width: 1fr; height: 1fr; border: solid #2D323A; background: #111827; padding: 0 1; margin-right: 1; }
    .privacy-card { height: 14; }
    .card-heading, .panel-heading { height: 2; }
    .card-heading .eyebrow, .panel-heading .eyebrow { width: 1fr; }
    .eyebrow { color: #8E93A0; text-style: bold; }
    .state-pill { color: #34C759; text-style: bold; }
    .state-disabled { color: #FF3B30; }
    .state-enabled { color: #34C759; }
    .state-unavailable { color: #8E93A0; }
    .card-details { height: 1fr; color: #8E93A0; }
    .quiet-action { min-width: 11; height: 2; border: none; background: transparent; color: #0A84FF; }
    .quiet-action:hover { border: none; background: transparent; color: #66A5FF; }
    .dashboard-panel { border: solid #2D323A; background: #111827; padding: 0 1; }
    .wide-panel { width: 2fr; margin-right: 1; }
    .narrow-panel { width: 1fr; }
    #overview-listening, #overview-findings-table, #overview-startup-table { height: 1fr; border: none; }
    #activity-summary, #startup-summary { height: 1fr; padding: 1 0; color: #8E93A0; }
    #network-tabs, #finding-filter-row { height: 3; margin-bottom: 1; }
    #firewall-actions { height: 9; }
    #firewall-actions Horizontal { height: 3; }
    #firewall-actions Button { margin-right: 1; min-width: 12; }
    #firewall-app-actions { height: 3; }
    #record-layout { height: 1fr; }
    #record-layout DataTable { width: 2fr; margin-right: 1; }
    #row-inspector { width: 1fr; }
    #startup-add-form { height: 3; }
    #startup-add-form Input { width: 1fr; }
    #network-tabs Button.-active, #finding-filter-row Button.-active { color: #0C1322; border: solid #0A84FF; background: #0A84FF; text-style: bold; }
    #findings-layout { height: 1fr; }
    #findings-layout #table-findings { width: 2fr; margin-right: 1; }
    #finding-inspector { width: 1fr; padding: 0 1; border-left: solid #2D323A; }
    #finding-detail { height: 1fr; padding-top: 1; color: #F2F4F8; }
    #startup-intro, #tcc-intro, #snapshot-intro { height: auto; min-height: 4; margin-bottom: 1; padding: 0 1; }
    #startup-inventory-summary, #tcc-summary { color: #8E93A0; }
    #snapshot-intro Button { dock: right; }
    #table-startup, #table-tcc, #table-snapshots, #table-listening, #table-established { height: 1fr; }
    DataTable { height: 1fr; border: solid #2D323A; background: #0C1322; }
    #status-findings, #status-listening, #status-established, #status-startup, #status-tcc, #status-privacy, #status-snapshots { height: 1; color: #8E93A0; }
    #overview-note { margin-top: 1; color: #8E93A0; }
    #runner-help { color: #8E93A0; margin-bottom: 1; }
    #command-presets { height: 3; margin-bottom: 1; }
    #command-presets Button { margin-right: 1; }
    .empty-note { height: 1; color: #8E93A0; }
    #command-panel { height: 9; min-height: 8; padding: 0 1; border-top: solid #2D323A; background: #0C1322; }
    #runner-tabs { height: 2; }
    #runner-tabs Button { min-width: 16; height: 2; border: none; background: #0C1322; color: #8E93A0; padding: 0 1; }
    #runner-tabs Button.-active { color: #0A84FF; text-style: bold; border-bottom: solid #0A84FF; }
    #execution-log-view, #chat-ask-view { height: 1fr; }
    #command-head { height: 1; color: #0A84FF; text-style: bold; }
    #command-log { height: 1fr; color: #F2F4F8; }
    #command-controls { height: 3; }
    #command-input { width: 1fr; }
    #command-controls Button { min-width: 9; }
    #chat-log { height: 1fr; color: #F2F4F8; }
    #chat-controls { height: 3; }
    #chat-input { width: 1fr; }
    #detail-body, #confirm-body, #help-body {
        margin: 2 4; padding: 1 2; border: solid #2D323A; background: #111827;
    }
    DetailScreen, ConfirmScreen, HelpScreen { align: center middle; background: #000000 85%; }
    #detail-dialog { width: 76; max-height: 85%; height: auto; border: solid #2D323A; background: #111827; padding: 1 2; }
    #detail-body { margin: 0; padding: 1 0; border: none; }
    #confirm-body { width: 72; height: auto; max-height: 80%; margin: 0; border: solid #0A84FF; }
    #confirm-actions { height: 3; align: right middle; }
    #confirm-actions Button { margin-left: 1; }
    #confirm-command { padding: 0 1; margin: 1 0; border: solid #2D323A; background: #0C1322; color: #FF9F0A; }
    #confirm-description { color: #8E93A0; }
    #config-dialog { width: 68; height: auto; border: solid #414754; background: #111827; padding: 1 2; }
    #config-dialog Input { margin-top: 1; }
    #config-actions { height: 3; margin-top: 1; align: right middle; }
    #config-actions Button { margin-left: 1; }
    PaletteScreen { align: center middle; background: #000000 85%; }
    #palette-dialog { width: 74; height: auto; max-height: 75%; border: solid #0A84FF; background: #0C1322; padding: 1; }
    #palette-search-row { height: 3; margin-bottom: 1; }
    .palette-chevron { width: 3; color: #0A84FF; content-align: center middle; }
    #palette-search { width: 1fr; border: solid #0A84FF; }
    .keycap { width: 6; content-align: center middle; color: #8E93A0; }
    #palette-options { height: auto; max-height: 20; background: #111827; }
    #palette-footer { height: 1; color: #8E93A0; margin-top: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+p", "open_palette", "Palette", priority=True),
        Binding("ctrl+r", "open_runner_default", "Runner", priority=True),
        Binding("?", "help", "Keys"),
        Binding("ctrl+c", "stop_command", "Stop", priority=True),
        Binding("r", "refresh_current", "Refresh"),
        Binding("1", "view('dashboard')", "Overview", show=False),
        Binding("2", "view('findings')", "Findings", show=False),
        Binding("3", "view('listening')", "Listening", show=False),
        Binding("4", "view('startup')", "Startup", show=False),
        Binding("5", "view('tcc')", "Permissions", show=False),
        Binding("6", "view('privacy')", "Privacy", show=False),
        Binding("7", "view('snapshots')", "Snapshots", show=False),
        Binding("8", "view('firewall')", "Firewall", show=False),
    ]

    TITLE = "msp — tui v2"
    SUB_TITLE = "security & privacy console"

    DARK_THEME = Theme(
        name="msp-dark", primary="#AAC7FF", secondary="#C2C6D4", warning="#FFB691",
        error="#FFB4AB", success="#34C759", accent="#AAC7FF", foreground="#DCE2F7",
        background="#0C1322", surface="#111827", panel="#0C1322", boost="#1A2233",
        dark=True, variables={"outline": "#414754"},
    )

    def __init__(self) -> None:
        super().__init__()
        self._panes: dict[str, Union[DashboardPane, TablePane, RunnerPane]] = {}
        self._current_id: Optional[str] = None
        self.current_broker: Optional[CommandBroker] = None
        self._command_busy = False
        self.command_history: list[tuple[str, int, float]] = []
        self._command_history_index: Optional[int] = None
        self._stop_requested = False
        self.register_theme(self.DARK_THEME)
        self.theme = "msp-dark"

    # -- layout ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="brandbar"):
            yield Static("[red]●[/red] [yellow]●[/yellow] [green]●[/green]  [blue][[msp]][/blue]  macOS Security & Privacy Console", id="brand-left")
            yield Label("VIEW: OVERVIEW", id="brand-right")
            yield Button("Settings", id="open-config")
        with Horizontal(id="nav"):
            nav_labels = {"dashboard": "Dashboard", "findings": "Findings", "listening": "Network", "startup": "Startup", "tcc": "TCC", "privacy": "Privacy", "snapshots": "Snapshots"}
            for view_id in NAV_VIEWS:
                view = view_by_id(view_id)
                if view:
                    yield Button(nav_labels[view.id], id=f"nav-{view.id}")
            yield Button("⌘ Palette", id="open-palette", tooltip="Command palette (Ctrl+P)")
            yield Button("?", id="open-help", tooltip="Help")
        with Vertical(id="page"):
            pass
        with Vertical(id="command-panel"):
            with Horizontal(id="runner-tabs"):
                yield Button("Chat / Ask", id="runner-tab-chat")
                yield Button("Execution Logs", id="runner-tab-logs", classes="-active")
            with Vertical(id="execution-log-view"):
                yield Label("$ msp · waiting for command", id="command-head", markup=False)
                yield RichLog(id="command-log", markup=False, wrap=True, highlight=False)
                with Horizontal(id="command-controls"):
                    yield Input(placeholder="msp command…", id="command-input")
                    yield Button("Run", id="run-command", variant="primary")
                    yield Button("Stop", id="stop-command", variant="error", disabled=True)
            with Vertical(id="chat-ask-view"):
                yield RichLog(id="chat-log", markup=False, wrap=True, highlight=False)
                with Horizontal(id="chat-controls"):
                    yield Input(placeholder="Ask a question…", id="chat-input")
                    yield Button("Ask", id="ask-question", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#chat-ask-view", Vertical).display = False
        self.call_after_refresh(self.switch_view_id, "dashboard")

    def on_unmount(self) -> None:
        if self.current_broker is not None:
            self.current_broker.kill()

    def switch_view_id(self, view_id: str) -> None:
        spec = view_by_id(view_id)
        if spec is None and view_id != "runner":
            return
        pane = self._panes.get(view_id)
        if pane is None:
            pane = RunnerPane(self) if view_id == "runner" else DashboardPane() if view_id == "dashboard" else TablePane(spec, self)
            self._panes[view_id] = pane
            self.query_one("#page", Vertical).mount(pane)
        for other_id, other_pane in self._panes.items():
            other_pane.display = other_id == view_id
        self._current_id = view_id
        active_title = "Network" if view_id in {"listening", "established"} else spec.title if spec else "Commands"
        self.sub_title = active_title
        self.query_one("#brand-right", Label).update(f"VIEW: {active_title.upper()}")
        for nav_id in NAV_VIEWS:
            button = self.query_one(f"#nav-{nav_id}", Button)
            button.set_class(nav_id == view_id or (view_id == "established" and nav_id == "listening") or (view_id == "firewall" and nav_id == "privacy"), "-active")
        self.refresh_current()

    # -- actions ----------------------------------------------------------

    def open_config(self) -> None:
        self.push_screen(ConfigScreen(), self._save_config_value)

    def _save_config_value(self, setting: Optional[tuple[str, str]]) -> None:
        if setting is None:
            return
        key, value = setting
        command = f"config set {shlex.quote(key)} {shlex.quote(value)}"
        self.push_screen(
            ConfirmScreen(command),
            lambda confirmed: self.execute_commands([command], update_view=False) if confirmed else None,
        )

    def action_view(self, view_id: str) -> None:
        self.switch_view_id(view_id)

    def refresh_current(self) -> None:
        view_id = self._current_id
        if view_id == "runner":
            return
        commands = list(DASHBOARD_COMMANDS) if view_id == "dashboard" else [view_by_id(view_id).command]
        self.execute_commands([cmd for cmd in commands if cmd], view_id=view_id)

    def action_open_runner_default(self) -> None:
        self.switch_view_id("runner")

    def open_runner(self, command: str) -> None:
        self.switch_view_id("runner")
        self.query_one("#command-input", Input).value = command
        self.query_one("#command-input", Input).focus()

    def open_help(self) -> None:
        self.push_screen(HelpScreen())

    def open_palette(self) -> None:
        palette = PaletteScreen()
        self.push_screen(palette, lambda selected: self._palette_selected(selected, palette.entries))

    def _palette_selected(self, selected: Optional[int], entries: list[tuple[str, str, str, str]]) -> None:
        if selected is None or selected >= len(entries):
            return
        _, _, _, payload = entries[selected]
        if payload.startswith("view:"):
            self.switch_view_id(payload[5:])
        elif payload.startswith("run:"):
            self.query_one("#command-input", Input).value = payload[4:]
            self.submit_command()
        elif payload.startswith("help:"):
            self.open_help()
        elif payload.startswith("form:"):
            form = payload[5:]
            target = "firewall" if form == "firewall-app" else "startup"
            self.switch_view_id(target)
            field = "#firewall-app-path" if target == "firewall" else "#startup-path"
            self.query_one(field, Input).focus()

    def action_open_palette(self) -> None:
        self.open_palette()

    def action_help(self) -> None:
        self.open_help()

    def open_detail(self, spec: ViewSpec, index: int, row: dict[str, Any]) -> None:
        lines = []
        for key in row:
            value = row.get(key)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, default=str)
            lines.append(f"{key.replace('_', ' ').title():<18} {value}")
        body = "\n".join(lines) if lines else "(empty record)"
        self.push_screen(DetailScreen(f"{spec.title} · row {index + 1}", body))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "runner-tab-chat":
            self.select_runner_tab("chat")
        elif button_id == "runner-tab-logs":
            self.select_runner_tab("logs")
        elif button_id.startswith("nav-"):
            self.switch_view_id(button_id[4:])
        elif button_id == "open-palette":
            self.open_palette()
        elif button_id == "open-help":
            self.open_help()
        elif button_id == "open-config":
            self.open_config()
        elif button_id in {"inspect-process", "stop-process", "force-stop-process", "disable-startup", "enable-startup", "startup-login-add", "startup-agent-add", "startup-remove"}:
            self._run_context_action(button_id)
        elif button_id.startswith("firewall-"):
            self._firewall_action(button_id)
        elif button_id == "refresh-view":
            self.refresh_current()
        elif button_id == "run-command":
            self.submit_command()
        elif button_id == "ask-question":
            self.submit_question()
        elif button_id == "stop-command":
            self.action_stop_command()
        elif button_id == "card-listening":
            self.switch_view_id("listening")
        elif button_id == "card-established":
            self.switch_view_id("established")
        elif button_id == "card-startup":
            self.switch_view_id("startup")
        elif button_id == "card-findings":
            self.switch_view_id("findings")
        elif button_id.startswith("inspect-"):
            self.switch_view_id("firewall" if button_id == "inspect-firewall" else "privacy")
        elif button_id == "network-listening":
            self.switch_view_id("listening")
        elif button_id == "network-established":
            self.switch_view_id("established")
        elif button_id == "capture-snapshot":
            command = "snapshot capture"
            self.push_screen(
                ConfirmScreen(command),
                lambda confirmed: self.execute_commands([command, "snapshot list --json"], view_id="snapshots") if confirmed else None,
            )
        elif button_id.startswith("preset-"):
            command = {
                "preset-status": "status --json",
                "preset-network": "net list --json",
                "preset-scan": "scan quick --json",
                "preset-startup": "startup audit --json",
            }.get(button_id)
            if command:
                self.execute_commands([command], update_view=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "command-input":
            self.submit_command()
        elif event.input.id == "chat-input":
            self.submit_question()

    def select_runner_tab(self, tab: str) -> None:
        is_chat = tab == "chat"
        self.query_one("#chat-ask-view", Vertical).display = is_chat
        self.query_one("#execution-log-view", Vertical).display = not is_chat
        self.query_one("#runner-tab-chat", Button).set_class(is_chat, "-active")
        self.query_one("#runner-tab-logs", Button).set_class(not is_chat, "-active")

    def submit_question(self) -> None:
        box = self.query_one("#chat-input", Input)
        prompt = box.value.strip()
        if not prompt:
            return
        if self._command_busy:
            return
        self.select_runner_tab("chat")
        self.query_one("#chat-log", RichLog).write(f"You: {prompt}")
        box.value = ""
        command = "ask " + shlex.quote(prompt) + " --json"
        self.execute_commands([command], update_view=False, chat_prompt=prompt)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id or ""
        if not table_id.startswith("overview-"):
            return
        if "findings" in table_id:
            target = "findings"
        elif "listening" in table_id:
            target = "listening"
        elif "startup" in table_id:
            target = "startup"
        else:
            return
        self.switch_view_id(target)

    def submit_command(self) -> None:
        box = self.query_one("#command-input", Input)
        line = box.value.strip()
        if not line:
            return
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            self._append_output(f"Invalid command: {exc}")
            return
        if tokens and Path(tokens[0]).name == "msp":
            tokens = tokens[1:]
            line = shlex.join(tokens)
        if not tokens:
            self._append_output("Enter an msp command.")
            return
        if len(tokens) > 1 and tokens[0].lower() == "net" and tokens[1].lower() in {"kill", "terminate"} and "--yes" not in tokens and "--force" not in tokens:
            tokens.append("--yes")
            line = shlex.join(tokens)
        self.select_runner_tab("logs")
        if _requires_confirmation(tokens):
            self.push_screen(ConfirmScreen(line), lambda confirmed: self.execute_commands([line], update_view=False) if confirmed else None)
        else:
            self.execute_commands([line], update_view=False)
        box.value = ""

    def _append_output(self, text: str) -> None:
        self.query_one("#command-log", RichLog).write(text)

    def _run_context_action(self, action: str) -> None:
        pane = self._panes.get(self._current_id or "")
        row = getattr(pane, "_selected_row", None)
        if action in {"startup-login-add", "startup-agent-add"}:
            path = self.query_one("#startup-path", Input).value.strip()
            name = self.query_one("#startup-name", Input).value.strip()
            if not path or not name:
                self.select_runner_tab("logs")
                self._append_output("Enter an application or executable path and a name first.")
                return
            command = f"startup login-add --name {shlex.quote(name)} --path {shlex.quote(path)}" if action == "startup-login-add" else f"startup agent-add {shlex.quote(name)} --path {shlex.quote(path)}"
            self.push_screen(ConfirmScreen(command), lambda confirmed: self.execute_commands([command, "startup managed --json"], update_view=True, view_id="startup") if confirmed else None)
            return
        if action == "startup-remove":
            if not isinstance(row, dict):
                return
            name = str(row.get("name") or row.get("label") or "")
            command = f"startup login-remove --name {shlex.quote(name)}" if row.get("type") == "login_item" else f"startup agent-remove {shlex.quote(str(row.get('label') or name))}" if row.get("type") == "agent" else ""
            if not command:
                self._append_output("Only current-user Login Items and LaunchAgents can be removed here.")
                self.select_runner_tab("logs")
                return
            self.push_screen(ConfirmScreen(command), lambda confirmed: self.execute_commands([command, "startup managed --json"], update_view=True, view_id="startup") if confirmed else None)
            return
        if not isinstance(row, dict):
            return
        if action == "inspect-process":
            pid = row.get("pid")
            if pid:
                self.execute_commands([f"net inspect --pid {int(pid)} --json"], update_view=False)
        elif action in {"stop-process", "force-stop-process"}:
            pid = row.get("pid")
            if pid:
                command = f"net kill --pid {int(pid)} --signal KILL --yes" if action == "force-stop-process" else f"net terminate --pid {int(pid)} --yes --json"
                self.push_screen(ConfirmScreen(command), lambda confirmed: self.execute_commands([command], update_view=False) if confirmed else None)
        elif action in {"disable-startup", "enable-startup"}:
            label = str(row.get("label") or row.get("name") or "")
            if not label or row.get("type") != "agent" or not str(row.get("path", "")).startswith(str(Path.home() / "Library" / "LaunchAgents")):
                self._append_output("Only current-user Login Items and LaunchAgents can be changed here.")
                self.select_runner_tab("logs")
                return
            operation = "agent-disable" if action == "disable-startup" else "agent-enable"
            command = f"startup {operation} {shlex.quote(label)}"
            self.push_screen(ConfirmScreen(command), lambda confirmed: self.execute_commands([command], update_view=False) if confirmed else None)

    def _firewall_action(self, button_id: str) -> None:
        actions = {
            "firewall-enable": "firewall set enabled on", "firewall-disable": "firewall set enabled off",
            "firewall-stealth-on": "firewall set stealth_mode on", "firewall-stealth-off": "firewall set stealth_mode off",
            "firewall-block-on": "firewall set block_all on", "firewall-block-off": "firewall set block_all off",
            "firewall-signed-on": "firewall set allows_signed on", "firewall-signed-off": "firewall set allows_signed off",
            "firewall-signed-app-on": "firewall set allows_signed_app on", "firewall-signed-app-off": "firewall set allows_signed_app off",
        }
        command = actions.get(button_id)
        if button_id.startswith("firewall-app-"):
            operation = button_id.removeprefix("firewall-app-")
            app_path = self.query_one("#firewall-app-path", Input).value.strip()
            if not app_path:
                self.select_runner_tab("logs")
                self._append_output("Enter an application path first.")
                return
            command = f"firewall app {operation} {shlex.quote(app_path)}"
        if command:
            self.select_runner_tab("logs")
            self.push_screen(ConfirmScreen(command), lambda confirmed: self.execute_commands([command], update_view=False) if confirmed else None)

    def execute_commands(
        self, commands: list[str], update_view: bool = True, view_id: Optional[str] = None,
        chat_prompt: Optional[str] = None,
    ) -> None:
        if self._command_busy:
            self._append_output("A command is already running.")
            return
        panel = self.query_one("#command-log", RichLog)
        panel.clear()
        if chat_prompt is None:
            self.select_runner_tab("logs")
        self._command_busy = True
        self._stop_requested = False
        target_view = view_id if view_id is not None else self._current_id
        self.query_one("#stop-command", Button).disabled = False
        self.query_one("#command-head", Label).update("$ msp " + "  ·  $ msp ".join(commands))
        self._append_output("Starting…")

        def worker() -> None:
            results: dict[str, tuple[int, list[str]]] = {}
            for command in commands:
                if self._stop_requested:
                    break
                broker = CommandBroker(command)
                self.current_broker = broker
                self.call_from_thread(self._append_output, f"\n$ msp {command}")
                lines: list[str] = []
                rc = 1
                for output, done, return_code, elapsed in broker.run():
                    if done:
                        rc = return_code if return_code is not None else 1
                        self.call_from_thread(self._append_output, output)
                        results[command] = (rc, lines)
                        self.call_from_thread(self._record_command, command, rc, elapsed)
                        self.current_broker = None
                    else:
                        lines.append(output)
                        self.call_from_thread(self._append_output, output)
            self.call_from_thread(self._commands_complete, results, update_view, target_view, chat_prompt)

        self.run_worker(worker, name="cli-command", group="cli", thread=True, exclusive=True, exit_on_error=False)

    def _record_command(self, command: str, rc: int, elapsed: float) -> None:
        self.command_history.append((command, rc, elapsed))
        self.query_one("#command-head", Label).update(f"$ msp {command}  ·  exit {rc}  ·  {elapsed:.1f}s")
        runner = self._panes.get("runner")
        if isinstance(runner, RunnerPane):
            runner.add_history(command, f"exit {rc}", elapsed)

    def _commands_complete(
        self, results: dict[str, tuple[int, list[str]]], update_view: bool = True,
        view_id: Optional[str] = None, chat_prompt: Optional[str] = None,
    ) -> None:
        self.current_broker = None
        self._command_busy = False
        self.query_one("#stop-command", Button).disabled = True
        if chat_prompt is not None:
            command = "ask " + shlex.quote(chat_prompt) + " --json"
            code, lines = results.get(command, (1, []))
            payload = _extract_json(lines)
            response = payload.get("response") if isinstance(payload, dict) else None
            chat_log = self.query_one("#chat-log", RichLog)
            if response:
                chat_log.write(f"Assistant: {response}")
            else:
                details = next(
                    (
                        line.strip()
                        for line in reversed(lines)
                        if re.search(r"(?i)(error:|api key required|request failed|timed out)", line)
                    ),
                    None,
                )
                if details:
                    details = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", details)
                    chat_log.write(f"Assistant: {details}")
                else:
                    reason = f"Ask returned no response (exit {code})" if code else "No response returned"
                    chat_log.write(f"Assistant: {reason}. See Execution Logs for details.")
        for command, (code, lines) in results.items():
            if command.startswith("net terminate ") and code == 0:
                result = _extract_json(lines)
                if isinstance(result, dict) and result.get("sent") and result.get("still_running"):
                    pid = int(result.get("pid", 0))
                    identity = shlex.quote(str(result.get("identity") or ""))
                    force_command = f"net kill --pid {pid} --signal KILL --yes --expected-identity {identity}"
                    self.push_screen(
                        ConfirmScreen(force_command),
                        lambda confirmed, cmd=force_command: self.execute_commands([cmd], update_view=False) if confirmed else None,
                    )
                    return
        if not update_view:
            return
        if view_id and view_id != self._current_id:
            self.refresh_current()
            return
        pane = self._panes.get(view_id or self._current_id or "")
        if isinstance(pane, DashboardPane):
            pane.show_data(results)
        elif isinstance(pane, TablePane):
            command = pane.spec.command or ""
            code, lines = results.get(command, (1, []))
            if code != 0:
                pane.data_failed("command failed; see output")
                return
            payload = _extract_json(lines)
            if payload is None:
                pane.data_failed("no JSON data returned")
            else:
                pane.data_ready(_payload_rows(pane.spec.id, payload))
                if isinstance(payload, dict) and payload.get("errors"):
                    pane.data_notice("Some data is unavailable due to system permissions. See command output below.")

    def action_stop_command(self) -> None:
        if self.current_broker is not None:
            self.current_broker.kill()
            self._stop_requested = True
            self._append_output("Stopping…")


def main(argv: Optional[Tuple[str, ...]] = None) -> None:
    """Entry point for msp tui (v2). ``--v1`` falls back to the legacy dashboard."""
    argv = tuple(argv if argv is not None else sys.argv[1:])
    if "--v1" in argv:
        from src.tui import main as tui_v1_main

        tui_v1_main()
        return
    MspTUI().run()


if __name__ == "__main__":
    main()
