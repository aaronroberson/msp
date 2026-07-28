# Implementation Plan: msp Updates

## Overview

This document outlines the implementation plan for enhancing the macOS Security & Privacy CLI (`msp`). The plan is organized into phases with dependencies and risk mitigation strategies.

## Phase 1: TUI Mode Implementation

### Goal
Add interactive Terminal User Interface mode using Textual framework.

### Tasks
- [ ] Create `src/tui.py` module with Textual-based interface
- [ ] Add `msp tui` command to launch interactive mode
- [ ] Implement dashboard view showing:
  - Security status summary
  - Network connections
  - Startup items count
  - Disk/memory usage
- [ ] Create TUI widgets for each subsystem:
  - [ ] Network monitor widget
  - [ ] Startup audit widget
  - [ ] Scan results widget
- [ ] Add keyboard shortcuts:
  - `r` - Refresh
  - `q` - Quit
  - `s` - Security status
  - `n` - Network
  - `a` - Audit

### Dependencies
- None

### Risk
- Low - UI is additive, doesn't break existing CLI

---

## Phase 2: CLI Architecture Refactor

### Goal
Clean up argument parsing and command routing.

### Tasks
- [ ] Replace manual argument parsing with argparse subparsers
- [ ] Remove duplicate snapshot handling code (lines 109-182, 367-416 in main.py)
- [ ] Create `src/cli.py` for centralized command routing
- [ ] Add `--version` flag
- [ ] Add `--config` flag for custom config file

### Code Changes
```python
# Before: Manual routing
if command == "snapshot":
    # Manual parsing...

# After: Subparsers
subparsers = parser.add_subparsers(dest="command")
snapshot_parser = subparsers.add_parser("snapshot")
snapshot_parser.add_subparsers(dest="action")
# action = "capture|list|diff|restore|watch|delete"
```

### Dependencies
- Phase 1 task: Create proper subcommand structure

### Risk
- Medium - Affects core CLI entry point

### Mitigation
- Add comprehensive test coverage before refactoring

---

## Phase 3: Error Handling & UX

### Goal
Improve error messages and user guidance.

### Tasks
- [ ] Create `src/errors.py` with custom exception classes
- [ ] Add actionable error messages with install hints
- [ ] Implement graceful degradation for missing tools
- [ ] Add `--fix` flag to auto-install missing dependencies
- [ ] Improve `--help` output with examples

### Examples
```
Error: nmap not found
Hint: brew install nmap
Try: msp doctor --fix
```

### Dependencies
- None

### Risk
- Low

---

## Phase 4: Testing Enhancement

### Goal
Comprehensive test coverage using agent-tui patterns.

### Tasks
- [ ] Add TUI acceptance tests
- [ ] Create JSON output contract tests
- [ ] Add end-to-end workflow tests
- [ ] Implement session lifecycle tests
- [ ] Add assertion tests for security scanner

### Test Structure
```
tests/
├── cli/
│   ├── test_tui_interaction.py
│   └── test_command_routing.py
├── unit/
│   ├── network/
│   ├── startup/
│   └── security/
└── e2e/
    ├── test_daily_audit_chain.py
    └── test_presets.py
```

### Dependencies
- Phase 2: Clean CLI structure for reliable testing

### Risk
- Medium - Requires stable CLI interface

---

## Phase 5: Configuration System

### Goal
Add flexible configuration management.

### Tasks
- [ ] Create `~/.msp/config.toml` support
- [ ] Add `msp config` command
- [ ] Migrate hardcoded settings to config
- [ ] Add config validation
- [ ] Create schema for config

### Config Schema
```toml
[llm]
provider = "ollama"
model = "qwen2.5-coder:1.5b"
base_url = "http://localhost:11434"

[network]
default_ports = [80, 443, 8080]
scan_timeout = 30

[security]
auto_audit = true
risk_threshold = "MEDIUM"

[ui]
theme = "dark"
refresh_interval = 5
```

### Dependencies
- Phase 2: Clean configuration loading

### Risk
- Low

---

## Phase 6: Performance Optimizations

### Goal
Improve command execution speed and resource usage.

### Tasks
- [ ] Parallelize nmap scans using concurrent.futures
- [ ] Add caching for repeated facts collection
- [ ] Implement incremental snapshots
- [ ] Add `--quick` mode for fast status checks
- [ ] Optimize AI context collection (reduce subprocess calls)

### Dependencies
- Phase 1: TUI mode for progress indicators
- Phase 4: Tests to validate performance

### Risk
- Medium - Changes to core scanning logic

---

## Implementation Order

```
1. Phase 1: TUI Mode (Parallelizable)
2. Phase 3: Error Handling (Low risk, quick wins)
3. Phase 2: CLI Refactor (Requires tests first)
4. Phase 4: Testing (Depends on Phase 2)
5. Phase 5: Configuration (Can run parallel to Phase 2)
6. Phase 6: Performance (Final optimization)
```

## Success Metrics

- TUI mode: Interactive dashboard loads in <2s
- CLI refactor: All commands work with same flags
- Testing: >80% code coverage on core modules
- Error handling: Every error suggests a fix
- Performance: `msp status` runs in <3s

## Rollback Plan

- Git tags for each phase
- `--legacy` flag to use old argument parsing
- Config file versioning for migration