#!/usr/bin/env python3
"""Method chaining module for msp CLI."""

import json
import os
import subprocess
import sys
import time
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from dataclasses import dataclass, asdict

try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


@dataclass
class ChainStep:
    module: str
    command: str
    args: List[str]


@dataclass
class Chain:
    name: str
    description: str
    steps: List[ChainStep]
    interval: Optional[int] = None


class ChainManager:
    """Manage and execute method chains."""

    DEFAULT_CHAINS = {
        "suspicious": Chain(
            name="suspicious",
            description="Detect suspicious activity",
            steps=[
                ChainStep("net", "established", []),
                ChainStep("startup", "audit", []),
                ChainStep("scan", "suspicious", []),
            ]
        ),
        "daily": Chain(
            name="daily",
            description="Daily security overview",
            steps=[
                ChainStep("net", "list", []),
                ChainStep("net", "established", []),
                ChainStep("startup", "list", []),
                ChainStep("traffic", "summary", []),
            ]
        ),
        "audit": Chain(
            name="audit",
            description="Comprehensive security audit",
            steps=[
                ChainStep("scan", "deep", []),
                ChainStep("startup", "audit", []),
                ChainStep("fswatch", "audit", []),
                ChainStep("ai", "suggest", []),
            ]
        ),
    }

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.config_dir = os.path.expanduser("~/.msp")
        self.chains_file = os.path.join(self.config_dir, "chains.json")
        self.chains = self._load_chains()
        self._init_config_dir()

    def _init_config_dir(self) -> None:
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(os.path.join(self.config_dir, "baselines"), exist_ok=True)
        os.makedirs(os.path.join(self.config_dir, "reports"), exist_ok=True)

    def _load_chains(self) -> Dict[str, Chain]:
        chains = dict(self.DEFAULT_CHAINS)

        if os.path.exists(self.chains_file):
            try:
                with open(self.chains_file, 'r') as f:
                    data = json.load(f)
                    for name, chain_data in data.items():
                        steps = [ChainStep(**s) for s in chain_data.get("steps", [])]
                        chains[name] = Chain(
                            name=name,
                            description=chain_data.get("description", ""),
                            steps=steps,
                            interval=chain_data.get("interval")
                        )
            except (json.JSONDecodeError, TypeError) as e:
                if self.verbose:
                    print(f"Error loading chains: {e}")

        return chains

    def _save_chains(self) -> None:
        with open(self.chains_file, 'w') as f:
            data = {}
            for name, chain in self.chains.items():
                if name not in self.DEFAULT_CHAINS:
                    data[name] = {
                        "description": chain.description,
                        "steps": [asdict(s) for s in chain.steps],
                        "interval": chain.interval
                    }
            json.dump(data, f, indent=2)

    def _run_cmd(self, cmd: List[str], timeout: int = 60) -> tuple[bool, str]:
        try:
            msp_path = os.path.expanduser("~/macos-privacy-cli/main.py")
            full_cmd = ["python3", msp_path] + cmd

            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def list_chains(self, json_output: bool = False) -> List[Chain]:
        """List all available chains."""
        chains = list(self.chains.values())

        if json_output:
            output = {
                name: {
                    "description": c.description,
                    "steps": [f"{s.module} {s.command}" for s in c.steps],
                    "interval": c.interval,
                    "default": name in self.DEFAULT_CHAINS
                }
                for name, c in self.chains.items()
            }
            print(json.dumps(output, indent=2))
            return chains

        if RICH_AVAILABLE and console:
            table = Table(title="Available Chains")
            table.add_column("Name", style="cyan")
            table.add_column("Description", style="green")
            table.add_column("Steps", style="yellow")
            table.add_column("Type", style="magenta")

            for name, chain in self.chains.items():
                step_str = " → ".join(f"{s.module} {s.command}" for s in chain.steps)
                chain_type = "Built-in" if name in self.DEFAULT_CHAINS else "Custom"
                table.add_row(name, chain.description or "-", step_str[:50], chain_type)
            console.print(table)
        else:
            print("Available chains:")
            for name, chain in self.chains.items():
                print(f"\n[{name}] {chain.description}")
                for s in chain.steps:
                    print(f"  → {s.module} {s.command}")

        return chains

    def define_chain(self, name: str, steps_str: str, description: str = "",
                    interval: Optional[int] = None, silent: bool = False) -> bool:
        """Define a new chain from a string like 'net list | startup list | scan quick'."""
        steps = []
        parts = [p.strip() for p in steps_str.split('|')]

        for part in parts:
            tokens = part.split()
            if len(tokens) >= 2:
                module = tokens[0]
                command = tokens[1]
                args = tokens[2:] if len(tokens) > 2 else []
                steps.append(ChainStep(module=module, command=command, args=args))
            elif len(tokens) == 1:
                steps.append(ChainStep(module=tokens[0], command="", args=[]))

        if steps:
            self.chains[name] = Chain(
                name=name,
                description=description,
                steps=steps,
                interval=interval
            )
            self._save_chains()
            if not silent:
                print(f"Chain '{name}' defined with {len(steps)} steps")
            return True

        if not silent:
            print("Error: invalid chain definition")
        return False

    def delete_chain(self, name: str) -> bool:
        """Delete a custom chain."""
        if name in self.DEFAULT_CHAINS:
            print(f"Cannot delete built-in chain: {name}")
            return False

        if name in self.chains:
            del self.chains[name]
            self._save_chains()
            print(f"Deleted chain: {name}")
            return True

        print(f"Chain not found: {name}")
        return False

    def run_chain(self, name: str, prompt: Optional[str] = None,
                  json_output: bool = False) -> List[Dict[str, Any]]:
        """Execute a chain and optionally analyze results with AI."""
        if name not in self.chains:
            print(f"Chain not found: {name}")
            return []

        chain = self.chains[name]
        results = []

        if RICH_AVAILABLE and console:
            console.print(f"\n[cyan]Running chain:[/cyan] {name}")
            console.print(f"[dim]{chain.description or 'No description'}[/dim]\n")

        for i, step in enumerate(chain.steps):
            step_cmd = [step.module, step.command] + step.args
            step_str = " ".join(step_cmd)

            if RICH_AVAILABLE and console:
                console.print(f"[yellow]Step {i+1}/{len(chain.steps)}:[/yellow] {step_str}")

            success, output = self._run_cmd(step_cmd)

            result = {
                "step": i + 1,
                "command": step_str,
                "success": success,
                "output": output[:2000] if output else ""
            }
            results.append(result)

            if self.verbose or not RICH_AVAILABLE:
                print(f"\n--- {step_str} ---")
                print(output[:500] if output else "No output")
                print()

        if prompt or json_output:
            from src.ai import AIAnalyzer
            ai = AIAnalyzer(verbose=self.verbose)

            if prompt:
                combined = "\n\n".join(
                    f"=== Step {r['step']}: {r['command']} ===\n{r['output']}"
                    for r in results
                )
                ai.ask(f"{prompt}\n\nAnalyze the results and suggest any actions:", data=combined)
            else:
                print(json.dumps(results, indent=2))

        return results

    def watch_chain(self, name: str, interval: int = 60,
                    prompt: Optional[str] = None, max_iterations: Optional[int] = None) -> None:
        """Run a chain repeatedly, alerting on changes."""
        if name not in self.chains:
            print(f"Chain not found: {name}")
            return

        chain = self.chains[name]
        baseline = None
        iteration = 0

        print(f"Watching chain '{name}' every {interval}s (Ctrl+C to stop)\n")

        try:
            while True:
                iteration += 1
                print(f"\n{'='*60}")
                print(f"Iteration {iteration} at {time.strftime('%H:%M:%S')}")
                print("="*60)

                results = self.run_chain(name, prompt=prompt)

                current = [r["output"] for r in results]

                if baseline is None:
                    baseline = current
                    print("\nBaseline established.")
                else:
                    changes = []
                    for i, (prev, curr) in enumerate(zip(baseline, current)):
                        if prev != curr and curr.strip():
                            changes.append((i, prev, curr))
                            print(f"\n⚠️ Change detected in step {i+1}")

                    if changes:
                        print(f"\nFound {len(changes)} changes since baseline.")

                        if prompt:
                            from src.ai import AIAnalyzer
                            ai = AIAnalyzer()
                            ai.ask(
                                "System state has changed. Analyze these changes and "
                                "flag any security concerns:",
                                data="\n\n".join(
                                    f"Step {c[0]+1}:\nPrevious:\n{c[1][:500]}\n\nCurrent:\n{c[2][:500]}"
                                    for c in changes
                                )
                            )

                        confirm = input("\nUpdate baseline? [Y/n] ").strip().lower()
                        if not confirm or confirm == 'y':
                            baseline = current
                            print("Baseline updated.")
                    else:
                        print("\n✓ No changes detected.")

                if max_iterations and iteration >= max_iterations:
                    print(f"\nCompleted {max_iterations} iterations.")
                    break

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\nStopped.")

    def export_chain(self, name: str, file_path: str) -> bool:
        """Export a chain to a file."""
        if name not in self.chains:
            print(f"Chain not found: {name}")
            return False

        chain = self.chains[name]
        data = {
            "name": chain.name,
            "description": chain.description,
            "steps": [asdict(s) for s in chain.steps],
            "interval": chain.interval
        }

        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"Exported '{name}' to {file_path}")
        return True

    def import_chain(self, file_path: str) -> bool:
        """Import a chain from a file."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            name = data.get("name", os.path.basename(file_path).replace(".json", ""))
            steps = [ChainStep(**s) for s in data.get("steps", [])]

            chain = Chain(
                name=name,
                description=data.get("description", ""),
                steps=steps,
                interval=data.get("interval")
            )

            self.chains[name] = chain
            self._save_chains()

            print(f"Imported chain '{name}' with {len(steps)} steps")
            return True

        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error importing chain: {e}")
            return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Chain Manager")
    parser.add_argument("action", choices=["list", "run", "define", "delete", "watch", "export", "import"])
    parser.add_argument("name", nargs="?", help="Chain name")
    parser.add_argument("--steps", help="Steps definition (for define)")
    parser.add_argument("--description", help="Chain description")
    parser.add_argument("--interval", type=int, help="Watch interval in seconds")
    parser.add_argument("--max", type=int, help="Max iterations for watch")
    parser.add_argument("--prompt", help="Prompt for AI analysis")
    parser.add_argument("--file", help="File for export/import")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    manager = ChainManager(verbose=args.verbose)

    if args.action == "list":
        manager.list_chains(json_output=args.json)

    elif args.action == "run":
        if not args.name:
            print("Error: chain name required")
            sys.exit(1)
        manager.run_chain(args.name, prompt=args.prompt, json_output=args.json)

    elif args.action == "define":
        if not args.name or not args.steps:
            print("Error: name and --steps required")
            sys.exit(1)
        manager.define_chain(args.name, args.steps, args.description or "", args.interval)

    elif args.action == "delete":
        if not args.name:
            print("Error: chain name required")
            sys.exit(1)
        manager.delete_chain(args.name)

    elif args.action == "watch":
        if not args.name:
            print("Error: chain name required")
            sys.exit(1)
        manager.watch_chain(args.name, interval=args.interval or 60,
                          prompt=args.prompt, max_iterations=args.max)

    elif args.action == "export":
        if not args.name or not args.file:
            print("Error: name and --file required")
            sys.exit(1)
        manager.export_chain(args.name, args.file)

    elif args.action == "import":
        if not args.file:
            print("Error: --file required")
            sys.exit(1)
        manager.import_chain(args.file)


if __name__ == "__main__":
    main()