"""Auto-generated fallback pages (plan D14).

Every command without a curated page gets a place on a generated page for its
command group, so the whole CLI is reachable from the TUI while pages are
still being designed. Each command gets a form (its arguments, or just a Run
button) and, for reads, a panel showing its output with the default component
for its envelope. Mutations go through the shell's confirm path; their output
appears in the command rail.

Fallback pages are badged "Auto-generated · not yet designed" and never count
as coverage (``PageMeta.fallback``).
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.tui_manifest import CommandSpec, PageSpec

FALLBACK_CONCERN = "fallback"

# Default component per envelope kind (a curated page may choose differently).
DEFAULT_COMPONENT = {
    "collection": "RecordTable",
    "findings": "FindingList",
    "definitions": "DefinitionCatalog",
    "diff": "RecordTable",
    "run": "RecordTable",
    "item": "ReportView",
    "result": "ReportView",
    "document": "ReportView",
}


def _unavailable(command: CommandSpec) -> str:
    if command.envelope_kind == "stream":
        return "Live output: this streams until stopped, which the live panel (Phase 4) will handle. Use the command runner below meanwhile."
    if command.interactive:
        return "Interactive: this needs a terminal. Use the command runner below."
    return ""


def fallback_pages(commands: Dict[str, CommandSpec], curated: Dict[str, PageSpec]) -> Dict[str, PageSpec]:
    """One generated page per command group for commands no curated page runs."""
    placed = {run.command for page in curated.values() if not page.page.fallback for run in page.runs}
    groups: Dict[str, List[CommandSpec]] = {}
    for command in commands.values():
        if command.id not in placed:
            groups.setdefault(command.group, []).append(command)
    pages: Dict[str, PageSpec] = {}
    for order, (group, members) in enumerate(sorted(groups.items()), start=1):
        runs: List[Dict[str, Any]] = []
        slots: List[Dict[str, Any]] = []
        for command in members:
            run_id = command.id.replace(".", "_").replace("-", "_")
            runs.append({"id": run_id, "command": command.id, "trigger": "on_action"})
            line = "msp " + " ".join(command.argv)
            props: Dict[str, Any] = {
                "title": line,
                "submit": ("Run" if command.risk == "read" else command.argv[-1].replace("-", " ").capitalize() + "…")
                          + (" ↗" if command.active_network or command.llm else ""),
            }
            reason = _unavailable(command)
            if reason:
                props["unavailable"] = reason
            slots.append({"region": "workspace.main", "order": len(slots) + 1, "component": "ActionForm",
                          "actions": [run_id], "props": props})
            if command.risk == "read" and not reason:
                slots.append({"region": "workspace.main", "order": len(slots) + 1,
                              "component": DEFAULT_COMPONENT.get(command.envelope_kind, "ReportView"),
                              "run": run_id, "props": {"empty": f"Run {line} to see its output."}})
        page = PageSpec.model_validate({
            "page": {"id": f"fallback.{group}", "concern": FALLBACK_CONCERN, "title": group,
                     "order": order, "template": "review", "fallback": True},
            "runs": runs,
            "slots": slots,
        })
        pages[page.page.id] = page
    return pages
