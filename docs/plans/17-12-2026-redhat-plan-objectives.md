Objective
- Produce an evidence-backed, 12-section security/privacy architecture report and phased implementation plan for the existing macos-privacy-cli repo (macOS security/privacy toolkit with TUI), including graph-driven durable automation design, autonomy/approval model, execution-ready backlog, first implementation slice, and an autonomous execution contract.
- Planning only: no product changes, installs, privileged actions, or intrusive scans during this assignment.
Important Details
- Repo root: /Users/conscious/macos-privacy-cli; branch main, HEAD a512eae; dirty worktree (modified: CHANGELOG.md, src/deps.py, src/main.py, src/scanner.py, src/tui.py, src/tui_v2.py, src/tune.py, tests/test_tune.py; untracked: docs/audits/command-suite-audit.md, docs/plans/* (3 new), screenshots/, tests/test_deps.py, tests/test_scan_bundle.py).
- Stack: Python ≥3.9 (mypy targets 3.12), setuptools src-layout; deps argcomplete>=3.0.0, rich>=13.0.0, textual>=0.80.0; optional llm = openai>=1.0.0; test = pytest>=7.0, mypy>=1.8.
- Entry points (pyproject.toml): msp/mac-privacy/mpc → src.main:console_main; msp-interrogate→src.facts:main; msp-reason→src.llm:main; msp-remediate→src.remediate:main; msp-report→src.report:main; msp-workflow→src.workflows:main; msp-forensics→src.forensics:main.
- CLI commands (from src/main.py docstring): status, list, enable/disable, net, startup, firewall, fswatch, traffic, scan, tcc, audit, interrogate, reason, remediate, report, workflow, forensics, ask/ai, chain, doctor, tune (alias merging into doctor), presets, tui. Dispatch is argparse-based; imports setup_completion, suggest_command, logger from src.command.
- External tool deps (deps.json): fswatch (brew, required, auto-install), ollama (brew, required, auto-install; suggests qwen2.5-coder:1.5b), apfel (optional Apple Intelligence CLI fallback), plus more (file truncated).
- Codebase-memory index exists: project Users-conscious-macos-privacy-cli, 2602 nodes/9900 edges; languages Python 55 files, HTML 23, YAML 12, Bash 4, TOML 1.
- Baseline "documented vs implemented" mismatch: root CLAUDE.md is a generic npm/TypeScript template (npm run dev/lint/test, scripts/validate_env.py) that does not match this Python project; AGENTS.md also exists.
- Repo also contains adjacent/possibly out-of-scope material: frigate-setup/, onvif_manager.py, lancedb/, .mcp.json, .agents/, .claude/, .stitch/, .docs_archive/, AUDIT_FULL.md, AUDIT_INSTALLABILITY.md.
- src/workflows.py is small (451 lines): WORKFLOW_SCHEMA_VERSION = "1.0"; frozen dataclasses WorkflowStep(id, concept, title, description, command_hint, destructive, inputs, outputs) and Workflow(id, title, description, steps); BUILTIN_WORKFLOWS dict (includes daily); docstring "Built-in non-destructive workflow runner"; imports LLMReasoner from src.llm — this is the seed for graph-driven automation.
- src/rules.py symbols: get_path, Rule (applies_to_profile, evaluate, extract_evidence), Finding (from_rule, to_dict), RuleEngine (evaluate, rules_for_profile), rule decorator, default_rules(), evaluate(), findings_to_json, findings_to_table, summarize, load_facts, main; helpers _password_delay_exceeds_profile, _screen_lock_exceeds_profile, _has_exposed_developer_port.
- src/facts.py symbols: FactCollector (collect, _safe_collect, per-section collectors: privacy_settings, network, startup, sharing, security, tcc, shell), collect_facts, collect_host_metadata, facts_to_json, write_facts, redact_facts, _redact_value/_redact_string/_redact_endpoint, _connection_to_* (output truncated).
- TUI: two generations coexist — src/tui.py (876 lines) and src/tui_v2.py (1566 lines, current focus; .stitch GitHub-dark palette committed; prior commit 044ecfa sunset tui_xli).
- Deliverable format is fixed: report sections in order 1–12 (Executive assessment; Repository evidence; Threat model; Research findings; Target architecture; Automation design; TUI plan; Phased implementation plan; Execution-ready backlog table Task ID|Task|Location|Dependencies|Risk|Effort|Verification|Done criteria; First implementation slice; Autonomous execution contract; Open questions), with Mermaid diagrams, workflow schema, executor pseudocode, crash-resume and failed-remediation walkthroughs.
Work State
Completed
- Established repo baseline: file inventory, line counts (~22,925 lines in src/*.py), git history/status, packaging config, dependency manifests, entry points, CLI command surface.
- Read src/main.py routing header and src/workflows.py in full (start of it); grepped symbol maps for src/rules.py, src/facts.py, and (partially) src/remediate.py, src/workflows.py, src/sdk.py, src/errors.py.
- Retrieved codebase-memory architecture overview (node/edge counts, languages, entry points).
- Identified key evidence gaps: CLAUDE.md mismatch, dual TUI, textual-based stack, LLM integration points (src/llm.py, src/ai.py, openai optional dep, ollama/apfel).
Active
- Repository inspection phase: need to read remaining engine modules in detail — src/remediate.py (815), src/scanner.py (757), src/sdk.py (478), src/errors.py (145), src/rules.py rule catalog (default_rules body, lines ~367–620), src/llm.py, src/report.py, src/security.py, src/firewall.py, src/tcc.py, src/privacy_settings.py, src/startup.py, src/network.py.
- Still to inspect: src/tui_v2.py screen/widget structure, existing docs/audits/* and docs/plans/* (esp. command-suite-audit.md, utility-expansion.md), tests/ layout, AGENTS.md, AUDIT_FULL.md.
- Not yet started: external research (Apple docs: TCC, Endpoint Security, FileVault, notarization, launchd/SMAppService, Unified Logging; TUI/orchestration framework comparisons), threat model, and report authoring.
Blocked
- (none) — some tool outputs were truncated (e.g., deps.json, facts.py grep, architecture entry_points list); re-read specific ranges if exact content needed.
Next Move
1. Read engine modules with side effects and trust boundaries: src/remediate.py, src/scanner.py, src/sdk.py, src/errors.py, plus default_rules() body in src/rules.py (lines ~367–660).
2. Inspect TUI architecture (src/tui_v2.py class/screen/widget map) and existing audit/plan docs (docs/audits/command-suite-audit.md, docs/plans/utility-expansion.md, docs/plans/12-11-2026-utility-expansion-plan-structure.md, AUDIT_FULL.md) to align the new plan with prior findings; then proceed to research and report authoring.
Relevant Files
- pyproject.toml: packaging, entry points, deps, pytest/mypy config.
- deps.json: external brew tool dependencies (fswatch, ollama, apfel) and auto-install metadata.
- src/main.py (680): argparse CLI dispatch, command surface.
- src/workflows.py (451): existing workflow dataclasses/schema v1.0 — seed for graph automation design.
- src/rules.py (863): rule engine, Rule/Finding/RuleEngine, default_rules().
- src/facts.py (580): fact collection + redaction pipeline (FactCollector, redact_facts).
- src/remediate.py (815): remediation planner/executor — key privilege boundary to inspect.
- src/scanner.py (757), src/security.py (288), src/firewall.py (130): assessment/controls.
- src/tcc.py (998), src/privacy_settings.py (1296): TCC/privacy integrations.
- src/startup.py (1611), src/network.py (989): persistence and network visibility.
- src/tui_v2.py (1566) and src/tui.py (876): Textual TUI layers (v2 current).
- src/llm.py (562), src/ai.py (1043): LLM reasoning surfaces (optional openai, ollama/apfel).
- src/report.py (345), src/sdk.py (478), src/errors.py (145), src/chain.py (539), src/command.py (511).
- docs/audits/command-suite-audit.md, docs/plans/*.md, AUDIT_FULL.md, AUDIT_INSTALLABILITY.md: prior audits/plans to reconcile with.
- CLAUDE.md, AGENTS.md: documented-vs-implemented mismatch evidence.
- tests/ (incl. new tests/test_deps.py, tests/test_scan_bundle.py): existing test baseline.
- frigate-setup/, onvif_manager.py, .mcp.json, .stitch/: ancillary/camera and tooling artifacts; assess in/out of scope.