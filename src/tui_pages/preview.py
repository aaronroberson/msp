"""Preview a manifest page in the terminal.

    .venv/bin/python -m src.tui_pages.preview security.firewall [--replay]

``--replay`` renders the committed sanitized fixtures instead of running the
CLI. Actions are previewed only; nothing that changes the system runs.
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional

from textual.app import App, ComposeResult
from textual.widgets import Footer

from src.tui_manifest import load_commands, load_pages
from src.tui_pages import PAGE_CSS, PageView, RunResult, execute


class PagePreviewApp(App[None]):
    CSS = PAGE_CSS
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    def __init__(self, page_id: str, replay: bool) -> None:
        super().__init__()
        self.page = load_pages()[page_id]
        self.commands = load_commands()
        self.replay = replay
        self.title = f"msp · {self.page.page.title}"

    def _run_on_open(self) -> Dict[str, RunResult]:
        results: Dict[str, RunResult] = {}
        for run in sorted(self.page.runs, key=lambda r: r.order):
            command = self.commands[run.command]
            if run.trigger == "on_open" and command.risk == "read":
                results[run.id] = execute(run.id, command, replay=self.replay)  # each run executes once
        return results

    def compose(self) -> ComposeResult:
        yield PageView(self.page, self.commands, self._run_on_open())
        yield Footer()

    def action_refresh(self) -> None:
        self.query_one(PageView).remove()
        self.mount(PageView(self.page, self.commands, self._run_on_open()), before=self.query_one(Footer))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Preview a manifest page")
    parser.add_argument("page", nargs="?", default="security.firewall")
    parser.add_argument("--replay", action="store_true", help="Render committed fixtures instead of running msp")
    args = parser.parse_args(argv)
    PagePreviewApp(args.page, args.replay).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
