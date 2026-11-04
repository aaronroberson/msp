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
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple, Union, cast

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
            stdout=cast(str, _redact_value(
                completed.stdout,
                sensitive_values=sensitive_values,
                redact_ips=redact_ips,
            )),
            stderr=cast(str, _redact_value(
                completed.stderr,
                sensitive_values=sensitive_values,
                redact_ips=redact_ips,
            )),
            duration=duration,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - start
        return CommandResult(
            command=display_command,
            returncode=124,
            stdout=cast(str, _redact_value(
                _decode_output(exc.stdout),
                sensitive_values=sensitive_values,
                redact_ips=redact_ips,
            )),
            stderr=cast(str, _redact_value(
                _decode_output(exc.stderr),
                sensitive_values=sensitive_values,
                redact_ips=redact_ips,
            )),
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


def pause_for_enter(msg: str = "\nPress Enter to continue...") -> None:
    """Wait for Enter. Ctrl-C/Ctrl-D/EOF return quietly, not a traceback."""
    try:
        input(msg)
    except (KeyboardInterrupt, EOFError):
        print()


def _read_terminal_key(fd: int) -> Optional[str]:
    """Read one logical keypress from a raw-mode tty.

    Blocks until a key (or EOF) arrives. Maps escape sequences to logical
    names. Bare ESC stops translating after ``_ESCAPE_TIMEOUT`` seconds so a
    lone Escape press cannot stall the stream.

    Returns one of: printable text, "UP", "DOWN", "ESC" (bare escape),
    "IGN" (swallowed escape sequence or unknown byte), "CC" (Ctrl-C),
    "CD" (Ctrl-D), or None on EOF.
    """
    _ESCAPE_TIMEOUT = 0.03
    while True:
        try:
            data = os.read(fd, 1)
        except OSError:
            return None
        if not data:
            return None  # EOF
        if data == b"\x1b":
            # Bare ESC (nothing follows quickly) has cancel semantics. A
            # recognized arrow sequence maps to a navigation key. Any other
            # sequence is swallowed ("IGN") so terminals with extra escapes
            # (e.g. Apple Terminal's ESC O D) can never cancel the menu.
            tail = b""
            for _ in range(2):
                ready, _, _ = select.select([fd], [], [], _ESCAPE_TIMEOUT)
                if not ready:
                    break
                tail += os.read(fd, 1)
            if not tail:
                return "ESC"
            if tail == b"[A":
                return "UP"
            if tail == b"[B":
                return "DOWN"
            return "IGN"
        if data == b"\x03":
            return "CC"
        if data == b"\x04":
            return "CD"
        if data == b"\x7f":  # backspace: ignore
            continue
        return data.decode("utf-8", errors="replace")


def interactive_select(
    items: List[Item],
    *,
    title: str = "",
    multi: bool = False,
) -> Optional[List[str]]:
    """Arrow-key navigable, Space-toggle terminal selector.

    Keys: ↑/↓ navigate, Space (or Tab) toggle in multi-select, ↵ confirm,
    ``q``/Esc/Ctrl-C/Ctrl-D cancel. Unknown keys are ignored silently.

    Rendering is raw-mode-safe: every line ends with CRLF and the cursor is
    always parked one row below the panel between paints, so repaints never
    creep up or stair-step across the screen.

    Args:
        items: list of (value, label, description) tuples.
        title: header displayed above the list.
        multi: if True, Space/Tab toggle selection and Enter confirms all
               selected items (defaulting to the item under the cursor if
               none are toggled). If False, Enter immediately selects the
               item under the cursor.

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

    HIDE = "\x1b[?25l"
    SHOW = "\x1b[?25h"
    CLR = "\x1b[2K"
    BOLD = "\x1b[1m"
    RST = "\x1b[0m"
    CYN = "\x1b[36m"
    GRAY = "\x1b[90m"

    if title:
        layout_rows = 3 + n  # title + help + spacer + items
    else:
        layout_rows = 2 + n  # help + spacer + items

    def render() -> str:
        """Build the panel; every line is CRLF-terminated for raw mode."""
        lines: List[str] = []
        if title:
            lines.append(f"  {BOLD}{title}{RST}")
        if multi:
            help_text = "(↑↓ navigate, space toggle, ↵ execute, q/Esc cancel)"
        else:
            help_text = "(↑↓ navigate, ↵ select, q/Esc cancel)"
        lines.append(f"  {GRAY}{help_text}{RST}")
        lines.append("")  # spacer between help and items
        for i, item in enumerate(items):
            _, label, desc = item
            prefix = "▸" if i == cursor else " "
            if multi:
                check = "☑" if i in selected else "☐"
                display = f"  {CYN if i == cursor else RST}{check} {label}{RST}"
            else:
                display = f" {prefix} {CYN if i == cursor else RST}{label}{RST}"
            if desc and i == cursor:
                display += f"  {GRAY}{desc}{RST}"
            lines.append(display)
        return "\r\n".join(lines) + "\r\n"

    def clear_panel() -> None:
        """Erase the rendered panel.

        Invariant: on entry and on exit the cursor rests exactly one row
        below the panel. Steps use LF+CR (not cursor-down) so a panel whose
        bottom row sits on the last screen row scrolls instead of sticking,
        which is what keeps repaints anchored.
        """
        out = [f"\x1b[{layout_rows}A"]  # rise to the panel's top row
        for _ in range(layout_rows):
            out.append(CLR)
            out.append("\n\r")  # step down; LF scrolls anchor-safely
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    try:
        tty.setraw(fd)
    except termios.error:
        # Not an interactive tty (pipe/file): fall back to numbered prompt.
        for i, item in enumerate(items, start=1):
            print(f"  {i}. {item[1]}")
        try:
            while True:
                answer = input("Number (q to cancel): ").strip()
                if answer in ("q", "esc", ""):
                    return None
                if answer.isdigit() and 1 <= int(answer) <= n:
                    picked = items[int(answer) - 1][0]
                    return [picked]
                print("Invalid choice")
        except (EOFError, KeyboardInterrupt):
            return None
    try:
        painted = False
        sys.stdout.write(HIDE)
        sys.stdout.flush()

        while True:
            sys.stdout.write(render())
            sys.stdout.flush()
            painted = True

            key = _read_terminal_key(fd)

            if key in (None, "ESC", "CC", "CD", "q", "Q"):
                return None

            if key in ("\r", "\n"):
                if multi:
                    if not selected:
                        selected.add(cursor)  # Enter with nothing toggled
                    break
                selected.add(cursor)
                break

            if key in (" ", "\t") and multi:
                if cursor in selected:
                    selected.remove(cursor)
                else:
                    selected.add(cursor)
                clear_panel()

            elif key == "UP" and cursor > 0:
                cursor -= 1
                clear_panel()

            elif key == "DOWN" and cursor < n - 1:
                cursor += 1
                clear_panel()

            # Any other key: silent no-op, never repaint.
    finally:
        if painted:
            clear_panel()
        # TCSANOW, not TCSADRAIN: the DRAIN variants block waiting for the
        # terminal output queue to drain, which can deadlock on macOS ptys.
        termios.tcsetattr(fd, termios.TCSANOW, old)
        sys.stdout.write(SHOW)
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
