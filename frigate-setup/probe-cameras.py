#!/usr/bin/env python3
"""Quick ONVIF camera probe for known camera IPs"""

from onvif import ONVIFCamera
import warnings
warnings.filterwarnings("ignore", message="urllib3")

CAMERAS = [
    ("10.0.0.31", 80),    # Same subnet
    ("192.168.1.2", 80),  # Isolated subnet
    ("192.168.1.3", 80),  # Isolated subnet
]

# Common credential combinations
CREDS = [
    ("admin", "admin"),
    ("admin", ""),
    ("admin", "password"),
    ("user", "user"),
    ("admin", "12345"),
]

print("🎯 Probing ONVIF cameras...")

for ip, port in CAMERAS:
    print(f"\n📹 Testing {ip}:")
    for user, passwd in CREDS:
        try:
            cam = ONVIFCamera(ip, port, user, passwd, encrypt=False)
            info = cam.devicemgmt.GetDeviceInformation()
            print(f"  ✅ SUCCESS with {user}:{passwd}")
            print(f"     Model: {info.Model}")
            print(f"     Firmware: {info.FirmwareVersion}")
            
            # Get stream URIs
            media = cam.create_media_service()
            profiles = media.GetProfiles()
            if profiles:
                stream_uri = media.GetStreamUri({'StreamProfileToken': profiles[0].token})
                print(f"     RTSP: {stream_uri.Uri}")
            break
        except Exception as e:
            error = str(e)[:50].replace('\n', ' ')
            # Only show if it's not just connection refused
            if "timed out" not in error.lower() and "connection" not in error.lower():
                print(f"  ❌ {user}:{passwd} - {error}")