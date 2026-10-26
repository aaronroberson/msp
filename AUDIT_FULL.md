# Full App & Architecture Audit — macos-privacy-cli

Scope: CLI + TUI architecture, conventions, best practices, installability.
Format: Document-only (saved to `AUDIT_FULL.md`).

---

# 1. Executive Summary

The app is a functional macOS security/privacy CLI with a large surface area (~35 source modules, ~20k lines). It works when run from the checkout directory, but has significant architectural issues that make it hard to maintain, extend, test, or install reliably:

- **Routing chaos**: `main.py` mixes a `COMMAND_MODULES` dict with a massive inline `if/elif` chain (~20 direct command handlers). Inconsistent patterns make adding commands error-prone.
- **Dual TUI implementations**: `tui.py` (Textual) and `tui_xli.py` (xli transcript) compete; no shared data layer or UI contract.
- **Security risks**: `shell=True` used pervasively with user-controlled input (command injection surface).
- **No test suite runs**: `pytest` isn't installed; test files exist but cannot be executed.
- **No logging**: `print()` everywhere; no structured logging, no log levels, no log files.
- **Type hints inconsistent**: Some modules typed, many not; `Any` and `Optional[None]` misuse causes mypy/LSP errors.
- **Entry point hack**: `main.py` mutates `sys.argv` and `sys.path` at runtime to simulate subcommand invocation.

The app is installable now (packaging fixes applied), but the internal architecture needs refactoring before it can safely grow.

---

# 2. Directory & Module Inventory

```
macos-privacy-cli/
├── main.py                      → now src/main.py (CLI router + direct command handlers)
├── macos-privacy                → bash wrapper (repo-local only)
├── pyproject.toml               → package manifest (fixed)
├── requirements.txt             → synced deps (fixed)
├── deps.json                    → system (brew) deps tracked by msp doctor
├── AGENTS.md                    → project instructions incl. Command Addition Standard
├── AUDIT_INSTALLABILITY.md      → packaging-focused audit
├── AUDIT_FULL.md                → this document
├── src/
│   ├── __init__.py              → NEW (package marker)
│   ├── main.py                  → CLI entry / router
│   ├── command.py               → shared command execution helpers + interactive_select/menu
│   ├── tune.py                  → system tuning (check/fix/top)
│   ├── network.py               → network monitoring (ports, connections, nmap, bandwidth)
│   ├── tui.py                   → Textual dashboard TUI
│   ├── tui_xli.py               → xli transcript-style TUI
│   ├── tcc.py                   → TCC privacy permissions
│   ├── privacy_settings.py      → privacy settings CRUD + presets + interactive bash menu
│   ├── scanner.py               → security scanner
│   ├── rules.py                 → rule-based audit
│   ├── facts.py                 → normalized fact collection (interrogate)
│   ├── llm.py                   → LLM providers (ollama, apfel, openai, etc.)
│   ├── ai.py                    → AI analysis command (ask)
│   ├── remediate.py             → remediation planning
│   ├── report.py                → evidence reports
│   ├── workflows.py             → built-in interrogation workflows
│   ├── snapshot.py              → config snapshots
│   ├── sharing.py               → sharing services status
│   ├── security.py              → lock/sleep/screen settings
│   ├── shell_audit_cli.py       → shell audit & repair
│   ├── shell_audit.py           → shell audit engine
│   ├── shell_audit_ai.py        → AI line-edit repair proposals
│   ├── startup.py               → startup item management
│   ├── fswatch.py               → file system watching
│   ├── traffic.py               → traffic analysis
│   ├── forensics.py             → volume/AppleDouble forensics
│   ├── deps.py                  → DependencyManager + doctor
│   ├── presets.py               → preset management
│   ├── sdk.py                   → provider SDK metadata
│   ├── chain.py                 → method chaining
│   ├── errors.py                → config load/save
│   └── splash.py                → splash screen
└── tests/
    ├── test_cli_smoke.py
    ├── test_command.py
    ├── test_facts.py
    ├── test_forensics.py
    ├── test_llm.py
    ├── test_remediate.py
    ├── test_report.py
    ├── test_rules.py
    ├── test_shell_audit.py
    ├── test_tcc.py
    ├── test_tui_acceptance.py
    ├── test_workflows.py
    └── test_ai.py
```

---

# 3. Detailed Findings by Category

## 3.1 CLI Routing — "God Router" anti-pattern (`main.py`)

**Severity: High**

`main.py` handles commands through TWO parallel mechanisms:

1. `COMMAND_MODULES` dict → `run_command()` for module-based commands (`net`, `tune`, `tcc`, etc.)
2. A ~150-line `if/elif` chain for direct handlers (`status`, `list`, `enable`, `disable`, `preset`, `services`, `snapshot`, `sharing`, `security`, `shell`, `config`, `ask`, `doctor`, `tui`)

