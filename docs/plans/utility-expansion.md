# Plan: Full Audit & Utility Expansion (pre-Phase-2)

Status: **Drafted 2026-11-12 — awaiting approval of decisions in §6.** Authority for findings: [`docs/audits/command-suite-audit.md`](../audits/command-suite-audit.md) (overlaps O-1…O-13, gaps G-1…G-25). Phase 1 (doctor/scan/tune merge) is complete and uncommitted — see [`command-suite-redesign.md`](command-suite-redesign.md).

Extension points below are grounded in file:line research of the current tree.

## 0. Architecture principles (inherits Phase 1)

- **scan = collector** (canonical bundle `~/.msp/scans/latest.json`, schema "1.0"), **doctor = single health surface**, **doctor fix = merged remediation**. Every new capability plugs into this, not beside it.
- Canonical entry contract: `{domain, name, status ∈ ok|n/a|low|medium|high, title, detail, fixable, fix_cmd}` — new checks populate `self.<domain>_results` (pattern: `scanner._check_file_permissions`, scanner.py:289–377) and compose via `collect_health_checks` (scanner.py:81–93) or `Tuner._HEALTH_CHECKS` (tune.py:409–423).
- **Keep `scan quick` fast (~30s)**: sampling/heavy detectors go to `scan deep` or on-demand subcommands.
- **No new outbound network calls.** All new commands: `--json` + rich fallback + `interactive_menu` + `main.py` epilog + TUI RUNNABLES + write-gate if mutating + tests + CHANGELOG (AGENTS.md DoD).
- One new module (`src/redact.py`); everything else extends existing modules.

## 1. Phase A — High-severity wins

### A1. G-7 Keylogger / input-tap detection — `tcc.py` + `scanner.py` + `startup.py`

*Research facts:* tcc.py has Input Monitoring (`kTCCServiceInputMonitoring`, tccutil token `ListenEvent`, tcc.py:130) + Accessibility (:58); audit at tcc.py:274–334; read-only sqlite (:502–542); **no `kTCCServiceListenEvent`/`PostEvent` constants, no ioreg/IOKit code anywhere**; startup.py captures `program`/`program_arguments` (startup.py:128–129) but has no query filter.

- Add `kTCCServiceListenEvent` + `kTCCServicePostEvent` service definitions/aliases (legacy DB rows).
- New `TCCManager.detect_input_taps()` — 3 signal layers:
  1. **TCC**: input-monitoring / accessibility / post-event grants, joined to running processes.
  2. **iOKit**: `ioreg -lw0` scan for `CGEventTap` / `HIDEventTap` / `IOHIDLibUserClient`, parse owners (best-effort; documented false-negative risk — Endpoint Security not available to CLIs).
  3. **Persistence**: filter `_collect_launch_plist_inventory` program/args for HID/event keywords in writable locations (reuse `comprehensive_audit` token pattern, startup.py:728–736).
- Allowlist known-good input apps (Karabiner, BetterTouchTool, Raycast, Alfred, Keyboard Maestro…) → downgrade to ok/low; user-extendable.
- CLI: `msp tcc input-taps`; scan: `SecurityScanner._check_input_taps` → domain `security`, wired into `scan_quick`; doctor renders it. `fixable=False` (revoke = `tccutil reset`, disruptive — guidance only).
- Tests: stubbed sqlite rows + ioreg fixture; allowlist downgrade; no-data → n/a.

### A2. G-3 P2P / torrent node detection — `network.py` + `scanner.py` + `rules.py`

*Research facts:* `_run_cmd` network.py:69; lsof parsers at :102–160 (`parts[8]`) and :162–211 (**masks remote at :181 — need `remote_raw`**); `nmap_scan` :424–561 (no `-sV`; parse bug :487 drops service when version present); camsweep pipeline pattern :698–798.

