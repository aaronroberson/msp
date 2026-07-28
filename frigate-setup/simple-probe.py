#!/usr/bin/env python3
"""Simple ONVIF camera discovery without WSDL dependency"""

import socket
import requests
from requests.auth import HTTPDigestAuth, HTTPBasicAuth

CAMERAS = [
    "10.0.0.31",
    "192.168.1.2", 
    "192.168.1.3",
]

CREDS = [
    ("admin", "admin"),
    ("admin", ""),
    ("admin", "password"),
    ("user", "user"),
]

def probe_http(ip, port=80):
    """Probe HTTP endpoints on cameras"""
    endpoints = [
        "/",
        "/onvif",
        "/onvif/device_service",
        "/web",
        "/cgi-bin",
    ]
    
    for endpoint in endpoints:
        try:
            r = requests.get(f"http://{ip}:{port}{endpoint}", timeout=2, verify=False)
            if r.status_code == 200:
                # Check if it looks like a camera
                content = r.text.lower()
                if any(x in content for x in ['camera', 'onvif', 'ipcam', 'rtsp']):
                    print(f"  🔍 {endpoint} - Possible camera endpoint!")
        except:
            pass

def probe_rtsp(ip, port=554):
    """Check if RTSP port is reachable"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result == 0:
            print(f"  ✅ RTSP port {port} OPEN")
            return True
        else:
            print(f"  ❌ RTSP port {port} CLOSED")
    except Exception as e:
        print(f"  ❌ RTSP error: {e}")

print("🎯 Quick Camera Discovery\n")

for ip in CAMERAS:
    print(f"📹 {ip}:")
    probe_rtsp(ip)
    probe_http(ip, 8080)
    probe_http(ip, 80)