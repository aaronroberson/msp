# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (phase 0 — foundation refactor)
- **Central state registry (`src/state.py`)**: every `~/.msp` path (scans, reports, backups, baselines, snapshots, settings, config) resolves through one module honoring the `MSP_HOME` environment variable at call time. All collectors (scanner, tune, privacy settings, snapshot, ai, fswatch, shell audit, errors) migrated off ad-hoc path literals.
- **Canonical finding schema (`src/schema.py`, v2)**: `FindingV2` dataclass (title/category/severity/control_id/check_id/evidence_refs/provenance/…) with duck-typed adapters from the four historical finding shapes (scanner items, rules findings, tune checks, remediation results) and `canonicalize_check` for health-check entries. Scan bundle schema bumped to `2.0` while keeping every legacy key; `msp scan --json` and reports now emit canonical findings plus the legacy `item`/`rule_id` aliases consumers rely on.
- **Control registry (`src/controls.py`)**: all 16 rules, 13 health checks and 7 preset settings registered as controls with remediation id, safety class and references. `rules.default_rules()` fails fast on unregistered ids and the remediation planner skips findings whose control id is unknown instead of silently planning them. Completeness tests pin rules/registry/remediate parity (SEC-001 orphan resolved).
- **Structured firewall app rules**: `msp firewall status` now parses `socketfilterfw --listapps` two-line output (path line + `(Allow|Block incoming connections)` verdict) into `{path, name, status}` entries under `apps` alongside the raw `apps_output`; the TUI firewall view prefers the structured list.

### Fixed (phase 0)
- **Firewall verdicts were read-only lies** (`msp audit`/scan): `--getallowsigned` outputs say `ENABLED.`/`DISABLED.`, so the old `"on" in output` test never matched and signed-software allowance was always reported off; the firewall status also queried nonexistent flags (`--getallowsignedapp`, `--getincoming`, `--getoutgoing`, which exit 255) and never reported their results. Verdicts now match real output; dead queries and their always-false keys removed.
- **FileVault status treated mid-conversion as encrypted**: `fdesetup status` "Encryption in progress" no longer counts as encrypted; honest enabled/encrypted verdicts.
- **Presets had two drifted sources of truth**: `privacy_settings.PresetManager` shipped its own 4-preset copy while `src/presets.py` had 5 (including `nist`, invisible via CLI). The manager now imports the single source; `nist` applies via CLI and is delete-protected like the built-ins.
- **Preset apply hung/fake-failed on FileVault**: enabling FileVault requires interactive auth and a recovery key, so unattended `fdesetup enable` would hang. Preset application now skips FileVault with actionable guidance (System Settings path or manual `sudo fdesetup enable`) instead of printing `[FAIL]`.
- **Shell execution hardened**: privacy-settings commands run as argv via `subprocess.run(shell=False)` with `shlex.split`; the pipe/redirect callers (`lsof`, `launchctl | grep`, `defaults` reads) were rewritten to filter in Python.
- **README preset table** synced with the real five presets.

### Fixed
- `msp doctor` shell-performance output rendered raw Rich markup (`[red]HIGH[/red]`) instead of color; it now prints via `console.print`.
- `msp doctor` suggested nonexistent commands: `msp tune profile` (slow startup) and `msp tune apply` (corrupted history) now point to `msp tune fix` / `msp tune check`.
- `msp doctor` and `msp tune` startup findings no longer list hard-coded remedies (NVM lazy-load, history trim); applicable fixes are enumerated per machine by `msp tune check`.
- `msp tune` check output leaked raw Rich markup (`[red]HIGH[/red] [red]zsh[/red]`) in the severity lines; now rendered with `console.print`.

### Changed
- `msp tune fix` destructive operations (`~/.zshrc` rewrite, zsh history trim/repair) now create timestamped backups in `~/.msp/backups/` before modifying files. On failure every backup is restored (all-or-nothing run); on success backups are kept and interactive users are offered cleanup, non-interactive runs report backup paths. Applies fixes summary with per-fix status and backup location.