- Constants `P2P_PORTS` (6881–6999, 51413, 6969, IPFS 4001/5001, Soulseek 2234/5534) + `P2P_PROCESS_FINGERPRINTS` (transmission, qbittorrent, deluge, aria2, webtorrent, kubo/ipfs, soulseek…). **Use `ps -p <pid> -o comm=` for full names** (lsof truncates COMMAND to ~9 chars).
- `NetworkMonitor.p2p_audit()`: listening listeners filtered by port + fingerprint; established peers by remote port; `--deep` adds nmap `-sV` fingerprint on local listeners (plus fix the :487 parse bug).
- CLI: `msp net p2p [audit|peers]`; menu/dispatch/argparse (:803–815, :906–908, :916, :984).
- Scan: `_check_p2p` → domain `security`, medium/high when active peers/listeners, fixable=False. Rules: `NW-003` + facts.py `_collect_network` (:132–142) extension `network.p2p`.

### A3. G-2 Outbound exfiltration attribution — `traffic.py` (+ `network.py` join)

*Research facts:* `summary` traffic.py:72–124 = single nettop snapshot (no `-x -P`); `_run_cmd` :47 has a double-sudo bug when composing `sudo` strings; `_http_fallback` lsof join :224–253; `mask_sensitive` :30; `bandwidth_top` network.py:213–275 already uses `-J bytes_in,bytes_out -L 1 -x`.

- `TrafficAnalyzer.attribution(window=60, threshold_mb=50)`:
  1. Two `nettop -x -P -L 1 -J bytes_in,bytes_out` samples (PID column; cumulative counters → subtract across window).
  2. Join PID→process (`ps -p -o comm=`) and destinations (fresh lsof; keep raw remote for evidence, mask in display).
  3. Severity: ≥ threshold/window → medium; ≥5× → high; report bytes_out delta + destinations.
- CLI: `msp traffic exfil [--window 60] [--threshold 50]`; menu/dispatch/argparse (:328–334, :370–389, :397).
- Scan: v1 **on-demand only** (sampling too slow for quick); optional `scan deep` check after thresholds are proven.
- Opportunistic cleanup: extract shared `parse_lsof_connections()` (duplicated in network/traffic/scanner/snapshot) — defer to its own commit.

### A4. G-8 / G-23 LLM redaction gate + local-only policy — new `src/redact.py` + `ai.py` + `llm.py` + `report.py`

*Research facts:* ai.py masks only `data` (`mask_sensitive` :259–270 via `_format_for_llm` :609–616); cloud boundary `_chat` type dispatch :669–707 and `_http_chat_completion` :315–361; **dead block at ai.py:998 means `msp ai ask` currently does nothing** (collapsed branches — must fix as part of this); llm.py OpenAI serializes raw payload :337–352; shell_audit_ai.py bypasses the central reasoner at :191–205; report.py `SENSITIVE_FIELD_PATTERNS` :37–52 + `redact` :96–113 (keys+IPs only), used only in `build_bundle` :171–188.

- New `src/redact.py`: centralize report patterns + add PEM private-key blocks, API-key formats (`sk-`, `ghp_`, `xox`, `AKIA`), Bearer tokens, `password=`/`token=` pairs, emails, `/Users/<name>` → `/Users/[USER]`; API `redact_text(s) -> (text, counts)`, `redact_obj`, `summarize`.
- Gate: in `_chat` when provider type is `openai_compatible` (**and** `custom` with non-loopback URL); redact final prompt + messages; print counts only ("Redacted 3 secrets, 2 IPs"); `--no-redact` warns. Fix dead :998 block so `ai ask` works.
- Also gate `llm.OpenAIProvider.complete_json` (inside provider, covers shell_audit_ai) — central chokepoint.
- `local_only` config key (~/.msp/ai.json): `_resolve_active_provider` (:618–659) skips cloud when set; `msp ai providers` shows policy. report.py imports from redact.py (public API preserved).
- Tests: pattern matrix, cloud-gate invoked / local-not, local_only resolution, report compat.

### A5. G-6 Secure keyboard entry toggle — `security.py`

*Research facts:* `_run_cmd` security.py:28; osascript template :43; defaults-parsing pattern :62–65; no secure-keyboard-entry code repo-wide.

