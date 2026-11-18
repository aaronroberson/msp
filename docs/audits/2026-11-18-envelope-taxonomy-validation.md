# Audit: envelope taxonomy validation (Phase 0, P0.2)

**Date:** 2026-11-18 · **Plan:** `docs/plans/2026-11-18-tui-command-surface-plan.md` §3.2 · **Input:** 57 sanitized fixtures from `scripts/capture_fixtures.py` (`tests/fixtures/cli/`)

## Question

Does the draft type model, `Envelope<Record>` with 9 envelopes (Collection, Item, Findings, Definitions, Stream, Diff, Run, Result, Document), describe what the CLI actually returns, before schemas and components are built on it?

## Method

Every passive read command (and the local analysis pipeline) was run as `msp --json …`. Each output was classified mechanically by top-level shape: list vs dict, uniform row keys, presence of severity fields, wrapper keys, artifact files. The result was then compared with the envelope the plan predicted. Streams and mutations were deliberately not captured, because the capture must not change host state or run indefinitely.

## Result

**The 9 envelopes hold semantically**, with no output that needed a new envelope. The way envelopes are *encoded* on the wire varies, and the plan must model that separately.

| Envelope | Observed in | Notes |
|---|---|---|
| Collection | `net list/established/hosts`, `privacy list`, `services list`, `startup list/agents/daemons/running/disabled/login-items/managed`, `snapshot list`, `deps status`, `fswatch new` | bare lists, wrapped (`items` + `scope`/`access_errors`), name-keyed dict (`deps status`), and a list of scalars (`fswatch new`: paths) |
| Item | `firewall status`, `security status`, `sharing status`, `status`, `doctor`, `tune top`, `net inspect`, `scan signature`, `deps check`, `config list`, `interrogate` (artifact) | Items routinely **embed collections** (`firewall.apps`, `sharing.share_points`, `doctor.dependencies`, `status.listening_services`); `status`/`interrogate` are composites of other domains |
| Findings | `scan quick/suspicious`, `shell audit`, `tune check`, `startup audit/summary/comprehensive-audit`, `audit`, `tcc audit` | four severity vocabularies, two field names (below) |
| Definitions | `chain list`, `preset list` (name-keyed dicts), `workflow list` (wrapped list) | |
| Run | `workflow run --dry-run`, `remediate apply` (preview: `results` + `summary`) | |
| Diff | `snapshot diff` (rows of `setting`, `section`, `snapshot_value`, `current_value`, `status`) | |
| Document | `report` (markdown artifact), `scan report` | |
| Stream, Result | not captured by design | validate from code and tests in Phases 3–4 |

## Refinements adopted into the plan (§3.2)

1. **Encoding ≠ envelope.** The same envelope arrives as a bare list, a name-keyed dict, a wrapper object (`{<data_key>: [...], <facets>}`), or a file the command writes. CommandSpec gains `encoding` (`list` · `keyed` · `wrapped` · `scalar-list`), `data_key`, and `channel` (`stdout` · `artifact:<arg>`). Adapters normalize to the envelope before validation, which keeps today's CLI JSON unchanged.
2. **Canonical severity for Findings.** Observed: `severity` ∈ {critical, high, medium, low}; `severity` ∈ {ERROR, WARNING, NOTICE} (`shell audit`); `risk` ∈ {HIGH, REVIEW, LOW} (`startup *`, `status.listening_services`). Findings records carry a normalized `severity` (critical/high/medium/low/info) via a per-command mapping declared in the manifest. This overlaps master-plan **T-02** (canonical finding schema v2) and should converge with it rather than duplicate it.
3. **Facets confirmed:** `errors` (permission failures, e.g. TCC without Full Disk Access), `access_errors`, `scope`, and meta fields `generated_at` / `schema_version`.
4. **Success codes are command-specific:** `audit` exits 1 when findings exist, and `deps check` exits 1 when the package is not installed. CommandSpec gains `success_codes` (default `[0]`).
5. **Scalar collections** (`fswatch new` → paths) are wrapped as records (`{path: …}`) by the adapter.

## Gaps found

| Gap | Commands | Disposition |
|---|---|---|
| Text where structured data belongs | `scan verify` (verdict), `ai devices` (device list) | small CLI fixes during P0.5 curation of `scan` and `ai` |
| Empty output: record shape not observable | `fswatch recent/audit`, `net arp`, `traffic summary`, `startup cron` | schemas derived from source; re-capture on a host with data |
| Requires sudo or streams: not capturable passively | `traffic dns/http/capture/stream`, `fswatch watch/system`, `net top`, `* watch` | schemas from source; validated in Phase 4 |
| Requires a volume | `forensics *` | schemas from source; fixture on an external volume later |
| LLM-backed (would send host data to a remote provider) | `ask`, `ai ask/analyze/explain/suggest/compare`, `reason` | Document/Item schemas from source; fixtures with a local provider only |

## Defects fixed while capturing (committed separately)

- `main.py` split options from their values (`interrogate --output f` → `f --output`) and its global `--provider` choices rejected module options of the same name. Fixed with verbatim forwarding (`259a63a`).
- `deps check <pkg>` / `install <pkg>` rejected the package positional (`f299853`).
- `audit` rejected the global `--json` (`d086170`).

## Status 2026-11-18: P0.3 schemas

- `src/schemas` implements the envelopes, 45 records, encoding adapters and the `resolve`/`validate_output` registry. All 57 raw and sanitized fixtures validate against the envelopes declared in `src/tui_manifest/commands.toml`.
- **Contracts reject mismatches:** validating a fixture against a wrong envelope fails on the missing or mistyped field (e.g. `net list` as `Collection[Connection]` → `data.0.remote`; `shell audit` as `RuleFinding` → unknown severity `ERROR`).
- **Empty data proves nothing.** `tcc audit` (no findings without Full Disk Access) validated against an unrelated record type because its list is empty. The P0.6 contract test must refuse to count an empty fixture as verified; affected commands get hand-authored sample records derived from source.
- **Canonical severity confirmed:** ERROR/WARNING/NOTICE → high/medium/low; HIGH/REVIEW/LOW → high/medium/low; critical..low unchanged.
- **Scan findings have no stable identity:** `check_id` is empty and `control_id` is null for all 116 findings from `scan quick`/`scan suspicious`, so the canonical `id` falls back to the title. Logged against master-plan T-02 (canonical finding schema).
- Fixed while validating: `services list` parsed launchctl's header as a service (`be2423e`). `net hosts` turned out to run `nmap -sn` on the local subnet; it was removed from the passive capture list (it ran twice on 2026-11-18, during the initial probe and the first capture).
