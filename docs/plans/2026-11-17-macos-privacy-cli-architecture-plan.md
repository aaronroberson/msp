# macos-privacy-cli — Architecture Plan (master)

> Date: 2026-11-17
> Scope: Read-only review of the repository at `HEAD a512eae` (branch `main`, dirty worktree with Phase-1 "doctor/scan/tune merge" uncommitted) plus targeted primary-source research.
> Companion evidence: `docs/audits/command-suite-audit.md` (overlaps O-1…O-13, gaps G-1…G-25), `docs/plans/command-suite-redesign.md` (Phase-1 redesign), `docs/plans/utility-expansion.md` (Phase A–C expansion, awaiting §6 decisions).
> Status: Planning only. No product changes made during this review.
>
> **Supporting technical references (docs/technical/):**
> - `docs/technical/macos-privacy-cli-repository-evidence.md` — §2 of the original report (detailed evidence with file:line citations)
> - `docs/technical/macos-privacy-cli-threat-model.md` — §3 (trust model, assets, adversarial paths, invariants)
> - `docs/technical/macos-privacy-cli-research-findings.md` — §4 (primary-source research: TCC, SMAppService/privileged ops, logging, orchestration patterns)
> - `docs/technical/macos-privacy-cli-target-architecture.md` — §5 (layered architecture, ControlSpec, finding v2, privilege broker, evidence/state discipline, AI gate)
> - `docs/technical/macos-privacy-cli-automation-design.md` — §6 (workflow schema v2, executor, approval gate, crash-resume & rollback walkthroughs)
> - `docs/technical/macos-privacy-cli-tui-plan.md` — §7 (TUI architecture and parity rules)

---

## 1. Executive assessment

**What the product is.** A local-first, CLI-first macOS security/privacy toolkit (~23k LOC, 35 modules in `src/`, 17 test files) that shells out to its own CLI from a Textual TUI (`src/tui_v2.py`). Phase 1 of the approved redesign — single `scan` collector (versioned bundle), single `doctor` health surface, merged `doctor fix` remediation — is already implemented in the working tree and passes 193 tests.

**Verdict.** The product has a sound conceptual core — a pure rule engine (`src/rules.py`), serializable remediation with rollback payloads (`src/remediate.py`), a versioned scan bundle (`src/scanner.py`), and one correct privileged-execution pattern (`src/firewall.py` via AppleScript admin prompt) — but it is missing the three capabilities the report was commissioned to deliver:

1. **Durable automation.** `src/workflows.py` is a *plan renderer, not an executor*: every step is emitted as `"not_executed"` with `will_execute: False` (workflows.py:276–323), `--dry-run` is `store_true, default=True` so it can never run, and there is no state, checkpoint, retry, or artifact. A competing duplicate "daily" runner exists in `src/chain.py` (audit O-2).
2. **A defensible autonomy/approval model.** The only confirmation gate is a hand-maintained advisory allowlist inside the TUI (`tui_v2.py:54–90`); it is UI-only, bypassable, misses several mutating verbs (`shell repair`, `fswatch` baseline writes, `forensics clean`, `chain run`, `ai configure`), and is not bound to args/targets. The engine itself accepts any mutating command.
3. **A trustworthy execution surface.** Privilege is fragmented across at least five idioms (argv+sudo, shell-string+sudo, AppleScript admin, launchctl direct, tccutil) with no broker, no askpass, no per-operation scoping, and no elevation audit log. `command.run_command` prepends a literal `sudo` and blankets all IPv4/IPv6 output with `[REDACTED]` by default (command.py:103, 216–243), which destroys evidence fidelity for exactly the findings (exfil, P2P, network rules) the tool is meant to produce.

**Highest-risk gaps** (ranked): unenforced LLM redaction / unreachable `ai ask` path (ai.py:998 dead block); UI-only approval gate; no privileged-helper discipline; four coexisting finding shapes; `~/.msp` persistence sprawl without a registry; substring-matching status bugs that can flip security verdicts (`privacy_settings.py:289, 341`); blanket IP redaction; 10 rules behind four identical-coverage profiles; no CI/lockfile/signing/notarization.

