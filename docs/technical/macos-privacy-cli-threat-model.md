# macos-privacy-cli — Threat Model

> Companion to `docs/plans/2026-11-17-macos-privacy-cli-architecture-plan.md` (master plan) and `docs/technical/macos-privacy-cli-repository-evidence.md`.
> The tool is *both* the auditor and the most privileged process on the machine it audits, so the trust model is stated from the tool's own perspective.

```mermaid
flowchart TD
    subgraph Host["macOS host"]
        TUI["tui_v2 TUI"] -->|piped argv| CLI["src.main (CLI)"]
        CLI --> CB["command.run_command"]
        CB -->|sudo prefix / osascript| OS["launchctl / socketfilterfw / tccutil / defaults / ps / nettop"]
        CB -->|osascript admin prompt| ASK["Native auth prompt (firewall.py pattern)"]
        CLI --> SCAN["scanner → ~/.msp bundle"]
        CLI --> WF["workflows (renderer only)"]
        CLI --> AI["ai/llm → OpenAI / ollama"]
    end
    AI -->|"unredacted host facts + prompt"| NET["Network / LLM provider"]
    NET -.->|"attacker-influenced tool output (lsof, ps, log)"| AI
    USER["Operator"] -->|approval (advisory only)| TUI
```

## Assets

Host configuration state (launchd jobs, TCC grants, firewall rules, shell init files), evidence artifacts (`~/.msp/*`), operator intent (approval decisions), and LLM credentials in `~/.msp/ai.json`.

## Actors & adversarial paths

1. **Malicious or compromised host output.** Every collector reads attacker-influenceable sources (process listings, logs, app manifests, network connections). Text flows into: rules (evidence strings), reports, and — via `ask` — the LLM prompt. A crafted line can steer the model or pollute a finding. *Current mitigation: none on the LLM path; redaction applies to stored stdout only.*
2. **Approval bypass via the TUI.** The confirmation gate lives in the UI (`tui_v2.py:54–90`, hand-maintained advisory allowlist), not the engine. Any actor that invokes the CLI directly (script, cron, `CommandBroker` bug) executes `remediate`/`shell repair`/`forensics clean` unattended.
3. **Privilege ladder abuse.** `sudo`-prefix commands run with the operator's cached sudo credentials, unscoped and unlogged. A bug that concatenates attacker text into one of the `shell=True` strings (privacy_settings.py:269–282) becomes root.
4. **Evidence tampering.** Findings/backups/scan bundles share `~/.msp` with config and AI keys, are unversioned and unsealed; an attacker with FDA can rewrite history to hide persistence.
5. **FDA paradox (research-confirmed).** Granting Full Disk Access to the *terminal host app* transitively grants it to every unsandboxed program launched from that terminal (Lapcat, 2022 — see `docs/technical/macos-privacy-cli-research-findings.md`). The tool depends on FDA to read TCC.db; therefore the tool's documentation must instruct users to grant FDA narrowly (per-terminal, not blanket) and the tool must never recommend widening it beyond need.
6. **Rollback downgrades.** `spctl --master-enable`'s rollback is `--master-disable` (remediate.py:348–349) — a failed apply of a *hardening* step can leave the host *less* secure than before.

## Design invariants that follow

These become the autonomous execution contract (plan §11):

- Engine-side approval enforcement (the gate lives in the engine, not the UI).
- Per-operation scoped elevation with an audit ledger.
- Evidence stored raw with redaction applied at *presentation/export*, not collection.
- Rollback must be a return to the *pre-state*, never a global toggle flip.
- LLM egress behind a mandatory redaction gate with `local_only` enforced.
