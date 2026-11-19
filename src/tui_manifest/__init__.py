"""TUI manifest: commands, components and pages, plus the checks that keep them honest.

Data files live next to this module:
  commands.toml        one [[command]] per CLI action (curated)
  commands.seed.json   generated inventory (scripts/seed_manifest.py)
  components.toml      what each component accepts
  pages/*.toml         pages: ordered runs + slots binding run output to components
  templates.toml       page recipes: layout + allowed regions
  labels.toml          display text for concerns, fields and values

Checks (plan §9, Phase 0):
  check_drift      every seeded CLI action <-> exactly one CommandSpec
  check_contracts  every fixture validates against its command's `emits`
  check_bindings   every slot projects to a shape its component accepts
  check_pages      known template, allowed regions, valid page links
  coverage         per action: curated pages or fallback-only; contract status
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import jmespath
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from src.schemas import EncodingError, resolve, validate_output

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "cli"
SAMPLES = FIXTURES / "samples"

Risk = Literal["read", "confirm", "dangerous"]
Region = Literal["header", "notice", "strip", "workspace.main", "workspace.aside", "dock"]
REGION_ORDER: Tuple[str, ...] = ("header", "notice", "strip", "workspace.main", "workspace.aside", "dock")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArgSpec(_Strict):
    name: str
    kind: Literal["flag", "choice", "int", "text"]
    option: Optional[str] = None
    required: bool = False
    choices: List[str] = Field(default_factory=list)
    multi: bool = False
    repeat: bool = False   # multi via a repeated option (argparse append): --opt a --opt b

    @property
    def key(self) -> str:
        """Identity: the option string, or the dest for positionals (two options may share a dest)."""
        return self.option or self.name


class CommandSpec(_Strict):
    id: str
    group: str
    argv: List[str]
    emits: str
    encoding: Literal["list", "keyed", "wrapped", "scalar-list", "object", "text", "lines", "exit"]
    data_key: Optional[str] = None
    key_field: str = "name"
    scalar_field: str = "value"
    text_format: Literal["text", "markdown"] = "text"
    channel: str = "stdout"
    success: List[int] = Field(default_factory=lambda: [0])
    risk: Risk = "read"
    needs_root: bool = False
    long_running: bool = False
    active_network: bool = False
    llm: bool = False
    interactive: bool = False
    fixture: Optional[str] = None
    notes: str = ""
    args: List[ArgSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "CommandSpec":
        resolve(self.emits)  # raises KeyError on a bad reference
        if self.encoding == "wrapped" and not self.data_key:
            raise ValueError(f"{self.id}: wrapped encoding needs data_key")
        if self.risk != "read" and self.emits != "Result" and not self.emits.startswith(("Run", "Item")):
            raise ValueError(f"{self.id}: mutating commands emit Result (or a Run/Item record)")
        keys = [arg.key for arg in self.args]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{self.id}: duplicate argument {sorted(k for k in keys if keys.count(k) > 1)}")
        names = [arg.name for arg in self.args]
        if len(names) != len(set(names)):
            # aliases sharing an argparse dest (--json/--format, --force/--dry-run) need
            # their own names, or forms and argv building cannot tell them apart
            raise ValueError(f"{self.id}: duplicate argument name {sorted(n for n in names if names.count(n) > 1)}")
        return self

    @property
    def envelope_kind(self) -> str:
        return self.emits.split("[", 1)[0].lower()

    def normalize_kwargs(self, returncode: Optional[int] = None) -> Dict[str, Any]:
        return {
            "encoding": self.encoding, "data_key": self.data_key, "key_field": self.key_field,
            "scalar_field": self.scalar_field, "text_format": self.text_format,
            "returncode": returncode, "success_codes": tuple(self.success),
        }


class ComponentSpec(_Strict):
    name: str
    accepts: List[str]
    requires: List[str] = Field(default_factory=list)


class RunSpec(_Strict):
    id: str
    command: str
    trigger: str = "on_open"
    order: int = 0
    wave: Optional[int] = None
    depends_on: List[str] = Field(default_factory=list)
    refreshes: List[str] = Field(default_factory=list)
    args: Dict[str, Any] = Field(default_factory=dict)


class TabSpec(_Strict):
    id: str
    title: str


TRIGGER_KINDS = ("on_open", "on_action", "manual", "on_view:", "on_select:", "after:")


class SlotSpec(_Strict):
    region: Region
    order: int
    component: str
    tab: Optional[str] = None     # show only on this view tab (default: the tab of its run)
    run: Optional[str] = None
    select: Optional[str] = None
    facet: Optional[Literal["errors", "access_errors"]] = None
    follows: Optional[str] = None
    actions: List[str] = Field(default_factory=list)
    row_actions: List[str] = Field(default_factory=list)
    props: Dict[str, Any] = Field(default_factory=dict)


class PageMeta(_Strict):
    id: str
    concern: str
    title: str
    order: int
    template: str
    fallback: bool = False


class PageSpec(_Strict):
    page: PageMeta
    tabs: List[TabSpec] = Field(default_factory=list)
    runs: List[RunSpec] = Field(default_factory=list)
    slots: List[SlotSpec] = Field(default_factory=list)

    def slot_tab(self, slot: SlotSpec) -> Optional[str]:
        """The view tab a slot belongs to: explicit ``tab``, else its run's ``on_view`` tab."""
        if slot.tab:
            return slot.tab
        run = next((r for r in self.runs if r.id == slot.run), None)
        return run.trigger.split(":", 1)[1] if run and run.trigger.startswith("on_view:") else None

    @model_validator(mode="after")
    def _check(self) -> "PageSpec":
        run_ids = [run.id for run in self.runs]
        if len(run_ids) != len(set(run_ids)):
            raise ValueError(f"{self.page.id}: duplicate run ids")
        known = set(run_ids)
        for run in self.runs:
            for ref in run.depends_on + run.refreshes:
                if ref not in known:
                    raise ValueError(f"{self.page.id}: run {run.id!r} references unknown run {ref!r}")
        for slot in self.slots:
            for ref in [slot.run] + slot.actions + slot.row_actions + _prop_runs(slot.props):
                if ref and ref not in known:
                    raise ValueError(f"{self.page.id}: slot references unknown run {ref!r}")
        tab_ids = {tab.id for tab in self.tabs}
        slot_keys = {f"{s.region}#{s.order}" for s in self.slots}
        for run in self.runs:
            if not any(run.trigger == k or (k.endswith(":") and run.trigger.startswith(k)) for k in TRIGGER_KINDS):
                raise ValueError(f"{self.page.id}: run {run.id!r} has unknown trigger {run.trigger!r}")
            kind, _, target = run.trigger.partition(":")
            if kind == "on_view" and target not in tab_ids:
                raise ValueError(f"{self.page.id}: run {run.id!r} is triggered by undeclared tab {target!r}")
            if kind == "on_select" and target not in slot_keys:
                raise ValueError(f"{self.page.id}: run {run.id!r} follows unknown slot {target!r}")
            if kind == "after" and target not in known:
                raise ValueError(f"{self.page.id}: run {run.id!r} runs after unknown run {target!r}")
        for slot in self.slots:
            if slot.tab and slot.tab not in tab_ids:
                raise ValueError(f"{self.page.id}: slot {slot.region}#{slot.order} is on undeclared tab {slot.tab!r}")
        _check_acyclic(self.page.id, {run.id: run.depends_on for run in self.runs})
        positions = [(REGION_ORDER.index(s.region), s.order) for s in self.slots]
        if positions != sorted(positions):
            raise ValueError(f"{self.page.id}: slots must be listed in composition order (region, order)")
        return self


