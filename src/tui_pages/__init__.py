"""Render manifest pages (src/tui_manifest/pages/*.toml) in the TUI.

  runtime.py     execute runs (live / replay), RunScheduler (waves, triggers, refreshes)
  components.py  generic slot components; display text comes from props + labels.toml
  page.py        PageView: the page frame, async run delivery, action previews
  shell.py       Sidebar: concerns ▸ pages for MspTUI
"""
from src.tui_pages.components import COMPONENTS, ActionRequested, OpenPage, PageContext, RowSelected
from src.tui_pages.page import PAGE_CSS, ActionPreviewed, PageView, RunFinished, RunStarted
from src.tui_pages.runtime import (
    RunResult, RunScheduler, build_argv, execute, executor_for, preview_command, run_live, run_replay,
)

__all__ = [
    "COMPONENTS", "ActionPreviewed", "ActionRequested", "OpenPage", "PAGE_CSS", "PageContext", "PageView",
    "RowSelected", "RunFinished", "RunResult", "RunScheduler", "RunStarted", "build_argv", "execute",
    "executor_for", "preview_command", "run_live", "run_replay",
]
