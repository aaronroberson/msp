# Implementation Plan: Grouped Commits

**Goal:** Commit all pending changes in logical, conventional commits, ignoring temporary database and history files, and finally push to the remote repository.

**Approach:**
1. Create `.gitignore` to exclude `lancedb/`, `$APFEL_GLOBAL_HISTORY`, and `.pytest_cache/`.
2. Stage and commit files in functional groups with conventional commit messages and bodies.
3. Push to the remote repository.

### Commit Groups

1. **chore: project configuration and ignore rules**
   - Files: `.gitignore`, `pyproject.toml`, `deps.json`, `requirements.txt`
   - Body: Add `.gitignore` to exclude local databases and history files. Update `pyproject.toml` and dependencies with project configuration.

2. **docs: update documentation and specifications**
   - Files: `CHANGELOG.md`, `COMMANDS_UPDATE_PLAN.md`, `COMMANDS.md`, `SPEC_TCC.md`
   - Body: Add update plans for commands and TCC specifications. Update main commands documentation and changelog.

3. **feat(core): update main CLI command structure**
   - Files: `main.py`, `src/command.py`
   - Body: Enhance CLI dispatcher and command processing logic to support new modules and interactive modes.

4. **feat(network): enhance network and traffic monitoring**
   - Files: `src/network.py`, `src/traffic.py`
   - Body: Add improved sorting and filtering for network connections and traffic analysis commands.

5. **feat(security): update privacy and security settings management**
   - Files: `src/privacy_settings.py`, `src/security.py`, `src/sharing.py`, `src/tcc.py`
   - Body: Expand security settings coverage, including computer sleep options, sharing status sorts, and TCC permissions handling.

6. **feat(system): enhance file system, startup, and dependencies tools**
   - Files: `src/deps.py`, `src/fswatch.py`, `src/startup.py`
   - Body: Add subcommands and sort capabilities for dependency management, file system watching, and startup item auditing.

7. **feat(scanner): improve security scanner and rules engine**
   - Files: `src/scanner.py`, `src/rules.py`, `tests/test_rules.py`
   - Body: Update security scanner with new heuristics and sorting. Refine remediation rules and tests.

8. **feat(ai): integrate LLM and facts management**
   - Files: `src/ai.py`, `src/llm.py`, `src/facts.py`, `tests/test_llm.py`, `tests/test_facts.py`
   - Body: Add Apfel LLM integration for local AI-assisted analysis and fact generation. Include comprehensive tests.

9. **feat(workflows): implement method chaining and advanced workflows**
   - Files: `src/chain.py`, `src/workflows.py`, `tests/test_workflows.py`
   - Body: Introduce method chaining with custom iteration and interactive prompts. Add workflow tests.

10. **feat(remediate): add reporting and remediation capabilities**
    - Files: `src/remediate.py`, `src/report.py`, `src/snapshot.py`, `tests/test_remediate.py`, `tests/test_report.py`
    - Body: Implement detailed report generation, system snapshot capture/restore with custom flags, and automated remediation actions.

11. **chore: executable entry point**
    - Files: `macos-privacy`
    - Body: Add CLI entry point script/symlink.

### Implementation Steps
1. Execute the git add/commit commands sequentially as defined in the plan.
2. Execute `git push` once all commits are complete.