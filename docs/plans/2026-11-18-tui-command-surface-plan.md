# Plan: TUI as the graphical shell for every `msp` command

**Date:** 2026-11-18 · **Status:** Phase 0 complete (merged); Phase 1 complete (2026-11-18, branch `feat/tui-phase1-shell`); Phase 2 next · **Implements:** master plan T-21 (`2026-11-17-macos-privacy-cli-architecture-plan.md`) · **Extends:** `2026-11-04-tui-v2-plan.md`

## 0. Objective and user decisions

Every `msp` CLI command gets first-class TUI controls (buttons, toggles, forms) and a first-class output display (tables, cards, cells, text). The command palette does not count. The TUI should behave like a graphical operating system for the CLI.

Decisions from the user on 2026-11-18:

| # | Decision |
|---|---|
| D1 | **Component-schema architecture, structured like a headless CMS.** Sort commands and their output into reusable display units, similar to React components. Define a component schema and a manifest. Give every manifest item a schema type and an order that reflects how the pieces assemble on screen. |
| D2 | **Grouped left sidebar** replaces the top tab bar. |
| D3 | **Admin rights:** a native password popup that feeds the process that needs it. (The user suggested Keychain; §6 explains why this plan uses sudo askpass instead.) |
| D4 | **Order:** group by concern first (security, monitoring, system control, privacy, forensics, automation, repair & recovery). Within a page, order by **composition**: how components nest and assemble into the interface (shell → page regions → components → building blocks), not by component type or name. |
| D5 | **Scope:** all CLI groups: privacy settings; net, startup, firewall, fswatch, traffic; scan, tcc, interrogate, audit, reason, remediate, report, workflow; forensics; ai/ask, chain, doctor, tune; tui. |
| D6 | Write this plan to disk before any code. Prefer existing open-source libraries for parsing and rendering (§7). |
| D7 | **Data is not bound to a display type.** Commands emit typed data entities; the same entity can be rendered by several components. Templates and pages list which commands run, in what order, and which component renders each output where (§3.4). |
| D8 | Fix defects as they are found unless the fix is a considerable detour; detours go to the master plan backlog (§9 of `2026-11-17-macos-privacy-cli-architecture-plan.md`). |
| D9 | **Pages are authored once, as files** (not a runtime CMS), but keep CMS-style separation of concerns: entity schemas, components, templates and pages are separate layers. |
| D10 | **Explicit, tool-enforced contracts** between command output and components (no implied/duck-typed bindings), designed in from the start. |
| D11 | Dependencies approved: **pydantic, jmespath, textual-fspicker, jc** (resolves L1 → pydantic, L2). |
| D12 | **Type model = operation envelope × domain record** (§3.2). The user's first framing was "command : vehicle :: subcommand : car" (inheritance); the probe data shows the group is a namespace owning record types, while subcommands differ by operation kind. |
| D13 | **Admin rights via `sudo -A` + askpass** (native password dialog, nothing stored; optional Touch ID through `pam_tid` in `/etc/pam.d/sudo_local`). Resolves A1 (§6). |
| D14 | **Fallback pages approved, but a fallback page does not count as implementing a command.** Any command without a curated placement is still reachable through an auto-generated page per command group (default component per envelope). These pages are visibly badged "Auto-generated · not yet designed" and are excluded from coverage (§9). |

## 1. Current state (measured 2026-11-18)

The CLI has 22 module-backed command groups plus 4 dispatched by `main.py` (shell, config, ask, doctor): **26 groups, 135 actions** per the seeder (`scripts/seed_manifest.py`). TUI v2 has dedicated screens for about 10 views (dashboard, findings, network listening/established, startup managed, TCC list, privacy, firewall, snapshots, workflows, AI). Groups with **no** TUI surface: fswatch, traffic, sharing, security, chain, doctor/deps, tune, forensics, and the analysis pipeline (interrogate, audit, reason, remediate, report).

### 1.1 Output probe of read-only actions

Each read-only action was run as `msp --json <action>` with a 25 s timeout.

| Output shape observed (→ envelope, §3.2) | Actions |
|---|---|
| list of uniform records | `list`, `services`, `net list/established/arp/hosts`, `startup list/agents/daemons/cron/running/disabled`, `traffic summary/dns` |
| object wrapping `items` (+ `scope`, `access_errors`) | `startup managed`, `startup login-items` |
| severity-tagged items (`item`, `risk`, `reasons`) | `startup audit/summary`, `tcc audit` (`findings`), `scan *` |
| object of boolean/scalar settings groups | `status`, `firewall status`, `security status`, `interrogate` |
| object of named definitions (name → object) | `preset list`, `chain list` |
| command result object (`command`, `returncode`, `output`) | `tune top` |
| records + `errors` list (permission problems) | `tcc list`, `tcc audit`, `interrogate` (Full Disk Access missing) |
| human text despite `--json` | `doctor status/check`, `ai devices`; `sharing list/status` print a Python object, not JSON |
| broken at probe time (all fixed since, §8) | **all `fswatch` actions**: syntax error at `src/fswatch.py:148` (committed in `544a9bb`; the uncommitted edit is also invalid) · `snapshot list` prints usage text when given global `--json` · `workflow list` rejects global `--json` · `ai providers` opens an interactive prompt |
| slower than 25 s | `scan quick`, `scan suspicious`, `tune check`, `startup inventory` |

### 1.2 Structural constraint

15 of the 22 modules use one flat `action` argument with `choices=[…]`. All of their options sit on that one parser, so **nothing in the code says which flag belongs to which action**. Generating forms from the parsers alone, whether by our own code or with argparse-tui/Trogon, would show every flag on every action. The per-action argument list therefore has to be written into the manifest (§3.1). The parsers can supply a starting draft for it.

## 2. Architecture overview

