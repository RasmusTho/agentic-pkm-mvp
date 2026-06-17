---
name: Return Governance Handoff Reference
description: When a canvas co-authoring intent is governance-bearing, return the staged Panel intent reference (intent_id + action_type + origin) to the caller instead of an opaque 409, so the UI can correlate the canvas intent with the Panel proposal
task_id: CHAT-PANEL-HANDOFF-01
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md :: Allowed Crossings
parent_capability: Chat to Panel Governance Handoff
prerequisites: []
depends_on:
  - GENERATE_COAUTHORING_EDIT.md
  - GATE_GOVERNANCE_BEARING_MUTATIONS.md
can_parallelize_with: []
---

State: Implementation task specification. Today `_route_governance_bearing` in `app/api/routes/canvas.py` stages a Panel intent via `GovernanceRouter` but discards the returned `intent_id` and raises an opaque HTTP 409 string. The UI therefore cannot correlate the canvas intent with the Panel proposal that was created. This task surfaces that reference.
Doc role: Implementation task spec
Authority: Implements the "Chat session → governed execution boundary → Panel command locality" crossing from `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`. Does not change the gated-execution invariant.
Owner: v6.0 architecture owner
Last reviewed: 2026-06-09

# Return Governance Handoff Reference

## Purpose

The Chat→Panel handoff is dead-ended in the API. `GovernanceRouter.request_governance_action` returns a `PendingAction(intent_id, ...)`, but the `/coauthor` governance-bearing branch throws that away and raises a bare 409. Answer the schema's explicit question — "How does a Chat-originated governance-bearing intent enter the existing execution boundary, and where is its reference?" — by returning a structured handoff reference.

## What This Task Does

- Change `_route_governance_bearing` (and the `POST /api/canvas/sessions/{id}/governance` path) to capture the `PendingAction` and return a structured **governance handoff reference**: `intent_id`, `action_type`, and a `status` of `routed_to_panel`. The note remains unmutated.
- For the `/coauthor` governance-bearing case, replace the opaque 409 string with a 409 (or 200 handoff) response whose JSON body carries the handoff reference, so the UI can correlate and link to the Panel proposal. Keep a stable, typed response model (e.g. `GovernanceHandoffRef`).
- Mark the staged Panel proposal with a **proposal-scoped** origin of `canvas_coauthoring` so it is attributable to its canvas source when surfaced. **Do not reuse the artifact/frontmatter `origin` field** exposed by the companion workspace aggregate (that field is vault-note metadata in `_ARTIFACT_OPTIONAL_FIELDS`, not proposal metadata, and `StagedProposal` / `_proposal_rows_from_panel` carry no origin today). Add a dedicated proposal-origin field on `StagedProposal` (and surface it on the proposal row), or map it onto an existing proposal-event field such as `PanelIntentEvent.payload`'s handoff metadata — but keep it distinct from note origin so Panel attribution never overwrites artifact origin.
- Record the same `intent_id` in the `.chats/` session log (already done by `GovernanceRouter`); this task makes the reference visible to the caller, not just the log.

This stays within `HYBRID_CHAT_INTEGRATION_SCHEMA.md` Allowed Crossings: it exchanges a reference between the canvas session and the governed-execution boundary; it does not let Chat mutate governance state directly.

## Concretely

```
POST /api/canvas/sessions/{id}/coauthor
{ "intent": "promote this note to evergreen" }   # governance-bearing

-> 409  (or 200 handoff)
{
  "status": "routed_to_panel",
  "intent_id": "intent-abc123",
  "action_type": "maturity_transition",
  "detail": "Governance-bearing — routed to the gated pipeline; body unchanged."
}
# A Panel proposal now exists with a proposal-scoped origin="canvas_coauthoring",
# intent_id=intent-abc123 (distinct from any vault-note/frontmatter origin)
```

## Why This Matters

Without a returned reference the UI can only show a generic "routed to Panel" flag with no link to the actual proposal — the user cannot find or act on what their intent produced. The reference is the thread that makes the whole handoff loop navigable.

## Acceptance Criteria

- [ ] A governance-bearing co-authoring intent returns a structured handoff reference containing `intent_id`, `action_type`, and `status="routed_to_panel"`.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_governance_bearing_returns_handoff_reference`
- [ ] The staged Panel proposal carries a proposal-scoped origin of `canvas_coauthoring` (a dedicated proposal field, not the vault-note/frontmatter `origin`).
  Verify: `tests/api/test_canvas_governance_handoff.py::test_staged_proposal_marked_canvas_origin`
- [ ] The note body is left unchanged on the governance-bearing path.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_coauthor_governance_bearing_is_routed_not_applied`
- [ ] The `intent_id` returned to the caller matches the `intent_id` recorded in the session log.
  Verify: `tests/api/test_canvas_governance_handoff.py::test_handoff_reference_matches_session_log_intent`
- [ ] The path is gated behind `CANVAS_ENABLED`; Core Runtime defaults unchanged.
  Verify: `tests/api/test_canvas_governance_handoff.py::test_governance_handoff_requires_canvas_enabled`

## How to Verify (Pre-Merge)

- `pytest -q tests/api/test_canvas_coauthor_api.py tests/api/test_canvas_governance_handoff.py`
- `ruff check app tests`
- `git diff --check`

## Out of Scope

- Any Companion UI surface (that is `SURFACE_CHAT_TO_PANEL_HANDOFF.md`).
- Receipt reflection back into the canvas context (that is `REFLECT_HANDOFF_RECEIPT.md`).
- Changing the Panel admission/confirm/execute pipeline itself.
- New governance action types beyond those already in `GovernanceActionType`.

## Related Docs

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` :: Allowed Crossings, Minimum Future Runtime Questions
- `docs/CANVAS_CHAT_SURFACE/GENERATE_COAUTHORING_EDIT.md`
- `app/chat/governance_router.py`, `app/api/routes/canvas.py`, `app/api/routes/companion.py` (proposal `origin`)

## Related GitHub Issues

The issue should reference "Implements CANVAS_CHAT_SURFACE/RETURN_GOVERNANCE_HANDOFF_REFERENCE" and must preserve the gated-execution invariant (note never mutated on this path).
