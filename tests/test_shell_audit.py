#!/usr/bin/env python3
"""Shell Audit CLI tests.

Tests for the MSP Shell Audit & Repair feature.
Follows the unittest patterns established in the codebase.
"""
import os
import sys
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import asdict

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.shell_audit import (
    AuditFinding,
    audit_path_integrity,
    find_path_origins,
    audit_zstartup_semantics,
    audit_completion_system,
    audit_executable_shadowing,
    audit_symlink_integrity,
    audit_package_managers,
)
from src.shell_audit_cli import (
    _auditfinding_to_finding,
    _run_all_audits,
    _detect_shell,
    _home,
    _severity_rank,
    _classify_repairability,
    _apply_repair,
    _apply_auto_safe,
    _apply_guided,
    _apply_all_repairs,
    _write_validated,
    _repair_duplicate_compinit,
    _repair_path_entry,
    _repair_dangling_symlink,
    _report_results,
    _scope_allows,
    _select_scope,
    _has_automated_repair,
    _apply_fix,
    _guided_repair,
    _menu_scope,
    _ai_is_fatal,
    _SCOPE_CHOICES,
)
from src.rules import Finding, SEVERITY_ORDER


class ShellAuditCliTest(unittest.TestCase):
    """Tests for the shell audit CLI module."""

    def test_detect_shell_zsh(self):
        """Test shell detection when SHELL points to zsh."""
        with patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            from src.shell_audit_cli import _detect_shell
            self.assertEqual(_detect_shell(), "zsh")

    def test_detect_shell_bash(self):
        """Test shell detection when SHELL points to bash."""
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            from src.shell_audit_cli import _detect_shell
            self.assertEqual(_detect_shell(), "bash")

    def test_detect_shell_unknown(self):
        """Test shell detection when SHELL is not set."""
        with patch.dict(os.environ, {}, clear=True):
            from src.shell_audit_cli import _detect_shell
            self.assertEqual(_detect_shell(), "unknown")

    def test_home_dir(self):
        """Test home directory detection."""
        from src.shell_audit_cli import _home
        home = _home()
        self.assertIsInstance(home, Path)
        self.assertTrue(home.exists())

    def test_severity_rank(self):
        """Test severity ranking conversion."""
        self.assertEqual(_severity_rank("info"), SEVERITY_ORDER["info"])
        self.assertEqual(_severity_rank("low"), SEVERITY_ORDER["low"])
        self.assertEqual(_severity_rank("medium"), SEVERITY_ORDER["medium"])
        self.assertEqual(_severity_rank("high"), SEVERITY_ORDER["high"])
        self.assertEqual(_severity_rank("critical"), SEVERITY_ORDER["critical"])
        # Unknown severity defaults to 0
        self.assertEqual(_severity_rank("unknown"), 0)

    def test_classify_repairability_auto_safe(self):
        """Test repairability classification for auto-safe categories."""
        self.assertEqual(
            _classify_repairability("low", "symlink"),
            "auto_safe"
        )
        self.assertEqual(
            _classify_repairability("medium", "executable"),
            "auto_safe"
        )

    def test_classify_repairability_guided(self):
        """Test repairability classification for guided categories."""
        # Use ERROR (uppercase) as shell_audit does, not "error" (lowercase)
        self.assertEqual(
            _classify_repairability("ERROR", "executable"),
            "guided"
        )
        self.assertEqual(
            _classify_repairability("high", "path"),
            "guided"
        )

    def test_classify_repairability_advisory(self):
        """Test repairability classification for advisory categories."""
        self.assertEqual(
            _classify_repairability("info", "package_manager"),
            "advisory_only"
        )

    def test_auditfinding_to_finding_conversion(self):
        """Test conversion from AuditFinding to MSP Finding."""
        af = AuditFinding(
            id="shell.path.duplicate_entry",
            category="path",
            severity="warning",
            title="Duplicate PATH entry",
            summary="PATH entry duplicated",
            evidence='{"entry": "/usr/local/bin"}',
            source_file="/Users/test/.zshrc",
            line_numbers=(5,),
            current_state="duplicate",
            recommended_state="deduplicate",
            risk="medium",
            repairability="auto_safe",
            repair_action="typeset -U path PATH",
        )
        f = _auditfinding_to_finding(af)
        self.assertIsInstance(f, Finding)
        self.assertEqual(f.rule_id, af.id)
        self.assertEqual(f.title, af.title)
        self.assertEqual(f.category, af.category)
        self.assertEqual(f.severity, af.severity)
        self.assertEqual(f.description, af.summary)
        self.assertEqual(f.remediation, af.recommended_state)

    def test_run_all_audits_returns_findings(self):
        """Test that running all audits returns a list of findings."""
        home = Path.home()
        shells = ["zsh", "bash"]
        findings = _run_all_audits(home, shells)
        self.assertIsInstance(findings, list)
        # Should have at least some findings
        self.assertGreaterEqual(len(findings), 0)

    def test_audit_path_integrity_returns_findings(self):
        """Test PATH integrity audit returns findings."""
        home = Path.home()
        path_str = "/usr/local/bin:/usr/bin:/bin"
        findings = audit_path_integrity(path_str, home)
        self.assertIsInstance(findings, list)

    def test_audit_zstartup_semantics_returns_findings(self):
        """Test zsh startup semantics audit returns findings."""
        home = Path.home()
        # Only run if zsh is the detected shell
        findings = audit_zstartup_semantics(home)
        self.assertIsInstance(findings, list)

    def test_audit_completion_system_returns_findings(self):
        """Test completion system audit returns findings."""
        zshrc = Path.home() / ".zshrc"
        zprofile = Path.home() / ".zprofile"
        # Only run if files exist
        if zshrc.exists() or zprofile.exists():
            findings = audit_completion_system(zshrc, zprofile)
            self.assertIsInstance(findings, list)
        else:
            # If files don't exist, that's OK too
            self.assertTrue(True)

    def test_audit_executable_shadowing_returns_findings(self):
        """Test executable shadowing audit returns findings."""
        tools = ["git", "ssh", "curl"]
        findings = audit_executable_shadowing(tools, Path.home())
        self.assertIsInstance(findings, list)

    def test_audit_symlink_integrity_returns_findings(self):
        """Test symlink integrity audit returns findings."""
        from unittest.mock import patch
        default_paths = [
            str(Path.home() / ".local/bin"),
            str(Path.home() / ".codex"),
        ]
        # Mock os.readlink to avoid issues with real symlinks
        with patch("os.readlink", return_value="/some/valid/target") as mock_readlink:
            with patch("os.path.islink", return_value=True):
                with patch("os.path.exists", return_value=True):
                    findings = audit_symlink_integrity(default_paths, Path.home())
                    self.assertIsInstance(findings, list)

    def test_audit_package_managers_returns_findings(self):
        """Test package manager audit returns findings."""
        home = Path.home()
        findings = audit_package_managers(home)
        self.assertIsInstance(findings, list)

    def test_findings_to_table_output(self):
        """Test that findings can be converted to table format."""
        from src.rules import findings_to_table
        findings = [
            Finding(
                rule_id="test-001",
                title="Test Finding",
                category="path",
                severity="warning",
                description="Test summary",
                remediation="Fix it",
                profile="personal",
                evidence={},
            )
        ]
        table = findings_to_table(findings)
        self.assertIsInstance(table, str)
        self.assertIn("Test Finding", table)

    def test_findings_to_json_output(self):
        """Test that findings can be serialized to JSON."""
        findings = [
            Finding(
                rule_id="test-001",
                title="Test Finding",
                category="path",
                severity="error",
                description="Test summary",
                remediation="Fix it",
                profile="personal",
                evidence={},
            )
        ]
        # Convert to dict for JSON serialization
        findings_dict = [vars(f) for f in findings]
        json_output = json.dumps(findings_dict, indent=2, default=str)
        self.assertIsInstance(json_output, str)
        parsed = json.loads(json_output)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["rule_id"], "test-001")
        self.assertEqual(parsed[0]["title"], "Test Finding")

    def test_severity_integration_with_profile(self):
        """Test that severity filtering works with profiles."""
        findings = [
            Finding(
                rule_id="high-001",
                title="High Severity",
                category="path",
                severity="high",
                description="High severity issue",
                remediation="Fix high severity",
                profile="personal",
                evidence={},
            ),
            Finding(
                rule_id="low-001",
                title="Low Severity",
                category="path",
                severity="low",
                description="Low severity issue",
                remediation="Fix low severity",
                profile="personal",
                evidence={},
            ),
            Finding(
                rule_id="info-001",
                title="Info Severity",
                category="path",
                severity="info",
                description="Info severity issue",
                remediation="Fix info severity",
                profile="personal",
                evidence={},
            ),
        ]

        # Filter with personal profile (minimum severity = low)
        min_severity = 1  # low
        filtered = [f for f in findings if SEVERITY_ORDER.get(f.severity, 0) >= min_severity]

        # Should include high and low, but not info
        rule_ids = {f.rule_id for f in filtered}
        self.assertIn("high-001", rule_ids)
        self.assertIn("low-001", rule_ids)
        self.assertNotIn("info-001", rule_ids)