This mirrors a headless CMS with four separate layers. **Commands emit data entities. Entities have no fixed component.** A page decides which commands to run, in what order, and which component renders each output, often several components for the same output.

```
 msp CLI (engine; contract: argv in → JSON / text / stream out)
      ▲ argv                                   │ stdout · stderr · exit code
      │                                        ▼
 ① CommandSpec ── emits ──▶ ② Entity: Envelope<Record>, e.g. Collection<Socket>
      ▲                                        │  select (JMESPath projection)
      │ runs, in order                         ▼
 ④ Page / Template ─── binds run output ──▶ ③ Component (declares the entity shapes it accepts)
   runs:  [r1 → r2 → (r3 ‖ r4) …]                │ placed in
   slots: [run.select → component @ region]     ▼
                         Shell ▸ Sidebar ▸ Page frame regions ▸ components
```

- **Typed as `Envelope<Record>` (§3.2).** Envelopes are the operation kinds that recur across all groups; records are each group's domain nouns.
- **Many-to-many by design.** One run can feed several slots. For example, one `firewall status` run fills the status pills, the settings toggles and the app-rules table. Equally, one component type renders output from many different commands.
- **Each command executes once per page refresh**, however many slots use its output.
- **Single source of truth:** `src/tui_manifest/` holds the data files plus the schemas. RUNNABLES, the palette, keyboard help and sidebar entries are generated from it, and the hand-maintained lists get deleted.
- **Curated screens become manifest pages.** Today's Dashboard, Privacy, Firewall, Findings, Network and Startup screens are re-expressed as pages. Behavior is preserved, verified by the existing tests plus screenshots.

## 3. Schemas

### 3.1 `CommandSpec`: what can be run

| Field | Type | Notes |
|---|---|---|
| `id` | str | `tcc.revoke`, `net.list` … (`group.action`) |
| `argv` | list[str] | template, e.g. `["tcc","revoke","{service}","{client}"]` |
| `args` | list[ArgSpec] | per-action arguments (fills the gap in §1.2) |
| `emits` | EntityRef | `Envelope[Record]` (§3.2), e.g. `Collection[Socket]`, `Item[FirewallState]`, `Findings[StartupItem]`, `Stream[FsEvent]`, `Result` |
| `encoding` / `data_key` | enum / str | how the envelope arrives on the wire: `list` · `keyed` (name → record) · `wrapped` (`{data_key: [...], facets}`) · `scalar-list`. Adapters normalize before validation (P0.2) |
| `channel` | enum | `stdout` or `artifact:<arg>` for commands whose output is the file they write (`interrogate --output`, `remediate plan --output`, `report --output`) |
| `success_codes` | list[int] | default `[0]`; e.g. `audit` `[0, 1]` (1 = findings present), `deps check` `[0, 1]` (1 = not installed) |
| `severity_map` | dict | Findings only: maps the command's own severity vocabulary/field (`risk: HIGH/REVIEW/LOW`, `severity: ERROR/WARNING/NOTICE`) onto the canonical scale; converges with master-plan T-02 |
| `risk` | enum | `read` · `confirm` · `dangerous` (feeds `ConfirmScreen`, and later T-10 approval tokens) |
| `needs_root` | bool | routes through askpass (§6) |
| `timeout_s` / `long_running` | int / bool | slow actions show progress; long-running ones get Start/Stop |
| `produces` / `consumes` | list[str] | artifact files for pipeline steps (`facts.json` → `findings.json` → …) |

`ArgSpec`: `name`, `kind` (`text`/`path`/`int`/`choice`/`flag`/`multi`), `choices`, `required`, `default`, `help`.

A CommandSpec says nothing about display.

### 3.2 Entity type model: operation envelope × domain record

Each command's output is an entity typed as **`Envelope<Record>`**:

- **Domain record** is the noun: what the data is about. Records are owned by the command group, which acts as a namespace: `net` owns `Socket`, `Connection`, `Process`, `Host`; `startup` owns `StartupItem`; `tcc` owns `Permission`; `firewall` owns `FirewallState`, `AppRule`.
- **Envelope** is the operation kind: what the subcommand did with it. Envelopes are the same across every group.

| Envelope | Operation kind | Examples |
|---|---|---|
| `Collection<R>` | query many | `net list` → `Collection<Socket>` · `startup agents` → `Collection<StartupItem>` · `tcc list` → `Collection<Permission>` |
| `Item<R>` | query one / state | `net inspect` → `Item<Process>` · `firewall status` → `Item<FirewallState>` · `doctor --json` → `Item<HealthReport>` |
| `Findings<R>` | analyze; each finding references a record | `startup audit` → `Findings<StartupItem>` · `scan quick` → `Findings<HostCheck>` · `tcc audit` → `Findings<Permission>` |
| `Definitions<R>` | named catalog | `preset list` → `Definitions<Preset>` · `workflow list` → `Definitions<Workflow>` |
| `Stream<R>` | observe over time | `fswatch watch` → `Stream<FsEvent>` · `net top` → `Stream<ProcessRate>` |
| `Diff<R>` | compare | `snapshot diff` → `Diff<SecurityState>` · `fswatch diff` → `Diff<FileEntry>` |
| `Run<Step>` | execute a sequence | `workflow run`, `chain run`, the analysis pipeline |
| `Result` | mutate | every `enable`/`disable`/`kill`/`apply`/… (ok, message, affected record ref) |
| `Document` | narrate | `ai ask`, `report --format md` |

**Why not inheritance (group → subcommand)?** The probe data (§1.1) disproves it. Inside one group, subcommands return different shapes: `net list` is a collection, `net inspect` one item, `net top` a stream, `net kill` a result. What *is* consistent inside a group is the record: `startup list/agents/daemons/running/disabled` all return `StartupItem` with optional fields, and `startup audit` returns findings about `StartupItem`. What is consistent *across* groups is the envelope: `scan`, `startup audit`, `tcc audit`, `fswatch audit` are all `Findings`. So the model uses generics/composition: one envelope schema per operation kind, parameterized by a record schema.

