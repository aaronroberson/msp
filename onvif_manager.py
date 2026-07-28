#!/usr/bin/env python3
"""
ONVIF Device Manager - Native Python for macOS
Discover, connect to, and manage ONVIF cameras
"""

import socket
import argparse
from onvif_zeep_async import ONVIFCamera


def discover_devices(network="192.168.1.0/24"):
    """Discover ONVIF devices on network via WS-Discovery"""
    print(f"Discovering ONVIF devices on {network}...")
    print("(Requires ONVIF devices to respond to multicast discovery)")
    print()


def connect_device(ip, port=8080, user="admin", password="12345"):
    """Connect to an ONVIF device"""
    try:
        camera = ONVIFCamera(ip, port, user, password)
        print(f"✓ Connected to {ip}:{port}")
        return camera
    except Exception as e:
        print(f"✗ Failed to connect: {e}")
        return None


def get_device_info(camera):
    """Fetch device information"""
    try:
        info = camera.devicemgmt.GetDeviceInformation()
        print(f"\nDevice Information:")
        print(f"  Manufacturer: {info['Manufacturer']}")
        print(f"  Model: {info['Model']}")
        print(f"  Firmware: {info['FirmwareVersion']}")
        print(f"  Serial: {info['SerialNumber']}")
    except Exception as e:
        print(f"Error fetching device info: {e}")


def list_profiles(camera):
    """List available media profiles"""
    try:
        profiles = camera.media.GetProfiles()
        print(f"\nAvailable Profiles ({len(profiles)}):")
        for profile in profiles:
            print(f"  - {profile['Name']} (Token: {profile['token']})")
    except Exception as e:
        print(f"Error fetching profiles: {e}")


def get_stream_uri(camera, profile_token):
    """Get streaming URI for a profile"""
    try:
        request = camera.media.create_type('GetStreamUri')
        request['ProfileToken'] = profile_token
        request['StreamSetup'] = {
            'Stream': 'RTP-Unicast',
            'Transport': {'Protocol': 'RTSP'}
        }
        uri = camera.media.GetStreamUri(request)
        print(f"\nStream URI:")
        print(f"  {uri['Uri']}")
    except Exception as e:
        print(f"Error fetching stream URI: {e}")


def main():
    parser = argparse.ArgumentParser(description="ONVIF Device Manager")
    parser.add_argument("ip", nargs="?", help="Device IP address")
    parser.add_argument("-p", "--port", type=int, default=8080, help="ONVIF port (default: 8080)")
    parser.add_argument("-u", "--user", default="admin", help="Username (default: admin)")
    parser.add_argument("-pw", "--password", default="12345", help="Password (default: 12345)")
    parser.add_argument("--stream", action="store_true", help="Get RTSP stream URI")

    args = parser.parse_args()

    if not args.ip:
        print("ONVIF Device Manager")
        print("=" * 50)
        print("\nUsage:")
        print("  python3 onvif_manager.py <IP> [options]")
        print("\nExamples:")
        print("  python3 onvif_manager.py 192.168.1.100")
        print("  python3 onvif_manager.py 192.168.1.100 -u admin -pw password --stream")
        print("\nOptions:")
        print("  -p, --port PORT          ONVIF port (default: 8080)")
        print("  -u, --user USER          Username (default: admin)")
        print("  -pw, --password PASSWORD Password (default: 12345)")
        print("  --stream                 Get RTSP stream URI")
        return

    camera = connect_device(args.ip, args.port, args.user, args.password)
    if not camera:
        return

    get_device_info(camera)
    list_profiles(camera)

    if args.stream and camera:
        try:
            profiles = camera.media.GetProfiles()
            if profiles:
                get_stream_uri(camera, profiles[0]['token'])
        except Exception as e:
            print(f"Error getting stream: {e}")


if __name__ == "__main__":
    main()
