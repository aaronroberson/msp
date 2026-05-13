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


def run_command(module_name: str, command: str, args: list):
    """Import and run a command from a module."""
    try:
        module = __import__(f"src.{module_name}", fromlist=["main"])
        sys.argv = [command] + args
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

    command_map = {
        "status": "privacy_settings",
        "list": "privacy_settings",
        "enable": "privacy_settings",
        "disable": "privacy_settings",
        "services": "privacy_settings",
        "net": "network",
        "startup": "startup",
        "fswatch": "fswatch",
        "traffic": "traffic",
        "scan": "scanner",
        "ask": "ai",
        "chain": "chain",
        "doctor": "deps",
        "deps": "deps",
    }

    if command in command_map:
        run_command(command_map[command], command, args.args)
    else:
        print(f"Unknown command: {command}")
        print("Run 'msp --help' for available commands.")


if __name__ == "__main__":
    main()