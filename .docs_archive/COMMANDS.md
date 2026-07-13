# msp/mac-privacy/mpc - Complete Command Reference

The CLI can be invoked as `msp`, `mpc`, or `mac-privacy`. All commands support `--json` and `--verbose` flags.

---

## Core Privacy & Security

| Command | Subcommands | Description |
|---------|-------------|-------------|
| `msp status` | — | Full security dashboard (firewall, encryption, sharing, services, lock) |
| `msp list` | `[--category <cat>] [--sort <key>]` | List privacy settings |
| `msp enable` | `<setting-name>` | Enable a privacy setting |
| `msp disable` | `<setting-name>` | Disable a privacy setting |
| `msp services` | `list [--sort <key>]` | List running services with risk levels |
| `msp preset` | `list`, `apply <name> [--dry-run]`, `save <name> --settings JSON [--description]`, `delete <name>` | Manage security presets (basic, paranoid, drduh, term7, nist) |

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
| `list` | `[--sort <key>]` | All startup items (agents, daemons, launchd) |
| `agents` | `[--sort <key>]` | User launch agents only |
| `daemons` | `[--sort <key>]` | System launch daemons only |
| `cron` | `[--json]` | Cron jobs |
| `running` | `[--sort <key>]` | Currently running daemons with PIDs |
| `disabled` | `[--sort <key>]` | Disabled daemons (plist exists, not running) |
| `pause` | `<label>` | Pause/stop a running daemon |
| `start` | `<label>` | Start a disabled daemon |
| `disable` | `<label> [--force]` | Disable a startup item |
| `enable` | `<label>` | Enable a startup item |
| `audit` | `[--json] [--interactive]` | Audit for suspicious items |
| `summary` | `[--json]` | Quick risk summary (HIGH/MEDIUM/REVIEW) |
| `search` | `<term>` | Find items by name/label |

**Sort Keys:** `name`, `label`, `pid`, `type`, `path`, `status`

---

## File Monitoring (`msp fswatch`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `watch` | `<path>` | Watch directory (requires fswatch) |
| `recent` | `[--seconds N] [--sort <key>]` | Recent events (last N seconds, default 60) |
| `system` | — | Monitor system directories |
| `new` | `[path] [--days N] [--sort <key>]` | Recently created files |
| `diff` | `<path>` | Diff config changes |
| `audit` | `[--sort <key>]` | Audit system directories |

**Sort Keys:** `recent` → `timestamp`, `call`, `process`, `path` | `new` → `path`, `age` | `audit` → `path`, `directory`, `warning`

---

## Traffic Analysis (`msp traffic`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `summary` | `[--limit N] [--sort <key>]` | Top bandwidth consumers |
| `dns` | `[--count N]` | DNS queries |
| `http` | `[--count N] [--sort <key>]` | HTTP/HTTPS traffic |
| `capture` | `[--output file] [--duration N] [--filter BPF]` | Packet capture |
| `stream` | `[--duration N] [--filter BPF]` | Live traffic stream |

**Sort Keys:** `summary` → `total`, `in`, `out`, `process` | `http` → `host`, `source`, `destination`

---

## Security Scanner (`msp scan`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `quick` | `[--sort <key>]` | Fast 30s scan |
| `deep` | `[--sort <key>]` | Comprehensive scan (5min) |
| `suspicious` | `[--sort <key>]` | Heuristic detection |
| `verify` | `<path>` | Gatekeeper check |
| `signature` | `<path>` | Code signature info |
| `report` | `[--output file]` | Generate report |

**Sort Keys:** `severity` (HIGH > MEDIUM > LOW), `category`, `item`

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
| `list` | `[--sort <key>]` | List available chains |
| `run` | `<name> [--prompt "..."]` | Run a chain |
| `define` | `<name> --steps "cmd1 \| cmd2" [--desc "..."]` | Define custom chain |
| `delete` | `<name>` | Delete custom chain |
| `watch` | `<name> [--interval N] [--max N] [--prompt "..."]` | Repeat monitoring with alerts |
| `export` | `<name> --file <path>` | Export chain to file |
| `import` | `--file <path>` | Import chain from file |

**Built-in chains:** `suspicious`, `daily`, `audit`

**Sort Keys:** `list` → `name`, `type` (built-in first), `steps`

---

## Snapshots (`msp snapshot`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `capture` | `[name] [--include-network] [--include-startup]` | Save current settings (custom settings always included) |
| `list` | `[--sort <key>]` | List all snapshots |
| `diff` | `<name> [--json]` | Compare current vs snapshot |
| `restore` | `<name> [--dry-run] [--force]` | Restore settings from snapshot |
| `watch` | `<name> [--interval N] [--auto-restore]` | Monitor snapshot drift |
| `delete` | `<name>` | Delete a snapshot |

**Sort Keys:** `list` → `name`, `timestamp` (newest first), `hostname`

---

## Sharing (`msp sharing`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `list` / `status` | `[--sort <key>]` | Show sharing status |
| `disable` | `<name>` | Disable a share |
| `disable-guest` | `[name]` | Disable guest access |
| `enable` | `<name>` | Enable a share |
| `stop-all` | — | Disable all sharing |

**Sort Keys:** `name`, `path`, `guest`, `readonly`

---

## Security Settings (`msp security`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `status` | `[--sort <key>]` | Show security settings |
| `lock` | — | Lock screen |
| `sleep` | — | Sleep display |
| `computer-sleep` | — | Put computer to sleep |
| `set` | `<key> <value>` | Set a security setting |

