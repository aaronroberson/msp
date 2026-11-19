"""main.py forwards module arguments verbatim and in order."""
import contextlib
import io
import sys

import pytest

import src.main as main_module


@pytest.fixture
def forwarded(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "run_command", lambda module, command, args, global_args=None: calls.append((module, command, args)))

    def run(*argv):
        calls.clear()
        monkeypatch.setattr(sys, "argv", ["msp", *argv])
        with contextlib.redirect_stdout(io.StringIO()):
            main_module.main()
        return calls[-1]

    return run


@pytest.mark.parametrize("argv, expected", [
    # option/value pairs used to be split when no positional preceded them
    (("interrogate", "--output", "f.json"), ("facts", "", ["--output", "f.json"])),
    (("audit", "f.json", "--format", "json"), ("rules", "", ["f.json", "--format", "json"])),
    (("net", "inspect", "--pid", "123"), ("network", "inspect", ["--pid", "123"])),
    # global flags before the command are not forwarded as module args
    (("--json", "tcc", "list", "--service", "Camera"), ("tcc", "list", ["--service", "Camera"])),
    # a module option sharing a global name reaches the module
    (("reason", "--provider", "local", "--facts", "f.json"), ("llm", "", ["--provider", "local", "--facts", "f.json"])),
    # main-only flags are dropped
    (("--redact-ips", "list", "--sort", "name"), ("privacy_settings", "list", ["--sort", "name"])),
])
def test_module_arguments_are_forwarded_verbatim(forwarded, argv, expected):
    assert forwarded(*argv) == expected


def test_ask_still_validates_its_provider(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["msp", "ask", "--provider", "nope", "hello"])
    with contextlib.redirect_stderr(io.StringIO()), pytest.raises(SystemExit) as exc:
        main_module.main()
    assert exc.value.code == 2
