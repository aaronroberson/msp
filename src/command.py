"""Shared command execution helpers for local CLI operations."""

from __future__ import annotations

import logging
import os
import re
import select
import shlex
import subprocess
import sys
import termios
import time
import tty
from dataclasses import asdict, dataclass
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple, Union

logger = logging.getLogger("msp")


def setup_logging(verbose: bool = False) -> None:
    """Configure the msp package logger."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

try:
    import argcomplete
    HAS_ARGCOMPLETE = True
except ImportError:
    HAS_ARGCOMPLETE = False


def setup_completion(parser: Any) -> None:
    """Enable argcomplete shell completion for *parser* when available."""
    if HAS_ARGCOMPLETE:
        try:
            argcomplete.autocomplete(parser)
        except Exception:
            pass


def suggest_command(cmd: str, commands: Sequence[str]) -> None:
    """Print a suggestion when an unknown command is entered."""
    from difflib import get_close_matches
    matches = [m for m in get_close_matches(cmd, commands, n=3, cutoff=0.4) if m != cmd]
    if matches:
        print(f"Unknown command: {cmd}")
        print(f"Did you mean? {', '.join(matches)}")
    else:
        print(f"Unknown command: {cmd}")
    print("Run 'msp --help' for available commands.")


Command = Union[str, Sequence[str]]

IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_RE = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{0,4}\b")
REDACTION = "[REDACTED]"


@dataclass(frozen=True)
class CommandResult:
    """JSON-serializable result for a local command invocation."""

    command: Union[str, list[str]]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    dry_run: bool = False
    error: Optional[str] = None
    duration: float = 0.0

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None

    @property
    def output(self) -> str:
        return self.stdout + self.stderr

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["success"] = self.success
        payload["output"] = self.output
        return payload


def run_command(
    command: Command,
    *,
    timeout: Optional[float] = 60,
    sudo: bool = False,
    dry_run: bool = False,
    shell: bool = False,
    cwd: Optional[Union[str, os.PathLike[str]]] = None,
    env: Optional[Mapping[str, str]] = None,
    sensitive_values: Optional[Sequence[str]] = None,
    redact_ips: bool = True,
) -> CommandResult:
    """Run a local command and return a normalized, redacted result.

    The default path uses ``shell=False`` and expects an argv sequence. Passing
    ``shell=True`` accepts existing command strings during migration.
    """

    normalized = _normalize_command(command, shell=shell, sudo=sudo)
    display_command = _redact_value(
        _display_command(normalized, shell=shell),
        sensitive_values=sensitive_values,
        redact_ips=redact_ips,
    )

    if dry_run:
        return CommandResult(
            command=display_command,
            returncode=0,
            dry_run=True,
        )

    start = time.monotonic()
    try:
        completed = subprocess.run(
            normalized,
            shell=shell,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        duration = time.monotonic() - start
        return CommandResult(
            command=display_command,
            returncode=completed.returncode,
            stdout=_redact_value(
                completed.stdout,
                sensitive_values=sensitive_values,
                redact_ips=redact_ips,
            ),
            stderr=_redact_value(
                completed.stderr,
                sensitive_values=sensitive_values,
                redact_ips=redact_ips,
            ),
            duration=duration,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        return CommandResult(
            command=display_command,
            returncode=124,
            stdout=_redact_value(
                _decode_output(exc.stdout),
                sensitive_values=sensitive_values,
                redact_ips=redact_ips,
            ),
            stderr=_redact_value(
                _decode_output(exc.stderr),
                sensitive_values=sensitive_values,
                redact_ips=redact_ips,
            ),
            timed_out=True,
            error="Command timed out",
            duration=duration,
        )
    except FileNotFoundError as exc:
        return _error_result(
            display_command,
            127,
            exc,
            sensitive_values=sensitive_values,
            redact_ips=redact_ips,
        )
    except OSError as exc:
        return _error_result(
            display_command,
            1,
            exc,
            sensitive_values=sensitive_values,
            redact_ips=redact_ips,
        )


def list_command(command: Sequence[str], **kwargs) -> CommandResult:
    """Run an argv-list command with ``shell=False``."""

    return run_command(list(command), shell=False, **kwargs)


def _normalize_command(command: Command, *, shell: bool, sudo: bool) -> Command:
    if shell:
        command_text = command if isinstance(command, str) else shlex.join(command)
        return f"sudo {command_text}" if sudo else command_text

    if isinstance(command, str):
        argv = shlex.split(command)
    else:
        argv = list(command)

    return ["sudo", *argv] if sudo else argv


def _display_command(command: Command, *, shell: bool) -> Union[str, list[str]]:
    if shell:
        return str(command)
    if isinstance(command, str):
        return shlex.split(command)
    return list(command)


def _redact_value(
    value: Union[str, list[str]],
    *,
    sensitive_values: Optional[Sequence[str]],
    redact_ips: bool,
) -> Union[str, list[str]]:
    if isinstance(value, list):
        return [
            _redact_text(item, sensitive_values=sensitive_values, redact_ips=redact_ips)
            for item in value
        ]
    return _redact_text(value, sensitive_values=sensitive_values, redact_ips=redact_ips)


def _redact_text(
    text: str,
    *,
    sensitive_values: Optional[Sequence[str]],
    redact_ips: bool,
) -> str:
    redacted = text
    for sensitive in sensitive_values or ():
        if sensitive:
            redacted = redacted.replace(sensitive, REDACTION)
    if redact_ips:
        redacted = IPV4_RE.sub(REDACTION, redacted)
        redacted = IPV6_RE.sub(REDACTION, redacted)
    return redacted


def _decode_output(value: Optional[Union[str, bytes]]) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _error_result(
    display_command: Union[str, list[str]],
    returncode: int,
    exc: OSError,
    *,
    sensitive_values: Optional[Sequence[str]],
    redact_ips: bool,
) -> CommandResult:
    return CommandResult(
        command=display_command,
        returncode=returncode,
        stderr=_redact_text(
            str(exc),
            sensitive_values=sensitive_values,
            redact_ips=redact_ips,
        ),
        error=exc.__class__.__name__,
    )


# ── Interactive terminal UI ──────────────────────────────────────────────

Item = Tuple[str, str, Optional[str]]  # (value, label, description)


def interactive_select(
    items: List[Item],
    *,
    title: str = "",
    multi: bool = False,
) -> Optional[List[str]]:
    """Arrow-key navigable, Tab-toggle terminal selector.

    Args:
        items: list of (value, label, description) tuples.
        title: header displayed above the list.
        multi: if True, Tab toggles selection and Enter confirms all
               selected. If False, Enter immediately selects the item
               under the cursor.

    Returns:
        List of selected values, or None if cancelled.
    """
    if not items:
        return None

    n = len(items)
    cursor = 0
    selected: set[int] = set()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    HIDE = "\033[?25l"
    SHOW = "\033[?25h"
    CLR = "\033[2K"
    BOLD = "\033[1m"
    RST = "\033[0m"
    CYN = "\033[36m"
    GRN = "\033[32m"
    GRAY = "\033[90m"

    def render() -> str:
        lines: List[str] = []
        if title:
            lines.append(f"  {BOLD}{title}{RST}")
        help_text = "(↑↓ navigate, ↵ select, q quit)"
        if multi:
            help_text = "(↑↓ navigate, ⭾ toggle, ↵ execute, q quit)"
        lines.append(f"  {GRAY}{help_text}{RST}\n")
        for i, item in enumerate(items):
            _, label, desc = item
            prefix = "▸" if i == cursor else " "
            if multi:
                check = "☑" if i in selected else "☐"
                display = f" {prefix} {CYN if i == cursor else RST}{check} {label}{RST}"
            else:
                display = f" {prefix} {CYN if i == cursor else RST}{label}{RST}"
            if desc and i == cursor:
                display += f"  {GRAY}{desc}{RST}"
            lines.append(display)
        lines.append("")
        return "\n".join(lines)

    def count() -> int:
        return n + 3  # title + help + blank + n items

    try:
        tty.setraw(fd)
        sys.stdout.write(HIDE)
        sys.stdout.flush()

        while True:
            rendered = render()
            sys.stdout.write(rendered)
            sys.stdout.flush()

            raw = b""
            while True:
                b = os.read(fd, 1)
                raw += b
                if b == b"\x1b":
                    raw += os.read(fd, 2)
                break

            key = raw.decode("utf-8", errors="replace")

            sys.stdout.write(f"\033[{count()}A")
            for _ in range(count()):
                sys.stdout.write(CLR)
                sys.stdout.write("\033[B" if _ < count() - 1 else "")
            sys.stdout.write(f"\033[{count()}A")

            if key == "\r" or key == "\n":
                if multi:
                    if selected:
                        break
                else:
                    selected.add(cursor)
                    break
            elif key == "q":
                selected.clear()
                break
            elif key == "\t" or key == " ":
                if multi:
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
        sys.stdout.write(SHOW)
        for _ in range(count()):
            sys.stdout.write(CLR)
            sys.stdout.write("\n")
        sys.stdout.write(f"\033[{count()}A")
        sys.stdout.flush()

    return [items[i][0] for i in sorted(selected)] if selected else None


def interactive_menu(
    actions: List[Tuple[str, str, str]],
    *,
    title: str = "",
    back_label: str = "Back",
) -> Optional[str]:
    """Convenience wrapper around *interactive_select* for menu navigation.

    Args:
        actions: list of (value, label, description) tuples.
        title: header text.
        back_label: label for the implicit back/quit option.

    Returns:
        Selected value string, or None if user hit back/quit.
    """
    menu_items: List[Item] = []
    for val, label, desc in actions:
        menu_items.append((val, label, desc))

    result = interactive_select(menu_items, title=title, multi=False)
    if result is None:
        return None
    return result[0] if result else None
