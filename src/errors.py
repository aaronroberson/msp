#!/usr/bin/env python3
"""
Error handling and user guidance for msp CLI.
Provides actionable error messages with install hints.
"""
import subprocess
import sys
import os
from pathlib import Path
from typing import Optional, List


# Configuration directory
CONFIG_DIR = Path.home() / ".msp"
CONFIG_FILE = CONFIG_DIR / "config.toml"


# Tool definitions with install hints
TOOL_HINTS = {
    "nmap": {"brew": "nmap", "hint": "Network scanning and device discovery"},
    "fswatch": {"brew": "fswatch", "hint": "File system monitoring"},
    "ollama": {"brew": "ollama", "hint": "Local LLM provider"},
    "wireshark": {"brew": "wireshark", "hint": "Packet analysis (tshark CLI)"},
    "tshark": {"brew": "wireshark", "hint": "Packet analysis"},
    "knockknock": {"brew": "knockknock", "hint": "Startup scanner"},
    "processmonitor": {"brew": "processmonitor", "hint": "Process monitoring"},
    "somo": {"brew": "somo", "hint": "Network monitor"},
}


class MSPError(Exception):
    """Base exception for msp errors."""
    def __init__(self, message: str, hint: str = "", tool: str = ""):
        self.message = message
        self.hint = hint
        self.tool = tool
        super().__init__(self.message)


class ToolNotFoundError(MSPError):
    """Raised when a required tool is not found."""
    def __init__(self, tool: str):
        hint = TOOL_HINTS.get(tool, {})
        install_cmd = f"brew install {hint.get('brew', tool)}" if hint else f"brew install {tool}"
        super().__init__(
            f"Error: {tool} not found",
            f"Hint: {hint.get('hint', 'Required tool')} | Try: msp doctor --fix",
            tool
        )


def check_tool(tool: str) -> bool:
    """Check if a tool exists in PATH."""
    try:
        result = subprocess.run(
            ["which", tool],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def format_error(error: MSPError) -> str:
    """Format an error with actionable hints."""
    lines = [f"❌ {error.message}"]
    if error.hint:
        lines.append(f"   {error.hint}")
    return "\n".join(lines)


def require_tool(tool: str) -> None:
    """Raise ToolNotFoundError if tool not available."""
    if not check_tool(tool):
        raise ToolNotFoundError(tool)


def doctor_fix() -> None:
    """Auto-install missing dependencies."""
    from src.deps import DependencyManager
    
    manager = DependencyManager()
    results = manager.install_required()
    
    for name, success, msg in results:
        status = "✓" if success else "✗"
        print(f"{status} {name}: {msg}")


def load_config() -> dict:
    """Load configuration from ~/.msp/config.toml."""
    if not CONFIG_FILE.exists():
        return {}
    
    try:
        config = {}
        content = CONFIG_FILE.read_text()
        
        current_section = None
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1]
                config[current_section] = {}
            elif "=" in line and current_section:
                key, value = line.split("=", 1)
                config[current_section][key.strip()] = value.strip().strip('"')
        
        return config
    except Exception:
        return {}


def save_config(config: dict) -> bool:
    """Save configuration to ~/.msp/config.toml."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        lines = ["# msp Configuration"]
        
        for section, values in config.items():
            lines.append(f"\n[{section}]")
            for key, value in values.items():
                if isinstance(value, str):
                    lines.append(f'{key} = "{value}"')
                else:
                    lines.append(f"{key} = {value}")
        
        CONFIG_FILE.write_text("\n".join(lines))
        return True
    except Exception:
        return False


def main():
    """Test error handling."""
    print(format_error(ToolNotFoundError("nmap")))
    print()
    print(f"nmap available: {check_tool('nmap')}")
    print(f"config dir exists: {CONFIG_DIR.exists()}")


if __name__ == "__main__":
    main()