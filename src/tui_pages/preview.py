"""Preview one manifest page on its own (outside the full shell).

    .venv/bin/python -m src.tui_pages.preview security.firewall [--replay]

Run it in a real terminal. ``--replay`` renders the committed sanitized
fixtures instead of running the CLI. Mutating actions are previewed only.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from textual.app import App, ComposeResult
from textual.widgets import Footer

from src.tui_manifest import load_commands, load_labels, load_pages, load_templates
from src.tui_pages.page import PAGE_CSS, PageView
from src.tui_pages.runtime import Executor, executor_for


class PagePreviewApp(App[None]):
    CSS = "Screen { background: #0D1117; color: #C9D1D9; }\n" + PAGE_CSS
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    def __init__(self, page_id: str, replay: bool = False, executor: Optional[Executor] = None) -> None:
        super().__init__()
        self.page = load_pages()[page_id]
        self.commands = load_commands()
        self.templates = load_templates()
        self.labels = load_labels()
        self.executor = executor or executor_for(replay)
        self.title = f"msp · {self.page.page.title}"

    def compose(self) -> ComposeResult:
        yield PageView(self.page, self.commands, self.templates[self.page.page.template], self.labels, self.executor)
        yield Footer()

    def action_refresh(self) -> None:
        self.query_one(PageView).refresh_page()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Preview a manifest page")
    parser.add_argument("page", nargs="?", default="security.firewall")
    parser.add_argument("--replay", action="store_true", help="Render committed fixtures instead of running msp")
    args = parser.parse_args(argv)
    PagePreviewApp(args.page, args.replay).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