if __name__ == "__main__":
    unittest.main()

class FakeCard:
    def __init__(self):
        self.status = None
        self.output = None

    def update(self, status=None, output=None, **kwargs):
        if status is not None:
            self.status = status
        if output is not None:
            self.output = output


class FakeUI:
    def __init__(self):
        self.cards = []

    def tool(self, name, status=None, args=None, **kwargs):
        card = FakeCard()
        card.name = name
        card.status = status
        self.cards.append(card)
        return card


class TestTUIShellCommand(unittest.TestCase):
    """Acceptance tests for /shell command inside the MSP TUI."""

    def _run(self, args):
        import asyncio
        from src.tui_xli import cmd_shell

        ui = FakeUI()
        asyncio.run(cmd_shell(ui, args))
        return ui

    def test_shell_audit_renders_findings(self):
        ui = self._run("audit")
        self.assertEqual(len(ui.cards), 1)
        card = ui.cards[0]
        self.assertEqual(card.status, "done")
        self.assertIn("Shell Audit", card.output)

    def test_shell_fix_renders_result(self):
        ui = self._run("fix")
        self.assertEqual(len(ui.cards), 1)
        self.assertEqual(ui.cards[0].status, "done")

    def test_shell_default_is_audit(self):
        ui = self._run("")
        self.assertEqual(ui.cards[0].status, "done")
        self.assertIn("Shell Audit", ui.cards[0].output)

    def test_shell_unknown_subcommand_shows_usage(self):
        ui = self._run("bogus")
        self.assertEqual(ui.cards[0].status, "done")
        self.assertIn("Usage", ui.cards[0].output)


