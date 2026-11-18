# macos-privacy-cli — Research Findings (primary sources)

> Companion to `docs/plans/2026-11-17-macos-privacy-cli-architecture-plan.md` (master plan).
> Primary-source research supporting the target architecture and automation design.

## 1. TCC database access (Apple DTS + community forensics)

- Two databases, SIP-protected; reading either requires the *reading process* to hold Full Disk Access; writing is impossible with SIP on (Apple DTS forum thread 114452: "No API to test FDA; the TCC.db location is not API — do the real operation and handle errors").
- `auth_value`: 0 = denied, 2 = allowed, 3 = limited (schema undocumented, changes between releases — treat read-only).
- System DB (`/Library/Application Support/com.apple.TCC/TCC.db`) holds FDA/Accessibility/Screen Recording/Input Monitoring/Endpoint Security; user DB (`~/Library/…`) holds camera/mic/Automation/folder access; MDM grants live in `MDMOverrides.plist` (PPPC). Always query both + overrides, and mark incompleteness when a read fails.
- `tccutil` can only reset — never grant; programmatic grant requires MDM/PPPC (and cannot silently grant Screen Recording).
- TCC decisions surface in Unified Logging: `log stream --predicate 'subsystem == "com.apple.TCC"'` — a cheap, SIP-safe evidence source the tool currently ignores.

**Consequences for this project:** `tcc.py`'s read-only stance is correct and matches Apple guidance; the fix is *provenance and incompleteness semantics* (target architecture F4), not writes. FDA acquisition must become a guided, first-class, narrowest-possible flow with the Lapcat caveat stated.

Sources: developer.apple.com/forums/thread/114452; Huntress "Ask the Mac Guy: FDA"; machardening.com TCC/PPPC guide; macforensics.app TCC forensics; lapcatsoftware.com/articles/FullDiskAccess.html; fullmetalmac.com TCC overview.

## 2. Privileged operations on modern macOS

- `SMJobBless` (10.6) is deprecated since macOS 13 → **`SMAppService`** for launch agents/daemons; daemon-containing apps must be **notarized**; `register()` requires admin approval in System Settings; status is *not* process liveness; signing binds helper to product; helper must validate clients via code-signing/audit-token; keep IPC narrow; include protocol/build version handshake.
- Least-privilege guidance (WWDC23 environment constraints; Apple daemon design docs): keep UI, networking, and parsing in the least-privileged process; split privileged operations into a narrow service; do not choose a daemon merely to avoid user-session constraints.
- For a *CLI context*, the pattern `osascript … do shell script … with administrator privileges` remains the standard non-daemon scoped-elevation mechanism — which is precisely what `firewall.py` already does, once per operation, with no cached authorization.

**Consequences:** Do **not** propose an SMAppService daemon now (notarization + bundle restructuring + IPC is a distribution-level commitment). Instead: make `firewall.py`'s per-op AppleScript elevation the *shared broker* for all privileged calls; revisit a daemon only when scheduled unattended scans become a product requirement (plan §12 Q3).

Sources: developer.apple.com SMAppService/SMJobBless/XPC docs; WWDC23 session 10266; danielcosenza.com SMAppService & SMJobBless migration posts; Apple BPSystemStartup daemon design archive.

## 3. Evidence integrity & logging

- Unified Logging (`log show/stream` with subsystem predicates) is the system-supported evidence channel; combined with `fswatch`/hash baselines (G-5) it enables durable audit trails without kernel extensions.
- Endpoint Security framework would give kernel-level event streams but requires a special Apple entitlement and a notarized app — out of scope for a CLI; document as future work (matches the known ES false-negative caveat already documented in `docs/plans/utility-expansion.md` A1).

## 4. Workflow/orchestration patterns

- Durable execution of mutating steps reduces to: (a) DAG or ordered-list of typed operations, (b) persisted state machine with per-step status transitions, (c) idempotency + verification-after-apply, (d) rollback-on-verify-failure, (e) crash-resume by replaying state from disk. No external dependency is needed to build this; Python's stdlib (json state files, `retry_with_backoff` already in `src/sdk.py`) suffices. Textual TUI already has the panes needed for run monitoring; an approval-inbox pane is a natural extension.
