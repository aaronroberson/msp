#!/usr/bin/env python3
"""
ONVIF Camera Discovery Script for macOS
Discovers ONVIF devices on your network
"""

from onvif import ONVIFCamera
import socket
import concurrent.futures

def check_onvif(ip, port=80, user="admin", password=""):
    """Check if IP has ONVIF service"""
    try:
        cam = ONVIFCamera(ip, port, user, password)
        resp = cam.devicemgmt.GetDeviceInformation()
        print(f"✅ FOUND ONVIF CAMERA: {ip}")
        print(f"   Model: {resp.Model}")
        print(f"   Firmware: {resp.FirmwareVersion}")
        print(f"   Serial: {resp.SerialNumber}")
        return ip
    except Exception as e:
        pass
    return None

def scan_network(base_ip="10.0.0"):
    """Scan network for ONVIF cameras"""
    print(f"Scanning {base_ip}.1-{base_ip}.254 for ONVIF cameras...")
    
    # First, check if common ONVIF ports are open
    import subprocess
    
    cameras_found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = []
        for i in range(1, 255):
            ip = f"{base_ip}.{i}"
            futures.append(executor.submit(scan_ip, ip))
        
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                cameras_found.append(result)
    
    return cameras_found

def scan_ip(ip):
    """Scan single IP for ONVIF"""
    # Quick port check first
    for port in [80, 8080, 8081, 8899]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result == 0:
            # Port open, try ONVIF
            print(f"Port {port} open on {ip}, checking ONVIF...")
            return check_onvif(ip, port)
    return None

if __name__ == "__main__":
    import sys
    network = sys.argv[1] if len(sys.argv) > 1 else "10.0.0"
    scan_network(network)