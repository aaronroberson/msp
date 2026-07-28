#!/usr/bin/env python3
"""
msp TUI - Terminal User Interface for macOS Security & Privacy CLI

A full-featured, intuitive dashboard using Textual framework.
"""
import argparse
import json
import os
import subprocess
import sys
from typing import Dict, Any, List, Optional

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, DataTable, Label, Input
from textual.containers import Horizontal, Vertical, Container
from textual.screen import Screen

# Import CLI modules for live data
try:
    from src.network import NetworkMonitor
    from src.startup import StartupManager
    from src.scanner import SecurityScanner, Finding
    from src.tcc import TCCManager, SERVICE_DEFINITIONS
    from src.privacy_settings import PrivacySettingsManager
    from src.ai import AIAnalyzer
    from src.snapshot import SnapshotManager
except ImportError:
    NetworkMonitor = None
    StartupManager = None
    SecurityScanner = None
    TCCManager = None
    PrivacySettingsManager = None
    AIAnalyzer = None
    SnapshotManager = None


class TUIDataProvider:
    """Provides live data from CLI modules for TUI display."""
    
    def __init__(self):
        self.network = NetworkMonitor() if NetworkMonitor else None
        self.startup = StartupManager() if StartupManager else None
        self.scanner = SecurityScanner() if SecurityScanner else None
        self.tcc = TCCManager() if TCCManager else None
        self.privacy = PrivacySettingsManager() if PrivacySettingsManager else None
    
    def get_firewall_status(self) -> Dict[str, Any]:
        """Get firewall status with all details."""
        if self.privacy:
            return self.privacy.get_firewall_status()
        return {"enabled": False, "stealth_mode": False, "exceptions": []}
    
    def get_gatekeeper_status(self) -> Dict[str, Any]:
        """Get Gatekeeper status."""
        if self.privacy:
            return self.privacy.get_gatekeeper_status()
        return {"enabled": False}
    
    def get_filevault_status(self) -> Dict[str, Any]:
        """Get FileVault status."""
        if self.privacy:
            return self.privacy.get_filevault_status()
        return {"enabled": False, "encrypted": False}
    
    def get_listening_ports(self) -> List[Dict]:
        """Get listening ports with process info."""
        if self.network:
            return [
                {"process": c.process, "pid": c.pid, "port": c.local_addr.split(":")[-1] if ":" in c.local_addr else c.local_addr,
                 "user": c.user, "protocol": c.protocol}
                for c in self.network.list_listening(json_output=False)
            ]
        return []
    
    def get_established_connections(self) -> List[Dict]:
        """Get established connections."""
        if self.network:
            return self.network.list_established(json_output=False)
        return []
    
    def get_bandwidth_top(self, limit: int = 10) -> List[Dict]:
        """Get top bandwidth consumers."""
        if self.network:
            return self.network.bandwidth_top(limit=limit, json_output=True)
        return []
    
    def get_startup_items(self) -> List[Dict]:
        """Get startup items with risk assessment."""
        if self.startup:
            items = []
            for item in self.startup.list_all(json_output=False):
                high_risk = ["update", "helper", "agent", "daemon", "service", "monitor", "scanner", "sync", "backup", "cloud", "telemetry"]
                risky = any(p in item.name.lower() for p in high_risk) and "apple" not in item.name.lower()
                items.append({
                    "name": item.name[:30] if len(item.name) > 30 else item.name,
                    "label": item.label[:40] if len(item.label) > 40 else item.label,
                    "pid": str(item.pid) if item.pid else "-",
                    "status": item.status,
                    "risk": "HIGH" if risky else "INFO",
                })
            return items
        return []
    
    def get_security_findings(self, quick: bool = True) -> List:
        """Get security scan findings."""
        if self.scanner:
            return self.scanner.scan_quick(json_output=False) if quick else self.scanner.scan_deep(json_output=False)
        return []
    
    def get_tcc_permissions(self, service: Optional[str] = None) -> List[Dict]:
        """Get TCC privacy permissions."""
        if self.tcc:
            entries = self.tcc.list_permissions(service=service, json_output=False)
            return [
                {"service": e.service_name or e.service, "client": e.client_name or e.client,
                 "auth": e.auth_status or "unknown", "source": e.source}
                for e in entries[:100]
            ]
        return []
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information."""
        info = {"uptime": "unknown", "disk": "unknown", "swap": "unknown", "memory_pressure": "unknown"}
        
        try:
            r = subprocess.run(["uptime", "-p"], capture_output=True, text=True, timeout=5)
            info["uptime"] = r.stdout.strip() or "unknown"
        except Exception:
            pass
        
        try:
            r = subprocess.run(["df", "-h", "/", "--output=used,avail"], capture_output=True, text=True, timeout=5)
            lines = r.stdout.strip().split("\n")
            info["disk"] = lines[1] if len(lines) > 1 else "unknown"
        except Exception:
            pass
        
        try:
            r = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True, timeout=5)
            info["swap"] = r.stdout.strip().split(":")[-1].strip() if ":" in r.stdout else "unknown"
        except Exception:
            pass
        
        return info


# Shared data provider instance for widgets
_provider = TUIDataProvider()


def _get_security_content() -> str:
    """Get security widget content with live data."""
    fw = _provider.get_firewall_status()
    gk = _provider.get_gatekeeper_status()
    fv = _provider.get_filevault_status()
    
    fw_status = "enabled" if fw.get("enabled") else "disabled"
    fw_color = "status-ok" if fw.get("enabled") else "status-error"
    stealth = "on" if fw.get("stealth_mode") else "off"
    stealth_color = "status-ok" if fw.get("stealth_mode") else "status-warn"
    
    gk_status = "enabled" if gk.get("enabled") else "disabled"
    gk_color = "status-ok" if gk.get("enabled") else "status-error"
    
    fv_status = "enabled" if fv.get("enabled") else "disabled"
    fv_color = "status-ok" if fv.get("enabled") else "status-error"
    
    return f"""[bold]Security Status[/bold]

