"""Domain records, grouped by the command group (namespace) that owns them.

Field sets come from the captured fixtures (P0.1/P0.2) and, for commands whose
output was empty or not capturable, from the producing source code. Only fields
a component may rely on are declared; everything else passes through as extra.
"""
from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple, Union

from pydantic import Field

from .base import Finding, Record

# --------------------------------------------------------------------------- net


class NetEndpoint(Record):
    process: str
    pid: int
    user: str = ""
    local: str


class Socket(NetEndpoint):
    """`net list`: a listening socket."""

    state: str
    protocol: str


class Connection(NetEndpoint):
    """`net established`: an active connection."""

    remote: str


class ProcessInfo(Record):
    """`net inspect`."""

    pid: int
    process: str
    open_files: List[Any] = Field(default_factory=list)


class Host(Record):
    """`net hosts` (nmap -sn discovery)."""

    ip: str
    status: str = ""
    ports: List[Any] = Field(default_factory=list)


class ArpEntry(Record):
    """`net arp` (empty on the capture host; shape from source)."""

    ip: str


class ListeningServiceRisk(Finding):
    """`status` → listening_services: a socket rated by exposure."""

    SEVERITY_FIELD: ClassVar[str] = "risk"
    SEVERITY_MAP: ClassVar[Dict[str, str]] = {"high": "high", "review": "medium", "low": "low"}
    TITLE_FIELDS: ClassVar[Tuple[str, ...]] = ("process",)
    ID_FIELDS: ClassVar[Tuple[str, ...]] = ("port",)

    process: str
    pid: int
    port: str
    type: str


# ----------------------------------------------------------------------- startup


class StartupItem(Record):
    """Shared by `startup list/agents/daemons/running/disabled/managed/login-items`."""

    name: str
    label: str
    path: str = ""
    type: str = ""
    status: str = ""
    pid: Optional[int] = None


class StartupRisk(Finding):
    """`startup audit/summary/comprehensive-audit`."""

    SEVERITY_FIELD: ClassVar[str] = "risk"
    SEVERITY_MAP: ClassVar[Dict[str, str]] = {"high": "high", "review": "medium", "low": "low"}
    TITLE_FIELDS: ClassVar[Tuple[str, ...]] = ("item",)
    ID_FIELDS: ClassVar[Tuple[str, ...]] = ("item",)

    item: str
    reasons: List[str] = Field(default_factory=list)
    path: str = ""


class CronEntry(Record):
    """`startup cron` (empty on the capture host; shape from source)."""

    entry: str


class StartupInventory(Record):
    """`startup inventory`: sections of startup-related collections."""


# ----------------------------------------------------------------------- privacy


class PrivacySetting(Record):
    """`list`: a toggleable privacy setting."""

    name: str
    category: str
    description: str = ""
    state: Literal["enabled", "disabled", "unknown"]
    requires_root: bool = False


class LaunchService(Record):
    """`services list`."""

    name: str
    pid: str = ""
    status: str = ""


class Preset(Record):
    """`preset list` (name-keyed; adapter puts the key in `key`)."""

    key: str
    name: str
    description: str = ""
    settings: Dict[str, Any] = Field(default_factory=dict)


class PrivacyStatus(Record):
    """`status`: composite of other domains' state."""

    firewall: Dict[str, Any]
    filevault: Dict[str, Any]
    gatekeeper: Dict[str, Any]
    listening_services: List[ListeningServiceRisk] = Field(default_factory=list)


# ---------------------------------------------------------------------- firewall


class AppRule(Record):
    name: str
    path: str = ""
    status: Literal["ALLOW", "BLOCK"]


class FirewallState(Record):
    """`firewall status`."""

    available: bool = True
    enabled: Optional[bool]
    stealth_mode: Optional[bool] = None
    block_all: Optional[bool] = None
    allows_signed: Optional[bool] = None
    allows_signed_app: Optional[bool] = None
    apps: List[AppRule] = Field(default_factory=list)


# ----------------------------------------------------------- sharing / security


class SharePoint(Record):
    name: str
    path: str
    shared: str = ""
    guest_access: str = ""
    protocols: Dict[str, Dict[str, str]] = Field(default_factory=dict)


class SharingState(Record):
    """`sharing status/list`."""

    sharing_enabled: bool
    services: Dict[str, bool] = Field(default_factory=dict)
    share_points: List[SharePoint] = Field(default_factory=list)


class SecurityState(Record):
    """`security status`: nested setting groups (display, energy, firewall)."""

    display: Dict[str, Any] = Field(default_factory=dict)
    energy: Dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- tcc


