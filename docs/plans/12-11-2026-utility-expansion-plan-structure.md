Plan: Full Audit & Utility Expansion (pre-Phase-2)

Objective
- Merge msp tune into msp doctor (user decided: doctor is the primary name, msp doctor fix is the merged remediation command); scan becomes the collector whose persisted results inform doctor; doctor should prompt for quick/full scan when no results exist, and add file-permission checks.
- Extra credit (in progress): full command-surface code review to find overlaps and gaps; comprehensive audit already produced and written to docs/audits/command-suite-audit.md — must be summarized to the user.
Important Details
- Repo: /Users/conscious/macos-privacy-cli (msp macOS CLI, Python), branch main. Tests: .venv/bin/python -m pytest (system python3 lacks pytest). Baseline: 187 passed.
- Conventional commits; commit/push only when user explicitly asks — merge work is deliberately uncommitted. screenshots/ pre-existing untracked, exclude.
- LSP errors "Console"/"Table" is possibly unbound and interactive_select invariant warnings are pre-existing false positives — ignore.
- deps.json = msp's own runtime deps (10 entries: fswatch, ollama required; apfel, processmonitor, knockknock, wireshark, somo, nmap, exiftool, openvino optional) — NOT system deps. Doctor = "is msp fully armed".
- Git evidence: _shell_startup_check (deps.py) and tune.py both born in same commit ba87f58 — original sin of duplication.
- Approved design: scan = collector persisting canonical bundle ~/.msp/scans/latest.json schema "1.0" → {schema, timestamp, mode, checks:[{domain, name, status, title, detail, fixable, fix_cmd}]}, one entry per check (status: ok|n/a|low|medium|high). doctor = single health surface reading the bundle (no inline re-checks), sections shell/system/permissions, stale note >7 days, prompt quick/full/skip when missing (non-TTY → hint). msp doctor fix = Tuner.fix engine. tune = deprecated alias (stderr notice, functionality kept).
- deps.py facts: _run_cmd → (bool, str); check_all() → Dict[str, DepStatus]; doctor() currently prints Dependencies + Shell performance sections built earlier today and returns bool.
- tune.py facts: Tuner.fix(dry_run=False, json_output=False), fix handler keys nvm_lazy, history_trim, history_repair, async, brew_shellenv; BACKUP_DIR = HOME/".msp"/"backups"; all-or-nothing fix w/ rollback; BACKUP cleanup prompt TTY-only.
- main.py routing: doctor special-cased at main.py:624-628 (dm.doctor(verbose=args.verbose)); epilog lines 35-36 (doctor/tune descriptions) + examples 272-277 need updates; tune routes via module main.
- Audit subagent: free-longread type FAILS ([invalid_value] Invalid value for 'tools': maximum number of items is 128) — use general type instead.
- User machine: zsh startup 924–1495ms (HIGH), wants to delete NVM; zero fixable zsh findings on their box.
- Policy: doctor/tune startup messages must NOT enumerate hard-coded remedies; only msp tune check lists per-machine fixes.
Work State
Completed
- Doctor healthy-check printing (pre-merge): _shell_startup_check returned (issues, checked); doctor printed ✓/–/severity lines + dep counts; tests/test_deps.py (5 tests, fixed 87ms→100ms assertion); suite 187 passed; CHANGELOG bullet added (uncommitted). This code is now being superseded by the bundle design.
- Q&A answered: deps.json inventory explained; doctor/tune separation traced to ba87f58.
- Audit report completed (4 sections: inventory, overlaps O-1..O-13, migration-table suite proposal, gaps G-1..G-25) and written unchanged to docs/audits/command-suite-audit.md; created docs/audits/ and docs/plans/.
- tune.py edits (done, unverified): Finding gained check_id: str = ""; all 12 _check_* methods now return Optional[str] healthy detail + tag findings with check_id (zsh_startup, zsh_nvm, zsh_history, zsh_path_dupes, zsh_async, zsh_brew, disk, memory, brew, docker, cache, launch_daemons); added _HEALTH_CHECKS 4-tuple registry + collect_health() returning canonical entries; _print_check hint → "→ msp doctor fix"; main() prints stderr deprecation notice ("'msp tune' is merging into 'msp doctor'…").
- scanner.py edits (done, unverified): added from pathlib import Path; module-level SCAN_BUNDLE_SCHEMA="1.0", scan_bundle_path(), write_scan_bundle(mode, checks), read_latest_scan(), collect_health_checks() (lazy-imports Tuner, runs its collect_health(), then SecurityScanner()._check_file_permissions() merges permission_results); _check_file_permissions rewritten: /etc/passwd,/etc/sudoers,/etc/shadow world-writable + protected user paths (~/.ssh 700, ~/.ssh/id_{rsa,ed25519,dsa,ecdsa} 600, ~/.gnupg 700, ~/.aws 700, ~/.netrc 600, ~/.kube/config 600, ~/.zsh_history 600) → canonical ok/n/a/high/medium entries + Security Findings; all 3 scan modes call new _persist_health(mode, json_output) which writes bundle + prints "Health snapshot saved to: …" (non-JSON).
Active
- deps.py merge NOT yet applied: mid-read of lines 200-360 to delete _shell_startup_check (~line 208) and replace the doctor shell-performance block (~lines 325-352) with bundle rendering (_render_bundle) + _offer_scan() prompt.
- No compile/test run since the large tune.py + scanner.py edits began.
Blocked
- (none)
Next Move
1. Finish deps.py: remove _shell_startup_check; rewrite doctor() → deps summary (keep) + load read_latest_scan(); if None → _offer_scan() (TTY interactive_select quick/full/skip running SecurityScanner().scan_quick()/scan_deep(), non-TTY hint "Run 'msp scan quick'…"); render bundle grouped by domain with ✓ ok / – n/a / severity lines, fixable → "(fix: msp doctor fix)", staleness note; return False if any severity finding.
2. main.py: msp doctor fix branch (args.args[0]=="fix" → Tuner().fix(dry_run="--dry-run" in args, json_output=args.json)); update epilog lines 35-36 + examples 272-277 (doctor = health, tune = alias); check tui_v2 RUNNABLES palette for "msp doctor fix" entry.
3. Rewrite tests/test_deps.py for bundle-driven doctor (renders crafted bundle, non-TTY hint, stale note, deps summary); add tests/test_scan_bundle.py (write/read roundtrip, permissions canonical entries via tmp home, Tuner.collect_health() ok/n/a/severity with stubbed tune._run); run .venv/bin/python -m pytest (187 baseline) + live msp doctor smoke; update CHANGELOG.
4. Report merge results to user + summarize audit findings (docs/audits/command-suite-audit.md: O-1 shell checks ×3, O-2 daily duplicated chain/workflow, O-3 AI stacks ×3, O-4 four Finding shapes, O-6 ~/.msp persistence sprawl, O-8 remediation ×3; gaps: keylogger detection G-7, P2P/torrent G-3, exfiltration G-2, resource hogs G-4, secure keyboard G-6, LLM redaction G-8, sandboxing G-9, watchers G-1, integrity G-5). Do NOT commit until asked.
Relevant Files
- /Users/conscious/macos-privacy-cli/src/deps.py — doctor rewrite pending: delete _shell_startup_check (~208), replace shell section (~325-352), add _offer_scan/_render_bundle.
- /Users/conscious/macos-privacy-cli/src/tune.py — check_id on Finding, Optional[str] check returns, _HEALTH_CHECKS, collect_health(), deprecation notice in main() (done, unverified).
- /Users/conscious/macos-privacy-cli/src/scanner.py — bundle funcs (SCAN_BUNDLE_SCHEMA, scan_bundle_path, write_scan_bundle, read_latest_scan, collect_health_checks), extended _check_file_permissions w/ self.permission_results, _persist_health wired into 3 scan modes (done, unverified).
- /Users/conscious/macos-privacy-cli/src/main.py — doctor fix routing (lines 623-628), epilog 35-36/272-277.
- /Users/conscious/macos-privacy-cli/tests/test_deps.py — 5 tests exist but test _shell_startup_check (being deleted) → must rewrite for bundle-driven doctor.
- /Users/conscious/macos-privacy-cli/tests/test_tune.py — 10 tests; check methods' new return values + check_id must not break them.
- /Users/conscious/macos-privacy-cli/docs/audits/command-suite-audit.md — full audit report (inventory/overlaps/migration proposal/gaps).
- /Users/conscious/macos-privacy-cli/docs/plans/ — created, empty (synthesis plan can go here).
- /Users/conscious/macos-privacy-cli/CHANGELOG.md — has doctor ✓-printing bullet; needs merge entries.
- /Users/conscious/macos-privacy-cli/deps.json — source of self.deps.
- /Users/conscious/macos-privacy-cli/src/tui_v2.py — RUNNABLES palette (~lines 91-132) may need msp doctor fix.