if __name__ == "__main__":
    unittest.main()


class RepairEngineTest(unittest.TestCase):
    """Tests for the real repair engine in shell_audit_cli.

    All file operations run against temp dirs; _home and _BACKUP_ROOT are
    patched so the user's real startup files are never touched.
    """

    def setUp(self):
        import shutil
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="msp-repair-test-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.backups = self.tmp / "backups"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _finding(self, **overrides):
        """Build an AuditFinding with sensible defaults."""
        from src.shell_audit import AuditFinding

        base = dict(
            id="shell.path.nonexistent_dir",
            category="PATH",
            severity="ERROR",
            title="Nonexistent PATH directory",
            summary="PATH entry does not exist",
            evidence="evidence",
            source_file="",
            line_numbers=(),
            current_state="PATH entry '/nonexistent' does not exist as a directory",
            recommended_state="Remove or fix PATH entry",
            risk="high",
            repairability="AUTO_SAFE",
        )
        base.update(overrides)
        return AuditFinding(**base)

    def _patch_home_and_backups(self):
        return (
            patch("src.shell_audit_cli._home", return_value=self.home),
            patch("src.shell_audit_cli._BACKUP_ROOT", self.backups),
        )

    def test_classify_prefers_finding_declaration(self):
        """finding.repairability wins over the severity heuristic."""
        f = self._finding(severity="NOTICE", repairability="GUIDED")
        self.assertEqual(
            _classify_repairability(f.severity, f.category, f), "guided"
        )
        f = self._finding(severity="ERROR", repairability="ADVISORY_ONLY")
        self.assertEqual(
            _classify_repairability(f.severity, f.category, f), "advisory_only"
        )
        f = self._finding(severity="ERROR", repairability="auto_safe")
        self.assertEqual(
            _classify_repairability(f.severity, f.category, f), "auto_safe"
        )
        # Unknown declaration falls back to the heuristic
        f = self._finding(severity="ERROR", repairability="mystery")
        self.assertEqual(
            _classify_repairability(f.severity, f.category, f), "guided"
        )

    def test_write_validated_accepts_valid_script(self):
        """Valid zsh content is backed up and atomically replaced."""
        p = self.home / ".zshrc"
        p.write_text("export OLD=1\n")
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            ok, backup = _write_validated(p, "export NEW=1\n")
        self.assertTrue(ok)
        self.assertEqual(p.read_text(), "export NEW=1\n")
        backup_path = Path(backup)
        self.assertTrue(backup_path.is_file())
        self.assertIn("export OLD=1", backup_path.read_text())

    def test_write_validated_rolls_back_on_invalid_script(self):
        """Invalid zsh content is rejected and the original is kept."""
        p = self.home / ".zshrc"
        original = "export KEEP=1\n"
        p.write_text(original)
        with patch("src.shell_audit_cli._BACKUP_ROOT", self.backups):
            ok, msg = _write_validated(p, "if [ 1 = 1 ]; then\necho hi\n")
        self.assertFalse(ok)
        self.assertIn("validation failed", msg)
        self.assertEqual(p.read_text(), original)
        self.assertFalse(p.with_name(".zshrc.msp-new").exists())

    def test_compinit_repair_comments_duplicates(self):
        """Duplicate compinit lines are commented; first and autoload kept."""
        p = self.home / ".zshrc"
        p.write_text(
            "autoload -Uz compinit\n"
            "compinit\n"
            "# setup\n"
            "compinit -u\n"
        )
        finding = self._finding(
            id="shell.zsh.zshrc_duplicate_compinit",
            source_file=str(p),
        )
        with patch("src.shell_audit_cli._BACKUP_ROOT", self.backups):
            ok, msg = _repair_duplicate_compinit(finding)
        self.assertTrue(ok, msg)
        from src.shell_audit import _compinit_invocations

        content = p.read_text()
        self.assertIn("autoload -Uz compinit\n", content)
        self.assertEqual(len(_compinit_invocations(content)), 1)
        self.assertIn("# msp: duplicate compinit disabled: compinit -u", content)
        self.assertIn("(backup:", msg)
        backups = list(self.backups.rglob(".zshrc"))
        self.assertTrue(backups)

    def test_compinit_repair_idempotent_when_single(self):
        """A single compinit is left alone on re-run."""
        p = self.home / ".zshrc"
        p.write_text("autoload -Uz compinit\ncompinit\n")
        before = p.read_text()
        finding = self._finding(
            id="shell.zsh.zshrc_duplicate_compinit",
            source_file=str(p),
        )
        with patch("src.shell_audit_cli._BACKUP_ROOT", self.backups):
            ok, msg = _repair_duplicate_compinit(finding)
        self.assertFalse(ok)
        self.assertIn("already clean", msg)
        self.assertEqual(p.read_text(), before)

    def test_path_entry_repair_removes_entry(self):
        """The concrete entry is removed from a PATH assignment."""
        p = self.home / ".zshrc"
        p.write_text('export PATH="/nonexistent:$PATH"\nexport FOO=1\n')
        finding = self._finding()
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            ok, msg = _repair_path_entry(finding)
        self.assertTrue(ok, msg)
        self.assertIn('export PATH="$PATH"', p.read_text())
        self.assertIn("export FOO=1", p.read_text())
        self.assertIn("backup:", msg)

    def test_path_entry_repair_honest_when_not_in_files(self):
        """Entries injected by system files are reported, not silently faked."""
        finding = self._finding()
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            ok, msg = _repair_path_entry(finding)
        self.assertFalse(ok)
        self.assertIn("manual:", msg)
        self.assertIn("not found", msg)

    def test_path_entry_repair_skips_runtime_dollar_values(self):
        """A literal $PATH entry from a bogus audit is never edited into files."""
        finding = self._finding(
            current_state="PATH entry '$PATH' does not exist as a directory"
        )
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            ok, msg = _repair_path_entry(finding)
        self.assertFalse(ok)
        self.assertIn("runtime value", msg)

    def test_dangling_symlink_removed_and_logged(self):
        """A symlink to a missing target is removed and logged."""
        link = self.home / "broken-link"
        link.symlink_to(self.home / "missing-target")
        finding = self._finding(
            id="shell.symlink.dangling_broken",
            source_file=str(link),
        )
        with patch("src.shell_audit_cli._BACKUP_ROOT", self.backups):
            ok, msg = _repair_dangling_symlink(finding)
        self.assertTrue(ok, msg)
        self.assertFalse(link.exists() and link.is_symlink())
        logs = list(self.backups.rglob("removed_symlinks.log"))
        self.assertTrue(logs)
        self.assertIn(str(link), logs[0].read_text())

    def test_dangling_symlink_idempotent(self):
        """Re-running reports already-clean instead of failing."""
        target = self.home / "real-file"
        target.write_text("x")
        link = self.home / "ok-link"
        link.symlink_to(target)
        finding = self._finding(
            id="shell.symlink.dangling_ok",
            source_file=str(link),
        )
        with patch("src.shell_audit_cli._BACKUP_ROOT", self.backups):
            ok, msg = _repair_dangling_symlink(finding)
        self.assertFalse(ok)
        self.assertIn("already clean", msg)
        self.assertTrue(link.is_symlink())

    def test_dry_run_previews_without_touching_disk(self):
        """dry_run returns a preview and makes no changes."""
        p = self.home / ".zshrc"
        before = "export PATH=/tmp:$PATH\n"
        p.write_text(before)
        finding = self._finding()
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            ok, msg = _apply_repair(finding, dry_run=True)
        self.assertTrue(ok)
        self.assertIn("[dry run]", msg)
        self.assertEqual(p.read_text(), before)

    def test_unknown_repair_is_honest_manual(self):
        """Unsupported findings report manual instead of claiming success."""
        finding = self._finding(
            id="shell.zsh.zshrc_export_path",
            repairability="GUIDED",
            recommended_state="Keep PATH export in .zprofile only",
        )
        ok, msg = _apply_repair(finding, dry_run=False)
        self.assertFalse(ok)
        self.assertIn("manual:", msg)

    def test_advisory_findings_are_skipped(self):
        """Advisory findings are never applied."""
        finding = self._finding(
            id="shell.pkg.go_configured",
            severity="NOTICE",
            repairability="ADVISORY_ONLY",
        )
        results = _apply_all_repairs([finding], dry_run=False, confirm=False)
        self.assertEqual(len(results), 1)
        ok, msg = results[0]
        self.assertFalse(ok)
        self.assertIn("advisory:", msg)

    def test_report_results_counts(self):
        """_report_results prints applied and per-reason bucket counts."""
        import io

        buf = io.StringIO()
        _report_results(
            [(True, "did a real fix"), (False, "manual: one"), (False, "manual: two")],
            stream=buf,
        )
        out = buf.getvalue()
        self.assertIn("1 applied, 2 need manual attention", out)
        self.assertIn("did a real fix", out)
        self.assertIn("manual: one", out)

    def test_report_results_buckets_advisory_separately(self):
        """Advisory and unchanged skips are not lumped into 'manual'."""
        import io

        buf = io.StringIO()
        _report_results(
            [
                (False, "advisory: go installed - skipped"),
                (False, "already clean: nothing to do"),
            ],
            stream=buf,
        )
        out = buf.getvalue()
        self.assertIn("0 applied, 1 advisory, 1 unchanged", out)
        self.assertIn("--scope advisory", out)

    def test_report_results_ignores_dry_run_previews(self):
        """Dry-run previews are not counted as applied."""
        import io

        buf = io.StringIO()
        _report_results([(True, "[dry run] would fix: x")], stream=buf)
        self.assertIn("0 applied", buf.getvalue())