### Added
- `tests/test_tune.py` covering backup creation, rollback on handler/write failure, dry-run isolation, backup cleanup, and JSON output of backup paths.

### Added
- `msp doctor` now prints every check's outcome instead of staying silent: healthy shell checks as ✓ lines (e.g. "✓ Zsh history — 8,902 lines, text format OK"), unavailable checks as skipped (–) lines, and a dependency summary with counts (required installed, total checked) plus missing optional dependencies.
- `tests/test_deps.py` covering healthy/partitioned/skipped shell-check reporting and the doctor dependency summary.

### Changed (doctor/scan/tune merge — phase 1)
- **`msp scan` is now the single collector.** Every scan mode (quick/deep/suspicious) collects shell + system + file-permission health via one canonical implementation (`Tuner.collect_health()` + extended `_check_file_permissions`) and persists a versioned bundle to `~/.msp/scans/latest.json` — one entry per check with status ok / n/a / issue-severity, including healthy and skipped checks.
- **`msp doctor` is the single health surface.** It renders the persisted scan bundle (no re-running checks inline), grouped by Shell / System / Protected files, with provenance ("scan from …") and a staleness note after 7 days. When no results exist it offers to run a scan (quick/full, interactive only); non-interactive runs print the hint.
- **`msp doctor fix` is the merged remediation command** — applies performance auto-fixes (tune engine with backup/rollback) plus safe `chmod` fixes for over-permissive protected paths found in the bundle; dry-run previews both. TUI palette and help text updated; deps interactive menu gains "Doctor fix".
- **File-permission audit extended**: `msp scan` now checks protected user paths (`~/.ssh` 700, private keys 600, `~/.gnupg`, `~/.aws`, `~/.netrc`, `~/.kube/config`, `~/.zsh_history`) for group/world access in addition to the existing critical system paths.
- **`msp tune` is a deprecated alias**: still fully functional (check/fix/top), prints a merge notice on stderr; `msp doctor`'s duplicated inline shell checks were removed (single implementation now lives in the tune collector consumed by scan).
- `tests/test_scan_bundle.py` (bundle roundtrip, corrupt handling, permission canonical entries, chmod fix idempotence, collector composition) and rewritten `tests/test_deps.py` (bundle-driven doctor rendering, no-scan prompt, staleness note).

## [0.2.0] - 2026-09-02

### Added
- `remediation_id` and `evidence_paths` metadata to security rules and findings in `src/rules.py`.
- Interactive menus for `msp audit`, `msp startup`, and `msp tcc`.
- Support for sorting in many commands (`msp list`, `msp services`, `msp startup`, `msp fswatch`, `msp net`, `msp scan`, `msp chain`).
- New core modules: `src/facts.py`, `src/llm.py`, `src/remediate.py`, `src/report.py`, `src/workflows.py`.
- Tests for new modules and remediation metadata.
- Shell completion support via `setup_completion` in `src/command.py`.
- `nist` preset support.
- Comprehensive inventory and audit subcommands to `msp startup`.
- `grant`, `revoke`, and `restore` (placeholder) subcommands to `msp tcc`.
- New `forensics` module (`src/forensics.py` and `tests/test_forensics.py`) for external volume inspection, AppleDouble (`._*`) binary v2 parsing, `com.apple.quarantine`, `com.apple.provenance`, and `com.apple.avkit` xattr extraction, external Spotlight store inspection, and multi-vector local Mac host correlation.
- Embedded media EXIF/XMP metadata extraction in `msp forensics inspect` powered by `exiftool`.
- Integrated `exiftool`, `apfel`, and `ollama` into `deps.json` and `msp doctor` dependency checks.
- Interactive menu for `msp forensics` with volume selection, artifact scanning, and rogue file cleanup.

### Changed
- Refactored `src/rules.py` to use `remediation_id` and `evidence_paths` for better automated remediation.
- Updated `COMMANDS.md` with new subcommands, options, and sort keys.
- Integrated `rich` for better table rendering and interactive menus.
- Improved error handling in `msp audit` when facts are missing from stdin.

### Fixed
- Improved sort key consistency across all modules.