Firewall: [{fw_color}]{fw_status}[/{fw_color}]
Stealth Mode: [{stealth_color}]{stealth}[/{stealth_color}]
Exceptions: {len(fw.get('exceptions', []))} apps
FileVault: [{fv_color}]{fv_status}[/{fv_color}]
Gatekeeper: [{gk_color}]{gk_status}[/{gk_color}]"""


def _get_network_content() -> str:
    """Get network widget content with live data."""
    listening = _provider.get_listening_ports()
    connections = _provider.get_established_connections()
    
    content = f"""[bold]Network[/bold]

Listening: {len(listening)} ports
Connections: {len(connections)} active
"""
    if listening:
        content += "\n[top 3 listening ports]\n"
        for port in listening[:3]:
            content += f"  • {port['process'][:15]}:{port['port']}\n"
    
    return content


def _get_startup_content() -> str:
    """Get startup widget content with live data."""
    items = _provider.get_startup_items()
    
    high_risk = sum(1 for i in items if i.get("risk") == "HIGH")
    medium_risk = sum(1 for i in items if i.get("risk") in ("MEDIUM", "REVIEW"))
    
    risk_color = "risk-high" if high_risk else "risk-ok"
    bold_start = "[bold]" if high_risk else ""
    bold_end = "[/bold]" if high_risk else ""
    
    content = f"""[bold]Startup[/bold]

Total Items: {len(items)}
High Risk: [{risk_color}]{bold_start}{high_risk}{bold_end}[/{risk_color}]
Medium Risk: {medium_risk}
"""
    if high_risk > 0:
        content += "\n[bold red]⚠ Suspicious items detected[/bold red]\n"
        for item in items[:3]:
            if item.get("risk") == "HIGH":
                content += f"  • {item['name']}\n"
    
    return content


def _get_system_content() -> str:
    """Get system widget content with live data."""
    info = _provider.get_system_info()
    
    return f"""[bold]System[/bold]

