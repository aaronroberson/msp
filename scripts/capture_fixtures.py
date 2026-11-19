#!/usr/bin/env python3
"""Capture `msp --json` output of read-only commands as contract-test fixtures.

Two outputs per capture:
  tests/fixtures/cli/live/<id>.json  raw host data, gitignored, never committed
  tests/fixtures/cli/<id>.json       sanitized (identity, network identifiers,
                                     serials replaced; long lists truncated)

Only passive, local, read-only commands are listed in CAPTURES. Excluded on
purpose: anything that mutates state, streams forever, needs sudo, touches the
network beyond this host (nmap, camsweep, lookup), or calls an LLM (ask, ai
ask/analyze/explain/suggest/compare, reason) because that would send host data
to a remote provider.

    .venv/bin/python scripts/capture_fixtures.py [--only ID[,ID...]] [--workers N]
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
MSP = [PYTHON, str(REPO / "src" / "main.py")]
FIXTURES = REPO / "tests" / "fixtures" / "cli"
LIVE = FIXTURES / "live"
WORK = Path(tempfile.gettempdir()) / "msp-fixture-work"
MAX_LIST = 8

Argv = Union[List[str], Callable[[Dict[str, Any]], Optional[List[str]]]]


def _first(results: Dict[str, Any], capture_id: str, path: Sequence[Any]) -> Optional[Any]:
    value = results.get(capture_id, {}).get("json")
    for key in path:
        if isinstance(key, int):
            if not isinstance(value, list) or len(value) <= key:
                return None
        elif not isinstance(value, dict):
            return None
        value = value[key]
    return value


# id -> (argv after `msp --json`, timeout seconds, depends_on)
CAPTURES: Dict[str, tuple] = {
    # privacy
    "privacy.status": (["status"], 60, ()),
    "privacy.list": (["list"], 60, ()),
    "privacy.services_list": (["services", "list"], 60, ()),
    "privacy.preset_list": (["preset", "list"], 60, ()),
    # net (local only)
    "net.list": (["net", "list"], 60, ()),
    "net.established": (["net", "established"], 60, ()),
    "net.arp": (["net", "arp"], 60, ()),
    # net hosts is NOT passive: it runs `nmap -sn` across the local subnet.
    # Its fixture (tests/fixtures/cli/net.hosts.json) was captured once on
    # 2026-11-18 and is kept for the Collection[Host] shape; do not re-run here.
    "net.inspect": (lambda r: ["net", "inspect", "--pid", str(_first(r, "net.list", [0, "pid"]))]
                    if _first(r, "net.list", [0, "pid"]) else None, 60, ("net.list",)),
    # startup
    **{f"startup.{a.replace('-', '_')}": (["startup", a], 240 if a in {"inventory", "comprehensive-audit"} else 90, ())
       for a in ("list", "managed", "login-items", "agents", "daemons", "cron", "summary",
                 "running", "disabled", "audit", "inventory", "comprehensive-audit")},
    # firewall / sharing / security
    "firewall.status": (["firewall", "status"], 60, ()),
    "sharing.list": (["sharing", "list"], 60, ()),
    "sharing.status": (["sharing", "status"], 60, ()),
    "security.status": (["security", "status"], 60, ()),
    # fswatch (no watch/system streams; diff writes a baseline)
    "fswatch.recent": (["fswatch", "recent", "5"], 60, ()),
    "fswatch.new": (["fswatch", "new"], 120, ()),
    "fswatch.audit": (["fswatch", "audit"], 120, ()),
    # traffic (dns/http need sudo tcpdump; capture/stream are streams)
    "traffic.summary": (["traffic", "summary"], 60, ()),
    # scan (deep omitted: same envelope as quick, ~5 min)
    "scan.quick": (["scan", "quick"], 300, ()),
    "scan.suspicious": (["scan", "suspicious"], 300, ()),
    "scan.verify": (["scan", "verify", "/System/Applications/Calculator.app"], 120, ()),
    "scan.signature": (["scan", "signature", "/System/Applications/Calculator.app"], 120, ()),
    "scan.report": (["scan", "report"], 60, ("scan.quick",)),
    # tcc
    "tcc.list": (["tcc", "list"], 60, ()),
    "tcc.audit": (["tcc", "audit"], 60, ()),
    "tcc.show": (["tcc", "show", "kTCCServiceCamera"], 60, ()),
    # analysis pipeline (local; no LLM)
    "interrogate": (["interrogate", "--output", str(WORK / "facts.json")], 240, ()),
    "audit": (["audit", str(WORK / "facts.json"), "--format", "json"], 120, ("interrogate",)),
    "remediate.plan": (["remediate", "plan", str(WORK / "findings.json"), "--output", str(WORK / "plan.json")],
                       120, ("audit",)),
    "remediate.apply_preview": (["remediate", "apply", str(WORK / "plan.json")], 120, ("remediate.plan",)),
    "report": (["report", "--facts", str(WORK / "facts.json"), "--findings", str(WORK / "findings.json"),
                "--format", "md", "--output", str(WORK / "report.md")], 120, ("audit",)),
    # workflows / chains / snapshots
    "workflow.list": (["workflow", "list"], 60, ()),
    "workflow.show": (["workflow", "show", "daily"], 60, ()),
    "workflow.run_dry": (["workflow", "run", "daily", "--dry-run", "--no-reason"], 60, ()),
    "chain.list": (["chain", "list"], 60, ()),
    "snapshot.list": (["snapshot", "list"], 60, ()),
    "snapshot.diff": (lambda r: ["snapshot", "diff", str(_first(r, "snapshot.list", [0, "name"]))]
                      if _first(r, "snapshot.list", [0, "name"]) else None, 120, ("snapshot.list",)),
    # ai (local listings only)
    "ai.providers": (["ai", "providers"], 60, ()),
    "ai.devices": (["ai", "devices"], 60, ()),
    # maintenance
    "deps.status": (["deps", "status"], 60, ()),
    "deps.check": (["deps", "check", "jq"], 60, ()),
    "doctor": (["doctor"], 120, ()),
    "tune.check": (["tune", "check"], 300, ()),
    "tune.top": (["tune", "top"], 60, ()),
    "config.list": (["config", "list"], 30, ()),
    "shell.audit": (["shell", "audit", "--json"], 120, ()),
}


# --------------------------------------------------------------------------
# Sanitizer
# --------------------------------------------------------------------------

def _cmd(argv: List[str]) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def sensitive_tokens() -> Dict[str, str]:
    """Literal host-identifying strings -> replacement."""
    user = getpass.getuser()
    tokens: Dict[str, str] = {str(Path.home()): "/Users/user", user: "user"}
    full_name = _cmd(["id", "-F"])
    if full_name:
        tokens[full_name] = "Example User"
        parts = full_name.split()
        if len(parts) > 1 and len(parts[-1]) > 3:
            tokens[parts[-1]] = "User"
    for name in {_cmd(["scutil", "--get", key]) for key in ("ComputerName", "LocalHostName", "HostName")} | {socket.gethostname()}:
        if name and name.lower() not in {"localhost", ""}:
            tokens[name] = "example-host"
            tokens[name.split(".")[0]] = "example-host"
    serial = re.search(r'"IOPlatformSerialNumber" = "([^"]+)"', _cmd(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"]))
    if serial:
        tokens[serial.group(1)] = "SERIAL"
    # longest first so full name wins over its parts
    return dict(sorted(tokens.items(), key=lambda kv: -len(kv[0])))


PATTERNS = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
     "00000000-0000-0000-0000-000000000000"),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2}\b"), "00:00:00:00:00:00"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "user@example.com"),
    (re.compile(r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?:\d{1,3}\.){3}\d{1,3}\b"), "192.0.2.1"),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b"), "2001:db8::1"),
]


def sanitize_text(text: str, tokens: Dict[str, str]) -> str:
    for literal, replacement in tokens.items():
        text = text.replace(literal, replacement)
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def sanitize(value: Any, tokens: Dict[str, str]) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, tokens)
    if isinstance(value, list):
        return [sanitize(item, tokens) for item in value[:MAX_LIST]]
    if isinstance(value, dict):
        return {sanitize_text(str(k), tokens): sanitize(v, tokens) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------

# Commands whose real output is a file they write (--output); read it back.
ARTIFACTS: Dict[str, Path] = {
    "interrogate": WORK / "facts.json",
    "remediate.plan": WORK / "plan.json",
    "report": WORK / "report.md",
}


def _read_artifact(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"path": path.name, "missing": True}
    text = path.read_text(errors="replace")
    parsed = _parse_json(text) if path.suffix == ".json" else None
    return {"path": path.name, "json": parsed, "text": None if parsed is not None else text[:4000]}


def _parse_json(stdout: str) -> Optional[Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char in "[{":
            try:
                value, _ = decoder.raw_decode(stdout[index:])
                return value
            except json.JSONDecodeError:
                continue
    return None


def run_capture(capture_id: str, argv: List[str], timeout: int) -> Dict[str, Any]:
    full = [*MSP, "--json", *argv]
    started = time.monotonic()
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, cwd=REPO, env={**os.environ, "NO_COLOR": "1"})
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        code, out, err = None, (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), "TIMEOUT"
    parsed = _parse_json(out)
    leading = out[: out.find("[") if parsed is not None and out.find("[") >= 0 else 0]
    return {
        "id": capture_id,
        "argv": ["msp", "--json", *argv],
        "returncode": code,
        "duration_s": round(time.monotonic() - started, 2),
        "json": parsed,
        "text": None if parsed is not None else out[:4000],
        "stdout_has_preamble": bool(parsed is not None and out.lstrip()[:1] not in ("[", "{")),
        "stderr": err[-2000:],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="Comma-separated capture ids")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    wanted = set(args.only.split(",")) if args.only else set(CAPTURES)
    LIVE.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    tokens = sensitive_tokens()
    results: Dict[str, Dict[str, Any]] = {}
    for path in LIVE.glob("*.json"):  # dependencies may come from an earlier run
        results[path.stem] = json.loads(path.read_text())

    pending = {cid: spec for cid, spec in CAPTURES.items() if cid in wanted}
    # audit's findings feed later pipeline steps
    while pending:
        # a dependency is satisfied only once it is captured in this run
        # (or, when not being recaptured, by an earlier run's live result)
        ready = {cid: spec for cid, spec in pending.items()
                 if all(dep not in pending and dep in results for dep in spec[2] if dep in CAPTURES)}
        if not ready:
            print(f"unresolvable dependencies: {sorted(pending)}", file=sys.stderr)
            return 1
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {}
            for cid, (spec_argv, timeout, _deps) in ready.items():
                resolved = spec_argv(results) if callable(spec_argv) else spec_argv
                if resolved is None:
                    print(f"skip {cid}: dependency produced no usable value")
                    continue
                futures[cid] = pool.submit(run_capture, cid, resolved, timeout)
            for cid, future in futures.items():
                result = future.result()
                if cid in ARTIFACTS:
                    result["artifact"] = _read_artifact(ARTIFACTS[cid])
                results[cid] = result
                if cid == "audit" and result["json"] is not None:
                    (WORK / "findings.json").write_text(json.dumps(result["json"]))
                (LIVE / f"{cid}.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
                clean = sanitize(result, tokens)
                (FIXTURES / f"{cid}.json").write_text(json.dumps(clean, indent=2, default=str) + "\n")
                shape = type(result["json"]).__name__ if result["json"] is not None else "TEXT"
                print(f"{cid:<28} rc={result['returncode']!s:<5} {result['duration_s']:>6}s  {shape}")
        for cid in ready:
            pending.pop(cid, None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
