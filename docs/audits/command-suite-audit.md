# msp — Comprehensive Read-Only Audit Report

Scope: full static read of all 35 modules in `src/`, `main.py` routing, `README.md`, `pyproject.toml`, `tests/`, plus root scripts (`onvif_manager.py`, `frigate-setup/`). All claims carry file:line evidence. Delivered by a read-only audit agent; no files were written by the agent.

---

## 1. Command Inventory

### 1a. Commands routed via `COMMAND_MODULES` (src/main.py:52)

| Command | Module | Subcommands (argparse evidence) | `--json` | Notes |
|---|---|---|---|---|
| `scan` | `scanner.py` (568 LOC) | quick, deep, suspicious, verify, signature, report (scanner.py:532) | Yes | Own `Finding(severity, category, item, description, recommendation, data)`; writes `~/.msp/reports/scan_report.json` (scanner.py:522-564) |
| `doctor` / `deps` | `deps.py` (476) | status, doctor, check, install, fix, install-all, "" (deps.py:432) | Yes | `DependencyManager`; deps.json at repo root; includes shell checks (deps.py:208-286) |
| `tune` | `tune.py` (745) | check, fix, top, "" (tune.py:699) | Partial | Own `Finding(domain, severity, title, fixable, fix_cmd…)`; backups in `~/.msp/backups` (tune.py:42,695) |
| `net` | `network.py` (989) | list, established, top, kill, terminate, inspect, lookup, arp, nmap, hosts, camsweep (network.py:916) | Yes | `camsweep` = ping→ARP→ports→ONVIF→mDNS (network.py:698-735); `nmap --scan-type cameras` (network.py:429-435) |
| `firewall` | `firewall.py` (130) | status, set, app (firewall.py:104-111) | Yes | AppleScript admin-auth path (firewall.py:20-22) |
| `tcc` | `tcc.py` (998) | list, show, grant, revoke, reset, backup, restore, audit (tcc.py:923) | Yes | Read-only TCC.db + tccutil resets; `grant/revoke` compatibility-stub (tcc.py:928) |
| `startup` | `startup.py` (1611) | 23 actions: list, managed, login-items, login-add/remove, agent-add/remove/enable/disable, agents, daemons, cron, disable, enable, audit, summary, search, running, disabled, pause, start, inventory, comprehensive-audit (startup.py:1295) | Yes | Risk engine: SUSPICIOUS_PATTERNS vs KNOWN_GOOD_PREFIXES; 30s `_run_cmd` timeout |
| `privacy_settings` | `privacy_settings.py` (1296) | list, status, enable, disable, services, preset (list/apply/save/delete) (privacy_settings.py:1199-1223) | Yes | Also hosts legacy `presets`/`status` aliases (see 1b) |
| `audit` | `rules.py` (863) | single-command: `--profile personal/developer`, severity/category filters | Yes | Rule engine over normalized facts; NIST refs per rule (rules.py:388-614) |
| `interrogate` | `facts.py` (580) | single-command fact collection (`--sections`, `--json`) | Yes | `DEFAULT_SECTIONS` 7 collectors; failures recorded not fatal |
| `reason` | `llm.py` (562) | single command, `--provider auto/local/ollama/apfel/openai` (llm.py:475) | Yes | Dependency-free; evidence-based reasoning over facts |
| `remediate` | `remediate.py` (815) | plan, apply (remediate.py:676,687) | Yes | `RemediationAction(finding_id, safety low/medium/high/destructive, rollback…)`; plan/dry-run default |
| `report` | `report.py` (345) | single command `--facts --findings --format md/json --output` | Yes | BUNDLE_SCHEMA_VERSION "1.0"; SENSITIVE_FIELD_PATTERNS redaction + IP masking |
| `workflow` | `workflows.py` (451) | list, show, run (workflows.py:350-357) | Yes | WORKFLOW_SCHEMA_VERSION "1.0"; BUILTIN_WORKFLOWS incl. "daily" (workflows.py:66-105) |
| `snapshot` | `snapshot.py` (965) | capture, list, diff, restore, watch, delete (snapshot.py:910) | Yes | `~/.msp/snapshots` (snapshot.py:57); watch state in `~/.msp/snapshot_watch.*` (snapshot.py:769-770) |
| `sharing` | `sharing.py` (345) | list, status, disable, disable-guest, enable, stop-all (sharing.py:308) | Yes | |
| `security` | `security.py` (288) | status, lock, sleep, set, computer-sleep (security.py:258) | Yes | Screen-lock/sleep control |
| `ai` / `ask` | `ai.py` (1043) | ask, configure, providers, analyze, watch, explain, compare, suggest, devices (ai.py:964) | Yes | BYOK multi-provider + keychain (`msp-` service prefix); dead block at ai.py:998 (see O-11) |
| `chain` | `chain.py` (539) | list, run, define, delete, watch, export, import (chain.py:478) | Yes | `DEFAULT_CHAINS` suspicious/daily/audit (chain.py:45-80) |
| `tui` | `tui_v2.py` (1563) | `--v1` → legacy `tui.py` (tui_v2.py:1551-1558) | n/a | Textual; command palette + subprocess broker |
| `forensics` | `forensics.py` (718) | scan, inspect, correlate, spotlight, clean (forensics.py:573-593) | Yes | AppleDouble parser (MAGIC 0x00051607), quarantine/provenance/AVKit decoders |
| `traffic` | `traffic.py` (426) | summary, dns, http, capture, stream (traffic.py:397) | Yes | tcpdump/pfctl-based |
| `fswatch` | `fswatch.py` (482) | watch, recent, system, new, diff, audit (fswatch.py:446) | Yes | Baselines in `~/.msp/baselines` (fswatch.py:262) |