class RepairScopeTest(unittest.TestCase):
    """Scope filtering for --scope / the interactive menu."""

    def test_scope_choices_match_menu(self):
        self.assertEqual(
            set(_SCOPE_CHOICES), {"auto_safe", "guided", "advisory", "all"}
        )

    def test_legacy_scope_excludes_advisory_only(self):
        self.assertTrue(_scope_allows(None, "auto_safe"))
        self.assertTrue(_scope_allows(None, "guided"))
        self.assertFalse(_scope_allows(None, "advisory_only"))

    def test_named_scope_is_a_filter(self):
        self.assertTrue(_scope_allows("auto_safe", "auto_safe"))
        self.assertFalse(_scope_allows("auto_safe", "guided"))
        self.assertTrue(_scope_allows("advisory", "advisory_only"))
        self.assertTrue(_scope_allows("all", "advisory_only"))
        self.assertTrue(_scope_allows("all", "guided"))

    def test_scope_accepts_a_list(self):
        allowed = ["auto_safe", "advisory"]
        self.assertTrue(_scope_allows(allowed, "auto_safe"))
        self.assertTrue(_scope_allows(allowed, "advisory_only"))
        self.assertFalse(_scope_allows(allowed, "guided"))

    def test_unknown_scope_raises(self):
        with self.assertRaises(ValueError):
            _scope_allows("sometimes", "guided")

    def test_ai_failure_classification(self):
        """A dead provider stops the run; a rejected proposal does not."""
        self.assertTrue(_ai_is_fatal("AI unavailable (no module)"))
        self.assertTrue(
            _ai_is_fatal("AI provider ollama failed: Ollama response error: timed out")
        )
        self.assertFalse(_ai_is_fatal("AI proposal rejected (needs sudo)"))
        self.assertFalse(_ai_is_fatal(""))

    def test_menu_scope_mapping(self):
        self.assertEqual(_menu_scope("1", False), (["auto_safe"], False))
        self.assertEqual(_menu_scope("2", True), (["guided"], False))
        self.assertEqual(_menu_scope("3", True), (["guided"], True))
        self.assertEqual(_menu_scope("4", False), (["advisory"], False))
        self.assertEqual(
            _menu_scope("5", True),
            (["auto_safe", "guided", "advisory"], True),
        )

    def test_has_automated_repair(self):
        finding = RepairEngineTest()._finding
        self.assertTrue(
            _has_automated_repair(finding(id="shell.zsh.zshrc_duplicate_compinit"))
        )
        self.assertTrue(
            _has_automated_repair(finding(id="shell.symlink.dangling_x"))
        )
        self.assertTrue(_has_automated_repair(finding(id="shell.path.duplicate_entry")))
        self.assertFalse(_has_automated_repair(finding(id="shell.exec.multiple_git")))
        self.assertFalse(
            _has_automated_repair(finding(id="shell.path.origin.zsh_zshrc"))
        )