This duplication means:
- Adding a command requires editing `main.py` in multiple places.
- Help text (epilog) must be manually kept in sync with actual routing.
- `--json`, `--verbose`, `--sort` flags are threaded through inconsistently.
- `sys.argv` is mutated at runtime to simulate subcommand calls (`sys.argv = ["msp-" + module_name]`), which is fragile and breaks argparse's expectation of stable argv.

**Example of the direct-handler block** (`main.py:288-338`):
```python
if command in ("status", "list", "enable", "disable", "preset", "presets", "services"):
    manager = PrivacySettingsManager(verbose=args.verbose)
    ...
```

These should be delegated to `src/privacy_settings.py` via `run_command()` like module-based commands.

**Recommendation**: Consolidate all commands into the `COMMAND_MODULES` pattern or a proper subparser architecture. Eliminate the inline `if/elif` chain. Each command module should own its own argument parsing and output.

## 3.2 Dual TUI Implementations

**Severity: High**

Two completely separate TUI implementations with no shared code:

| File | Framework | Style | Status |
|------|-----------|-------|--------|
| `src/tui.py` | Textual | Dashboard widgets (Security, Network, Startup, System) + detail screens | Imported but `textual` was undeclared (now fixed) |
| `src/tui_xli.py` | xli | Transcript/chat-style interactive assistant | Routed by `main.py` when `command == "tui"` |

Problems:
- `main.py` routes `tui` → `tui_xli` (line 620-623), ignoring `tui.py` entirely for the `msp tui` command.
- `tui.py` widgets pull data directly from module managers (`NetworkMonitor`, `StartupManager`, etc.) with no caching, no refresh coordination, and no error boundaries.
- No shared data provider contract; each widget instantiates managers independently.
- `HelpScreen` in `tui.py` lists keyboard shortcuts but not CLI commands (partially addressed — added `msp tune top`).
- No test coverage for either TUI.

**Recommendation**: Pick ONE TUI framework (Textual is more modern and actively maintained than xli). Unify data access behind a `TUIDataProvider` (already started in `tui.py`). Make the TUI a thin presentation layer over the same command modules the CLI uses.

## 3.3 Security — `shell=True` with user input

**Severity: Critical**

`shell=True` is used extensively across `src/command.py`, `src/network.py`, `src/tune.py`, `src/ai.py`, `src/deps.py`, etc., often with user-controlled or environment-derived strings.

**Examples**:
- `tune.py:51`: `_run("time ( zsh -i -c exit ) 2>&1")`
- `network.py:101`: `lsof -iTCP ...` via `shell=True`
- `ai.py:525-530`: `_sh()` helper runs arbitrary shell via `subprocess.run(cmd, shell=True)`
- `deps.py:73-85`: `check_dep` runs `verify_cmd` from `deps.json` via shell

**Risk**: If any `verify_cmd`, `install_cmd`, or user-supplied argument contains shell metacharacters (`;`, `$(...)`, backticks), arbitrary code execution is possible.

**Recommendation**: 
- Default to `shell=False` with argv lists.
- Reserve `shell=True` only for commands that genuinely need shell features (pipes, globbing, env expansion), and sanitize/validate all inputs.
- Add a security lint rule (e.g., `bandit` or `flake8-bandit`) to flag `shell=True`.

## 3.4 Error Handling & Output

**Severity: Medium**

- `print()` used everywhere instead of the `logging` module. No log levels, no log rotation, no structured output except `--json` on some commands.
- Inconsistent `--json` support: some commands emit JSON, others print human-readable only.
- Exceptions are caught broadly and printed (`print(f"Error: {e}")`) with no traceback in non-verbose mode.
- `main.py` catches `SystemExit` and re-raises, but other exceptions print and `sys.exit(1)`.

**Recommendation**: 
- Adopt `logging` with `-v`/`--verbose` controlling level.
- Make `--json` uniform: every command should support it, emitting `{"success": bool, "data": ..., "error": ...}`.
- Centralize error handling in `main.py` rather than per-command try/except.

## 3.5 Type Hints & Static Analysis

**Severity: Medium**

LSP/mypy errors across multiple files:

- `main.py`: `None` assigned to `dict` parameters; `list[str | None]` where `Iterable[str]` expected; `Any | None` where `str` expected.
- `tune.py` / `tui.py`: `rich` / `textual` imports unresolved (environmental now, but the `try/except ImportError` guard leaves `Console`/`Table` possibly unbound).
- No `mypy` or `pyright` configuration in `pyproject.toml`.