**Exceptions, handled by the same rules:**
- **Composites:** `status` and `interrogate` are `Item<Composite>` whose fields are other domains' records (`firewall: FirewallState`, `sharing: SharingState`, …). A slot's `select` reaches into a field and gets that record with its own type.
- **Wrappers:** `tune top` is `Item<CommandOutput>` (raw text) until it gets structured fields.
- **Facets** belong to every envelope: `errors` / `access_errors` (permissions) and `meta` (timestamp, scope, source). They bind separately, usually to the notice region.

**Validated against real output (P0.2, `docs/audits/2026-11-18-envelope-taxonomy-validation.md`):** all captured outputs fit the 9 envelopes. Refinements: encoding is separate from envelope (four wire encodings, normalized by adapters); Findings carry a canonical `severity` (critical/high/medium/low/info) mapped from four observed vocabularies; Items routinely embed collections, reached by projection; success codes are per command.

**Record inheritance where it is real:** records share base fields through ordinary subclassing, e.g. `Socket` and `Connection` extend `NetEndpoint` (process, pid, user, local); `LaunchAgent`/`LaunchDaemon`/`LoginItem` narrow `StartupItem` by `type`. This is the part of the vehicle → car intuition that holds.

**Where the contract lives (CLI owns it):** pydantic models in `src/schemas/` (records + generic envelopes). Each `CommandSpec.emits` names one, e.g. `Findings[StartupItem]`. The CLI's current JSON is **not** changed. Today's bare lists/dicts are the envelope's `data` with facets alongside, so scripts and tests keep working. Adapters normalize the few odd wrappers (`startup managed` → `{items, scope, access_errors}`). A later opt-in `--json-envelope` can emit the envelope literally.

**Enforced by tooling, not convention (D10):**
1. *Output contract test:* each read command's output (recorded fixtures + a live smoke run on macOS) validates against its `emits` model.
2. *Binding type-check (manifest load + CI):* each slot's `select` is evaluated against the `emits` JSON Schema, and the projected shape must satisfy the component's `accepts` (envelope kind + required fields, e.g. FindingList requires a severity field).
3. *Drift test:* every CLI action ↔ exactly one CommandSpec with an `emits`.

### 3.3 `ComponentSpec`: what each component can render

Components declare `accepts`: envelope kinds (§3.2) plus any required record fields, checked after projection. There is no fixed entity → component mapping. The renderer validates each binding against `accepts` when the manifest loads.

| Component | Accepts |
|---|---|
| StatusStrip (StatePills) | `Item` with boolean fields · scalar projections |
| KPI cell | scalar projections of any entity (`length(...)`, counts by field) |
| SettingsPanel (ToggleRows) | `Item` with scalar/boolean fields · `Collection` with a state field (e.g. `list` → enable/disable) |
| RecordTable | `Collection` · `Findings` · `Definitions` (as rows) · `Item` (as key/value rows) · `Diff` (flattened) |
| FindingList | `Findings` · `Collection` + a declared severity field |
| DefinitionCatalog | `Definitions` · `Collection` with a name field |
| RecordInspector | `Item` · any selected row of any envelope |
| ReportView | `Document` · `Item` (rendered as text) · `Result` |
| DiffView | `Diff` · two `Collection`s/`Item`s (diffed client-side) |
| LiveStream (+ Sparkline) | `Stream` · `Document` chunks |
| PipelineStepper | `Run` |
| NoticeBanner | `errors` facet · failed `Result` · run progress |
| ActionForm / ActionBar | CommandSpec args (input side; `from_row` fills args from the selected row) |

### 3.4 `Template` and `Page`: what to run, in what order, rendered where

A **template** is a reusable page recipe. It lists ordered **run roles** and the **slots** each role's output is rendered into. A **page** instantiates a template by assigning concrete commands to its roles. A page may add runs and slots or override them. Both use the same two lists:

**`runs`**: ordered command executions.

| Field | Notes |
|---|---|
| `id` | local name (`fw`, `rules`, `detail`) |
| `command` / `args` | CommandSpec id + arg values (literal, `{row.field}`, `{form.field}`, `{run.<id>.<select>}`) |
| `trigger` | `on_open` · `on_view:<tab>` · `on_select:<slot>` · `on_action` · `after:<run>` · `interval:<s>` · `manual` |
| `order` / `wave` | execution order; runs in the same wave execute in parallel |
| `depends_on` | runs whose output feeds this run's args or must finish first |
| `refreshes` | runs to re-execute after this one (a mutation → re-run its read) |

**`slots`**: where each output is rendered. They are listed in composition order (§4.1): header → notice → strip → workspace.main → workspace.aside → dock.

| Field | Notes |
|---|---|
| `region` / `order` | position in the page frame; order comes from position, never from component type |
| `run` + `select` | which run's output, and the JMESPath projection |
| `component` + `props` | any component whose `accepts` matches the projected shape |
| `follows` | the slot whose selection drives this one (aside follows main) |
| `actions` / `row_actions` | CommandSpec ids shown as buttons (page-level or selection-level) |

Example: the Firewall page. One run feeds three components, and a mutation re-runs the read.

