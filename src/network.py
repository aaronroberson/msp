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


def interactive_menu(monitor: NetworkMonitor, json_output: bool = False):
    """Interactive menu for network management."""
    actions = [
        ("1", "list", "List listening ports"),
        ("2", "established", "List established connections"),
        ("3", "top", "Show top bandwidth consumers"),
        ("4", "kill", "Kill a process by PID"),
        ("5", "lookup", "DNS lookup"),
        ("q", "quit", "Exit"),
    ]

    sort_options = {
        "list": ["port", "process", "pid", "user", "protocol"],
        "established": ["process", "pid", "user", "local", "remote"],
        "top": ["total", "in", "out", "process"],
    }
    current_sort = {"list": "port", "established": "process", "top": "total"}

    while True:
        print("\n" + "=" * 60)
        print("       Network Monitor - Interactive Mode")
        print("=" * 60)
        for key, action, desc in actions:
            print(f"  {key:>2}. {action:<12} - {desc}")
        print("  s. sort      - Change sort order")
        print("=" * 60)

        choice = input("\nSelect action [1-5, s, q]: ").strip().lower()

        if choice == "q" or choice == "quit":
            print("Goodbye!")
            break

        if choice == "s" or choice == "sort":
            print("\nSelect command to change sort for:")
            sortable_actions = [a for a in actions if a[1] in sort_options]
            for i, (key, action_name, desc) in enumerate(sortable_actions, 1):
                print(f"  {i}. {desc} (current: {current_sort[action_name]})")
            cmd_choice = input(f"\nSelect [1-{len(sortable_actions)}]: ").strip()
            try:
                cmd_idx = int(cmd_choice) - 1
                if 0 <= cmd_idx < len(sortable_actions):
                    cmd = sortable_actions[cmd_idx][1]
                    opts = sort_options[cmd]
                    print(f"\nSort options for {sortable_actions[cmd_idx][2]}:")
                    for i, opt in enumerate(opts, 1):
                        marker = " *" if opt == current_sort[cmd] else ""
                        print(f"  {i}. {opt}{marker}")
                    sort_choice = input(f"\nSelect sort [1-{len(opts)}]: ").strip()
                    idx = int(sort_choice) - 1
                    if 0 <= idx < len(opts):
                        current_sort[cmd] = opts[idx]
                        print(f"Sort set to: {current_sort[cmd]}")
                    else:
                        print("Invalid choice")
                else:
                    print("Invalid choice")
            except ValueError:
                print("Invalid choice")
            continue

        action_map = {
            "1": "list",
            "2": "established",
            "3": "top",
            "4": "kill",
            "5": "lookup",
        }

        if choice in action_map:
            action = action_map[choice]
        elif choice in [a[1] for a in actions]:
            action = choice
        else:
            print(f"Invalid choice: {choice}")
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

        input("\nPress Enter to continue...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Network Monitor")
    parser.add_argument("action", nargs="?", choices=["list", "established", "top", "kill", "lookup"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("--pid", type=int, help="PID for kill command")
    parser.add_argument("--host", help="Host for lookup command")
    parser.add_argument("--limit", type=int, default=10, help="Limit for top command")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--sort", choices=["port", "process", "pid", "user", "protocol", "local", "remote", "total", "in", "out"], help="Sort by: port, process, pid, user, protocol, local, remote, total, in, out")
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


if __name__ == "__main__":
    main()