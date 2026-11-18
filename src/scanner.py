#!/usr/bin/env python3
"""Security scanner module for msp CLI."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from src.command import (
    setup_completion,
    suggest_command,
    interactive_menu as cmd_interactive_menu,
    interactive_select,
)
from src.command import pause_for_enter
from src.state import latest_scan_bundle, reports_dir

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


# ── canonical scan bundle (~/.msp/scans/latest.json) ───────────
# The single source consumed by `msp doctor` (health surface) so that
# doctor never re-runs checks inline. Written by every scan mode.

SCAN_BUNDLE_SCHEMA = "1.0"


def scan_bundle_path() -> Path:
    return latest_scan_bundle()


def write_scan_bundle(mode: str, checks: List[Dict[str, Any]]) -> Path:
    """Persist canonical health checks. One entry per check — healthy
    ('ok'), skipped ('n/a'), or an issue with its severity."""
    path = scan_bundle_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "schema": SCAN_BUNDLE_SCHEMA,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "checks": checks,
    }
    path.write_text(json.dumps(bundle, indent=2) + "\n")
    return path


def read_latest_scan() -> Optional[Dict[str, Any]]:
    """Load the latest scan bundle, or None if missing/invalid."""
    path = scan_bundle_path()
    if not path.exists():
        return None
    try:
        bundle = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(bundle, dict) or "checks" not in bundle:
        return None
    return bundle


def collect_health_checks() -> List[Dict[str, Any]]:
    """Gather canonical health checks from all collectors.

    Single composition point: tune's checks (single implementation after
    the doctor/tune merge) + scanner's permission audit.
    """
    from src.tune import Tuner  # lazy: keep scan imports light
    tuner = Tuner()
    checks = tuner.collect_health()
    scanner = SecurityScanner()
    scanner._check_file_permissions()
    checks.extend(getattr(scanner, "permission_results", []))
    return checks


def fix_permission_issues(dry: bool = False) -> List[tuple[str, bool, str]]:
    """Apply the chmod fixes for fixable permission entries in the bundle.

    Tightening permissions on protected paths is safe and idempotent.
    Returns (name, success, message) per fixable entry; empty when no
    bundle exists.
    """
    bundle = read_latest_scan()
    if not bundle:
        return []
    results: List[tuple[str, bool, str]] = []
    for c in bundle.get("checks", []):
        if c.get("domain") != "permissions" or not c.get("fixable"):
            continue
        fix_cmd = c.get("fix_cmd", "")
        if not fix_cmd.startswith("chmod "):
            continue
        name = c.get("name", fix_cmd)
        try:
            parts = fix_cmd.split()
            mode = int(parts[1], 8)
            path = Path(parts[2])
            old = path.stat().st_mode & 0o777
            if old == mode:
                results.append((name, True, "already fixed"))
                continue
            if dry:
                results.append((name, True, f"would fix: {oct(old)} → {oct(mode)}"))
                continue
            path.chmod(mode)
            results.append((name, True, f"{oct(old)} → {oct(mode)}"))
        except (OSError, ValueError, IndexError) as e:
            results.append((name, False, str(e)))
    return results


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

    def scan_quick(self, json_output: bool = False, sort_by: str = "severity") -> List[Finding]:
        """Quick 30-second scan."""
        self.findings = []
        print("Running quick security scan...")

        self._check_listening_ports()
        self._check_established_connections()
        self._check_system_updates()

        self._persist_health("quick", json_output)
        return self._display_findings(json_output, sort_by)

    def scan_deep(self, json_output: bool = False, sort_by: str = "severity") -> List[Finding]:
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

        self._persist_health("deep", json_output)
        return self._display_findings(json_output, sort_by)

    def scan_suspicious(self, json_output: bool = False, sort_by: str = "severity") -> List[Finding]:
        """Heuristic suspicious activity detection."""
        self.findings = []
        print("Scanning for suspicious activity...")

        self._check_unusual_ports()
        self._check_unsigned_network()
        self._check_new_persistence()
        self._check_suspicious_process_names()

        self._persist_health("suspicious", json_output)
        return self._display_findings(json_output, sort_by)

    def _persist_health(self, mode: str, json_output: bool) -> None:
        """Collect health checks (single canonical source) and persist the
        scan bundle consumed by `msp doctor`."""
        try:
            checks = collect_health_checks()
            bundle_path = write_scan_bundle(mode, checks)
            if not json_output:
                print(f"Health snapshot saved to: {bundle_path}")
        except Exception as e:
            if not json_output:
                print(f"Warning: could not save health snapshot: {e}")

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
        """Check critical system paths and protected user files/dirs.

        Populates self.findings (Security Finding shape) AND
        self.permission_results (canonical check entries consumed by the
        scan bundle), so doctor can show every protected path's state.
        """
        self.permission_results: List[Dict[str, Any]] = []

        # ── critical system paths ──
        for path in ["/etc/passwd", "/etc/sudoers", "/etc/shadow"]:
            if os.path.exists(path):
                mode = os.stat(path).st_mode & 0o777
                ok = not (mode & 0o002)
                detail = f"mode {oct(mode)}"
                if ok:
                    self.permission_results.append({
                        "domain": "permissions", "name": f"Protected: {path}",
                        "status": "ok", "title": f"Protected: {path}",
                        "detail": detail, "fixable": False, "fix_cmd": "",
                    })
                else:
                    self.findings.append(Finding(
                        severity="high",
                        category="Permissions",
                        item=f"World-writable: {path}",
                        description=f"{path} is world-writable (mode {oct(mode)})",
                        recommendation="Fix permissions with: sudo chmod o-w " + path
                    ))
                    self.permission_results.append({
                        "domain": "permissions", "name": f"Protected: {path}",
                        "status": "high", "title": f"World-writable: {path}",
                        "detail": f"{detail} — must not be world-writable",
                        "fixable": False, "fix_cmd": "",
                    })

        # ── protected user paths (permissions must not exceed these) ──
        protected_user_paths = [
            (".ssh", 0o700, "SSH config directory"),
            (".ssh/id_rsa", 0o600, "SSH private key"),
            (".ssh/id_ed25519", 0o600, "SSH private key"),
            (".ssh/id_dsa", 0o600, "SSH private key"),
            (".ssh/id_ecdsa", 0o600, "SSH private key"),
            (".gnupg", 0o700, "GPG keyring"),
            (".aws", 0o700, "AWS credentials"),
            (".netrc", 0o600, "Network credentials"),
            (".kube/config", 0o600, "Kubernetes credentials"),
            (".zsh_history", 0o600, "Shell history"),
        ]
        for rel, expected, what in protected_user_paths:
            path = Path.home() / rel
            if not path.exists():
                self.permission_results.append({
                    "domain": "permissions", "name": f"Protected: ~/{rel}",
                    "status": "n/a", "title": f"Protected: ~/{rel}",
                    "detail": f"{what} not present — skipped",
                    "fixable": False, "fix_cmd": "",
                })
                continue
            mode = path.stat().st_mode & 0o777
            group_world = mode & 0o077
            world_writable = bool(mode & 0o002)
            if world_writable:
                sev = "high"
                issue = f"~/{rel} is world-writable (mode {oct(mode)})"
                fix = f"chmod {oct(expected)[2:]} {path}"
                self.findings.append(Finding(
                    severity="high", category="Permissions",
                    item=f"World-writable: ~/{rel}",
                    description=f"{what} at ~/{rel} is world-writable.",
                    recommendation=f"Fix permissions with: {fix}"
                ))
            elif group_world:
                sev = "medium"
                issue = f"~/{rel} readable by group/others (mode {oct(mode)})"
                fix = f"chmod {oct(expected)[2:]} {path}"
                self.findings.append(Finding(
                    severity="medium", category="Permissions",
                    item=f"Over-permissive: ~/{rel}",
                    description=f"{what} at ~/{rel} should be {oct(expected)}, is {oct(mode)}.",
                    recommendation=f"Fix permissions with: {fix}"
                ))
            else:
                self.permission_results.append({
                    "domain": "permissions", "name": f"Protected: ~/{rel}",
                    "status": "ok", "title": f"Protected: ~/{rel}",
                    "detail": f"{what} — mode {oct(mode)} OK",
                    "fixable": False, "fix_cmd": "",
                })
                continue
            self.permission_results.append({
                "domain": "permissions", "name": f"Protected: ~/{rel}",
                "status": sev, "title": issue,
                "detail": f"{what}: expected {oct(expected)}, found {oct(mode)} — fix with {fix}",
                "fixable": True, "fix_cmd": fix,
            })

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

    def signature_info(self, app_path: str, json_output: bool = False) -> Dict[str, str]:
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

    def _sort_findings(self, findings: List[Finding], sort_by: str) -> List[Finding]:
        """Sort findings by the specified key."""
        if sort_by == "severity":
            severity_order = {"high": 0, "medium": 1, "low": 2}
            return sorted(findings, key=lambda x: severity_order.get(x.severity, 3))
        elif sort_by == "category":
            return sorted(findings, key=lambda x: x.category.lower())
        elif sort_by == "item":
            return sorted(findings, key=lambda x: x.item.lower())
        return findings

    def _display_findings(self, json_output: bool = False, sort_by: str = "severity") -> List[Finding]:
        findings = self._sort_findings(self.findings, sort_by)

        if json_output:
            output = [{
                "severity": f.severity,
                "category": f.category,
                "item": f.item,
                "description": f.description,
                "recommendation": f.recommendation
            } for f in findings]
            print(json.dumps(output, indent=2))
            return self.findings

        if not findings:
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

            for f in findings:
                color = severity_colors.get(f.severity, "white")
                table.add_row(
                    f"[{color}]{f.severity.upper()}[/{color}]",
                    f.category,
                    f.item[:40],
                    f.description[:60]
                )
            console.print(table)

            print("\nRecommendations:")
            for f in findings:
                print(f"  • {f.item}: {f.recommendation}")
        else:
            print(f"\nFound {len(findings)} security issue(s):\n")
            for f in findings:
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


def interactive_menu(scanner: SecurityScanner, json_output: bool = False):
    """Interactive menu for security scanner."""
    actions = [
        ("1", "quick", "Quick 30-second scan"),
        ("2", "deep", "Deep 5-minute comprehensive scan"),
        ("3", "suspicious", "Heuristic suspicious activity detection"),
        ("4", "verify", "Verify app with Gatekeeper"),
        ("5", "signature", "Get code signature info"),
        ("6", "report", "Generate comprehensive report"),
    ]

    sort_options = {
        "quick": ["severity", "category", "item"],
        "deep": ["severity", "category", "item"],
        "suspicious": ["severity", "category", "item"],
    }
    current_sort = {"quick": "severity", "deep": "severity", "suspicious": "severity"}

    while True:
        action = cmd_interactive_menu([
            ("1", "quick", "Quick 30-second scan"),
            ("2", "deep", "Deep 5-minute comprehensive scan"),
            ("3", "suspicious", "Heuristic suspicious activity detection"),
            ("4", "verify", "Verify app with Gatekeeper"),
            ("5", "signature", "Get code signature info"),
            ("6", "report", "Generate comprehensive report"),
            ("s", "sort", "Change sort order"),
        ], title="Security Scanner - Interactive Mode")

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

        if action == "quick":
            scanner.scan_quick(json_output=json_output, sort_by=current_sort["quick"])
        elif action == "deep":
            scanner.scan_deep(json_output=json_output, sort_by=current_sort["deep"])
        elif action == "suspicious":
            scanner.scan_suspicious(json_output=json_output, sort_by=current_sort["suspicious"])
        elif action == "verify":
            path = input("App path to verify: ").strip()
            if path:
                scanner.verify_app(path)
            else:
                print("Path required")
        elif action == "signature":
            path = input("App path for signature info: ").strip()
            if path:
                scanner.signature_info(path, json_output=json_output)
            else:
                print("Path required")
        elif action == "report":
            output = input(f"Output file [{reports_dir() / 'scan_report.json'}]: ").strip()
            output = output or str(reports_dir() / "scan_report.json")
            scanner.generate_report(output)

        pause_for_enter()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="msp Security Scanner")
    parser.add_argument("action", nargs="?", choices=["quick", "deep", "suspicious", "verify", "signature", "report"], help="Action to perform (omit for interactive mode)")
    parser.add_argument("path", nargs="?", help="Path to verify/signature check")
    parser.add_argument("--output", help="Output file for report")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--sort", choices=["severity", "category", "item"], help="Sort by: severity, category, item")
    setup_completion(parser)
    args = parser.parse_args()

    scanner = SecurityScanner(verbose=args.verbose)

    if not args.action:
        interactive_menu(scanner, args.json)
        return

    if args.action == "quick":
        scanner.scan_quick(json_output=args.json, sort_by=args.sort or "severity")
    elif args.action == "deep":
        scanner.scan_deep(json_output=args.json, sort_by=args.sort or "severity")
    elif args.action == "suspicious":
        scanner.scan_suspicious(json_output=args.json, sort_by=args.sort or "severity")
    elif args.action == "verify":
        if not args.path:
            print("Error: path required")
            sys.exit(1)
        scanner.verify_app(args.path)
    elif args.action == "signature":
        if not args.path:
            print("Error: path required")
            sys.exit(1)
        scanner.signature_info(args.path, json_output=args.json)
    elif args.action == "report":
        output = args.output or str(reports_dir() / "scan_report.json")
        scanner.generate_report(output)


if __name__ == "__main__":
    main()