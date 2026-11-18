"""Tests for the canonical scan bundle: writers, readers, and collectors.

`msp scan` is the collector; `msp doctor` is the consumer. The bundle
(~/.msp/scans/latest.json) must carry one entry per check with status
ok / n/a / issue-severity, including healthy checks.
"""

from __future__ import annotations

import json

import pytest

import src.scanner as scanner_mod
from src.scanner import (
    SecurityScanner,
    fix_permission_issues,
    read_latest_scan,
    scan_bundle_path,
    write_scan_bundle,
)


@pytest.fixture
def scan_home(tmp_path, monkeypatch):
    monkeypatch.setattr(scanner_mod.Path, "home", lambda: tmp_path)
    return tmp_path


def test_bundle_roundtrip(scan_home):
    checks = [
        {"domain": "shell", "name": "Zsh history", "status": "ok",
         "title": "Zsh history", "detail": "10 lines", "fixable": False, "fix_cmd": ""},
    ]
    path = write_scan_bundle("quick", checks)
    assert path == scan_home / ".msp" / "scans" / "latest.json"
    bundle = read_latest_scan()
    assert bundle is not None
    assert bundle["schema"] == "2.0"
    assert bundle["mode"] == "quick"
    assert bundle["checks"] == checks


def test_read_latest_scan_handles_missing_and_corrupt(scan_home):
    assert read_latest_scan() is None  # missing
    scan_bundle_path().parent.mkdir(parents=True, exist_ok=True)
    scan_bundle_path().write_text("{not json")
    assert read_latest_scan() is None  # corrupt
    scan_bundle_path().write_text(json.dumps({"schema": "1.0", "timestamp": "x"}))
    assert read_latest_scan() is None  # no checks key


def test_permissions_check_produces_canonical_entries(scan_home):
    ssh = scan_home / ".ssh"
    ssh.mkdir()
    (ssh / "id_rsa").write_text("fake key")
    ssh.chmod(0o777)          # dir too open
    (ssh / "id_rsa").chmod(0o644)  # key too open

    s = SecurityScanner()
    s._check_file_permissions()

    by_name = {c["name"]: c for c in s.permission_results}
    dir_entry = by_name["Protected: ~/.ssh"]
    assert dir_entry["status"] == "high"
    assert "world-writable" in dir_entry["title"]
    assert "fix with" in dir_entry["detail"]
    key_entry = by_name["Protected: ~/.ssh/id_rsa"]
    assert key_entry["status"] == "medium"
    assert key_entry["fixable"] is True and "chmod" in key_entry["fix_cmd"]
    # security findings mirror the canonical entries
    items = [f.item for f in s.findings]
    assert any("Over-permissive: ~/.ssh/id_rsa" in i for i in items)
    assert any("World-writable: ~/.ssh" in i for i in items)


def test_permissions_absent_paths_are_skipped(scan_home):
    s = SecurityScanner()
    s._check_file_permissions()
    na = [c for c in s.permission_results if c["status"] == "n/a"]
    assert len(na) >= 8  # ssh keys, gnupg, aws, netrc, kube, ...
    assert all("not present" in c["detail"] for c in na)


def test_collect_health_checks_composes_tuner_and_permissions(scan_home, monkeypatch):
    # healthy tmp machine: no .zshrc/.zsh_history → shell checks n/a
    stubbed = {
        "df -g / 2>/dev/null | tail -1": (0, "Filesystem 50 200 100 50% 1\n"),
        "memory_pressure 2>/dev/null | head -5": (0, "System-wide memory free percentage: 55"),
        "brew cleanup --dry-run 2>&1": (1, ""),
    }
    def fake_run(cmd, timeout=30, shell=True):
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        for prefix, res in stubbed.items():
            if cmd.startswith(prefix.split(" 2>/dev/null")[0].split(" 2>&1")[0]):
                return res
        return 0, ""
    import src.tune as tune_mod
    monkeypatch.setattr(tune_mod, "_run", fake_run)

    from src.scanner import collect_health_checks
    checks = collect_health_checks()
    domains = {c["domain"] for c in checks}
    assert {"shell", "system", "permissions"} <= domains
    statuses = {c["status"] for c in checks}
    assert "n/a" in statuses          # absent user files
    disk = next(c for c in checks if c["name"] == "Disk space")
    assert disk["status"] == "ok" and "50%" in disk["detail"]
    perms = [c for c in checks if c["domain"] == "permissions"]
    assert all(c["name"].startswith("Protected:") for c in perms)


def test_fix_permission_issues_applies_chmod(scan_home):
    target = scan_home / ".zsh_history"
    target.write_text("history")
    target.chmod(0o644)
    write_scan_bundle("quick", [{
        "domain": "permissions", "name": "Protected: ~/.zsh_history",
        "status": "medium", "title": "over-permissive", "detail": "",
        "fixable": True, "fix_cmd": f"chmod 600 {target}",
    }])

    # dry run previews without changing
    results = fix_permission_issues(dry=True)
    assert results == [("Protected: ~/.zsh_history", True, "would fix: 0o644 → 0o600")]
    assert (target.stat().st_mode & 0o777) == 0o644

    # apply, then idempotent re-run
    results = fix_permission_issues(dry=False)
    assert results == [("Protected: ~/.zsh_history", True, "0o644 → 0o600")]
    assert (target.stat().st_mode & 0o777) == 0o600
    assert fix_permission_issues() == [("Protected: ~/.zsh_history", True, "already fixed")]


def test_fix_permission_issues_no_bundle(scan_home):
    assert fix_permission_issues() == []