The recommended path is **not** another feature push. It is a three-part foundation — (a) a typed **control registry**, (b) a canonical **finding schema v2**, and (c) an **engine-enforced approval gate** — on top of which the existing scan/doctor/remediate/workflow surfaces are re-anchored. Everything in the approved `utility-expansion.md` Phase A/B/C plan then lands *through* the registry instead of as parallel modules, which is the mechanism that stops the duplication the prior audit catalogued.

---

## 8. Phased implementation plan

Phases are ordered so each lands the enabling substrate for the next; utility-expansion's Phase A/B/C work re-anchors onto this sequence rather than running in parallel.

| Phase | Theme | Ships | Depends on |
|---|---|---|---|
| **0 — Foundation** | Registry + schema + bugfix | `state.py`, finding schema v2 in scanner/rules/remediate, `controls.py` seeding existing 10 rules + scanner checks + 4 remediation mappings, fix substring verdict bugs (privacy_settings.py:289,341), presets path bug, `--getallowsignedapp`, retire SEC-001 orphan, deps.json → ~/.msp | none |
| **1 — Trust** | Gate + privilege | `gate.py` engine-enforced approval (risk classes, tokens, ledger), `privilege.py` broker + migration of sudo-prepend call sites, evidence store with sealed raw + presentation redaction, blanket-IP-redaction → opt-in | Phase 0 |
| **2 — Automation** | Executor | workflow schema v2, executor w/ state machine + checkpoints + crash-resume + rollback + retries (reuse `sdk.retry_with_backoff`), daily/incident/harden/evidence as executable DAGs, retire `chain.py` duplicate | Phase 1 |
| **3 — AI hygiene** | Redaction + unify | `redact.py` gate on all outbound, `local_only` enforced in code, delete ai.py:998 dead block, unify ai/llm/sdk into one registry, AI parity in TUI | Phase 1 (gate) |
| **4 — Coverage** | New checks (utility-expansion A1–A5, B1–B3) | input-tap detection (G-7), P2P (G-3, NW-003), exfil attribution (G-2), secure-keyboard check (G-6), resource/fork-bomb (G-4), fswatch hash baselines (G-5), sandbox facts (G-9) — all as ControlSpecs, zero parallel finding shapes | Phases 0–2 |
| **5 — Polish** | Surfaces + hygiene | TUI parity + approval inbox + runs/ledger panes, retire `tui.py`, CI (pytest+mypy), lockfile, README sync (5-vs-4 presets etc.), notarization guidance doc, unify `~/.msp` docs | Phases 0–3 |

Sequencing rationale: Phase 0 is pure refactor with the existing 193 tests as the net. Phase 1 closes the two most consequential security gaps (approval bypass, sudo sprawl) before any new automation exists that could be abused. Phase 2 makes workflows real only after the gate and broker exist, so the executor is never capable of unattended mutation. Phases 3–4 deliver user-visible value on stable rails. Phase 5 is housekeeping.

---

## 9. Execution-ready backlog