Context & principles
- Current architecture (scan=collector bundle; doctor=surface; doctor fix=remediation; tune=alias; TUI palette + write gate).
- All new capabilities follow: canonical bundle entries (domain/name/status/title/detail/fixable/fix_cmd), --json + rich fallback + interactive_menu, main.py routing + epilog, TUI RUNNABLES + write-gate for mutating verbs + HelpScreen, tests, CHANGELOG.
- New modules only where necessary; prefer extending existing modules per audit's "natural extending module" column.
- Read-only checks vs fixable actions; mutating actions require confirmation + no silent changes; TCC/System Events permission caveats documented.

Phase A — High-severity wins (in order)
A1. Keylogger / input-tap detection (G-7) — extend tcc.py + scanner bundle
- Detection layers: (a) TCC audit for kTCCServiceListenEvent (Input Monitoring), kTCCServiceAccessibility, kTCCServicePostEvent grants — tcc.py audit exists; add service focus + process attribution; (b) ioreg CGEventTap/hidEventTap inspection (ioreg -lw0 | grep -iE "CGEventTap|HIDEventTap|EventMonitor" / ioreg -c IOHIDSystem), parse owner; (c) auxiliary: launchd items with IOKit/HID claims (startup.py engine reuse).
- Deliverables: msp tcc audit --input (or new msp tcc input-monitors), canonical scan checks domain "security"/"shell"? → "security": entries for each tap/permission with severity + allowlist of known-good apps (BetterTouchTool, Karabiner, Raycast, etc.); doctor surfaces them.
- CLI: extend tcc.py actions; JSON; interactive menu; main.py epilog. No fix (revoke via tcc reset stays out or requires confirmation).
- Caveats: ioreg output varies by macOS; EndpointSecurity not available to CLI; document that absence of ioreg taps ≠ no keylogger (false-negative risk) — combine with TCC + suspicious persistence list.
A2. P2P / torrent node detection (G-3) — extend network.py
- Detection: listening/established ports in BT ranges (6881-6999, 51413, 6969, 1337, DHT UDP 6881, IPFS 4001/5001/8080 swarm), process names (transmission*, qbittorrent, deluge*, aria2*, webtorrent, ipfs/kubo, soulseek*), reverse lookup flags for known P2P; nmap service fingerprint optional (existing scan types).
- Deliverable: msp net p2p (actions: list/detect), canonical checks in scan (domain "security" or "network") with severity medium/high when active peer connections found; fixable=False (guidance to quit/uninstall), maybe fix "kill" gated.
- Reuse camsweep discovery pattern + _run_cmd; JSON + menu + tests with stubbed command outputs.
A3. Outbound exfiltration attribution (G-2) — extend traffic.py
- Detection: sample nettop -x -P -L 1 -J bytes_in,bytes_out -t wifi (or -t all) over window; compute per-PID egress delta; join with lsof -i -nP for destinations; thresholds (e.g. >50MB in 60s or >N MB/min sustained); flag unknown/signed status.
- Deliverable: msp traffic exfil [--window 60 --threshold 50]; canonical check entry "exfiltration watch" (domain "security", fixable=False); periodic watch mode optional later.
- Careful: nettop column parsing is brittle; fall back to nettop -P -L 0 -x -J ...; no sudo needed. JSON + tests with fixture strings.
A4. LLM redaction gate + local-only policy (G-8/G-23) — new src/redact.py + ai.py/llm.py integration
- Extract report.py SENSITIVE_FIELD_PATTERNS into shared src/redact.py (secrets: API keys, tokens, private keys, paths?, IPs hostnames optional), redact(text) -> (clean, stats), redact_obj.
- Apply in ai.py ask path when provider is non-local (cloud); print/emit redaction summary (not raw secrets); --no-redact override with warning; config local_only = true in ~/.msp/config.toml (errors.py) enforcing local providers only (honor README promise); msp ai providers shows policy status.
- Also apply to shell_audit_ai LineEdit prompts (already disciplined) and report.py reuses util (no behavior change).
A5. Secure keyboard entry toggle (G-6) — extend security.py
- msp security secure-keyboard [status|on|off]; Terminal.app via System Events menu click (requires Accessibility); iTerm2 AppleScript property if present; status via menu state; document permission caveat; non-TTY/no-permission graceful message.
- Canonical scan check: whether Secure Keyboard Entry is ON while a terminal is frontmost? (may be flaky — keep as live tool, not scan check; or scan check "terminal running without SKE" advisory).
Phase B — Medium
B1. Resource-hog / fork-bomb detection (G-4) — scan checks + msp doctor top
- Checks: top CPU/mem processes above thresholds; same-parent child count >N (fork bomb heuristic) via double-sample; zombie count; load average vs ncpu. Domain "system"; advisory (fixable=False) — or "kill" guidance.
- msp doctor top alias for tune top (live view), plus msp doctor top --hogs summary.
B2. Integrity baselining (G-5) — extend fswatch.py
- sha256 manifest of protected dirs (baseline action exists — extend to hashes), msp fswatch verify, scheduled via launchd optional; scan check "integrity" domain: last verify result stored in bundle/meta.
B3. Sandboxing recommendations (G-9) — rules.py + scanner
- New audit rules: unsigned/not-notarized apps, apps with dangerous entitlements (disable-library-validation, allow-unsigned-executable-memory), non-App-Sandbox apps in sensitive paths, apps with full disk access (join tcc) → advisory recommendations (container/VM/separate user; note macOS-specific options: Docker/Podman/OrbStack, UTM, Parallels, separate standard user, App Sandbox only at build time).
- Surface via msp audit --category sandbox + doctor rules section later.
Phase C — Remaining §4 gaps (roadmap-level, prioritized)
- G-1 watcher inventory (fswatch system watches + launchd WatchPaths + Spotlight importers), G-10 browser extension audit, G-11 DNS/DoH, G-12 WiFi history, G-15 remote access posture, G-19 firewall per-app rules, G-21 keychain/login hygiene, G-24 XProtect versions, G-25 Time Machine. (G-14 ONVIF: decide keep net camsweep, delete dead onvif_manager.py; G-16/17/18/20/22 optional.)