```toml
[[page]]
id = "security.firewall"
concern = "security"
order = 2
template = "explorer"

[[page.runs]]
id = "fw";  command = "firewall.status";  trigger = "on_open";  order = 1

[[page.runs]]
id = "toggle";  command = "firewall.set";  trigger = "on_action";  refreshes = ["fw"]

[[page.runs]]
id = "rule";  command = "firewall.app";  trigger = "on_action";  refreshes = ["fw"]
args = { operation = "{form.operation}", path = "{row.path}" }

[[page.slots]]   # strip: same run, rendered as pills
region = "strip";  order = 1;  run = "fw"
select = "{enabled: enabled, stealth: stealth_mode, block_all: block_all}"
component = "StatusStrip"

[[page.slots]]   # main: same run, rendered as toggles
region = "workspace.main";  order = 1;  run = "fw"
select = "{stealth_mode: stealth_mode, block_all: block_all, allows_signed: allows_signed, allows_signed_app: allows_signed_app}"
component = "SettingsPanel";  props.on_toggle = "toggle"

[[page.slots]]   # main: same run, rendered as a table
region = "workspace.main";  order = 2;  run = "fw";  select = "apps"
component = "RecordTable";  props.columns = ["name", "status"]

[[page.slots]]
region = "workspace.aside";  order = 1;  follows = "workspace.main#2"
component = "RecordInspector";  row_actions = ["rule:block", "rule:unblock", "rule:remove"]
```

The schemas are written as plain dataclasses (or pydantic, see §10 decision L1). Templates and pages are stored as TOML (`tomllib` is in the stdlib), which keeps the manifest editable like CMS content. A JSON Schema export lets editors validate the files.

## 4. Component model: ordered by composition

Components are organized by **where they sit and what they contain**, from the outermost frame inward. They are not numbered or sorted by type, and they are not tied to any command. Each level is built from the level below it.

### 4.1 Composition hierarchy

```
Shell ─────────────────────────────────────────────────────────────────────────
│ Sidebar (concern sections ▸ pages)  │  Page frame                 │ Runner rail │
│                                     │  ┌ 1 header ─────────────┐  │ (command    │
│                                     │  ├ 2 notice ─────────────┤  │  log, chat) │
│                                     │  ├ 3 strip ──────────────┤  │             │
│                                     │  ├ 4 workspace ──────────┤  │             │
│                                     │  │   main  │   aside     │  │             │
│                                     │  └ 5 dock ───────────────┘  │             │
└ Command bar ─────────────────────────────────────────────────────────────────┘
```

| Level | Region (render order) | Components that can fill it | Contains (building blocks) | Composes with |
|---|---|---|---|---|
| Shell | left column | **Sidebar** | concern headings, page links, active marker, number-key hints | selects the page |
| Shell | right column | **Runner rail** (existing) | command log, chat/ask | shows every run's command and raw output |
| Shell | bottom | **Command bar** (existing) | free-form `msp …` input, Run/Stop | same runner as buttons |
| Page frame | 1 · header | **PageHeader** | title, **ViewTabs** (switch the active `on_view` run), page **ActionButtons**, Refresh | tabs switch which run feeds main; buttons trigger `on_action` runs or open an aside ActionForm |
| Page frame | 2 · notice | **NoticeBanner** | `errors` facets, run progress + Cancel, privilege badge, fix-it link | shown only while there is something to say |
| Page frame | 3 · strip | **StatusStrip**, **KPI cells**, **SeverityChips** | StatePills, counts, severity filters | summarizes and filters main; re-renders when its run refreshes |
| Page frame | 4 · workspace.main | one or more stacked primaries: SettingsPanel · RecordTable · FindingList · DefinitionCatalog · ReportView · DiffView · PipelineStepper | FilterInput, ToggleRows | selection is the context for aside |
| Page frame | 4 · workspace.aside | RecordInspector + ActionBar, or ActionForm | ArgFields | `on_select` runs fill it; row actions pre-fill args from the selected row |
| Page frame | 5 · dock | LiveStream (+ Sparkline), status line | Start/Stop | streams long-running runs; collapses when idle |

**Shared building blocks** (used inside components; never placed on their own): StatePill, KPI cell, SeverityChip, ToggleRow, ActionButton (risk styling + lock badge for `needs_root`), FilterInput, ArgField (text/path picker/number/select/switch), ViewTabs.

### 4.2 Interaction and run flow

```
open page ─▶ runs wave 1 (on_open, parallel) ─▶ slots render (strip, main, notice)
   │
   ├─ ViewTab ──────────▶ on_view run ─────────▶ main re-binds
   ├─ select row ───────▶ on_select run ───────▶ aside (inspector) + ActionBar enabled
   └─ action / form ────▶ confirm (→ askpass) ─▶ on_action run ─▶ refreshes ─▶ strip + main re-render
                                                     └─ errors/progress ─▶ notice;  command + output ─▶ Runner rail
```

### 4.3 Templates: run roles in order, then where each renders

Templates are listed from the simplest page recipe to the richest. **Runs** are in execution order (`‖` marks the same wave, i.e. parallel). **Slots** are in composition order and give the default component for each role's output. Pages may bind the same role to different or additional components.

| Template | Runs (order → trigger) | Slots (role.select → component @ region) |
|---|---|---|
| **dashboard** | 1 `state` ‖ `cards…` → on_open | state → StatusStrip @ strip · each card run → compact RecordTable or FindingList @ main grid (links to its page) |
| **control-panel** | 1 `state` → on_open · 2 `set` → on_action, refreshes `state` | state.booleans → StatusStrip @ strip · state → SettingsPanel @ main · state.non-booleans → ActionForm(`set`) @ aside |
| **explorer** | 1 `list[tab]` → on_open / on_view · 2 `detail` → on_select · 3 `mutate…` → on_action, refreshes `list` · 4 `stream` → manual | list.errors → NoticeBanner @ notice · list counts → KPI cells @ strip · list → RecordTable @ main · detail → RecordInspector @ aside · mutate → ActionBar / ActionForm @ aside · stream → LiveStream @ dock |
| **review** | 1 `scan` → manual or on_open (cached) · 2 `detail` → on_select · 3 `remedy` → on_action, refreshes `scan` | scan progress → NoticeBanner @ notice · scan severity counts → SeverityChips @ strip · scan → FindingList @ main · detail → RecordInspector @ aside · remedy → ActionBar @ aside |
| **catalog** | 1 `defs` → on_open · 2 `show` → on_select · 3 `act…` → on_action, refreshes `defs` · 4 `run` → on_action | defs → DefinitionCatalog @ main · show → RecordInspector or ReportView @ aside · act → ActionBar @ aside · run → PipelineStepper or LiveStream @ dock |
| **compare** | 1 `a` ‖ `b` → on_action (pickers) · 2 `diff` → after `a`,`b` (or one diff command) | form → ActionForm @ header · diff counts → KPI cells @ strip · diff → DiffView @ main · selected change → RecordInspector @ aside |
| **pipeline** | 1 → 2 → 3 … sequential steps, each `after:` the previous, artifacts via `produces`/`consumes` | steps → PipelineStepper @ main · each step's output → its chosen component inside the stepper · step options → ActionForm @ aside · current step → LiveStream @ dock |
| **console** | 1 `doc` → on_action (prompt) or on_open · 2 `side` → on_open | doc → ReportView @ main · prompt → ActionForm @ aside · side → RecordTable @ aside |

