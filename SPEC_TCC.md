# SPEC: TCC (Transparency, Consent, and Control) Module

## Overview
Manage macOS app permissions (camera, microphone, screen recording, accessibility, full disk access, contacts, calendars, etc.) via the TCC database.

## CLI Interface

### Command Structure
```
msp tcc <subcommand> [options]
```

### Subcommands

| Subcommand | Arguments | Options | Description |
|------------|-----------|---------|-------------|
| `list` | — | `--service <name>`, `--client <bundle-id>`, `--json`, `--sort <key>` | List all TCC permissions |
| `show` | `<service>` | `--client <bundle-id>`, `--json` | Show permissions for a specific service |
| `grant` | `<service> <bundle-id>` | `--type allow/deny`, `--json` | Grant or revoke permission |
| `revoke` | `<service> <bundle-id>` | `--json` | Revoke permission (alias for grant --type deny) |
| `reset` | `<service>` | `[<bundle-id>]`, `--json` | Reset permissions for service (all or specific app) |
| `backup` | — | `--output <file>`, `--json` | Export TCC database to JSON |
| `restore` | `<file>` | `--json` | Import TCC database from JSON |
| `audit` | — | `--json`, `--sort <key>` | Find over-permissive apps |

### Services (TCC Service Names)

| Service Key | Display Name | Description |
|-------------|--------------|-------------|
| `kTCCServiceCamera` | Camera | Camera access |
| `kTCCServiceMicrophone` | Microphone | Microphone access |
| `kTCCServiceScreenCapture` | Screen Recording | Screen capture/recording |
| `kTCCServiceAccessibility` | Accessibility | Accessibility API access |
| `kTCCServiceAllFiles` | Full Disk Access | Full disk access |
| `kTCCServiceContacts` | Contacts | Contacts access |
| `kTCCServiceCalendars` | Calendars | Calendars access |
| `kTCCServiceReminders` | Reminders | Reminders access |
| `kTCCServicePhotos` | Photos | Photos library access |
| `kTCCServiceBluetooth` | Bluetooth | Bluetooth access |
| `kTCCServiceLocalNetwork` | Local Network | Local network access |
| `kTCCServiceFilesAndFolders` | Files and Folders | File/folder access |
| `kTCCServiceSpeechRecognition` | Speech Recognition | Speech recognition |
| `kTCCServiceSiri` | Siri | Siri/Dictation |
| `kTCCServiceDeveloperTool` | Developer Tools | Developer tool access |
| `kTCCServiceInputMonitoring` | Input Monitoring | Keyboard/mouse monitoring |
| `kTCCServiceSystemPolicyAllFiles` | System Policy All Files | System policy - all files |
| `kTCCServiceSystemPolicySysAdminFiles` | System Policy SysAdmin Files | System policy - sysadmin files |
| `kTCCServiceSystemPolicyDesktopFolder` | Desktop Folder | Desktop folder access |
| `kTCCServiceSystemPolicyDocumentsFolder` | Documents Folder | Documents folder access |
| `kTCCServiceSystemPolicyDownloadsFolder` | Downloads Folder | Downloads folder access |
| `kTCCServiceSystemPolicyNetworkVolumes` | Network Volumes | Network volumes access |
| `kTCCServiceSystemPolicyRemovableVolumes` | Removable Volumes | Removable volumes access |

**Short aliases:** `camera`, `microphone`, `screen`, `accessibility`, `fulldisk`, `contacts`, `calendars`, `reminders`, `photos`, `bluetooth`, `localnetwork`, `files`, `speech`, `siri`, `developer`, `input`, `allfiles`, `sysadmin`, `desktop`, `documents`, `downloads`, `networkvolumes`, `removable`

### Sort Keys (for list/audit)

| Key | Description |
|-----|-------------|
| `service` | Service name |
| `client` | Bundle identifier |
| `client_name` | App display name |
| `allowed` | Permission status (allowed first) |
| `prompt_count` | Number of prompts |
| `last_modified` | Last modification time |

### Output Format

