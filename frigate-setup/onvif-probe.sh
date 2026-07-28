#!/bin/bash
# ONVIF Camera Discovery Script (Bash version)
# Works on macOS without additional dependencies

NETWORK=${1:-"10.0.0"}
echo "Scanning $NETWORK.1-$NETWORK.254 for cameras..."

# Common camera ports
PORTS="80,8080,8081,8899,554,8554,9000"

# Quick scan
/opt/homebrew/bin/nmap -p $PORTS -Pn --open $NETWORK.0/24 2>/dev/null | grep "report for" | while read line; do
    ip=$(echo "$line" | awk '{print $NF}')
    echo "Checking: $ip"
    
    # Try ONVIF detection endpoint
    curl -s -m 2 --connect-timeout 1 "http://$ip/onvif/device_service" -o /dev/null && echo "  🔍 ONVIF service detected!"
    
    # Try HTTP for device info
    device_info=$(curl -s -m 2 "http://$ip/" 2>/dev/null | grep -iE "camera|ipcam|onvif" | head -1)
    [[ -n "$device_info" ]] && echo "  📷 Possible camera: $device_info" | cut -c1-100
done

echo ""
echo "Done. Check results above for camera IPs."