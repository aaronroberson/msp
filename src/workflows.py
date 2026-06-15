#!/usr/bin/env python3
"""Built-in non-destructive workflow runner for macOS privacy operations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.command import setup_completion, suggest_command

try:
    from .llm import LLMReasoner
except ImportError:  # pragma: no cover - direct script execution fallback
    from llm import LLMReasoner  # type: ignore


WORKFLOW_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class WorkflowStep:
    id: str
    concept: str
    title: str
    description: str
    command_hint: str
    destructive: bool = False
    inputs: Sequence[str] = field(default_factory=tuple)
    outputs: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class Workflow:
    id: str
    title: str
    description: str
    steps: Sequence[WorkflowStep]


def _step(
    step_id: str,
    concept: str,
    title: str,
    description: str,
    command_hint: str,
    inputs: Sequence[str] = (),
    outputs: Sequence[str] = (),
    destructive: bool = False,
) -> WorkflowStep:
    return WorkflowStep(
        id=step_id,
        concept=concept,
        title=title,
        description=description,
        command_hint=command_hint,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        destructive=destructive,
    )


BUILTIN_WORKFLOWS: Dict[str, Workflow] = {
    "daily": Workflow(
        id="daily",
        title="Daily Privacy Check",
        description="Fast recurring posture review for drift and newly exposed surfaces.",
        steps=(
            _step(
                "collect",
                "interrogate",
                "Collect current facts",
                "Gather normalized host, network, sharing, TCC, startup, and settings facts.",
                "msp interrogate --format json --output facts.json",
                outputs=("facts.json",),
            ),
            _step(
                "audit",
                "audit",
                "Evaluate baseline rules",
                "Run the personal profile against collected facts.",
                "msp audit --profile personal --format json < facts.json > findings.json",
                inputs=("facts.json",),
                outputs=("findings.json",),
            ),
            _step(
                "reason",
                "reason",
                "Summarize risk",
                "Use optional LLM reasoning or local heuristics to explain the highest-priority issues.",
                "msp reason --facts facts.json --findings findings.json --format json",
                inputs=("facts.json", "findings.json"),
                outputs=("reasoning.json",),
            ),
            _step(
                "report",
                "report",
                "Write evidence report",
                "Generate a redacted report for daily history.",
                "msp report --facts facts.json --findings findings.json --format md --output daily.md",
                inputs=("facts.json", "findings.json"),
                outputs=("daily.md",),
            ),
        ),
    ),
    "incident": Workflow(
        id="incident",
        title="Incident Triage",
        description="Evidence-first interrogation for suspected compromise or suspicious behavior.",
        steps=(
            _step(
                "collect",
                "interrogate",
                "Collect expanded facts",
                "Capture broad system state including persistence, network exposure, TCC, and profiles.",
                "msp interrogate --deep --format json --output incident-facts.json",
                outputs=("incident-facts.json",),
            ),
            _step(
                "audit",
                "audit",
                "Run high-signal rules",
                "Evaluate high-security checks to prioritize risky exposure.",
                "msp audit --profile high_security --format json < incident-facts.json > incident-findings.json",
                inputs=("incident-facts.json",),
                outputs=("incident-findings.json",),
            ),
            _step(
                "reason",
                "reason",
                "Build triage narrative",
                "Explain likely risk areas, evidence gaps, and next investigative actions.",
                "msp reason --facts incident-facts.json --findings incident-findings.json --format json",
                inputs=("incident-facts.json", "incident-findings.json"),
                outputs=("incident-reasoning.json",),
            ),
            _step(
                "remediate-plan",
                "remediate plan",
                "Prepare safe remediation plan",
                "Generate proposed actions without applying changes.",
                "msp remediate plan --findings incident-findings.json --dry-run --format json",
                inputs=("incident-findings.json",),
                outputs=("incident-plan.json",),
            ),
            _step(
                "report",
                "report",
                "Export incident bundle",
                "Create redacted JSON evidence suitable for handoff.",
                "msp report --facts incident-facts.json --findings incident-findings.json --plan incident-plan.json --format json",
                inputs=("incident-facts.json", "incident-findings.json", "incident-plan.json"),
                outputs=("incident-bundle.json",),
            ),
        ),
    ),
    "harden": Workflow(
        id="harden",
        title="Hardening Plan",
        description="Plan privacy and security hardening without applying destructive changes.",
        steps=(
            _step(
                "collect",
                "interrogate",
                "Collect hardening facts",
                "Gather current state before recommending changes.",
                "msp interrogate --format json --output harden-facts.json",
                outputs=("harden-facts.json",),
            ),
            _step(
                "audit",
                "audit",
                "Evaluate enterprise posture",
                "Use the enterprise profile to identify hardening candidates.",
                "msp audit --profile enterprise --format json < harden-facts.json > harden-findings.json",
                inputs=("harden-facts.json",),
                outputs=("harden-findings.json",),
            ),
            _step(
                "remediate-plan",
                "remediate plan",
                "Generate remediation plan",
                "Create an ordered, dry-run list of supported changes.",
                "msp remediate plan --findings harden-findings.json --dry-run --format json",
                inputs=("harden-findings.json",),
                outputs=("harden-plan.json",),
            ),
            _step(
                "reason",
                "reason",
                "Explain tradeoffs",
                "Summarize privacy benefits, operational impact, and manual review points.",
                "msp reason --facts harden-facts.json --findings harden-findings.json --plan harden-plan.json",
                inputs=("harden-facts.json", "harden-findings.json", "harden-plan.json"),
                outputs=("harden-reasoning.json",),
            ),
            _step(
                "report",
                "report",
                "Write hardening report",
                "Export the plan and supporting evidence.",
                "msp report --facts harden-facts.json --findings harden-findings.json --plan harden-plan.json --format md",
                inputs=("harden-facts.json", "harden-findings.json", "harden-plan.json"),
                outputs=("harden.md",),
            ),
        ),
    ),
    "evidence": Workflow(
        id="evidence",
        title="Evidence Bundle",
        description="Collect and package current posture evidence for audit or support.",
        steps=(
            _step(
                "collect",
                "interrogate",
                "Collect evidence facts",
                "Capture normalized state for reporting.",
                "msp interrogate --format json --output evidence-facts.json",
                outputs=("evidence-facts.json",),
            ),
            _step(
                "audit",
                "audit",
                "Evaluate findings",
                "Run a balanced profile to annotate evidence with rule outcomes.",
                "msp audit --profile personal --format json < evidence-facts.json > evidence-findings.json",
                inputs=("evidence-facts.json",),
                outputs=("evidence-findings.json",),
            ),
            _step(
                "report",
                "report",
                "Create evidence bundle",
                "Export redacted JSON evidence.",
                "msp report --facts evidence-facts.json --findings evidence-findings.json --format json",
                inputs=("evidence-facts.json", "evidence-findings.json"),
                outputs=("evidence-bundle.json",),
            ),
        ),
    ),
}


def list_workflows() -> List[Dict[str, str]]:
    return [
        {
            "id": workflow.id,
            "title": workflow.title,
            "description": workflow.description,
            "steps": str(len(workflow.steps)),
        }
        for workflow in BUILTIN_WORKFLOWS.values()
    ]


def get_workflow(workflow_id: str) -> Workflow:
    try:
        return BUILTIN_WORKFLOWS[workflow_id]
    except KeyError as exc:
        raise ValueError(f"unknown workflow: {workflow_id}") from exc


def workflow_to_dict(workflow: Workflow) -> Dict[str, Any]:
    return {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "id": workflow.id,
        "title": workflow.title,
        "description": workflow.description,
        "steps": [asdict(step) for step in workflow.steps],
    }


def run_workflow(
    workflow_id: str,
    dry_run: bool = True,
    include_reasoning: bool = True,
    reasoner: Optional[LLMReasoner] = None,
) -> Dict[str, Any]:
    """Return an execution plan. Destructive actions are never executed here."""

    workflow = get_workflow(workflow_id)
    steps: List[Dict[str, Any]] = []
    for index, step in enumerate(workflow.steps, start=1):
        steps.append(
            {
                **asdict(step),
                "order": index,
                "status": "planned" if dry_run else "not_executed",
                "will_execute": False,
                "reason": "workflow runner is non-destructive and returns planned CLI steps",
            }
        )

    result: Dict[str, Any] = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "workflow": {
            "id": workflow.id,
            "title": workflow.title,
            "description": workflow.description,
        },
        "dry_run": bool(dry_run),
        "destructive_actions_allowed": False,
        "steps": steps,
    }
    if include_reasoning:
        active_reasoner = reasoner or LLMReasoner()
        findings = [
            {
                "severity": "info",
                "category": "workflow",
                "title": f"Workflow {workflow.id} planned",
                "rule_id": f"WF-{workflow.id.upper()}",
            }
        ]
        result["reasoning"] = active_reasoner.analyze(
            facts={"workflow": workflow_to_dict(workflow)},
            findings=findings,
            plan={"steps": steps},
        )
    return result


def render_text_workflow_list(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = ["Available workflows:"]
    for row in rows:
        lines.append(f"- {row['id']}: {row['title']} ({row['steps']} steps)")
    return "\n".join(lines) + "\n"


def render_text_workflow(workflow: Workflow) -> str:
    lines = [f"{workflow.title}", workflow.description, ""]
    for index, step in enumerate(workflow.steps, start=1):
        lines.append(f"{index}. {step.title} [{step.concept}]")
        lines.append(f"   {step.description}")
        lines.append(f"   {step.command_hint}")
    return "\n".join(lines) + "\n"


def render_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run built-in macOS privacy workflows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List built-in workflows")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON")

    show_parser = subparsers.add_parser("show", help="Show workflow details")
    show_parser.add_argument("workflow", choices=sorted(BUILTIN_WORKFLOWS), help="Workflow id")
    show_parser.add_argument("--json", action="store_true", help="Emit JSON")

    run_parser = subparsers.add_parser("run", help="Plan a workflow run")
    run_parser.add_argument("workflow", choices=sorted(BUILTIN_WORKFLOWS), help="Workflow id")
    run_parser.add_argument("--dry-run", action="store_true", default=True, help="Return planned steps only")
    run_parser.add_argument("--json", action="store_true", help="Emit JSON")
    run_parser.add_argument("--no-reason", action="store_true", help="Skip reasoning summary")

    return parser


def interactive_menu() -> None:
    """Interactive menu for workflow management."""
    while True:
        print("\n" + "=" * 60)
        print("       Workflow - Interrogation Workflows")
        print("=" * 60)
        print("  1. List workflows")
        print("  2. Show workflow details")
        print("  3. Run a workflow (dry-run)")
        print("  q. Back to main menu")
        print("=" * 60)

        choice = input("\nSelect action [1-3, q]: ").strip().lower()

        if choice in ("q", "quit"):
            break

        if choice == "1":
            rows = list_workflows()
            print(render_text_workflow_list(rows))
            input("\nPress Enter to continue...")
        elif choice == "2":
            wf_ids = sorted(BUILTIN_WORKFLOWS)
            print("\nAvailable workflows:")
            for i, wid in enumerate(wf_ids, 1):
                print(f"  {i}. {wid}")
            sel = input(f"\nSelect workflow [1-{len(wf_ids)}]: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(wf_ids):
                workflow = get_workflow(wf_ids[int(sel) - 1])
                print(render_text_workflow(workflow))
            input("\nPress Enter to continue...")
        elif choice == "3":
            wf_ids = sorted(BUILTIN_WORKFLOWS)
            print("\nAvailable workflows:")
            for i, wid in enumerate(wf_ids, 1):
                print(f"  {i}. {wid}")
            sel = input(f"\nSelect workflow [1-{len(wf_ids)}]: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(wf_ids):
                wid = wf_ids[int(sel) - 1]
                result = run_workflow(wid, dry_run=True, include_reasoning=True)
                print(render_text_workflow(get_workflow(wid)))
                print("Dry run: no commands were executed.")
            input("\nPress Enter to continue...")
        else:
            print("Invalid choice")


def main(argv: Optional[Sequence[str]] = None) -> int:
    if (argv is None and len(sys.argv) <= 1) or (argv is not None and len(argv) == 0):
        interactive_menu()
        return 0
    parser = _build_parser()
    setup_completion(parser)
    args = parser.parse_args(argv)

    if args.command == "list":
        rows = list_workflows()
        if args.json:
            print(render_json({"schema_version": WORKFLOW_SCHEMA_VERSION, "workflows": rows}), end="")
        else:
            print(render_text_workflow_list(rows), end="")
        return 0

    if args.command == "show":
        workflow = get_workflow(args.workflow)
        if args.json:
            print(render_json(workflow_to_dict(workflow)), end="")
        else:
            print(render_text_workflow(workflow), end="")
        return 0

    if args.command == "run":
        result = run_workflow(args.workflow, dry_run=args.dry_run, include_reasoning=not args.no_reason)
        if args.json:
            print(render_json(result), end="")
        else:
            print(render_text_workflow(get_workflow(args.workflow)), end="")
            print("Dry run: no commands were executed.")
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
