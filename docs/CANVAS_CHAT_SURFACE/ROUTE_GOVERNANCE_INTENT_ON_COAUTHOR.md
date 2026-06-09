---
name: Route Governance Intent on Coauthor
description: Wire the intent classifier into POST /coauthor so a governance-bearing intent routes to the gated Panel pipeline (with the correct GovernanceActionType) before and independent of body generation, keeping the body-frontmatter check as defense-in-depth
task_id: CANVAS-INTENT-02
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md :: Allowed Crossings
parent_capability: Intent-level governance classification on the /coauthor path
prerequisites: [CANVAS-INTENT-01]
depends_on:
  - CLASSIFY_COAUTHORING_INTENT.md
  - RETURN_GOVERNANCE_HANDOFF_REFERENCE.md
can_parallelize_with: []
---

State: Implementation task specification. Builds on `CLASSIFY_COAUTHORING_INTENT.md` (the classifier cognition) by wiring it into `POST /api/canvas/sessions/{id}/coauthor`. Today the route classifies governance-bearing only post-hoc, from the generated body's frontmatter; this task classifies the *intent* up front and routes governance-bearing intents to `GovernanceRouter` with the classified `GovernanceActionType`, never generating or applying a body on that path. Closes the "known limitation" recorded in `docs/runbooks/UAT_CANVAS_COAUTHORING.md` §4.
Doc role: Implementation task spec
Authority: Implements the "Chat session → governed execution boundary" crossing from `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` :: Allowed Crossings. Preserves `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` (note never mutated on the governance path) and the Panel-as-primary-command-surface posture.
Owner: v6.0 architecture owner
Last reviewed: 2026-06-09

# Route Governance Intent on Coauthor

## Purpose

Close the gap the classifier was built for. `POST /coauthor` must decide intent class from the *intent*, not the generated body: a governance-bearing intent routes to the gated Panel pipeline (returning the existing `GovernanceHandoffRef`) with the **correct** `GovernanceActionType`, before any body is generated; a co-authoring intent takes the existing generate-and-apply path; an **exploratory** intent is read-only and never mutates the note. The note is never mutated on the governance or exploratory path.

## What This Task Does

- In `app/api/routes/canvas.py`, run `IntentClassifierCognition.classify(intent=req.intent, current_body=...)` at the top of `coauthor()` (after the session lookup), using a module-level `_intent_classifier_facade_factory()` indirection mirroring `_coauthor_facade_factory()` so tests inject a stub.
- If `intent_class == GOVERNANCE_BEARING`: route immediately via `_route_governance_bearing(session, vault_root, action_type=classification.action_type)` and return the `GovernanceHandoffRef` (HTTP 409). **Do not call `generate_body`**; the body is never generated or applied.
- If `intent_class == CO_AUTHORING`, **or** `classified is False` (degraded backend): fall through to the existing `generate_body` → `CanvasWriter.apply_edit` path unchanged. The degraded default is `CO_AUTHORING`, so an unavailable classifier preserves today's behavior.
- If `intent_class == EXPLORATORY`: **do not** call `generate_body` or `apply_edit` — exploratory intent is non-mutating per `HYBRID_CHAT_INTEGRATION_SCHEMA.md` :: Intent Classes ("does not itself authorize durable mutation"). Return a read-only, non-mutating response (note unchanged) — e.g. HTTP 200 with a `status: "exploratory_no_edit"` marker. Surfacing an actual read-only *answer* (via the read-only cognition) is optional and out of scope for this slice; the **binding requirement is no mutation**. Only a confident `EXPLORATORY` classification takes this path — a degraded backend never lands here (it defaults to `CO_AUTHORING`).
- Change `_route_governance_bearing` to accept `action_type: GovernanceActionType` and use it instead of the hardcoded `GovernanceActionType.FRONTMATTER_UPDATE`. The existing **body-frontmatter defense-in-depth** branches (the `except GovernanceBearingMutationError` handlers) call it with the default `FRONTMATTER_UPDATE`, preserving the backstop when a generation slips frontmatter through.
- Keep the path gated behind `CANVAS_ENABLED`; do not change Core Runtime defaults (this stays Agentic Lab).
- **Owner-doc closure, bundled in this PR** (no separate docs follow-up):
  - Replace the "Known limitation (capability, not runbook)" note in `docs/runbooks/UAT_CANVAS_COAUTHORING.md` §4 with a deterministic natural-language walkthrough: a governance intent through `/coauthor` now routes to Panel with the classified `action_type`. Update the "Trigger note" so the natural intent is a reliable trigger (the explicit `/governance` endpoint remains available).
  - Add a **Phase 4** entry to `docs/CANVAS_CHAT_SURFACE/README.md` recording the capability and marking the gap closed.

### Reconciling existing tests

The existing `tests/api/test_canvas_coauthor_api.py` stubs only the co-authoring facade. With classification now running first, those tests must also inject an intent-classifier stub via `_intent_classifier_facade_factory`. Concretely:

