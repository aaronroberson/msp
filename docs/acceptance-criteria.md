# Acceptance Criteria: msp Implementation

## TUI Mode Implementation (Phase 1)

### Acceptance Tests

```gherkin
Feature: TUI Mode
  Scenario: Launch TUI dashboard
    Given the msp command exists
    When I run "msp tui"
    Then a Textual app launches
    And the dashboard shows security status
    And the dashboard shows network connections
    And the dashboard shows startup items count
    And the dashboard shows disk/memory usage

  Scenario: TUI navigation
    Given TUI is running
    When I press "r"
    Then the dashboard refreshes
    When I press "n"
    Then the network widget is focused
    When I press "s"
    Then the security widget is focused
    When I press "q"
    Then the app exits cleanly
```

### Success Criteria
- [ ] TUI loads in <2 seconds
- [ ] All 4 dashboard sections render correctly
- [ ] Keyboard shortcuts work (r, q, s, n, a)
- [ ] Async data loading doesn't block UI
- [ ] Exit code 0 on clean quit

---

## CLI Architecture Refactor (Phase 2)

### Acceptance Tests

```gherkin
Feature: Command Routing
  Scenario: Version flag
    When I run "msp --version"
    Then output shows version number
    And exit code is 0

  Scenario: Subcommand help
    When I run "msp net --help"
    Then output shows net subcommands
    And exit code is 0

  Scenario: Snapshot commands via subparser
    When I run "msp snapshot capture test"
    Then output shows capture confirmation
    When I run "msp snapshot list"
    Then output lists snapshots
    When I run "msp snapshot diff test"
    Then output shows diff
```

### Success Criteria
- [ ] No duplicate code paths for snapshot
- [ ] All existing commands work identically
- [ ] `--help` shows proper subcommand structure
- [ ] Exit codes consistent (0 success, 1 error)

---

## Error Handling & UX (Phase 3)

### Acceptance Tests

```gherkin
Feature: Error Messages
  Scenario: Missing dependency
    Given nmap is not installed
    When I run "msp net nmap"
    Then output shows "Error: nmap not found"
    And output shows "Hint: brew install nmap"
    And output shows "Try: msp doctor --fix"

  Scenario: Doctor fix flag
    When I run "msp doctor --fix"
    Then missing dependencies are installed
    Or user is prompted for each installation
```

### Success Criteria
- [ ] Every tool error suggests install command
- [ ] `doctor --fix` auto-installs missing deps
- [ ] Error messages fit in 80x24 terminal
- [ ] No stack traces on user errors

---

## Testing Enhancement (Phase 4)

### Acceptance Tests

```python
# test_acceptance_tui.py
def test_tui_dashboard_loads():
    """Dashboard must render all sections."""
    app = MSApp()
    async with app.run_test() as pilot:
        # Check all widgets exist
        assert app.query_one("#security-status")
        assert app.query_one("#network-widget")
        assert app.query_one("#startup-widget")
        assert app.query_one("#system-widget")

def test_cli_version_flag():
    """--version must work."""
    result = subprocess.run(["msp", "--version"], capture_output=True)
    assert result.returncode == 0
    assert result.stdout.strip().startswith(b"msp ")

def test_snapshot_commands():
    """All snapshot subcommands work."""
    # capture
    subprocess.run(["msp", "snapshot", "capture", "test"], check=True)
    # list
    result = subprocess.run(["msp", "snapshot", "list"], check=True)
    assert "test" in result.stdout
    # delete
    subprocess.run(["msp", "snapshot", "delete", "test"], check=True)
```

### Success Criteria
- [ ] >80% coverage on core modules
- [ ] All acceptance tests pass
- [ ] CI runs tests on push

---

## Configuration System (Phase 5)

### Acceptance Tests

```gherkin
Feature: Configuration
  Scenario: Default config
    When I run "msp config list"
    Then output shows default values
    And exit code is 0

  Scenario: Config file precedence
    Given ~/.msp/config.toml exists with custom settings
    When I run "msp status --config ~/.msp/config.toml"
    Then output uses config file values
```

### Success Criteria
- [ ] TOML config file support
- [ ] `msp config list` shows current config
- [ ] `msp config set key value` updates config
- [ ] Config validation prevents invalid values

---

## Performance Optimizations (Phase 6)

### Acceptance Tests

```gherkin
Feature: Performance
  Scenario: Quick status check
    When I run "msp status --quick"
    Then command completes in <1 second

  Scenario: Cached facts
    Given facts were cached 5 seconds ago
    When I run "msp interrogate --json"
    Then output returns fast from cache
```

### Success Criteria
- [ ] `msp status` runs in <3 seconds
- [ ] Cached facts return in <0.5s
- [ ] Parallel network scans show 2x+ speedup
- [ ] Memory usage <200MB during scan
```