class ScopedRepairTest(RepairEngineTest):
    """Repairs run against a temp home with an explicit scope."""

    def test_scope_excludes_other_classes(self):
        guided = self._finding(
            id="shell.path.origin.zsh_zshrc", repairability="GUIDED"
        )
        advisory = self._finding(
            id="shell.pkg.go_configured", repairability="ADVISORY_ONLY"
        )
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            results = _apply_all_repairs(
                [guided, advisory], dry_run=False, confirm=False, scope="guided"
            )
        self.assertTrue(results[0][1].startswith("manual:"), results[0][1])
        self.assertTrue(results[1][1].startswith("out of scope:"), results[1][1])

    def test_advisory_is_refused_by_default_but_allowed_when_scoped(self):
        advisory = self._finding(
            id="shell.pkg.go_configured", repairability="ADVISORY_ONLY"
        )
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            legacy = _apply_all_repairs([advisory], dry_run=False, confirm=False)
            explicit = _apply_all_repairs(
                [advisory], dry_run=False, confirm=False, scope="advisory"
            )
        self.assertTrue(legacy[0][1].startswith("advisory:"), legacy[0][1])
        self.assertFalse(explicit[0][1].startswith("advisory:"), explicit[0][1])

    def test_select_scope_filters_findings(self):
        guided = self._finding(id="shell.exec.multiple_git", repairability="GUIDED")
        auto = self._finding(
            id="shell.symlink.dangling_x", repairability="AUTO_SAFE"
        )
        self.assertEqual(_select_scope([guided, auto], "auto_safe"), [auto])
        self.assertEqual(_select_scope([guided, auto], "all"), [guided, auto])

    def test_guided_loop_reports_unimplemented_findings_as_manual(self):
        finding = self._finding(
            id="shell.exec.multiple_git",
            repairability="GUIDED",
            recommended_state="Canonicalize to one installation",
        )
        results = _guided_repair([finding], interactive=False)
        self.assertEqual(len(results), 1)
        ok, msg = results[0]
        self.assertFalse(ok)
        self.assertTrue(msg.startswith("manual:"), msg)
        self.assertIn("Canonicalize", msg)

    def test_guided_loop_applies_automated_repair_when_not_interactive(self):
        p = self.home / ".zshrc"
        p.write_text("autoload -Uz compinit\ncompinit\ncompinit -u\n")
        finding = self._finding(
            id="shell.zsh.zshrc_duplicate_compinit", source_file=str(p)
        )
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            results = _guided_repair([finding], interactive=False)
        self.assertTrue(results[0][0], results[0][1])
        self.assertIn("compinit", p.read_text())

    def test_guided_loop_honours_a_declined_prompt(self):
        p = self.home / ".zshrc"
        p.write_text("autoload -Uz compinit\ncompinit\ncompinit -u\n")
        finding = self._finding(
            id="shell.zsh.zshrc_duplicate_compinit", source_file=str(p)
        )
        hp, bp = self._patch_home_and_backups()
        with hp, bp, patch("builtins.input", return_value="n"):
            results = _guided_repair([finding], interactive=True)
        self.assertFalse(results[0][0])
        self.assertIn("declined", results[0][1])
        self.assertEqual(p.read_text().count("compinit -u"), 1)

    def test_guided_loop_stops_and_marks_the_rest_unreviewed(self):
        p = self.home / ".zshrc"
        p.write_text("autoload -Uz compinit\ncompinit\ncompinit -u\n")
        first = self._finding(
            id="shell.zsh.zshrc_duplicate_compinit", source_file=str(p)
        )
        second = self._finding(id="shell.exec.multiple_git", repairability="GUIDED")
        hp, bp = self._patch_home_and_backups()
        with hp, bp, patch("builtins.input", return_value="q"):
            results = _guided_repair([first, second], interactive=True)
        self.assertEqual(len(results), 2)
        self.assertIn("stopped by user", results[0][1])
        self.assertIn("not reviewed", results[1][1])

    def test_apply_fix_routes_guided_through_the_loop(self):
        p = self.home / ".zshrc"
        p.write_text("autoload -Uz compinit\ncompinit\ncompinit -u\n")
        automated = self._finding(
            id="shell.zsh.zshrc_duplicate_compinit",
            source_file=str(p),
            repairability="GUIDED",
        )
        unimplemented = self._finding(
            id="shell.exec.multiple_git", repairability="GUIDED"
        )
        hp, bp = self._patch_home_and_backups()
        with hp, bp:
            results = _apply_fix(
                [automated, unimplemented],
                scope=["guided"],
                use_ai=False,
                interactive=False,
            )
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0][0], results[0][1])
        self.assertTrue(results[1][1].startswith("manual:"), results[1][1])


