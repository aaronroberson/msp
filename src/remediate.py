#!/usr/bin/env python3
"""Conservative remediation planning and execution primitives.

The remediation layer turns rule findings into explicit actions. It defaults to
planning and dry-runs; callers must opt in to applying commands.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

try:
    from src.command import (
        CommandResult,
        interactive_menu as cmd_interactive_menu,
        interactive_select as cmd_interactive_select,
        list_command,
        setup_completion,
        suggest_command,
    )
except ImportError:  # pragma: no cover - allows direct module execution during development.
    from command import (  # type: ignore
        CommandResult,
        interactive_menu as cmd_interactive_menu,
        interactive_select as cmd_interactive_select,
        list_command,
        setup_completion,
        suggest_command,
    )


SAFETY_LEVELS = ("low", "medium", "high", "destructive")
SAFETY_RANK = {level: index for index, level in enumerate(SAFETY_LEVELS)}


Executor = Callable[..., CommandResult]


@dataclass(frozen=True)
class RemediationAction:
    """A single proposed remediation step."""

    id: str
    finding_id: str
    title: str
    description: str
    safety: str
    requires_sudo: bool = False
    command: Optional[List[str]] = None
    guidance: Optional[str] = None
    rollback_command: Optional[List[str]] = None
    rollback_guidance: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.safety not in SAFETY_RANK:
            raise ValueError(f"Unknown safety level: {self.safety}")
        if not self.command and not self.guidance:
            raise ValueError("RemediationAction needs either command or guidance")

    @property
    def executable(self) -> bool:
        return bool(self.command)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RemediationAction":
        return cls(
            id=str(data["id"]),
            finding_id=str(data["finding_id"]),
            title=str(data["title"]),
            description=str(data["description"]),
            safety=str(data["safety"]),
            requires_sudo=bool(data.get("requires_sudo", False)),
            command=list(data["command"]) if data.get("command") is not None else None,
            guidance=data.get("guidance"),
            rollback_command=list(data["rollback_command"])
            if data.get("rollback_command") is not None
            else None,
            rollback_guidance=data.get("rollback_guidance"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class RemediationPlan:
    """A serializable remediation plan."""

    actions: List[RemediationAction]
    source: str = "findings"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = "1.0"
    skipped_findings: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = [action.to_dict() for action in self.actions]
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RemediationPlan":
        return cls(
            actions=[
                RemediationAction.from_dict(action)
                for action in data.get("actions", [])
            ],
            source=str(data.get("source", "findings")),
            created_at=str(data.get("created_at", "")) or datetime.now(timezone.utc).isoformat(),
            schema_version=str(data.get("schema_version", "1.0")),
            skipped_findings=list(data.get("skipped_findings", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


@dataclass(frozen=True)
class RemediationResult:
    """Execution result for a remediation action."""

    action_id: str
    finding_id: str
    status: str
    dry_run: bool = True
    command_result: Optional[Dict[str, Any]] = None
    message: str = ""
    rollback: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RemediationPlanner:
    """Map rule findings to conservative remediation actions."""

    def __init__(self, executor: Executor = list_command) -> None:
        self.executor = executor

    def plan_from_findings(
        self,
        findings: Iterable[Mapping[str, Any]],
        *,
        max_safety: str = "destructive",
    ) -> RemediationPlan:
        self._validate_safety(max_safety)
        actions: List[RemediationAction] = []
        skipped: List[Dict[str, Any]] = []

        for finding in findings:
            rule_id = str(finding.get("rule_id", ""))
            mapped = self._actions_for_finding(finding)
            if not mapped:
                skipped.append(
                    {
                        "rule_id": rule_id,
                        "reason": "No conservative remediation is available.",
                    }
                )
                continue

            for action in mapped:
                if self._safety_allows(action.safety, max_safety):
                    actions.append(action)
                else:
                    skipped.append(
                        {
                            "rule_id": rule_id,
                            "action_id": action.id,
                            "reason": f"Action exceeds max safety {max_safety}.",
                            "safety": action.safety,
                        }
                    )

        return RemediationPlan(
            actions=actions,
            skipped_findings=skipped,
            metadata={"max_safety": max_safety},
        )

    def plan_from_findings_json(
        self,
        payload: str,
        *,
        max_safety: str = "destructive",
    ) -> RemediationPlan:
        return self.plan_from_findings(
            _extract_findings(json.loads(payload)),
            max_safety=max_safety,
        )

    def apply_plan(
        self,
        plan: RemediationPlan,
        *,
        apply: bool = False,
        allow_high_risk: bool = False,
        max_safety: str = "destructive",
        timeout: float = 60,
    ) -> List[RemediationResult]:
        self._validate_safety(max_safety)
        results: List[RemediationResult] = []

        for action in plan.actions:
            if not self._safety_allows(action.safety, max_safety):
                results.append(
                    self._skipped(
                        action,
                        f"Skipped because safety {action.safety} exceeds {max_safety}.",
                        dry_run=not apply,
                    )
                )
                continue

            if action.safety in {"high", "destructive"} and not allow_high_risk:
                results.append(
                    self._skipped(
                        action,
                        "High-risk actions require --allow-high-risk.",
                        dry_run=not apply,
                    )
                )
                continue

            if not action.command:
                results.append(
                    RemediationResult(
                        action_id=action.id,
                        finding_id=action.finding_id,
                        status="guidance",
                        dry_run=not apply,
                        message=action.guidance or "Manual review required.",
                        rollback=self._rollback_payload(action),
                    )
                )
                continue

            if not apply:
                results.append(
                    RemediationResult(
                        action_id=action.id,
                        finding_id=action.finding_id,
                        status="dry_run",
                        dry_run=True,
                        command_result={
                            "command": list(action.command),
                            "requires_sudo": action.requires_sudo,
                        },
                        message="Dry run only. Re-run apply with --apply to execute.",
                        rollback=self._rollback_payload(action),
                    )
                )
                continue

            command_result = self.executor(
                action.command,
                sudo=action.requires_sudo,
                dry_run=False,
                timeout=timeout,
            )
            results.append(
                RemediationResult(
                    action_id=action.id,
                    finding_id=action.finding_id,
                    status="applied" if command_result.success else "failed",
                    dry_run=False,
                    command_result=command_result.to_dict(),
                    message="Command completed." if command_result.success else "Command failed.",
                    rollback=self._rollback_payload(action),
                )
            )

        return results

    def _actions_for_finding(
        self,
        finding: Mapping[str, Any],
    ) -> List[RemediationAction]:
        rule_id = str(finding.get("rule_id", ""))
        action_id = rule_id.lower().replace("-", "_")

        if rule_id == "FW-001":
            return [
                RemediationAction(
                    id=f"{action_id}_enable_firewall",
                    finding_id=rule_id,
                    title="Enable application firewall",
                    description="Turns on the macOS application firewall.",
                    safety="medium",
                    requires_sudo=True,
                    command=[
                        "/usr/libexec/ApplicationFirewall/socketfilterfw",
                        "--setglobalstate",
                        "on",
                    ],
                    rollback_command=[
                        "/usr/libexec/ApplicationFirewall/socketfilterfw",
                        "--setglobalstate",
                        "off",
                    ],
                    rollback_guidance="Disabling the firewall reduces network protection.",
                )
            ]

        if rule_id == "FW-002":
            return [
                RemediationAction(
                    id=f"{action_id}_enable_stealth",
                    finding_id=rule_id,
                    title="Enable firewall stealth mode",
                    description="Suppresses responses to unsolicited network probes.",
                    safety="low",
                    requires_sudo=True,
                    command=[
                        "/usr/libexec/ApplicationFirewall/socketfilterfw",
                        "--setstealthmode",
                        "on",
                    ],
                    rollback_command=[
                        "/usr/libexec/ApplicationFirewall/socketfilterfw",
                        "--setstealthmode",
                        "off",
                    ],
                )
            ]

        if rule_id == "GK-001":
            return [
                RemediationAction(
                    id=f"{action_id}_enable_gatekeeper",
                    finding_id=rule_id,
                    title="Enable Gatekeeper",
                    description="Enables app assessment enforcement with spctl.",
                    safety="medium",
                    requires_sudo=True,
                    command=["spctl", "--master-enable"],
                    rollback_command=["spctl", "--master-disable"],
                    rollback_guidance="Only disable Gatekeeper temporarily for controlled testing.",
                )
            ]

        if rule_id == "SEC-001":
            return [
                RemediationAction(
                    id=f"{action_id}_enable_password_after_sleep",
                    finding_id=rule_id,
                    title="Require password after sleep",
                    description="Requires a password after sleep or screen saver.",
                    safety="low",
                    command=[
                        "defaults",
                        "write",
                        "com.apple.screensaver",
                        "askForPassword",
                        "-int",
                        "1",
                    ],
                    rollback_command=[
                        "defaults",
                        "write",
                        "com.apple.screensaver",
                        "askForPassword",
                        "-int",
                        "0",
                    ],
                ),
                self._password_delay_zero_action(rule_id, action_id),
            ]

        if rule_id == "SEC-002":
            return [self._password_delay_zero_action(rule_id, action_id)]

        if rule_id == "SEC-003":
            minutes = _screen_lock_minutes(finding)
            return [
                RemediationAction(
                    id=f"{action_id}_screen_lock_timeout",
                    finding_id=rule_id,
                    title="Reduce screen lock timeout",
                    description=f"Sets screen saver idle timeout to {minutes} minutes.",
                    safety="low",
                    command=[
                        "defaults",
                        "-currentHost",
                        "write",
                        "com.apple.screensaver",
                        "idleTime",
                        "-int",
                        str(minutes * 60),
                    ],
                    rollback_guidance="Restore the previous screen saver idleTime value if needed.",
                    metadata={"minutes": minutes},
                )
            ]

        if rule_id == "NW-002":
            return [
                RemediationAction(
                    id=f"{action_id}_remote_login_off",
                    finding_id=rule_id,
                    title="Disable remote login",
                    description="Disables macOS Remote Login/SSH.",
                    safety="medium",
                    requires_sudo=True,
                    command=["systemsetup", "-setremotelogin", "off"],
                    rollback_command=["systemsetup", "-setremotelogin", "on"],
                )
            ]

        if rule_id in {"SH-001", "SH-002"}:
            return [
                RemediationAction(
                    id=f"{action_id}_sharing_guidance",
                    finding_id=rule_id,
                    title="Review sharing configuration",
                    description="Sharing changes can disrupt expected access, so this is guidance-only.",
                    safety="medium",
                    guidance=(
                        "Review enabled sharing services and share points in System Settings > "
                        "General > Sharing, then disable anything not explicitly required."
                    ),
                    rollback_guidance="Re-enable required sharing services from System Settings.",
                )
            ]

        if rule_id == "TCC-001":
            return self._tcc_actions(finding, action_id)

        if rule_id == "TCC-002":
            return [
                RemediationAction(
                    id=f"{action_id}_reset_screen_capture",
                    finding_id=rule_id,
                    title="Reset Screen Recording permissions",
                    description="Resets all Screen Recording grants through tccutil.",
                    safety="high",
                    command=["tccutil", "reset", "ScreenCapture"],
                    guidance=(
                        "After reset, apps that legitimately need Screen Recording must request it again."
                    ),
                    rollback_guidance="There is no command-line rollback for TCC resets; re-grant in System Settings.",
                )
            ]

        if rule_id in {"ST-001", "ST-002"}:
            return [
                RemediationAction(
                    id=f"{action_id}_startup_guidance",
                    finding_id=rule_id,
                    title="Investigate startup persistence",
                    description="Startup item removal is guidance-only to avoid destructive deletion.",
                    safety="high",
                    guidance=(
                        "Inspect each startup item, verify ownership and signature, then unload or "
                        "remove only entries confirmed to be unauthorized."
                    ),
                    rollback_guidance="Keep a copy of any removed plist or executable before changing it.",
                )
            ]

        return []

    def _tcc_actions(
        self,
        finding: Mapping[str, Any],
        action_id: str,
    ) -> List[RemediationAction]:
        services = _tcc_services_from_finding(finding)
        if not services:
            return [
                RemediationAction(
                    id=f"{action_id}_tcc_review_guidance",
                    finding_id="TCC-001",
                    title="Review high-risk TCC grants",
                    description="Specific TCC service reset could not be inferred from the finding.",
                    safety="high",
                    guidance=(
                        "Review Privacy & Security grants for Camera, Microphone, Screen Recording, "
                        "Accessibility, Full Disk Access, and Input Monitoring. Reset only unnecessary grants."
                    ),
                    rollback_guidance="There is no command-line rollback for TCC resets.",
                )
            ]

        return [
            RemediationAction(
                id=f"{action_id}_reset_{service.lower()}",
                finding_id="TCC-001",
                title=f"Reset {service} permissions",
                description=f"Resets {service} grants through tccutil.",
                safety="high",
                command=["tccutil", "reset", service],
                guidance=f"Apps that need {service} access must request it again after reset.",
                rollback_guidance="There is no command-line rollback for TCC resets; re-grant in System Settings.",
                metadata={"service": service},
            )
            for service in sorted(services)
        ]

    def _password_delay_zero_action(
        self,
        rule_id: str,
        action_id: str,
    ) -> RemediationAction:
        return RemediationAction(
            id=f"{action_id}_password_delay_zero",
            finding_id=rule_id,
            title="Set password-after-sleep delay to zero",
            description="Requires a password immediately after sleep or screen saver.",
            safety="low",
            command=[
                "defaults",
                "write",
                "com.apple.screensaver",
                "askForPasswordDelay",
                "-int",
                "0",
            ],
            rollback_guidance="Restore the previous askForPasswordDelay value if needed.",
        )

    def _skipped(
        self,
        action: RemediationAction,
        message: str,
        *,
        dry_run: bool,
    ) -> RemediationResult:
        return RemediationResult(
            action_id=action.id,
            finding_id=action.finding_id,
            status="skipped",
            dry_run=dry_run,
            message=message,
            rollback=self._rollback_payload(action),
        )

    @staticmethod
    def _rollback_payload(action: RemediationAction) -> Optional[Dict[str, Any]]:
        if not action.rollback_command and not action.rollback_guidance:
            return None
        return {
            "command": action.rollback_command,
            "guidance": action.rollback_guidance,
        }

    @staticmethod
    def _safety_allows(action_safety: str, max_safety: str) -> bool:
        return SAFETY_RANK[action_safety] <= SAFETY_RANK[max_safety]

    @staticmethod
    def _validate_safety(level: str) -> None:
        if level not in SAFETY_RANK:
            raise ValueError(f"Unknown safety level: {level}")


def _extract_findings(payload: Any) -> List[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        findings = payload.get("findings", [])
    else:
        findings = payload
    if not isinstance(findings, list):
        raise ValueError("Findings JSON must contain a list or a {'findings': [...]} object")
    return [finding for finding in findings if isinstance(finding, Mapping)]


def _screen_lock_minutes(finding: Mapping[str, Any]) -> int:
    profile = str(finding.get("profile", "personal"))
    if profile in {"enterprise", "high_security"}:
        return 5
    return 15


def _tcc_services_from_finding(finding: Mapping[str, Any]) -> set[str]:
    evidence = finding.get("evidence", {})
    if not isinstance(evidence, Mapping):
        return set()

    grants = evidence.get("tcc.high_risk_grants", [])
    services: set[str] = set()
    if isinstance(grants, Mapping):
        grants = grants.values()
    if not isinstance(grants, Sequence) or isinstance(grants, (str, bytes)):
        return services

    for grant in grants:
        if not isinstance(grant, Mapping):
            continue
        service = grant.get("service") or grant.get("tcc_service") or grant.get("name")
        normalized = _normalize_tcc_service(str(service)) if service else None
        if normalized:
            services.add(normalized)
    return services


def _normalize_tcc_service(service: str) -> Optional[str]:
    cleaned = service.replace("kTCCService", "").replace("SystemPolicyAllFiles", "AllFiles")
    aliases = {
        "camera": "Camera",
        "microphone": "Microphone",
        "screen": "ScreenCapture",
        "screencapture": "ScreenCapture",
        "accessibility": "Accessibility",
        "allfiles": "SystemPolicyAllFiles",
        "fulldisk": "SystemPolicyAllFiles",
        "inputmonitoring": "ListenEvent",
        "listenevent": "ListenEvent",
    }
    return aliases.get(cleaned.lower(), cleaned or None)


def _read_json_file(path: str) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_output(payload: str, output: Optional[str]) -> None:
    if output:
        Path(output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


def _results_to_dict(results: Sequence[RemediationResult]) -> Dict[str, Any]:
    return {
        "results": [result.to_dict() for result in results],
        "summary": {
            "total": len(results),
            "applied": sum(1 for result in results if result.status == "applied"),
            "failed": sum(1 for result in results if result.status == "failed"),
            "skipped": sum(1 for result in results if result.status == "skipped"),
            "dry_run": sum(1 for result in results if result.status == "dry_run"),
            "guidance": sum(1 for result in results if result.status == "guidance"),
        },
    }


def _human_plan(plan: RemediationPlan) -> str:
    lines = [
        f"Remediation plan: {len(plan.actions)} action(s)",
        f"Schema: {plan.schema_version}",
    ]
    for action in plan.actions:
        mode = "command" if action.command else "guidance"
        lines.append(
            f"- {action.id} [{action.safety}, {mode}]: {action.title}"
        )
    if plan.skipped_findings:
        lines.append(f"Skipped findings: {len(plan.skipped_findings)}")
    return "\n".join(lines)


def _human_results(results: Sequence[RemediationResult]) -> str:
    lines = [f"Remediation results: {len(results)} action(s)"]
    for result in results:
        lines.append(f"- {result.action_id}: {result.status} - {result.message}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and apply conservative remediations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Create a remediation plan from findings JSON.")
    plan_parser.add_argument("findings_json", help="Path to findings JSON.")
    plan_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    plan_parser.add_argument("--output", help="Write output to a file.")
    plan_parser.add_argument(
        "--max-safety",
        choices=SAFETY_LEVELS,
        default="destructive",
        help="Highest safety level to include in the plan.",
    )

    apply_parser = subparsers.add_parser("apply", help="Dry-run or apply a remediation plan.")
    apply_parser.add_argument("plan_json", help="Path to remediation plan JSON.")
    apply_parser.add_argument("--apply", action="store_true", help="Actually execute commands.")
    apply_parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    apply_parser.add_argument("--output", help="Write output to a file.")
    apply_parser.add_argument(
        "--max-safety",
        choices=SAFETY_LEVELS,
        default="destructive",
        help="Highest safety level to execute.",
    )
    apply_parser.add_argument(
        "--allow-high-risk",
        action="store_true",
        help="Allow high or destructive actions to run.",
    )

    return parser


def interactive_menu() -> None:
    """Interactive menu for remediation planning."""
    from .facts import collect_facts
    from .rules import evaluate as rules_evaluate, findings_to_json

    while True:
        action = cmd_interactive_menu([
            ("1", "Full chain: interrogate → audit → plan", None),
            ("2", "Load findings from file & plan", None),
            ("3", "Load plan from file & apply", None),
        ], title="Remediate - Remediation Planning")

        if action is None:
            break

        if action == "1":
            print("\nCollecting system facts...")
            try:
                facts = collect_facts(redact=False)
                print("Evaluating with personal profile...")
                findings = rules_evaluate(facts, profile="personal")
                payload = json.loads(findings_to_json(findings))
                planner = RemediationPlanner()
                safeties = ["informational", "moderate", "aggressive", "destructive"]
                items = [(s, s, None) for s in safeties]
                result = cmd_interactive_select(items, title="Select max safety level")
                max_safety = result[0] if result else "destructive"
                plan = planner.plan_from_findings(
                    _extract_findings(payload),
                    max_safety=max_safety,
                )
                print(_human_plan(plan))
            except Exception as e:
                print(f"Error: {e}")
            input("\nPress Enter to continue...")
        elif action == "2":
            path = input("Path to findings JSON file: ").strip()
            if path:
                try:
                    payload = _read_json_file(path)
                    planner = RemediationPlanner()
                    safeties = ["informational", "moderate", "aggressive", "destructive"]
                    items = [(s, s, None) for s in safeties]
                    result = cmd_interactive_select(items, title="Select max safety level")
                    max_safety = result[0] if result else "destructive"
                    plan = planner.plan_from_findings(
                        _extract_findings(payload),
                        max_safety=max_safety,
                    )
                    print(_human_plan(plan))
                except Exception as e:
                    print(f"Error: {e}")
            input("\nPress Enter to continue...")
        elif action == "3":
            path = input("Path to plan JSON file: ").strip()
            if path:
                try:
                    plan = RemediationPlan.from_dict(_read_json_file(path))
                    apply = input("Apply remediations? (y/N): ").strip().lower() == "y"
                    planner = RemediationPlanner()
                    results = planner.apply_plan(plan, apply=apply)
                    print(_human_results(results))
                except Exception as e:
                    print(f"Error: {e}")
            input("\nPress Enter to continue...")


def main(argv: Optional[Sequence[str]] = None) -> int:
    if (argv is None and len(sys.argv) <= 1) or (argv is not None and len(argv) == 0):
        interactive_menu()
        return 0
    parser = build_parser()
    setup_completion(parser)
    args = parser.parse_args(argv)
    planner = RemediationPlanner()

    try:
        if args.command == "plan":
            payload = _read_json_file(args.findings_json)
            plan = planner.plan_from_findings(
                _extract_findings(payload),
                max_safety=args.max_safety,
            )
            output = plan.to_json() if args.json or args.output else _human_plan(plan)
            _write_output(output, args.output)
            return 0

        plan = RemediationPlan.from_dict(_read_json_file(args.plan_json))
        results = planner.apply_plan(
            plan,
            apply=args.apply,
            allow_high_risk=args.allow_high_risk,
            max_safety=args.max_safety,
        )
        result_payload = _results_to_dict(results)
        output = (
            json.dumps(result_payload, indent=2, sort_keys=True)
            if args.json or args.output
            else _human_results(results)
        )
        _write_output(output, args.output)
        return 1 if any(result.status == "failed" for result in results) else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"remediate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
