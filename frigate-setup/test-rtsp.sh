#!/bin/bash
# Test RTSP URLs on accessible camera
IP="10.0.0.31"
PASSWORDS="admin password 12345"

echo "Testing RTSP URLs on $IP..."

for path in "stream1" "h264" "stream0" "ch0/0.264" "live.sdp" "cam/realmonitor?channel=1&subtype=0" "Streaming/Channels/101" "av0_0"; do
    for pass in $PASSWORDS; do
        echo -n "Trying: rtsp://admin:$pass@$IP:554/$path ... "
        if ffmpeg -rtsp_transport tcp -i "rtsp://admin:$pass@$IP:554/$path" -frames:v 1 -f image2 /tmp/test.jpg 2>&1 | grep -q "Input"; then
            echo "SUCCESS!"
            echo "Found working URL: rtsp://admin:$pass@$IP:554/$path"
            break 2
        else
            echo "failed"
        fi
    done
done

echo "Done testing."