## 5. Pages: concern → page → runs → renders

Sidebar sections follow the user's concern order (D4), with Overview first. Within a section, pages go from status, to inventory, to review, to tools. **Runs** are listed in execution order (`‖` = parallel wave). **Renders** maps each run's output (`.select`) to a component and region, in composition order. The same command appears on several pages and in several components where useful. Every CLI action must have at least one **curated** placement in this table. An auto-generated fallback page (D14) keeps a command reachable meanwhile, but it is not coverage.

| Concern | Page (template) | Runs, in order | Renders (run.select → component @ region) |
|---|---|---|---|
| **Overview** | Dashboard (dashboard) | 1 `status` ‖ `net list` ‖ `scan` (cached latest) ‖ `startup managed` | status.{firewall,gatekeeper,filevault}.enabled → StatusStrip @ strip · `net list`[:5] → RecordTable card · scan.findings[:3] → FindingList card · startup.items[:4] → RecordTable card @ main |
| **Security** | Posture (control-panel) | 1 `security status` · 2 `security set` / `lock` / `sleep` / `computer-sleep` (on_action, refresh 1) | status booleans → StatusStrip @ strip · status → SettingsPanel @ main · lock/sleep → ActionButtons @ header |
| | Firewall (explorer) | 1 `firewall status` · 2 `firewall set` (on_action, refresh 1) · 3 `firewall app add/remove/block/unblock` (on_action, refresh 1) | 1.{enabled,stealth,block_all} → StatusStrip @ strip · 1.settings → SettingsPanel @ main · 1.apps → RecordTable @ main · selected app → RecordInspector + ActionBar(3) @ aside · add → ActionForm(3, path picker) @ aside |
| | Scans (review) | 1 `scan quick` / `deep` / `suspicious` (manual; latest cached on_open) · 2 `scan verify` / `signature` (on_action, path) · 3 `scan report` (on_action) | 1 progress → NoticeBanner @ notice · 1 severity counts → SeverityChips @ strip · 1.findings → FindingList @ main · selected → RecordInspector @ aside · 2 → ReportView @ aside · 3 → ReportView @ dock |
| **Monitoring** | Network (explorer) | 1 `net list` ‖ `net established` (on_view tabs) · 1b `net hosts` / `net arp` (on_view) · 2 `net inspect` (on_select) · 3 `net terminate` / `kill` / `lookup` (on_action, refresh 1) · 4 `net nmap` / `net camsweep` (on_action) · 5 `net top` (manual) | 1 counts → KPI cells @ strip · 1 → RecordTable @ main · 2 → RecordInspector @ aside · 3 → ActionBar @ aside · 4 → RecordTable (results tab) @ main · 5 → LiveStream @ dock |
| | Traffic (explorer) | 1 `traffic summary` ‖ `dns` ‖ `http` (on_view) · 2 `traffic stream` / `capture` (manual) | 1.total/in/out → KPI cells @ strip · 1 → RecordTable @ main · 2 → LiveStream + Sparkline @ dock |
| | File activity (explorer) | 1 `fswatch recent` / `system` / `new` (on_view) · 2 `fswatch audit` (on_view) · 3 `fswatch watch` (manual, path) | 1 → RecordTable @ main · 2 → FindingList @ main (Audit tab) · selected → RecordInspector @ aside · 3 → LiveStream @ dock |
| | Processes & load (console) | 1 `tune top` (on_open, interval) | 1.output → ReportView @ main · parsed load/pressure → KPI cells @ strip (once JSON fields exist) |
| **System control** | Startup & persistence (explorer) | 1 `startup managed` / `login-items` / `agents` / `daemons` / `cron` / `running` / `disabled` / `inventory` / `search` (on_view; search uses `{form.query}`) · 2 `startup enable` / `disable` / `pause` / `start` / `login-remove` / `agent-remove` / `agent-enable` / `agent-disable` (on_action, refresh 1) · 3 `startup login-add` / `agent-add` (on_action, form) | 1 counts by type → KPI cells @ strip · 1 → RecordTable @ main · selected → RecordInspector + ActionBar(2) @ aside · 3 → ActionForm @ aside |
| | Startup audit (review) | 1 `startup audit` ‖ `summary` · 1b `comprehensive-audit` (manual) · 2 `startup disable` (on_action, refresh 1) | 1 severity → SeverityChips @ strip · 1 → FindingList @ main · selected → RecordInspector + ActionBar(2) @ aside |
| **Privacy** | Privacy settings (control-panel) | 1 `status` ‖ `list` · 2 `enable` / `disable` (on_action, refresh 1) · 3 `services` (on_open) | status booleans → StatusStrip @ strip · `list` → SettingsPanel (state toggles → 2) @ main · `services` → RecordTable @ aside |
| | Presets (catalog) | 1 `preset list` · 2 `preset apply` / `delete` (on_action, refresh 1 + Privacy settings) · 3 `preset save` (on_action, form: name + current settings) | 1 → DefinitionCatalog @ main · selected.settings → RecordTable (preview) @ aside · 2 → ActionBar @ aside · 3 → ActionForm @ aside |
| | TCC permissions (explorer) | 1 `tcc list` ‖ `tcc audit` (on_view) · 2 `tcc show` (on_select) · 3 `tcc revoke` / `reset` / `grant` (on_action, refresh 1) · 4 `tcc backup` / `restore` (on_action) | 1.errors → NoticeBanner (Full Disk Access) @ notice · `list`.permissions → RecordTable @ main · `audit`.findings → FindingList @ main (Audit tab) · 2 → RecordInspector @ aside · 3 → ActionBar + ActionForm(grant) @ aside · 4 → ActionButtons @ header |
| | Sharing (control-panel) | 1 `sharing status` · 2 `sharing enable` / `disable` / `disable-guest` / `stop-all` (on_action, refresh 1) | 1.sharing_enabled + services → StatusStrip @ strip · 1.share_points → RecordTable @ main · selected → RecordInspector + ActionBar(2) @ aside |
| **Forensics** | Volume forensics (compare) | 1 `forensics scan` (on_action, volume picker) · 2 `forensics correlate` · 3 `forensics spotlight` · 4 `forensics inspect` (on_select) · 5 `forensics clean` (dangerous) | picker → ActionForm @ header · 1 counts → KPI cells @ strip · 1 → FindingList @ main · 2 → DiffView @ main (Correlate tab) · 3 → RecordTable @ main (Spotlight tab) · 4 → RecordInspector @ aside · 5 → ActionBar @ aside |
| | Snapshots (explorer) | 1 `snapshot list` · 2 `snapshot capture` / `restore` / `delete` (on_action, refresh 1) · 3 `snapshot watch` (manual) | 1 → RecordTable @ main · selected → RecordInspector + ActionBar(2, Diff → Change comparison) @ aside · 3 → LiveStream @ dock |
| | Change comparison (compare) | 1 `snapshot diff {name}` or `fswatch diff {path}` (on_action, picker) | picker → ActionForm @ header · 1 counts → KPI cells @ strip · 1 → DiffView @ main · selected change → RecordInspector @ aside |
| **Automation** | Analysis pipeline (pipeline) | 1 `interrogate` → 2 `audit --profile` → 3 `reason --provider` → 4 `remediate plan` → 5 `remediate apply` (dangerous, optional) → 6 `report --format` (sequential; artifacts facts → findings → plan → report) | steps → PipelineStepper @ main, rendering 1 → RecordInspector, 2 → FindingList, 3 → ReportView, 4 → RecordTable, 6 → ReportView inside each step · options → ActionForm @ aside · current step → LiveStream @ dock |
| | Workflows (catalog) | 1 `workflow list` · 2 `workflow show` (on_select) · 3 `workflow run` (on_action) | 1 → DefinitionCatalog @ main · 2.steps → RecordTable @ aside · 3 → PipelineStepper @ dock |
| | Chains (catalog) | 1 `chain list` · 2 `chain define` / `import` (on_action, form) · 3 `chain run` / `export` / `delete` (on_action) · 4 `chain watch` (manual) | 1 → DefinitionCatalog @ main · selected → RecordInspector @ aside · 2 → ActionForm @ aside · 3 run → PipelineStepper @ dock · 4 → LiveStream @ dock |
| | AI (control-panel + console) | 1 `ai providers` ‖ `ai devices` · 2 `ai configure` (on_action, form) · 3 `ai ask` / `explain` / `suggest` / `analyze` (on_action, prompt) · 4 `ai compare` (on_action) · 5 `ai watch` (manual) | 1.default + local_only → StatusStrip @ strip · 1.providers → DefinitionCatalog @ main · 2 → ActionForm @ aside · 3 → ReportView @ main (Ask tab) · 4 → DiffView @ main (Compare tab) · 5 → LiveStream @ dock |
| **Repair & recovery** | Health (console) | 1 `doctor` (on_open) ‖ `deps status` · 2 `deps install` / `install-all` / `fix`, `doctor fix` (on_action, confirm, refresh 1) | 1.ok → StatusStrip @ strip · doctor.scan.checks → FindingList @ main · deps → RecordTable @ aside · 2 → ActionBar @ aside |
| | Performance (review) | 1 `tune check` (manual) · 2 `tune fix` (on_action, confirm, refresh 1) | 1 severity → SeverityChips @ strip · 1 → FindingList @ main · 2 → ActionBar @ aside |
| | Restore points (explorer) | 1 `snapshot list` ‖ `preset list` (TCC backups once listed by the CLI) · 2 `snapshot restore` / `preset apply` / `tcc restore` (on_action) | 1 merged → RecordTable @ main · selected → RecordInspector + ActionBar(2) @ aside |