Uptime: {info.get('uptime', 'unknown')}
Disk: {info.get('disk', 'unknown')}
Swap: {info.get('swap', 'unknown')}"""


class ConfirmScreen(Screen):
    """Confirmation dialog screen."""
    
    CSS = """
    ConfirmScreen {
        background: $surface-darken-1;
    }
    
    #confirm-container {
        width: 60%;
        height: auto;
        border: tall $primary;
        padding: 2 4;
        margin: 10 0;
    }
    """
    
    BINDINGS = [
        ("y", "confirm", "Confirm"),
        ("n", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, message: str):
        super().__init__()
        self.message = message
    
    def compose(self) -> ComposeResult:
        with Container(id="confirm-container"):
            yield Label(f"[bold]{self.message}[/bold]")
            yield Label("")
            yield Label("[bold]y[/bold] to confirm, [bold]n[/bold] or [bold]escape[/bold] to cancel")
    
    def action_confirm(self) -> None:
        self.dismiss(True)
    
    def action_cancel(self) -> None:
        self.dismiss(False)


class NetworkScreen(Screen):
    """Detailed network view with tabs for ports and connections."""
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "pop_screen", "Back"),
        ("/", "search", "Search"),
        ("r", "refresh", "Refresh"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("x", "kill_process", "Kill Process"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("[bold]Network Details[/bold]")
        yield DataTable(id="network-table")
        yield Footer()
    
    def on_mount(self) -> None:
        table = self.query_one("#network-table", DataTable)
        table.add_column("Process", key="process")
        table.add_column("PID", key="pid")
        table.add_column("Port", key="port")
        table.add_column("User", key="user")
        table.add_column("Protocol", key="protocol")
        
        # Load initial data
        self.refresh_network_data()
    
    def refresh_network_data(self, filter_term: str = "") -> None:
        """Load listening ports into the table, optionally filtered."""
        table = self.query_one("#network-table", DataTable)
        table.clear()
        
        for port in _provider.get_listening_ports():
            if not filter_term or filter_term.lower() in str(port).lower():
                table.add_row(port["process"], port["pid"], port["port"], port["user"], port["protocol"])
    
    def action_search(self) -> None:
        """Open search for network."""
        self.app.bell()
    
    def action_refresh(self) -> None:
        """Refresh network data."""
        self.refresh_network_data()
    
    def action_kill_process(self) -> None:
        """Kill the selected process."""
        table = self.query_one("#network-table", DataTable)
        if table.cursor_row is not None:
            try:
                row_data = table.get_row_at(table.cursor_row)
                if row_data:
                    self.app.bell()
            except Exception:
                pass


class StartupScreen(Screen):
    """Detailed startup items view."""
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "pop_screen", "Back"),
        ("/", "search", "Search"),
        ("r", "refresh", "Refresh"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("d", "disable_selected", "Disable"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("[bold]Startup Items[/bold]")
        yield DataTable(id="startup-table")
        yield Footer()
    
    def on_mount(self) -> None:
        table = self.query_one("#startup-table", DataTable)
        table.add_column("Name", key="name")
        table.add_column("Label", key="label")
        table.add_column("PID", key="pid")
        table.add_column("Status", key="status")
        table.add_column("Risk", key="risk")
        
        self.refresh_startup_data()
    
    def refresh_startup_data(self, filter_term: str = "") -> None:
        """Load startup items into the table."""
        table = self.query_one("#startup-table", DataTable)
        table.clear()
        
        for item in _provider.get_startup_items():
            if not filter_term or filter_term.lower() in item["name"].lower() or filter_term.lower() in item.get("label", "").lower():
                table.add_row(item["name"], item["label"], item["pid"], item["status"], item["risk"])
    
    def action_search(self) -> None:
        """Open search for startup."""
        self.app.bell()
    
    def action_refresh(self) -> None:
        """Refresh startup data."""
        self.refresh_startup_data()
    
    def action_disable_selected(self) -> None:
        """Disable the selected startup item."""
        table = self.query_one("#startup-table", DataTable)
        if table.cursor_row is not None:
            self.app.bell()


class PrivacyScreen(Screen):
    """Privacy/TCC permissions view."""
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "pop_screen", "Back"),
        ("/", "search", "Search"),
        ("r", "refresh", "Refresh"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("[bold]Privacy Permissions (TCC)[/bold]")
        yield DataTable(id="privacy-table")
        yield Footer()
    
    def on_mount(self) -> None:
        table = self.query_one("#privacy-table", DataTable)
        table.add_column("Service", key="service")
        table.add_column("Client", key="client")
        table.add_column("Auth", key="auth")
        table.add_column("Source", key="source")
        
        self.refresh_privacy_data()
    
    def refresh_privacy_data(self, filter_term: str = "") -> None:
        """Load TCC permissions into the table."""
        table = self.query_one("#privacy-table", DataTable)
        table.clear()
        
        for perm in _provider.get_tcc_permissions():
            if not filter_term or filter_term.lower() in str(perm).lower():
                table.add_row(perm["service"], perm["client"], perm["auth"], perm["source"])
    
    def action_search(self) -> None:
        """Open search for privacy."""
        self.app.bell()
    
    def action_refresh(self) -> None:
        """Refresh privacy data."""
        self.refresh_privacy_data()


class ScannerScreen(Screen):
    """Security scanner view."""
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "pop_screen", "Back"),
        ("/", "search", "Search"),
        ("r", "refresh", "Refresh"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("s", "scan_suspicious", "Scan Suspicious"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("[bold]Security Findings[/bold]")
        yield DataTable(id="findings-table")
        yield Footer()
    
    def on_mount(self) -> None:
        table = self.query_one("#findings-table", DataTable)
        table.add_column("Severity", key="severity", style="severity-medium")
        table.add_column("Category", key="category")
        table.add_column("Item", key="item")
        table.add_column("Description", key="description")
        
        self.refresh_findings()
    
    def refresh_findings(self, filter_term: str = "") -> None:
        """Load security findings into the table."""
        table = self.query_one("#findings-table", DataTable)
        table.clear()
        
        for finding in _provider.get_security_findings():
            if not filter_term or filter_term.lower() in f"{finding.severity} {finding.category} {finding.item} {finding.description}".lower():
                sev = finding.severity.upper()
                # Apply color classes based on severity
                if finding.severity == "critical":
                    sev = f"[bold red]{sev}[/bold red]"
                elif finding.severity == "high":
                    sev = f"[red]{sev}[/red]"
                elif finding.severity == "medium":
                    sev = f"[yellow]{sev}[/yellow]"
                elif finding.severity == "low":
                    sev = f"[green]{sev}[/green]"
                
                table.add_row(
                    sev,
                    finding.category,
                    finding.item[:40] if len(finding.item) > 40 else finding.item,
                    finding.description[:60] if len(finding.description) > 60 else finding.description
                )
    
    def action_search(self) -> None:
        """Open search for findings."""
        self.app.bell()
    
    def action_refresh(self) -> None:
        """Refresh findings."""
        self.refresh_findings()
    
    def action_scan_suspicious(self) -> None:
        """Run suspicious scan and refresh."""
        self.app.bell()


class SearchScreen(Screen):
    """Search overlay screen."""
    
    CSS = """
    SearchScreen {
        background: $surface-darken-1;
    }
    
    #search-container {
        width: 80%;
        height: auto;
        border: tall $primary;
        padding: 2 4;
        margin: 10 0;
    }
    
    #search-input {
        width: 100%;
    }
    """
    
    def compose(self) -> ComposeResult:
        with Container(id="search-container"):
            yield Label("[bold]Search[/bold] - Type to search processes, connections, or startup items")
            yield Input(placeholder="Enter search term (pid, process, host, port)...", id="search-input")
    
    def on_mount(self) -> None:
        self.query_one("#search-input").focus()
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.input.value)


class AIAnalysisScreen(Screen):
    """AI-powered security analysis screen."""
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "pop_screen", "Back"),
        ("r", "refresh", "Refresh Analysis"),
    ]
    
    CSS = """
    #ai-container {
        padding: 2 4;
    }
    
    #ai-output {
        height: 1fr;
        overflow: auto;
        border: round $primary;
        padding: 1 2;
    }
    """
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("[bold]AI Security Analysis[/bold]")
        yield Static(id="ai-output")
        yield Label("")
        yield Label("[dim]Press 'r' for refresh, 'escape' to return[/dim]")
        yield Footer()
    
    def on_mount(self) -> None:
        self.title = "msp - AI Analysis"
        self.refresh_ai_output()
    
    def refresh_ai_output(self) -> None:
        """Get and display AI analysis."""
        output = self.query_one("#ai-output", Static)
        output.update("[dim]Analyzing system security...[/dim]")
        
        # Collect data for analysis
        data = {
            "firewall": _provider.get_firewall_status(),
            "gatekeeper": _provider.get_gatekeeper_status(),
            "filevault": _provider.get_filevault_status(),
            "listening_ports": len(_provider.get_listening_ports()),
            "connections": len(_provider.get_established_connections()),
            "startup_items": len(_provider.get_startup_items()),
            "tcc_permissions": len(_provider.get_tcc_permissions()),
        }
        
        # If AI is available, run analysis
        if AIAnalyzer:
            try:
                analyzer = AIAnalyzer(verbose=False)
                analysis = analyzer.ask(
                    "Analyze this macOS security data and provide actionable recommendations",
                    data=data,
                    json_output=False
                )
                if analysis:
                    output.update(analysis)
                else:
                    output.update("[red]AI analysis unavailable. Install ollama or set OPENAI_API_KEY[/red]")
            except Exception as e:
                output.update(f"[red]AI analysis unavailable: {e}[/red]")
        else:
            output.update("[dim]No AI provider configured. Set OPENAI_API_KEY or install ollama.[/dim]")
    
    def action_refresh(self) -> None:
        """Refresh AI analysis."""
        self.refresh_ai_output()


class SnapshotScreen(Screen):
    """Snapshot management screen."""
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "pop_screen", "Back"),
        ("n", "create_snapshot", "New Snapshot"),
        ("r", "refresh", "Refresh"),
    ]
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("[bold]Security Snapshots[/bold]")
        yield DataTable(id="snapshots-table")
        yield Footer()
    
    def on_mount(self) -> None:
        table = self.query_one("#snapshots-table", DataTable)
        table.add_column("Name", key="name")
        table.add_column("Timestamp", key="timestamp")
        table.add_column("Firewall", key="firewall")
        table.add_column("Gatekeeper", key="gatekeeper")
        table.add_column("FileVault", key="filevault")
        
        self.refresh_snapshots()
    
    def refresh_snapshots(self) -> None:
        """Load snapshots into the table."""
        if not SnapshotManager:
            return
        
        table = self.query_one("#snapshots-table", DataTable)
        table.clear()
        
        try:
            manager = SnapshotManager(verbose=False)
            for snap in manager.list_snapshots():
                table.add_row(
                    snap["name"],
                    snap["timestamp"],
                    str(snap["settings"].get("firewall", "-")),
                    str(snap["settings"].get("gatekeeper", "-")),
                    str(snap["settings"].get("filevault", "-")),
                )
        except Exception:
            pass
    
    def action_refresh(self) -> None:
        """Refresh snapshots."""
        self.refresh_snapshots()
    
    def action_create_snapshot(self) -> None:
        """Create a new snapshot."""
        if SnapshotManager:
            try:
                manager = SnapshotManager(verbose=False)
                path = manager.capture()
                self.app.bell()
            except Exception:
                pass


class HelpScreen(Screen):
    """Help overlay showing all keybindings."""
    
    CSS = """
    HelpScreen {
        background: $surface-darken-1;
    }
    
    #help-container {
        width: 70%;
        height: auto;
        border: tall $primary;
        padding: 2 4;
        margin: 5 0;
    }
    
    .help-section {
        margin-bottom: 1;
    }
    
    .help-key {
        color: $primary;
        text-style: bold;
        min-width: 10;
        display: inline-block;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "pop_screen", "Back"),
    ]
    
    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Label("[bold]msp TUI - Keyboard Shortcuts[/bold]")
            yield Label("")
            yield Label("[bold]Dashboard Navigation:[/bold]")
            yield Label("  [bold]q[/bold]         Quit the application")
            yield Label("  [bold]r[/bold]         Refresh dashboard data")
            yield Label("  [bold]h[/bold]         Show this help screen")
            yield Label("  [bold]1-4[/bold]       Focus widget (Security, Network, Startup, System)")
            yield Label("  [bold]s/n/a[/bold]     Focus Security/Network/Startup widget")
            yield Label("")
            yield Label("[bold]View Navigation:[/bold]")
            yield Label("  [bold]N[/bold]         Network details screen")
            yield Label("  [bold]S[/bold]         Startup items screen")
            yield Label("  [bold]p[/bold]         Privacy/TCC permissions screen")
            yield Label("  [bold]c[/bold]         Security scanner screen")
            yield Label("  [bold]i[/bold]         AI security analysis screen")
            yield Label("  [bold]v[/bold]         Snapshots management screen")
            yield Label("")
            yield Label("[bold]Table Navigation:[/bold]")
            yield Label("  [bold]j/↓[/bold]       Move cursor down")
            yield Label("  [bold]k/↑[/bold]       Move cursor up")
            yield Label("  [bold]/[/bold]         Search/filter in current view")
            yield Label("  [bold]r[/bold]         Refresh current screen data")
            yield Label("  [bold]x[/bold]         Kill selected process (Network screen)")
            yield Label("  [bold]d[/bold]         Disable selected item (Startup screen)")
            yield Label("")
            yield Label("[bold]In Detail Screens:[/bold]")
            yield Label("  [bold]escape[/bold]    Return to dashboard")
            yield Label("")
            yield Label("[dim]Press any key to close...[/dim]")


