#!/usr/bin/env python3
"""Traffic analyzer module for msp CLI."""

import os
import json
import subprocess
import sys
from typing import List, Dict, Any, Optional
import threading
import time

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def mask_sensitive(data: str) -> str:
    """Mask sensitive data in output."""
    import re
    data = re.sub(r'Bearer [^\s]+', 'Bearer ***', data)
    data = re.sub(r'Authorization: [^\s]+', 'Authorization: ***', data)
    data = re.sub(r'cookie[=:][^\s;]+', 'cookie=***', data, flags=re.IGNORECASE)
    data = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.(\d{1,3})\b', r'***.***.***.\1', data)
    return data


class TrafficAnalyzer:
    """Analyze network traffic."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._running = False

    def _run_cmd(self, cmd: str, sudo: bool = False, timeout: int = 30) -> tuple[bool, str]:
        try:
            if sudo:
                cmd = f"sudo {cmd}"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _sort_processes(self, processes: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
        """Sort processes by the specified key."""
        if sort_by == "total":
            return sorted(processes, key=lambda x: x["total"], reverse=True)
        elif sort_by == "in":
            return sorted(processes, key=lambda x: x["bytes_in"], reverse=True)
        elif sort_by == "out":
            return sorted(processes, key=lambda x: x["bytes_out"], reverse=True)
        elif sort_by == "process":
            return sorted(processes, key=lambda x: x["process"].lower())
        return processes

    def summary(self, limit: int = 10, json_output: bool = False, sort_by: str = "total") -> List[Dict[str, Any]]:
        """Show top bandwidth consumers."""
        success, output = self._run_cmd("nettop -J process_name,bytes_in,bytes_out -L 1 2>/dev/null")

        processes = []
        if success and output.strip():
            for line in output.strip().split('\n'):
                parts = line.split(',')
                if len(parts) >= 3:
                    try:
                        name = parts[0].strip()
                        b_in = int(parts[1].strip()) if parts[1].strip().isdigit() else 0
                        b_out = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else 0
                        if name and (b_in > 0 or b_out > 0):
                            processes.append({
                                "process": name,
                                "bytes_in": b_in,
                                "bytes_out": b_out,
                                "total": b_in + b_out
                            })
                    except (ValueError, IndexError):
                        continue

        processes = self._sort_processes(processes, sort_by)
        processes = processes[:limit]

        if json_output:
            print(json.dumps(processes, indent=2))
            return processes

        def fmt(b):
            if b > 1_000_000_000:
                return f"{b/1_000_000_000:.1f}GB"
            elif b > 1_000_000:
                return f"{b/1_000_000:.1f}MB"
            elif b > 1_000:
                return f"{b/1_000:.1f}KB"
            return f"{b}B"

        if RICH_AVAILABLE and console:
            table = Table(title=f"Top {limit} Bandwidth Consumers")
            table.add_column("Process", style="cyan")
            table.add_column("↓ In", style="green", justify="right")
            table.add_column("↑ Out", style="yellow", justify="right")
            table.add_column("Total", style="magenta", justify="right")
            for p in processes:
                table.add_row(p["process"], fmt(p["bytes_in"]), fmt(p["bytes_out"]), fmt(p["total"]))
            console.print(table)
        else:
            for p in processes:
                print(f"{p['process']:<30} ↓{fmt(p['bytes_in']):<12} ↑{fmt(p['bytes_out']):<12}")

        return processes

    def dns(self, count: int = 20, json_output: bool = False) -> List[Dict[str, str]]:
        """Capture DNS queries."""
        print(f"Capturing {count} DNS queries (requires sudo)...\n")
        success, output = self._run_cmd(
            f"sudo tcpdump -n -c {count} port 53 2>/dev/null",
            sudo=True, timeout=60
        )

        queries = []
        if success and output.strip():
            for line in output.strip().split('\n'):
                parts = line.split()
                for i, p in enumerate(parts):
                    if "A?" in p or "AAAA?" in p:
                        try:
                            domain = p.replace("A?", "").replace("AAAA?", "")
                            queries.append({"domain": domain, "query_type": "A" if "A?" in p else "AAAA"})
                        except (ValueError, IndexError):
                            continue

        if json_output:
            print(json.dumps(queries, indent=2))
            return queries

        if queries:
            if RICH_AVAILABLE and console:
                table = Table(title="DNS Queries")
                table.add_column("Domain", style="cyan")
                table.add_column("Type", style="yellow")
                for q in queries:
                    table.add_row(q["domain"], q["query_type"])
                console.print(table)
            else:
                print("DNS Queries:")
                for q in queries:
                    print(f"  {q['domain']} ({q['query_type']})")
        else:
            print("No DNS queries captured. Run with sudo or check if tcpdump is working.")

        return queries

    def http(self, count: int = 50, json_output: bool = False, sort_by: str = "host") -> List[Dict[str, str]]:
        """Capture HTTP/HTTPS traffic summary."""
        print(f"Capturing HTTP/HTTPS traffic ({count} packets)...\n")

        if not self._which("tshark"):
            print("Wireshark (tshark) not installed. Install with: brew install wireshark")
            print("\nFalling back to basic analysis...")
            return self._http_fallback(count, json_output)

        success, output = self._run_cmd(
            f"sudo tshark -Y 'http or tls' -T fields -e ip.src -e ip.dst -e http.host -e tls.handshake.extensions_server_name -c {count} 2>/dev/null",
            sudo=True, timeout=60
        )

        requests = []
        if success and output.strip():
            for line in output.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) >= 2:
                    src, dst = parts[0], parts[1]
                    host = parts[2] if len(parts) > 2 else ""
                    sni = parts[3] if len(parts) > 3 else ""
                    domain = host or sni or f"{dst}:443"
                    requests.append({
                        "source": mask_sensitive(src),
                        "destination": mask_sensitive(dst),
                        "host": mask_sensitive(domain)
                    })

        if sort_by == "host":
            requests.sort(key=lambda x: x["host"].lower())
        elif sort_by == "source":
            requests.sort(key=lambda x: x["source"].lower())
        elif sort_by == "destination":
            requests.sort(key=lambda x: x["destination"].lower())

        if json_output:
            print(json.dumps(requests, indent=2))
            return requests

        if requests:
            if RICH_AVAILABLE and console:
                table = Table(title="HTTP/HTTPS Requests")
                table.add_column("Source", style="cyan")
                table.add_column("Destination", style="magenta")
                table.add_column("Host", style="green")
                for r in requests:
                    table.add_row(r["source"], r["destination"], r["host"][:50] if r["host"] else "-")
                console.print(table)
            else:
                for r in requests:
                    print(f"{r['source']} -> {r['destination']} ({r['host']})")
        else:
            print("No HTTP/HTTPS traffic captured.")

        return requests

    def _http_fallback(self, count: int, json_output: bool) -> List[Dict[str, str]]:
        """Fallback HTTP analysis using lsof."""
        success, output = self._run_cmd(
            "lsof -iTCP -sTCP:ESTABLISHED -nP 2>/dev/null | head -20"
        )

        requests = []
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        local = parts[8].split("->")[0] if "->" in parts[8] else ""
                        remote = parts[8].split("->")[1] if "->" in parts[8] else ""
                        requests.append({
                            "process": parts[0],
                            "local": local,
                            "remote": mask_sensitive(remote)
                        })
                    except (ValueError, IndexError):
                        continue

        if json_output:
            print(json.dumps(requests, indent=2))
        else:
            print("Established connections (HTTPS traffic):")
            for r in requests:
                print(f"  {r['process']}: {r['local']} -> {r['remote']}")

        return requests

    def _which(self, cmd: str) -> bool:
        success, _ = self._run_cmd(f"which {cmd}")
        return success

    def capture(self, count: int = 100, output_file: str = "/tmp/msp_capture.pcap", json_output: bool = False) -> str:
        """Capture network packets."""
        print(f"Capturing {count} packets...")
        print(f"Saving to: {output_file}")

        success, output = self._run_cmd(
            f"sudo tcpdump -c {count} -w {output_file} 2>&1",
            sudo=True, timeout=120
        )

        if success or os.path.exists(output_file):
            print(f"Capture saved to {output_file}")

            if json_output:
                return output_file

            print("\nAnalyzing capture...")
            self._analyze_pcap(output_file)
            return output_file

        print(f"Capture failed: {output}")
        return ""

    def _analyze_pcap(self, pcap_file: str) -> None:
        """Analyze captured packets."""
        if self._which("tshark"):
            success, output = self._run_cmd(
                f"tshark -r {pcap_file} -T fields -e ip.src -e ip.dst -e _ws.col.Protocol -e _ws.col.Info 2>/dev/null | head -30"
            )
            if success and output.strip():
                print("\nPacket summary:")
                for line in output.strip().split('\n')[:20]:
                    print(f"  {line}")
        else:
            success, output = self._run_cmd(
                f"sudo tcpdump -r {pcap_file} -n 2>/dev/null | head -20"
            )
            if success and output.strip():
                print("\nPacket summary:")
                print(mask_sensitive(output))

    def stream(self, duration: int = 30, filter_expr: str = "") -> None:
        """Stream live traffic."""
        print(f"Streaming traffic for {duration} seconds...")
        print("Press Ctrl+C to stop early.\n")

        cmd = f"sudo tcpdump -n -l -i any {filter_expr}".strip()
        cmd = f"timeout {duration} {cmd}"

        try:
            proc = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, text=True
            )

            count = 0
            for line in proc.stdout:
                if count >= 100:
                    break
                print(mask_sensitive(line.strip()))
                count += 1

        except KeyboardInterrupt:
            print("\nStopped.")
        except Exception as e:
            print(f"Stream error: {e}")


def interactive_menu(analyzer: TrafficAnalyzer, json_output: bool = False):
    """Interactive menu for traffic analyzer."""
    actions = [
        ("1", "summary", "Show top bandwidth consumers"),
        ("2", "dns", "Capture DNS queries"),
        ("3", "http", "Capture HTTP/HTTPS traffic"),
        ("4", "capture", "Capture packets to file"),
        ("5", "stream", "Stream live traffic"),
        ("q", "quit", "Exit"),
    ]

    sort_options = {
        "summary": ["total", "in", "out", "process"],
        "http": ["host", "source", "destination"],
    }
    current_sort = {"summary": "total", "http": "host"}

    while True:
        print("\n" + "=" * 60)
        print("       Traffic Analyzer - Interactive Mode")
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
            "1": "summary",
            "2": "dns",
            "3": "http",
            "4": "capture",
            "5": "stream",
        }

        if choice in action_map:
            action = action_map[choice]
        elif choice in [a[1] for a in actions]:
            action = choice
        else:
            print(f"Invalid choice: {choice}")
            continue

        if action == "summary":
            analyzer.summary(json_output=json_output, sort_by=current_sort["summary"])
        elif action == "dns":
            count = input("Packet count [20]: ").strip()
            count = int(count) if count.isdigit() else 20
            analyzer.dns(count=count, json_output=json_output)
        elif action == "http":
            count = input("Packet count [50]: ").strip()
            count = int(count) if count.isdigit() else 50
            analyzer.http(count=count, json_output=json_output, sort_by=current_sort["http"])
        elif action == "capture":
            count = input("Packet count [100]: ").strip()
            count = int(count) if count.isdigit() else 100
            output = input("Output file [/tmp/msp_capture.pcap]: ").strip() or "/tmp/msp_capture.pcap"
            analyzer.capture(count=count, output_file=output, json_output=json_output)
        elif action == "stream":
            duration = input("Duration seconds [30]: ").strip()
            duration = int(duration) if duration.isdigit() else 30
            filter_expr = input("BPF filter (optional): ").strip()
            analyzer.stream(duration=duration, filter_expr=filter_expr)

        input("\nPress Enter to continue...")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Traffic Analyzer")
    parser.add_argument("action", nargs="?", choices=["summary", "dns", "http", "capture", "stream"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("--count", type=int, default=100, help="Packet count")
    parser.add_argument("--output", default="/tmp/msp_capture.pcap", help="Output file")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds")
    parser.add_argument("--filter", default="", help="BPF filter expression")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--sort", choices=["total", "in", "out", "process", "host", "source", "destination"], help="Sort by: total, in, out, process, host, source, destination")
    args = parser.parse_args()

    analyzer = TrafficAnalyzer(verbose=args.verbose)

    if not args.action:
        interactive_menu(analyzer, args.json)
        return

    if args.action == "summary":
        analyzer.summary(json_output=args.json, sort_by=args.sort or "total")
    elif args.action == "dns":
        analyzer.dns(count=args.count, json_output=args.json)
    elif args.action == "http":
        analyzer.http(count=args.count, json_output=args.json, sort_by=args.sort or "host")
    elif args.action == "capture":
        analyzer.capture(count=args.count, output_file=args.output, json_output=args.json)
    elif args.action == "stream":
        analyzer.stream(duration=args.duration, filter_expr=args.filter)


if __name__ == "__main__":
    main()