Note how outputs are reused: `snapshot list` renders as a RecordTable on Snapshots and as part of a merged RecordTable on Restore points; `firewall status` renders as StatusStrip + SettingsPanel + RecordTable on one page and as StatePills on the Dashboard; `status` feeds the Dashboard strip and the Privacy settings strip.

`tui` itself (and `--v1`) is the Shell, not a page.

## 6. Privileged actions (D3)

**Decision (D13): `sudo -A` with an askpass helper, plus optional Touch ID. Not Keychain.**

- *What the user proposed:* store the admin password in Keychain and use the Keychain prompt to release it to the process.
- *The problem:* that makes the admin password a stored secret. The Keychain item's access list would have to include the Python interpreter, so after one "Always Allow" **any** Python script run by the user could read the admin password silently. It also turns a one-time authorization into a permanent credential.
- *Same experience, safer:* `sudo` already supports a GUI password helper. The TUI runs privileged commands as `sudo -A msp …` with `SUDO_ASKPASS` pointing at a tiny helper that shows a native macOS password dialog (`osascript … display dialog … with hidden answer`). The helper writes the typed password to sudo's stdin. Nothing is stored, and sudo's normal timestamp caching applies.
- *Touch ID:* if the user adds `auth sufficient pam_tid.so` to `/etc/pam.d/sudo_local`, sudo asks for Touch ID before falling back to askpass. Setup is documented in a runbook (`docs/runbooks/tui-admin-auth.md`) and is never edited automatically.
- *Existing privileged paths:* `firewall.py` `_run(privileged=True)` and the TUI process-stop action already elevate with `osascript … with administrator privileges` (also nothing stored). Phase 3 moves them onto the same askpass helper so there is one privilege path (one prompt style, one place to log to the privilege ledger, T-21).
- *UX:* `needs_root` actions show a lock badge, and the confirm screen states "will ask for administrator password". Cancelling the dialog is reported as "cancelled", not as an error.

