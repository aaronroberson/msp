#!/usr/bin/env python3
"""AI integration module for msp CLI.

Unified Bring-Your-Own-Key (BYOK) and local AI inference engine:
  - OpenAI, Groq, DeepSeek, OpenRouter, Together, Custom OpenAI-compatible endpoints
  - Ollama (Local REST)
  - Apple Intelligence (apfel CLI)
  - OpenVINO (Intel CPU/GPU/USB NPU)
"""

from __future__ import annotations

import argparse
import datetime
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# OpenVINO imports (optional)
try:
    from openvino.runtime import Core
    OPENVINO_AVAILABLE = True
except ImportError:
    OPENVINO_AVAILABLE = False

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

# Configuration paths
CONFIG_DIR = Path.home() / ".msp"
AI_CONFIG_FILE = CONFIG_DIR / "ai_config.json"
KEYCHAIN_SERVICE_PREFIX = "msp-"

# Default provider definitions
DEFAULT_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "suggested_models": ["gpt-4o-mini", "gpt-4o", "o3-mini", "gpt-4-turbo"],
        "env_key": "OPENAI_API_KEY",
        "type": "openai_compatible",
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "suggested_models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "env_key": "GROQ_API_KEY",
        "type": "openai_compatible",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "suggested_models": ["deepseek-chat", "deepseek-reasoner"],
        "env_key": "DEEPSEEK_API_KEY",
        "type": "openai_compatible",
    },
    "openrouter": {
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-3.5-sonnet",
        "suggested_models": [
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o-mini",
            "google/gemini-2.0-flash-001",
            "meta-llama/llama-3.3-70b-instruct",
            "deepseek/deepseek-r1",
        ],
        "env_key": "OPENROUTER_API_KEY",
        "type": "openai_compatible",
    },
    "together": {
        "name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "suggested_models": [
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
        ],
        "env_key": "TOGETHER_API_KEY",
        "type": "openai_compatible",
    },
    "ollama": {
        "name": "Ollama (Local)",
        "base_url": "http://localhost:11434",
        "default_model": "qwen2.5-coder:1.5b",
        "suggested_models": ["qwen2.5-coder:1.5b", "llama3.2:3b", "mistral", "qwen2.5:7b"],
        "env_key": "",
        "type": "ollama",
    },
    "apfel": {
        "name": "Apple Intelligence (apfel)",
        "base_url": "",
        "default_model": "apple-intelligence",
        "suggested_models": ["apple-intelligence"],
        "env_key": "",
        "type": "apfel",
    },
    "openvino": {
        "name": "OpenVINO (Intel Hardware)",
        "base_url": "",
        "default_model": "qwen2.5-coder-1.5b-openvino",
        "suggested_models": ["qwen2.5-coder-1.5b-openvino"],
        "env_key": "",
        "type": "openvino",
    },
    "custom": {
        "name": "Custom OpenAI-Compatible Endpoint",
        "base_url": "http://localhost:8000/v1",
        "default_model": "default",
        "suggested_models": [],
        "env_key": "CUSTOM_API_KEY",
        "type": "openai_compatible",
    },
}


# ---------------------------------------------------------------------------
# Keychain & Config Helpers
# ---------------------------------------------------------------------------

def load_ai_config() -> Dict[str, Any]:
    """Load persistent AI configuration from ~/.msp/ai_config.json."""
    if AI_CONFIG_FILE.exists():
        try:
            with open(AI_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "default_provider": "",
        "providers": {},
    }


