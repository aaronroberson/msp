# Code Quality & Installability Architecture Audit

## Summary

This audit covers packaging, imports, entry points, and CLI structure for the `macos-privacy-cli` project. The goal is to make the app easily installable and runnable by others.

---

## Critical Issues

### 1. Broken Python package layout

`pyproject.toml` declares:
```toml
py-modules = ["main"]
packages.find include = ["src*"]
```

Problems:
- **No `src/__init__.py` exists**, so `src` is an implicit namespace package. Code imports `from src.command import ...` which only works because `main.py` manually injects the repo root into `sys.path`. This is fragile and breaks once installed elsewhere.
- Entry points like `msp-forensics = "src.forensics:main"` will **fail to resolve** because `src` isn't registered as an importable package.
- `main.py` and `src/` live side-by-side at root — a confusing dual layout.

### 2. Declared deps are not installed / missing deps

`pyproject.toml` lists `python-xli>=0.2.0`, but `pip show python-xli` → not found. `src/tui_xli.py` does `import xli` at module top, so `msp tui` crashes on import.

`src/tui.py` imports `textual` at top, but `textual` is **not declared anywhere** (not in `pyproject.toml`, not in `requirements.txt`). `msp tui` (textual variant) also crashes.

`requirements.txt` only has `rich` + `argcomplete` — missing `python-xli`, `textual`, `openai`, `pytest`.

### 3. Python / pip installation mismatch

- `python3` → `/opt/homebrew/bin/python3` (3.15.0)
- `pip` → `/Users/conscious/Library/Python/3.9/bin/pip` (Python 3.9)

So `pip install` installs packages for 3.9, but the app runs under 3.15. `rich` shows in `pip list` but `import rich` fails under `python3`. Users installing via `pip` won't get working deps.

### 4. Optional deps imported unconditionally

`src/tui_xli.py` and `src/tui.py` import `xli`/`textual` at module scope with no fallback. Any command that transitively imports these will hard-crash if the optional dep is absent.

### 5. `macos-privacy` wrapper is repo-local only

It runs `python3 main.py "$@"` — works only from the checkout directory, not an installed entry point.

---

## Source layout inventory

```
macos-privacy-cli/
├── main.py                 # CLI entry (root level)
├── macos-privacy           # bash wrapper (repo-local only)
├── pyproject.toml          # package manifest
├── requirements.txt        # incomplete (rich, argcomplete only)
├── deps.json               # system (brew) deps — apfel, ollama, nmap, etc.
├── src/
│   ├── __init__.py         # MISSING
│   ├── command.py
│   ├── network.py
│   ├── tune.py             # ← contains new `top` subcommand
│   ├── tui.py              # textual-based TUI (imports `textual` unconditionally)
│   ├── tui_xli.py          # xli-based TUI (imports `xli` unconditionally)
│   ├── ai.py               # uses `apfel` (brew formula, optional)
│   ├── llm.py              # uses `apfel` (brew formula, optional)
│   ├── deps.py             # DependencyManager (reads deps.json)
│   └── ... (other modules)
```

---

## Dependencies analysis

### Python packaging deps (`pyproject.toml`)
- `argcomplete>=3.0.0` — declared, installed under pip 3.9 but not importable under python3 3.15
- `rich>=13.0.0` — declared, same mismatch
- `python-xli>=0.2.0` — declared, but package not found by pip
- `textual` — used by `src/tui.py`, NOT declared anywhere

### Optional extras (`pyproject.toml`)
- `llm = ["openai>=1.0.0"]`
- `test = ["pytest>=7.0"]`

### System deps (`deps.json`, managed by `msp doctor`)
These are Homebrew formulas/casks, NOT pip packages:
- `fswatch` (required, auto-install)
- `ollama` (required, auto-install)
- `apfel` (optional, fallback LLM)
- `processmonitor`, `knockknock` (casks, optional)
- `wireshark`, `somo`, `nmap`, `exiftool` (optional)
- `openvino` (pip, optional)

### `apfel` clarification

`apfel` is **not** used by `msp tune top`. That command uses only built-in macOS utilities (`ps`, `memory_pressure`, `uptime`). `apfel` is only used by the AI/llm modules (`src/ai.py`, `src/llm.py`) as an optional LLM fallback. It is correctly tracked as an optional dependency in `deps.json`.

---

## Recommended fixes

### A. Fix the package layout (choose one)

**Option 1 (simplest):** Move everything under `src/` and make it a real package:
```
src/__init__.py
src/main.py      (cli entry)
src/command.py
...
```
Then `pyproject.toml`:
```toml
[tool.setuptools.packages.find]
include = ["src*"]

[project.scripts]
msp = "src.main:main"
```

**Option 2:** Keep `main.py` at root, add `src/__init__.py`, and declare `src` as a package:
```toml
[tool.setuptools]
py-modules = ["main"]
packages = ["src"]
```

### B. Declare all runtime deps correctly

`pyproject.toml`:
```toml
dependencies = [
  "argcomplete>=3.0.0",
  "rich>=13.0.0",
  "python-xli>=0.2.0",
  "textual>=0.80.0",
]

[project.optional-dependencies]
llm = ["openai>=1.0.0"]
test = ["pytest>=7.0"]
```

Sync `requirements.txt` to match.

### C. Make optional imports safe

Guard `xli` / `textual` imports:
```python
try:
    import xli
    HAS_XLI = True
except ImportError:
    HAS_XLI = False
```
And raise a clear, actionable error in `tui`/`tui_xli` main() only when the user actually invokes those commands.

### D. Fix the pip/python mismatch

Document `python3 -m pip` (not bare `pip`) so packages install for the same interpreter that runs the app:
```bash
python3 -m pip install -e .
```

### E. Provide an installable entry point

With proper packaging, `pip install -e .` (or `pip install .`) creates the `msp` console script automatically — no need for the `macos-privacy` shell wrapper.

---

## Quick validation checklist

```bash
cd /Users/conscious/macos-privacy-cli
# 1. Add src/__init__.py (empty)
touch src/__init__.py

# 2. Install in editable mode for the correct interpreter
python3 -m pip install -e .

# 3. Verify package imports
python3 -c "import src.command; print('pkg OK')"

# 4. Verify console script works from anywhere
msp --help
msp tune top
msp tune top --json
```

---

## New command added (`msp tune top`)

Added `Tuner.top()` to `src/tune.py`:
- Runs: `ps axo pcpu,pmem,comm -r | head -12`, `ps axo pmem,comm -m | head -12`, `memory_pressure -Q`, `uptime`
- Registered in argparse choices (`check`, `fix`, `top`)
- Added to interactive tune menu (`3. top`)
- `--json` support: returns `{command, returncode, output}`
- CLI routing via existing `COMMAND_MODULES["tune"]` mapping in `main.py`
- Help text added to `msp --help` epilog
- TUI: hint added to System dashboard widget + HelpScreen CLI Commands entry

No third-party dependencies — uses only built-in macOS utilities.
