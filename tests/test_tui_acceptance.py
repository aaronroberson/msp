#!/usr/bin/env python3
"""
Acceptance tests for msp TUI implementation.
Tests TUI mode dashboard functionality.
"""
import subprocess
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_tui_imports():
    """Test that TUI module can be imported."""
    try:
        from src.tui import MSApp
        return True
    except ImportError as e:
        print(f"Import failed: {e}")
        return False


def test_tui_widget_ids():
    """Test that all required widgets have correct IDs in compose."""
    # Check the compose method yields correct IDs
    import inspect
    from src.tui import MSApp
    
    source = inspect.getsource(MSApp.compose)
    
    required_ids = ["security", "network", "startup", "system"]
    for wid in required_ids:
        if f'id="{wid}"' not in source and f"id='{wid}'" not in source:
            print(f"Missing widget id: {wid}")
            return False
    
    return True


def test_tui_bindings():
    """Test that required keyboard shortcuts are defined."""
    from src.tui import MSApp
    
    binding_keys = {b[0] for b in MSApp.BINDINGS}
    
    required = {"q", "r", "s", "n", "a"}
    missing = required - binding_keys
    
    if missing:
        print(f"Missing bindings: {missing}")
        return False
    
    print("All keyboard shortcuts defined")
    return True


def test_tui_runs():
    """Test that TUI can start (smoke test)."""
    from src.tui import MSApp
    
    try:
        import asyncio
        app = MSApp()
        
        async def run_test():
            async with app.run_test(size=(80, 24)) as pilot:
                # Check app title
                assert app.title == "msp - Security Dashboard"
                
                # Give it time to render
                await pilot.pause()
                return True
        
        result = asyncio.run(run_test())
        return result
    except Exception as e:
        print(f"TUI run test failed: {e}")
        return False


def test_tui_refresh():
    """Test that refresh action exists and is callable."""
    from src.tui import MSApp
    import asyncio
    
    try:
        app = MSApp()
        
        async def run_test():
            async with app.run_test(size=(80, 24)) as pilot:
                # Check refresh action exists
                assert hasattr(app, 'action_refresh'), "action_refresh missing"
                # Check it's a coroutine function
                import inspect
                assert inspect.iscoroutinefunction(app.action_refresh), "action_refresh not async"
                return True
        
        return asyncio.run(run_test())
    except Exception as e:
        print(f"Refresh test failed: {e}")
        return False


def test_tui_has_help():
    """Test that TUI has help text."""
    from src.tui import MSApp
    
    # Check BINDINGS have descriptions
    for binding in MSApp.BINDINGS:
        if len(binding) < 3:
            print(f"Binding missing description: {binding}")
            return False
    
    return True


def test_cli_tui_command():
    """Test that msp tui command works via CLI."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, '.'); from src.tui import main; print('OK')"],
        capture_output=True,
        text=True,
        cwd="/Users/conscious/macos-privacy-cli"
    )
    
    if result.returncode != 0:
        print(f"CLI tui command failed: {result.stderr}")
        return False
    
    return True


def main():
    """Run all acceptance tests."""
    tests = [
        ("imports", test_tui_imports),
        ("widget IDs", test_tui_widget_ids),
        ("bindings", test_tui_bindings),
        ("runs", test_tui_runs),
        ("refresh action", test_tui_refresh),
        ("has help", test_tui_has_help),
        ("cli command", test_cli_tui_command),
    ]
    
    passed = 0
    failed = 0
    
    print("=" * 50)
    print("TUI Acceptance Tests")
    print("=" * 50)
    
    for name, test_func in tests:
        try:
            if test_func():
                print(f"[PASS] {name}")
                passed += 1
            else:
                print(f"[FAIL] {name}")
                failed += 1
        except Exception as e:
            print(f"[ERROR] {name}: {e}")
            failed += 1
    
    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())