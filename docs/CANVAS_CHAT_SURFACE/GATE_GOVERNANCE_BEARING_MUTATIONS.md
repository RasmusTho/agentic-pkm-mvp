---
name: Gate Governance-Bearing Mutations
description: Ensure that mutations originating from a canvas session that are governance-bearing (frontmatter classification, cross-note, lifecycle transitions) route through the same gated-execution pipeline as Panel, not through the co-authoring path.
task_id: CANVAS-03
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md :: The Authority Split :: Governance-bearing
parent_capability: Canvas Chat Surface
prerequisites: [CANVAS-01, CANVAS-02]
depends_on: [WRITE_SESSION_LOGS.md, CO_AUTHOR_NOTE_BODY.md]
can_parallelize_with: []
---

State: Implemented. Delivered by issue #685 (2026-04-29).

# Gate Governance-Bearing Mutations

## Purpose

Canvas Chat has two mutation classes with different authorization models. The co-authoring path (CANVAS-02) handles body edits authorized by user presence. This task handles everything else: mutations that carry governance meaning must not bypass the gated pipeline, even during an active canvas session.

## What This Task Does

1. **Formalizes the governance-bearing set** — canonically defined in the spec; this task makes that set machine-enforceable from a canvas session context:
   - Frontmatter field writes where the field carries classification or governance meaning: `type`, `maturity`, `review_state`, `kind`, scope/sphere tags, any field named in the Panel action catalog as governance-bearing
   - Cross-note operations: writes to any note other than `session.note_path`
   - Note lifecycle transitions: creation, deletion, rename, move, archival
   - Promotion of maturity or commitment state

2. **Canvas-to-Panel bridge** — `app/chat/governance_router.py` (new):
   - `request_governance_action(session, action_type, payload) -> PendingAction`
   - Converts a canvas-originated governance request into a Panel-compatible intent
   - Routes it through the existing admission path (`allowlist`, `write_guard`, `policy gate`, `event_id` dedup)
   - Returns a `PendingAction` with receipt linkage — canvas session can record the pending action in its session log
   - Does **not** execute immediately; respects the `observation -> normalization/contract -> admission -> execution` boundary

3. **Session log records pending actions** — when a governance action is requested, the session log records it as pending with the Panel intent ID, not as an executed change.

4. **Explicit rejection in CanvasWriter** — `CanvasWriter.apply_edit` (CANVAS-02) already raises `GovernanceBearingMutationError` for frontmatter writes; this task adds the complementary positive path: instead of just rejecting, the canvas surface can route to `GovernanceRouter.request_governance_action`.

## Concretely

```python
from app.chat.governance_router import GovernanceRouter, GovernanceActionType

router = GovernanceRouter(panel_pipeline=..., session_log_writer=log_writer)

# User says: "mark this note as evergreen"
pending = router.request_governance_action(
    session=session,
    action_type=GovernanceActionType.FRONTMATTER_UPDATE,
    payload={"field": "maturity", "value": "evergreen"}
)
# pending.intent_id links to the Panel pipeline entry
# session log records: "Governance action pending: maturity=evergreen (intent: <id>)"
# The note is NOT updated until admission completes through the normal Panel path
```

Attempting to bypass via `apply_edit` still raises:
```python
canvas.apply_edit(session, "---\nmaturity: evergreen\n---\n\nBody")
# GovernanceBearingMutationError — use GovernanceRouter for this
```

## Why This Matters

The gated-execution invariant is the core safety property of the whole system. If canvas Chat can write classification fields, create notes, or promote maturity by going through the co-authoring path, the invariant collapses. The Panel admission path exists precisely to enforce allowlist checks, write-guard state, idempotency, and receipt generation for these actions. Canvas Chat must use it — this is not a convenience integration, it is the architectural constraint named in `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`.

## Acceptance Criteria

- [ ] `app/chat/governance_router.py` exists with `GovernanceRouter` and `request_governance_action`.
  - Verify: `tests/chat/test_governance_router.py::test_request_routes_to_panel_pipeline`
- [ ] A governance action request does not immediately mutate the note; it creates a Panel intent and returns a receipt reference.
  - Verify: `tests/chat/test_governance_router.py::test_request_does_not_write_note_directly`
- [ ] The session log records the pending governance action with the Panel intent ID.
  - Verify: `tests/chat/test_governance_router.py::test_session_log_records_pending_intent`
- [ ] `CanvasWriter.apply_edit` (from CANVAS-02) continues to raise `GovernanceBearingMutationError` for frontmatter in body; this task does not remove that guard.
  - Verify: `tests/chat/test_canvas_writer.py::test_apply_edit_rejects_frontmatter_in_body` (regression)
- [ ] `GovernanceRouter` passes the action through `write_guard` before creating the Panel intent; if write-guard is not open, the action is rejected with a clear error.
  - Verify: `tests/chat/test_governance_router.py::test_request_respects_write_guard`
- [ ] `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/chat/test_governance_router.py tests/chat/test_canvas_writer.py -m "not pg" -q` passes.

## How to Verify (Pre-Merge)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/chat/ -m "not pg" -q

# Confirm CANVAS-02 regression test still passes
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/chat/test_canvas_writer.py::test_apply_edit_rejects_frontmatter_in_body -m "not pg" -q
```

## Out of Scope

- Changes to the Panel admission pipeline itself.
- UI for the user to approve or reject the pending governance action (deferred to the editor layer).
- Cross-note synthesis or workspace mode (explicitly deferred per spec).
- Implementing new governance action types beyond what Panel already supports.

## Related Docs

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md` §The Authority Split :: Governance-bearing
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md`
- `docs/PANEL_AGENT.md` — the admission pipeline this task routes through
- `docs/CANVAS_CHAT_SURFACE/CO_AUTHOR_NOTE_BODY.md` — prerequisite

## Related GitHub Issues

When filed, the issue should reference "Implements CANVAS_CHAT_SURFACE/GATE_GOVERNANCE_BEARING_MUTATIONS" and must not change the Panel admission pipeline's existing behavior.
