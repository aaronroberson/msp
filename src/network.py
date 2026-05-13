#!/usr/bin/env python3
"""Network monitoring module for msp CLI."""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

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

    def _run_cmd(self, cmd: str, sudo: bool = False) -> tuple[bool, str]:
        try:
            if sudo:
                cmd = f"sudo {cmd}"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def list_listening(self, json_output: bool = False) -> List[NetworkConnection]:
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

    def list_established(self, json_output: bool = False) -> List[Dict[str, str]]:
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

    def bandwidth_top(self, limit: int = 10, json_output: bool = False) -> List[Dict[str, Any]]:
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

        processes.sort(key=lambda x: x["total"], reverse=True)
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
                success, output = self._run_cmd(f"ps -o comm= -p {pid}")
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


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Network Monitor")
    parser.add_argument("action", choices=["list", "established", "top", "kill", "lookup"])
    parser.add_argument("--pid", type=int, help="PID for kill command")
    parser.add_argument("--host", help="Host for lookup command")
    parser.add_argument("--limit", type=int, default=10, help="Limit for top command")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    monitor = NetworkMonitor(verbose=args.verbose)

    if args.action == "list":
        monitor.list_listening(json_output=args.json)
    elif args.action == "established":
        monitor.list_established(json_output=args.json)
    elif args.action == "top":
        monitor.bandwidth_top(limit=args.limit, json_output=args.json)
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


if __name__ == "__main__":
    main()