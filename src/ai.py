#!/usr/bin/env python3
"""AI integration module for msp CLI using local LLM providers.

Primary:    Ollama (local, on-device, privacy-first)
Fallback:   apfel (Apple Intelligence)
"""

import json
import os
import re
import select
import subprocess
import sys
import termios
import tty
from contextlib import contextmanager
from typing import Iterator, Optional, List, Dict, Any
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

from src.command import (
    interactive_menu as cmd_interactive_menu,
    interactive_select,
    setup_completion,
    suggest_command,
)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:1.5b"


@contextmanager
def _spinner(message: str) -> Iterator[None]:
    """Show a spinner while work is in progress. Falls back to simple text."""
    if RICH_AVAILABLE:
        with Progress(SpinnerColumn(), TextColumn(f"[progress.description]{message}..."), transient=True) as p:
            p.add_task("", total=None)
            yield
    else:
        sys.stdout.write(f"\r\u23f3 {message}...")
        sys.stdout.flush()
        try:
            yield
        finally:
            sys.stdout.write("\r" + " " * 40 + "\r")
            sys.stdout.flush()


def mask_sensitive(data: str) -> str:
    """Mask sensitive data before sending to LLM."""
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


def _ollama_available(base_url: str = DEFAULT_OLLAMA_BASE_URL) -> bool:
    req = Request(f"{base_url}/api/tags", method="GET")
    req.add_header("Accept", "application/json")
    try:
        with urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (URLError, OSError):
        return False


def _ollama_model_loaded(model: str, base_url: str = DEFAULT_OLLAMA_BASE_URL) -> bool:
    """Check if model is already pulled; skip if it would trigger a download/crash."""
    req = Request(f"{base_url}/api/tags", method="GET")
    req.add_header("Accept", "application/json")
    try:
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    models = data.get("models", [])
    return any(model in m.get("name", "") for m in models)