- The body-frontmatter **defense-in-depth** test (`test_coauthor_governance_bearing_is_routed_not_applied`, `test_governance_bearing_returns_handoff_reference`) should use an intent the classifier labels `CO_AUTHORING` (e.g. "rewrite the body") while the co-authoring stub still returns a frontmatter-bearing body — so the backstop fires and the handoff `action_type` is `frontmatter_update`.
- A new test asserts that a **natural governance intent** ("promote this note to evergreen") routes via the *intent* path with `action_type=maturity_transition`, even though the co-authoring stub would have returned a frontmatter-free body.

## Concretely

```
POST /api/canvas/sessions/{id}/coauthor
{ "intent": "promote this note to evergreen" }

# classifier -> GOVERNANCE_BEARING / MATURITY_TRANSITION (before any generation)
-> 409
{
  "status": "routed_to_panel",
  "intent_id": "intent-abc123",
  "action_type": "maturity_transition",
  "detail": "Governance-bearing — routed to the gated Panel pipeline; note body left unchanged."
}
# note body unchanged; no body was generated.

POST /api/canvas/sessions/{id}/coauthor
{ "intent": "expand the decision section with trade-offs" }
# classifier -> CO_AUTHORING -> existing generate+apply path -> 200, body edited in place.

POST /api/canvas/sessions/{id}/coauthor
{ "intent": "what does this note argue?" }
# classifier -> EXPLORATORY -> no generation, no write -> 200 {"status":"exploratory_no_edit", ...}
# note body unchanged.
```

## Why This Matters

Without intent-level routing the governance handoff is dead on arrival for natural language: the user asks to promote a note, the body gets edited (or no-op'd), and nothing reaches the gated pipeline — the exact invariant `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` exists to protect. Routing on the classified intent, with the right `action_type`, makes the Chat→Panel crossing reachable as designed while the note stays untouched until the gated path executes.

## Acceptance Criteria

- [ ] A natural governance intent ("promote this note to evergreen") routes to Panel via the intent path — note unchanged, no body generated — even when the co-authoring stub would return a frontmatter-free body.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_natural_governance_intent_routes_to_panel`
- [ ] The returned handoff reference carries the classified `action_type` (`maturity_transition`), not a hardcoded `frontmatter_update`.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_handoff_action_type_reflects_classified_intent`
- [ ] A pure body-edit (co-authoring) intent still generates and applies in place.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_coauthor_applies_generated_body`
- [ ] An exploratory intent ("what does this note argue?") does **not** generate or apply — the note body is unchanged and a non-mutating response is returned.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_exploratory_intent_does_not_mutate`
- [ ] The body-frontmatter defense-in-depth still routes a frontmatter-bearing generation (classifier labels it co-authoring; backstop fires with `frontmatter_update`).
  Verify: `tests/api/test_canvas_coauthor_api.py::test_coauthor_governance_bearing_is_routed_not_applied`
- [ ] When the classifier is degraded (`classified=False`), the route falls through to the existing generate path with no fabricated governance routing.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_classifier_degraded_falls_through`
- [ ] The path is gated behind `CANVAS_ENABLED`; Core Runtime defaults unchanged.
  Verify: `tests/api/test_canvas_coauthor_api.py::test_coauthor_requires_canvas_enabled`
- [ ] The UAT runbook §4 "Known limitation" note is replaced with a deterministic natural-language routing walkthrough.
  Verify: doc target `docs/runbooks/UAT_CANVAS_COAUTHORING.md` :: §4 (no intent-classification "Known limitation" paragraph; new walkthrough present)
- [ ] The capability README records Phase 4 as delivered with the gap closed.
  Verify: doc target `docs/CANVAS_CHAT_SURFACE/README.md` :: Phase 4

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_canvas_coauthor_api.py tests/api/test_canvas_governance_handoff.py tests/chat/test_intent_classifier.py`
- `ruff check app tests`
- `git diff --check`

## Out of Scope

- Building the classifier cognition itself (that is `CLASSIFY_COAUTHORING_INTENT.md`).
- New `GovernanceActionType` values or changes to the Panel admission/confirm/execute pipeline.
- Companion UI / served-page changes beyond what already invokes `/coauthor` (the affordance already renders the handoff reference).
- A deterministic keyword classifier fallback.

## Related Docs

- `docs/CANVAS_CHAT_SURFACE/CLASSIFY_COAUTHORING_INTENT.md`
- `docs/CANVAS_CHAT_SURFACE/RETURN_GOVERNANCE_HANDOFF_REFERENCE.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` :: Allowed Crossings, Intent Classes
- `docs/runbooks/UAT_CANVAS_COAUTHORING.md` :: §4
- `app/api/routes/canvas.py` (`coauthor`, `_route_governance_bearing`)

## Related GitHub Issues

The issue should reference "Implements CANVAS_CHAT_SURFACE/ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR", depend on the CANVAS-INTENT-01 classifier issue, and point back to the Phase 4 parent feature issue. It must preserve the gated-execution invariant (note never mutated on the governance path) and bundle the runbook + README owner-doc closure in the same PR.