**Recommendation**: 
- Add `mypy` to dev dependencies and a `mypy.ini` / `[tool.mypy]` section.
- Run `python3 -m mypy src/` in CI.
- Fix the `None`-to-`dict` and `Optional` issues in `main.py`.

## 3.6 Testing

**Severity: High**

- `tests/` has 11 test files but `pytest` is not installed and cannot run in this environment.
- `pyproject.toml` declares `test = ["pytest>=7.0"]` as an optional extra, but tests aren't run in any CI configuration (no `.github/workflows`, no `Makefile`, no `tox.ini`).
- No test fixtures, no mocking strategy for subprocess calls.
- `test_tui_acceptance.py` exists but TUI tests likely require a terminal/display.

**Recommendation**: 
- Add a `Makefile` or CI workflow running `python3 -m pytest -q`.
- Mock `subprocess.run` in tests for commands that shell out.
- Add `pytest` to default dependencies or document `pip install -e ".[test]"`.

## 3.7 Configuration

**Severity: Low**

- `src/errors.py` provides `load_config()` / `save_config()` for a JSON config file (location unclear).
- `deps.json` tracks system deps separately from Python deps — two config sources.
- No schema validation for config.
- `--provider`, `--model`, `--openvino-device` CLI flags for LLM are parsed in `main.py` but not clearly documented.

**Recommendation**: 
- Document config file location and schema.
- Consider `pydantic-settings` for typed config with env var overrides.

---

# 4. CLI/TUI Conventions Audit

Against the `Command Addition Standard` I added to `AGENTS.md`:

| Dimension | Status | Notes |
|-----------|--------|-------|
| CLI routing in `main.py` | ⚠️ Partial | `COMMAND_MODULES` exists but direct `if/elif` handlers bypass it |
| Module implementation | ✅ | Most modules have `main()` with `--json` |
| Interactive menu | ⚠️ Partial | `command.interactive_menu` exists; some modules use it, others have custom loops |
| TUI integration | ⚠️ Partial | `tui.py` has widgets; `tui_xli.py` is separate; HelpScreen partially updated |
| Help text | ⚠️ Partial | Epilog lists commands but not all subcommands (e.g., `tune top` added) |
| `py_compile` | ✅ | Passes for modified files |
| End-to-end smoke test | ✅ | `msp tune top` and `--json` verified |

**Key gap**: The standard is new and aspirational — existing commands (predating it) do not all comply. `status`, `list`, `enable`, `disable` are still inline in `main.py` rather than delegated to `privacy_settings.py` via `run_command`.

---

# 5. Recommended Refactoring Roadmap

## Phase 1 — Stabilize (no breaking changes)

1. **Eliminate `shell=True`** where possible; switch to argv lists.
2. **Add `logging`**; replace `print()` with `logger.info/warn/error`.
3. **Add `mypy`** + fix existing type errors in `main.py`, `tune.py`, `tui.py`.
4. **Add `pytest` to CI** and make the existing test suite runnable.
5. **Unify `--json`** output shape across all commands.

## Phase 2 — Consolidate routing

6. **Move inline `main.py` handlers** (`status`, `list`, `enable`, `disable`, `preset`, `services`, `sharing`, `security`, `shell`, `config`) into their modules and route via `COMMAND_MODULES` / `run_command()`.
7. **Stop mutating `sys.argv`**; use proper argparse subparsers or pass `argv` explicitly to module `main()`.
8. **Pick one TUI framework**; deprecate the other or make them share a `TUIDataProvider`.

## Phase 3 — Harden

9. **Add input validation** for all shell-adjacent commands.
10. **Add integration tests** that invoke `msp <command>` in a subprocess and assert exit codes / output shape.
11. **Add a `Makefile`** with `make test`, `make lint`, `make typecheck`, `make install`.

---

# 6. Quick Validation Checklist (for contributors)

```bash
# 1. Create a venv (avoids PEP 668 / externally-managed errors)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install the package
pip install --upgrade pip
pip install -e /path/to/macos-privacy-cli

# 3. Verify the console script
msp --help
msp tune top --json | python3 -m json.tool

# 4. Type check (once mypy is added)
python3 -m mypy src/

# 5. Run tests
python3 -m pytest -q
```

---

# 7. Files Changed in This Audit Session

- `src/__init__.py` — new package marker
- `src/main.py` — moved from root, `sys.path` fix
- `pyproject.toml` — `textual` dep, `packages = ["src"]`, entry points to `src.main:main`
- `requirements.txt` — synced
- `.gitignore` — build artifacts
- `AGENTS.md` — Command Addition Standard + Definition of Done
- `AUDIT_INSTALLABILITY.md` — packaging audit
- `AUDIT_FULL.md` — this document
