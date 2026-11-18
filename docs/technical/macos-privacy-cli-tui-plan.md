# macos-privacy-cli — TUI Plan

> Companion to `docs/plans/2026-11-17-macos-privacy-cli-architecture-plan.md` (master plan).
> Depends on the approval gate and control registry (see `docs/technical/macos-privacy-cli-target-architecture.md` and `-automation-design.md`).

- **tui_v2 stays the primary TUI; it becomes thinner.** `RUNNABLES` (40 hand-maintained entries, audit O-7 drift) is generated from `controls.py` + workflow ids; `_requires_confirmation` is deleted in favor of gate-produced risk classes (the gate still surfaces its decisions to the TUI for UX, but the *enforcement* is engine-side).
- **New panes:** Approval Inbox (pending `confirm`/`dangerous` steps across runs, with target diffs and mint/approve actions calling `gate.approve()`); Runs (list `~/.msp/state/runs/`, show DAG, live status per step via the existing `CommandBroker` run of `msp workflow show --json`); Privilege Ledger (recent `run_privileged` entries).
- **Parity rule (from AGENTS.md Command Addition Standard):** every new verb appears in `RUNNABLES`, HelpScreen v1+v2, and (if tabular) a `ViewSpec`; acceptance test = every RUNNABLES verb runs through `CommandBroker` with clean `--json`.
- **Retire `src/tui.py`** (876 lines) at the end of Phase 3 — after parity tests exist — closing audit O-7.
- **No privileged calls from the TUI process itself:** the TUI only drives the CLI; the broker pattern already enforces this separation and it is preserved.
