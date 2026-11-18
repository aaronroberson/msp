"""Tests for msp doctor: the single health surface consuming scan bundles.

doctor() consumes ~/.msp/scans/latest.json (written by `msp scan`) instead
of running checks inline. It must render every check's outcome — healthy
(✓), skipped (–), and issues with severity — offer a scan when no results
exist, and note staleness.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import src.deps as deps_mod
from src.deps import DependencyManager, DepStatus


@pytest.fixture
def dm(tmp_path, monkeypatch):
    """DependencyManager isolated to tmp home."""
    return DependencyManager(deps_file=str(tmp_path / "none.json"))


def make_check(domain, name, status, title="", detail="", fixable=False, fix_cmd=""):
    return {"domain": domain, "name": name, "status": status,
            "title": title or name, "detail": detail,
            "fixable": fixable, "fix_cmd": fix_cmd}


def test_doctor_renders_bundle_sections(dm, capsys, tmp_path, monkeypatch):
    (tmp_path / ".zshrc").write_text("export PATH=/usr/bin:$PATH\n")
    dm._run_cmd = lambda cmd, shell=True: (True, "0.1 total\n")
    monkeypatch.setattr(dm, "deps", {"brew": {"required": True}})
    monkeypatch.setattr(dm, "check_all", lambda: {"brew": DepStatus.INSTALLED})
    bundle = {
        "schema": "1.0",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": "quick",
        "checks": [
            make_check("shell", "Zsh history", "ok", detail="8,896 lines, text format OK"),
            make_check("system", "Disk space", "ok", detail="62% used, 400GB free"),
            make_check("permissions", "Protected: ~/.ssh", "n/a",
                       detail="SSH config directory not present — skipped"),
            make_check("shell", "Zsh startup time", "high", title="Startup: 900ms (target <150ms)",
                       detail="Interactive zsh takes 900ms.", fixable=True, fix_cmd="nvm_lazy"),
        ],
    }
    import src.scanner as scanner_mod
    monkeypatch.setattr(scanner_mod, "read_latest_scan", lambda: bundle)

    assert dm.doctor(verbose=False) is False  # issue present
    out = capsys.readouterr().out
    assert "Shell:" in out and "System:" in out and "Protected files:" in out
    assert "✓ Zsh history — 8,896 lines, text format OK" in out
    assert "✓ Disk space — 62% used, 400GB free" in out
    assert "– Protected: ~/.ssh" in out
    assert "HIGH Startup: 900ms (target <150ms)" in out
    assert "(fix: msp doctor fix)" in out
    assert "scan from" in out  # source provenance line


def test_doctor_prompts_when_no_scan(dm, capsys, tmp_path, monkeypatch):
    """No bundle + non-TTY stdin → hint printed, no exception."""
    (tmp_path / ".zshrc").write_text("export PATH=/usr/bin:$PATH\n")
    dm._run_cmd = lambda cmd, shell=True: (True, "0.1 total\n")
    monkeypatch.setattr(dm, "deps", {})
    monkeypatch.setattr(dm, "check_all", lambda: {})
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    import src.scanner as scanner_mod
    monkeypatch.setattr(scanner_mod, "read_latest_scan", lambda: None)

    assert dm.doctor(verbose=False) is True  # no data → not a failure
    out = capsys.readouterr().out
    assert "No scan results yet" in out
    assert "msp scan quick" in out


def test_doctor_notes_stale_bundle(dm, capsys, tmp_path, monkeypatch):
    (tmp_path / ".zshrc").write_text("export PATH=/usr/bin:$PATH\n")
    dm._run_cmd = lambda cmd, shell=True: (True, "0.1 total\n")
    monkeypatch.setattr(dm, "deps", {})
    monkeypatch.setattr(dm, "check_all", lambda: {})
    bundle = {
        "schema": "1.0",
        "timestamp": (datetime.now() - timedelta(days=12)).isoformat(timespec="seconds"),
        "mode": "quick",
        "checks": [make_check("shell", "Zsh history", "ok", detail="10 lines, text format OK")],
    }
    import src.scanner as scanner_mod
    monkeypatch.setattr(scanner_mod, "read_latest_scan", lambda: bundle)

    dm.doctor(verbose=False)
    out = capsys.readouterr().out
    assert "12 days old" in out and "msp scan quick" in out


def test_doctor_deps_summary_counts(dm, capsys, tmp_path, monkeypatch):
    (tmp_path / ".zshrc").write_text("export PATH=/usr/bin:$PATH\n")
    dm._run_cmd = lambda cmd, shell=True: (True, "0.1 total\n")
    monkeypatch.setattr(dm, "deps", {"brew": {"required": True}, "gh": {"required": False}})
    monkeypatch.setattr(dm, "check_all", lambda: {"brew": DepStatus.INSTALLED, "gh": DepStatus.MISSING})
    import src.scanner as scanner_mod
    monkeypatch.setattr(scanner_mod, "read_latest_scan", lambda: None)
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())

    assert dm.doctor(verbose=False) is True
    out = capsys.readouterr().out
    assert "All 1 required dependencies installed (checked 2)." in out
    assert "Optional, not installed (1): gh" in out
