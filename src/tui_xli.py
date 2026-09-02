#!/usr/bin/env python3
"""msp TUI - Interactive Security Assistant using xli.

A transcript-style terminal UI that combines all msp commands with AI-powered
analysis in a chat-like interface. Type questions for the LLM, or use /
commands for tools. All output stays in your terminal's native scrollback.

Usage:
    msp tui          # Launch the interactive security assistant
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import xli

from src.network import NetworkMonitor
from src.startup import StartupManager
from src.scanner import SecurityScanner, Finding
from src.privacy_settings import PrivacySettingsManager
from src.snapshot import SnapshotManager
from src.splash import make_splash
from src.traffic import TrafficAnalyzer

# ---------------------------------------------------------------------------
# Provider config
# ---------------------------------------------------------------------------

@dataclass
class LLMProvider:
    name: str
    api_key: str = ""
    base_url: str = ""
    models: list[str] = field(default_factory=list)
    env_key: str = ""

    def is_configured(self) -> bool:
        return bool(self.api_key) or self.name == "ollama"


def _discover_providers() -> dict[str, LLMProvider]:
    providers: dict[str, LLMProvider] = {}

    key_map = {
        "OPENAI_API_KEY": ("openai", "https://api.openai.com/v1",
                           ["gpt-4o-mini", "gpt-4o", "o1-mini", "o1-preview", "gpt-4.1", "gpt-4.1-mini"]),
        "ANTHROPIC_API_KEY": ("anthropic", "https://api.anthropic.com/v1",
                              ["claude-sonnet-4-20250514", "claude-haiku-4-20250514"]),
        "GEMINI_API_KEY": ("gemini", "https://generativelanguage.googleapis.com/v1beta",
                           ["gemini-2.5-flash", "gemini-2.5-pro"]),
        "OPENROUTER_API_KEY": ("openrouter", "https://openrouter.ai/api/v1",
                               ["openai/gpt-4o", "anthropic/claude-sonnet-4"]),
        "DEEPSEEK_API_KEY": ("deepseek", "https://api.deepseek.com",
                             ["deepseek-chat", "deepseek-reasoner"]),
        "GROQ_API_KEY": ("groq", "https://api.groq.com/openai/v1",
                         ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"]),
        "TOGETHER_API_KEY": ("together", "https://api.together.xyz/v1",
                             ["meta-llama/Llama-3.3-70B-Instruct-Turbo"]),
        "XAI_API_KEY": ("xai", "https://api.x.ai/v1",
                        ["grok-beta", "grok-2"]),
    }

    for env_var, (name, base_url, models) in key_map.items():
        key = os.environ.get(env_var, "")
        if key:
            providers[name] = LLMProvider(name=name, api_key=key, base_url=base_url, models=models, env_key=env_var)

    env_files = [".env", ".env.local"]
    for ef in env_files:
        p = Path(ef)
        if p.exists():
            with p.open() as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    v = v.strip("\"'").strip()
                    if k in key_map and k not in os.environ and v:
                        name, base_url, models = key_map[k]
                        if name not in providers:
                            providers[name] = LLMProvider(name=name, api_key=v, base_url=base_url, models=models, env_key=k)

    # An explicit preferred provider (MSP_LLM_PROVIDER) is honored even without a
    # key present — the TUI will prompt for its API key up front on startup.
    forced = os.environ.get("MSP_LLM_PROVIDER", "").lower()
    if forced in key_map:
        _name, _base_url, _models = key_map[forced]
        if _name not in providers:
            providers[_name] = LLMProvider(name=_name, api_key="", base_url=_base_url, models=_models, env_key=forced)

    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            ollama_models = [m["name"] for m in data.get("models", [])]
            providers["ollama"] = LLMProvider(
                name="ollama", base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
                models=ollama_models or [os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:1.5b")],
            )
    except Exception:
        pass

    return providers


def _fetch_ollama_models(base_url: str) -> list[str]:
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _fetch_openai_models(api_key: str, base_url: str) -> list[str]:
    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/models")
        req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["id"] for m in data.get("data", []) if not m["id"].startswith("ft:")]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_llm_provider: str = ""
_llm_model: str = ""
_llm_providers: dict[str, LLMProvider] = {}

def _pick_model_for_provider(name: str, provider: LLMProvider) -> str:
    if name == "ollama":
        models = _fetch_ollama_models(provider.base_url) or provider.models
    elif name in ("openai", "openrouter", "deepseek", "groq", "together", "xai", "gemini"):
        if provider.api_key:
            models = _fetch_openai_models(provider.api_key, provider.base_url) or provider.models
        else:
            models = provider.models
    else:
        models = provider.models
    return models[0] if models else "unknown"


def _init_llm_state(providers: dict[str, LLMProvider]) -> None:
    global _llm_provider, _llm_model, _llm_providers
    _llm_providers = providers
    forced = os.environ.get("MSP_LLM_PROVIDER", "").lower()
    if forced and forced in providers:
        _llm_provider = forced
    elif "openai" in providers:
        _llm_provider = "openai"
    elif "ollama" in providers:
        _llm_provider = "ollama"
    elif providers:
        _llm_provider = next(iter(providers))
    if _llm_provider:
        p = providers[_llm_provider]
        _llm_model = _pick_model_for_provider(_llm_provider, p)
    else:
        _llm_provider = ""
        _llm_model = ""


_KEYCHAIN_SERVICE_PREFIX = "msp-"


def _restore_keys_from_keychain(providers: dict[str, LLMProvider]) -> None:
    """Fill any missing provider keys from the macOS keychain (service `msp-<name>`)."""
    for name, p in providers.items():
        if p.api_key or name == "ollama" or not p.env_key:
            continue
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-s", f"{_KEYCHAIN_SERVICE_PREFIX}{name}", "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                p.api_key = r.stdout.strip()
                os.environ[p.env_key] = p.api_key
        except Exception:
            pass


def _save_key_to_keychain(name: str, key: str) -> bool:
    try:
        user = os.environ.get("USER", "")
        r = subprocess.run(
            ["security", "add-generic-password", "-s", f"{_KEYCHAIN_SERVICE_PREFIX}{name}",
             "-a", user, "-w", key, "-U"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


async def _prompt_for_provider_key(ui: xli.UI, provider: LLMProvider) -> bool:
    """Up-front, provider-named, masked modal for a missing API key.

    Tells the user which provider + env var is needed, captures the key with
    masked input (never echoed), and offers to persist it in the macOS keychain.
    Returns True if a key was set (env + provider state), False if skipped.
    """
    name = provider.name
    env_var = provider.env_key or f"{name.upper()}_API_KEY"

    ui.message("system",
        f"**{name}** needs an API key (`{env_var}` is not set).\n"
        f"Enter your {name} API key below — input is masked. "
        "Press ESC to skip and configure later via `/providers`."
    )
    key = await ui.secret_input(f"Enter your {name} API key ({env_var})", title="API Key Required")
    if not key:
        ui.note(f"Skipped — set `{env_var}` in your environment, or run `/providers`.")
        return False

    provider.api_key = key
    if provider.env_key:
        os.environ[provider.env_key] = key
    global _llm_model
    if not _llm_model:
        _llm_model = _pick_model_for_provider(name, provider)
    ui.status.set(provider=_llm_provider or name, model=_llm_model)

    decision = await ui.approve(
        title="Save to macOS keychain?",
        body=f"Store the {name} API key so future sessions don't prompt again?",
        reason="",
    )
    if decision in ("approved", "approved_for_session"):
        if _save_key_to_keychain(name, key):
            ui.note(f"Saved {name} API key to the macOS keychain.")
        else:
            ui.note("Could not save to keychain — key active for this session only.")
    else:
        ui.note("Key active for this session only.")
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class SysProvider:
    def __init__(self):
        self.network = NetworkMonitor(verbose=False)
        self.startup = StartupManager(verbose=False)
        self.scanner = SecurityScanner(verbose=False)
        self.privacy = PrivacySettingsManager(verbose=False)
        self.snapshot = SnapshotManager(verbose=False)
        self.traffic = TrafficAnalyzer(verbose=False)


_sys: SysProvider | None = None

def get_sys() -> SysProvider:
    global _sys
    if _sys is None:
        _sys = SysProvider()
    return _sys


def _open_terminal(cmd: str) -> bool:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'tell application "Terminal" to do script "{cmd}"'],
            capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _sh(cmd: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _fmt(obj: Any) -> str:
    if isinstance(obj, list):
        return "\n".join(str(x) for x in obj)
    if isinstance(obj, dict):
        return json.dumps(obj, indent=2)
    return str(obj)


# ---------------------------------------------------------------------------
# LLM chat (default handler)
# ---------------------------------------------------------------------------

class _HTTPError(RuntimeError):
    """Raised when a provider HTTP call fails (auth errors, network, ...)."""


def _open_url(req: urllib.request.Request, timeout: int = 90):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise _HTTPError(f"HTTP {e.code} from provider{': ' + detail if detail else ''}") from e
    except urllib.error.URLError as e:
        raise _HTTPError(f"Network error: {e.reason}") from e


def _ask_provider(provider: LLMProvider, prompt: str, context: list[str]) -> str:
    """Call the selected provider's HTTP API directly (stdlib urllib only).

    Avoids AIAnalyzer's provider chain, which would drop raw getpass/input
    prompts onto the terminal while the TUI is running.
    """
    full = prompt
    if context:
        full = f"{prompt}\n\n## Live System Data\n" + "\n".join(context)
    system = (
        "You are a macOS security and diagnostics assistant. "
        "Answer concisely and accurately. When relevant, include terminal commands "
        "the user can run (prefixed with `$ `). If you reference system data, "
        "be specific about PIDs, process names, and numbers. "
        "If nothing abnormal appears, say so — do not invent problems."
    )
    base = provider.base_url.rstrip("/")

    if provider.name == "ollama":
        body = json.dumps({
            "model": _llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": full},
            ],
            "stream": False,
        }).encode()
        req = urllib.request.Request(f"{base}/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        with _open_url(req) as resp:
            data = json.loads(resp.read())
        text = data.get("message", {}).get("content", "")
    elif provider.name == "anthropic":
        body = json.dumps({
            "model": _llm_model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": full}],
        }).encode()
        req = urllib.request.Request(f"{base}/messages", data=body, headers={
            "Content-Type": "application/json",
            "x-api-key": provider.api_key or "",
            "anthropic-version": "2023-06-01",
        })
        with _open_url(req) as resp:
            data = json.loads(resp.read())
        text = "\n".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))
    elif provider.name == "gemini":
        model = urllib.parse.quote(_llm_model)
        url = f"{base}/models/{model}:generateContent?key={provider.api_key or ''}"
        body = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": system + "\n\n" + full}]}],
        }).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        with _open_url(req) as resp:
            data = json.loads(resp.read())
        parts = []
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                parts.append(part.get("text", ""))
        text = "\n".join(parts)
    else:  # openai-compatible: openai, openrouter, deepseek, groq, together, xai
        body = json.dumps({
            "model": _llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": full},
            ],
            "stream": False,
        }).encode()
        req = urllib.request.Request(f"{base}/chat/completions", data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {provider.api_key or ''}",
        })
        with _open_url(req) as resp:
            data = json.loads(resp.read())
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

    if not text.strip():
        raise _HTTPError("Provider returned an empty response")
    return text


async def cmd_chat(ui: xli.UI, prompt: str) -> None:
    prompt = prompt.strip()
    if not prompt:
        return

    if not _llm_provider:
        ui.tool("chat", status="error", output=(
            "No AI provider configured — this command needs an API key.\n"
            "Run `/providers` to select a provider and enter its key, or set one of "
            "`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, ... in your "
            "environment or `.env`."
        ))
        return

    provider = _llm_providers.get(_llm_provider)
    if not provider:
        ui.tool("chat", status="error", output=f"Provider '{_llm_provider}' not found. Run `/providers`.")
        return

    if not provider.is_configured():
        got_key = await _prompt_for_provider_key(ui, provider)
        if not got_key:
            ui.tool("chat", status="error", output=(
                f"`{_llm_provider}` has no API key configured.\n"
                f"Set `{provider.env_key or _llm_provider.upper() + '_API_KEY'}` in your "
                "environment, or run `/providers` to enter one."
            ))
            return

    card = ui.tool("chat", status="running", args={"model": _llm_model})
    context_parts = []
    p = get_sys()

    net_kw = {"network", "connection", "port", "listen", "traffic", "bandwidth", "internet", "wifi", "dns"}
    startup_kw = {"startup", "launch", "boot", "login", "agent", "daemon", "service"}
    scan_kw = {"scan", "security", "virus", "malware", "suspicious", "weird", "unusual", "threat", "vulnerability"}

    all_keywords = net_kw | startup_kw | scan_kw
    has_relevant = any(kw in prompt.lower() for kw in all_keywords)

    if has_relevant:
        tags = []
        if any(kw in prompt.lower() for kw in net_kw):
            tags.append("network")
        if any(kw in prompt.lower() for kw in startup_kw):
            tags.append("startup")
        if any(kw in prompt.lower() for kw in scan_kw):
            tags.append("scan")

        for tag in tags:
            try:
                if tag == "network":
                    conns = p.network.list_established(json_output=False) if p.network else []
                    ports = p.network.list_listening(json_output=False) if p.network else []
                    context_parts.append(f"Active connections: {len(conns)}, Listening ports: {len(ports)}")
                if tag == "startup":
                    items = p.startup.list_all(json_output=False) if p.startup else []
                    context_parts.append(f"Startup items: {len(items)}")
                if tag == "scan" or tag == "security":
                    findings = p.scanner.scan_quick(json_output=False) if p.scanner else []
                    context_parts.append(f"Security findings: {len(findings)}")
            except Exception:
                pass

        try:
            uptime = _sh("uptime")
            if uptime:
                context_parts.append(uptime)
            cpu = _sh("ps axo pid,pcpu,pmem,comm -r | head -12")
            if cpu:
                context_parts.append(f"Top processes:\n{cpu}")
        except Exception:
            pass

        fw = p.privacy.get_firewall_status() if p.privacy else {}
        gk = p.privacy.get_gatekeeper_status() if p.privacy else {}
        context_parts.append(f"Firewall: {'on' if fw.get('enabled') else 'off'} | Gatekeeper: {'on' if gk.get('enabled') else 'off'}")

    try:
        output = _ask_provider(provider, prompt, context_parts)
    except Exception as e:
        output = f"LLM call failed: {e}"

    card.update(status="done", output=output)


# ---------------------------------------------------------------------------
# Slash Commands
# ---------------------------------------------------------------------------

async def cmd_status(ui: xli.UI, args: str) -> None:
    card = ui.tool("status", status="running", args={})
    p = get_sys()
    fw = p.privacy.get_firewall_status() if p.privacy else {}
    gk = p.privacy.get_gatekeeper_status() if p.privacy else {}
    fv = p.privacy.get_filevault_status() if p.privacy else {}
    listening = p.network.list_listening(json_output=False) if p.network else []
    startup_items = p.startup.list_all(json_output=False) if p.startup else []

    fw_enabled = fw.get("enabled", False)
    gk_enabled = gk.get("enabled", False)
    fv_enabled = fv.get("enabled", False)
    stealth = fw.get("stealth_mode", False)

    lines = [
        f"**Firewall:** {'✅ Enabled' if fw_enabled else '❌ Disabled'}" + (f" (Stealth: {'on' if stealth else 'off'})" if fw_enabled else ""),
        f"**Gatekeeper:** {'✅ Enabled' if gk_enabled else '❌ Disabled'}",
        f"**FileVault:** {'✅ Enabled' if fv_enabled else '❌ Disabled'}",
        f"**Listening Ports:** {len(listening)}",
        f"**Startup Items:** {len(startup_items)}",
    ]
    high_risk = sum(1 for s in startup_items if hasattr(s, 'name') and s.name.lower() in ('update', 'helper', 'agent', 'daemon', 'service'))
    if high_risk:
        lines.append(f"\n⚠️ **{high_risk} high-risk startup items**")

    card.update(status="done", output="\n".join(lines))


async def cmd_net(ui: xli.UI, args: str) -> None:
    p = get_sys()
    parts = shlex.split(args) if args else []
    cmd = parts[0] if parts else "list"
    card = ui.tool(f"net {cmd}", status="running", args={})

    if cmd == "established":
        conns = p.network.list_established(json_output=True) if p.network else []
        if not conns:
            output = "No active connections found."
        else:
            rows = [f"  `{c.get('process', c.get('name', '?'))}` ({c.get('pid', '?')})  {c.get('local', c.get('local_addr', '?'))} → {c.get('remote', c.get('remote_addr', '?'))}" for c in conns[:30]]
            output = f"**Active Connections** ({len(conns)} total, {min(30, len(conns))} shown):\n" + "\n".join(rows)
    elif cmd == "top":
        data = p.network.bandwidth_top(limit=15, json_output=True) if p.network else []
        if not data:
            output = "No bandwidth data available."
        else:
            rows = [f"  `{d.get('process', d.get('name', '?'))}`  ↓{d.get('in', d.get('received', '?'))}  ↑{d.get('out', d.get('sent', '?'))}" for d in data[:15]]
            output = "**Bandwidth Top:**\n" + "\n".join(rows)
    elif cmd == "arp":
        result = _sh("arp -a 2>/dev/null | head -30")
        output = f"**ARP Cache:**\n```\n{result or 'No entries'}\n```"
    elif cmd == "nmap":
        _open_terminal("msp net nmap")
        card.update(status="done", output="Opened Terminal window for `msp net nmap` (needs interactive input)")
        return
    else:
        ports_data = p.network.list_listening(json_output=False) if p.network else []
        if not ports_data:
            output = "No listening ports found."
        else:
            seen = set()
            rows = []
            for c in ports_data:
                port = c.local_addr.split(":")[-1] if ":" in c.local_addr else c.local_addr
                key = (port, c.process, c.pid)
                if key not in seen:
                    seen.add(key)
                    rows.append(f"  `:{port}`  {c.process} ({c.pid})  {c.user}")
            output = f"**Listening Ports** ({len(rows)}):\n" + "\n".join(rows[:40])

    card.update(status="done", output=output)


async def cmd_scan(ui: xli.UI, args: str) -> None:
    p = get_sys()
    parts = shlex.split(args) if args else []
    cmd = parts[0] if parts else "quick"
    card = ui.tool(f"scan {cmd}", status="running", args={})

    try:
        if cmd == "deep":
            findings = p.scanner.scan_deep(json_output=False) if p.scanner else []
        elif cmd == "suspicious":
            findings = p.scanner.scan_suspicious(json_output=False) if p.scanner else []
        else:
            findings = p.scanner.scan_quick(json_output=False) if p.scanner else []
    except Exception as e:
        card.update(status="error", output=f"Scan error: {e}")
        return

    if not findings:
        output = f"No findings from `{cmd}` scan."
    else:
        icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}
        lines = [f"**{cmd.capitalize()} Scan** — {len(findings)} findings:"]
        for f in findings[:25]:
            sev = f.severity.upper() if hasattr(f, 'severity') else "INFO"
            cat = f.category if hasattr(f, 'category') else "?"
            item = (f.item if hasattr(f, 'item') else "")[:60]
            desc = (f.description if hasattr(f, 'description') else "")[:100]
            ico = icon.get(sev, "⚪")
            lines.append(f"  {ico} **[{sev}]** {cat}: {item}")
            if desc:
                lines.append(f"    _{desc}_")
        output = "\n".join(lines)

    card.update(status="done", output=output)


async def cmd_startup(ui: xli.UI, args: str) -> None:
    p = get_sys()
    parts = shlex.split(args) if args else []
    cmd = parts[0] if parts else "list"
    card = ui.tool(f"startup {cmd}", status="running", args={})

    try:
        if cmd == "audit":
            items = p.startup.audit(json_output=False) if p.startup else []
            if not items:
                output = "No startup items flagged in audit."
            else:
                lines = [f"**Startup Audit** ({len(items)} items):"]
                for item in items[:30]:
                    risk = item.get('risk', item.get('severity', 'INFO'))
                    name = item.get('name', item.get('label', '?'))
                    label = item.get('label', '')
                    lines.append(f"  {'🟠' if risk in ('HIGH', 'MEDIUM') else '⚪'} **[{risk}]** {name}" + (f" — {label[:60]}" if label else ""))
                output = "\n".join(lines)
        else:
            items = p.startup.list_all(json_output=False) if p.startup else []
            if not items:
                output = "No startup items found."
            else:
                lines = [f"**Startup Items** ({len(items)}):"]
                for item in items[:25]:
                    name = getattr(item, 'name', getattr(item, 'label', '?'))
                    status = getattr(item, 'status', '?')
                    pid = getattr(item, 'pid', None)
                    lines.append(f"  `{name}` [{status}]" + (f" (pid {pid})" if pid else ""))
                output = "\n".join(lines)
    except Exception as e:
        output = f"Error: {e}"

    card.update(status="done", output=output)


async def cmd_traffic(ui: xli.UI, args: str) -> None:
    parts = shlex.split(args) if args else []
    cmd = parts[0] if parts else "summary"
    card = ui.tool(f"traffic {cmd}", status="running", args={})

    if cmd == "dns":
        result = _sh("scutil --dns 2>/dev/null | head -40")
        output = f"**DNS Configuration:**\n```\n{result or 'No DNS data'}\n```"
    elif cmd == "http":
        result = _sh(r"lsof -iTCP -sTCP:ESTABLISHED -nP 2>/dev/null | grep -E ':https|:http' | head -30")
        output = f"**HTTP/HTTPS Connections:**\n```\n{result or 'None found'}\n```"
    else:
        result = _sh("lsof -iTCP -sTCP:ESTABLISHED -nP 2>/dev/null | tail -n +2 | awk '{print $1}' | sort | uniq -c | sort -rn | head -15")
        output = f"**Top Consumers:**\n```\n{result or 'No data'}\n```"

    card.update(status="done", output=output)


async def cmd_snapshot(ui: xli.UI, args: str) -> None:
    p = get_sys()
    parts = shlex.split(args) if args else []
    cmd = parts[0] if parts else "list"
    card = ui.tool(f"snapshot {cmd}", status="running", args={})

    try:
        if cmd == "capture":
            name = parts[1] if len(parts) > 1 else None
            p.snapshot.capture(name=name) if p.snapshot else None
            output = f"✅ Snapshot captured: `{name or 'default'}`"
        elif cmd == "diff":
            name = parts[1] if len(parts) > 1 else None
            if name and p.snapshot:
                result = p.snapshot.diff(name, json_output=True)
                output = f"**Diff: `{name}`**\n```\n{_fmt(result)}\n```"
            else:
                output = "Usage: `/snapshot diff <name>`"
        else:
            snaps = p.snapshot.list_snapshots(json_output=True) if p.snapshot else []
            if not snaps:
                output = "No snapshots found."
            else:
                lines = ["**Snapshots:**"]
                for s in snaps[:15]:
                    lines.append(f"  - `{s.get('name', '?')}` ({s.get('timestamp', '?')})")
                output = "\n".join(lines)
    except Exception as e:
        output = f"Error: {e}"

    card.update(status="done", output=output)


async def cmd_watch(ui: xli.UI, args: str) -> None:
    parts = shlex.split(args) if args else []
    target = parts[0] if parts else "status"
    card = ui.tool(f"watch {target}", status="running", args={})
    p = get_sys()

    lines = []
    for i in range(10):
        if target == "network":
            conns = p.network.list_established(json_output=True) if p.network else []
            lines.append(f"**Tick {i+1}/10** — Connections: {len(conns)}")
        elif target == "ports":
            ports = p.network.list_listening(json_output=False) if p.network else []
            lines.append(f"**Tick {i+1}/10** — Listening ports: {len(ports)}")
        else:
            fw = p.privacy.get_firewall_status() if p.privacy else {}
            lines.append(f"**Tick {i+1}/10** — Firewall: {'on' if fw.get('enabled') else 'off'}")
        await asyncio.sleep(3)

    card.update(status="done", output="\n".join(lines))


async def cmd_clear(ui: xli.UI, args: str) -> None:
    ui.clear_transcript()


async def cmd_providers(ui: xli.UI, args: str) -> None:
    providers = _discover_providers()

    if not providers and not args:
        ui.note("No providers found. Set an API key (e.g. OPENAI_API_KEY) or make sure Ollama is running.")
        return

    items = [f"{p.name} ({p.env_key})" if p.env_key else p.name for p in providers.values()]
    items.append("➕ Custom provider")

    choice = await ui.pick("Select LLM provider", items)
    if choice is None:
        return

    if choice == "➕ Custom provider":
        base_url = await ui.input("Base URL", default="https://api.openai.com/v1")
        if base_url is None:
            return
        name_hint = base_url.split("//")[1].split(".")[0] if "//" in base_url else "custom"
        name = await ui.input("Provider name", default=name_hint)
        if name is None:
            return
        providers[name] = LLMProvider(name=name, api_key="", base_url=base_url, models=[])
        selected = name
    else:
        selected = choice.split(" ")[0]

    provider = providers[selected]
    global _llm_provider, _llm_model
    _llm_provider = selected
    _llm_providers = providers

    if selected not in ("ollama",) and not provider.is_configured():
        got_key = await _prompt_for_provider_key(ui, provider)
        if not got_key:
            ui.note(f"`{selected}` has no API key — chat will be unavailable until configured.")

    models = provider.models[:]
    if provider.api_key and selected not in ("ollama",):
        with ui.working("Fetching available models"):
            fetched = _fetch_openai_models(provider.api_key, provider.base_url)
            if fetched:
                models = fetched
    elif selected == "ollama":
        with ui.working("Fetching Ollama models"):
            fetched = _fetch_ollama_models(provider.base_url)
            if fetched:
                models = fetched

    if models:
        choice = await ui.pick(f"Model for {selected}", models)
        if choice:
            _llm_model = choice
    else:
        _llm_model = await ui.input("Model name", default="gpt-4o-mini") or "gpt-4o-mini"

    ui.status.set(provider=_llm_provider, model=_llm_model)
    ui.message("system", f"Provider set to **{_llm_provider}** with model **{_llm_model}**")


async def cmd_models(ui: xli.UI, args: str) -> None:
    if not _llm_provider:
        ui.note("No provider selected. Run `/providers` first.")
        return

    provider = _llm_providers.get(_llm_provider)
    if not provider:
        ui.note(f"Provider '{_llm_provider}' not found. Run `/providers` to re-configure.")
        return

    models = provider.models[:]
    if provider.api_key and _llm_provider != "ollama":
        with ui.working(f"Fetching models from {_llm_provider}"):
            fetched = _fetch_openai_models(provider.api_key, provider.base_url)
            if fetched:
                models = fetched
    elif _llm_provider == "ollama":
        with ui.working("Fetching Ollama models"):
            fetched = _fetch_ollama_models(provider.base_url)
            if fetched:
                models = fetched

    global _llm_model
    if not models:
        ui.note(f"No models found for {_llm_provider}. Enter one manually.")
        choice = await ui.input("Model name", default=_llm_model)
        if choice:
            _llm_model = choice
            ui.status.set(model=_llm_model)
        return

    choice = await ui.pick(f"Models — {_llm_provider}", models)
    if choice:
        _llm_model = choice
        ui.status.set(model=_llm_model)
        ui.message("system", f"Switched to **{_llm_model}**")


async def cmd_help(ui: xli.UI, args: str) -> None:
    groups = [
        ("Security", [
            ("/status", "Security dashboard overview"),
            ("/scan", "Quick security scan"),
            ("/scan deep", "Deep scan"),
            ("/scan suspicious", "Suspicious process scan"),
            ("/net", "Listening ports"),
            ("/net established", "Active connections"),
            ("/net top", "Bandwidth usage"),
            ("/net arp", "Network devices"),
            ("/net nmap", "Port scan (opens Terminal)"),
        ]),
        ("Privacy", [
            ("/startup", "List startup items"),
            ("/startup audit", "Audit startup items"),
            ("/traffic", "Traffic summary"),
            ("/traffic dns", "DNS queries"),
            ("/snapshot", "List snapshots"),
            ("/snapshot capture [name]", "Capture snapshot"),
        ]),
        ("Performance", [
            ("/watch [target]", "Monitor (3s intervals × 10 ticks)"),
        ]),
        ("Provider & Model", [
            ("/providers", "Select AI provider (auto-discovers API keys)"),
            ("/models", "Select model for current provider"),
        ]),
    ]
    lines = ["**msp Commands**\n"]
    for heading, cmds in groups:
        lines.append(f"**{heading}**")
        for cmd, desc in cmds:
            lines.append(f"  `{cmd}`  — {desc}")
        lines.append("")
    lines.append("**Help**")
    lines.append("  `/ask`  — Send to AI (bypasses built-in command matching)")
    lines.append("  `/clear`  — Clear transcript")
    lines.append("  `/help`  — Show this help")
    lines += [
        "",
        "**Exit**",
        "  `/q`  — Quit the TUI (also `/quit`, `/exit`)",
        "\n**Tips:**",
        "- Natural language runs matching commands automatically, or falls through to AI",
        "- Force AI with `/ask <question>` to bypass command matching",
        "- Use `@` to reference files from the working directory",
        "- Press **ESC** to interrupt a running command",
        "- All output stays in terminal scrollback",
    ]
    ui.message("system", "\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------



def main():
    providers = _discover_providers()
    _init_llm_state(providers)

    theme = xli.Theme(
        user_color="cyan",
        assistant_color="green",
        tool_glyph="→",
        muted_color="grey50",
        success_color="green",
        error_color="red",
        warning_color="yellow",
        code_theme="monokai",
    )

    app = xli.UI(
        title="msp — macOS Security Privacy Assistant",
        theme=theme,
        intro="Type a message (use @ to mention a file or / for a command):",
        status_fields=["provider", "model"],
    )

    if _llm_provider:
        app.status.set(provider=_llm_provider, model=_llm_model)
    else:
        app.status.set(provider="no LLM", model="")

    @app.on_ready
    async def startup_key_check() -> None:
        # Up-front check: if the default provider needs an API key and doesn't
        # have one (env, .env, or keychain), prompt with a masked modal.
        _restore_keys_from_keychain(_llm_providers)
        p = _llm_providers.get(_llm_provider) if _llm_provider else None
        if p and p.name != "ollama" and not p.is_configured():
            await _prompt_for_provider_key(app, p)

    @app.command("status", description="Security dashboard overview")
    async def _(ui, args):
        await cmd_status(ui, args)

    @app.command("net", description="Network monitoring")
    async def _(ui, args):
        await cmd_net(ui, args)

    @app.command("scan", description="Security scanning")
    async def _(ui, args):
        await cmd_scan(ui, args)

    @app.command("startup", description="Startup items")
    async def _(ui, args):
        await cmd_startup(ui, args)

    @app.command("traffic", description="Traffic analysis")
    async def _(ui, args):
        await cmd_traffic(ui, args)

    @app.command("snapshot", description="Snapshot management")
    async def _(ui, args):
        await cmd_snapshot(ui, args)

    @app.command("watch", description="Start a monitoring watch")
    async def _(ui, args):
        await cmd_watch(ui, args)

    @app.command("providers", description="Select LLM provider")
    async def _(ui, args):
        await cmd_providers(ui, args)

    @app.command("models", description="Select LLM model")
    async def _(ui, args):
        await cmd_models(ui, args)

    @app.command("clear", description="Clear the transcript")
    async def _(ui, args):
        await cmd_clear(ui, args)

    @app.command("ask", description="Force AI analysis (bypass built-in commands)")
    async def _(ui, args):
        await cmd_chat(ui, args)

    @app.command("q", description="Exit the TUI", aliases=("quit", "exit"))
    async def _(ui, args):
        ui.exit()

    @app.command("help", description="Show available commands", aliases=("?",))
    async def _(ui, args):
        await cmd_help(ui, args)

    NL_DISPATCH: dict[str, Any] = {
        "status": cmd_status,
        "net": cmd_net,
        "net established": cmd_net,
        "net top": cmd_net,
        "net arp": cmd_net,
        "scan quick": cmd_scan,
        "scan deep": cmd_scan,
        "scan suspicious": cmd_scan,
        "startup": cmd_startup,
        "startup audit": cmd_startup,
        "traffic": cmd_traffic,
        "traffic dns": cmd_traffic,
        "snapshot": cmd_snapshot,
        "snapshot capture": cmd_snapshot,
        "clear": cmd_clear,
        "help": cmd_help,
    }

    NL_INTENTS = [
        (r"(security\s*)?(dashboard|overview|status)(\s+check)?", "status"),
        (r"(list|show|what(\s+is)?\s+(on\s+)?my\s+)?(listening\s+)?ports?", "net"),
        (r"(active|current|open|established)\s+(connections?|sockets?)", "net established"),
        (r"(network|bandwidth|traffic|data)\s+(top|usage|consum)", "net top"),
        (r"(arp|devices?\s+on\s+network|who\s+is\s+on\s+network)", "net arp"),
        (r"quick\s+scan|security\s+scan|scan\s+(now|system)", "scan quick"),
        (r"deep\s+scan|thorough\s+scan|full\s+scan", "scan deep"),
        (r"suspicious\s+(process|activity|scan)", "scan suspicious"),
        (r"(list|show|what)\s+startup(\s+items?)?(\s+run)?", "startup"),
        (r"audit\s+startup|startup\s+audit", "startup audit"),
        (r"traffic\s+summary|summary\s+traffic", "traffic"),
        (r"dns(\s+(lookup|query|config))?", "traffic dns"),
        (r"list\s+snapshots?|show\s+snapshots?|snapshots?\s+list", "snapshot"),
        (r"capture\s+snapshot|snapshot\s+capture|take\s+snapshot", "snapshot capture"),
        (r"clear(\s+(screen|transcript|terminal))?", "clear"),
        (r"(show\s+)?help(\s+commands?)?", "help"),
    ]

    def _match_intent(prompt: str) -> str | None:
        lower = prompt.lower().strip()
        for pattern, cmd in NL_INTENTS:
            if re.search(pattern, lower):
                return cmd
        return None

    NL_SUGGESTIONS: dict[str, str] = {
        "status": "For more detail try `/scan quick` or `/net`",
        "net": "Shows listening ports. For external exposure try `/net nmap`. For active connections try `/net established`",
        "net established": "For listening ports try `/net list`. For bandwidth try `/net top`",
        "net top": "For active connections try `/net established`",
        "net arp": "For listening ports try `/net list`",
        "scan quick": "For deeper analysis try `/scan deep` or `/scan suspicious`",
        "scan deep": "For a broader scan try `/scan quick`",
        "scan suspicious": "For a broader scan try `/scan quick`",
        "startup": "To audit risk try `/startup audit`",
        "startup audit": "To review all items try `/startup`",
        "traffic": "For DNS config try `/traffic dns`",
        "traffic dns": "For traffic summary try `/traffic`",
        "snapshot": "To capture system state try `/snapshot capture <name>`",
        "snapshot capture": "To list snapshots try `/snapshot`",
    }

    @app.on_prompt
    async def handle_prompt(prompt: str) -> None:
        prompt = prompt.strip()
        if not prompt:
            return
        if prompt == "/":
            await cmd_help(app, "")
            return
        intent = _match_intent(prompt)
        if intent:
            handler = NL_DISPATCH.get(intent)
            if handler:
                parts = intent.split(maxsplit=1)
                cmd_args = parts[1] if len(parts) > 1 else ""
                await handler(app, cmd_args)
                hint = NL_SUGGESTIONS.get(intent)
                if hint:
                    app.message("system", f"💡 {hint}\nNot what you wanted? Use `/ask <question>` to send to AI instead")
                return
        await cmd_chat(app, prompt)

    cols = shutil.get_terminal_size().columns
    splash = make_splash("TUI")
    lines = splash.strip('\n').split('\n')
    max_w = max(len(l) for l in lines)
    pad = max(0, (cols - max_w) // 2)
    for line in lines:
        if line.strip():
            print(" " * pad + line)
        else:
            print()
    line1 = "  macOS Security Privacy Assistant  v0.1.0"
    line2 = "  type / for a list of commands"
    print(" " * max(0, (cols - len(line1)) // 2) + line1)
    print(" " * max(0, (cols - len(line2)) // 2) + line2)
    print()

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"TUI error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