class Permission(Record):
    """`tcc list/show` (empty without Full Disk Access; shape from source)."""

    service: str = Field(validation_alias="service_name", default="")
    client: str = ""


class TccFinding(Finding):
    """`tcc audit`."""


# ------------------------------------------------------------- scan/audit/shell


class HealthCheck(Finding):
    """`scan quick/deep/suspicious`."""

    category: str = ""
    fixable: bool = False


class Signature(Record):
    """`scan signature`."""

    path: str
    valid: bool
    signed: bool
    authority: str = ""


class RuleFinding(Finding):
    """`audit` (rules engine)."""

    rule_id: str
    category: str = ""
    remediation: str = ""


class ShellFinding(RuleFinding):
    """`shell audit`: same rule shape, ERROR/WARNING/NOTICE levels."""

    SEVERITY_MAP: ClassVar[Dict[str, str]] = {"error": "high", "warning": "medium", "notice": "low"}


class TuneCheck(Finding):
    """`tune check`."""

    domain: str = ""
    fixable: bool = False


class CommandOutput(Record):
    """`tune top`: a wrapped command's raw output."""

    command: str
    returncode: int
    output: str


# ------------------------------------------------------------------ fswatch etc.


class FileEvent(Record):
    """`fswatch recent` (empty on capture; shape from source)."""

    timestamp: str
    call: str = ""
    process: str = ""
    path: str = ""


class FilePath(Record):
    """`fswatch new`: a path (scalar list wrapped by the adapter)."""

    path: str


class FileChange(Finding):
    """`fswatch audit` (empty on capture; shape from source)."""

    TITLE_FIELDS: ClassVar[Tuple[str, ...]] = ("path",)
    ID_FIELDS: ClassVar[Tuple[str, ...]] = ("path",)
    SEVERITY_MAP: ClassVar[Dict[str, str]] = {"info": "info", "low": "low", "medium": "medium", "high": "high"}

    path: str
    severity: str = "info"


class TrafficRow(Record):
    """`traffic summary` (empty on capture; shape from source)."""

    process: str
    bytes_in: int = 0
    bytes_out: int = 0
    total: int = 0


# ---------------------------------------------------------------- snapshot/deps


class Snapshot(Record):
    name: str
    timestamp: str
    path: str = ""
    hostname: str = ""


class SettingChange(Record):
    """`snapshot diff` row."""

    setting: str
    section: str = ""
    snapshot_value: Any = None
    current_value: Any = None
    status: str


class Dependency(Record):
    """`deps status` (name-keyed; adapter puts the key in `name`) and `doctor` dependencies."""

    name: str
    status: str
    required: bool = False
    description: str = ""


class PackageStatus(Record):
    """`deps check <pkg>`."""

    package: str
    status: str


class DoctorReport(Record):
    """`doctor --json`."""

    ok: bool
    dependencies: List[Dependency]
    missing_required: List[str] = Field(default_factory=list)
    missing_optional: List[str] = Field(default_factory=list)
    scan: Optional[Dict[str, Any]] = None


class ConfigSections(Record):
    """`config list`: section -> key -> value."""


# -------------------------------------------------------- workflows/chains/ai


class WorkflowDef(Record):
    id: str
    title: str
    description: str = ""
    steps: Union[int, List[Any]] = 0


class ChainDef(Record):
    """`chain list` (name-keyed; adapter puts the key in `name`)."""

    name: str
    description: str = ""
    steps: List[Any] = Field(default_factory=list)
    default: bool = False


class PlannedStep(Record):
    """`workflow run/show` step."""

    id: str
    title: str
    order: Optional[int] = None
    status: str = ""


class ActionOutcome(Record):
    """`remediate apply` result row (preview or real)."""

    action_id: str
    finding_id: str = ""
    status: str
    dry_run: bool = True
    message: str = ""


class Provider(Record):
    """`ai providers` (never carries key values; only `key_source`)."""

    id: str
    name: str
    model: str = ""
    configured: bool = False
    key_source: Optional[Literal["config", "env"]] = None
    default: bool = False


class Facts(Record):
    """`interrogate` facts bundle (composite; sections reached by projection)."""


class RemediationPlan(Record):
    """`remediate plan` artifact."""

    actions: List[Dict[str, Any]]


RECORDS: Dict[str, type] = {
    name: obj for name, obj in list(globals().items())
    if isinstance(obj, type) and issubclass(obj, Record) and obj.__module__ == __name__
}
