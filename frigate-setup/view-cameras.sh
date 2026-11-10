#!/bin/bash
# View network cameras directly via RTSP (no Frigate needed).
# Usage: ./view-cameras.sh [camera_ip]   (default: 10.0.0.31)
set -euo pipefail

CAM_IP="${1:-10.0.0.31}"
USER="${CAM_USER:-admin}"
PASS="${CAM_PASS:-admin}"
URL="rtsp://${USER}:${PASS}@${CAM_IP}:554/stream1"

echo "Waiting for RTSP on ${CAM_IP}:554 ..."
until nc -z -G 2 "$CAM_IP" 554 2>/dev/null; do
  sleep 3
done
echo "RTSP is up — opening stream: $URL"
echo "(press q in the window to quit)"
exec ffplay -rtsp_transport tcp -fflags nobuffer -flags low_delay "$URL"
