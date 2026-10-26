# AGENTS.md — macos-privacy-cli

> Uniform project-root instruction file (deployed by `~/.agents/scripts/deploy-project-rules.sh`).
> Project-specific detail should live in sibling files (e.g. `CLAUDE.md`, `AGENTS_APP.md`); this file is the invariant core applied to every repo.

---

## Universal Agent Standards

### 1. Mandatory Static Checks (run before reporting work done)
Before finishing any change, run the project's validation chain. Defaults below;
override in `CLAUDE.md` when the project differs.

```bash
# TypeScript / JS projects
npx tsc --noEmit      # strict type check — never suppress with @ts-ignore / tsconfig exclude
npm run lint          # project linter
npm test              # unit tests

# Python projects
python3 -m pytest -q   # or: poetry run pytest
ruff check .           # when ruff is configured

# Every project: pre-spin env validation (see §3)
python3 scripts/validate_env.py --env .env.local
```

### 2. Forbidden Patterns
- **Never commit secrets.** No `.env*`, API keys, tokens, or credentials in git.
  `.env.local`, `.env.production.local` and siblings must stay in `.gitignore`.
- **Never silence the compiler.** `@ts-ignore`, `eslint-disable` for real errors,
  and appending to `tsconfig.json` `exclude` to hide broken code are prohibited.
  Stubs must carry an explicit `// TODO: <AgentName> - <reason>` comment.
- **No mock/fabricated production data.** Placeholder arrays masquerading as
  real data are forbidden; render real empty-states instead. (Test fixtures and
  design-system demos are exempt.)
- **No lazy logging noise.** No `console.log` spam in committed code; prefer the
  project's structured logger.
- **No hard-coded colors/strings** where a design token or constant exists.

### 3. Env Validation Before Container Spins
Run `scripts/validate_env.py` (pydantic schema, present in this repo) before any
`docker compose up`, `next build`, or worker daemon start. The script fails fast
with typed errors (exit 1) so misconfigured `.env` never reaches a container.

```bash
python3 scripts/validate_env.py          # uses .env.local by default (invention-scout)
python3 scripts/validate_env.py --env .env   # AutoGPT-style repos
```

### 4. Git Conventions
- **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`).
- **Commit per feature chunk** — small, reviewable, atomic commits.
- **Amend on iteration** within a feature branch instead of stacking fixup noise.
- Match the repo's existing style when in doubt; see the `git-conventions` skill.

### 5. Code Discovery Preference
Prefer the indexed stores over raw `grep`/`glob`/`read` for code structure and
docs when they are configured for this repo (see sibling files for the project
identifier):
- **codebase-memory-mcp** → `search_graph`, `trace_path`, `get_code_snippet`
- **local-rag / knowledge-rag** → semantic search over `.agent_docs/`, `docs/`

### 6. Agent Workflow Division of Labor
| CLI | Role |
|---|---|
| **Hermes** | Operational commands — cron, sends, gateway, status, bulk ops |
| **Claude Code** | Feature implementation, tests, day-to-day coding |
| **OpenCode** | Deep architectural refactoring, cross-cutting structural work |

---

## Command Addition Standard (msp CLI)

Adding a new command or subcommand must span all of the following dimensions. A change is not "done" until every applicable dimension is addressed.

| Dimension | Location | Requirement |
|---|---|---|
| **CLI routing** | `main.py` | Command routed via `COMMAND_MODULES` or a dedicated `if command == ...` block; appears in `msp --help` epilog. |
| **Module implementation** | `src/<module>.py` | New action/method added with `--json` support, rich fallback, and `interactive_menu` entry. |
| **Interactive menu** | `src/<module>.py` `interactive_menu` | New menu item with label + description, wired to the implementation. |
| **TUI integration** | `src/tui.py` | Surface data in a dashboard widget and/or dedicated screen; add HelpScreen entry. |
| **Help text** | `main.py` epilog | Command listed with usage example under the appropriate command group. |
| **Definition of Done** | — | All of the above implemented, files compile (`py_compile`), command runs end-to-end (normal + `--json`), and no regressions in existing command tests. |

Definition of Done for any command/subcommand addition:
1. CLI: `msp <command> [<subcommand>]` executes and produces correct output.
2. `--json` flag produces valid JSON when supported.
3. Interactive menu item exists with an accurate description.
4. TUI: data surfaced in widget/screen and HelpScreen updated (when TUI-relevant).
5. Help text: appears in `msp --help` epilog.
6. `python3 -m py_compile` passes for all modified files.
7. Manual smoke test of the new command passes.

---

## Skills (load on demand)
Relevant skills: `git-conventions`, `feature-implementation`, `changelog-status-sync`,
`workspace-guardrails`, `codebase-memory`, `ethical-constraints`.
Run `sync-skills` to refresh the shared skill library across agents.