| Task ID | Task | Location | Dependencies | Risk | Effort | Verification | Done criteria |
|---|---|---|---|---|---|---|---|
| T-01 | Create `src/state.py` (all `~/.msp` paths, version, migration hook) and replace scattered literals | `src/state.py`; call sites in scanner/remediate/tune/privacy_settings/snapshot/chain/deps | — | Low | M | `pytest tests/`; grep: no `Path("~/.msp` literals outside state.py | All path constants resolve through state.py; deps.json → ~/.msp/deps.json |
| T-02 | Canonical finding schema v2 + adapters in scanner/rules/remediate | `src/schema.py` (new), `src/scanner.py`, `src/rules.py`, `src/remediate.py` | T-01 | Low | M | unit tests comparing v2 output; bundle version bump | 4 finding shapes emit v2; bundle `schema_version` field present |
| T-03 | `src/controls.py` control registry seeding 10 rules + scanner checks + remediation mappings; delete SEC-001 orphan or implement | `src/controls.py`, `src/rules.py`, `src/remediate.py` | T-02 | Medium | L | registry completeness test (every rule id resolvable; every remediate mapping maps to a control) | rules/remediate/presets resolve via controls; `pytest` green |
| T-04 | Fix privacy_settings substring verdict bugs; convert `shell=True` strings to argv | `src/privacy_settings.py:289,341,269–282` | T-01 | Medium | S | new unit tests with "Firewall is disabled"/"off" fixtures | verdicts correct; no `shell=True` for privileged calls |
| T-05 | Fix presets path bug; sync README preset count; mark FileVault no-op honestly | `src/privacy_settings.py:265–267`, `src/presets.py`, `README.md` | — | Low | S | `msp presets --json` lists all 5; nist shows FileVault "unsupported" | path resolves; docs match behavior |
| T-06 | Fix `--getallowsignedapp` mapping; parse `--listapps` into per-app model | `src/firewall.py:33,51–52` | T-02 | Low | S | unit test on fake `socketfilterfw` output; TUI firewall view | allows_signed_app reads correct flag; apps parsed |
| T-07 | `src/gate.py` approval gate (risk classes, tokens w/ TTL+target binding, ledger `~/.msp/state/approval_ledger.jsonl`); wire into `remediate.apply_plan`, workflow executor, `doctor fix` | `src/gate.py`, `src/remediate.py`, `src/main.py` | T-03 | High | L | gate unit tests (deny/allow/expiry/target-mismatch); integration: `remediate --yes` without token exits 2 on `confirm`+ | engine refuses ungated mutating calls in non-TTY contexts |
| T-08 | `src/privilege.py` broker (AppleScript per-op elevation, argv-only, ledger `privilege_ledger.jsonl`); migrate call sites (scanner, traffic, sharing, startup, privacy_settings, remediate) | `src/privilege.py` + call sites | T-07 | High | L | no `["sudo",` argv construction outside broker; ledger records each elevation; firewall.py consumes broker | single elevation path; ledger populated |
| T-09 | Evidence store: raw sealed evidence dir + redaction at presentation; make IP redaction opt-in (`--redact-ips`) | `src/command.py:103,216–243`, `src/state.py` | T-01 | Medium | M | exfil/P2P findings retain endpoints in evidence refs while `msp report` output is redacted | stored findings carry raw refs; exports redacted |
| T-10 | Workflow schema v2 + executor (state machine, checkpoints, retries via `sdk.retry_with_backoff`, crash-resume, rollback-on-verify-fail) | `src/workflows.py`, new `src/executor.py` | T-07, T-08 | High | XL | crash-resume integration test (kill mid-run, resume); failed-verify walkthrough test; unit tests for topo order & backoff | `msp workflow run daily/incident/harden/evidence` executes with persisted state; `resume` works |
| T-11 | Retire `chain.py` duplicate daily; re-point callers | `src/chain.py`, `src/main.py`, TUI runnables | T-10 | Medium | S | grep: no chain imports; `msp chain` alias message | one "daily" implementation |
| T-12 | `src/redact.py` (G-8: PEM/keys/emails/paths per utility-expansion A4) wired as mandatory outbound filter in ai/llm | `src/redact.py`, `src/ai.py`, `src/llm.py`, `src/main.py:484–600` | T-01 | High | M | redaction unit tests incl. `ask` prompt builder; e2e with local ollama recording payload | no unredacted payload leaves process when provider != loopback |
| T-13 | Enforce `local_only` in code; delete ai.py:998 dead block; unify AI stack registry | `src/ai.py:998,669–707`, `src/llm.py`, `src/sdk.py` | T-12 | Medium | M | `local_only: true` + OpenAI provider → refuse with clear error; `msp ai ask` works | one provider registry; dead code gone |
| T-14 | Coverage: input-tap detection (A1) | `src/tcc.py` or `src/controls/` check per A1 spec | T-03 | Medium | M | fixture-driven ioreg parse tests; manual false-negative doc | `msp doctor` shows input-tap finding with ES caveat |
| T-15 | Coverage: P2P listeners + NW-003 rule (A2) | `src/network.py` (`remote_raw`), `src/traffic.py`, `src/rules.py` | T-03, T-09 | Medium | M | fake-lsof fixtures; rule unit test | endpoints preserved via raw evidence; NW-003 fires |
| T-16 | Coverage: exfil attribution two-sample nettop (A3); fix traffic.py:47 double-sudo | `src/traffic.py` | T-03, T-08 | Medium | M | two-sample unit test; threshold tests | `msp traffic exfil` single elevation |
| T-17 | Coverage: secure-keyboard check (A5) — requires Accessibility, gated `confirm` | `src/controls/` new check | T-03, T-07 | Low | S | mock System Events output | finding + confirm gating |
| T-18 | Coverage: resource/fork-bomb check (B1) in doctor; `msp doctor top` | `src/tune.py`, `src/scanner.py` | T-03 | Low | S | two-ps-sample unit tests | never auto-kills; surfaces only |
| T-19 | Coverage: fswatch sha256 baselines (B2) | `src/fswatch.py` | T-01 | Medium | M | baseline/verify round-trip test | `msp fswatch baseline/verify` with persisted manifest |
| T-20 | Coverage: sandbox entitlements facts (B3) | new check in controls | T-03 | Low | S | fixture parse | `sandbox` category in findings |
| T-21 | TUI parity: RUNNABLES generated from registry; approval inbox; runs pane; privilege ledger pane; delete `_requires_confirmation` | `src/tui_v2.py` | T-07, T-10 | Medium | L | parity acceptance test per AGENTS.md; every verb clean `--json` | TUI matches CLI; gate UI-only leftovers deleted |
| T-22 | Retire `src/tui.py` | `src/tui.py`, entry points | T-21 | Low | S | grep: no imports; docs updated | one TUI |
| T-23 | CI: GitHub Actions (pytest + mypy on 3.9/3.12); generate lockfile | `.github/workflows/ci.yml`, `pyproject.toml` | — | Low | S | CI green on PR | checks enforced |
| T-24 | README/docs sync (audit O-10) + `~/.msp` directory doc + FDA narrow-grant guidance (Lapcat caveat) | `README.md`, `docs/` | T-01, T-08 | Low | S | docs review | behavior matches docs |
| T-25 | Notarization/distribution guidance doc; decide daemon question (§12 Q3) | `docs/technical/` | — | Low | S | doc review | path documented; decision recorded |

