#!/usr/bin/env python3
"""AI integration module for msp CLI using apfel (Apple Intelligence)."""

import json
import os
import subprocess
import sys
from typing import Optional, List, Dict, Any
from pathlib import Path

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def mask_sensitive(data: str) -> str:
    """Mask sensitive data before sending to LLM."""
    import re
    patterns = [
        (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '***.***.***.*'),
        (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '***@***.***'),
        (r'Bearer [^\s]+', 'Bearer ***'),
        (r'password[=:][^\s,]+', 'password=***'),
        (r'token[=:][^\s,]+', 'token=***'),
    ]
    for pattern, replacement in patterns:
        data = re.sub(pattern, replacement, data)
    return data


class AIAnalyzer:
    """Integrate with apfel for AI-powered analysis."""

    SYSTEM_PROMPT = """You are a macOS security expert analyzing system data.
Focus on identifying:
1. Suspicious processes or network connections
2. Potential privacy leaks or telemetry
3. Unusual startup items or persistence mechanisms
4. Security misconfigurations

Provide concise, actionable recommendations.
Format findings as: [SEVERITY] Issue: Description → Recommendation

Mark severity as HIGH, MEDIUM, or LOW."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.apfel_path = self._find_apfel()

    def _find_apfel(self) -> Optional[str]:
        success, output = self._run_cmd("which apfel")
        if success:
            return "apfel"
        return None

    def _run_cmd(self, cmd: str, timeout: int = 60) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "HOME": os.environ.get("HOME", "/Users/conscious")}
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _format_for_llm(self, data: Any) -> str:
        if isinstance(data, str):
            return mask_sensitive(data)
        elif isinstance(data, dict):
            return mask_sensitive(json.dumps(data, indent=2))
        elif isinstance(data, list):
            return mask_sensitive("\n".join(str(item) for item in data))
        return str(data)

    def ask(self, prompt: str, data: Optional[Any] = None, json_output: bool = False) -> Optional[str]:
        """Ask apfel a question, optionally with data context."""
        if not self.apfel_path:
            print("Error: apfel not installed. Run: brew install apfel")
            return None

        full_prompt = prompt
        if data:
            formatted_data = self._format_for_llm(data)
            full_prompt = f"{prompt}\n\nContext data:\n```\n{formatted_data}\n```"

        if self.verbose:
            print(f"Querying apfel with: {prompt[:100]}...")

        success, output = self._run_cmd(
            f'{self.apfel_path} -s "{self.SYSTEM_PROMPT}" "{full_prompt}"'
        )

        if success and output.strip():
            if json_output:
                print(json.dumps({"response": output.strip()}, indent=2))
            else:
                if RICH_AVAILABLE and console:
                    console.print(Panel(
                        output.strip(),
                        title="AI Analysis",
                        border_style="green"
                    ))
                else:
                    print("\n" + "="*60)
                    print("AI Analysis:")
                    print("="*60)
                    print(output.strip())
            return output.strip()
        else:
            print(f"Error querying apfel: {output}")
            return None

    def analyze_results(self, data: Any, json_output: bool = False) -> Optional[str]:
        """Analyze scan/network/startup results with AI."""
        return self.ask(
            "Analyze this system data and flag any suspicious or concerning items:",
            data=data,
            json_output=json_output
        )

    def interactive_watch(self, interval: int = 60, modules: Optional[List[str]] = None) -> None:
        """Interactive watch mode: collect data, analyze, prompt user."""
        if not self.apfel_path:
            print("Error: apfel not required for interactive mode")
            return

        if modules is None:
            modules = ["net.established", "startup.list", "fswatch.recent"]

        print(f"Interactive watch mode (Ctrl+C to stop)")
        print(f"Running every {interval} seconds...\n")

        try:
            while True:
                print(f"\n{'='*60}")
                print(f"Scan at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("="*60)

                results = []
                for module_cmd in modules:
                    print(f"\n[Running: {module_cmd}]")
                    success, output = self._run_cmd(f"python3 ~/macos-privacy-cli/main.py {module_cmd.replace('.', ' ')} 2>/dev/null")
                    if success:
                        results.append({"module": module_cmd, "output": output.strip()})
                        print(f"✓ {module_cmd} completed")

                if results:
                    combined = "\n".join(
                        f"=== {r['module']} ===\n{r['output']}"
                        for r in results
                    )
                    self.ask(
                        "Review this system data and identify any security concerns. "
                        "For each issue, suggest: block, investigate, or ignore.",
                        data=combined
                    )

                    action = input("\nAction? [c]ontinue, [q]uit: ").strip().lower()
                    if action == 'q':
                        break

                import time
                time.sleep(interval)

        except KeyboardInterrupt:
            print("\nStopped.")

    def explain_setting(self, setting_name: str) -> Optional[str]:
        """Explain a security setting and its implications."""
        prompt = f"""Explain the macOS security setting '{setting_name}':