## 7. Libraries (D6)

Researched 2026-11-18. Versions and dates are from PyPI.

| Need | Choice | Status / reason |
|---|---|---|
| Widgets: tables, trees, markdown, logs, tabs, switches, selects, sparklines, progress | **Textual built-ins** (installed 8.2.8, 2026-06-30) | already a dependency; covers every component in §4.1 |
| Path arguments | **textual-fspicker** 1.0.1 (2026-05-20) | maintained; only depends on textual |
| JSON → component data binding | **jmespath** 1.1.0 (2026-01-22) | pure Python, stable query language; the `bind` field in §3.2 |
| Manifest schema validation + JSON Schema export | **pydantic** 2.14.3 (2026-11-05) *or* stdlib dataclasses + `tomllib` | see decision **L1** |
| CLI-side parsing of macOS tool output for missing `--json` (`arp -a`, `lsof`, `netstat`, `ifconfig`) | **jc** 1.26.2 (2026-10-29) | maintained, has macOS parsers; replaces hand-written regex in `network.py` where `--json` is weak; adopt per module, not wholesale |
| Auto-generated TUI from argparse | argparse-tui 0.3.1 (2024-11-27), Trogon 0.6.0 (2024-10-02) | **Rejected:** about 2 years without a release; renders one form per parser, so the flat-action modules (§1.2) would show every flag on every action; no output rendering. Borrow its parser-introspection approach for the manifest seeder only |
| Charts | textual-plotext 1.0.1 (2024-11-30) | **Not needed initially:** stale; Textual `Sparkline` covers traffic/top rates |
| Component snapshot tests | pytest-textual-snapshot (Textualize) | to verify before adopting; otherwise SVG screenshots via `app.save_screenshot` |

Today's runtime dependencies are argcomplete, rich and textual. Each addition above needs approval (L1/L2).

## 8. Prerequisites: CLI fixes before the TUI binds to it

| P | Fix | Status (2026-11-18) |
|---|---|---|
| P1 | `fswatch` failed to import: syntax error at `src/fswatch.py:148` | **done**. Also: `recent <seconds>` positional accepted; progress lines moved to stderr so `--json` output is clean |
| P2 | global `--json` must work before or after the command | **done**. `main.py` reads args after the command token wherever global flags sit; the duplicate snapshot interceptor was removed (keeping `--sort`/`--interval`); `--help` routing fixed; `workflows`/`remediate`/`forensics` accept `--json` at top level (the `firewall.py` SUPPRESS pattern) |
| P3 | `sharing` printed a Python repr | **done**. Real JSON. Also fixed: `sharing -l` nested protocol blocks were flattened (`"smb": "{"`); services were detected with a per-user `launchctl list` that cannot see system daemons (now listening ports); `sharing_enabled` matched the always-on AirDrop `sharingd`. `privacy_settings` delegates to the same parser |
| P4 | `doctor`/`deps`, `ai devices`: real `--json` output | **doctor done** (`doctor --json` → dependencies, missing required/optional, latest scan checks, `ok`); `deps status --json` already worked; `ai devices` still text (pending) |
| P5 | `ai providers` must not prompt when non-interactive | **done**. Non-interactive `providers` emits JSON (key *source* only, never key values); `configure` exits 2 without a TTY. Also fixed: the provider menu crashed for everyone (mixed tuple/dict item), and `msp ai ask` was a silent no-op (its `if` line had been swallowed by a collapsed comment block) |
| P6 | slow actions (`scan quick/suspicious`, `tune check`, `startup inventory`) exceed 25 s | open. The manifest declares expected duration and the TUI shows progress + cancel; root-cause work is backlog **T-28** |
| P7 | 5 failing tests | **done**. 4 were stale expectations (workflow schema 2.0, 7 new controls, opt-in IP redaction); 1 was a real bug: `remediate apply --yes TOKEN` split the token into characters, so CLI approval tokens never worked (`action="append"`). Suite: 277 passed, 0 failed |

Larger detours found along the way are logged in the master backlog: **T-26** (consolidate CLI dispatch), **T-27** (duplicated status collectors), **T-28** (slow read commands), plus the AI provider-order note on **T-13**.

## 9. Phases