def save_ai_config(config: Dict[str, Any]) -> bool:
    """Save persistent AI configuration to ~/.msp/ai_config.json."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(AI_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False


def get_keychain_key(provider_name: str) -> Optional[str]:
    """Retrieve API key for provider from macOS Keychain."""
    try:
        service = f"{KEYCHAIN_SERVICE_PREFIX}{provider_name}"
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def save_keychain_key(provider_name: str, key: str) -> bool:
    """Save API key for provider to macOS Keychain."""
    try:
        user = os.environ.get("USER", "")
        service = f"{KEYCHAIN_SERVICE_PREFIX}{provider_name}"
        r = subprocess.run(
            ["security", "add-generic-password", "-s", service,
             "-a", user, "-w", key, "-U"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def delete_keychain_key(provider_name: str) -> bool:
    """Delete API key for provider from macOS Keychain."""
    try:
        service = f"{KEYCHAIN_SERVICE_PREFIX}{provider_name}"
        r = subprocess.run(
            ["security", "delete-generic-password", "-s", service],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def get_resolved_api_key(provider_name: str) -> Optional[str]:
    """Resolve API key: check environment first, then macOS Keychain, then config."""
    defn = DEFAULT_PROVIDERS.get(provider_name, {})
    env_var = defn.get("env_key")
    if env_var and os.environ.get(env_var):
        return os.environ[env_var].strip()

    # Generic env fallback
    generic_env = f"{provider_name.upper()}_API_KEY"
    if os.environ.get(generic_env):
        return os.environ[generic_env].strip()

    # Keychain check
    key = get_keychain_key(provider_name)
    if key:
        return key

    # Config file check
    cfg = load_ai_config()
    return cfg.get("providers", {}).get(provider_name, {}).get("api_key")


# ---------------------------------------------------------------------------
# UI & Sensitive Data Helpers
# ---------------------------------------------------------------------------

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


def _extract_commands(text: str) -> List[str]:
    """Extract terminal commands suggested in AI response."""
    commands: List[str] = []
    seen: set = set()

    def add(cmd: str):
        c = cmd.strip().rstrip("`").strip()
        if c and c not in seen:
            seen.add(c)
            commands.append(c)

    # 1. Code blocks ```bash ... ``` or ``` ... ```
    code_blocks = re.findall(r"```(?:bash|sh|zsh)?\n?(.*?)```", text, re.DOTALL)
    for block in code_blocks:
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("$ "):
                add(line[2:])
            else:
                add(line)

    # 2. Line-by-line checks
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("$ "):
            add(line[2:])
        elif line.startswith("`$ ") and line.endswith("`"):
            add(line[3:-1])
        elif line.startswith("sudo ") or line.startswith("kill ") or line.startswith("launchctl ") or line.startswith("lsof "):
            add(line)

    return commands


# ---------------------------------------------------------------------------
# Inference Drivers (Zero External Dependencies)
# ---------------------------------------------------------------------------

def _http_chat_completion(
    provider_name: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    timeout: int = 60,
    json_mode: bool = False,
) -> str:
    """Standard OpenAI-compatible REST chat completion using built-in urllib."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    # Specific headers for OpenRouter
    if "openrouter" in provider_name.lower():
        req.add_header("HTTP-Referer", "https://github.com/aaronroberson/macos-privacy-cli")
        req.add_header("X-Title", "macos-privacy-cli")

    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("API returned empty choices list")
            return choices[0].get("message", {}).get("content", "")
    except HTTPError as e:
        error_detail = ""
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            error_detail = err_body.get("error", {}).get("message") or str(err_body)
        except Exception:
            error_detail = str(e)
        raise RuntimeError(f"[{provider_name} HTTP {e.code}] {error_detail}") from e
    except URLError as e:
        raise RuntimeError(f"[{provider_name} Connection Error] {e.reason}") from e


def _ollama_available(base_url: str = "http://localhost:11434") -> bool:
    req = Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
    req.add_header("Accept", "application/json")
    try:
        with urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_model_loaded(model: str, base_url: str = "http://localhost:11434") -> bool:
    req = Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
    req.add_header("Accept", "application/json")
    try:
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            return any(model in m.get("name", "") for m in models)
    except Exception:
        return False


def _ollama_chat(
    messages: List[Dict[str, str]],
    model: str = "qwen2.5-coder:1.5b",
    base_url: str = "http://localhost:11434",
    timeout: int = 60,
    json_mode: bool = False,
) -> str:
    if not _ollama_model_loaded(model, base_url):
        raise RuntimeError(f"Ollama model '{model}' not found. Run: ollama pull {model}")

    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "num_ctx": 2048,
        "options": {"temperature": 0.1},
        **({"format": "json"} if json_mode else {}),
    }).encode("utf-8")

    req = Request(f"{base_url.rstrip('/')}/api/chat", data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    with urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("message", {}).get("content", "")


def _apfel_available() -> bool:
    return shutil.which("apfel") is not None


def _apfel_chat(system_prompt: str, user_prompt: str, timeout: int = 60) -> str:
    result = subprocess.run(
        ["apfel", "-s", system_prompt, user_prompt],
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "HOME": os.environ.get("HOME", "/Users/conscious")},
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "apfel failed")
    return result.stdout.strip()


