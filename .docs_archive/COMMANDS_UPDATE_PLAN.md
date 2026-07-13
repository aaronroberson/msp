# COMMANDS.md Update Plan

## Overview
This document outlines the comprehensive plan to update COMMANDS.md to accurately reflect all commands, subcommands, arguments, and options available in the macos-privacy-cli codebase.

## Current State Analysis
- **COMMANDS.md**: 233 lines documenting CLI commands
- **Codebase**: 11 source modules in `src/` with extensive functionality
- **Gap**: Significant missing commands, flags, sort options, and examples

## Phase 1: Core Privacy & Security (`msp`)

### Missing Subcommands to Add
| Command | Options | Description |
|---------|---------|-------------|
| `msp preset save <name> --settings JSON [--description]` | `--settings` (JSON), `--description` (string) | Save custom preset |
| `msp preset delete <name>` | - | Delete custom preset (built-in protected) |

### Update Existing
- `msp services` → Add `list --sort <key>` with keys: `name`, `status`, `pid`

## Phase 2: Security Settings (`msp security`)

### Missing Subcommands
| Subcommand | Options | Description |
|------------|---------|-------------|
| `computer-sleep` | - | Put computer to sleep (distinct from display sleep) |

### Document `set` Keys
| Key | Value Type | Description |
|-----|------------|-------------|
| `lock-time` | minutes | Screen lock timeout |
| `password-delay` | seconds | Password delay after sleep |
| `password-enable` | (none) | Require password after sleep |
| `password-disable` | (none) | Don't require password |
| `display-sleep` | minutes | Display sleep timeout |

## Phase 3: Dependencies (`msp doctor` / `msp deps`)

### Replace Flag Table with Subcommand Table
| Subcommand | Options | Description |
|------------|---------|-------------|
| `status` | `--json`, `--sort` (name, status, required) | Show dependency status |
| `check <pkg>` | `--json` | Check specific package |
| `install <pkg>` | `--json` | Install specific package |
| `fix` | `--json` | Install missing required dependencies |
| `install-all` | `--json` | Install all missing packages |

Note: `msp doctor --fix` runs `fix` action; `msp deps` defaults to `status`

## Phase 4: Add `--sort` Reference Tables

### File System Watch (`msp fswatch`)
| Sort Key | Commands | Description |
|----------|----------|-------------|
| `timestamp` | `recent` | Event time |
| `call` | `recent` | Syscall name |
| `process` | `recent` | Process name |
| `path` | `recent`, `new`, `audit` | File path |
| `age` | `new` | File age |
| `directory` | `audit` | Directory |
| `warning` | `audit` | Warning type |

### Traffic Analysis (`msp traffic`)
| Sort Key | Commands | Description |
|----------|----------|-------------|
| `total` | `summary` | Total bandwidth |
| `in` | `summary` | Inbound bytes |
| `out` | `summary` | Outbound bytes |
| `process` | `summary` | Process name |
| `host` | `http` | Destination host |
| `source` | `http` | Source IP |
| `destination` | `http` | Destination IP |

### Security Scanner (`msp scan`)
| Sort Key | Commands | Description |
|----------|----------|-------------|
| `severity` | `quick`, `deep`, `suspicious` | HIGH > MEDIUM > LOW |
| `category` | `quick`, `deep`, `suspicious` | Category name |
| `item` | `quick`, `deep`, `suspicious` | Finding item |

### Method Chaining (`msp chain`)
| Sort Key | Commands | Description |
|----------|----------|-------------|
| `name` | `list` | Chain name |
| `type` | `list` | Built-in first, then custom |
| `steps` | `list` | Number of steps |

### Sharing (`msp sharing`)
| Sort Key | Commands | Description |
|----------|----------|-------------|
| `name` | `list`, `status` | Share point name |
| `path` | `list`, `status` | Share path |
| `guest` | `list`, `status` | Guest access |
| `readonly` | `list`, `status` | Read-only status |

### Snapshots (`msp snapshot`)
| Sort Key | Commands | Description |
|----------|----------|-------------|
| `name` | `list` | Snapshot name |
| `timestamp` | `list` | Creation time (newest first) |
| `hostname` | `list` | Host name |

### Services (`msp services`)
| Sort Key | Commands | Description |
|----------|----------|-------------|
| `name` | `list` | Service name |
| `status` | `list` | Running status |
| `pid` | `list` | Process ID |

## Phase 5: Missing Flags for Existing Commands

### Chain (`msp chain`)
- `--max <N>` for `watch` subcommand (max iterations)
- `--prompt` for `run` and `watch`

### Snapshot (`msp snapshot`)
- `--include-custom` for `capture` (include custom settings from ~/.msp/settings.json)
- `--force` for `restore` (skip confirmations)

### Startup (`msp startup`)
- `--interactive` / `-i` for `audit` subcommand

## Phase 6: Interactive Mode Documentation

All modules support interactive mode when no subcommand provided:
- `msp net` → interactive network menu
- `msp startup` → interactive startup menu
- `msp fswatch` → interactive fswatch menu
- `msp traffic` → interactive traffic menu
- `msp scan` → interactive scanner menu
- `msp ask` → interactive AI menu
- `msp chain` → interactive chain menu
- `msp snapshot` → interactive snapshot menu
- `msp sharing` → interactive sharing menu
- `msp security` → interactive security menu
- `msp deps` / `msp doctor` → interactive deps menu

## Phase 7: Update Global Flags Table

Add all discovered sort keys:
```
--sort <key>  Sort by: name, label, pid, type, path, status, port, process, protocol, local, remote, total, in, out, timestamp, call, age, directory, warning, severity, category, item, host, source, destination, state, hostname
```

## Phase 8: Update Examples Section

Add examples for new commands:
```bash
# Save custom preset
msp preset save myconfig --settings '{"Application Firewall": true, "Gatekeeper": true}'

# Delete custom preset
msp preset delete myconfig

# Computer sleep (not just display)
msp security computer-sleep

# Set specific security settings
msp security set lock-time 5
msp security set password-delay 0
msp security set display-sleep 10

# Check specific dependency
msp deps check fswatch

# Install all missing deps
msp deps install-all

# Watch chain with max iterations
msp chain watch audit --interval 300 --max 10

# Snapshot with custom settings
msp snapshot capture baseline --include-network --include-startup --include-custom
```

## Implementation Order
1. High Priority - Core table updates (Phases 1-3)
2. Medium Priority - Sort tables (Phase 4)
3. Medium Priority - Missing flags (Phase 5)
4. Medium Priority - Interactive mode doc (Phase 6)
4. Low Priority - Global flags + examples (Phases 7-8)

## Estimated Changes
- ~50 new lines for sort tables
- ~30 new lines for dependency subcommand table
- ~20 new lines for interactive mode section
- ~25 updated lines for existing tables
- ~15 new lines for examples
- **Total: ~140 lines added/modified** in COMMANDS.md