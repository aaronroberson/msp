#!/usr/bin/env python3
"""
msp TUI v2 — terminal console for the macOS Security & Privacy CLI.

An opencode-style Textual client:

* grouped sidebar (concern ▸ page); manifest pages (src/tui_manifest/pages)
  render through src.tui_pages, remaining screens are legacy panes
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

from src.tui_manifest import CommandSpec, load_commands, load_labels, load_pages, load_templates
from src.tui_pages.page import PAGE_CSS, PageView, RunFinished, RunStarted
from src.tui_pages.components import OpenPage
from src.tui_pages.runtime import Executor, build_argv, executor_for
from src.tui_pages.fallback import fallback_pages
from src.tui_pages.shell import PAGE_ALIASES, SIDEBAR_CSS, Sidebar, nav_entries, nav_key

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
    if command == "doctor":
        return bool(args and args[0].lower() == "fix")
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
    {"verb": "doctor", "title": "Run: doctor", "desc": "Health: deps + latest scan results"},
    {"verb": "doctor fix", "title": "Run: doctor fix", "desc": "Shell/system performance auto-fixes"},
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

    def __init__(self, screens: list[tuple[str, str]]) -> None:
        super().__init__()
        self.entries: list[tuple[str, str, str, str]] = []
        for key, title in screens:
            self.entries.append(("VIEW", title, f"Open {title.lower()} screen", f"view:{key}"))
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

class WorkflowsScreen(ModalScreen):
    """Show workflow execution state and gate status."""

    BINDINGS = [("q", "dismiss_screen", "Close"), ("escape", "dismiss_screen", "Close")]

    def __init__(self, run_result: Optional[dict] = None) -> None:
        super().__init__()
        self._run_result = run_result or {"run_id": "", "status": "idle", "completed_steps": []}

    def compose(self) -> ComposeResult:
        yield VerticalScroll(
            Static("Workflow Execution State", id="screen-title", markup=False),
            Static(f"Run ID: {self._run_result.get('run_id', '')}", id="run-id"),
            Static(f"Status: {self._run_result.get('status', 'idle')}", id="workflow-status"),
            Static(
                f"Completed steps: {', '.join(self._run_result.get('completed_steps', [])) or 'none'}",
                id="completed-steps",
            ),
            Static(
                "Use 'msp workflow run <name> --dry-run' to plan, or run for execution.\nGate enforces approval for dangerous/risk-increasing steps.",
                id="gate-note",
                markup=False,
            ),
            Button("Close", id="close-workflows"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-workflows":
            self.dismiss(None)


class ConfirmScreen(ModalScreen):
    """y / Enter confirm; n / esc cancel."""

    BINDINGS = [
        ("y", "confirm", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str, detail: str = "This command can change system settings or saved data.") -> None:
        super().__init__()
        self.message = message
        self.detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-body"):
            yield Label("Run this command?", classes="screen-title")
            yield Static(self.detail, id="confirm-description", markup=False)
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
    Screen { background: #0D1117; color: #C9D1D9; }
    Footer { background: #161B22; }
    Button {
        min-width: 8;
        height: 3;
        padding: 0 1;
        border: solid #30363D;
        background: #161B22;
        color: #C9D1D9;
        text-style: none;
    }
    Button:hover { background: #21262D; border: solid #8B949E; color: #F0F6FC; }
    Button:focus { border: solid #58A6FF; color: #58A6FF; }
    Button.-primary { background: #58A6FF; border: solid #58A6FF; color: #0D1117; text-style: bold; }
    Button.-primary:hover { background: #79B8FF; border: solid #79B8FF; color: #0D1117; }
    Button.-success { background: #12261E; border: solid #2EA043; color: #3FB950; }
    Button.-warning { background: #272115; border: solid #9E6A03; color: #D29922; }
    Button.-error { background: #2D1416; border: solid #B62324; color: #F85149; }
    Button.-error:hover { background: #3D1A1D; border: solid #F85149; color: #FF7B72; }
    Button:disabled { background: #0D1117; border: solid #21262D; color: #6E7681; }
    #brandbar { height: 2; padding: 0 1; background: #161B22; border-bottom: solid #30363D; }
    #brand-left { width: 1fr; color: #8B949E; }
    #brand-right { width: auto; color: #8B949E; }
    #brandbar Button { height: 2; min-width: 10; border: none; background: transparent; color: #58A6FF; }
    #page { width: 1fr; height: 1fr; padding: 0 1; }
    #main-row { height: 1fr; }
    #log-rail { width: 40; border-left: solid #30363D; background: #0D1117; padding: 0 1; }
    .screen-title { height: 1; text-style: bold; color: #C9D1D9; }
    .screen-toolbar { height: 3; align: left middle; }
    .screen-toolbar Button { dock: right; }
    .eyebrow { color: #8B949E; text-style: bold; }
    .state-pill { color: #3FB950; text-style: bold; }
    .state-disabled { color: #F85149; }
    .state-enabled { color: #3FB950; }
    .state-unavailable { color: #8B949E; }
    .quiet-action { min-width: 11; height: 2; border: none; background: transparent; color: #58A6FF; }
    .quiet-action:hover { border: none; background: transparent; color: #79B8FF; }
    #network-tabs, #finding-filter-row { height: 3; margin-bottom: 1; }
    #record-layout { height: 1fr; }
    #record-layout DataTable { width: 2fr; margin-right: 1; }
    #row-inspector { width: 1fr; }
    #startup-add-form { height: 3; }
    #startup-add-form Input { width: 1fr; }
    #network-tabs Button.-active, #finding-filter-row Button.-active { color: #0D1117; border: solid #58A6FF; background: #58A6FF; text-style: bold; }
    #findings-layout { height: 1fr; }
    #findings-layout #table-findings { width: 2fr; margin-right: 1; }
    #finding-inspector { width: 1fr; padding: 0 1; border-left: solid #30363D; }
    #finding-detail { height: 1fr; padding-top: 1; color: #C9D1D9; }
    #startup-intro, #tcc-intro, #snapshot-intro { height: auto; min-height: 4; margin-bottom: 1; padding: 0 1; }
    #startup-inventory-summary, #tcc-summary { color: #8B949E; }
    #snapshot-intro Button { dock: right; }
    #table-startup, #table-tcc, #table-snapshots, #table-listening, #table-established { height: 1fr; }
    DataTable { height: 1fr; border: solid #30363D; background: #0D1117; }
    #status-findings, #status-listening, #status-established, #status-startup, #status-tcc, #status-privacy, #status-snapshots { height: 1; color: #8B949E; }
    #runner-help { color: #8B949E; margin-bottom: 1; }
    #command-presets { height: 3; margin-bottom: 1; }
    #command-presets Button { margin-right: 1; }
    .empty-note { height: 1; color: #8B949E; }
    #command-panel { height: 3; padding: 0 1; border-top: solid #30363D; background: #0D1117; }
    #execution-log-view { height: 2fr; border-bottom: solid #30363D; padding-bottom: 1; }
    #command-head { height: 1; color: #58A6FF; text-style: bold; }
    #command-log { height: 1fr; color: #C9D1D9; }
    #command-controls { height: 3; align: left middle; }
    #command-input { width: 1fr; }
    #command-controls Button { height: 1; min-width: 7; padding: 0 1; border: none; }
    #command-controls #run-command { background: #58A6FF; color: #0D1117; text-style: bold; }
    #command-controls #stop-command { background: #2D1416; color: #F85149; }
    #command-controls Button:disabled { background: transparent; color: #6E7681; }
    #chat-ask-view { height: 1fr; }
    #chat-log { height: 1fr; color: #C9D1D9; }
    #chat-controls { height: 3; align: left middle; }
    #chat-input { width: 1fr; }
    #chat-controls Button { height: 1; min-width: 5; padding: 0 1; border: none; }
    #chat-controls #ask-question { background: #58A6FF; color: #0D1117; text-style: bold; }
    #detail-body, #confirm-body, #help-body {
        margin: 2 4; padding: 1 2; border: solid #30363D; background: #161B22;
    }
    ConfirmScreen, HelpScreen, ConfigScreen { align: center middle; background: #000000 85%; }
    HelpScreen VerticalScroll { align: center middle; }
    HelpScreen #help-body { width: 72; margin: 0; height: auto; }
    /* .stitch: thin dark scrollbars */
    * { scrollbar-color: #30363D; scrollbar-background: #0D1117; scrollbar-color-hover: #6E7681; }
    Screen, VerticalScroll, ScrollableContainer { scrollbar-size-vertical: 1; scrollbar-size-horizontal: 1; }
    #detail-dialog { width: 76; max-height: 85%; height: auto; border: solid #30363D; background: #161B22; padding: 1 2; }
    #detail-body { margin: 0; padding: 1 0; border: none; }
    #confirm-body { width: 72; height: auto; max-height: 80%; margin: 0; border: solid #58A6FF; }
    #confirm-actions { height: 3; align: right middle; }
    #confirm-actions Button { margin-left: 1; }
    #log-rail.-hidden { display: none; }
    #confirm-command { padding: 0 1; margin: 1 0; border: solid #30363D; background: #0D1117; color: #D29922; }
    #confirm-description { color: #8B949E; }
    #config-dialog { width: 68; height: auto; border: solid #30363D; background: #161B22; padding: 1 2; }
    #config-dialog Input { margin-top: 1; }
    #config-actions { height: 3; margin-top: 1; align: right middle; }
    #config-actions Button { margin-left: 1; }
    PaletteScreen { align: center middle; background: #000000 85%; }
    #palette-dialog { width: 74; height: auto; max-height: 75%; border: solid #58A6FF; background: #0D1117; padding: 1; }
    #palette-search-row { height: 3; margin-bottom: 1; }
    .palette-chevron { width: 3; color: #58A6FF; content-align: center middle; }
    #palette-search { width: 1fr; border: solid #58A6FF; }
    .keycap { width: 6; content-align: center middle; color: #8B949E; }
    #palette-options { height: auto; max-height: 20; background: #161B22; }
    #palette-footer { height: 1; color: #8B949E; margin-top: 1; }
    """ + PAGE_CSS + SIDEBAR_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+p", "open_palette", "Palette", priority=True),
        Binding("ctrl+r", "open_runner_default", "Runner", priority=True),
        Binding("?", "help", "Keys"),
        Binding("ctrl+c", "stop_command", "Stop", priority=True),
        Binding("r", "refresh_current", "Refresh"),
        Binding("ctrl+l", "toggle_rail", "Log rail"),
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
        name="msp-dark", primary="#58A6FF", secondary="#C9D1D9", warning="#D29922",
        error="#F85149", success="#3FB950", accent="#58A6FF", foreground="#C9D1D9",
        background="#0D1117", surface="#161B22", panel="#0D1117", boost="#21262D",
        dark=True, variables={"outline": "#30363D"},
    )

    def __init__(self, executor: Optional[Executor] = None) -> None:
        super().__init__()
        self.commands = load_commands()
        curated = load_pages()
        self.pages = {**curated, **fallback_pages(self.commands, curated)}
        self.templates = load_templates()
        self.labels = load_labels()
        self.nav = nav_entries(self.pages, self.labels["concerns"])
        self.page_executor = executor or executor_for(False)
        self._panes: dict[str, Union[PageView, RunnerPane]] = {}
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
            yield Button("⌘ Palette", id="open-palette", tooltip="Command palette (Ctrl+P)")
            yield Button("?", id="open-help", tooltip="Help")
            yield Button("Settings", id="open-config")
        with Horizontal(id="main-row"):
            yield Sidebar(self.nav, self.labels["concerns"])
            with Vertical(id="page"):
                pass
            with Vertical(id="log-rail"):
                with Vertical(id="execution-log-view"):
                    yield Label("$ msp · waiting for command", id="command-head", markup=False)
                    yield RichLog(id="command-log", markup=False, wrap=True, highlight=False)
                with Vertical(id="chat-ask-view"):
                    yield Label("CHAT / ASK", classes="eyebrow")
                    yield RichLog(id="chat-log", markup=False, wrap=True, highlight=False)
                    with Horizontal(id="chat-controls"):
                        yield Input(placeholder="Ask a question…", id="chat-input")
                        yield Button("Ask", id="ask-question", variant="primary")
        with Vertical(id="command-panel"):
            with Horizontal(id="command-controls"):
                yield Input(placeholder="msp command…", id="command-input")
                yield Button("Run", id="run-command", variant="primary")
                yield Button("Stop", id="stop-command", variant="error", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self.switch_view_id, "dashboard")

    def on_unmount(self) -> None:
        if self.current_broker is not None:
            self.current_broker.kill()

    def switch_view_id(self, view_id: str) -> None:
        """Show a page or legacy screen by nav key (``firewall``) or page id (``security.firewall``)."""
        view_id = nav_key(view_id)
        page_id = PAGE_ALIASES.get(view_id, view_id)
        page = self.pages.get(page_id)
        if page is None and view_id != "runner":
            return
        pane = self._panes.get(view_id)
        fresh = pane is None
        if pane is None:
            if page is not None:
                pane = PageView(page, self.commands, self.templates[page.page.template], self.labels, self.page_executor)
                pane.action_handler = self._page_action
            else:
                pane = RunnerPane(self)
            self._panes[view_id] = pane
            self.query_one("#page", Vertical).mount(pane)
        for other_id, other_pane in self._panes.items():
            other_pane.display = other_id == view_id
        self._current_id = view_id
        active_title = page.page.title if page else "Commands"
        self.sub_title = active_title
        self.query_one("#brand-right", Label).update(f"VIEW: {active_title.upper()}")
        self.query_one(Sidebar).mark_active(view_id)
        if isinstance(pane, PageView) and not fresh:
            pane.refresh_page(include_long=False)  # revisit: fresh fast reads, no repeat scan

    def _page_action(self, view: PageView, run_id: str, command: CommandSpec, args: dict[str, Any]) -> None:
        """Confirm, run through the command rail, then re-run the action's ``refreshes``."""
        line = shlex.join(build_argv(command, args))
        if command.risk == "read":
            # outbound read: confirm, then run inside the page so its slots fill
            reasons = []
            if command.active_network:
                reasons.append("This sends network traffic to other hosts (a scan or lookup).")
            if command.llm:
                reasons.append("This sends system data to the configured AI provider, which may be a cloud service.")
            if command.needs_root:
                reasons.append("macOS will ask for an administrator password.")
            if command.long_running:
                reasons.append("It can take a while.")
            self.push_screen(
                ConfirmScreen(line, " ".join(reasons) or "Run this command?"),
                lambda ok: view.start([run_id], force=True, args={run_id: args}) if ok else None,
            )
            return
        targets = view.refreshable(run_id)
        # --json: the rail shows the structured result, and follow-ups (a terminate
        # that left the process running offers a force quit) can read it
        line += " --json"
        detail = "This changes system settings."
        if command.needs_root:
            detail += " macOS will ask for an administrator password."
        if command.risk == "dangerous":
            detail = "This is destructive and may not be reversible. " + detail

        def decided(confirmed: Optional[bool]) -> None:
            if not confirmed:
                view.rerender()  # undo an optimistic switch flip
                return
            self.execute_commands([line], update_view=False,
                                  on_complete=lambda _results: view.start(targets, force=True) if targets else view.rerender())

        self.push_screen(ConfirmScreen(line, detail), decided)

    def on_open_page(self, message: OpenPage) -> None:
        self.switch_view_id(message.page_id)

    def on_run_started(self, message: RunStarted) -> None:
        self._append_output(f"$ {message.line}")

    def on_run_finished(self, message: RunFinished) -> None:
        result = message.result
        line = "msp " + " ".join(result.argv)
        if result.source == "live":
            status = f"exit {result.returncode}" if result.returncode is not None else "failed"
            self._record_command(" ".join(result.argv), result.returncode if result.returncode is not None else 1, result.elapsed)
            self._append_output(f"[{line} · {status} · {result.elapsed:.1f}s]" + (f" {result.failure}" if result.failure else ""))
        else:
            self._append_output(f"[{line} · replayed fixture]" + (f" {result.failure}" if result.failure else ""))

    def action_toggle_rail(self) -> None:
        self.query_one("#log-rail").toggle_class("-hidden")

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
        pane = self._panes.get(view_id or "")
        if isinstance(pane, PageView):
            pane.refresh_page()

    def action_open_runner_default(self) -> None:
        self.switch_view_id("runner")

    def open_runner(self, command: str) -> None:
        self.switch_view_id("runner")
        self.query_one("#command-input", Input).value = command
        self.query_one("#command-input", Input).focus()

    def open_help(self) -> None:
        self.push_screen(HelpScreen())

    def open_palette(self) -> None:
        palette = PaletteScreen([(entry.key, entry.title) for entry in self.nav])
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
            target, field = {
                "firewall-app": ("firewall", "#form-workspace-aside-2-path"),
                "startup-login": ("startup", "#form-workspace-aside-2-name"),
                "startup-agent": ("startup", "#form-workspace-aside-3-label"),
            }[form]
            self.switch_view_id(target)
            pane = self._panes[target]
            self.call_after_refresh(lambda: pane.query_one(field, Input).focus())

    def action_open_palette(self) -> None:
        self.open_palette()

    def action_help(self) -> None:
        self.open_help()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if event.button.has_class("nav-entry") and event.button.name:
            self.switch_view_id(event.button.name)
        elif button_id == "open-palette":
            self.open_palette()
        elif button_id == "open-help":
            self.open_help()
        elif button_id == "open-config":
            self.open_config()
        elif button_id == "run-command":
            self.submit_command()
        elif button_id == "ask-question":
            self.submit_question()
        elif button_id == "stop-command":
            self.action_stop_command()
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
        """Tabs are gone — the rail shows logs and chat together; just focus the log."""
        self.query_one("#command-log", RichLog).scroll_end(animate=False)

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

    def execute_commands(
        self, commands: list[str], update_view: bool = True, view_id: Optional[str] = None,
        chat_prompt: Optional[str] = None, on_complete: Optional[Any] = None,
    ) -> None:
        if self._command_busy:
            self._append_output("A command is already running.")
            if on_complete is not None:
                on_complete({})
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
            if on_complete is not None:
                self.call_from_thread(on_complete, results)

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
