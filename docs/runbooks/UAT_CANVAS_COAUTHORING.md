State: covers the Agentic Canvas Co-Authoring (Phase 2: #1716/#1717) and Chat→Panel Governance Handoff (Phase 3: #1726/#1727/#1728) capabilities, plus the live served-page co-authoring wiring (#1733). Dev/staging only, gated behind `CANVAS_ENABLED`.

# UAT — Agentic Canvas Co-Authoring & Chat→Panel Handoff

Purpose: end-to-end operator validation of the agentic canvas loop against a real vault note — a user
states an intent, an agent edits the note body in place, undo works, and a governance-bearing intent
is routed to a navigable Panel proposal whose executed receipt reflects back into the canvas context.

Scope: test/runbook only. No new feature work. This loop is **Agentic Lab**: opt-in, gated behind
`CANVAS_ENABLED`, and never changes Core Runtime defaults.

## Capability under test

| Phase | Component | Issues / PRs |
|-------|-----------|--------------|
| 2 | Write-capable co-authoring cognition + `POST /api/canvas/sessions/{id}/coauthor` | #1716 / PR #1720 |
| 2 | Companion UI server-gated co-authoring region (intent → applied edit → undo) | #1717 / PR #1723 |
| 3 | `GovernanceHandoffRef` (structured 409) + proposal-scoped `proposal_origin` | #1726 / PR #1731 |
| 3 | Canvas region view-in-Panel affordance + Panel rail canvas-origin attribution | #1727 / PR #1732 |
| 3 | Executed receipt reflected into the originating context | #1728 / PR #1734 |
| 3 | Live served-page `/coauthor` wiring (intent input, co-author control, 409 affordance) | #1733 / PR #1736 |

## Preconditions

- Repo Python env active with deps installed (`.venv`).
- A dedicated test vault with at least one `.md` note. Canonical path: `make test-bootstrap` →
  `vault-test/` (see `docs/runbooks/RUNBOOK_STARTUP.md`, `docs/ENVIRONMENTS.md`). Do **not** point this
  at a real personal vault.
- An edit-capable LLM provider configured for co-authoring. With a mock/degraded provider the
  `/coauthor` call returns **HTTP 503** by design (it must not write diagnostic text into the note) —
  acceptable for the negative path, but the positive applied-edit path needs a real provider.
- `STORE_BACKEND=memory` is sufficient; Postgres is only needed if you also exercise durable receipts.

## 1) Automated tests (must pass first)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q \
  tests/chat/test_coauthoring_cognition.py \
  tests/api/test_canvas_coauthor_api.py \
  tests/api/test_canvas_governance_handoff.py \
  tests/companion_ui/test_canvas_coauthoring_surface.py \
  tests/companion_ui/test_chat_to_panel_handoff.py \
  tests/companion_ui/test_handoff_receipt_reflection.py \
  tests/companion_ui/test_serve_dev_page_coauthor_wiring.py
```

Expected: all pass (behavioral proof of the contracts below). These are the authoritative slice
verification; the live steps confirm the operator experience on top.

## 2) Start the runtime (two processes)

**Backend API (port 18001), Canvas enabled:**

```bash
export VAULT_ROOT="$PWD/vault-test"        # the bootstrapped test vault
export CANVAS_ENABLED=1                     # enable the canvas surface (default off)
# Edit-capable provider env as configured for your setup (LLM_PROVIDER / REASONING_PROVIDER ...)
scripts/start_full_system.sh               # or your standard dev API start path
python -m app.cli health status --json     # expect state running/catch_up, writes_allowed=true
```

**Companion UI dev shell (port 8111):**

```bash
COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=127.0.0.1 PORT=8111 \
  .venv/bin/python -m companion_ui.workspace.serve_dev_page
# open http://127.0.0.1:8111/
```

Confirm the banner prints `DEV/STAGING ONLY` and `Runtime API: http://127.0.0.1:18001`.

## 3) Live UAT — Phase 2 co-authoring loop

1. Open a vault note in the shell. Confirm the **canvas co-authoring region** is present
   (`data-testid="workspace-canvas-coauthor"`) — it renders only because `guards.canvas_enabled` is true.
2. Enter a co-authoring intent (e.g. "tighten the intro paragraph") in the intent input
   (`data-testid` from #1733: `workspace-canvas-coauthor-intent`) and submit the co-author
   control (`workspace-canvas-coauthor-submit`).
   - Expect: a `POST /api/canvas/sessions/{id}/coauthor` call; the note body re-renders with the
     agent-applied edit (`workspace-canvas-coauthor-applied-body`) and the server's change summary
     (`workspace-canvas-coauthor-change-summary`). **No diff-review gate.** A provider-unavailable
     (503) response surfaces a calm notice (`workspace-canvas-coauthor-notice`) and writes nothing.
3. Use **Undo** (`workspace-canvas-undo`). Expect: the prior body is restored via
   `DELETE /api/canvas/sessions/{id}/edits/last`.
4. **Disabled check:** restart the API with `CANVAS_ENABLED=0`, reload. Expect: the co-authoring
   region is inert — no intent input, no co-author control, no `/coauthor` call.

Pass criteria: the body changes in place from a natural-language intent, undo restores it, and the
region is inert when the flag is off.

## 4) Live UAT — Phase 3 governance handoff loop

1. With `CANVAS_ENABLED=1`, enter a **governance-bearing** intent (e.g. "promote this note to
   evergreen" / a frontmatter/maturity change).
   - Expect: `POST /coauthor` returns **HTTP 409** with body
     `{ "status":"routed_to_panel", "intent_id":"…", "action_type":"…" }`. The note body is **not**
     changed.
2. Confirm the canvas region shows a read-only **"view in Panel"** affordance
   (`data-testid="workspace-canvas-view-in-panel"`, `data-intent-id` = the returned `intent_id`).
3. In the **Panel rail**, confirm the matching proposal appears with the server-declared canvas-origin
   attribution (`data-testid="workspace-panel-proposal-origin"`, `data-proposal-origin="canvas_coauthoring"`),
   correlated by `proposal_id == intent_id`.
4. Decide/confirm the proposal through the existing Panel flow (`POST /api/panel/confirm`).
5. After execution, confirm the **receipt reflects back** into the canvas/originating context
   (read-only, server-declared, keyed by `intent_id`). With no durable receipt yet, expect a
   pending/blocked posture — never an invented receipt.

Pass criteria: a governance-bearing intent never mutates the note directly, is navigable from the
canvas region to a canvas-origin Panel proposal, confirms through the gated path, and its outcome is
reflected back read-only.

## 5) Negative / safety checks

- Mock/degraded provider → `/coauthor` returns **503**, note unchanged (no diagnostic text written).
- Frontmatter/cross-note generation → routed to Panel (409), never applied as co-authoring.
- The served page composes no body locally and performs no direct vault write (server declares, UI
  renders). Receipts are never invented by the UI.

## 6) Record results

Capture for each step: the HTTP call observed (method + path + status), the rendered `data-testid`
element seen, and pass/fail. File any defect as a bug issue referencing this runbook and the relevant
PR. Keep this runbook as the durable operator script for the canvas co-authoring + handoff loop.

## Related

- `docs/CANVAS_CHAT_SURFACE/README.md` (Phase 2 + Phase 3 capability specs)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`
- `docs/runbooks/UAT_REAL_NOTE_VERTICAL_SLICE.md` (sibling UAT model)
- `docs/ENVIRONMENTS.md` (port map), `docs/runbooks/RUNBOOK_STARTUP.md` (startup)
