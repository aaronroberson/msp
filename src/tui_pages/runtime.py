"""Run execution and scheduling for manifest pages (plan §3.4, §4.2).

``RunScheduler`` decides *which* runs execute and in *what order*; it is plain
Python so it can be tested without Textual. Pages call it from a thread worker.

Invariants
* Each run executes at most once per page visit; every slot bound to it reads
  the cached result (one ``firewall status`` feeds strip, toggles and table).
* Only ``risk = "read"`` commands execute. Mutations are previewed until the
  confirm/askpass path lands (Phase 3); asking the scheduler to execute one
  raises ``PermissionError``.
* ``refreshes`` re-runs exactly the named runs after an action.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.schemas import validate_output
from src.tui_manifest import REPO, CommandSpec, PageSpec, RunSpec, command_envelope


@dataclass
class RunResult:
    run_id: str
    command: CommandSpec
    data: Any = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    source: str = "live"          # live | replay
    failure: Optional[str] = None
    argv: List[str] = field(default_factory=list)
    returncode: Optional[int] = None
    elapsed: float = 0.0


Executor = Callable[[str, CommandSpec, Dict[str, Any]], RunResult]


def build_argv(command: CommandSpec, args: Dict[str, Any]) -> List[str]:
    """CLI tokens after ``msp`` for a command and its argument values."""
    tokens = list(command.argv)
    for spec in command.args:
        value = args.get(spec.name)
        if value in (None, "", False):
            continue
        if spec.option:
            tokens += [spec.option] if spec.kind == "flag" else [spec.option, str(value)]
        else:
            tokens.append(str(value))
    return tokens


def preview_command(command: CommandSpec, args: Dict[str, Any]) -> str:
    """The exact CLI line an action would run (shown instead of running it)."""
    return " ".join(["msp", *build_argv(command, args)])


def _first_json(text: str) -> Any:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char in "[{":
            try:
                return decoder.raw_decode(text[index:])[0]
            except json.JSONDecodeError:
                continue
    return None


def run_replay(run_id: str, command: CommandSpec, args: Optional[Dict[str, Any]] = None) -> RunResult:
    """Result from the committed, sanitized fixture (no process runs)."""
    envelope, status = command_envelope(command)
    argv = build_argv(command, args or {})
    if envelope is None:
        return RunResult(run_id, command, source="replay", failure=f"no replayable fixture ({status})", argv=argv)
    dumped = envelope.model_dump(mode="json")
    return RunResult(run_id, command, dumped["data"], dumped.get("errors", []), source="replay", argv=argv, returncode=0)


def run_live(run_id: str, command: CommandSpec, args: Optional[Dict[str, Any]] = None, *, timeout: int = 300) -> RunResult:
    """Run the CLI once and validate its output against the command's contract."""
    tokens = build_argv(command, args or {})
    argv = [sys.executable, str(REPO / "src" / "main.py"), "--json", *tokens]
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, cwd=REPO)
    except subprocess.TimeoutExpired:
        return RunResult(run_id, command, failure=f"timed out after {timeout}s", argv=tokens, elapsed=time.monotonic() - started)
    elapsed = time.monotonic() - started
    raw = _first_json(proc.stdout)
    if raw is None and command.encoding in {"text", "lines", "exit"}:
        raw = proc.stdout
    try:
        envelope = validate_output(raw, command.emits, **command.normalize_kwargs(proc.returncode))
    except Exception as exc:  # contract violation: show it, never guess
        reason = (proc.stderr.strip().splitlines() or [""])[-1] if proc.returncode not in command.success else ""
        detail = reason or str(exc).splitlines()[0]
        return RunResult(run_id, command, failure=f"output broke its contract: {detail}", argv=tokens,
                         returncode=proc.returncode, elapsed=elapsed)
    dumped = envelope.model_dump(mode="json")
    return RunResult(run_id, command, dumped["data"], dumped.get("errors", []), argv=tokens,
                     returncode=proc.returncode, elapsed=elapsed)


def execute(run_id: str, command: CommandSpec, *, replay: bool, timeout: int = 300) -> RunResult:
    """Back-compatible single-run entry point used by the preview harness."""
    return run_replay(run_id, command) if replay else run_live(run_id, command, timeout=timeout)


def executor_for(replay_mode: bool) -> Executor:
    return run_replay if replay_mode else run_live


