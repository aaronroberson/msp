# msp/mac-privacy/mpc - Complete Command Reference

The CLI can be invoked as `msp`, `mpc`, or `mac-privacy`. All commands support `--json` and `--verbose` flags.

---

## Core Privacy & Security

| Command | Subcommands | Description |
|---------|-------------|-------------|
| `msp status` | — | Full security dashboard (firewall, encryption, sharing, services, lock) |
| `msp list` | `[--category <cat>]` | List privacy settings |
| `msp enable` | `<setting-name>` | Enable a privacy setting |
| `msp disable` | `<setting-name>` | Disable a privacy setting |
| `msp services` | `list` | List running services with risk levels |
| `msp preset` | `list`, `apply <name> [--dry-run]` | Manage security presets (basic, paranoid, drduh, term7) |

---

## Network (`msp net`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `list` | — | Listening ports + processes |
| `established` | — | Active connections |
| `top` | `[--limit N]` | Per-process bandwidth |
| `kill` | `--pid <PID> [--force]` | Kill process by PID |
| `lookup` | `--host <host>` | DNS lookup |

---

## Startup Items (`msp startup`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `list` | — | All startup items (agents, daemons, launchd) |
| `agents` | — | User launch agents only |
| `daemons` | — | System launch daemons only |
| `cron` | — | Cron jobs |
| `running` | — | Currently running daemons with PIDs |
| `disabled` | — | Disabled daemons (plist exists, not running) |
| `pause` | `<label>` | Pause/stop a running daemon |
| `start` | `<label>` | Start a disabled daemon |
| `disable` | `<label> [--force]` | Disable a startup item |
| `enable` | `<label>` | Enable a startup item |
| `audit` | `[--json] [--interactive]` | Audit for suspicious items |
| `summary` | — | Quick risk summary (HIGH/MEDIUM/REVIEW) |
| `search` | `<term>` | Find items by name/label |

---

## File Monitoring (`msp fswatch`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `watch` | `<path>` | Watch directory (requires fswatch) |
| `recent` | `[--seconds N]` | Recent events (last N seconds, default 60) |
| `system` | — | Monitor system directories |
| `new` | `[path] [--days N]` | Recently created files |
| `diff` | `<path>` | Diff config changes |
| `audit` | — | Audit system directories |

---

## Traffic Analysis (`msp traffic`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `summary` | — | Top bandwidth consumers |
| `dns` | `[--count N]` | DNS queries |
| `http` | `[--count N]` | HTTP/HTTPS traffic |
| `capture` | `[--output file] [--duration N] [--filter BPF]` | Packet capture |
| `stream` | `[--duration N] [--filter BPF]` | Live traffic stream |

---

## Security Scanner (`msp scan`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `quick` | — | Fast 30s scan |
| `deep` | — | Comprehensive scan (5min) |
| `suspicious` | — | Heuristic detection |
| `verify` | `<path>` | Gatekeeper check |
| `signature` | `<path>` | Code signature info |
| `report` | `[--output file]` | Generate report |

---

## AI Integration (`msp ask`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `ask` | `"question" [--data file]` | Direct AI query (auto-includes network context) |
| `analyze` | `[--data file]` | Analyze provided data |
| `watch` | — | Interactive monitoring mode |
| `explain` | `<setting>` | Explain a specific setting |
| `compare` | `<preset1> <preset2>` | Compare two presets |
| `suggest` | — | Hardening suggestions |

---

## Method Chaining (`msp chain`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `list` | — | List available chains |
| `run` | `<name> [--prompt "..."]` | Run a chain |
| `define` | `<name> --steps "cmd1 \| cmd2" [--desc "..."]` | Define custom chain |
| `delete` | `<name>` | Delete custom chain |
| `watch` | `<name> [--interval N] [--max N] [--prompt "..."]` | Repeat monitoring with alerts |
| `export` | `<name> --file <path>` | Export chain to file |
| `import` | `--file <path>` | Import chain from file |

**Built-in chains:** `suspicious`, `daily`, `audit`

---

## Snapshots (`msp snapshot`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `capture` | `[name] [--include-network] [--include-startup]` | Save current settings |
| `list` | — | List all snapshots |
| `diff` | `<name>` | Compare current vs snapshot |
| `restore` | `<name> [--dry-run]` | Restore settings from snapshot |
| `watch` | `<name> [--interval N] [--auto-restore]` | Monitor snapshot drift |
| `delete` | `<name>` | Delete a snapshot |

---

## Sharing (`msp sharing`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `list` / `status` | — | Show sharing status |
| `disable` | `<name>` | Disable a share |
| `disable-guest` | `[name]` | Disable guest access |
| `enable` | `<name>` | Enable a share |
| `stop-all` | — | Disable all sharing |

---

## Security Settings (`msp security`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `status` | — | Show security settings |
| `lock` | — | Lock screen |
| `sleep` | — | Sleep display |
| `set` | `<key> <value>` | Set a security setting |

---

## Dependencies (`msp doctor` / `msp deps`)

| Flag | Description |
|------|-------------|
| `--json` | JSON output |
| `--fix` | Auto-fix issues |
| `--install <pkg>` | Install specific package |
| `--check <pkg>` | Check specific package |

**Auto-installed:** fswatch, apfel
**Prompt to install:** processmonitor, knockknock, wireshark, somo

---

## Global Flags

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Verbose output |
| `--json` | JSON output |
| `--sort` | Sort by: name, label, pid, type, path, status (for list commands) |
| `-h`, `--help` | Show help |

---

## Startup Sorting Options

The `--sort` flag works with all startup list commands:

| Sort Key | Description | Best For |
|----------|-------------|----------|
| `name` | Alphanumeric by short name | Finding items by name |
| `label` | Alphanumeric by full label | Finding items by bundle ID |
| `pid` | By process ID (numeric) | Finding high/low PID processes |
| `type` | By type (agent/daemon/launchd) | Separating user vs system |
| `path` | By plist file path | Finding items by location |
| `status` | By running status | Finding running vs stopped |

Examples:
```bash
mpc startup running --sort pid      # Sort running by PID (default)
mpc startup list --sort type        # Group by agent/daemon
mpc startup disabled --sort path    # Sort by plist location
mpc startup agents --sort label     # Sort agents by bundle ID
```

---

## Examples

```bash
# Daily security check
msp chain run daily

# Investigate suspicious process
msp net established
msp net kill 12345

# Watch for changes every 5 minutes
msp chain watch audit --interval 300

# AI analysis of scan results
msp scan quick | msp ask "analyze these findings"
msp ask suggest

# Manage daemons
msp startup running          # See what's running
msp startup disabled         # See what's disabled
msp startup pause com.example.daemon  # Pause a daemon
msp startup start com.example.daemon  # Start a disabled daemon

# Apply security preset
msp preset apply basic
msp preset apply paranoid --dry-run

# Snapshot management
msp snapshot capture baseline
msp snapshot watch baseline --auto-restore
```