def _prop_runs(props: Dict[str, Any]) -> List[str]:
    """Run ids referenced from slot props, e.g. ``on = { run = "enable", ... }``."""
    return [v["run"] for v in props.values() if isinstance(v, dict) and isinstance(v.get("run"), str)]


def _check_acyclic(page_id: str, edges: Dict[str, List[str]]) -> None:
    state: Dict[str, int] = {}

    def visit(node: str, path: Tuple[str, ...]) -> None:
        if state.get(node) == 1:
            raise ValueError(f"{page_id}: run dependency cycle {' -> '.join(path + (node,))}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in edges.get(node, []):
            visit(nxt, path + (node,))
        state[node] = 2

    for node in edges:
        visit(node, ())


class TemplateSpec(_Strict):
    name: str
    layout: Literal["split", "grid"]
    regions: List[Region]


# --------------------------------------------------------------------- loaders

def load_commands(path: Path = HERE / "commands.toml") -> Dict[str, CommandSpec]:
    raw = tomllib.loads(path.read_text())["command"]
    commands = [CommandSpec.model_validate(entry) for entry in raw]
    ids = [c.id for c in commands]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate command ids: {sorted(i for i in ids if ids.count(i) > 1)}")
    return {c.id: c for c in commands}


def load_components(path: Path = HERE / "components.toml") -> Dict[str, ComponentSpec]:
    raw = tomllib.loads(path.read_text())["component"]
    return {name: ComponentSpec(name=name, **spec) for name, spec in raw.items()}


def load_pages(directory: Path = HERE / "pages") -> Dict[str, PageSpec]:
    pages = [PageSpec.model_validate(tomllib.loads(p.read_text())) for p in sorted(directory.glob("*.toml"))]
    return {p.page.id: p for p in pages}


def load_templates(path: Path = HERE / "templates.toml") -> Dict[str, TemplateSpec]:
    raw = tomllib.loads(path.read_text())["template"]
    return {name: TemplateSpec(name=name, **spec) for name, spec in raw.items()}


def load_labels(path: Path = HERE / "labels.toml") -> Dict[str, Dict[str, str]]:
    raw = tomllib.loads(path.read_text())
    return {section: dict(raw.get(section, {})) for section in ("concerns", "fields", "values")}


def check_pages(
    pages: Dict[str, PageSpec],
    templates: Dict[str, TemplateSpec],
    labels: Dict[str, Dict[str, str]],
    extra_links: Tuple[str, ...] = (),
    commands: Optional[Dict[str, CommandSpec]] = None,
) -> List[str]:
    """Pages use a known template and concern, only its regions, and link to real pages."""
    problems = []
    targets = set(pages) | set(extra_links)
    for page in pages.values():
        pid = page.page.id
        template = templates.get(page.page.template)
        if template is None:
            problems.append(f"{pid}: unknown template {page.page.template!r}")
            continue
        if page.page.concern not in labels["concerns"]:
            problems.append(f"{pid}: unknown concern {page.page.concern!r}")
        for run in page.runs:
            command = commands.get(run.command) if commands else None
            automatic = run.trigger == "on_open" or run.trigger.startswith(("on_view:", "on_select:", "after:"))
            if command and automatic and (command.active_network or command.llm or command.interactive):
                why = "sends network traffic" if command.active_network else "sends data to an AI provider" if command.llm else "is interactive"
                problems.append(f"{pid}: run {run.id!r} {why}; it must be manual or on_action, never automatic")
        for slot in page.slots:
            if slot.region not in template.regions:
                problems.append(f"{pid}: {template.name} template has no {slot.region} region")
            link = slot.props.get("link")
            if link and link not in targets:
                problems.append(f"{pid} {slot.region}#{slot.order}: link to unknown page {link!r}")
    return problems


def load_seed(path: Path = HERE / "commands.seed.json") -> Dict[str, Any]:
    return json.loads(path.read_text())


# ---------------------------------------------------------------------- checks

def seed_command_ids(seed: Dict[str, Any]) -> List[str]:
    ids = []
    for group in seed["groups"]:
        for action in group["actions"]:
            name = action["action"]
            if group["group"] == "privacy":
                ids.append("privacy." + name.replace(" ", "."))
            elif not name:
                ids.append(group["group"])
            else:
                ids.append(f"{group['group']}.{name.replace(' ', '.')}")
    return ids


def check_drift(seed: Dict[str, Any], commands: Dict[str, CommandSpec]) -> List[str]:
    seeded = seed_command_ids(seed)
    problems = [f"duplicate seeded action {i}" for i in sorted({i for i in seeded if seeded.count(i) > 1})]
    problems += [f"CLI action without manifest entry: {i}" for i in sorted(set(seeded) - set(commands))]
    problems += [f"manifest entry without CLI action: {i}" for i in sorted(set(commands) - set(seeded))]
    return problems


def _fixture_output(command: CommandSpec, fixture: Dict[str, Any]) -> Any:
    if command.channel.startswith("artifact:"):
        artifact = fixture.get("artifact") or {}
        return artifact["json"] if artifact.get("json") is not None else artifact.get("text")
    return fixture["json"] if fixture.get("json") is not None else fixture.get("text")


def _is_empty(envelope: Any) -> bool:
    data = envelope.data
    return isinstance(data, list) and not data


def command_envelope(command: CommandSpec, fixtures: Path = FIXTURES) -> Tuple[Optional[Any], str]:
    """Best validated envelope for a command and its contract status.

    status: verified | sample | empty-unverified | unverified-shape | no-fixture | failed: <reason>
    """
    if "Unverified" in command.emits:
        return None, "unverified-shape"
    sample_path = fixtures / "samples" / f"{command.id}.json"
    if not command.fixture:
        # never captured (sends traffic, needs root, …): a source-derived sample may stand in
        return _sample_envelope(command, sample_path) if sample_path.exists() else (None, "no-fixture")
    fixture = json.loads((fixtures / f"{command.fixture}.json").read_text())
    if fixture.get("returncode") not in command.success:
        return None, f"failed: exit {fixture.get('returncode')} not in {command.success}"
    try:
        envelope = validate_output(_fixture_output(command, fixture), command.emits,
                                   **command.normalize_kwargs(fixture.get("returncode")))
    except (ValidationError, EncodingError, KeyError) as exc:
        return None, f"failed: {str(exc).splitlines()[0]}"
    if not _is_empty(envelope):
        return envelope, "verified"
    if not sample_path.exists():
        return envelope, "empty-unverified"
    return _sample_envelope(command, sample_path)


def _sample_envelope(command: CommandSpec, sample_path: Path) -> Tuple[Optional[Any], str]:
    try:
        sample = validate_output(json.loads(sample_path.read_text())["json"], command.emits,
                                 **command.normalize_kwargs(0))
    except (ValidationError, EncodingError) as exc:
        return None, f"failed: sample {str(exc).splitlines()[0]}"
    return sample, "sample"


def check_contracts(commands: Dict[str, CommandSpec], fixtures: Path = FIXTURES) -> List[str]:
    problems = []
    for command in commands.values():
        _, status = command_envelope(command, fixtures)
        if status.startswith("failed") or status == "empty-unverified":
            problems.append(f"{command.id}: {status}")
    return problems


def _shape(value: Any) -> Tuple[str, List[Dict[str, Any]]]:
    """Shape kind of a projected value, plus the rows/object to check required fields on."""
    if isinstance(value, list):
        rows = [r for r in value if isinstance(r, dict)]
        if rows and all({"id", "title", "severity"} <= set(r) for r in rows):
            return "findings", rows
        return "collection", rows
    if isinstance(value, dict):
        if value and all(isinstance(v, bool) or v is None for v in value.values()):
            return "booleans", [value]
        return "item", [value]
    return "scalar", []


_SATISFIES = {
    "findings": {"findings", "collection"},
    "booleans": {"booleans", "item"},
}


def check_bindings(
    pages: Dict[str, PageSpec],
    commands: Dict[str, CommandSpec],
    components: Dict[str, ComponentSpec],
    fixtures: Path = FIXTURES,
) -> List[str]:
    problems = []
    for page in pages.values():
        runs = {run.id: run for run in page.runs}
        for run in page.runs:
            if run.command not in commands:
                problems.append(f"{page.page.id}: run {run.id!r} uses unknown command {run.command!r}")
        for slot in page.slots:
            where = f"{page.page.id} {slot.region}#{slot.order} {slot.component}"
            component = components.get(slot.component)
            if component is None:
                problems.append(f"{where}: unknown component")
                continue
            if slot.run is None:
                continue  # follower/inspector slots take the followed slot's selection
            command = commands.get(runs[slot.run].command)
            if command is None:
                continue
            if slot.facet:
                if "errors" not in component.accepts:
                    problems.append(f"{where}: does not accept the {slot.facet} facet")
                continue
            envelope, status = command_envelope(command, fixtures)
            if envelope is None:
                problems.append(f"{where}: cannot check binding, {command.id} contract is {status}")
                continue
            dumped = envelope.model_dump(mode="json")
            data = dumped["data"]
            if slot.select:
                try:
                    projected = jmespath.search(slot.select, data)
                except jmespath.exceptions.JMESPathError as exc:
                    problems.append(f"{where}: invalid select {slot.select!r}: {exc}")
                    continue
                kind, rows = _shape(projected)
                if kind == "collection" and command.envelope_kind in {"findings", "definitions", "diff", "run", "stream"} \
                        and isinstance(data, list):
                    kind = command.envelope_kind
            else:
                kind = command.envelope_kind
                rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
            accepted = _SATISFIES.get(kind, {kind})
            if not accepted & set(component.accepts):
                problems.append(f"{where}: projects to {kind!r}; component accepts {component.accepts}")
                continue
            for field in component.requires:
                missing = [i for i, row in enumerate(rows) if field not in row]
                if missing:
                    problems.append(f"{where}: rows lack required field {field!r}")
    return problems


# Commands whose page needs a later component (plan §12, deferred list).
PIPELINE_COMMANDS = ("reason", "remediate.plan", "report", "workflow.run")


def deferral(command: CommandSpec) -> Optional[str]:
    """Why a read command has no curated page yet, or None if nothing blocks one."""
    if "Unverified" in command.emits:
        return "no verified output contract yet"
    if command.envelope_kind == "stream":
        return "streams output: needs LiveStream (Phase 4)"
    if command.id in PIPELINE_COMMANDS:
        return "pipeline step: needs PipelineStepper (Phase 5)"
    return None


def coverage(
    commands: Dict[str, CommandSpec],
    pages: Dict[str, PageSpec],
    fixtures: Path = FIXTURES,
) -> List[Dict[str, Any]]:
    placements: Dict[str, List[str]] = {cid: [] for cid in commands}
    for page in pages.values():
        if page.page.fallback:
            continue  # D14: fallback pages never count as implementing a command
        for run in page.runs:
            if run.command in placements and page.page.id not in placements[run.command]:
                placements[run.command].append(page.page.id)
    rows = []
    for cid, command in commands.items():
        _, contract = command_envelope(command, fixtures)
        rows.append({
            "id": cid,
            "group": command.group,
            "risk": command.risk,
            "emits": command.emits,
            "contract": contract,
            "pages": placements[cid],
            "status": "curated" if placements[cid] else "fallback-only",
            "deferred": None if placements[cid] else deferral(command),
        })
    return rows


def render_coverage(rows: List[Dict[str, Any]]) -> str:
    curated = sum(1 for r in rows if r["status"] == "curated")
    contracts: Dict[str, int] = {}
    for r in rows:
        key = "failed" if r["contract"].startswith("failed") else r["contract"]
        contracts[key] = contracts.get(key, 0) + 1
    lines = [
        "# TUI command coverage",
        "",
        "Generated by `scripts/coverage_report.py`; do not edit. Fallback pages never count (D14).",
        "",
        f"**Curated placements: {curated}/{len(rows)}** · fallback-only: {len(rows) - curated}",
        "",
        "Contracts: " + " · ".join(f"{k} {v}" for k, v in sorted(contracts.items())),
        "",
    ]
    deferred = [r for r in rows if r["status"] != "curated" and r.get("deferred")]
    if deferred:
        lines += ["## Deferred (reachable on fallback pages meanwhile)", ""]
        for reason in sorted({r["deferred"] for r in deferred}):
            ids = ", ".join(f"`{r['id']}`" for r in deferred if r["deferred"] == reason)
            lines.append(f"- **{reason}:** {ids}")
        lines.append("")
    lines += [
        "| Command | Risk | Emits | Contract | Pages |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        pages = ", ".join(r["pages"]) or ("fallback-only (deferred)" if r.get("deferred") else "fallback-only")
        lines.append(f"| `{r['id']}` | {r['risk']} | `{r['emits']}` | {r['contract']} | {pages} |")
    return "\n".join(lines) + "\n"
