"""Shared command execution helpers for local CLI operations."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from typing import Mapping, Optional, Sequence, Union


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