**Set Keys:** `lock-time <min>`, `password-delay <sec>`, `password-enable`, `password-disable`, `display-sleep <min>`

**Sort Keys:** `key`

---

## Dependencies (`msp doctor` / `msp deps`)

| Subcommand | Options | Description |
|------------|---------|-------------|
| `status` | `[--json] [--sort <key>]` | Show dependency status (default) |
| `check <pkg>` | `[--json]` | Check specific package |
| `install <pkg>` | `[--json]` | Install specific package |
| `fix` | `[--json]` | Install missing required dependencies |
| `install-all` | `[--json]` | Install all missing packages |

**Sort Keys:** `name`, `status` (installed first), `required`

**Flags:** `--json`, `--fix` (alias for `fix` subcommand)

**Auto-installed:** fswatch, ollama
**Optional:** apfel (Apple Intelligence fallback)
**Prompt to install:** processmonitor, knockknock, wireshark, somo

---

## Global Flags

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Verbose output |
| `--json` | JSON output |
| `--sort <key>` | Sort by: name, label, pid, type, path, status, port, process, protocol, local, remote, total, in, out, timestamp, call, age, directory, warning, severity, category, item, host, source, destination, state, hostname |
| `-h`, `--help` | Show help |

---

## Interactive Mode

All modules support interactive mode when no subcommand is provided:

| Command | Interactive Menu |
|---------|------------------|
| `msp net` | Network monitoring (ports, connections, bandwidth, kill, DNS) |
| `msp startup` | Startup item management (list, audit, pause, start, disable, enable) |
| `msp fswatch` | File system watcher (watch, recent, system, new, diff, audit) |
| `msp traffic` | Traffic analysis (summary, DNS, HTTP, capture, stream) |
| `msp scan` | Security scanner (quick, deep, suspicious, verify, signature, report) |
| `msp ask` | AI analyzer (ask, analyze, watch, explain, compare, suggest) |
| `msp chain` | Chain manager (list, run, define, delete, watch, export, import) |
| `msp snapshot` | Snapshot manager (capture, list, diff, restore, watch, delete) |
| `msp sharing` | Sharing manager (list, disable, disable-guest, enable, stop-all) |
| `msp security` | Security settings (status, lock, sleep, computer-sleep, set) |
| `msp deps` / `msp doctor` | Dependency manager (status, check, install, fix, install-all) |

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

## File Monitoring Sorting Options (`msp fswatch`)

| Sort Key | Commands | Description |
|----------|----------|-------------|
| `timestamp` | `recent` | Event time |
| `call` | `recent` | Syscall name |
| `process` | `recent` | Process name |
| `path` | `recent`, `new`, `audit` | File path |
| `age` | `new` | File age |
| `directory` | `audit` | Directory |
| `warning` | `audit` | Warning type |

Examples:
```bash
msp fswatch recent --sort timestamp
msp fswatch new --sort age
msp fswatch audit --sort warning
```

---

## Traffic Analysis Sorting Options (`msp traffic`)

| Sort Key | Commands | Description |
|----------|----------|-------------|
| `total` | `summary` | Total bandwidth |
| `in` | `summary` | Inbound bytes |
| `out` | `summary` | Outbound bytes |
| `process` | `summary` | Process name |
| `host` | `http` | Destination host |
| `source` | `http` | Source IP |
| `destination` | `http` | Destination IP |

Examples:
```bash
msp traffic summary --sort total
msp traffic http --sort host
```

---

## Security Scanner Sorting Options (`msp scan`)

| Sort Key | Commands | Description |
|----------|----------|-------------|
| `severity` | `quick`, `deep`, `suspicious` | HIGH > MEDIUM > LOW |
| `category` | `quick`, `deep`, `suspicious` | Category name |
| `item` | `quick`, `deep`, `suspicious` | Finding item |

Examples:
```bash
msp scan quick --sort severity
msp scan deep --sort category
```

---

## Method Chaining Sorting Options (`msp chain`)

| Sort Key | Commands | Description |
|----------|----------|-------------|
| `name` | `list` | Chain name |
| `type` | `list` | Built-in first, then custom |
| `steps` | `list` | Number of steps |

Examples:
```bash
msp chain list --sort name
msp chain list --sort type
```

---

## Sharing Sorting Options (`msp sharing`)

| Sort Key | Commands | Description |
|----------|----------|-------------|
| `name` | `list`, `status` | Share point name |
| `path` | `list`, `status` | Share path |
| `guest` | `list`, `status` | Guest access |
| `readonly` | `list`, `status` | Read-only status |

Examples:
```bash
msp sharing list --sort name
msp sharing list --sort guest
```

---

## Snapshots Sorting Options (`msp snapshot`)

| Sort Key | Commands | Description |
|----------|----------|-------------|
| `name` | `list` | Snapshot name |
| `timestamp` | `list` | Creation time (newest first) |
| `hostname` | `list` | Host name |

Examples:
```bash
msp snapshot list --sort timestamp
msp snapshot list --sort name
```

---

## Services Sorting Options (`msp services`)

| Sort Key | Commands | Description |
|----------|----------|-------------|
| `name` | `list` | Service name |
| `status` | `list` | Running status |
| `pid` | `list` | Process ID |

Examples:
```bash
msp services list --sort name
msp services list --sort pid
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

# Snapshot with network and startup
msp snapshot capture baseline --include-network --include-startup

# Sort examples
msp startup list --sort type
msp fswatch recent --sort timestamp
msp traffic summary --sort total
msp scan quick --sort severity
msp chain list --sort name
msp sharing list --sort guest
msp snapshot list --sort timestamp
msp services list --sort pid
```