def _openvino_available() -> bool:
    if not OPENVINO_AVAILABLE:
        return False
    try:
        core = Core()
        return len(core.available_devices) > 0
    except Exception:
        return False


def _openvino_list_devices() -> List[str]:
    if not OPENVINO_AVAILABLE:
        return []
    try:
        core = Core()
        return core.available_devices
    except Exception:
        return []


def _openvino_chat(
    messages: List[Dict[str, str]],
    model: str = "qwen2.5-coder-1.5b-openvino",
    timeout: int = 60,
    device: str = "AUTO",
) -> str:
    if not OPENVINO_AVAILABLE:
        raise RuntimeError("OpenVINO not installed. Install with: pip install openvino")
    core = Core()
    available = core.available_devices
    raise NotImplementedError(
        f"OpenVINO requires pre-converted IR models (.xml/.bin). Available devices: {available}"
    )


# ---------------------------------------------------------------------------
# Interactive Provider Configuration (BYOK Experience)
# ---------------------------------------------------------------------------

def configure_provider_flow() -> Optional[str]:
    """Interactive guided setup to choose an AI provider and securely store keys."""
    print("\n" + "=" * 60)
    print("  Configure AI Inference Provider (BYOK)")
    print("=" * 60)
    print("Choose an inference provider to power msp AI diagnostics:\n")

    menu_items = [
        {"name": "1. OpenAI              (Official API - gpt-4o-mini, gpt-4o, o3-mini)", "value": "openai"},
        {"name": "2. Groq                (Ultra-fast cloud inference - Llama 3.3 70B)", "value": "groq"},
        {"name": "3. DeepSeek            (DeepSeek-V3 / DeepSeek-R1 reasoning)", "value": "deepseek"},
        {"name": "4. OpenRouter          (Multi-model router - Claude 3.5, Gemini, Llama)", "value": "openrouter"},
        {"name": "5. Together AI         (Open-source cloud models - Llama 3.3, Mixtral)", "value": "together"},
        {"name": "6. Ollama              (Local on-device inference - private & offline)", "value": "ollama"},
        {"name": "7. Apple Intelligence  (apfel CLI local on-device)", "value": "apfel"},
        {"name": "8. Custom Endpoint     (Self-hosted / vLLM / LocalAI / OpenAI-compatible)", "value": "custom"},
    ]

    selected_provider = None
    if cmd_interactive_menu:
        selected_provider = cmd_interactive_menu(menu_items, title="Select AI Provider:")
    else:
        for item in menu_items:
            print(f"  {item['name']}")
        choice = input("\nEnter choice [1-8]: ").strip()
        mapping = {"1": "openai", "2": "groq", "3": "deepseek", "4": "openrouter", "5": "together", "6": "ollama", "7": "apfel", "8": "custom"}
        selected_provider = mapping.get(choice)

    if not selected_provider:
        print("Setup cancelled.")
        return None

    cfg = load_ai_config()
    defn = DEFAULT_PROVIDERS.get(selected_provider, {})
    provider_type = defn.get("type", "openai_compatible")

    # Handle Custom Provider endpoint info
    base_url = defn.get("base_url", "")
    if selected_provider == "custom":
        custom_url = input(f"Enter Base URL [{base_url}]: ").strip()
        if custom_url:
            base_url = custom_url

    # Key entry for cloud / BYOK providers
    api_key = ""
    if provider_type == "openai_compatible":
        existing_key = get_resolved_api_key(selected_provider)
        if existing_key:
            masked = existing_key[:8] + "..." + existing_key[-4:] if len(existing_key) > 12 else "***"
            print(f"\n[+] Existing key detected ({masked})")
            keep = input("Keep existing key? [Y/n]: ").strip().lower() != "n"
            if keep:
                api_key = existing_key

        if not api_key:
            env_hint = defn.get("env_key") or f"{selected_provider.upper()}_API_KEY"
            print(f"\nEnter API key for {defn['name']} (input is hidden):")
            try:
                entered = getpass.getpass("API Key: ").strip()
                if entered:
                    api_key = entered
                    # Offer keychain saving
                    save_kc = input("Save key to macOS Keychain for persistent secure access? [Y/n]: ").strip().lower() != "n"
                    if save_kc:
                        if save_keychain_key(selected_provider, api_key):
                            print(f"[✓] Saved {selected_provider} API key to macOS Keychain (service 'msp-{selected_provider}').")
                        else:
                            print("[!] Could not write to Keychain; saving key for session.")
            except (EOFError, KeyboardInterrupt):
                print("\nKey entry cancelled.")
                return None

    # Model selection
    default_model = defn.get("default_model", "")
    suggested = defn.get("suggested_models", [])
    selected_model = default_model

    if suggested:
        print(f"\nDefault model: {default_model}")
        print(f"Suggested models: {', '.join(suggested)}")
        chosen_m = input(f"Enter model name [{default_model}]: ").strip()
        if chosen_m:
            selected_model = chosen_m
    elif selected_provider == "custom":
        chosen_m = input(f"Enter model name [{default_model}]: ").strip()
        if chosen_m:
            selected_model = chosen_m

    # Persist config
    if "providers" not in cfg:
        cfg["providers"] = {}
    cfg["default_provider"] = selected_provider
    cfg["providers"][selected_provider] = {
        "base_url": base_url,
        "model": selected_model,
        "type": provider_type,
    }
    save_ai_config(cfg)

    print(f"\n[✓] Successfully configured AI provider: {defn['name']} (Model: {selected_model})")
    return selected_provider


