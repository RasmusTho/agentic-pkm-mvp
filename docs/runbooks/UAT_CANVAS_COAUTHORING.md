State: covers the Agentic Canvas Co-Authoring (Phase 2: #1716/#1717) and Chat→Panel Governance Handoff (Phase 3: #1726/#1727/#1728) capabilities, plus the live served-page co-authoring wiring (#1733), intent-level governance routing (Phase 4: #1743/#1744), and the carried governance intent in routed proposal payloads (#1772). Dev/staging only, gated behind `CANVAS_ENABLED`.

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
| 4 | Intent-level governance classification + routing on `/coauthor` (classified `action_type` before generation) | #1743 / PR #1747, #1744 / PR #1754 |
| 4 | Original governance intent carried into routed Panel proposal payloads | #1772 |

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

The `companion_ui` package lives under `companion-ui/companion-app/` (it is **not** part of the repo
root package set in `pyproject.toml`), so run the module from that directory — otherwise
`python -m companion_ui.workspace.serve_dev_page` fails with `ModuleNotFoundError`:

```bash
cd companion-ui/companion-app
COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=127.0.0.1 PORT=8111 \
  python -m companion_ui.workspace.serve_dev_page
# open http://127.0.0.1:8111/
```

(Equivalently, from the repo root, prefix with `PYTHONPATH=companion-ui/companion-app`.)

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

## 4) Live UAT — Phase 3 + Phase 4 governance handoff loop

**Phase 4 (intent-level routing) shipped in PR #1754 / issue #1744.** The `/coauthor` path now
classifies the *intent* with an LLM-backed cognition (`IntentClassifierCognition`) before any body
is generated. A governance-bearing natural-language intent (e.g. "promote this note to evergreen")
routes to Panel *before* generation, carrying the classified `action_type`, and leaves the note
unchanged. The explicit `/governance` endpoint remains available as a deterministic alternative.

**Deterministic natural-language routing walkthrough:**

1. With an active session (`POST /api/canvas/sessions` → note the `session_id`) and `CANVAS_ENABLED=1`,
   submit a governance-bearing intent via `/coauthor`:

   ```bash
   curl -s -X POST "http://127.0.0.1:18001/api/canvas/sessions/<session_id>/coauthor" \
     -H 'Content-Type: application/json' \
     -d '{"intent":"promote this note to evergreen"}'
   # -> 409 {"status":"routed_to_panel","intent_id":"…",
   #         "action_type":"maturity_transition",
   #         "detail":"Governance-bearing — routed to the gated Panel pipeline; note body left unchanged."}
   ```

   The classifier labels the intent `GOVERNANCE_BEARING / maturity_transition` before body
   generation. The note body is **not** changed. Note the returned `intent_id`.

   The staged Panel proposal carries the original request (#1772): its action params include
   `original_request: "promote this note to evergreen"`, `routed_via: "intent_classifier"`,
   `intent_class: "governance_bearing"`, and `classified_action_type: "maturity_transition"`,
   and the proposal instruction quotes the request text
   (`canvas governance: maturity_transition — "promote this note to evergreen"`). Reviewing the
   proposal therefore shows what was actually asked — confirming it still routes through the
   gated Panel flow; nothing auto-executes from the carried text.

2. Alternatively, trigger deterministically via the explicit governance endpoint (unchanged from
   Phase 3):

   ```bash
   curl -s -X POST "http://127.0.0.1:18001/api/canvas/sessions/<session_id>/governance" \
     -H 'Content-Type: application/json' \
     -d '{"action_type":"maturity_transition","payload":{"to":"evergreen"}}'
   # -> 200 {"intent_id":"…","session_id":"…","artifact_id":"…",
   #         "action_type":"maturity_transition","status":"routed_to_panel"}
   ```

3. Confirm the canvas region shows a read-only **"view in Panel"** affordance
   (`data-testid="workspace-canvas-view-in-panel"`, `data-intent-id` = the returned `intent_id`).
4. In the **Panel rail**, confirm the matching proposal appears with the server-declared canvas-origin
   attribution (`data-testid="workspace-panel-proposal-origin"`, `data-proposal-origin="canvas_coauthoring"`),
   correlated by `proposal_id == intent_id`.
5. Decide/confirm the proposal through the existing Panel flow (`POST /api/panel/confirm`).
6. After execution, confirm the **receipt reflects back** into the canvas/originating context
   (read-only, server-declared, keyed by `intent_id`). With no durable receipt yet, expect a
   pending/blocked posture — never an invented receipt.

Pass criteria: a governance-bearing intent (natural-language or explicit) never mutates the note
directly, is navigable from the canvas region to a canvas-origin Panel proposal, confirms through
the gated path, and its outcome is reflected back read-only.

**Degraded-classifier fallback:** if the reasoning provider is unavailable, the classifier returns
`classified=False` (conservative default: `CO_AUTHORING`) and the path falls through to the
generate-and-apply loop unchanged. The body-frontmatter backstop remains as defense-in-depth for
any governance-bearing generation that slips through on the degraded path. A backstop-routed
proposal still carries the original request text in its payload
(`original_request` + `routed_via: "body_frontmatter_backstop"`); since no trusted classification
exists on that path, no classifier fields are fabricated.

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
