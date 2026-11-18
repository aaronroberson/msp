# Plan: Cohesive msp Command Suite (doctor/scan/tune merge + beyond)

Status: **Phase 1 complete** (2026-11-12). Authority for findings: [`docs/audits/command-suite-audit.md`](../audits/command-suite-audit.md) (read-only audit with file:line evidence for all overlaps O-1…O-13 and gaps G-1…G-25).

## Approved architecture (user decisions)

- **`doctor`** = the single health surface. Consumes the persisted scan bundle; never re-runs checks inline. Deps section stays (msp capabilities).
- **`msp doctor fix`** = the one remediation command (performance auto-fixes + protected-file chmod fixes). Backup/rollback contract from tune preserved.
- **`scan`** = the collector. Every mode persists one canonical bundle to `~/.msp/scans/latest.json` (schema "1.0"): `{timestamp, mode, checks[{domain, name, status, title, detail, fixable, fix_cmd}]}`, one entry per check (`ok` / `n/a` / severity).
- **`msp tune`** = deprecated alias (check/fix/top still work; stderr merge notice).

## Phase 1 — DONE

- Canonical bundle read/write/compose in `src/scanner.py` (`write_scan_bundle`, `read_latest_scan`, `collect_health_checks`).
- Single check implementation in `src/tune.py` (`Tuner.collect_health()` + `check_id` on findings); deps.py's duplicated `_shell_startup_check` deleted.
- File-permission audit extended to protected user paths (`~/.ssh` 700, private keys 600, `~/.gnupg`, `~/.aws`, `~/.netrc`, `~/.kube/config`, `~/.zsh_history`).
- `doctor fix` routes performance fixes (Tuner) + `chmod` fixes (`fix_permission_issues`); dry-run previews both.
- TUI (tui.py help, tui_v2 palette + write-gate), main.py epilog, deps interactive menu updated.
- Tests: 193 passing (`test_scan_bundle.py` new; `test_deps.py` rewritten).

## Phase 2 — next (from audit priorities)

1. **Unify finding shapes** (O-4): migrate scanner/rules/shell_audit findings onto one canonical schema (tune's `check_id` pattern); make `remediate.py` the engine behind `doctor fix --scope`.
2. **Fold `shell` (shell_audit) into scan** (O-1, O-8): audit results join the bundle; fixes via `doctor fix --scope shell` (shell_audit_cli's `zsh -n`-validated repair).
3. **`chain` → `workflow` merge** (O-2): rename built-ins to avoid the "daily" collision; demote `chain` to alias.
4. **AI layer consolidation** (O-3, O-11, G-8, G-23): one provider registry in ai.py, delete dead ai.py:998 block, redaction shared util from report.py's `SENSITIVE_FIELD_PATTERNS`, enforced `local_only` policy honoring README's privacy promise.
5. **Persistence registry** (O-6): document/centralize `~/.msp/*` state locations; retire duplicate snapshot-watch state (O-5).

## Phase 3 — coverage gaps (user-requested examples → audit gaps)

Priority high-severity wins: keylogger/input-tap detection (G-7: ioreg + existing tcc audit), P2P/torrent node detection (G-3: lsof/nmap fingerprints in network.py), outbound exfiltration per-process attribution (G-2: nettop sampling in traffic.py), LLM redaction gate (G-8). Medium: secure-keyboard-entry toggle (G-6), resource-hog detection (G-4), integrity baselining via fswatch (G-5), sandboxing recommendations (G-9). Full gap table: audit §4.