- `msp security secure-keyboard [status|on|off]`: Terminal.app via System Events menu click (requires **Accessibility permission** — detect denial and print grant instructions); idempotent (check state first); iTerm2 via AppleScript if its dictionary supports it (verify at implementation; else status + instructions).
- Write-gate: add to `_requires_confirmation` (tui_v2.py:54–90). **Not a scan check** (runtime state, flaky) — advisory only.

## 2. Phase B — Medium

### B1. G-4 Resource-hog detection — `tune.py` (+ `doctor top` alias)

- New `_HEALTH_CHECKS` entries (tune.py:409–423), domain `system`: top CPU > threshold; top mem; **fork-bomb heuristic** (double `ps -axo ppid=` sample 5s apart, parent with >50 children and growing → high); zombie count; load average vs `hw.ncpu`.
- `fixable=False` (never auto-kill). CLI: `msp doctor top` → Tuner top view; epilog + TUI.

### B2. G-5 Integrity baselining — `fswatch.py`

*Research facts:* only `diff_config` exists (fswatch.py:256–301) — copies bytes, no hashes; baseline dir `~/.msp/baselines` naming scheme :265–268; no `hashlib` repo-wide.

- `msp fswatch baseline <path> [--name]` / `msp fswatch verify [name] [--json]` / `--update`: sha256 manifest JSON per root (`{relpath: {sha256, size, mtime, mode}}`), skip symlinks, size guard; report added/removed/modified/mode-changed.
- v1 on-demand; later: latest verify result surfaced in doctor Security section.

### B3. G-9 Sandboxing recommendations — `rules.py` + `facts.py`

- New facts section: apps in /Applications + ~/Applications with codesign entitlements (app-sandbox, `allow-unsigned-executable-memory`, `disable-library-validation`), notarization (`spctl`), quarantine.
- New category `sandbox` in profiles (developer/enterprise/high_security at minimum); rules via `rule()` factory (rules.py:329): sandboxed=false with dangerous entitlements → medium; unsigned/not-notarized → reuses scanner findings; remediation text = container/UTM/separate-user guidance. `msp audit --category sandbox` works automatically (:764–769).

## 3. Phase C — Remaining audit §4 gaps (roadmap)

G-1 watcher inventory (launchd WatchPaths from startup.py:130–141 + fswatch), G-10 browser extensions, G-11 DNS/DoH (`scutil --dns`), G-12 WiFi history, G-15 remote-access posture, G-19 `socketfilterfw --listapps`, G-21 login/keychain hygiene, G-24 XProtect versions, G-25 Time Machine. Housekeeping: delete dead root `onvif_manager.py` stub (O-12).

## 4. TUI parity (explicit requirement)

- Every new verb → `RUNNABLES` (tui_v2.py:93–135); mutating ones → `_requires_confirmation` (:54–90); HelpScreen v2 (:913–934) + v1 (tui.py:665–732).
- New views only where tabular: P2P peers, integrity diff → `ViewSpec` (:157–162), `VIEWS` (:165–176), nav binding (:1073–1088), `_payload_rows` branch (:206–285).
- **Acceptance test**: every RUNNABLES verb executes through `CommandBroker` with clean `--json` — prevents TUI breakage.

## 5. Execution order (recommended)

0. **Checkpoint commit** of Phase 1 + audit docs (needs approval).
1. **A4 + dead-block fix** (shared redact util unblocks everything; fixes `msp ai ask`).
2. **A1 → A2 → A3** (each own commit: module + scan check + rules + TUI + tests + CHANGELOG).
3. **A5, B1–B3.**
4. Phase 2 remainder (finding-shape unification → shell fold → chain→workflow).
5. Phase C + onvif cleanup.

## 6. Decisions needed

1. **Command placement**: subcommands of existing verbs as proposed (`net p2p`, `traffic exfil`, `tcc input-taps`, `security secure-keyboard`, `fswatch baseline|verify`, `doctor top`) vs new top-level commands?
2. **Accessibility permission** OK for `security secure-keyboard` (System Events UI scripting)? Otherwise: status-only + manual instructions.
3. **Order**: start with A4 + dead-block fix (recommended), or strictly A1→A5?
4. **Commit Phase 1 checkpoint** before expansion work begins?