Cross-cutting work
- Bundle schema extension: add "category"/"evidence" fields? (schema 1.1 backward-compatible) for richer findings; keep doctor rendering generic.
- TUI parity: every new verb in RUNNABLES; mutating subcommands added to write-gate; views where relevant (security posture screen); HelpScreen update; test_tui_v2 acceptance remains green.
- Command/help/TUI/test DoD checklist per AGENTS.md (routing, --json, rich fallback, interactive_menu, epilog, py_compile, e2e smoke, no regressions).
- Performance: scan quick must stay ~30s; heavy checks (integrity verify, P2P nmap) go to scan deep or on-demand commands.
- Privacy: no outbound network calls in any new feature; redaction default-on for cloud AI.

Execution order & phases (with the user's "before Phase 2" constraint)
Hmm — the user says "before phase 2, ... plan". So plan covers Phase 2 + expansion? They ask to plan "a full audit and utility expansion" including the listed items; the doctor/tune Phase 2 (finding unification/shell folding/chain-workflow/AI consolidation) remains the prior roadmap. My plan should integrate: how these features land given Phase 2 architecture. Actually re-read: "before phase 2, which will also entail that commands issued from the tui are not broken, can you first please plan a full audit and utility expansion to the msp suite..." → They want planning now; execution after. Phase 2 (from my plan doc) = finding unification etc. The utility expansion overlaps with Phase 2 items 4/5 (AI consolidation, redaction). So the plan should note sequencing: some expansion work folds naturally into Phase 2 (AI layer + redaction; finding shape unifying enables new checks).

I'll propose revised sequencing:
- Step 0 (small): commit current Phase 1 work (user decision — ask).
- Step 1: Phase 2a — unify finding/check schema + remediation engine routing (needed by expansion) + TUI untouched-parity verification (smoke all palette verbs).
- Step 2: High-severity expansion (A1-A5) each as its own PR/chunk with tests.
- Step 3: Medium (B1-B3).
- Step 4: remaining gaps.

Testing strategy
- Unit tests per detector with stubbed command outputs (pattern from test_tune/test_scan_bundle).
- CLI smoke tests for new verbs (--json validity).
- TUI acceptance test update (palette entries exist + write-gate classification).
- Manual smoke matrix on user's machine (documented in report).

Risks / open questions (ask user)
1. Scope order: strictly the 8 listed first? (recommend yes)
2. Is Accessibility permission acceptable for security secure-keyboard (System Events UI scripting)? Alternative: status-only detection + manual instruction.
3. Sampling windows for exfil/fork-bomb (defaults 60s / 10s) OK? Should they run as part of scan deep (slower) or only on-demand?
4. Do we add a NEW top-level msp watch/msp procs command, or keep everything under existing verbs (net/traffic/tcc/security/doctor/audit)? (recommend existing verbs per cohesive-suite goal)
5. Should integrity baselining be hash-based (slower, accurate) or mtime/size (fast, weaker)? Recommend hash + opt-in dirs.
6. Commit Phase 1 + audit docs before starting? (recommend yes, as a checkpoint)

Also mention where plan will be written after approval: docs/plans/utility-expansion.md (per documentation policy) — but plan mode forbids writing now.
