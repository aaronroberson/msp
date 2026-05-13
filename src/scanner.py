#!/usr/bin/env python3
"""Security scanner module for msp CLI."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


@dataclass
class Finding:
    severity: str
    category: str
    item: str
    description: str
    recommendation: str
    data: Optional[Dict[str, Any]] = None


class SecurityScanner:
    """Scan for security issues."""

    SUSPICIOUS_PORTS = list(range(60000, 65535))
    SUSPICIOUS_PATTERNS = ["update", "helper", "agent", "daemon", "service",
                           "monitor", "scanner", "sync", "backup", "cloud",
                           "telemetry", "analytics", "tracking"]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.findings: List[Finding] = []

    def _run_cmd(self, cmd: str, sudo: bool = False) -> tuple[bool, str]:
        try:
            if sudo:
                cmd = f"sudo {cmd}"
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=120
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)

    def _is_apple_signed(self, path: str) -> bool:
        success, output = self._run_cmd(f"codesign -dvvv '{path}' 2>/dev/null")
        if success and "Apple" in output:
            return True
        return False

    def scan_quick(self, json_output: bool = False) -> List[Finding]:
        """Quick 30-second scan."""
        self.findings = []
        print("Running quick security scan...")

        self._check_listening_ports()
        self._check_established_connections()
        self._check_system_updates()

        return self._display_findings(json_output)

    def scan_deep(self, json_output: bool = False) -> List[Finding]:
        """Deep 5-minute comprehensive scan."""
        self.findings = []
        print("Running deep security scan...")

        self._check_listening_ports()
        self._check_established_connections()
        self._check_system_updates()
        self._check_startup_items()
        self._check_file_permissions()
        self._check_code_signatures()
        self._check_recent_files()
        self._check_telemetry()

        return self._display_findings(json_output)

    def scan_suspicious(self, json_output: bool = False) -> List[Finding]:
        """Heuristic suspicious activity detection."""
        self.findings = []
        print("Scanning for suspicious activity...")

        self._check_unusual_ports()
        self._check_unsigned_network()
        self._check_new_persistence()
        self._check_suspicious_process_names()

        return self._display_findings(json_output)

    def _check_listening_ports(self) -> None:
        success, output = self._run_cmd("lsof -iTCP -sTCP:LISTEN -nP 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 8:
                    try:
                        port = int(parts[8].split(":")[-1])
                        if port > 60000 and port < 65535:
                            self.findings.append(Finding(
                                severity="medium",
                                category="Network",
                                item=f"High port: {port}",
                                description=f"Process {parts[0]} listening on unusual port {port}",
                                recommendation="Verify this is expected behavior"
                            ))
                    except (ValueError, IndexError):
                        continue

    def _check_established_connections(self) -> None:
        success, output = self._run_cmd("lsof -i -sTCP:ESTABLISHED -nP 2>/dev/null")
        if success and output.strip():
            lines = output.strip().split('\n')[1:]
            if len(lines) > 50:
                self.findings.append(Finding(
                    severity="low",
                    category="Network",
                    item=f"Many connections: {len(lines)}",
                    description=f"System has {len(lines)} established connections",
                    recommendation="Review if this is expected"
                ))

    def _check_system_updates(self) -> None:
        success, output = self._run_cmd("softwareupdate --list 2>/dev/null")
        if success and "No updates" not in output and output.strip():
            self.findings.append(Finding(
                severity="high",
                category="System",
                item="Updates Available",
                description="System updates are available but not installed",
                recommendation="Run 'softwareupdate --install ALL' to update"
            ))

    def _check_startup_items(self) -> None:
        directories = [
            "/Library/LaunchAgents",
            "/Library/LaunchDaemons",
            os.path.expanduser("~/Library/LaunchAgents")
        ]

        for d in directories:
            if os.path.exists(d):
                for f in os.listdir(d):
                    if f.endswith('.plist'):
                        path = os.path.join(d, f)
                        success, output = self._run_cmd(f"codesign -dvvv '{path}' 2>/dev/null")
                        if success and "not signed" in output.lower():
                            self.findings.append(Finding(
                                severity="high",
                                category="Persistence",
                                item=f"Unsigned startup item: {f}",
                                description="Unsigned plist file in startup directory",
                                recommendation="Verify this is a legitimate startup item"
                            ))

    def _check_file_permissions(self) -> None:
        critical_paths = ["/etc/passwd", "/etc/sudoers", "/etc/shadow"]
        for path in critical_paths:
            if os.path.exists(path):
                stat = os.stat(path)
                mode = stat.st_mode & 0o777
                if mode & 0o002:
                    self.findings.append(Finding(
                        severity="high",
                        category="Permissions",
                        item=f"World-writable: {path}",
                        description=f"{path} is world-writable (mode {oct(mode)})",
                        recommendation="Fix permissions with: sudo chmod o-w " + path
                    ))

    def _check_code_signatures(self) -> None:
        success, output = self._run_cmd("ps aux 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 11:
                    pid = parts[1]
                    comm = parts[10] if len(parts) > 10 else ""
                    if comm and os.path.exists(comm):
                        sig_success, sig_out = self._run_cmd(f"codesign -dvvv '{comm}' 2>/dev/null")
                        if sig_success and "not signed" in sig_out.lower():
                            self.findings.append(Finding(
                                severity="medium",
                                category="Code Signing",
                                item=f"Unsigned: {os.path.basename(comm)}",
                                description="Unsigned binary running",
                                recommendation="Verify this is expected"
                            ))

    def _check_recent_files(self) -> None:
        directories = ["/Library/LaunchAgents", "/Library/LaunchDaemons", "/tmp"]
        for d in directories:
            if os.path.exists(d):
                success, output = self._run_cmd(f"find '{d}' -type f -mtime -1 2>/dev/null")
                if success and output.strip():
                    files = [f for f in output.strip().split('\n') if f]
                    if files:
                        self.findings.append(Finding(
                            severity="medium",
                            category="File System",
                            item=f"Recent files in {d}",
                            description=f"{len(files)} file(s) created/modified in last 24h",
                            recommendation="Review files if unexpected"
                        ))

    def _check_telemetry(self) -> None:
        telemetry_indicators = [
            ("analytics", "Analytics detected"),
            ("telemetry", "Telemetry detected"),
            ("crashreporter", "Crash reporter active"),
        ]
        success, output = self._run_cmd("ps aux 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n'):
                for indicator, label in telemetry_indicators:
                    if indicator in line.lower() and "apple" not in line.lower():
                        self.findings.append(Finding(
                            severity="low",
                            category="Telemetry",
                            item=label,
                            description=f"Possible telemetry process detected",
                            recommendation="Review if this telemetry is desired"
                        ))

    def _check_unusual_ports(self) -> None:
        success, output = self._run_cmd("lsof -iTCP -sTCP:LISTEN -nP 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 9:
                    try:
                        addr = parts[8]
                        port = int(addr.split(":")[-1])
                        if 4444 <= port <= 4449:
                            self.findings.append(Finding(
                                severity="high",
                                category="Network",
                                item=f"Suspicious port: {port}",
                                description="Common malware/debugging port detected",
                                recommendation="Investigate this process immediately"
                            ))
                    except (ValueError, IndexError):
                        continue

    def _check_unsigned_network(self) -> None:
        success, output = self._run_cmd("lsof -i -nP 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 7:
                    pid = parts[1]
                    comm = parts[0]
                    sig_success, sig_out = self._run_cmd(
                        f"codesign -dvvv -p {pid} 2>/dev/null"
                    )
                    if sig_success and "not signed" in sig_out.lower():
                        self.findings.append(Finding(
                            severity="medium",
                            category="Network",
                            item=f"Unsigned network access: {comm}",
                            description="Unsigned process with network access",
                            recommendation="Verify this application is legitimate"
                        ))

    def _check_new_persistence(self) -> None:
        directories = ["/Library/LaunchAgents", "/Library/LaunchDaemons"]
        for d in directories:
            if os.path.exists(d):
                success, output = self._run_cmd(
                    f"find '{d}' -name '*.plist' -mtime -1 2>/dev/null"
                )
                if success and output.strip():
                    for f in output.strip().split('\n'):
                        if f:
                            self.findings.append(Finding(
                                severity="medium",
                                category="Persistence",
                                item=f"New item: {os.path.basename(f)}",
                                description="New persistence mechanism installed in last 24h",
                                recommendation="Verify this installation is intentional"
                            ))

    def _check_suspicious_process_names(self) -> None:
        success, output = self._run_cmd("ps aux 2>/dev/null")
        if success and output.strip():
            for line in output.strip().split('\n')[1:]:
                parts = line.split()
                if len(parts) >= 11:
                    comm = parts[10] if len(parts) > 10 else ""
                    if comm:
                        name = os.path.basename(comm).lower()
                        for pattern in self.SUSPICIOUS_PATTERNS:
                            if pattern in name and "apple" not in name:
                                self.findings.append(Finding(
                                    severity="low",
                                    category="Process",
                                    item=f"Suspicious name: {name}",
                                    description=f"Process name contains '{pattern}'",
                                    recommendation="Verify this process is expected"
                                ))
                                break

    def verify_app(self, app_path: str) -> bool:
        """Verify an app with Gatekeeper."""
        if not os.path.exists(app_path):
            app_path = f"/Applications/{app_path}.app" if not app_path.endswith(".app") else app_path

        print(f"Verifying: {app_path}")
        success, output = self._run_cmd(f"spctl --assess --type exec --verbose=2 '{app_path}' 2>&1")
        
        if success and ("accepted" in output.lower() or "pass" in output.lower()):
            print("✓ App is verified and allowed to run")
            return True
        else:
            print("✗ App verification failed or was rejected")
            if output:
                print(f"Output: {output}")
            return False

    def signature_info(self, app_path: str) -> Dict[str, str]:
        """Get code signature information for an app."""
        if not os.path.exists(app_path):
            app_path = f"/Applications/{app_path}.app" if not app_path.endswith(".app") else app_path

        print(f"Checking signature: {app_path}")
        success, output = self._run_cmd(f"codesign -dvvv '{app_path}' 2>&1")

        info = {"path": app_path, "valid": False, "signed": False, "details": ""}

        if success and output.strip():
            info["details"] = output.strip()
            info["signed"] = "signed" in output.lower() and "not signed" not in output.lower()
            info["valid"] = "valid" in output.lower() and "invalid" not in output.lower()

            if "Apple" in output:
                info["authority"] = "Apple"
            elif "Developer ID" in output:
                info["authority"] = "Developer ID"
            else:
                info["authority"] = "Unknown"

        if json_output:
            print(json.dumps(info, indent=2))

        return info

    def _display_findings(self, json_output: bool = False) -> List[Finding]:
        if json_output:
            output = [{
                "severity": f.severity,
                "category": f.category,
                "item": f.item,
                "description": f.description,
                "recommendation": f.recommendation
            } for f in self.findings]
            print(json.dumps(output, indent=2))
            return self.findings

        if not self.findings:
            print("No security issues found.")
            return self.findings

        severity_colors = {
            "high": "red",
            "medium": "yellow",
            "low": "cyan"
        }

        if RICH_AVAILABLE and console:
            table = Table(title="Security Findings")
            table.add_column("Severity", style="red")
            table.add_column("Category", style="cyan")
            table.add_column("Item", style="yellow")
            table.add_column("Description")

            for f in self.findings:
                color = severity_colors.get(f.severity, "white")
                table.add_row(
                    f"[{color}]{f.severity.upper()}[/{color}]",
                    f.category,
                    f.item[:40],
                    f.description[:60]
                )
            console.print(table)

            print("\nRecommendations:")
            for f in self.findings:
                print(f"  • {f.item}: {f.recommendation}")
        else:
            print(f"\nFound {len(self.findings)} security issue(s):\n")
            for f in self.findings:
                print(f"[{f.severity.upper()}] {f.category}: {f.item}")
                print(f"  {f.description}")
                print(f"  → {f.recommendation}\n")

        return self.findings

    def generate_report(self, output_file: str = None) -> str:
        """Generate a comprehensive security report."""
        self.scan_deep()
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "scan_type": "comprehensive",
            "findings_count": len(self.findings),
            "findings": [{
                "severity": f.severity,
                "category": f.category,
                "item": f.item,
                "description": f.description,
                "recommendation": f.recommendation
            } for f in self.findings]
        }

        if output_file:
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"Report saved to: {output_file}")

        return json.dumps(report, indent=2)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Security Scanner")
    parser.add_argument("action", choices=["quick", "deep", "suspicious", "verify", "signature", "report"])
    parser.add_argument("path", nargs="?", help="Path to verify/signature check")
    parser.add_argument("--output", help="Output file for report")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    scanner = SecurityScanner(verbose=args.verbose)

    if args.action == "quick":
        scanner.scan_quick(json_output=args.json)
    elif args.action == "deep":
        scanner.scan_deep(json_output=args.json)
    elif args.action == "suspicious":
        scanner.scan_suspicious(json_output=args.json)
    elif args.action == "verify":
        if not args.path:
            print("Error: path required")
            sys.exit(1)
        scanner.verify_app(args.path)
    elif args.action == "signature":
        if not args.path:
            print("Error: path required")
            sys.exit(1)
        scanner.signature_info(args.path)
    elif args.action == "report":
        output = args.output or os.path.expanduser("~/.msp/reports/scan_report.json")
        scanner.generate_report(output)


if __name__ == "__main__":
    main()