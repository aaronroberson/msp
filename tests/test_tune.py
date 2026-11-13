"""Tests for msp tune backup/restore/cleanup of destructive operations.

Destructive `msp tune fix` operations (~/.zshrc rewrite, zsh history trim
and repair) must back up modified files to ~/.msp/backups first, restore
every backup on failure (all-or-nothing), and keep backups for user
confirmation/cleanup on success.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.tune as tune
from src.tune import Finding, Tuner


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Isolated home: .zshrc, an oversized .zsh_history, and module paths."""
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text("source $HOME/.oh-my-zsh/oh-my-zsh.sh\n"
                     "eval \"$(brew shellenv)\"\n"
                     "export PATH=/usr/bin:$PATH\n")
    history = tmp_path / ".zsh_history"
    history.write_text("\n".join(f"cmd {i}" for i in range(10001)) + "\n")
    monkeypatch.setattr(tune, "HOME", tmp_path)
    monkeypatch.setattr(tune, "ZSHRC", zshrc)
    monkeypatch.setattr(tune, "ZSH_HISTORY", history)
    monkeypatch.setattr(tune, "BACKUP_DIR", tmp_path / ".msp" / "backups")
    return {"zshrc": zshrc, "history": history, "backup_dir": tmp_path / ".msp" / "backups"}


def _stub_check(findings: list[Finding]):
    def check(self: Tuner, json_output: bool = False) -> list[Finding]:
        self.findings = findings
        return findings
    return check


def test_make_backup_creates_timestamped_copy(home, monkeypatch):
    backup_dir = home["backup_dir"]
    t = Tuner()
    backup = t._make_backup(home["history"])
    assert backup.parent == backup_dir
    assert backup.name.startswith(".zsh_history.") and backup.name.endswith(".bak")
    assert backup.read_text() == home["history"].read_text()
    assert (home["history"], backup) in t.backups


def test_fix_history_trim_backs_up_and_trims(home, monkeypatch):
    monkeypatch.setattr(
        tune.Tuner, "check",
        _stub_check([Finding(domain="zsh", severity="medium",
                             title="History: 10001 lines",
                             description="Large history slows compinit and search.",
                             fixable=True, fix_cmd="history_trim")]))
    t = Tuner()
    results = t.fix(json_output=False)  # non-TTY: backups kept, paths printed
    trimmed = home["history"].read_text().splitlines()
    assert len(trimmed) == 10000
    assert results[0]["status"] == "applied"
    backup = Path(results[0]["backup"])
    assert backup.exists()
    assert backup.read_text().splitlines()[0] == "cmd 0"
    assert t.backups == []  # recorded then cleared by cleanup prompt


def test_fix_history_trim_dry_run_touches_nothing(home, monkeypatch):
    before = home["history"].read_text()
    zshrc_before = home["zshrc"].read_text()
    monkeypatch.setattr(
        tune.Tuner, "check",
        _stub_check([Finding(domain="zsh", severity="medium", title="History: 10001 lines",
                             description="d", fixable=True, fix_cmd="history_trim")]))
    results = Tuner().fix(dry_run=True, json_output=False)
    assert results[0]["status"] == "dry-run"
    assert home["history"].read_text() == before
    assert home["zshrc"].read_text() == zshrc_before
    assert not home["backup_dir"].exists()


def test_failure_rolls_back_all_changes(home, monkeypatch, capsys):
    """history_trim applied, then a later handler fails -> history restored."""
    history = home["history"]
    before = history.read_text()
    monkeypatch.setattr(
        tune.Tuner, "check",
        _stub_check([
            Finding(domain="zsh", severity="medium", title="History: 10001 lines",
                    description="d", fixable=True, fix_cmd="history_trim"),
            Finding(domain="zsh", severity="medium", title="Auto-suggestions blocking prompt",
                    description="d", fixable=True, fix_cmd="async"),
        ]))
    def broken_async(self, lines, dry):
        raise RuntimeError("injected failure")
    monkeypatch.setattr(Tuner, "_fix_async", broken_async)
    results = Tuner().fix(json_output=False)
    failed = [r for r in results if r.get("status") == "failed"]
    assert failed and "injected failure" in failed[0]["reason"]
    assert history.read_text() == before  # restored from backup
    backups = list(home["backup_dir"].glob("*"))
    assert backups == []  # backup removed after successful restore