class MSApp(App):
    """Main TUI application for msp security dashboard."""
    
    SCREENS = {
        "default": "dashboard",
        "help": HelpScreen,
        "network": NetworkScreen,
        "startup": StartupScreen,
        "privacy": PrivacyScreen,
        "scanner": ScannerScreen,
        "search": SearchScreen,
        "ai": AIAnalysisScreen,
        "snapshots": SnapshotScreen,
    }
    
    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1 1;
        padding: 1;
    }
    
    .dashboard-widget {
        width: 1fr;
        height: 1fr;
        border: round $primary;
        padding: 1 2;
        overflow: hidden hidden;
    }
    
    .status-ok { color: $success; }
    .status-warn { color: $warning; }
    .status-error { color: $error; }
    .risk-high { color: $error; }
    .risk-warn { color: $warning; }
    .risk-ok { color: $success; }
    
    /* Severity colors for scanner findings */
    .severity-critical { color: $error; text-style: bold; }
    .severity-high { color: $error; }
    .severity-medium { color: $warning; }
    .severity-low { color: $success; }
    """

    # Bindings in tuple format for backward compatibility with tests
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("h", "help", "Help"),
        ("s", "focus_security", "Security"),
        ("n", "focus_network", "Network"),
        ("a", "focus_startup", "Startup"),
        ("p", "push_screen('privacy')", "Privacy"),
        ("c", "push_screen('scanner')", "Scanner"),
        ("i", "push_screen('ai')", "AI Analysis"),
        ("v", "push_screen('snapshots')", "Snapshots"),
        ("1", "focus_widget('security')", "Focus Security"),
        ("2", "focus_widget('network')", "Focus Network"),
        ("3", "focus_widget('startup')", "Focus Startup"),
        ("4", "focus_widget('system')", "Focus System"),
        ("N", "push_screen('network')", "Network Details"),
        ("S", "push_screen('startup')", "Startup Details"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            with Horizontal():
                yield Static(_get_security_content(), id="security", classes="dashboard-widget")
                yield Static(_get_network_content(), id="network", classes="dashboard-widget")
            with Horizontal():
                yield Static(_get_startup_content(), id="startup", classes="dashboard-widget")
                yield Static(_get_system_content(), id="system", classes="dashboard-widget")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "msp - Security Dashboard"
        # Set up auto-refresh timer (30 seconds)
        self.set_interval(30.0, self._auto_refresh)

    async def action_refresh(self) -> None:
        """Refresh all data widgets."""
        self.query_one("#security").update(_get_security_content())
        self.query_one("#network").update(_get_network_content())
        self.query_one("#startup").update(_get_startup_content())
        self.query_one("#system").update(_get_system_content())

    def action_focus_security(self) -> None:
        self.query_one("#security").focus()

    def action_focus_widget(self, widget_id: str) -> None:
        """Generic focus widget action for numeric keys."""
        try:
            self.query_one(f"#{widget_id}").focus()
        except Exception:
            pass

    def action_focus_network(self) -> None:
        self.query_one("#network").focus()

    def action_focus_startup(self) -> None:
        self.query_one("#startup").focus()
    
    def action_focus_system(self) -> None:
        """Focus the system widget."""
        try:
            self.query_one("#system").focus()
        except Exception:
            pass

    def action_quit(self) -> None:
        self.exit()
    
    def action_help(self) -> None:
        """Show help screen."""
        self.push_screen(HelpScreen())
    
    def action_search(self) -> None:
        """Open search screen."""
        self.push_screen(SearchScreen())
    
    def _auto_refresh(self) -> None:
        """Auto-refresh data periodically."""
        try:
            self.call_from_thread(self._refresh_thread_safe)
        except Exception:
            pass
    
    def _refresh_thread_safe(self) -> None:
        """Thread-safe refresh callback."""
        self.action_refresh()


def main():
    """Entry point for TUI mode."""
    app = MSApp()
    app.run()


if __name__ == "__main__":
    main()