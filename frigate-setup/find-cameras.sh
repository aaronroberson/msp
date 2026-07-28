#!/bin/bash
# ONVIF Camera Discovery Script
# Run this to find cameras on your network

NETWORK=${1:-"10.0.0"}  # Default to 10.0.0.x

echo "🔍 Scanning for ONVIF cameras on $NETWORK.0/24..."
echo "This will take 1-2 minutes..."
echo ""

# Common ONVIF ports
PORTS="554,80,8080,8899,8000,8554,9000"

# Fast ping scan
echo "📡 Finding active devices..."
for i in $(seq 1 254); do
    (timeout 0.5 ping -c 1 -W 1 $NETWORK.$i > /dev/null 2>&1 && echo "Found active: $NETWORK.$i") &
    if (( $i % 50 == 0 )); then wait; fi
done
wait

echo ""
echo "📹 Checking ONVIF ports on active devices..."

# Check each found device for ONVIF ports
for ip in $(arp -a | awk '{print $2}' | tr -d '()' | grep "^$NETWORK"); do
    result=$(/opt/homebrew/bin/nmap -p $PORTS -Pn --open $ip 2>&1 | grep open)
    if [[ -n "$result" ]]; then
        echo "✅ Potential camera found: $ip"
        echo "   Ports: $result"
    fi
done

echo ""
echo "🛠️  Manual ONVIF discovery tips:"
echo "1. Check router at http://$NETWORK.1 for connected devices"
echo "2. Try ONVIF Device Manager app on Windows"
echo "3. Common ONVIF URLs to test:"
echo "   rtsp://admin:admin@$NETWORK.IP:554/stream1"
echo "   rtsp://admin:admin@$NETWORK.IP:554/h264"
echo "   rtsp://admin:admin@$NETWORK.IP:554/cam/realmonitor?channel=1&subtype=0"