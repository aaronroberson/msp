# CLAUDE.md — macos-privacy-cli

> Uniform project-root instruction file (deployed by `~/.agents/scripts/deploy-project-rules.sh`).
> This file is the invariant command/validation core. Repo-specific detail belongs in the
> project's existing docs.

---

## Universal Command & Validation Contract

### Dev loop
```bash
npm run dev            # typical dev server (override per project)
```

### Mandatory pre-push / before-report checks
```bash
npx tsc --noEmit        # strict type check
npm run lint
npm test
python3 scripts/validate_env.py   # env schema check before container spins
```

### Never do
- Commit `.env*` or any secret.
- Use `@ts-ignore` / eslint-disable to mask compile errors.
- Push mock/fake production data.
- Skip the validation chain and report work as done.

### Commit style
Conventional Commits; one logical change per commit; amend on iteration.

---

## Stack / run commands (project-specific — fill in)

| Task | Command |
|---|---|
| Install | `npm install` |
| Dev | `npm run dev` |
| Typecheck | `npx tsc --noEmit` |
| Lint | `npm run lint` |
| Test | `npm test` |
| Env validate | `python3 scripts/validate_env.py` |
