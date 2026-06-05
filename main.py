#!/usr/bin/env python3
"""
msp - macOS Security & Privacy CLI

A comprehensive CLI for macOS security and privacy management.
Combines native commands, Homebrew tools, and Apple Intelligence.

Usage:
    msp <command> [options]

Commands:
    status              Show security status
    list               List privacy settings
    enable <setting>   Enable a setting
    disable <setting>  Disable a setting

    net                Network monitoring
    startup            Startup item management
    fswatch            File system watching
    traffic            Traffic analysis
    scan               Security scanning

    ask                AI-powered analysis
    chain              Method chaining

    doctor             Check dependencies
    presets            Manage presets
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_command(module_name: str, command: str, args: list, global_args: dict = None):
    """Import and run a command from a module."""
    try:
        module = __import__(f"src.{module_name}", fromlist=["main"])
        new_argv = [command] + args
        if global_args:
            if global_args.get("json"):
                new_argv.append("--json")
            if global_args.get("verbose"):
                new_argv.append("--verbose")
            if global_args.get("sort"):
                new_argv.extend(["--sort", global_args.get("sort")])
        sys.argv = new_argv
        module.main()
    except SystemExit:
        raise
    except ImportError as e:
        print(f"Error: Could not load {module_name} module: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error running {module_name}: {e}")
        sys.exit(1)


def main():
    # Pre-parse to intercept snapshot commands before argparse consumes flags
    if len(sys.argv) >= 2 and sys.argv[1] == "snapshot":
        from src.snapshot import SnapshotManager
        sm = SnapshotManager(verbose="-v" in sys.argv or "--verbose" in sys.argv)

        # Parse snapshot command manually
        raw_args = sys.argv[2:]
        action = raw_args[0] if raw_args else None

        if action == "capture":
            name = raw_args[1] if len(raw_args) > 1 else None
            sm.capture(name=name)
        elif action == "list":
            sm.list_snapshots(json_output="--json" in sys.argv)
        elif action == "diff":
            name = raw_args[1] if len(raw_args) > 1 else None
            if name:
                sm.diff(name, json_output="--json" in sys.argv)
            else:
                print("Usage: msp snapshot diff <name>")
        elif action == "restore":
            name = raw_args[1] if len(raw_args) > 1 else None
            dry_run = "--dry-run" in raw_args
            if name:
                sm.restore(name, dry_run=dry_run)
            else:
                print("Usage: msp snapshot restore <name> [--dry-run]")
        elif action == "watch":
            name = raw_args[1] if len(raw_args) > 1 else "default"
            sm.watch(name, interval=300, auto_restore="--auto-restore" in raw_args)
        elif action == "delete":
            name = raw_args[1] if len(raw_args) > 1 else None
            if name:
                sm.delete(name)
            else:
                print("Usage: msp snapshot delete <name>")
        else:
            print("Usage: msp snapshot <capture|list|diff|restore|watch|delete> [args]")
        return

    parser = argparse.ArgumentParser(
        description="msp - macOS Security & Privacy CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  status, list, enable, disable - Privacy settings
  net, startup, fswatch, traffic - Monitoring
  scan, ask, chain, doctor - Security & AI

Examples:
  msp status                       Show security status
  msp list                          List privacy settings
  msp preset list                   List presets
  msp preset apply basic            Apply preset

  msp net list                      Listening ports
  msp net established               Active connections
  msp net top                       Bandwidth usage

  msp startup list                   Startup items
  msp startup audit                 Audit startup items

  msp fswatch recent 60             Recent file events
  msp fswatch watch /path           Watch directory

  msp traffic summary                Bandwidth summary
  msp traffic dns                    DNS queries

  msp scan quick                     Quick security scan
  msp scan deep                      Deep scan

  msp ask "what's suspicious?"      AI analysis
  msp chain run daily               Run daily check

  msp doctor                        Check dependencies
        """
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--sort", choices=["name", "label", "pid", "type", "path", "status"], help="Sort by: name, label, pid, type, path, status")
    parser.add_argument("command", nargs="?", help="Command to run")
    parser.add_argument("args", nargs="*", help="Command arguments")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        print("\nRun 'msp <command> --help' for command-specific help.")
        return

    command = args.command.lower()

    # Direct handling for privacy_settings commands (avoid subparser routing issues)
    if command in ("status", "list", "enable", "disable", "preset", "presets", "services"):
        try:
            from src.privacy_settings import PrivacySettingsManager, PresetManager
            manager = PrivacySettingsManager(verbose=args.verbose)
            preset_manager = PresetManager(manager)

            if command == "status":
                manager.get_status(json_output=args.json)

            elif command == "list":
                category = None
                if args.args and args.args[0] == "--category":
                    category = args.args[1] if len(args.args) > 1 else None
                manager.list_settings(category=category, json_output=args.json)

            elif command in ("enable", "disable"):
                setting_name = args.args[0] if args.args else None
                if not setting_name:
                    print(f"Usage: msp {command} <setting-name>")
                    return
                setting = next((s for s in manager.SETTINGS if s.name == setting_name), None)
                if setting:
                    if command == "enable":
                        success = manager.enable_setting(setting)
                    else:
                        success = manager.disable_setting(setting)
                    print(f"{'Enabled' if command == 'enable' else 'Disabled'}: {setting.name}" if success else f"Failed")
                else:
                    print(f"Unknown setting: {setting_name}")

            elif command in ("preset", "presets"):
                if not args.args or args.args[0] == "list":
                    preset_manager.list_presets(json_output=args.json)
                elif args.args[0] == "apply":
                    name = args.args[1] if len(args.args) > 1 else None
                    dry_run = "--dry-run" in args.args
                    if name:
                        preset_manager.apply_preset(name, dry_run=dry_run)
                    else:
                        print("Usage: msp preset apply <name>")
                else:
                    print(f"Unknown preset action: {args.args[0]}")

            elif command == "services":
                if not args.args or args.args[0] == "list":
                    manager.list_services(json_output=args.json)

        except Exception as e:
            print(f"Error: {e}")
        return

    # Handle sharing command
    if command == "sharing":
        from src.sharing import SharingManager
        sm = SharingManager(verbose=args.verbose)
        action = args.args[0] if args.args else "status"

        if action == "status" or action == "list":
            sm.show_status(json_output=args.json)
        elif action == "disable" and len(args.args) > 1:
            sm.disable_share(args.args[1])
        elif action == "disable-guest":
            sm.disable_guest_access(args.args[1] if len(args.args) > 1 else None)
        elif action == "stop-all":
            sm.disable_all_sharing()
        elif action == "enable" and len(args.args) > 1:
            sm.enable_share(args.args[1])
        return

    # Handle security command (sleep, lock, screen settings)
    if command == "security":
        from src.security import SecuritySettings
        ss = SecuritySettings(verbose=args.verbose)
        action = args.args[0] if args.args else "status"

        if action == "status":
            ss.show_status(json_output=args.json)
        elif action == "lock":
            ss.lock_screen()
        elif action == "sleep":
            ss.sleep_display()
        elif action == "set" and len(args.args) > 1:
            key = args.args[1]
            value = args.args[2] if len(args.args) > 2 else None
            ss.set_setting(key, value)
        return

    # Snapshot commands - handle before argparse processes flags
    if command == "snapshot":
        from src.snapshot import SnapshotManager
        sm = SnapshotManager(verbose=args.verbose)

        # Manually parse snapshot args to avoid argparse flag issues
        raw_args = sys.argv[2:] if len(sys.argv) > 2 else []
        action = raw_args[0] if raw_args else None

        # Filter out global flags before passing to snapshot module
        filtered_args = [a for a in raw_args[1:] if not a.startswith("--")]

        if action == "capture":
            name = filtered_args[0] if filtered_args else None
            include_network = "--json" in raw_args
            sm.capture(name=name, include_network=include_network)
        elif action == "list":
            sm.list_snapshots(json_output=args.json)
        elif action == "diff":
            name = filtered_args[0] if filtered_args else None
            if name:
                sm.diff(name, json_output=args.json)
            else:
                print("Usage: msp snapshot diff <name>")
        elif action == "restore":
            name = filtered_args[0] if filtered_args else None
            dry_run = "--dry-run" in raw_args
            if name:
                sm.restore(name, dry_run=dry_run)
            else:
                print("Usage: msp snapshot restore <name> [--dry-run]")
        elif action == "watch":
            name = filtered_args[0] if filtered_args else "default"
            auto_restore = "--auto-restore" in raw_args
            sm.watch(name, interval=300, auto_restore=auto_restore)
        elif action == "delete":
            name = filtered_args[0] if filtered_args else None
            if name:
                sm.delete(name)
            else:
                print("Usage: msp snapshot delete <name>")
        else:
            print("Usage: msp snapshot <capture|list|diff|restore|watch|delete> [args]")
        return

    # Handle ask command specially - pass quoted prompt directly
    if command == "ask" and args.args:
        from src.ai import AIAnalyzer
        from src.network import NetworkMonitor

        analyzer = AIAnalyzer(verbose=args.verbose)
        prompt = " ".join(args.args)

        # Auto-include network data for network-related questions
        network_keywords = ["network", "connection", "connections", "port", "listen", "outbound", "inbound", "traffic", "firewall"]
        if any(kw in prompt.lower() for kw in network_keywords):
            nm = NetworkMonitor()
            established = nm.list_established()
            listening = nm.list_listening()

            context = "\n\n## Current Network Data:\n\n### Established Connections (first 50):\n"
            if established:
                for c in established[:50]:
                    local = getattr(c, 'local', getattr(c, 'host', '*')) or '*'
                    remote = getattr(c, 'remote', getattr(c, 'peer', '')) or ''
                    proc = getattr(c, 'process', getattr(c, 'name', '')) or ''
                    context += f"- {local} -> {remote} | {proc}\n"
            else:
                context += "None\n"

            context += "\n### Listening Ports (first 30):\n"
            if listening:
                for c in listening[:30]:
                    port = getattr(c, 'port', '?') or '?'
                    proc = getattr(c, 'process', getattr(c, 'name', '')) or ''
                    context += f"- *:{port} | {proc}\n"
            else:
                context += "None\n"

            prompt = f"{prompt}\n\n{context}"

        data = None
        if "--data" in args.args:
            idx = args.args.index("--data")
            if idx + 1 < len(args.args):
                with open(args.args[idx + 1]) as f:
                    data = f.read()

        analyzer.ask(prompt, data=data, json_output=args.json)
        return

    command_map = {
        "net": "network",
        "startup": "startup",
        "fswatch": "fswatch",
        "traffic": "traffic",
        "scan": "scanner",
        "chain": "chain",
        "doctor": "deps",
        "deps": "deps",
    }

    if command in command_map:
        run_command(command_map[command], command, args.args, {"json": args.json, "verbose": args.verbose, "sort": getattr(args, 'sort', None)})
    else:
        print(f"Unknown command: {command}")
        print("Run 'msp --help' for available commands.")


if __name__ == "__main__":
    main()