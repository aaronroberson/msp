# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `remediation_id` and `evidence_paths` metadata to security rules and findings in `src/rules.py`.
- Interactive menus for `msp audit`, `msp startup`, and `msp tcc`.
- Support for sorting in many commands (`msp list`, `msp services`, `msp startup`, `msp fswatch`, `msp net`, `msp scan`, `msp chain`).
- New core modules: `src/facts.py`, `src/llm.py`, `src/remediate.py`, `src/report.py`, `src/workflows.py`.
- Tests for new modules and remediation metadata.
- Shell completion support via `setup_completion` in `src/command.py`.
- `nist` preset support.
- Comprehensive inventory and audit subcommands to `msp startup`.
- `grant`, `revoke`, and `restore` (placeholder) subcommands to `msp tcc`.

### Changed
- Refactored `src/rules.py` to use `remediation_id` and `evidence_paths` for better automated remediation.
- Updated `COMMANDS.md` with new subcommands, options, and sort keys.
- Integrated `rich` for better table rendering and interactive menus.
- Improved error handling in `msp audit` when facts are missing from stdin.

### Fixed
- Improved sort key consistency across all modules.