---

## 10. First implementation slice

**Scope: T-01 → T-04 + T-05 + T-06 (Phase 0), one PR series.**

Rationale: it is pure refactor guarded by 193 green tests, it unlocks every later task, and it contains zero behavior change visible to users except fixed bugs. Slice steps:

1. `src/state.py` with path constants + `ensure_dirs()`; migrate call sites (T-01).
2. `src/schema.py` finding v2 + adapters; bump scan bundle `schema_version` to `2` with tolerant reader (T-02).
3. `src/controls.py` seed registry; re-point `rules.py` evaluate and `remediate.py` mappings through it; resolve SEC-001 (T-03).
4. Bugfix trio with regression tests: privacy_settings substring verdicts + argv conversion (T-04), presets path/docs/FileVault honesty (T-05), firewall flag + app parse (T-06).
5. Update `CHANGELOG.md`, run `python3 -m py_compile` on touched files, full `pytest`, `mypy src`.

Exit criteria: all existing tests pass; new regression tests for the three bug classes; no `~/.msp` literal outside state.py; `msp scan`, `msp doctor`, `msp doctor fix` behave identically to HEAD except corrected verdicts.

---

## 11. Autonomous execution contract

The contract an autonomous agent must satisfy when executing the backlog above (each task = one conventional commit; amend on iteration, never stack fixups, per AGENTS.md):

