#!/usr/bin/env python3
"""Network monitoring module for msp CLI."""

import os
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

from src.command import (
    setup_completion,
    suggest_command,
    interactive_menu as cmd_interactive_menu,
    interactive_select,
)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.tree import Tree
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def mask_ip(ip: str) -> str:
    """Mask sensitive parts of IP addresses."""
    if not ip or ip in ["*", "-", "::1", "localhost"]:
        return ip

    if ":" in ip:
        parts = ip.split(":")
        if len(parts) >= 2:
            return f"{parts[0]}:***"
    else:
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.*"

    return ip


@dataclass
class NetworkConnection:
    process: str
    pid: int
    user: str
    local_addr: str
    remote_addr: str
    state: str
    protocol: str = "TCP"


class NetworkMonitor:
    """Monitor network connections and ports."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def _run_cmd(self, cmd: str | list[str], sudo: bool = False, shell: bool = True) -> tuple[bool, str]:
        try:
            if sudo and isinstance(cmd, str):
                cmd = f"sudo {cmd}"
            result = subprocess.run(
                cmd, shell=shell, capture_output=True, text=True, timeout=60
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _sort_connections(self, connections: List, sort_by: str, is_listening: bool = True) -> List:
        """Sort connections by the specified key."""
        if sort_by == "port" and is_listening:
            return sorted(connections, key=lambda x: int(x.local_addr.split(":")[-1]) if ":" in x.local_addr and x.local_addr.split(":")[-1].isdigit() else 0)
        elif sort_by == "port":
            return sorted(connections, key=lambda x: int(x["local"].split(":")[-1]) if ":" in x["local"] and x["local"].split(":")[-1].isdigit() else 0)
        elif sort_by == "process":
            return sorted(connections, key=lambda x: x.process.lower() if hasattr(x, 'process') else x["process"].lower())
        elif sort_by == "pid":
            return sorted(connections, key=lambda x: x.pid if hasattr(x, 'pid') else int(x["pid"]))
        elif sort_by == "user":
            return sorted(connections, key=lambda x: x.user.lower() if hasattr(x, 'user') else x["user"].lower())
        elif sort_by == "protocol":
            return sorted(connections, key=lambda x: x.protocol if hasattr(x, 'protocol') else "")
        elif sort_by == "local":
            return sorted(connections, key=lambda x: x.local_addr.lower() if hasattr(x, 'local_addr') else x["local"].lower())
        elif sort_by == "remote":
            return sorted(connections, key=lambda x: x.remote_addr.lower() if hasattr(x, 'remote_addr') else x.get("remote", "").lower())
        return connections

    def list_listening(self, json_output: bool = False, sort_by: str = "port") -> List[NetworkConnection]:
        """List all listening ports with process info."""
        success, output = self._run_cmd(
            "lsof -iTCP -sTCP:LISTEN -nP 2>/dev/null | tail -n +2"
        )

        connections = []
        if success and output.strip():
            for line in output.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        conn = NetworkConnection(
                            process=parts[0],
                            pid=int(parts[1]),
                            user=parts[2],
                            local_addr=parts[8].split("->")[0] if "->" in parts[8] else parts[8],
                            remote_addr="",
                            state="LISTEN"
                        )
                        if "(IPv6" in parts[8]:
                            conn.protocol = "TCP6"
                        connections.append(conn)
                    except (ValueError, IndexError):
                        continue

        connections = self._sort_connections(connections, sort_by, is_listening=True)

        if json_output:
            print(json.dumps([{
                "process": c.process,
                "pid": c.pid,
                "user": c.user,
                "local": c.local_addr,
                "state": c.state,
                "protocol": c.protocol
            } for c in connections], indent=2))
            return connections

        if RICH_AVAILABLE and console:
            table = Table(title="Listening Ports")
            table.add_column("Port", style="cyan", justify="right")
            table.add_column("Process", style="green")
            table.add_column("PID", style="yellow")
            table.add_column("User", style="magenta")
            table.add_column("Protocol")

            for conn in connections:
                port = conn.local_addr.split(":")[-1] if ":" in conn.local_addr else conn.local_addr
                table.add_row(port, conn.process, str(conn.pid), conn.user, conn.protocol)
            console.print(table)
        else:
            print(f"{'Port':<8} {'Process':<20} {'PID':<8} {'User':<12} {'Proto'}")
            print("-" * 70)
            for conn in connections:
                port = conn.local_addr.split(":")[-1] if ":" in conn.local_addr else conn.local_addr
                print(f"{port:<8} {conn.process:<20} {conn.pid:<8} {conn.user:<12} {conn.protocol}")

        return connections

    def list_established(self, json_output: bool = False, sort_by: str = "process") -> List[Dict[str, str]]:
        """List all established connections."""
        success, output = self._run_cmd(
            "lsof -i -sTCP:ESTABLISHED -nP 2>/dev/null | tail -n +2"
        )

        connections = []
        if success and output.strip():
            for line in output.strip().split('\n'):
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        local = parts[8].split("->")[0] if "->" in parts[8] else parts[8]
                        remote = parts[8].split("->")[1] if "->" in parts[8] else ""
                        connections.append({
                            "process": parts[0],
                            "pid": parts[1],
                            "user": parts[2],
                            "local": local,
                            "remote": mask_ip(remote),
                        })
                    except (ValueError, IndexError):
                        continue

        connections = self._sort_connections(connections, sort_by, is_listening=False)

        if json_output:
            print(json.dumps(connections, indent=2))
            return connections

        if RICH_AVAILABLE and console:
            table = Table(title="Established Connections")
            table.add_column("Process", style="cyan")
            table.add_column("PID", style="yellow")
            table.add_column("Local", style="green")
            table.add_column("Remote", style="magenta")

            for conn in connections:
                table.add_row(
                    conn["process"],
                    conn["pid"],
                    conn["local"],
                    conn["remote"]
                )
            console.print(table)
        else:
            for conn in connections:
                print(f"{conn['process']} ({conn['pid']}): {conn['local']} -> {conn['remote']}")

        return connections

    def bandwidth_top(self, limit: int = 10, json_output: bool = False, sort_by: str = "total") -> List[Dict[str, Any]]:
        """Show top bandwidth consumers."""
        success, output = self._run_cmd(
            "nettop -J process_name,bytes_in,bytes_out -L 1 -x 2>/dev/null | tail -n +2"
        )

        processes = []
        if success and output.strip():
            for line in output.strip().split('\n'):
                parts = line.split(',')
                if len(parts) >= 3:
                    try:
                        proc_name = parts[0].strip()
                        bytes_in = int(parts[1].strip()) if parts[1].strip() else 0
                        bytes_out = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip() else 0
                        if proc_name and (bytes_in > 0 or bytes_out > 0):
                            processes.append({
                                "process": proc_name,
                                "bytes_in": bytes_in,
                                "bytes_out": bytes_out,
                                "total": bytes_in + bytes_out
                            })
                    except (ValueError, IndexError):
                        continue

        if sort_by == "total":
            processes.sort(key=lambda x: x["total"], reverse=True)
        elif sort_by == "in":
            processes.sort(key=lambda x: x["bytes_in"], reverse=True)
        elif sort_by == "out":
            processes.sort(key=lambda x: x["bytes_out"], reverse=True)
        elif sort_by == "process":
            processes.sort(key=lambda x: x["process"].lower())

        processes = processes[:limit]

        if json_output:
            print(json.dumps(processes, indent=2))
            return processes

        if RICH_AVAILABLE and console:
            table = Table(title=f"Top {limit} Bandwidth Consumers")
            table.add_column("Process", style="cyan")
            table.add_column("↓ In", style="green", justify="right")
            table.add_column("↑ Out", style="yellow", justify="right")
            table.add_column("Total", style="magenta", justify="right")

            for p in processes:
                def fmt(b):
                    if b > 1_000_000_000:
                        return f"{b/1_000_000_000:.1f}GB"
                    elif b > 1_000_000:
                        return f"{b/1_000_000:.1f}MB"
                    elif b > 1_000:
                        return f"{b/1_000:.1f}KB"
                    return f"{b}B"
                table.add_row(p["process"], fmt(p["bytes_in"]), fmt(p["bytes_out"]), fmt(p["total"]))
            console.print(table)
        else:
            for p in processes:
                print(f"{p['process']}: ↓{p['bytes_in']} ↑{p['bytes_out']}")

        return processes

    def kill_process(self, pid: int, force: bool = False) -> bool:
        """Kill a process by PID."""
        confirm = ""
        if not force:
            try:
                success, output = self._run_cmd(
                    ["ps", "-o", "comm=", "-p", str(pid)], shell=False
                )
                if success and output.strip():
                    confirm = input(f"Kill process {pid} ({output.strip()})? [y/N] ")
            except (ValueError, subprocess.CalledProcessError):
                pass

        if force or confirm.lower() in ['y', 'yes']:
            try:
                os.kill(pid, 9)
                print(f"Killed process {pid}")
                return True
            except ProcessLookupError:
                print(f"Process {pid} not found")
            except PermissionError:
                print(f"Permission denied to kill {pid}")
        else:
            print("Cancelled")

        return False

    def lookup(self, host: str) -> List[str]:
        """DNS lookup for a host."""
        success, output = self._run_cmd(f"dig +short {host} 2>/dev/null")
        if success and output.strip():
            ips = [ip.strip() for ip in output.strip().split('\n') if ip.strip()]
            for ip in ips:
                print(f"{host} -> {ip}")
            return ips
        else:
            print(f"No DNS records for {host}")
            return []

    def list_devices_arp(self, limit: int = 20, json_output: bool = False) -> List[Dict[str, str]]:
        """List network devices discovered via ARP cache.

        Uses: arp -a | grep -E '([0-9]{1,3}\.){3}[0-9]{1,3}'
        """
        success, output = self._run_cmd("arp -a 2>/dev/null")

        devices = []
        if success and output.strip():
            # Parse ARP output: ? (192.168.1.1) at (xx:xx:xx:xx:xx:xx) on en0 ifscope [ethernet]
            arp_pattern = re.compile(r'\(([\d.]+)\)\s+at\s+([0-9a-f:]+)\s+on\s+(\w+)')
            for line in output.strip().split('\n'):
                # Also filter for IP addresses
                if re.search(r'([0-9]{1,3}\.){3}[0-9]{1,3}', line):
                    match = arp_pattern.search(line)
                    if match:
                        ip, mac, interface = match.groups()
                        devices.append({
                            "ip": mask_ip(ip),
                            "mac": mac,
                            "interface": interface,
                            "status": "reachable"
                        })

        # Sort by IP
        devices = sorted(devices, key=lambda x: x["ip"])[:limit]

        if json_output:
            print(json.dumps(devices, indent=2))
            return devices

        if RICH_AVAILABLE and console:
            table = Table(title="Network Devices (ARP Cache)")
            table.add_column("IP", style="cyan")
            table.add_column("MAC Address", style="green")
            table.add_column("Interface", style="yellow")
            table.add_column("Status", style="magenta")

            for d in devices:
                table.add_row(d["ip"], d["mac"], d["interface"], d["status"])
            console.print(table)
        else:
            print(f"{'IP':<18} {'MAC Address':<18} {'Interface':<12} {'Status'}")
            print("-" * 70)
            for d in devices:
                print(f"{d['ip']:<18} {d['mac']:<18} {d['interface']:<12} {d['status']}")

        return devices

    def nmap_scan(self, target: str = None, ports: str = None, subnet: str = None, json_output: bool = False, sudo: bool = False, scan_type: str = "default", ping_scan: bool = False, check_http: bool = False) -> List[Dict[str, Any]]:
        """Scan network for open ports using nmap.

        Uses: nmap -p <ports> <target> --open
        Default ports: 554 (RTSP), 80 (HTTP), 8080 (HTTP-alt), 8899 (Roku)
        scan_type: 'default' uses ports param, 'cameras' uses camera-specific ports
        ping_scan: If True, runs nmap -sn (host discovery only)
        check_http: If True, performs HTTP check on discovered hosts
        """
        # Set ports based on scan type if not provided
        if ports is None and scan_type == "cameras":
            ports = "554,80,8080,8899,5541,8000,8554,8888,9000,1900"  # RTSP, ONVIF, HTTP camera ports
        elif ports is None:
            ports = "554,80,8080,8899"
        # Determine target - auto-detect local subnet if not provided
        scan_target = target
        if not scan_target:
            if subnet:
                scan_target = subnet
            else:
                # Try to detect local network
                success, output = self._run_cmd("route get default 2>/dev/null | grep interface")
                if success and output.strip():
                    iface = output.strip().split()[-1] if output.strip() else "en0"
                else:
                    iface = "en0"

                # Get IP and derive subnet
                success, output = self._run_cmd(f"ipconfig getifaddr {iface} 2>/dev/null")
                if success and output.strip():
                    ip_parts = output.strip().split('.')
                    if len(ip_parts) == 4:
                        scan_target = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
                    else:
                        scan_target = "10.0.0.0/24"  # fallback
                else:
                    scan_target = "10.0.0.0/24"  # fallback

        # Build nmap command
        if ping_scan:
            cmd = f"nmap -sn {scan_target} 2>&1"
            if self.verbose:
                print(f"Ping scanning {scan_target}...")
        else:
            cmd = f"nmap -p {ports} {scan_target} --open 2>&1"
            if self.verbose:
                print(f"Scanning {scan_target} for open ports {ports}...")

        success, output = self._run_cmd(cmd, sudo=sudo)

        results = []
        if ping_scan:
            # Parse ping scan output - just list live hosts
            host_pattern = re.compile(r'^Nmap scan report for ([\d.]+)', re.MULTILINE)
            host_up_pattern = re.compile(r'Host is up')
            for line in output.strip().split('\n'):
                host_match = host_pattern.search(line)
                if host_match:
                    ip = host_match.group(1)
                    results.append({"ip": mask_ip(ip), "originIp": ip, "ports": [], "status": "alive"})
        elif "open" in output.lower() or "report" in output.lower():
            # Parse port scan output
            host_pattern = re.compile(r'^Nmap scan report for ([\d.]+)', re.MULTILINE)
            port_pattern = re.compile(r'(\d+)/tcp\s+open\s+(\w+)(?:\s+(.+?))?$')

            current_host = None
            for line in output.strip().split('\n'):
                line = line.strip()
                host_match = host_pattern.search(line)
                if host_match:
                    current_host = host_match.group(1)
                    if current_host not in [r.get("ip") for r in results]:
                        results.append({"ip": mask_ip(current_host), "ports": []})

                port_match = port_pattern.search(line)
                if port_match and current_host:
                    port, state, service = port_match.groups()
                    for r in results:
                        if r["ip"] == mask_ip(current_host) or r["ip"] == current_host:
                            r["ports"].append({"port": int(port), "service": service or "unknown"})

        # HTTP check if requested
        if check_http and results:
            for r in results:
                # Use originIp if available, otherwise try to unmask
                original_ip = r.get("originIp", r["ip"].replace(".*", ""))
                http_cmd = f"curl -s --connect-timeout 2 -o /dev/null -w '%{{http_code}}' http://{original_ip}/ 2>/dev/null"
                _, http_out = self._run_cmd(http_cmd)
                if http_out.strip() and http_out.strip() != "000":
                    r["http_status"] = http_out.strip()
                else:
                    r["http_status"] = "none"

        if json_output:
            print(json.dumps(results, indent=2))
            return results

        # Truncate long target strings for display
        display_target = scan_target if len(scan_target) <= 40 else scan_target[:37] + "..."

        if RICH_AVAILABLE and console:
            table = Table(title=f"Nmap Scan Results ({display_target})")
            table.add_column("IP", style="cyan")
            if ping_scan:
                if check_http:
                    table.add_column("Status", style="green")
                    table.add_column("HTTP", style="yellow")
                else:
                    table.add_column("Status", style="green")
            else:
                table.add_column("Open Ports", style="green")
                table.add_column("Services", style="yellow")

            for r in results:
                if ping_scan:
                    if check_http:
                        table.add_row(r["ip"], r.get("status", "alive"), r.get("http_status", "none"))
                    else:
                        table.add_row(r["ip"], r.get("status", "alive"))
                else:
                    ports_str = ", ".join(str(p["port"]) for p in r["ports"]) if r["ports"] else "none"
                    services_str = ", ".join(p["service"] for p in r["ports"]) if r["ports"] else "-"
                    table.add_row(r["ip"], ports_str, services_str)
            console.print(table)
        else:
            print(f"\nNmap scan results for {display_target}:")
            print("-" * 50)
            for r in results:
                if ping_scan:
                    if check_http:
                        print(f"{r['ip']}: {r.get('status', 'alive')} (HTTP: {r.get('http_status', 'none')})")
                    else:
                        print(f"{r['ip']}: {r.get('status', 'alive')}")
                else:
                    ports_str = ", ".join(str(p["port"]) for p in r["ports"]) if r["ports"] else "none"
                    print(f"{r['ip']}: {ports_str}")

        return results

    def get_local_subnet(self) -> str:
        """Detect local network subnet."""
        success, output = self._run_cmd("route get default 2>/dev/null | grep interface")
        if success and output.strip():
            iface = output.strip().split()[-1]
        else:
            iface = "en0"

        success, output = self._run_cmd(f"ipconfig getifaddr {iface} 2>/dev/null")
        if success and output.strip():
            ip_parts = output.strip().split('.')
            if len(ip_parts) == 4:
                return f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24"
        return "10.0.0.0/24"


def interactive_menu(monitor: NetworkMonitor, json_output: bool = False):
    """Interactive menu for network management."""
    actions = [
        ("1", "list", "List listening ports"),
        ("2", "established", "List established connections"),
        ("3", "top", "Show top bandwidth consumers"),
        ("4", "kill", "Kill a process by PID"),
        ("5", "lookup", "DNS lookup"),
        ("6", "arp", "List network devices (ARP)"),
        ("7", "hosts", "Discover live hosts (nmap -sn)"),
        ("8", "nmap", "Scan network (nmap)"),
    ]

    sort_options = {
        "list": ["port", "process", "pid", "user", "protocol"],
        "established": ["process", "pid", "user", "local", "remote"],
        "top": ["total", "in", "out", "process"],
        "arp": ["ip", "mac", "interface"],
        "hosts": ["ip"],
        "nmap": ["ip", "ports"],
    }
    current_sort = {"list": "port", "established": "process", "top": "total", "arp": "ip", "hosts": "ip", "nmap": "ip"}

    while True:
        action = cmd_interactive_menu([
            ("1", "list", "List listening ports"),
            ("2", "established", "List established connections"),
            ("3", "top", "Show top bandwidth consumers"),
            ("4", "kill", "Kill a process by PID"),
            ("5", "lookup", "DNS lookup"),
            ("6", "arp", "List network devices (ARP)"),
            ("7", "hosts", "Discover live hosts (nmap -sn)"),
            ("8", "nmap", "Scan network (nmap)"),
            ("s", "sort", "Change sort order"),
        ], title="Network Monitor - Interactive Mode")

        if action is None:
            print("Goodbye!")
            break

        if action == "s":
            sortable_actions = [a for a in actions if a[1] in sort_options]
            cmd_items = [(a[1], f"{a[2]} (current: {current_sort[a[1]]})", None) for a in sortable_actions]
            cmd_val = interactive_select(cmd_items, title="Select command to change sort for")
            if cmd_val:
                cmd = cmd_val[0]
                opts = sort_options[cmd]
                opt_items = [(o, o + (" *" if o == current_sort[cmd] else ""), None) for o in opts]
                sort_val = interactive_select(opt_items, title="Sort options")
                if sort_val:
                    current_sort[cmd] = sort_val[0]
                    print(f"Sort set to: {current_sort[cmd]}")
            continue

        if action == "list":
            monitor.list_listening(json_output=json_output, sort_by=current_sort["list"])
        elif action == "established":
            monitor.list_established(json_output=json_output, sort_by=current_sort["established"])
        elif action == "top":
            monitor.bandwidth_top(json_output=json_output, sort_by=current_sort["top"])
        elif action == "kill":
            pid = input("PID to kill: ").strip()
            if pid.isdigit():
                monitor.kill_process(int(pid))
            else:
                print("Invalid PID")
        elif action == "lookup":
            host = input("Host to lookup: ").strip()
            if host:
                monitor.lookup(host)
            else:
                print("Host required")
        elif action == "arp":
            limit = input("Limit (default 20): ").strip()
            limit = int(limit) if limit.isdigit() else 20
            monitor.list_devices_arp(limit=limit, json_output=json_output)
        elif action == "hosts":
            target = input("Target subnet (blank for auto-detect): ").strip() or None
            monitor.nmap_scan(target=target, ports="", json_output=json_output, ping_scan=True)
        elif action == "nmap":
            target = input("Target subnet (blank for auto-detect): ").strip() or None
            ping_only = input("Ping scan only? (y/N): ").strip().lower() == 'y'
            ports = input("Ports (default 554,80,8080,8899): ").strip() or "554,80,8080,8899"
            monitor.nmap_scan(target=target, ports=ports, json_output=json_output, ping_scan=ping_only)

        input("\nPress Enter to continue...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Network Monitor")
    parser.add_argument("action", nargs="?", choices=["list", "established", "top", "kill", "lookup", "arp", "nmap", "hosts"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("--pid", type=int, help="PID for kill command")
    parser.add_argument("--host", help="Host for lookup command")
    parser.add_argument("--limit", type=int, default=20, help="Limit for arp command")
    parser.add_argument("--target", help="Target subnet for nmap (e.g., 192.168.1.0/24)")
    parser.add_argument("--ports", default="554,80,8080,8899", help="Ports for nmap scan (default: 554,80,8080,8899)")
    parser.add_argument("--sudo", action="store_true", help="Use sudo for nmap scan (may be required for full port scan)")
    parser.add_argument("--scan-type", choices=["default", "cameras"], help="Scan type: default (custom ports) or cameras (RTSP/Web camera ports)")
    parser.add_argument("--ping-scan", action="store_true", help="Ping scan only (discover live hosts, no port scan)")
    parser.add_argument("--check-http", action="store_true", help="Check HTTP status on discovered hosts")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--sort", choices=["port", "process", "pid", "user", "protocol", "local", "remote", "total", "in", "out"], help="Sort by: port, process, pid, user, protocol, local, remote, total, in, out")
    setup_completion(parser)
    args = parser.parse_args()

    monitor = NetworkMonitor(verbose=args.verbose)

    if not args.action:
        interactive_menu(monitor, args.json)
        return

    if args.action == "list":
        monitor.list_listening(json_output=args.json, sort_by=args.sort or "port")
    elif args.action == "established":
        monitor.list_established(json_output=args.json, sort_by=args.sort or "process")
    elif args.action == "top":
        monitor.bandwidth_top(limit=args.limit, json_output=args.json, sort_by=args.sort or "total")
    elif args.action == "kill":
        if not args.pid:
            print("Error: --pid required for kill")
            sys.exit(1)
        monitor.kill_process(args.pid, force=args.force)
    elif args.action == "lookup":
        if not args.host:
            print("Error: --host required for lookup")
            sys.exit(1)
        monitor.lookup(args.host)
    elif args.action == "arp":
        monitor.list_devices_arp(limit=args.limit, json_output=args.json)
    elif args.action == "nmap":
        scan_type = getattr(args, 'scan_type', 'default')
        ping_scan = getattr(args, 'ping_scan', False)
        check_http = getattr(args, 'check_http', False)
        if scan_type == "cameras":
            ports = "554,80,8080,8899,5541,8000,8554,8888,9000,1900"
        else:
            ports = args.ports or "554,80,8080,8899"
        monitor.nmap_scan(target=args.target, ports=ports, json_output=args.json, sudo=args.sudo, ping_scan=ping_scan, check_http=check_http)
    elif args.action == "hosts":
        check_http = getattr(args, 'check_http', False)
        monitor.nmap_scan(target=args.target, ports="", json_output=args.json, sudo=args.sudo, ping_scan=True, check_http=check_http)


if __name__ == "__main__":
    main()