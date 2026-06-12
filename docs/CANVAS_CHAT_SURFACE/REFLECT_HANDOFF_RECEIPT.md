---
name: Reflect Handoff Receipt
description: After a canvas-originated Panel proposal is confirmed and executed, reflect the resulting receipt back into the canvas/originating context so the user can see the outcome of their Chat-originated governance-bearing intent without leaving the surface
task_id: CHAT-PANEL-HANDOFF-03
source_anchor: docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md :: Minimum Future Runtime Questions
parent_capability: Chat to Panel Governance Handoff
prerequisites: [CHAT-PANEL-HANDOFF-02]
depends_on:
  - SURFACE_CHAT_TO_PANEL_HANDOFF.md
can_parallelize_with: []
---

State: Implementation task specification. CHAT-PANEL-HANDOFF-02 makes the proposal navigable from the canvas region; this task closes the loop by reflecting the executed receipt back into the originating context.
Doc role: Implementation task spec
Authority: Answers the schema's explicit question "Where does the user inspect the receipt for a Chat-originated governance-bearing mutation?". Receipts are read-only and must not be invented by the UI.
Owner: v6.0 architecture owner
Last reviewed: 2026-06-09

# Reflect Handoff Receipt

## Purpose

The hybrid handoff is only complete when the user can see the outcome. `HYBRID_CHAT_INTEGRATION_SCHEMA.md` lists "Where does the user inspect the receipt for a Chat-originated governance-bearing mutation?" as a required runtime question. This task answers it: once the canvas-originated Panel proposal executes and a durable receipt exists, the canvas/originating context reflects that receipt posture.

## What This Task Does

- When a confirmed proposal carries `origin="canvas_coauthoring"` and a durable receipt becomes available, surface the receipt posture (outcome, intent_id, receipt id/visibility) in the canvas region's panel-routed state — read-only, server-declared.
- Correlate strictly by the server-provided `intent_id` from CHAT-PANEL-HANDOFF-01; the UI must not invent receipts or infer success. If no durable receipt exists, the region shows a pending/blocked posture as the server declares it (mirroring the existing operational-loop receipt-visibility semantics).
- Reuse the existing receipt-visibility projection (`receipt_visibility` / `panel.receipts`) already consumed by the Companion UI operational loop; this task scopes it to the canvas-originating context, not a new receipt store.

## Concretely

```
Canvas region after the Panel proposal executes:
  "Routed to Panel — maturity_transition  ✓ receipt: applied"   (intent-abc123)
                                          (read-only; server-declared)

If not yet executed:
  "Routed to Panel — maturity_transition  · awaiting decision"   (no receipt invented)
```

## Why This Matters

Without receipt reflection the user must leave the canvas context and hunt the Panel/receipts surface to learn whether their governance-bearing intent actually landed. Reflecting the receipt closes the "Panel command locality → receipt visible in the originating context" crossing and makes the hybrid loop feel coherent end to end — while keeping receipts strictly server-owned.

## Acceptance Criteria

- [ ] A durable receipt for a canvas-originated proposal is reflected in the canvas region keyed by `intent_id`.
  Verify: `tests/companion_ui/test_handoff_receipt_reflection.py::test_receipt_reflected_for_canvas_origin`
- [ ] When no durable receipt exists, the region shows a pending/blocked posture and invents no receipt.
  Verify: `tests/companion_ui/test_handoff_receipt_reflection.py::test_no_receipt_shows_pending_not_invented`
- [ ] The reflected receipt is read-only and server-declared (no local outcome inference).
  Verify: `tests/companion_ui/test_handoff_receipt_reflection.py::test_reflected_receipt_is_read_only_server_declared`
- [ ] Receipt correlation is strictly by the server-provided `intent_id`.
  Verify: `tests/companion_ui/test_handoff_receipt_reflection.py::test_receipt_correlation_by_intent_id`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_handoff_receipt_reflection.py`
- Regression: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui` (state any pre-existing unrelated failures explicitly).
- `ruff check app tests companion-ui`
- `git diff --check`

## Out of Scope

- Creating or storing receipts (receipts are produced by the Panel/governance pipeline).
- Backend handoff reference (CHAT-PANEL-HANDOFF-01) and proposal navigation (CHAT-PANEL-HANDOFF-02).
- Changing receipt-visibility semantics for non-canvas origins.
- Hosting/packaging decisions.

## Related Docs

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md` :: Minimum Future Runtime Questions
- `docs/CANVAS_CHAT_SURFACE/SURFACE_CHAT_TO_PANEL_HANDOFF.md`
- `companion-ui/docs/COMPANION_UI_STATE_MAP.md` (operational loop / receipt-visibility)
- `app/api/routes/companion.py` (receipt projection), `app/panel/confirmation.py`

## Related GitHub Issues

The issue should reference "Implements CANVAS_CHAT_SURFACE/REFLECT_HANDOFF_RECEIPT" and must preserve "receipts must not be invented by the UI".