1. **Static checks before reporting done:** `pytest`, `mypy src`, `python3 -m py_compile` on touched files; for TUI tasks the parity acceptance run; for CLI tasks a smoke of normal + `--json` paths. Claim "done" only with these outputs in hand.
2. **Never bypass the gate or broker.** During Phases 1–2 the agent implements the gate/broker and must run the *new* code paths in tests only — never executing privileged mutations on the host to "verify". Manual smoke of privileged paths is the operator's step, run once, with outputs pasted into the task notes.
3. **Verification before success claims.** A remediation/apply step is done only when its `verify()` (re-read of system state) succeeds. No success claim from apply's exit code alone — this is the same standard the executor enforces.
4. **Rollback discipline.** Any apply the agent triggers in a *test harness* must restore recorded pre-state (the executor's `capture_pre_state` rule) and confirm restoration by re-verify before proceeding.
5. **Scope fencing.** Tasks touch only files listed in their Location column plus their tests. Cross-file renames required by a task are stated in the commit body. No new dependencies without updating `pyproject.toml` and noting why in the commit.
6. **Doc & spec sync.** Closing a task updates the affected docs (`README.md`, AGENTS.md epilog when new commands appear, this plan's backlog table status) in the same commit.
7. **Stop conditions.** The agent stops and reports when: a test suite is red for reasons unrelated to its change; a task requires privileges the harness lacks; evidence contradicts a task's premise (e.g., a scanner check turns out to be structurally impossible without the ES entitlement); or two tasks' premises conflict — in which case the conflict is documented under §12 before proceeding.
8. **No secrets, no host changes outside declared tasks,** no committing `.env*` or generated host data, no LLM calls with host payloads outside the (post-T-12) gated path.

---

## 12. Open questions

1. **Placement of new verbs** (`tcc input-taps`, `net p2p`, `traffic exfil`): subcommands of existing groups vs top-level — `utility-expansion.md` §6 decision still open (blocking A1–A3 polish, not their design).
2. **Accessibility-risk acceptance** for the secure-keyboard check (A5) — needs a one-time operator decision; reversible but consent-flavored.
3. **Privileged daemon question:** is scheduled unattended scanning worth an SMAppService launch daemon (requires notarized app bundle, admin approval, IPC) versus the current user-triggered CLI? Recommendation: defer until Phase 5; the gate+broker model works fully user-triggered. If yes, the notarization task (T-25) becomes a prerequisite, not guidance.
4. **FDA grant UX:** grant narrowly per terminal host and state the transitive-grant caveat in docs (T-24) — confirm acceptable that `doctor`'s TCC section is marked `incomplete` on machines without FDA rather than probing further (per Apple DTS guidance).
5. **Evidence retention policy:** how long raw sealed evidence (which contains endpoints/paths) is kept, and whether an explicit purge command belongs in `forensics`.
6. **Profile differentiation:** the four profiles currently differ only in name; should Phase 0 also differentiate threshold sets, or is that deferred to coverage work in Phase 4?
7. **`deps.json` consumers:** confirm nothing external reads the repo-tree `deps.json` before moving it to `~/.msp` (T-01).

---

## Status and handoffs

- Related audit report: `docs/audits/command-suite-audit.md` (this plan consumes its O-*/G-* findings).
- Phase-1 redesign baseline: `docs/plans/command-suite-redesign.md`.
- Expansion plan being re-anchored: `docs/plans/utility-expansion.md` (its §6 open decisions map to §12 Q1–Q2 here).
- Technical references live under `docs/technical/macos-privacy-cli-*.md` (index at top).
- Next review point: after the first slice (T-01…T-06) lands, revisit §12 Q3 and Q6 with real usage.