Interactive menus: every module falls back to an `interactive_menu` when its positional action is omitted (pattern: scanner.py:532 "omit for interactive mode", same for network.py:916, tcc.py:923, startup.py:1295, etc.), all built on shared helpers in `command.py` (511 LOC: `interactive_menu`, `interactive_select`, `setup_completion`, `suggest_command`, `setup_logging`, `IPV4_RE/IPV6_RE`).

### 1b. Special-cased and alias routes (main.py pre-argparse)

| Route | Evidence | Behavior |
|---|---|---|
| `snapshot` / `sharing` / `security` | main.py:142, 326, 344, 373 | Handled before argparse; argv rewritten (e.g. main.py:207, 366) |
| `shell` | main.py:425 → `shell_audit_cli.py` (1328) | Audit/fix of startup files; `--profile personal/developer/enterprise/high_security` (shell_audit_cli.py:1159), category filters path/zsh_startup/completion/executable/symlink/package_manager (shell_audit_cli.py:1178); backups `~/.msp/backups/shell_audit/<ts>` (shell_audit_cli.py:337) |
| `config` | main.py:446 → `errors.py` (145) | `~/.msp/config.toml` load/save (errors.py:92,118) |
| `status`, `list`, `enable`, `disable`, `preset`, `presets`, `services` | main.py:603 (alias map) | Rewritten to `privacy_settings …`; `cli/console/menu` → `privacy_settings.interactive_menu` |
| no args | main() default | Launches `tui_v2` |
| unknown command | main.py:647 | `suggest_command` (difflib cutoff 0.4) |
| `--help` fast path | main.py:134-138 | Skips full argparse for `<cmd> --help` |

### 1c. Console-script entry points (pyproject.toml:26-35)

`msp` / `mac-privacy` / `mpc` → `src.main:console_main`; plus 6 standalone: `msp-interrogate` (facts), `msp-reason` (llm), `msp-remediate` (remediate), `msp-report` (report), `msp-workflow` (workflows), `msp-forensics` (forensics).

### 1d. Non-routed scripts (dead/standalone)

