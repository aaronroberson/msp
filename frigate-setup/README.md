# Frigate Camera Setup

## Quick Start

```bash
# Start Frigate
cd ~/macos-privacy-cli/frigate-setup
docker compose -f docker-compose.frigate.yml --env-file .env up -d

# Access UI
open http://localhost:5001
```

## Camera IPs Found
| IP | Status | Notes |
|-----|---------|-------|
| `10.0.0.31` | ✅ Ping reachable | Needs RTSP credentials (port 554 closed) |
| `192.168.1.2` | ❌ Isolated | Different VLAN - needs XFINITY config |
| `192.168.1.3` | ❌ Isolated | Different VLAN - needs XFINITY config |

## 🔧 Network Fix Required

For `192.168.1.x` cameras to be accessible:

1. Go to XFINITY admin: `http://10.0.0.1`
2. Navigate to **Gateway > Connection > Wi-Fi Settings**
3. **Disable** "AP Isolation" or "Client Isolation"
4. Ensure all devices use the **same WiFi band** (2.4GHz or 5GHz)

## Configuration

Edit `config/config.yml` to add your RTSP credentials:
```yaml
cameras:
  camera_10g:
    ffmpeg:
      inputs:
        - path: rtsp://admin:YOUR_PASSWORD@10.0.0.31:554/stream1
```

Restart after changes:
```bash
docker compose -f docker-compose.frigate.yml --env-file .env restart frigate
```

## Discovery Scripts

| Script | Purpose |
|--------|---------|
| `probe-cameras.py` | ONVIF camera discovery via Python |
| `simple-probe.py` | Quick network port scanner |
| `test-rtsp.sh` | Test RTSP URLs with ffmpeg |
| `find-cameras.sh` | Bash-based network scanner |

## Storage

Recordings stored at: `~/macos-privacy-cli/frigate-setup/storage/`

## Common RTSP URL Formats

| Brand | URL Format |
|-------|------------|
| Generic ONVIF | `rtsp://admin:pass@IP:554/stream1` |
| Reolink | `rtsp://admin:pass@IP:554/h264` |
| Amcrest | `rtsp://admin:pass@IP:554/cam/realmonitor?channel=1&subtype=0` |
| Hikvision | `rtsp://admin:pass@IP:554/Streaming/Channels/101` |