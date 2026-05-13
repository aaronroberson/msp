# msp - macOS Security & Privacy CLI

A comprehensive security and privacy CLI for macOS that combines native commands, Homebrew tools, and Apple Intelligence (via apfel) for real-time monitoring and threat detection.

## Features

- **Network Monitoring** - View ports, connections, bandwidth usage
- **Startup Management** - Control launch agents, daemons, login items, cron
- **File Watching** - Real-time filesystem monitoring
- **Traffic Analysis** - DNS queries, HTTP traffic, packet capture
- **Security Scanner** - Code signatures, Gatekeeper, heuristic detection
- **AI Integration** - Apple Intelligence-powered analysis via `apfel`
- **Method Chaining** - Build and run custom monitoring workflows
- **Dependency Manager** - Auto-install required tools

## Quick Start

```bash
# First run - check/install dependencies
msp doctor

# View security status
msp status

# List all commands
msp --help
```

## Installation

```bash
# Symlink to PATH
ln -s ~/macos-privacy-cli/main.py ~/bin/msp

# Add to PATH (if not already)
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

## Commands

### Core
```bash
msp status              # Full security dashboard (firewall, encryption, sharing, services, lock)
msp list                # List privacy settings
msp list --category Firewall
msp enable <setting>    # Enable a setting
msp disable <setting>   # Disable a setting
msp presets list        # List presets
msp presets apply <name>  # Apply a preset
```

**`msp status` includes:**
- Firewall: enabled, stealth mode, auto-allow settings, exceptions
- Encryption: FileVault status
- App Security: Gatekeeper
- Wireless: Bluetooth, Captive Portal Probe
- Sharing: daemon status, share points with guest access
- Network Services: HIGH/MEDIUM risk services with ports and connection types
- Screen Lock: idle time, password requirement
- Last scan time and report location
- Active snapshot watch status

### Snapshots
```bash
msp snapshot capture [name]     # Save current settings to snapshot
msp snapshot list               # List all snapshots
msp snapshot diff <name>        # Compare current vs snapshot
msp snapshot restore <name>     # Restore settings from snapshot
msp snapshot restore <name> --dry-run  # Preview restore
msp snapshot watch <name>       # Monitor snapshot drift
msp snapshot watch <name> --auto-restore  # Auto-restore on drift
msp snapshot delete <name>     # Delete a snapshot
```

**`msp status` shows:**
- Firewall: enabled/disabled, stealth mode, auto-allow settings, exceptions, connection rules
- FileVault, Gatekeeper, Bluetooth, Captive Portal Probe status
- Last security scan time and report location
- Active snapshot watch status and monitored snapshot name

### Network (`msp net`)
```bash
msp net list            # Listening ports + processes
msp net established      # Active connections
msp net top              # Per-process bandwidth
msp net kill <pid>       # Kill process
msp net lookup <host>    # DNS lookup
```

### Startup Items (`msp startup`)
```bash
msp startup list        # All startup items
msp startup agents      # User agents only
msp startup daemons     # System daemons
msp startup cron        # Cron jobs
msp startup disable <label>  # Disable item
msp startup audit       # Check for suspicious items
```

### File Monitoring (`msp fswatch`)
```bash
msp fswatch watch <path>   # Watch directory (requires fswatch)
msp fswatch recent [sec]    # Recent events (last N seconds)
msp fswatch system          # Monitor system directories
msp fswatch new [dir]       # Recently created files
msp fswatch audit           # Audit system directories
```

### Traffic Analysis (`msp traffic`)
```bash
msp traffic summary    # Top bandwidth consumers
msp traffic dns         # DNS queries
msp traffic http        # HTTP/HTTPS traffic
msp traffic capture     # Packet capture
msp traffic stream      # Live traffic stream
```

### Security Scanner (`msp scan`)
```bash
msp scan quick          # Fast 30s scan
msp scan deep           # Comprehensive scan (5min)
msp scan suspicious     # Heuristic detection
msp scan verify <app>   # Gatekeeper check
msp scan signature <app> # Code signature info
msp scan report         # Generate report
```

### AI Integration (`msp ask`)
```bash
msp ask "what's suspicious in my processes?"           # Direct query
msp ask "analyze my connections"                      # Auto-includes network data
msp ask "explain firewall settings"                    # Explain specific settings
msp ask watch               # Interactive monitoring mode
msp ask suggest             # Hardening suggestions
```

Note: `msp ask` automatically includes network context (established connections, listening ports) for network-related questions.

### Method Chaining (`msp chain`)
```bash
msp chain list            # List available chains
msp chain run <name>       # Run a chain
msp chain run daily --prompt "flag issues"  # With AI analysis
msp chain define suspicious "net established | startup audit | scan suspicious"
msp chain watch daily      # Repeat monitoring with alerts
msp chain delete <name>    # Delete custom chain
```

## Presets

Apply security configurations from security guides:

| Preset | Description |
|--------|-------------|
| `basic` | Essential security (firewall, stealth mode, gatekeeper) |
| `paranoid` | Maximum privacy |
| `drduh` | Based on drduh/macOS-Security-and-Privacy-Guide |
| `term7` | Based on term7/MacOS-Privacy-and-Security-Enhancements |

```bash
msp presets apply basic
msp presets apply paranoid --dry-run
```

## Dependencies

Run `msp doctor` to check and install dependencies.

| Package | Description | Auto-install |
|---------|-------------|--------------|
| fswatch | File system watcher | ✓ |
| apfel | Apple Intelligence | ✓ (already installed) |
| processmonitor | Process monitoring (Objective-See) | Prompt |
| knockknock | Startup scanner (Objective-See) | Prompt |
| wireshark | Packet analyzer (tshark CLI) | Prompt |
| somo | Network monitor | Prompt |

## Privacy

- All data stays local (apfel is onboard Apple Intelligence)
- Sensitive data (IPs, hostnames) are masked in output
- No outbound network calls
- No telemetry or analytics

## Configuration

```bash
~/.msp/
├── chains.json     # User-defined chains
├── baselines/      # Saved snapshots for comparison
└── reports/        # Generated reports
```

## Built-in Chains

| Chain | Steps |
|-------|-------|
| `suspicious` | net established → startup audit → scan suspicious |
| `daily` | net list → net established → startup list → traffic summary |
| `audit` | scan deep → startup audit → fswatch audit → ai suggest |

## Examples

### Daily Security Check
```bash
msp chain run daily
```

### Investigate Suspicious Process
```bash
msp net established
msp net kill 12345
```

### Watch for Changes
```bash
msp chain watch audit --interval 300  # Every 5 minutes
```

### AI Analysis
```bash
msp scan quick | msp ask "analyze these findings"
msp ask suggest
```

## License

MIT - Use at your own risk.