class RunScheduler:
    """Plans and executes a page's runs; caches results for the page visit."""

    def __init__(self, page: PageSpec, commands: Dict[str, CommandSpec], executor: Executor) -> None:
        self.page, self.commands, self.executor = page, commands, executor
        self.runs: Dict[str, RunSpec] = {run.id: run for run in page.runs}
        self.results: Dict[str, RunResult] = {}
        self.executions: List[str] = []   # every run id actually executed, in order

    # -- planning ------------------------------------------------------

    def command(self, run_id: str) -> CommandSpec:
        return self.commands[self.runs[run_id].command]

    def waves(self, run_ids: List[str]) -> List[List[str]]:
        """Group runs into waves: same ``wave`` (or ``order``) runs together,
        and a run never shares or precedes a wave with a run it depends on."""
        wanted = [self.runs[r] for r in run_ids]
        level: Dict[str, int] = {}
        keys = sorted({(r.wave if r.wave is not None else r.order) for r in wanted})
        for run in sorted(wanted, key=lambda r: (r.wave if r.wave is not None else r.order)):
            base = keys.index(run.wave if run.wave is not None else run.order)
            deps = [level[d] + 1 for d in run.depends_on if d in level]
            level[run.id] = max([base, *deps])
        grouped: Dict[int, List[str]] = {}
        for run in wanted:
            grouped.setdefault(level[run.id], []).append(run.id)
        return [grouped[k] for k in sorted(grouped)]

    def triggered(self, trigger: str) -> List[str]:
        """Read runs with this trigger, e.g. ``on_open`` or ``on_view:audit``."""
        return [r.id for r in self.page.runs if r.trigger == trigger and self.command(r.id).risk == "read"]

    def manual_runs(self) -> List[str]:
        """Read runs the user can start from the page header: manual ones, and
        long-running ones (which a revisit does not repeat on its own)."""
        return [r.id for r in self.page.runs if self.command(r.id).risk == "read"
                and (r.trigger == "manual" or self.command(r.id).long_running)]

    def refreshed_by(self, run_id: str) -> List[str]:
        """Runs whose completion will refresh ``run_id`` (e.g. a scan refreshes its cached read)."""
        return [r.id for r in self.page.runs if run_id in self.refresh_targets(r.id)]

    def refresh_targets(self, run_id: str) -> List[str]:
        """Runs to re-execute after ``run_id`` completes: its ``refreshes`` and ``after:`` followers."""
        followers = [r.id for r in self.page.runs if r.trigger == f"after:{run_id}"]
        return list(dict.fromkeys(self.runs[run_id].refreshes + followers))

    # -- execution -----------------------------------------------------

    def execute(
        self,
        run_ids: List[str],
        *,
        force: bool = False,
        on_start: Optional[Callable[[str], None]] = None,
        on_result: Optional[Callable[[RunResult], None]] = None,
        args: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, RunResult]:
        """Execute runs wave by wave (parallel within a wave). Cached runs are
        skipped unless ``force``. Returns the results produced by this call."""
        for run_id in run_ids:
            if self.command(run_id).risk != "read":
                raise PermissionError(f"{run_id}: {self.command(run_id).id} changes the system; preview it instead")
        produced: Dict[str, RunResult] = {}
        for wave in self.waves(run_ids):
            todo = [r for r in wave if force or r not in self.results]
            if not todo:
                continue
            for run_id in todo:
                if on_start:
                    on_start(run_id)

            def one(run_id: str) -> RunResult:
                run = self.runs[run_id]
                return self.executor(run_id, self.command(run_id), {**run.args, **((args or {}).get(run_id, {}))})

            with ThreadPoolExecutor(max_workers=max(1, len(todo))) as pool:
                for result in pool.map(one, todo):
                    self.results[result.run_id] = result
                    self.executions.append(result.run_id)
                    produced[result.run_id] = result
                    if on_result:
                        on_result(result)
        return produced

    def open(self, **kw: Any) -> Dict[str, RunResult]:
        return self.execute(self.triggered("on_open"), **kw)

    def refresh(self, **kw: Any) -> Dict[str, RunResult]:
        """Re-run everything currently shown (on_open plus runs already executed)."""
        shown = list(dict.fromkeys(self.triggered("on_open") + [r for r in self.results if self.command(r).risk == "read"]))
        return self.execute(shown, force=True, **kw)