# ---------------------------------------------------------------------------
# AIAnalyzer Class
# ---------------------------------------------------------------------------

class AIAnalyzer:
    """Unified AI diagnostics engine with BYOK provider routing and intelligent fallback."""

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

    def __init__(
        self,
        verbose: bool = False,
        provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        openvino_device: Optional[str] = None,
    ):
        self.verbose = verbose
        self.cli_provider = provider
        self.cli_model = llm_model
        self.cli_base_url = llm_base_url
        self.openvino_device = openvino_device or os.environ.get("OPENVINO_DEVICE", "AUTO")

    def _format_for_llm(self, data: Any) -> str:
        if isinstance(data, str):
            return mask_sensitive(data)
        elif isinstance(data, dict):
            return mask_sensitive(json.dumps(data, indent=2))
        elif isinstance(data, list):
            return mask_sensitive("\n".join(str(item) for item in data))
        return str(data)

    def _resolve_active_provider(self) -> Tuple[str, str, str, str]:
        """Resolve (provider_name, base_url, model, api_key)."""
        cfg = load_ai_config()

        # 1. CLI or ENV override
        target_name = (
            self.cli_provider
            or os.environ.get("MSP_LLM_PROVIDER")
            or cfg.get("default_provider")
        )

        # 2. If nothing configured, check if an existing keychain key or local tool exists
        if not target_name:
            for p in ["openai", "groq", "deepseek", "openrouter", "together"]:
                if get_resolved_api_key(p):
                    target_name = p
                    break

        if not target_name:
            if _ollama_available():
                target_name = "ollama"
            elif _apfel_available():
                target_name = "apfel"

        # 3. If still nothing configured and running interactively, launch setup flow
        if not target_name:
            if sys.stdin.isatty():
                selected = configure_provider_flow()
                if selected:
                    target_name = selected
                    cfg = load_ai_config()
            if not target_name:
                target_name = "apfel" if _apfel_available() else "openai"

        defn = DEFAULT_PROVIDERS.get(target_name, DEFAULT_PROVIDERS["openai"])
        p_cfg = cfg.get("providers", {}).get(target_name, {})

        base_url = self.cli_base_url or p_cfg.get("base_url") or defn.get("base_url", "")
        model = self.cli_model or p_cfg.get("model") or defn.get("default_model", "")
        api_key = get_resolved_api_key(target_name) or ""

        return target_name, base_url, model, api_key

    def _chat(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        """Executes chat completion with transparent diagnostics and intelligent fallback."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        target_name, base_url, model, api_key = self._resolve_active_provider()
        defn = DEFAULT_PROVIDERS.get(target_name, {})
        p_type = defn.get("type", "openai_compatible")

        # Try Primary Provider
        try:
            if p_type == "openai_compatible":
                if not api_key and target_name != "custom":
                    # Prompt for key if missing
                    print(f"\n[!] API Key required for provider '{defn.get('name', target_name)}'.")
                    if sys.stdin.isatty():
                        entered = getpass.getpass("Enter API key: ").strip()
                        if entered:
                            api_key = entered
                            if input("Save to Keychain? [Y/n]: ").strip().lower() != "n":
                                save_keychain_key(target_name, api_key)
                    if not api_key:
                        raise RuntimeError(f"Missing API key for {target_name}. Set {defn.get('env_key')} or run 'msp ai configure'")

                with _spinner(f"{defn.get('name', target_name)} ({model})"):
                    return _http_chat_completion(
                        provider_name=target_name,
                        base_url=base_url,
                        api_key=api_key,
                        model=model,
                        messages=messages,
                        json_mode=json_mode,
                    )

            elif p_type == "ollama":
                with _spinner(f"Ollama ({model})"):
                    return _ollama_chat(messages, model=model, base_url=base_url, json_mode=json_mode)

            elif p_type == "apfel":
                with _spinner("Apple Intelligence (apfel)"):
                    return _apfel_chat(system_prompt, user_prompt)

            elif p_type == "openvino":
                with _spinner(f"OpenVINO ({self.openvino_device})"):
                    return _openvino_chat(messages, model=model, device=self.openvino_device)

        except Exception as primary_error:
            # Report the exact error reason from primary provider
            print(f"\n[-] {defn.get('name', target_name)} failed: {primary_error}", file=sys.stderr)

            # Check if local fallback is available
            fallback_options = []
            if target_name != "apfel" and _apfel_available():
                fallback_options.append("apfel")
            if target_name != "ollama" and _ollama_available():
                fallback_options.append("ollama")

            if fallback_options:
                fallback_name = fallback_options[0]
                print(f"[!] Notice: Falling back to local on-device AI ('{fallback_name}') ...", file=sys.stderr)
                try:
                    if fallback_name == "apfel":
                        with _spinner("Apple Intelligence (apfel fallback)"):
                            return _apfel_chat(system_prompt, user_prompt)
                    elif fallback_name == "ollama":
                        with _spinner("Ollama (fallback)"):
                            return _ollama_chat(messages, model="qwen2.5-coder:1.5b", json_mode=json_mode)
                except Exception as fb_err:
                    print(f"[-] Fallback provider '{fallback_name}' also failed: {fb_err}", file=sys.stderr)

            raise RuntimeError(
                f"Primary provider '{target_name}' failed ({primary_error}).\n"
                "Run 'msp ai configure' to update your API key or select a different provider."
            ) from primary_error

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
            print(f"\nError: {e}", file=sys.stderr)
            return None

        if output and output.strip():
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
            print("Error: AI returned empty response", file=sys.stderr)
            return None

    def analyze_results(self, data: Any, json_output: bool = False) -> Optional[str]:
        return self.ask(
            "Analyze this system data and flag any suspicious or concerning items:",
            data=data,
            json_output=json_output
        )

    def interactive_watch(self, interval: int = 60, modules: Optional[List[str]] = None) -> None:
        if modules is None:
            modules = ["net.established", "startup.list", "fswatch.recent"]

        print(f"Interactive watch mode (Ctrl+C to stop)")
        print(f"Running every {interval} seconds...\n")

        try:
            while True:
                print(f"\n{'=' * 60}")
                print(f"Scan at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
        prompt = f"""Explain the macOS security setting '{setting_name}':
1. What does it do?
2. What are the security implications of having it on/off?
3. Who should enable/disable it based on their threat model?

Keep the response practical and concise."""
        return self.ask(prompt)

    def compare_presets(self, preset1: str, preset2: str) -> Optional[str]:
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
        prompt = "Based on this system's current security configuration, suggest specific hardening steps:"
        return self.ask(prompt, json_output=json_output)


# ---------------------------------------------------------------------------
# Interactive Menu & CLI
# ---------------------------------------------------------------------------

def interactive_menu(analyzer: AIAnalyzer, json_output: bool = False):
    cfg = load_ai_config()
    cur_p = cfg.get("default_provider", "auto-detect")
    cur_m = cfg.get("providers", {}).get(cur_p, {}).get("model", "")

    while True:
        action = cmd_interactive_menu([
            {"name": "💬  Ask a question", "value": "ask"},
            {"name": "⚙️   Configure AI Provider & Keys (BYOK)", "value": "configure"},
            {"name": "🔍  Analyze system state", "value": "analyze"},
            {"name": "👀  Watch mode (periodic scan + AI analysis)", "value": "watch"},
            {"name": "📖  Explain a security setting", "value": "explain"},
            {"name": "⚖️   Compare presets", "value": "compare"},
            {"name": "🛡️   Suggest hardening steps", "value": "suggest"},
            {"name": "⚡  List OpenVINO / USB devices", "value": "devices"},
            {"name": "❌  Exit", "value": "exit"},
        ], title=f"=== macOS Privacy AI Diagnostics (Active: {cur_p} {cur_m}) ===")

        if not action or action == "exit":
            break

        if action == "ask":
            q = input("\nEnter your question: ").strip()
            if q:
                analyzer.ask(q, json_output=json_output)
        elif action == "configure":
            configure_provider_flow()
            cfg = load_ai_config()
            cur_p = cfg.get("default_provider", "auto-detect")
            cur_m = cfg.get("providers", {}).get(cur_p, {}).get("model", "")
        elif action == "analyze":
            analyzer.analyze_results({}, json_output=json_output)
        elif action == "watch":
            analyzer.interactive_watch()
        elif action == "explain":
            s = input("Setting name: ").strip()
            if s:
                analyzer.explain_setting(s)
        elif action == "compare":
            p1 = input("Preset 1: ").strip()
            p2 = input("Preset 2: ").strip()
            if p1 and p2:
                analyzer.compare_presets(p1, p2)
        elif action == "suggest":
            analyzer.suggest_hardening(json_output=json_output)
        elif action == "devices":
            devs = _openvino_list_devices()
            print(f"\nOpenVINO Devices: {devs if devs else 'none'}")

        input("\nPress Enter to continue...")


def main():
    parser = argparse.ArgumentParser(
        description="msp AI Analyzer - BYOK and On-Device macOS Diagnostics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  msp ask "what processes are using high memory?"
  msp ask "is my firewall configured securely?"
  msp ai configure                      Configure provider & API keys
  msp ai providers                      List / select active AI provider
  msp ai ask --text "analyze network"   Ask question via flag
""",
    )
    parser.add_argument("action", nargs="?", choices=["ask", "configure", "providers", "analyze", "watch", "explain", "compare", "suggest", "devices"],
                        help="Action to perform (omit for interactive menu)")
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
    parser.add_argument("--model", help="LLM model name")
    parser.add_argument("--provider", choices=list(DEFAULT_PROVIDERS.keys()), help="Force a specific LLM provider")
    parser.add_argument("--openvino-device", help="OpenVINO device to use (AUTO, CPU, GPU, NPU, USB)")
    parser.add_argument("--sort", help="Sort not applicable for AI commands")
    setup_completion(parser)
    args = parser.parse_args()

    analyzer = AIAnalyzer(
        verbose=args.verbose,
        provider=args.provider,
        llm_model=args.model,
        openvino_device=args.openvino_device,
    )

    if not args.action:
        interactive_menu(analyzer, args.json)
        return

    if args.action in ("configure", "providers"):
        configure_provider_flow()
        return

    if args.action == "ask":
        prompt = args.text or (input("Your question: ").strip() if sys.stdin.isatty() else "")
        if not prompt:
            print("Error: prompt required", file=sys.stderr)
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
        analyzer.analyze_results(data, json_output=args.json)

    elif args.action == "watch":
        analyzer.interactive_watch(interval=args.interval, modules=args.modules)

    elif args.action == "explain":
        if not args.setting:
            print("Error: --setting required", file=sys.stderr)
            sys.exit(1)
        analyzer.explain_setting(args.setting)

    elif args.action == "compare":
        if not args.preset1 or not args.preset2:
            print("Error: --preset1 and --preset2 required", file=sys.stderr)
            sys.exit(1)
        analyzer.compare_presets(args.preset1, args.preset2)

    elif args.action == "suggest":
        analyzer.suggest_hardening(json_output=args.json)

    elif args.action == "devices":
        devices = _openvino_list_devices()
        print(f"\nAvailable OpenVINO devices: {devices if devices else 'none detected'}")


if __name__ == "__main__":
    main()