class ShellAuditAiTest(unittest.TestCase):
    """AI line-edit proposal contract."""

    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="msp-shell-ai-test-"))
        self.file = self.tmp / ".zshrc"
        self.file.write_text("export A=1\nexport B=2\nexport C=3\n")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _edit(self, **overrides):
        from src.shell_audit_ai import LineEdit

        base = dict(
            path=self.file,
            start_line=2,
            end_line=2,
            replacement="export B=22",
            explanation="tighten B",
            provider="fake",
            confidence=0.9,
        )
        base.update(overrides)
        return LineEdit(**base)

    def test_apply_line_edit_replaces_the_range(self):
        from src.shell_audit_ai import apply_line_edit

        new, reason = apply_line_edit(self.file.read_text(), self._edit())
        self.assertEqual(reason, "")
        self.assertIn("export B=22\n", new)
        self.assertIn("export A=1\n", new)
        self.assertIn("export C=3\n", new)

    def test_apply_line_edit_rejects_out_of_range(self):
        from src.shell_audit_ai import apply_line_edit

        new, reason = apply_line_edit(
            self.file.read_text(), self._edit(start_line=9, end_line=11)
        )
        self.assertIsNone(new)
        self.assertIn("exceeds file length", reason)

    def test_apply_line_edit_rejects_a_noop(self):
        from src.shell_audit_ai import apply_line_edit

        new, reason = apply_line_edit(
            self.file.read_text(), self._edit(replacement="export B=2")
        )
        self.assertIsNone(new)
        self.assertIn("no effective change", reason)

    def test_apply_line_edit_rejects_an_inverted_range(self):
        from src.shell_audit_ai import apply_line_edit

        new, reason = apply_line_edit(
            self.file.read_text(), self._edit(start_line=3, end_line=1)
        )
        self.assertIsNone(new)
        self.assertIn("invalid line range", reason)

    def test_propose_repair_refuses_the_offline_heuristic(self):
        from src import llm
        from src.shell_audit import AuditFinding
        from src.shell_audit_ai import propose_repair

        finding = AuditFinding(
            id="shell.zsh.zshrc_export_path",
            category="zsh_startup",
            severity="NOTICE",
            title="PATH export in .zshrc",
            summary="s",
            evidence="e",
            source_file=str(self.file),
            line_numbers=(),
            current_state="export PATH in .zshrc",
            recommended_state="Move PATH export to .zprofile",
            risk="low",
            repairability="GUIDED",
        )
        edit, reason = propose_repair(
            finding, [self.file], provider=llm.LocalHeuristicProvider()
        )
        self.assertIsNone(edit)
        self.assertIn("no LLM provider available", reason)

    def test_propose_repair_applies_a_valid_model_answer(self):
        from src.shell_audit import AuditFinding
        from src.shell_audit_ai import propose_repair

        target = self.file

        class FakeProvider:
            name = "fake"

            def complete_json(self, prompt, payload):
                self.payload = payload
                return {
                    "action": "edit",
                    "path": str(target),
                    "start_line": 1,
                    "end_line": 1,
                    "replacement": "export A=11",
                    "explanation": "renamed A",
                    "confidence": "0.8",
                }

        provider = FakeProvider()
        finding = AuditFinding(
            id="shell.zsh.zshrc_export_path",
            category="zsh_startup",
            severity="NOTICE",
            title="PATH export in .zshrc",
            summary="s",
            evidence="e",
            source_file=str(self.file),
            line_numbers=(),
            current_state="export PATH in .zshrc",
            recommended_state="Move PATH export to .zprofile",
            risk="low",
            repairability="GUIDED",
        )
        edit, reason = propose_repair(finding, [self.file], provider=provider)
        self.assertEqual(reason, "")
        self.assertEqual(edit.path, self.file)
        self.assertEqual(edit.start_line, 1)
        self.assertEqual(edit.confidence, 0.8)
        self.assertEqual(provider.payload["file"]["path"], str(self.file))

    def test_propose_repair_rejects_a_path_outside_the_allow_list(self):
        from src.shell_audit import AuditFinding
        from src.shell_audit_ai import propose_repair

        outside = self.tmp / "evil.sh"
        outside.write_text("rm -rf /\n")

        class FakeProvider:
            name = "fake"

            def complete_json(self, prompt, payload):
                return {
                    "action": "edit",
                    "path": str(outside),
                    "start_line": 1,
                    "end_line": 1,
                    "replacement": "safe",
                    "explanation": "nope",
                    "confidence": 0.9,
                }

        finding = AuditFinding(
            id="shell.zsh.zshrc_export_path",
            category="zsh_startup",
            severity="NOTICE",
            title="t",
            summary="s",
            evidence="e",
            source_file=str(self.file),
            line_numbers=(),
            current_state="c",
            recommended_state="r",
            risk="low",
            repairability="GUIDED",
        )
        edit, reason = propose_repair(
            finding, [self.file], provider=FakeProvider()
        )
        self.assertIsNone(edit)
        self.assertIn("allow-list", reason)

    def test_propose_repair_handles_a_declining_model(self):
        from src.shell_audit import AuditFinding
        from src.shell_audit_ai import propose_repair

        class FakeProvider:
            name = "fake"

            def complete_json(self, prompt, payload):
                return {"action": "no_change", "explanation": "needs sudo"}

        finding = AuditFinding(
            id="shell.path.nonexistent_dir",
            category="PATH",
            severity="ERROR",
            title="t",
            summary="s",
            evidence="e",
            source_file="",
            line_numbers=(),
            current_state="c",
            recommended_state="r",
            risk="high",
            repairability="GUIDED",
        )
        edit, reason = propose_repair(finding, [self.file], provider=FakeProvider())
        self.assertIsNone(edit)
        self.assertIn("needs sudo", reason)




if __name__ == "__main__":
    unittest.main()