**JSON Structure (list/show):**
```json
[
  {
    "service": "kTCCServiceCamera",
    "service_name": "Camera",
    "client": "com.apple.Terminal",
    "client_name": "Terminal",
    "client_type": "bundle",
    "auth_value": 2,
    "allowed": true,
    "prompt_count": 1,
    "last_modified": "2024-01-15T10:30:00Z",
    "csreq": "<base64-encoded-cdhash>"
  }
]
```

**auth_value meanings:**
- `0` = not determined (never prompted)
- `1` = denied
- `2` = allowed
- `3` = limited (Files and Folders only)

## Implementation Details

### TCC Database Locations

1. **User database:** `~/Library/Application Support/com.apple.TCC/TCC.db`
2. **System database:** `/Library/Application Support/com.apple.TCC/TCC.db` (requires sudo)

### Schema (TCC.db)
```sql
CREATE TABLE access (
    service TEXT NOT NULL,
    client TEXT NOT NULL,
    client_type INTEGER NOT NULL,  -- 0 = bundle, 1 = path
    auth_value INTEGER NOT NULL,   -- 0=not determined, 1=denied, 2=allowed, 3=limited
    auth_reason INTEGER,
    auth_version INTEGER,
    csreq BLOB,                    -- Code signing requirement (CDHash)
    policy_id INTEGER,
    indirect_object_identifier TEXT,
    indirect_object_identifier_type INTEGER,
    flags INTEGER,
    last_modified INTEGER,         -- Unix timestamp
    last_reminded INTEGER,
    prompt_count INTEGER,
    PRIMARY KEY (service, client, client_type)
);
```

### Key Operations

**List permissions:**
```sql
SELECT service, client, client_type, auth_value, csreq, last_modified, prompt_count
FROM access
WHERE service LIKE ? AND client LIKE ?
ORDER BY service, client;
```

**Grant/Revoke:**
```sql
-- Requires TCC.db write access (sudo for system, user for user db)
-- Better: use `tccutil` command-line tool
tccutil reset <service> [<bundle-id>]  -- Reset
# For grant: no direct CLI, must use MDM profile or TCC.db manipulation
```

**Backup:**
- Dump both user and system databases to JSON

**Restore:**
- Import JSON to TCC.db (requires appropriate privileges)

### Permission Mapping

| auth_value | Display | Meaning |
|------------|---------|---------|
| 0 | `not-determined` | Never prompted |
| 1 | `denied` | User denied |
| 2 | `allowed` | User allowed |
| 3 | `limited` | Files and Folders - limited access |

### Client Types

| client_type | Description |
|-------------|-------------|
| 0 | Bundle ID (e.g., `com.apple.Terminal`) |
| 1 | Path (e.g., `/usr/bin/ssh`) |

## Interactive Mode

When run without subcommand, enters interactive menu:

```
TCC Manager - Interactive Mode
1. list         - List all permissions
2. show         - Show permissions for a service
3. grant        - Grant permission
4. revoke       - Revoke permission
5. reset        - Reset permissions
6. backup       - Backup TCC database
7. restore      - Restore TCC database
8. audit        - Audit for over-permissive apps
q. quit
```

## Dependencies

- **Required:** `sqlite3` (built-in), `tccutil` (macOS built-in)
- **Optional:** `python3` with `sqlite3` module (built-in)

## Error Handling

- Database locked → Retry with timeout
- Permission denied → Suggest `sudo` for system database
- Invalid service → Show valid service list
- Invalid bundle ID → Validate format

## Security Considerations

- Modifying TCC.db directly requires SIP disabled or special entitlements
- Prefer `tccutil` for reset operations
- Grant/revoke via MDM profile is the supported Apple method
- Direct SQLite writes are unsupported and may break with OS updates
- Always backup before modifications

## Testing

Test on:
- macOS 13+ (Ventura, Sonoma, Sequoia)
- Both user and system TCC databases
- Various services (camera, microphone, accessibility, fulldisk)
- Apps with different client types (bundle vs path)