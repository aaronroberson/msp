# msp - macOS Security & Privacy CLI

A comprehensive security and privacy CLI for macOS that combines native commands, Homebrew tools, and local AI (via Ollama) for real-time monitoring and threat detection.

## Features

- **Network Monitoring** - View ports, connections, bandwidth usage, **network devices (ARP)**, **port scanning (nmap)**
- **Startup Management** - Control launch agents, daemons, login items, cron
- **File Watching** - Real-time filesystem monitoring
- **Traffic Analysis** - DNS queries, HTTP traffic, packet capture
- **Security Scanner** - Code signatures, Gatekeeper, heuristic detection
- **Volume & File Forensics** - External drive inspection, AppleDouble (._*) parsing, extended attribute extraction (quarantine, provenance, AVKit keys), Spotlight store inspection, and local Mac host correlation
- **AI Integration** - Local AI-powered analysis via `ollama`, **OpenVINO USB acceleration support**
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
msp net arp             # Network devices via ARP cache
msp net arp --limit 20  # Limit output (default: 20)
msp net hosts           # Discover live hosts on network (nmap -sn)
msp net nmap            # Scan for open ports (auto-detect subnet)
msp net nmap --ports 80,443,8080  # Custom ports
msp net nmap --target 192.168.1.0/24  # Custom target subnet
msp net nmap --scan-type cameras  # Camera-specific ports (RTSP, ONVIF, HTTP)
msp net nmap --ping-scan     # Host discovery only (no port scan)
msp net nmap --check-http    # Check HTTP status on discovered hosts
msp net nmap --sudo     # Use sudo for full scan (may be required)
```

### Startup Items (`msp startup`)
```bash
msp startup list        # All startup items
msp startup agents      # User agents only
msp startup daemons     # System daemons
msp startup cron        # Cron jobs
msp startup disable <label>  # Disable item
msp startup audit       # Audit for HIGH/MEDIUM risk items
msp startup audit --interactive  # Review and disable each item
msp startup summary     # Quick count of items by risk level
msp startup search <term>  # Find items by name/label
```

**Audit filters out:** Apple services, common apps (Spotify, Slack, VSCode, etc.), known-good prefixes. Only flags actual concerns with risk level (HIGH/MEDIUM/REVIEW).

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
msp ask watch                 # Interactive monitoring mode
msp ask suggest               # Hardening suggestions
msp ask devices               # List available AI devices (checks OpenVINO USB)
```

Providers (auto-detected in order):
1. **openai** - Cloud API (requires `OPENAI_API_KEY`)
2. **ollama** - Local LLM (default, requires `ollama serve`)
3. **apfel** - Apple Intelligence fallback (`brew install apfel`)
4. **openvino** - Intel USB accelerators (`pip install openvino`)

Note: `msp ask` automatically includes network context (established connections, listening ports) for network-related questions. Requires `ollama serve` to be running (or `apfel` as fallback).

### AI Model Configuration

The default model is **`qwen2.5-coder:1.5b`** — an ultra-small code-specialized model (~1GB RAM) that runs on any Mac without crashing. Configure via environment variables:

```bash
# Use a larger model (requires more RAM):
export OLLAMA_MODEL="llama3.2"

# Point to a remote Ollama instance:
export OLLAMA_BASE_URL="http://192.168.1.100:11434"

# Explicit provider selection:
export MSP_LLM_PROVIDER="apfel"    # Apple Intelligence fallback
export MSP_LLM_PROVIDER="openai"   # Requires OPENAI_API_KEY
export MSP_LLM_PROVIDER="local"    # Offline heuristic (no LLM needed)
export MSP_LLM_PROVIDER="openvino"  # Intel OpenVINO with USB acceleration

# OpenVINO device selection (when using openvino provider):
export OPENVINO_DEVICE="NPU"      # Intel Neural Compute Stick 2
export OPENVINO_DEVICE="GPU"       # Intel GPU
export OPENVINO_DEVICE="CPU"       # Force CPU
export OPENVINO_DEVICE="AUTO"      # Auto-detect (default)
```

Usage hints:
- **First time**: `ollama pull qwen2.5-coder:1.5b` (downloads ~1GB)
- **Start server**: `ollama serve` (runs in background)
- **Check memory**: If your system feels sluggish, try `ollama pull granite-code:3b` (3B, ~2GB) or stick with the default 1.5B
- **No Ollama?** apfel serves as automatic fallback if installed
- **USB Acceleration**: Install OpenVINO (`pip install openvino`) and use `MSP_LLM_PROVIDER=openvino` for Intel NCS2/NPU devices

### Method Chaining (`msp chain`)
```bash
msp chain list            # List available chains
msp chain run <name>       # Run a chain
msp chain run daily --prompt "flag issues"  # With AI analysis
msp chain define suspicious "net established | startup audit | scan suspicious"
msp chain watch daily      # Repeat monitoring with alerts
msp chain delete <name>    # Delete custom chain
```

### Forensics (`msp forensics`)
Inspect external volumes, USB drives, SD cards, and hidden macOS metadata sidecars.

```bash
msp forensics                           # Launch interactive menu
msp forensics scan "/Volumes/NO NAME"   # Scan volume for AppleDoubles & xattrs
msp forensics correlate "/Volumes/NO NAME"  # Correlate drive evidence against local Mac
msp forensics spotlight "/Volumes/NO NAME"  # Inspect external Spotlight OS build stores
msp forensics inspect "/path/to/._file" # Deeply inspect a specific ._* AppleDouble file
msp forensics clean "/Volumes/NO NAME" --dry-run  # Preview stray artifact cleanup
msp forensics clean "/Volumes/NO NAME" --force    # Remove stray metadata artifacts (orphaned ._*, .DS_Store)
```

**Forensic capabilities include:**
- **AppleDouble (`._*`) Parser**: Reads binary headers, 32-byte FinderInfo, and `ATTR` extended attribute blocks directly.
- **Quarantine Decoder**: Extracts originating application/agent, hex timestamps, UTC/local date conversion, and UUIDs.
- **Provenance Decoder**: Extracts process lineage tokens and creation UUIDs.
- **AVKit Scrubbing Keys**: Extracts thumbnail cache identifiers and AES encryption keys.
- **Multi-Vector Host Correlator**: Cross-references volume findings against macOS install receipts (`InstallHistory.plist`), LaunchServices SharedFileList recent documents (`.sfl4`), and QuickTime Player sandboxed preferences.


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
| ollama | Local LLM inference server (privacy-first AI) | ✓ |
| apfel | Apple Intelligence from CLI (local on-device) | Prompt |
| exiftool | Image, audio, video metadata & camera forensics | Prompt |
| processmonitor | Process monitoring (Objective-See) | Prompt |
| knockknock | Startup scanner (Objective-See) | Prompt |
| wireshark | Packet analyzer (tshark CLI) | Prompt |
| somo | Network monitor | Prompt |
| nmap | Network scanner for device discovery | Prompt |
| openvino | Intel AI acceleration (USB/NPU) | Prompt |

## Privacy

- All data stays local (Ollama runs on-device open-source models)
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

### Network Device Discovery
```bash
msp net arp                 # List devices on your network via ARP cache
msp net nmap              # Scan for open ports (RTSP, HTTP, Roku default ports)
msp ask "analyze my network devices" --data <(msp net arp)  # AI analysis of ARP results
```

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