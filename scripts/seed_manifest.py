#!/usr/bin/env python3
"""Seed the TUI command manifest by introspecting every CLI module's argparse parser.

Most modules build their parser inside ``main()``. We patch
``ArgumentParser.parse_args``/``parse_known_args`` to raise as soon as the
top-level parser is about to parse, capture that parser, and never run the
module's own logic. The output is a machine-generated *draft*
(``src/tui_manifest/commands.seed.json``); curation happens in
``commands.toml``. Re-run after CLI changes:

    .venv/bin/python scripts/seed_manifest.py [--check]

``--check`` exits 1 if the committed seed is stale (used by tests/CI).
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SEED_PATH = REPO / "src" / "tui_manifest" / "commands.seed.json"

# CLI group -> module. Mirrors src/main.py COMMAND_MODULES plus the
# privacy_settings aliases (status/list/enable/disable/preset/services).
GROUPS: Dict[str, str] = {
    "privacy": "privacy_settings",
    "net": "network",
    "startup": "startup",
    "firewall": "firewall",
    "fswatch": "fswatch",
    "traffic": "traffic",
    "scan": "scanner",
    "tcc": "tcc",
    "audit": "rules",
    "interrogate": "facts",
    "reason": "llm",
    "remediate": "remediate",
    "report": "report",
    "workflow": "workflows",
    "snapshot": "snapshot",
    "sharing": "sharing",
    "security": "security",
    "ai": "ai",
    "chain": "chain",
    "deps": "deps",
    "tune": "tune",
    "forensics": "forensics",
}

# Names of the positional that selects the action in flat-action modules.
ACTION_DESTS = {"action", "command", "subcommand"}
GLOBAL_DESTS = {"help", "json", "verbose", "sort"}


class _Captured(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        self.parser = parser


def capture_parser(module_name: str) -> argparse.ArgumentParser:
    module = importlib.import_module(f"src.{module_name}")
    original_parse_args = argparse.ArgumentParser.parse_args
    original_parse_known = argparse.ArgumentParser.parse_known_args

    def _capture(self: argparse.ArgumentParser, *_a: Any, **_k: Any) -> Any:
        raise _Captured(self)

    argparse.ArgumentParser.parse_args = _capture  # type: ignore[assignment]
    argparse.ArgumentParser.parse_known_args = _capture  # type: ignore[assignment]
    saved_argv = sys.argv
    sys.argv = [f"msp-{module_name}", "__seed_probe__"]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                main = getattr(module, "main")
                try:
                    main(["__seed_probe__"])
                except TypeError:
                    main()
            except _Captured as captured:
                return captured.parser
    finally:
        argparse.ArgumentParser.parse_args = original_parse_args  # type: ignore[assignment]
        argparse.ArgumentParser.parse_known_args = original_parse_known  # type: ignore[assignment]
        sys.argv = saved_argv
    raise RuntimeError(f"{module_name}.main() never reached parse_args")


def _arg(action: argparse.Action) -> Optional[Dict[str, Any]]:
    if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
        return None
    if action.dest in GLOBAL_DESTS:
        return None
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        kind = "flag"
    elif action.choices:
        kind = "choice"
    elif action.type is int:
        kind = "int"
    else:
        kind = "text"
    entry: Dict[str, Any] = {
        "name": action.dest,
        "kind": kind,
        "positional": not action.option_strings,
        "option": action.option_strings[-1] if action.option_strings else None,
        "required": bool(action.required) or (not action.option_strings and action.nargs not in ("?", "*")),
        "help": action.help or "",
    }
    if action.choices:
        entry["choices"] = sorted(str(c) for c in action.choices)
    if action.default not in (None, False, argparse.SUPPRESS):
        entry["default"] = action.default
    if action.nargs in ("*", "+") or isinstance(action, argparse._AppendAction):
        entry["multi"] = True
    return entry


def _walk_subparsers(sub_action: argparse._SubParsersAction, prefix: str = "") -> List[Dict[str, Any]]:
    """Flatten (possibly nested) subparsers into 'parent child' action names."""
    found: List[Dict[str, Any]] = []
    for name, sub in sub_action.choices.items():
        full = f"{prefix}{name}"
        nested = [a for a in sub._actions if isinstance(a, argparse._SubParsersAction)]
        args = [a for a in (_arg(x) for x in sub._actions) if a]
        selector = next((a for a in args if a["positional"] and a["name"] in ACTION_DESTS and a.get("choices")), None)
        if selector and not nested:
            # flat action positional inside a subparser (e.g. `privacy preset apply`)
            rest = [a for a in args if a is not selector]
            for choice in selector["choices"]:
                found.append({"action": f"{full} {choice}", "args": [], "args_source": "unassigned",
                              "shared_args": rest})
            continue
        if nested:
            for child in nested:
                found.extend(_walk_subparsers(child, prefix=f"{full} "))
            if args:  # the parent itself is also runnable with its own options
                found.append({"action": full, "args": args, "args_source": "subparser"})
        else:
            found.append({"action": full, "args": args, "args_source": "subparser"})
    return found


# Commands dispatched by src/main.py itself rather than a module parser.
MAIN_DISPATCHED: List[Dict[str, Any]] = [
    {"group": "shell", "module": "main", "style": "main", "shared_args": [], "actions": [
        {"action": "audit", "args": [], "args_source": "module:shell_audit_cli"},
        {"action": "repair", "args": [], "args_source": "module:shell_audit_cli (--fix-only)"},
    ]},
    {"group": "config", "module": "main", "style": "main", "shared_args": [], "actions": [
        {"action": "list", "args": [], "args_source": "main"},
        {"action": "set", "args": [
            {"name": "key", "kind": "text", "positional": True, "option": None, "required": True, "help": "section.key"},
            {"name": "value", "kind": "text", "positional": True, "option": None, "required": True, "help": ""},
        ], "args_source": "main"},
    ]},
    {"group": "ask", "module": "main", "style": "main", "shared_args": [], "actions": [
        {"action": "", "args": [
            {"name": "prompt", "kind": "text", "positional": True, "option": None, "required": True,
             "multi": True, "help": "Question; system diagnostics are attached as context"},
        ], "args_source": "main"},
    ]},
    {"group": "doctor", "module": "main", "style": "main", "shared_args": [], "actions": [
        {"action": "", "args": [], "args_source": "main (deps.doctor)"},
        {"action": "fix", "args": [
            {"name": "dry_run", "kind": "flag", "positional": False, "option": "--dry-run", "required": False, "help": ""},
            {"name": "yes", "kind": "text", "positional": False, "option": "--yes", "required": False, "help": "approval token"},
        ], "args_source": "main (doctor_fix_gate)"},
    ]},
]

# Interactive-only entry points: deliberately not part of the command surface.
EXCLUDED = {
    "tui": "the TUI itself (the shell)",
    "cli": "legacy interactive menu", "console": "legacy interactive menu", "menu": "legacy interactive menu",
}


def describe(group: str, module_name: str) -> Dict[str, Any]:
    parser = capture_parser(module_name)
    shared_args: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    style = "single"

    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            style = "subparsers"
            actions.extend(_walk_subparsers(action))
        elif not action.option_strings and action.dest in ACTION_DESTS and action.choices:
            style = "flat"
            for choice in action.choices:
                if choice == "":
                    continue
                actions.append({"action": str(choice), "args": [], "args_source": "unassigned"})
        else:
            arg = _arg(action)
            if arg:
                shared_args.append(arg)

    if style == "single":
        actions.append({"action": "", "args": shared_args, "args_source": "parser"})
        shared_args = []

    return {
        "group": group,
        "module": module_name,
        "style": style,
        # flat style: options on the one parser, not attributed to any action
        # (the gap curation fills, plan §1.2)
        "shared_args": shared_args,
        "actions": actions,
    }


def build_seed() -> Dict[str, Any]:
    groups = [describe(group, module) for group, module in GROUPS.items()]
    shell_parser = capture_parser("shell_audit_cli")
    shell_args = [a for a in (_arg(x) for x in shell_parser._actions) if a]
    for entry in MAIN_DISPATCHED:
        entry = json.loads(json.dumps(entry))
        if entry["group"] == "shell":
            for action in entry["actions"]:
                action["args"] = [a for a in shell_args if not (action["action"] == "repair" and a["name"] == "fix_only")]
        groups.append(entry)
    return {
        "generated_by": "scripts/seed_manifest.py",
        "note": "Machine-generated draft. Do not edit; curate in commands.toml.",
        "excluded": EXCLUDED,
        "groups": groups,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Fail if the committed seed is stale")
    args = parser.parse_args(argv)
    rendered = json.dumps(build_seed(), indent=2, sort_keys=False, default=str) + "\n"
    if args.check:
        current = SEED_PATH.read_text() if SEED_PATH.exists() else ""
        if current != rendered:
            print(f"{SEED_PATH.relative_to(REPO)} is stale; run scripts/seed_manifest.py", file=sys.stderr)
            return 1
        return 0
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEED_PATH.write_text(rendered)
    seed = json.loads(rendered)
    total = sum(len(g["actions"]) for g in seed["groups"])
    print(f"wrote {SEED_PATH.relative_to(REPO)}: {len(seed['groups'])} groups, {total} actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
