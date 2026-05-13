# msp Implementation Plan

## Overview
Comprehensive macOS security and privacy CLI integrating native commands, Homebrew tools, and Apple Intelligence for real-time monitoring and threat detection.

## Dependencies

| Package | Source | Required | Auto-install |
|---------|--------|----------|--------------|
| fswatch | brew | Yes | ✓ |
| processmonitor | brew cask | No | Prompt |
| knockknock | brew cask | No | Prompt |
| wireshark | brew | No | Prompt |
| somo | brew | No | Prompt |
| apfel | brew | Yes | ✓ (installed) |

## Modules

### 1. deps.py - Dependency Manager
- Check installed packages: `brew list <pkg>`
- Auto-install required deps
- On-demand install for optional deps
- Verify package integrity

### 2. network.py - Network Monitor
- `list`: `lsof -iTCP -sTCP:LISTEN -nP` → Table(Port, Process, PID, User)
- `established`: `lsof -i -sTCP:ESTABLISHED -nP` → Table(Process, Local, Remote, State)
- `top`: `nettop -J process_name,bytes_in,bytes_out` → Top 10
- `kill <pid>`: `kill <pid>` with confirmation
- Data masking: obscure last octet of remote IPs

### 3. startup.py - Startup Manager
- `list`: Parse `launchctl list` + `ls` directories
- `agents`: `~/Library/LaunchAgents`, `/Library/LaunchAgents`
- `daemons`: `/Library/LaunchDaemons`
- `cron`: `crontab -l`
- `disable <id>`: `launchctl bootout gui/$(id -u)/<id>`
- `audit`: Flag unsigned, unusual paths, suspicious names

### 4. fswatch.py - File Watcher
- `watch <path>`: `fswatch -x -o path` with colored output
- `recent [n]`: `sudo fs_usage -f filesys -t n`
- `system`: Monitor `/Library/LaunchAgents`, `/etc`
- `diff <file>`: Show last modification diff
- `new [dir]`: `find dir -mtime -1`

### 5. traffic.py - Traffic Analyzer
- `summary`: `nettop -L 1`
- `dns`: `sudo tcpdump -n port 53 -c 20`
- `http`: `tshark -Y http -T fields`
- `capture [n]`: `sudo tcpdump -c n -w /tmp/capture.pcap`
- `stream`: `sudo tcpdump -n -l`
- Data masking: strip cookies, obscure tokens

### 6. scanner.py - Security Scanner
- `quick`: Ports, processes, connections (30s)
- `deep`: + signatures, startup, file perms (5min)
- `suspicious`: Heuristics (unsigned, unusual ports, new items)
- `verify <app>`: `spctl --assess`
- `signature <app>`: `codesign -dvvv`
- `report`: JSON + human-readable

### 7. ai.py - AI Integration
- `ask "prompt"`: Call `apfel "prompt"`
- `ask "prompt" -f scan.json`: Attach file
- `analyze <module>`: Run module, pass to apfel
- `watch`: Interactive scan → analyze → prompt → act
- Privacy: All data stays local via apfel

### 8. chain.py - Method Chaining
- `define <name> "cmd1 | cmd2"`: Save to `~/.msp/chains.json`
- `list`: Show chains
- `run <name>`: Execute
- `run <name> --prompt "<prompt>"`: Execute + LLM analyze
- `delete <name>`: Remove chain
- `watch <name> --interval n`: Repeat every n seconds

## Privacy & Confirmation Rules

- **Data masking**: IPs partially obscured, paths anonymized
- **Onboard AI**: apfel stays local - no outbound calls
- **Confirmation levels**:
  - System apps: Always confirm
  - User apps: Auto-allow with warning
  - Cron/login items: Warn only

## File Structure

```
~/.msp/
├── chains.json         # User-defined chains
├── baselines/          # Snapshots for comparison
│   └── *.json
├── reports/           # Generated reports
└── config.json        # User preferences
```

## Implementation Order

1. deps.py - Dependency manager
2. network.py - Network commands
3. startup.py - Startup commands
4. fswatch.py - File watching
5. traffic.py - Traffic analysis
6. scanner.py - Security scan
7. ai.py - Apfel integration
8. chain.py - Method chaining
9. main.py - Updated dispatcher
10. Documentation