| Phase | Scope | Exit criteria |
|---|---|---|
| 0 | **Taxonomy validation:** the entity shapes (§3.2), component `accepts` (§3.3) and templates (§4.3) are a working draft. Validate them against the real JSON of every read action, then adjust shapes before anything binds to them. Then: schemas (§3); manifest seeder (argparse introspection → draft TOML); hand-curated per-action args and `emits` | **drift test:** every action `choice` in every module ↔ exactly one CommandSpec. **Coverage report** (generated, checked in): per action → curated page(s) or `fallback-only`; fallback placements never count. **Entity test:** each CommandSpec's live/fixture output validates against its `emits` schema. **Binding test:** every page slot's `select` projects to a shape its component `accepts`; every run referenced by a slot exists; run order has no cycles |
| 1 | Shell (Sidebar, page frame regions) + run scheduler (waves, triggers, `refreshes`, one execution per run) + header/notice/strip components + RecordTable, SettingsPanel, FindingList, DefinitionCatalog, RecordInspector; templates dashboard, control-panel, explorer, review (D2); re-express Dashboard/Privacy/Firewall as manifest pages | existing TUI tests green; screenshot parity for those three pages; one run feeding multiple slots executes once |
| 2 | All read-only actions placed per §5; fallback pages (D14) for anything not yet curated, badged "Auto-generated · not yet designed" | every `risk=read` action has a **curated** placement (coverage report shows 0 `fallback-only` read actions); fallback pages render but are excluded from the count |
| 3 | ActionForm, ActionBar row actions, confirm/dangerous flow; askpass privilege path (§6) + runbook | every mutating action has a control; confirm and cancel paths tested; root actions prompt via askpass; mutations re-run their `refreshes` |
| 4 | dock LiveStream (start/stop/cancel), DiffView + compare template | watch/stream/capture start and stop cleanly with no orphan processes |
| 5 | PipelineStepper + pipeline/catalog/console templates: analysis pipeline, workflow run, chain run | end-to-end pipeline run from the TUI produces a report file |
| 6 | Generate RUNNABLES/palette/help from the manifest; delete hand lists and `_requires_confirmation` (gate moves to `CommandSpec.risk`) | no hand-maintained verb list remains; coverage report shows 0 `fallback-only` actions of any risk class (T-21 done criterion) |

Each phase ends with `pytest` green, with screenshots captured headlessly, and with a status entry appended to `docs/audits/2026-11-08-tui-v2.md`.

## 10. Decisions

All decisions needed before Phase 0 are resolved (2026-11-18):

- **L1 → pydantic**, **L2 → jmespath, textual-fspicker, jc** (D11).
- **F1**: resolved by D8; P1–P5 and P7 done (§8).
- **A1 → sudo askpass** (D13).
- **Fallback pages → approved, excluded from coverage** (D14).

## 11. Phase 1 build plan (approved 2026-11-18)

The Firewall prototype was approved for the whole suite. Phase 1 turns it into the shell.

**Integration: one app, not two.** The sidebar replaces the top nav inside `MspTUI` (`msp tui`). The runner rail and command bar stay. The sidebar lists manifest pages by concern (D4 order) and page `order`. Legacy screens that have no page yet stay listed under their concern until Phase 2 replaces them. `switch_view_id` and the number keys keep working, so existing tests and muscle memory survive. `python -m src.tui_pages.preview <page>` stays as the single-page harness.

**Modules** (`src/tui_pages/`):

| Module | Responsibility |
|---|---|
| `runtime.py` | `execute` (live / replay), `preview_command`, `RunScheduler`: plans waves from `order`/`wave`/`depends_on`; triggers `on_open`, `on_view:<tab>`, `on_select:<slot>`, `on_action`, `manual`; caches each run's result for the page visit (one execution per run); `refreshes` re-runs after an action. The plan is pure Python and tested without Textual. Execution runs in thread workers so the UI never blocks |
| `components.py` | PageHeader + ViewTabs, NoticeBanner (errors facet + run progress), StatusStrip, KPICell, SeverityChips, SettingsPanel, RecordTable, FindingList, DefinitionCatalog, RecordInspector |
| `page.py` | `PageView`: lays out slots by template and region, re-renders only the slots of a run that finished, wires `follows`, posts actions |
| `shell.py` | `Sidebar` built from `load_pages()` plus legacy entries |

**Content stays in the manifest, not in code.** Field and value labels move to `src/tui_manifest/labels.toml`. Per-slot titles, columns, `limit`, `count_by`, `link` and `hide_when` move to slot `props`. The firewall-specific constants in the prototype (`LABELS`, `HIDE_WHEN`, the "APPLICATION RULES" title) go away.

**Templates** (`src/tui_manifest/templates.toml`): `dashboard` (main is a card grid), `control-panel`, `explorer`, `review` (main and aside, 2:1). Each declares its layout and the regions it allows. Pages must name a known template, and slots must use allowed regions (checked at load time).

**Pages:**

| Page | Runs | Notes |
|---|---|---|
| `overview.dashboard` | `status` ‖ `net list` ‖ `net established` ‖ `startup managed` ‖ `doctor` (on_open) · `scan quick` (manual, refreshes `doctor`) | Recent findings come from the latest *persisted* scan via `doctor` (projected to findings with JMESPath), so opening the page no longer starts a 30 s+ scan. Each card links to its page |
| `privacy.settings` | `status` ‖ `list` ‖ `services list` (on_open) · `enable` / `disable` (on_action, refresh `list`, `status`) | Firewall rules summary + "Manage rules ›" link to Security ▸ Firewall (parity with today's Privacy tab) |
| `security.firewall` | as prototyped | unchanged behaviour, labels now from the manifest |

**Actions remain preview-only in Phase 1.** They show the exact command. Running them with confirm and askpass is Phase 3. Manual *read* runs (`scan quick`) do execute, because they change nothing.

**Exit checks:** the existing TUI tests stay green, updated only where a legacy screen became a page, with the same behaviour asserted. Headless SVG screenshots of the three pages are saved under `docs/audits/assets/`. A scheduler test proves a run feeding several slots executes once and that `refreshes` re-runs exactly the named runs.

## Status and handoffs

- Audit/status log: `docs/audits/2026-11-08-tui-v2.md` (append dated sections there). Latest: Phase 1 complete (2026-11-18); actions execute in the shell with confirmation (deviation recorded there).
- Phase 0 taxonomy validation: `docs/audits/2026-11-18-envelope-taxonomy-validation.md`.
- Generated coverage: `src/tui_manifest/COVERAGE.md` (`scripts/coverage_report.py`).
