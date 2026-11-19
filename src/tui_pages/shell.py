"""Sidebar for the msp shell: concern sections ▸ pages (plan §4.1, D4).

Entries come from the manifest pages plus the legacy screens that have no
manifest page yet (Phase 2 replaces those). Each entry has a *nav key*: the
legacy view id where one exists (so ``switch_view_id("firewall")``, number
keys and links keep working), otherwise the page id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Label

from src.tui_manifest import PageSpec

# Manifest pages that replaced a legacy screen keep that screen's nav key.
PAGE_ALIASES: Dict[str, str] = {
    "dashboard": "overview.dashboard",
    "privacy": "privacy.settings",
    "firewall": "security.firewall",
    "listening": "monitoring.network",
    "startup": "system.startup",
    "tcc": "privacy.tcc",
    "findings": "security.scans",
    "snapshots": "forensics.snapshots",
    "workflows": "automation.workflows",
    "ai": "automation.ai",
}

# (nav key, concern, title, order) for screens not yet expressed as manifest pages.
LEGACY_ENTRIES = (
    ("runner", "overview", "Command runner", 9),
)


@dataclass(frozen=True)
class NavEntry:
    key: str          # nav key (button id suffix, switch_view_id argument)
    concern: str
    title: str
    order: int
    page_id: Optional[str] = None   # manifest page, or None for a legacy screen


def nav_key(page_id: str) -> str:
    return next((alias for alias, target in PAGE_ALIASES.items() if target == page_id), page_id)


def nav_entries(pages: Dict[str, PageSpec], concerns: Dict[str, str]) -> List[NavEntry]:
    entries = [NavEntry(nav_key(p.page.id), p.page.concern, p.page.title, p.page.order, p.page.id)
               for p in pages.values()]
    entries += [NavEntry(*legacy) for legacy in LEGACY_ENTRIES]
    rank = {concern: i for i, concern in enumerate(concerns)}
    return sorted(entries, key=lambda e: (rank.get(e.concern, len(rank)), e.order, e.title))


def dom_id(key: str) -> str:
    return "nav-" + key.replace(".", "-")


class Sidebar(VerticalScroll):
    def __init__(self, entries: List[NavEntry], concerns: Dict[str, str], **kw) -> None:
        super().__init__(id="sidebar", **kw)
        self.entries, self.concerns = entries, concerns

    def compose(self) -> ComposeResult:
        current = None
        for entry in self.entries:
            if entry.concern != current:
                current = entry.concern
                yield Label(self.concerns.get(current, current).upper(), classes="nav-section")
            yield Button(entry.title, id=dom_id(entry.key), name=entry.key, classes="nav-entry")

    def mark_active(self, key: str) -> None:
        for button in self.query(".nav-entry"):
            button.set_class(button.name == key, "-active")


SIDEBAR_CSS = """
#sidebar { width: 24; background: #0D1117; border-right: solid #30363D; padding: 0 1; }
.nav-section { color: #6E7681; text-style: bold; margin-top: 1; }
.nav-entry { width: 100%; height: 1; min-width: 0; border: none; background: transparent; color: #8B949E;
             content-align: left middle; text-align: left; padding: 0 1; }
.nav-entry:hover { background: #161B22; color: #F0F6FC; border: none; }
.nav-entry:focus { border: none; color: #58A6FF; }
.nav-entry.-active { background: #1F2B3A; color: #58A6FF; text-style: bold; border: none; }
"""
