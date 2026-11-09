"""Native macOS application firewall controls."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

SOCKETFILTERFW = "/usr/libexec/ApplicationFirewall/socketfilterfw"


def _run(argv: list[str], privileged: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a fixed socketfilterfw operation, using the native macOS auth prompt."""
    if privileged and os.geteuid() != 0:
        if sys.platform != "darwin":
            raise RuntimeError("Firewall changes require macOS administrator authorization")
        shell_command = shlex.join(argv)
        applescript = f"do shell script {json.dumps(shell_command)} with administrator privileges"
        return subprocess.run(["/usr/bin/osascript", "-e", applescript], capture_output=True, text=True, check=False)
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def status() -> dict[str, Any]:
    keys = {
        "enabled": "--getglobalstate",
        "stealth_mode": "--getstealthmode",
        "block_all": "--getblockall",
        "allows_signed": "--getallowsigned",
        "allows_signed_app": "--getallowsigned",
    }
    result: dict[str, Any] = {"available": Path(SOCKETFILTERFW).exists(), "apps": []}
    if not result["available"]:
        return result
    for key, option in keys.items():
        proc = _run([SOCKETFILTERFW, option])
        text = (proc.stdout + proc.stderr).strip()
        if key == "allows_signed":
            state_line = next((line for line in text.splitlines() if "built-in signed" in line.lower()), text)
            result[key] = "enabled" in state_line.lower() if proc.returncode == 0 else None
        elif key == "allows_signed_app":
            state_line = next((line for line in text.splitlines() if "downloaded signed" in line.lower()), "")
            result[key] = "enabled" in state_line.lower() if proc.returncode == 0 and state_line else None
        else:
            result[key] = ("enabled" in text.lower() or "is on" in text.lower() or text.lower().endswith("on")) if proc.returncode == 0 else None
        if proc.returncode:
            result[f"{key}_error"] = text
    apps = _run([SOCKETFILTERFW, "--listapps"])
    result["apps_output"] = (apps.stdout + apps.stderr).strip()
    return result


def set_option(name: str, value: bool) -> dict[str, Any]:
    option = {"enabled": "--setglobalstate", "stealth_mode": "--setstealthmode", "block_all": "--setblockall", "allows_signed": "--setallowsigned", "allows_signed_app": "--setallowsignedapp"}.get(name)
    if not option:
        raise ValueError(f"Unsupported firewall option: {name}")
    proc = _run([SOCKETFILTERFW, option, "on" if value else "off"], privileged=True)
    return {"ok": proc.returncode == 0, "option": name, "value": value, "output": (proc.stdout + proc.stderr).strip()}


def app_action(action: str, app_path: str) -> dict[str, Any]:
    if action not in {"add", "remove", "block", "unblock"}:
        raise ValueError("App action must be add, remove, block, or unblock")
    path = Path(app_path).expanduser().resolve()
    if action != "remove" and not path.exists():
        raise ValueError(f"Application path does not exist: {path}")
    option = {"add": "--add", "remove": "--remove", "block": "--blockapp", "unblock": "--unblockapp"}[action]
    proc = _run([SOCKETFILTERFW, option, str(path)], privileged=True)
    return {"ok": proc.returncode == 0, "action": action, "path": str(path), "output": (proc.stdout + proc.stderr).strip()}


def interactive_menu() -> None:
    """Small CLI menu that exposes the same supported firewall operations."""
    while True:
        print("\nFirewall: [s]tatus, [e]nable, [d]isable, [t]oggle stealth, [b]lock all, [q]uit")
        choice = input("Action: ").strip().lower()
        try:
            if choice == "q":
                return
            if choice == "s":
                result = status()
            elif choice in {"e", "d"}:
                result = set_option("enabled", choice == "e")
            elif choice == "t":
                value = input("Stealth mode [on/off]: ").strip().lower()
                result = set_option("stealth_mode", value == "on")
            elif choice == "b":
                value = input("Block all incoming connections [on/off]: ").strip().lower()
                result = set_option("block_all", value == "on")
            else:
                print("Choose s, e, d, t, b, or q.")
                continue
            print(json.dumps(result, indent=2))
        except (OSError, RuntimeError, ValueError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Manage the macOS application firewall")
    parser.add_argument("--json", action="store_true", help="Emit JSON output (default output is also JSON)")
    sub = parser.add_subparsers(dest="action")
    status_parser = sub.add_parser("status", help="Show firewall settings")
    status_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output")
    set_parser = sub.add_parser("set", help="Change a firewall setting")
    set_parser.add_argument("option", choices=["enabled", "stealth_mode", "block_all", "allows_signed", "allows_signed_app"])
    set_parser.add_argument("value", choices=["on", "off"])
    set_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output")
    app_parser = sub.add_parser("app", help="Manage an application rule")
    app_parser.add_argument("operation", choices=["add", "remove", "block", "unblock"])
    app_parser.add_argument("path")
    app_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Emit JSON output")
    args = parser.parse_args(argv)
    if args.action is None:
        interactive_menu()
        return
    try:
        result = status() if args.action == "status" else set_option(args.option, args.value == "on") if args.action == "set" else app_action(args.operation, args.path)
        print(json.dumps(result, indent=2))
        if isinstance(result, dict) and result.get("ok") is False:
            raise SystemExit(1)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