def test_write_failure_restores_all(home, monkeypatch):
    """zshrc write fails after a successful history fix -> everything restored."""
    history = home["history"]
    zshrc = home["zshrc"]
    history_before = history.read_text()
    zshrc_before = zshrc.read_text()
    monkeypatch.setattr(
        tune.Tuner, "check",
        _stub_check([
            Finding(domain="zsh", severity="medium", title="History: 10001 lines",
                    description="d", fixable=True, fix_cmd="history_trim"),
            Finding(domain="zsh", severity="medium", title="brew shellenv runs every time",
                    description="d", fixable=True, fix_cmd="brew_shellenv"),
        ]))
    def broken_write(self, lines):
        return False
    monkeypatch.setattr(Tuner, "_write_zshrc", broken_write)
    results = Tuner().fix(json_output=False)
    assert any(r.get("status") == "failed" for r in results)
    assert history.read_text() == history_before
    assert zshrc.read_text() == zshrc_before
    assert list(home["backup_dir"].glob("*")) == []


def test_zshrc_fix_backs_up_before_rewrite(home, monkeypatch):
    zshrc = home["zshrc"]
    zshrc_before = zshrc.read_text()
    monkeypatch.setattr(
        tune.Tuner, "check",
        _stub_check([Finding(domain="zsh", severity="medium", title="brew shellenv runs every time",
                             description="d", fixable=True, fix_cmd="brew_shellenv")]))
    t = Tuner()
    results = t.fix(json_output=False)
    assert results[0]["status"] == "applied"
    write = [r for r in results if r.get("fix") == "zshrc_write"][0]
    assert write["status"] == "applied"
    backup = Path(write["backup"])
    assert backup.exists()
    assert backup.read_text() == zshrc_before  # pre-change snapshot
    assert "HOMEBREW_PREFIX" in zshrc.read_text()


def test_fix_nvm_only_touches_nvm_source_line(monkeypatch):
    """Regression: the match guard must not replace an unrelated first line."""
    lines = ["export PATH=/usr/bin:$PATH\n", "source ~/.nvm/nvm.sh\n"]
    t = Tuner()
    result = t._fix_nvm(lines, dry=False)
    assert result["status"] == "applied"
    assert lines[0] == "export PATH=/usr/bin:$PATH\n"
    assert "nvm()" in lines[1]


def test_cleanup_backups_delete(home, monkeypatch):
    t = Tuner()
    b1 = t._make_backup(home["history"])
    b2 = t._make_backup(home["zshrc"])
    assert b1.exists() and b2.exists()
    removed = t._cleanup_backups(delete=True)
    assert sorted(removed) == sorted([str(b1), str(b2)])
    assert not b1.exists() and not b2.exists()
    assert t.backups == []


def test_json_output_includes_backup_paths(home, monkeypatch, capsys):
    monkeypatch.setattr(
        tune.Tuner, "check",
        _stub_check([Finding(domain="zsh", severity="medium", title="History: 10001 lines",
                             description="d", fixable=True, fix_cmd="history_trim")]))
    results = Tuner().fix(json_output=True)
    out = capsys.readouterr().out
    lines = out.splitlines()
    idx = next(i for i, l in enumerate(lines) if l.strip() == "[")  # json.dumps list start
    data = json.loads("\n".join(lines[idx:]))
    assert data[0]["status"] == "applied"
    assert Path(data[0]["backup"]).exists()