def _ollama_chat(
    messages: List[Dict[str, str]],
    model: str = DEFAULT_OLLAMA_MODEL,
    base_url: str = DEFAULT_OLLAMA_BASE_URL,
    timeout: int = 60,
    json_mode: bool = False,
) -> str:
    if not _ollama_model_loaded(model, base_url):
        raise RuntimeError(
            f"Ollama model '{model}' not found. Run: ollama pull {model}"
        )

    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "num_ctx": 2048,
        "options": {"temperature": 0.1},
        **({"format": "json"} if json_mode else {}),
    }).encode("utf-8")

    req = Request(f"{base_url}/api/chat", data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    with urlopen(req, timeout=timeout) as resp:
        response_data = json.loads(resp.read().decode("utf-8"))

    return response_data.get("message", {}).get("content", "")


def _apfel_available() -> bool:
    try:
        result = subprocess.run(
            ["which", "apfel"], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _apfel_chat(system_prompt: str, user_prompt: str, timeout: int = 60) -> str:
    result = subprocess.run(
        ["apfel", "-s", system_prompt, user_prompt],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "HOME": os.environ.get("HOME", "/Users/conscious")},
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "apfel failed")
    return result.stdout.strip()


class AIAnalyzer:
    """Privacy-first AI analysis using local LLM providers."""

    SYSTEM_PROMPT = """You are a macOS terminal diagnostics engineer. Live system data is below.

RULES — follow every rule:
1. Analyze the provided data — never give generic advice
2. Name SPECIFIC PIDs, process names, and memory/cpu numbers from the data
3. Every recommendation MUST include an exact terminal one-liner the user can copy-paste
4. NEVER suggest GUI tools (Activity Monitor, System Settings, etc.) — terminal only
5. At the end, ask the user if they want you to take action (e.g. kill a process, clear cache)
6. If nothing abnormal appears in the data, say so — do not invent problems

When suggesting a command, prefix it with "  $ " so it is easy to identify.

Example format:
  "PID 563 (Google Chrome Helper) is using 2.3GB RAM — that's 40% of your 8GB.
     $ ps -p 563 -o pid,rss,command
     $ kill -9 563
   Want me to run one of these?"""


_COMMAND_PREFIXES = (
    "kill", "pkill", "sudo", "ps ", "lsof", "top ", "htop", "nettop",
    "launchctl", "defaults", "spctl", "csrutil", "fdesetup", "diskutil",
    "dscacheutil", "mdutil", "pmset", "sysctl", "vm_stat", "df ", "du ",
    "ps aux", "ps -", "echo", "cat ", "less", "more", "head", "tail",
    "grep", "awk", "sed", "sort", "uniq", "wc ", "cut ", "tr ",
    "find ", "locate", "which", "whereis", "type ",
    "ping", "dig ", "nslookup", "curl", "wget",
    "brew", "pip", "npm", "npx", "yarn",
    "python", "python3", "ruby", "perl",
    "open ", "say ", "osascript",
    "tcpdump", "netstat", "ifconfig", "ip ",
    "chmod", "chown", "ln ", "cp ", "mv ", "rm ", "mkdir", "touch",
    "ditto", "tar ", "gzip", "gunzip", "unzip",
    "date", "cal ", "bc ", "expr",
    "xattr", "file ", "stat ", "sw_vers", "system_profiler",
    "mdfind", "screencapture",
)


def _extract_commands(text: str) -> List[str]:
    """Extract shell commands from AI response text."""
    seen: set[str] = set()
    commands: List[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        # Skip empty, comments, markdown fences
        if not stripped or stripped.startswith("#") or stripped.startswith("```"):
            continue

        # Remove common prompt prefixes
        if stripped.startswith("$ "):
            stripped = stripped[2:].strip()
        elif stripped.startswith("> "):
            stripped = stripped[2:].strip()
        elif stripped.startswith("% "):
            stripped = stripped[2:].strip()

        # Check if it looks like a shell command
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in _COMMAND_PREFIXES):
            # Normalize whitespace and deduplicate
            normalized = " ".join(stripped.split())
            if normalized not in seen and len(normalized) > 2:
                seen.add(normalized)
                commands.append(normalized)

    return commands


def _interactive_command_select(commands: List[str]) -> List[int]:
    """Arrow-key navigable, Tab-toggle multi-select for a list of commands.

    Returns indices of selected commands (empty list if cancelled).
    """
    if not commands:
        return []

    n = len(commands)
    cursor = 0
    selected: set[int] = set()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    # ANSI helpers
    UP = "\033[A"
    DOWN = "\033[B"
    HIDE = "\033[?25l"
    SHOW = "\033[?25h"
    CLEAR_LINE = "\033[2K"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"

    def render():
        lines = [f"\n {BOLD}Select commands to run:{RESET}  (↑↓ navigate, ⭾ toggle, ↵ execute, q quit)\n"]
        for i, cmd in enumerate(commands):
            prefix = "▸" if i == cursor else " "
            check = "☑" if i in selected else "☐"
            style = CYAN if i == cursor else RESET
            desc = cmd[:80] + ("..." if len(cmd) > 80 else "")
            lines.append(f" {prefix} {style}{check} {desc}{RESET}")
        lines.append("")
        return "\n".join(lines)

    def count_lines() -> int:
        return n + 3  # header + n items + blank line

    try:
        tty.setraw(fd)
        sys.stdout.write(HIDE)
        sys.stdout.flush()

        while True:
            # Render
            rendered = render()
            sys.stdout.write(rendered)
            sys.stdout.flush()

            # Read key
            raw = b""
            while True:
                b = os.read(fd, 1)
                raw += b
                if b == b"\x1b":
                    # Read next 2 bytes for escape sequences
                    raw += os.read(fd, 2)
                break

            key = raw.decode("utf-8", errors="replace")

            # Move cursor back up for re-render
            sys.stdout.write(f"\033[{count_lines()}A")
            for _ in range(count_lines()):
                sys.stdout.write(CLEAR_LINE)
                if _ < count_lines() - 1:
                    sys.stdout.write("\033[B")
            sys.stdout.write(f"\033[{count_lines()}A")

            if key == "\r" or key == "\n":
                break
            elif key == "q":
                selected.clear()
                break
            elif key == "\t" or key == " ":
                if cursor in selected:
                    selected.remove(cursor)
                else:
                    selected.add(cursor)
            elif key == "\x1b[A" and cursor > 0:
                cursor -= 1
            elif key == "\x1b[B" and cursor < n - 1:
                cursor += 1

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        # Clear the selection area
        sys.stdout.write(SHOW)
        for _ in range(count_lines()):
            sys.stdout.write(CLEAR_LINE)
            sys.stdout.write("\n")
        sys.stdout.write(f"\033[{count_lines()}A")
        sys.stdout.flush()

    return sorted(selected)

    def __init__(
        self,
        verbose: bool = False,
        llm_model: Optional[str] = None,
        llm_base_url: Optional[str] = None,
    ):
        self.verbose = verbose
        self.model = llm_model or os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        self.base_url = (llm_base_url or os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)).rstrip("/")

    def _format_for_llm(self, data: Any) -> str:
        if isinstance(data, str):
            return mask_sensitive(data)
        elif isinstance(data, dict):
            return mask_sensitive(json.dumps(data, indent=2))
        elif isinstance(data, list):
            return mask_sensitive("\n".join(str(item) for item in data))
        return str(data)

    def _chat(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        """Try providers in order: Ollama -> apfel -> error.

        Ollama uses qwen2.5-coder:1.5b by default — ~1GB RAM, runs on any Mac.
        Override via OLLAMA_MODEL env var or --model flag.
        On crash/timeout, falls back to apfel (Apple Intelligence).
        """
        try:
            if _ollama_available(self.base_url):
                if not _ollama_model_loaded(self.model, self.base_url):
                    raise RuntimeError(f"model '{self.model}' not pulled")

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
                with _spinner(f"Ollama ({self.model})"):
                    return _ollama_chat(messages, self.model, self.base_url, json_mode=json_mode)
        except Exception as e:
            if self.verbose:
                print(f"Ollama: {e}")
                print("Falling back to apfel...")

        try:
            if _apfel_available():
                with _spinner("apfel"):
                    return _apfel_chat(system_prompt, user_prompt)
        except Exception as e:
            if self.verbose:
                print(f"apfel also failed: {e}")

        raise RuntimeError(
            "No AI provider available.\n"
            f"  ollama: model={self.model}: run 'ollama pull {self.model}' then 'ollama serve'\n"
            "  apfel:  run 'brew install apfel'"
        )

    def ask(self, prompt: str, data: Optional[Any] = None, json_output: bool = False) -> Optional[str]:
        """Ask the AI a question, optionally with data context."""
        full_prompt = prompt
        if data:
            formatted_data = self._format_for_llm(data)
            full_prompt = f"{prompt}\n\nContext data:\n```\n{formatted_data}\n```"

        if self.verbose:
            print(f"Querying AI with: {prompt[:100]}...")

        try:
            output = self._chat(self.SYSTEM_PROMPT, full_prompt)
        except RuntimeError as e:
            print(f"Error: {e}")
            return None

        if output.strip():
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
                    print("\n" + "=" * 60)
                    print("AI Analysis:")
                    print("=" * 60)
                    print(output.strip())

            # Offer to execute commands from the response
            if not json_output and sys.stdin.isatty():
                commands = _extract_commands(output)
                if commands:
                    print()
                    items = [(c, c[:80] + ("..." if len(c) > 80 else ""), None) for c in commands]
                    selected = interactive_select(items, title="Select commands to run", multi=True)
                    if selected:
                        print("\n Executing command(s):")
                        for cmd in selected:
                            print(f"\n  $ {cmd}")
                            try:
                                r = subprocess.run(
                                    cmd, shell=True, capture_output=True, text=True, timeout=60
                                )
                                if r.stdout:
                                    for line in r.stdout.rstrip().splitlines():
                                        print(f"  {line}")
                                if r.stderr:
                                    for line in r.stderr.rstrip().splitlines():
                                        print(f"  \033[90m{line}\033[0m", file=sys.stderr)
                                if r.returncode != 0:
                                    print(f"  \033[90m[exit code: {r.returncode}]\033[0m")
                            except subprocess.TimeoutExpired:
                                print(f"  \033[90m[timed out after 60s]\033[0m")
                            except Exception as e:
                                print(f"  error: {e}")
                    else:
                        print("  (no commands selected)")

            return output.strip()
        else:
            print("Error: AI returned empty response")
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
        if modules is None:
            modules = ["net.established", "startup.list", "fswatch.recent"]

        print(f"Interactive watch mode (Ctrl+C to stop)")
        print(f"Running every {interval} seconds...\n")

        try:
            while True:
                print(f"\n{'=' * 60}")
                print(f"Scan at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print("=" * 60)

                results = []
                for module_cmd in modules:
                    print(f"\n[Running: {module_cmd}]")
                    success, output = self._run_cmd(
                        f"python3 ~/macos-privacy-cli/main.py {module_cmd.replace('.', ' ')} 2>/dev/null"
                    )
                    if success:
                        results.append({"module": module_cmd, "output": output.strip()})
                        print(f"\u2713 {module_cmd} completed")

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


def interactive_menu(analyzer: AIAnalyzer, json_output: bool = False):
    """Interactive menu for AI analyzer."""
    if json_output or not sys.stdin.isatty():
        return

    while True:
        action = cmd_interactive_menu([
            ("ask", "Ask AI a question", None),
            ("analyze", "Analyze current system data", None),
            ("watch", "Interactive monitoring mode", None),
            ("explain", "Explain a security setting", None),
            ("compare", "Compare two presets", None),
            ("suggest", "Security hardening suggestions", None),
        ], title="AI Analyzer - Interactive Mode")

        if action is None:
            print("Goodbye!")
            break

        if action == "ask":
            prompt = input("Your question: ").strip()
            if prompt:
                analyzer.ask(prompt, json_output=json_output)
            else:
                print("Prompt required")
        elif action == "analyze":
            analyzer.analyze_results({}, json_output=json_output)
        elif action == "watch":
            interval = input("Interval seconds [60]: ").strip()
            interval = int(interval) if interval.isdigit() else 60
            modules = input("Modules (comma-separated, optional): ").strip()
            modules_list = [m.strip() for m in modules.split(",")] if modules else None
            analyzer.interactive_watch(interval=interval, modules=modules_list)
        elif action == "explain":
            setting = input("Setting name: ").strip()
            if setting:
                analyzer.explain_setting(setting)
            else:
                print("Setting name required")
        elif action == "compare":
            p1 = input("Preset 1: ").strip()
            p2 = input("Preset 2: ").strip()
            if p1 and p2:
                analyzer.compare_presets(p1, p2)
            else:
                print("Both preset names required")
        elif action == "suggest":
            analyzer.suggest_hardening(json_output=json_output)

        input("\nPress Enter to continue...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp AI Analyzer")
    parser.add_argument("action", nargs="?", choices=["ask", "analyze", "watch", "explain", "compare", "suggest"],
                        help="Action to perform (omit for interactive mode)")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--data", help="File to attach as data context")
    parser.add_argument("--text", help="Prompt text (for ask)")
    parser.add_argument("--file", help="Data file to analyze")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--modules", nargs="+")
    parser.add_argument("--setting", help="Setting name to explain")
    parser.add_argument("--preset1", help="First preset to compare")
    parser.add_argument("--preset2", help="Second preset to compare")
    parser.add_argument("--model", help="Ollama model name (default: llama3.2)")
    parser.add_argument("--ollama-url", help="Ollama base URL (default: http://localhost:11434)")
    parser.add_argument("--sort", choices=[""], help="Sort not applicable for AI commands")
    setup_completion(parser)
    args = parser.parse_args()

    analyzer = AIAnalyzer(
        verbose=args.verbose,
        llm_model=args.model,
        llm_base_url=args.ollama_url,
    )

    if not args.action:
        interactive_menu(analyzer, args.json)
        return

    if args.action == "ask":
        prompt = args.text or input("Your question: ").strip()
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
        if not args.setting:
            print("Error: --setting required")
            sys.exit(1)
        analyzer.explain_setting(args.setting)

    elif args.action == "compare":
        if not args.preset1 or not args.preset2:
            print("Error: --preset1 and --preset2 required")
            sys.exit(1)
        analyzer.compare_presets(args.preset1, args.preset2)

    elif args.action == "suggest":
        analyzer.suggest_hardening(json_output=args.json)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
