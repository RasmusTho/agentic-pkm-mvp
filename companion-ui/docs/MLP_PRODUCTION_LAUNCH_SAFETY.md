---
name: Companion UI MLP Production Launch Safety
description: Minimal operator-safe launch profile for the Companion UI MLP production server-rendered shell.
doc_role: Production launch safety / operator runbook
authority: Operational guidance subordinate to runtime authority docs, Companion UI contracts, and shipped behavior.
owner: Companion UI / operations
last_reviewed: 2026-05-21
governing_issue: "#1188"
---

# MLP Production Launch Safety

## Purpose

This document defines the minimal production launch safety pass for the Companion UI MLP under #1177 and #1188.

It documents how to run the current server-rendered Companion UI shell against the production runtime without implying public internet readiness or a full frontend platform.

## Authority and Boundaries

Companion UI remains a shell/host. It is not a fourth authority surface.

The runtime remains authoritative for policy, WriteGuard, idempotency, action handling, events, receipts, and durable projection. The UI never writes vault files directly and never chooses the vault.

Vault / Markdown remains the human-readable canonical surface. The UI must show runtime/channel and guard/degraded state where the workspace payload exposes it.

## Launch Command

From the repository root:

```bash
cd companion-ui/companion-app
COMPANION_API_BASE_URL=http://127.0.0.1:18000 HOST=127.0.0.1 PORT=8113 \
  python -m companion_ui.workspace.serve_production_page
```

Open:

```text
http://127.0.0.1:8113/?note_path=<runtime-relative-note-path>
```

The runtime API must already be running on the configured production API base URL.

## Port Map

| Surface | Dev | Test | Prod |
|---|---:|---:|---:|
| Runtime API | 18001 | 18002 | 18000 |
| Companion UI | 8111 | 8112 | 8113 |

## Bind Address

Default production binding is local-only:

```text
HOST=127.0.0.1
```

LAN or Tailscale exposure must be an explicit operator action:

```bash
HOST=0.0.0.0 PORT=8113 COMPANION_API_BASE_URL=http://<trusted-host>:18000 \
  python -m companion_ui.workspace.serve_production_page
```

Use LAN/Tailscale only on trusted personal networks or trusted tailnets. Prefer Tailscale over open LAN when another device needs access.

The production and dev/test UI launchers use threaded request handling so a slow browser, LAN, or Tailscale client connection does not block unrelated local requests. This does not change the exposure posture: LAN/Tailscale binding is still explicit operator opt-in, and public internet exposure remains unsupported.

## No Public Exposure

Do not expose this profile to the public internet.

The current MLP production profile does not provide auth, TLS, reverse proxy hardening, multi-user isolation, or public exposure safety. Public access requires a separate accepted auth/TLS/reverse-proxy contract and implementation.

## Readiness and Health Checks

Before use:

1. Start the production runtime API.
2. Confirm the runtime health endpoint responds:

```bash
curl -fsS http://127.0.0.1:18000/health
```

3. Start Companion UI with the launch command above.
4. Open a real note through `GET /api/companion/workspace` by loading the UI with a runtime-relative `note_path`.
5. Confirm the UI visibly shows runtime/channel, WriteGuard state, Canvas enabled/disabled state, guard/degraded state, artifact identity or unresolved fallback, note path, content hash, and receipt/block state when present.

## Stop and Rollback

Stop the Companion UI process with `Ctrl-C` in the terminal that launched it.

Rollback options:

- Return to the previous known-good git checkout or release channel.
- Restart the runtime API on the previous known-good version.
- Restart Companion UI using the same local-only bind and API base URL.

The UI does not own durable vault writes, so UI rollback does not require vault migration. Runtime rollback must still respect runtime migration and data-store rules.

## Known Limitations

- Minimal server-rendered shell.
- No auth, TLS, or reverse proxy by default.
- No public internet safety.
- No global inbox.
- No direct UI vault writes.
- No UI-side proposal reclassification.
- Canvas session and proposal visibility may include in-memory or volatile limits where the runtime reports them.
- Find is candidate/unavailable display, not a full search product.
- Resurface controls are unavailable unless runtime-backed persistence exists.

## Verification

Issue #1188 verification:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/companion_ui/test_production_launch_profile.py \
  tests/companion_ui/test_real_note_workspace_dev_server.py
python3 scripts/docs_guard.py
git diff --check
```