1. What does it do?
2. What are the security implications of having it on/off?
3. Who should enable/disable it based on their threat model?

Keep the response practical and concise."""
        return self.ask(prompt)

    def compare_presets(self, preset1: str, preset2: str) -> Optional[str]:
        """Compare two security presets."""
        prompt = f"""Compare these two macOS security presets:
Preset 1: {preset1}
Preset 2: {preset2}

For each, explain:
- What security features are enabled/disabled
- Which users/organizations should use each
- Trade-offs between security and usability

Be concise and practical."""
        return self.ask(prompt)

    def suggest_hardening(self, json_output: bool = False) -> Optional[str]:
        """Suggest hardening steps based on current system state."""
        prompt = "Based on this system's current security configuration, suggest specific hardening steps:"
        data = self._get_current_state()
        return self.ask(prompt, data=data, json_output=json_output)

    def _get_current_state(self) -> Dict[str, Any]:
        """Get current security state of the system."""
        state = {}

        commands = [
            ("firewall", "/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate"),
            ("stealth_mode", "/usr/libexec/ApplicationFirewall/socketfilterfw --getstealthmode"),
            ("filevault", "fdesetup status"),
            ("gatekeeper", "spctl --status"),
            ("sip", "csrutil status"),
        ]

        for name, cmd in commands:
            success, output = self._run_cmd(f"sudo {cmd}" if "sudo" in cmd else cmd)
            if success:
                state[name] = output.strip()

        return state


from datetime import datetime


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp AI Analyzer")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--data", help="File to attach as data context")

    subparsers = parser.add_subparsers(dest="action", help="Commands")

    ask_parser = subparsers.add_parser("ask", help="Ask AI a question")
    ask_parser.add_argument("prompt", nargs="*", help="Question or prompt")
    ask_parser.add_argument("--text", help="Prompt text (alternative)")

    analyze_parser = subparsers.add_parser("analyze", help="Analyze data")
    analyze_parser.add_argument("file", nargs="?", help="Data file to analyze")

    watch_parser = subparsers.add_parser("watch", help="Interactive monitoring")
    watch_parser.add_argument("--interval", type=int, default=60)
    watch_parser.add_argument("--modules", nargs="+")

    explain_parser = subparsers.add_parser("explain", help="Explain a setting")
    explain_parser.add_argument("setting", help="Setting name to explain")

    compare_parser = subparsers.add_parser("compare", help="Compare presets")
    compare_parser.add_argument("preset1")
    compare_parser.add_argument("preset2")

    suggest_parser = subparsers.add_parser("suggest", help="Security suggestions")

    args = parser.parse_args()

    analyzer = AIAnalyzer(verbose=args.verbose)

    if args.action == "ask":
        prompt = " ".join(args.prompt) if args.prompt else args.text
        if not prompt:
            print("Error: prompt required")
            sys.exit(1)
        data = None
        if args.data:
            with open(args.data) as f:
                data = f.read()
        analyzer.ask(prompt, data=data, json_output=args.json)

    elif args.action == "analyze":
        data = None
        if args.file:
            with open(args.file) as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = f.read()
        else:
            from src.network import NetworkMonitor
            from src.startup import StartupManager
            data = {}
            data["network"] = NetworkMonitor().list_established()
            data["startup"] = StartupManager().list_all()
        analyzer.analyze_results(data, json_output=args.json)

    elif args.action == "watch":
        analyzer.interactive_watch(interval=args.interval, modules=args.modules)

    elif args.action == "explain":
        analyzer.explain_setting(args.setting)

    elif args.action == "compare":
        analyzer.compare_presets(args.preset1, args.preset2)

    elif args.action == "suggest":
        analyzer.suggest_hardening(json_output=args.json)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()