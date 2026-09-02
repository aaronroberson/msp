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

## Skills (load on demand)
Relevant skills: `git-conventions`, `feature-implementation`, `changelog-status-sync`,
`workspace-guardrails`, `codebase-memory`, `ethical-constraints`.
Run `sync-skills` to refresh the shared skill library across agents.
