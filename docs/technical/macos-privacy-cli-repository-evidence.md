# macos-privacy-cli — Repository Evidence

> Companion to `docs/plans/2026-11-17-macos-privacy-cli-architecture-plan.md` (master plan).
> Basis: read-only review at `HEAD a512eae` (branch `main`, dirty worktree with Phase-1 "doctor/scan/tune merge" uncommitted). Consumes `docs/audits/command-suite-audit.md` (O-1…O-13, G-1…G-25) rather than restating it.

## 1. Shape of the codebase

| Fact | Evidence |
|---|---|
| ~22,925 LOC across 35 modules; Python ≥3.9 (mypy targets 3.12) | `pyproject.toml`; runtime deps only `argcomplete`, `rich`, `textual` (optional `openai`) |
| Entry points: `msp`/`mac-privacy`/`mpc` + 6 sub-binary entry points | `pyproject.toml [project.scripts]` |
| argparse dispatch; `run_command()` rewrites global `sys.argv` then calls `module.main()` | `src/main.py:52–131` (`COMMAND_MODULES`, 25 commands, aliases, `NO_ACTION_MODULES`) |
| Duplicated dead `snapshot` pre-argparse blocks | `src/main.py:142–215` and `373–423` |
| `ask` shells live diagnostics into the LLM prompt (uptime, `ps axo`, `memory_pressure`, `sysctl`, `df`, network listings) | `src/main.py:484–600` — unredacted host→model path + prompt-injection surface |
| Two TUI generations coexist | `src/tui_v2.py` (1566 lines, current) vs `src/tui.py` (876, legacy) — audit O-7 |
| No CI, no lockfile, no `conftest.py`; 193 tests green after Phase 1 | `tests/` layout; `CHANGELOG.md` [Unreleased] |
| Running the tool dirties the source tree | `deps.py` writes root `deps.json` in the repo working tree |

## 2. The four finding shapes (audit O-4, confirmed)

1. `rules.Finding` (`src/rules.py`) — frozen dataclass with CIS/NIST/STIG refs + evidence paths.
2. `scanner.Finding` (`src/scanner.py`) — severity/category/item/description/recommendation/data.
3. `remediate.RemediationPlan`-bound results (`src/remediate.py`) — serializable, rollback payloads.
4. Scan-bundle entry `{domain,name,status,title,detail,fixable,fix_cmd}` (`docs/plans/command-suite-redesign.md`; `scanner.py` `scan_bundle_path()` → `~/.msp/scans/latest.json`).

## 3. Rule & profile reality

`rules.py` defines exactly **10 rules** (FW-001, FW-002, FV-001, GK-001, SH-001, SH-002, ST-001, ST-002, NW-001, NW-002). `PROFILE_DEFINITIONS` (personal/developer/enterprise/high_security) share the **same 8 categories** — developer differs only in description. `SEC-001` is referenced in `remediate.py:354` but is not a defined rule (orphan mapping). Coverage is thin relative to the tool's ambitions; profiles are marketing, not policy.

## 4. Mutation & privilege surface (read-only scan)

- **Correct pattern (one module):** `firewall.py:16–24` builds `osascript … do shell script … with administrator privileges` per call — scoped, native prompt, no cached authorization.
- **Everywhere else:** literal `sudo` prefix relying on an interactive TTY: `command.py:195–205` `_normalize_command`; `scanner.py:144–147`; `traffic.py:47–50`; `sharing.py:41–44`; `startup.py:57–60`; `privacy_settings.py:269–282` (`shell=True`, no timeout/env/cwd/redaction).
- **Destructive call sites:** `tccutil reset` (tcc.py:367–396); `launchctl disable/enable/bootout/bootstrap` user+system (startup.py:851–1132); `launchctl unload` smbd/afpd (sharing.py:133–134); `socketfilterfw` global/stealth/signed/blockall/app rules (firewall.py:56–72; privacy_settings.py:516–548); `spctl --master-enable/--master-disable` (remediate.py:348–349 — the rollback is the *less* secure state); `defaults write com.apple.screensaver askForPassword` (remediate.py:363–377); `tccutil reset ScreenCapture` (remediate.py:447–449); osascript System Events UI scripting (startup.py:454–474, 979); `shutil.copy2`/`unlink` backups+restores (tune.py:511–543; shell_audit_cli.py:421–466, 612); privileged packet capture (traffic.py:128–305); `kickstart` ARD (privacy_settings.py:249–250).
- **TUI broker:** `CommandBroker` runs `[sys.executable, "-m", "src.main", *tokens]` (tui_v2.py:292–346) with merged output and `kill()` → `terminate()` only. The TUI never sees privileged prompts sensibly because child stdout is piped — sudo prompts dead-lock or fail silently in `shell=True` paths.

## 5. Settings/presets defects

- `PrivacySetting.enable_value/disable_value` are empty strings for most entries (Location Services, Diagnostics, Spotlight, Siri, FileVault, Gatekeeper, SIP) — `enable_setting`/`disable_setting` implement only 4 hard-coded names (privacy_settings.py:169–242, 516–548); the SETTINGS list is largely display data.
- Status readers parse text with substring matches that **can flip verdicts**: `"enabled" in output` is TRUE for "Firewall is disabled" (privacy_settings.py:289, 341).
- `PresetManager.presets_dir` points at `src/presets/` (privacy_settings.py:265–267) — presets are actually in `src/presets.py`; latent path bug.
- `presets.PRESETS` has 5 presets vs README's 4 (audit O-10); `nist` lists `FileVault Encryption: True` but FileVault has no implementation — the preset silently no-ops its headline control.
- `get_last_scan_info` reads `~/.msp/reports/*.json` (privacy_settings.py:360–374), ignoring the newer `~/.msp/scans/latest.json` bundle — stale persistence path.
- `firewall.py:33` maps `allows_signed_app` to `--getallowsigned` (should be `--getallowsignedapp`); app list from `--listapps` is returned unparsed, so per-app firewall rules are unmodelable (G-19).

## 6. TCC & privacy evidence layer

- `tcc.py` reads both TCC databases via sqlite3 (USER_DB/SYSTEM_DB at tcc.py:35–36), never writes; grants handled only via `tccutil reset` (supported, reset-only). System-DB reads silently degrade without FDA — no machine-readable "incomplete" marker, no provenance, no capture of *why* rows are missing.
- `HIGH_RISK` set (Accessibility, InputMonitoring, SystemPolicyAllFiles, AllFiles) is the right instinct and matches Apple's own positioning of those services.
- `snapshot.py`/`privacy_settings.get_snapshot_watch_status` both read `~/.msp/snapshot_watch.*` (audit O-5 duplicate watch state).

## 7. LLM layer

- `sdk.py` (478) is the only retry/backoff/fallback primitive (`retry_with_backoff`, `score_provider`, `_build_fallback_chain`) — good bones, reusable for workflow node retries.
- Three AI stacks coexist (`ai.py`, `llm.py`, `sdk.py` — audit O-3); a 5,752-char dead block at `ai.py:998` makes `msp ai ask` unreachable (audit O-11).
- README claims `local_only`, but the flag is a config note; nothing in `_chat` dispatch (ai.py:669–707) or `llm.OpenAIProvider.complete_json` enforces redaction before egress. `ask` (main.py:484–600) ships raw host diagnostics to the model.

## 8. Prior-audit reconciliation

All of O-1…O-13 and G-1…G-25 from `docs/audits/command-suite-audit.md` were spot-verified as still true at HEAD except where Phase 1 closed them (shell triple → merged `scan`; finding shape #4 now canonical for scan/doctor). See the plan for consumption of those findings.