| Script | Status | Evidence |
|---|---|---|
| `onvif_manager.py` (root, 112) | **Unrouted** — no `msp` imports; third-party dep `onvif_zeep_async` not in pyproject deps; `discover_devices` is a print-only stub | onvif_manager.py:9, 84-106 |
| `frigate-setup/probe-cameras.py`, `onvif-discovery.py`, `simple-probe.py` | Standalone experiments; `onvif` dep, no msp integration | frigate-setup/*.py:4, 11 |
| `deps.json` at repo root | State file written by deps.py | pyproject aside |

Test coverage exists for 16 areas (tests/: test_ai, test_cli_smoke, test_command, test_deps, test_facts, test_forensics, test_llm, test_remediate, test_report, test_rules, test_shell_audit, test_tcc, test_tui_acceptance, test_tui_v2, test_tune, test_workflows).

---

## 2. Overlap Analysis (evidence-backed)

| # | Overlap | Evidence | Severity |
|---|---|---|---|
| O-1 | **Shell health checks ×3.** `deps.py::_shell_startup_check` (deps.py:208-286: `zsh -i -c exit` timing :229, history checks :244-261, duplicate PATH in `.zshrc` :274-284) duplicates `tune.py` `_check_zsh_startup/_check_zsh_nvm/_check_zsh_history/_check_zsh_path_dupes/_check_zsh_async/_check_zsh_brew` (tune.py:116-121, 170-262, `_check_brew` :314-330) **and** the dedicated `shell_audit.py` engine (7 audit functions; e.g. brew-architecture id `shell.pkg.brew_architecture`, `path_helper -d` duplicate-PATH check, symlink/PAexec-shadowing audits) | deps.py:208, tune.py:116-330, shell_audit.py:audit_* | HIGH — three divergent implementations of the same checks, three output shapes |
| O-2 | **"daily" defined twice.** `chain.py::DEFAULT_CHAINS["daily"]` (chain.py:55: net list → net established → startup list → traffic summary) vs `workflows.py::BUILTIN_WORKFLOWS["daily"]` (workflows.py:67-105: status → net → startup → tcc → report, LLM-annotated, writes `daily.md`) | chain.py:55, workflows.py:67-105, README.md:279 | HIGH — two competing orchestration abstractions with colliding names |
| O-3 | **AI provider stacks ×3.** `ai.py` BYOK engine (OpenAI/Groq/DeepSeek/OpenRouter/Together/custom/Ollama/apfel/OpenVINO; ai.py:54,149-163), `llm.py` provider layer (auto/local/ollama/apfel/openai; llm.py:475), `sdk.py` fallback chain with preference scoring (`PREF_*` :0-4, `PROVIDER_PREF_SCORES`), importing from ai.py (sdk.py imports DEFAULT_PROVIDERS, AIAnalyzer, configure_provider_flow) | ai.py:964, llm.py:475, sdk.py | HIGH — three code paths decide "which model answers"; `reason`/`ask`/tui chat use different stacks |
| O-4 | **Finding shapes ×4 + severity vocabularies ×2.** scanner.Finding (severity/category/item), tune.Finding (domain/severity/title/fixable/fix_cmd), rules.Finding (info/low/medium/high/critical), shell_audit.AuditFinding (id/category/summary/evidence/…; INFO/NOTICE/WARNING/ERROR/SECURITY). `shell_audit_cli._SEVERITY_MAP` (shell_audit_cli.py) exists solely to bridge vocabularies into rules.py's `SEVERITY_ORDER` | scanner.py, tune.py, rules.py:341, shell_audit.py:AuditFinding, shell_audit_cli.py:_SEVERITY_MAP | HIGH — blocks the `doctor fix` merge; every remediation engine parses a different shape |
| O-5 | **Snapshot-watch state duplicated.** snapshot.py:769-770 and privacy_settings.py:378-391 both read/write `~/.msp/snapshot_watch.pid` + `snapshot_watch_config.json` | snapshot.py:769, privacy_settings.py:378 | MEDIUM |
| O-6 | **`~/.msp` persistence sprawl — 9+ schemes, no registry.** `~/.msp/snapshots` (snapshot.py:57), `~/.msp/backups` (tune.py:42) + `~/.msp/backups/shell_audit` (shell_audit_cli.py:337), `~/.msp/baselines` (fswatch.py:262), `~/.msp/reports` (scanner.py:522-564, privacy_settings.py:362), `~/.msp/config.toml` (errors.py:14,92), `~/.msp/ai_config.json` + keychain `msp-` (ai.py:54,149), `~/.msp/settings.json` (snapshot.py:447), `~/.msp/snapshot_watch.{pid,json}` (snapshot.py:769, privacy_settings.py:378), `~/.msp` chains dir (chain.py:79), repo-root deps.json | listed per file | HIGH — `doctor` currently cannot see any of it; scan/doctor persistence has no single source of truth |
| O-7 | **Dual TUIs.** `tui.py` (876; dashboard + own risk heuristic duplicating startup.py's — inline HIGH-risk word list tui.py:93-94) vs `tui_v2.py` (1563; subprocess-broker console that re-parses CLI JSON). main.py default = v2, `--v1` fallback (tui_v2.py:1551-1558) | tui.py:735-863, tui_v2.py:47-88, 162-180 | MEDIUM — v1 duplicates provider/risk logic; palette RUNNABLES (tui_v2.py:91-132) is a hand-maintained copy of the CLI surface |
| O-8 | **Remediation engines ×3.** remediate.py (plan/apply, finding_id-linked, rollback commands), tune.py fix (backup+apply with full restore-on-failure contract, tune.py:695), shell_audit_cli repair (backup + `zsh -n` validation, `~/.msp/backups/shell_audit`, shell_audit_cli.py:336-337,453) + shell_audit_ai.py line-edit proposals (LineEdit, allow-listed paths, MAX_CONTEXT_CHARS 6000) | remediate.py:676-687, tune.py:695, shell_audit_cli.py:336, shell_audit_ai.py:160-222 | HIGH — `doctor fix` consolidation is exactly the missing unifier |
| O-9 | **Reporting ×3.** report.py (redacted evidence bundle BUNDLE_SCHEMA "1.0"), scanner.py report action (scanner.py:522-564 → `~/.msp/reports/scan_report.json`), privacy_settings.py report dir handling (privacy_settings.py:362) | report.py, scanner.py:522, privacy_settings.py:362 | MEDIUM |
| O-10 | **README drift.** Presets table lists 4 presets (README.md:229-235) but code ships 5 incl. `nist` (presets.py:54-64, wired at privacy_settings.py:24,1223); README claims "No outbound network calls" while ai.py supports cloud providers (ai.py DEFAULT_PROVIDERS openai api.openai.com) | README.md:229-235,262 vs presets.py:54, ai.py | LOW (doc) |
| O-11 | **Dead AI block.** ai.py:998 is one 5,752-char line containing commented-out `ask_list/ask_status/ask_preset/ask_preset_list` branch code (mid-line `#`); those actions are absent from argparse choices (ai.py:964) and the branch's body is the following `ask` body — unreachable and unfixable as-is | ai.py:964,998 | MEDIUM (bug-adjacent) |
| O-12 | **Camera logic in 4 places.** `net nmap --scan-type cameras` (network.py:429-435), `net camsweep` (network.py:698-795 incl. ONVIF WS-Discovery :653, mDNS :673-675), unrouted `onvif_manager.py`, and frigate-setup scripts | network.py:429,698; onvif_manager.py | MEDIUM |
| O-13 | **Duplicate risk heuristics.** startup.py SUSPICIOUS_PATTERNS engine vs tui.py inline `high_risk` word list (tui.py:93-94) vs scanner.py "suspicious" heuristic vs shell_audit executable-shadowing | startup.py, tui.py:93, scanner.py | LOW-MED |

---

## 3. Proposed Cohesive Command Suite

Design principles (per user direction):
- **`scan` = the collector.** Runs all detection layers, persists one versioned result bundle to `~/.msp/scans/latest.json` (new; subsumes O-6 sprawl for read surfaces).
- **`doctor` = the single health surface.** Consumes the persisted scan bundle + deps + shell + AI config; sections per domain. No re-running checkers inline.
- **`msp doctor fix` = the one remediation command.** Built on `remediate.py`'s engine (finding_id → action → safety → rollback), absorbing tune's backup/restore contract and shell_audit's `zsh -n`-validated repair path; AI proposals (shell_audit_ai.py LineEdit) become one action type.

### Migration table

| Current | Proposed | Action |
|---|---|---|
| `doctor`/`deps` (deps.py:432) + `tune check` + `shell` + inline status | `doctor` (status/health single surface) | **Merge**: deps → doctor section; keep `deps` as alias 1 release |
| `remediate plan/apply` + `tune fix` + `shell` fix + preset apply | `doctor fix [--scope] [--safety low..destructive]` | **Merge**; remediate stays as power-user alias |
| `scan quick/deep/suspicious/verify/signature/report` | `scan [quick|deep|suspicious]`, `scan verify/signature`, `doctor report` (report moves under doctor; scanner's own report action retired) | **Relocate** |
| `chain` vs `workflow` (O-2) | Keep `workflow` (richer: LLM-annotated, redacted report output); demote `chain` to thin alias, rename built-ins to avoid collision | **Merge into workflow** |
| `ai`/`ask`/`reason` + `sdk.py` (O-3) | One provider registry in `ai.py` (already the superset); `reason` becomes evidence-mode flag of `ask`; `sdk.py` scoring feeds the same registry | **Consolidate** |
| `tui` + `tui --v1` (O-7) | `tui` (v2 only); drop legacy tui.py and inline heuristics | **Retire v1** |
| `status`/`presets` aliases (main.py:603) | `doctor status` / `doctor preset apply` | **Alias-only** during transition |
| `onvif_manager.py`, `frigate-setup/` | Delete or promote under `net camsweep --onvif` | **Decide** (see §4 G-14) |
| `shell` (O-1, O-8) | `shell audit` output folds into scan results; fixes via `doctor fix --scope shell` | **Fold in** |

Per AGENTS.md Command Addition Standard, each merged command needs: main.py routing + epilog entry, `--json`, `interactive_menu` item, tui widget/screen + HelpScreen entry, and the 7-point DoD; existing tests in tests/ (test_deps, test_tune, test_remediate…) give the regression baseline.

---

## 4. Gap Analysis — macOS security & privacy coverage

Sev: H = high impact, M = medium, L = nice-to-have. "Stock CLI" = how macOS exposes it natively today.

| # | Gap | Sev | Stock macOS CLI approach | Natural extending module | Caveats |
|---|---|---|---|---|---|
| G-1 | **Folder-watcher/file tamper detection** beyond `fswatch` (system persistence dirs watched continuously) | H | `fswatch` (already used); `lsappinfo`/quarantine xattr polling | `fswatch.py` | Daemon for continuous watch; no entitlement needed |
| G-2 | **Outbound exfiltration detection w/ per-process attribution** (large upload volume per PID, rare-destination spotting) | H | `nettop -P -L`, `pfctl` counters; `tcpdump` attribution | `traffic.py` | Needs TCC Full Disk? No — but per-process byte attribution is best via nettop sampling |
| G-3 | **P2P/torrent node detection** (BitTorrent/DHT port + peer graphs, known P2P C2) | H | `lsof -i`, nmap service fingerprinting | `network.py` (extends camsweep pattern) | None |
| G-4 | **Resource-hog / fork-bomb detection** (runaway proc trees, threads-per-pid, zombie storms) | M | `ps -axo ppid,pid,%cpu,%mem,comm`, `ulimit` audit | new `procs` or `tune top` | None |
| G-5 | **File-integrity baselining** (hash watched trees, alert on change) | H | `shasum -a 256` sweeps; already have fswatch baselines `~/.msp/baselines` | `fswatch.py` (diff exists fswatch.py:446) | Full-disk scan perf; SIP limits on system paths |
| G-6 | **Secure Keyboard Entry toggle** (Terminal) — anti-keylogger | M | Terminal.app AppleScript `secure keyboard entry` | `security.py` | Per-terminal-app; only effective in Terminal.app |
| G-7 | **Keylogger / input-monitor detection** — CGEventTap & hidEventTap taps via ioreg | H | `ioreg -w 0 -a CGEventTapList` style queries; check apps with Accessibility+Input Monitoring TCC grants | `tcc.py` (audit exists) + ioreg parse | Some taps are legitimate (BetterTouchTool etc.); needs allowlist |
| G-8 | **Local redaction before LLM** (mask IPs/hosts/secrets in prompt payloads) — exists in report.py (SENSITIVE_FIELD_PATTERNS) and shell_audit_ai prompt discipline ("never move secrets", ai.py PROMPT:18-31) but not in `ai.py` ask path | H | n/a (self) | `ai.py` | Reuse report.py patterns as shared util |
| G-9 | **App sandboxing / VM / container recommendations** | L | `codesign -d --entitlements -`, `system_profiler SPApplicationsDataType` | `scanner.py` | Advisory-only output |
| G-10 | **Browser telemetry/extension audit** (Chrome/Firefox/Safari extension + prefs scan) | M | Reading profile JSON/SQLite in `~/Library/Application Support` | `privacy_settings.py` or new module | TCC Full Disk Access needed for browser data |
| G-11 | **DNS config & DoH leakage** (resolv.conf, scutil --dns, browser DoH default) | M | `scutil --dns`, `networksetup -getdnsservers` | `network.py` | Advisory |
| G-12 | **WiFi history / preferred-network leakage** (auto-join lists broadcast you) | M | `defaults read com.apple.wifi.known-networks`, `airport -s` | `privacy_settings.py` | Some keys SIP/secure-preferences protected |
| G-13 | **Spotlight privacy** (external index state, privacy exclusions) — forensics.py partially covers external Spotlight stores | L | `mdutil -s`, `mdimport -L` | `forensics.py` | Needs sudo for mdutil -E |
| G-14 | **ONVIF/camera device manager** — camsweep detects (network.py:698) but there's no credentialed ONVIF follow-up; `onvif_manager.py` exists but unrouted and stub-discovery | M | nmap `--script onvif-info` | `network.py` absorb onvif_manager or drop it | Third-party dep decision |
| G-15 | **VNC/SSH/ARD exposure audit** — sharing.py covers daemons/shares but not remote-login config posture per service | M | `systemsetup -getremotelogin`, `launchctl list com.apple.sshd` | `sharing.py` | Sudo for some queries |
| G-16 | **Print/spooler audit** (IPP Everywhere leaks, CUPS web UI on :631, printer kdcp/beacon) | L | `lpstat -v`, CUPS config read | new module or `network.py` | Low sev |
| G-17 | **Notifications/Shortcuts privacy** (apps allowed to send, Shortcuts sharing) | L | `defaults read com.apple.notificationcenterui`, Shortcuts DB | `tcc.py`-adjacent | TCC DB is read-only source |
| G-18 | **DNS/block-list integrity** (hosts file tamper, resolver override) | M | diff `/etc/hosts`, `scutil --dns` | `fswatch.py` baseline | None |
| G-19 | **Per-app firewall application-rules audit** (socketfilterfw app list w/ blocked status) — firewall.py status prints `apps_output` but no audit rule over it | M | `/usr/libexec/ApplicationFirewall/socketfilterfw --listapps` | `firewall.py` | None |
| G-20 | **Quarantine/provenance sweep of *local* disk** (all Downloads+apps, not just external volumes) — forensics.py AppleDouble/quarantine decoders exist but scoped to volumes | M | `xattr -p com.apple.quarantine`, `mdfind kMDItemWhereFroms` | `forensics.py`/`scanner.py` | Full-disk perf |
| G-21 | **Login/keychain hygiene** (loginwindow autologin, keychain lock timeout, iCloud Keychain state) | M | `defaults read com.apple.loginwindow`, `security show-keychain-info` | `security.py` | `security` cmd may prompt |
| G-22 | **Clipboard monitor** (pbpaste sampling with sensitive-pattern alerting) | M | `pbpaste` polling | `traffic.py`-adjacent new watcher | Privacy-sensitive feature; opt-in only |
| G-23 | **LLM local-vs-cloud policy gate** — currently `MSP_LLM_PROVIDER` env (README.md:172-178) and ai.py providers, but no enforced "local-only" mode binding ai.py cloud providers off | H | n/a (self) | `ai.py` + `~/.msp/config.toml` | Quick win; aligns with README privacy claims (O-10) |
| G-24 | **XProtect/Gatekeeper/MRT version + last-update check** — security.py/gatekeeper status exists but engine-definitions version isn't surfaced | L | `defaults read /Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info.plist CFBundleShortVersionString` | `doctor` section | None |
| G-25 | **Time Machine backup audit** (exclusions, encryption of backups) | L | `tmutil destinationinfo`, `tmutil isexcluded` | `security.py` | None |

### Priority recommendations (cross-cutting)

1. **Unify findings + persistence first** (O-4, O-6): one canonical finding schema and `~/.msp/scans/latest.json` makes `doctor`, `doctor fix`, and TUI consumption trivial and unblocks nearly every gap above.
2. **Kill the tripled shell-check layer** (O-1): shell_audit.py is the superset engine — deps and tune should call it, not re-implement.
3. **Fix/finish the AI layer** (O-3, O-11, G-8, G-23): one provider registry, remove dead ai.py:998 block, default `local_only` policy to honor the README's privacy promise.
4. **Cheapest high-severity gap wins**: G-7 (keylogger taps via ioreg + TCC audit you already have), G-3 (P2P port heuristics extend camsweep), G-2 (nettop sampling extends traffic.py).
