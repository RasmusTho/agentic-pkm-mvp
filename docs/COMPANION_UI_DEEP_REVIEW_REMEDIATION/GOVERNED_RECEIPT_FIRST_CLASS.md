---
name: Governed Receipt First Class
description: Promote the post-apply receipt to a first-class in-place card state that confirms the vault change and links directly to its history entry, without scrolling the rail.
task_id: CUIDR-07
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 02 J6; 04 A2
parent_capability: Companion UI Deep-Review Remediation
prerequisites: [CUIDR-02, CUIDR-03]
depends_on: [OVERLAY_MODAL_FRAME_SPEC.md, RAIL_AMBIENT_UNTIL_ACTIVE.md]
can_parallelize_with: [Mist Ladder Subtractive, Blocked Recourse and Lane Labeling]
---

# Governed Receipt First Class

## Purpose

The receipt is the trust payload of the entire system — the one artifact that answers "did your
vault change, and is there a record?" After a governed Apply, that answer is buried in a dim
monospace log line at the bottom of the already-long rail. The user cannot tell at a glance that
anything happened. This task promotes the receipt to where the user's attention already is: the
card they just acted on.

## What This Task Does

On a governed Apply (surface S4 in the review), the originating proposal card transitions
in-place to an "Applied · receipt recorded" confirmed state. The confirmed state replaces the
proposal UI — the Apply / Discard / Defer buttons are gone; in their place is a compact confirmed
card showing the outcome and a control that opens the receipts history overlay focused on that
exact entry. No scrolling, no hunting for a log line.

The dim monospace log line ("executed · success moved via governed path · …") is retired as the
primary confirmation vehicle. It may remain as a developer detail behind a disclosure, but it is
no longer the only signal that the vault changed.

## Concretely (the post-apply card state + the link-to-history control)

After the runtime returns a confirmed receipt from POST /api/panel/confirm with
`status == "executed"`, the card that held the proposal renders the following confirmed state:

**Header line:** "Applied · receipt recorded"
- Rendered at the same visual weight as an active proposal card heading — not demoted, not
  dim, not monospace.

**Secondary line (from runtime payload):** outcome label + timestamp, verbatim from the receipt
object. Example: "success · 2026-06-10T11:00:00Z". These values are rendered from the runtime
confirmation payload; they are never synthesised by the client.

**Link-to-history control:** a single, named affordance — label "View receipt" or equivalent —
that, when activated, opens the receipts history overlay (O6) via the overlay host (CUIDR-02
frame, `receipts.open` intent) with the overlay pre-focused on the receipt whose id matches the
just-confirmed proposal. The control does not scroll the rail and does not navigate away from the
current note.

**Card position:** the confirmed card occupies the exact slot the proposal occupied in the rail's
active state (CUIDR-03). It does not shift position in the rail. Once confirmed, the card has no
further actionable affordances; it is read-only.

**Data attributes (for test assertions):**
- `data-testid="workspace-panel-receipt-card"` on the confirmed card root
- `data-receipt-state="applied"` on the card root
- `data-receipt-persistence="durable-runtime-projection"` (mirrors existing receipt rendering
  contract in `tests/companion_ui/test_panel_confirm_browser.py`)
- `data-testid="workspace-panel-receipt-link-to-history"` on the link-to-history control
- `data-receipt-id="<id>"` on the control, carrying the receipt id from the runtime payload

## Why This Matters

The review's J6 Axis B verdict is "Broken" specifically because the receipt — the thing this
system exists to produce — is the least visible thing on screen after the action that creates it.
The trust model only holds if the confirmation is unambiguous. An "Applied · receipt recorded"
card in the slot where the proposal was is the minimum legible signal: it is spatially anchored to
the action, temporally immediate, and directly linked to the durable record.

This change requires no reclassification. The receipt id, timestamp, outcome, and target path are
already in the runtime confirmation payload (`app/panel/confirmation.py`; exercised by
`test_panel_confirm_browser.py::test_receipt_rendered_after_executed`). This task only changes
where and how prominently those values are displayed.

## Acceptance Criteria

**AC1 — A2 (live):** Immediately after a governed Apply, the originating card shows an "Applied ·
receipt recorded" state in place of the proposal, with a control that opens that exact entry in
receipts history — without scrolling the rail.

Verify: `tests/companion_ui/test_governed_receipt_first_class.py::test_applied_card_replaces_proposal_live` — live UAT round-trip; capture the post-apply state against the running shell, assert the proposal affordances are absent and the confirmed card is present in the same rail slot.

**AC2 — In-place-state:** The applied card's confirmation replaces the proposal in the rail's
active state (CUIDR-03), and the link-to-history control opens the receipts history overlay
rendered through the modal-frame spec (CUIDR-02) focused on that entry.

Verify: `tests/companion_ui/test_governed_receipt_first_class.py::test_applied_card_in_place_state` — static; render the post-confirm fixture (workspace payload with `status == "executed"` and a receipt object), assert `data-testid="workspace-panel-receipt-card"` is present and `data-affordance-status` for Apply/Discard/Defer is absent; assert `data-testid="workspace-panel-receipt-link-to-history"` fires `receipts.open` via the overlay host.

**AC3 — Runtime-only confirmation:** The "Applied · receipt recorded" card state is rendered only
when the runtime confirmation payload carries `status == "executed"` and a non-null receipt
object. A pending, staged, blocked, or rejected proposal must not render the confirmed state.

Verify: `tests/companion_ui/test_governed_receipt_first_class.py::test_confirmed_state_requires_runtime_receipt` — static; assert that payloads with `status == "blocked"`, `status == "staged"`, and a null receipt do not render `data-receipt-state="applied"`.

**AC4 — No optimistic confirmation:** The client never renders the confirmed card state before the
runtime POST /api/panel/confirm response arrives. There is no optimistic "applying…" → "applied"
transition driven by client-side state; the state is set only from the confirmed response.

Verify: `tests/companion_ui/test_governed_receipt_first_class.py::test_no_optimistic_confirmation` — static; intercept the POST before it returns; assert the card still shows proposal affordances (Apply/Discard/Defer) and does not show `data-receipt-state="applied"`.

**AC5 — Degraded path:** If the receipts history overlay (O6) is unreachable when the link
control is activated, the confirmed card remains visible and a degraded inline notice replaces the
overlay content — "receipt recorded — history unavailable" — without removing or overwriting the
confirmed card in the rail.

Verify: `tests/companion_ui/test_governed_receipt_first_class.py::test_confirmed_card_degraded_history` — static; simulate a WorkspaceClientError on the receipts fragment fetch after apply; assert the confirmed card is still present and the overlay content shows the degraded copy.

## How to Verify (Pre-Merge)

1. Run the static test suite: `pytest tests/companion_ui/test_governed_receipt_first_class.py -v`
   and confirm AC2–AC5 pass.
2. Run the existing confirmation regression: `pytest tests/companion_ui/test_panel_confirm_browser.py -v`
   and confirm no regressions in `test_receipt_rendered_after_executed` or `test_blocked_reason_rendered`.
3. For AC1 (live): with the runtime running, apply a staged governed proposal and confirm that:
   - the originating card changes to "Applied · receipt recorded" in-place,
   - the Apply / Discard / Defer affordances are absent,
   - the "View receipt" control, when clicked, opens the receipts overlay focused on the correct entry
     without scrolling the rail.
4. Confirm that a body-edit (amber lane, S2) is unaffected — its card does not gain a receipt state
   and does not show the "View receipt" control after apply.

## Out of Scope

- The receipts history overlay content itself — that is owned by `test_receipts_history_surface.py`
  and the `receipts_history.py` module. This task adds only the focused-entry trigger; it must use
  the existing `receipts.open` intent via the overlay host.
- The body-edit lane (amber, S2) — it has no receipt by design. The "Applied · not recorded"
  labeling of that lane is owned by CUIDR-08 (Blocked Recourse and Lane Labeling).
- Blocked state recourse copy — owned by CUIDR-08.
- The dim monospace log line in developer/operator views — this task retires it as the primary
  user-facing confirmation; its visibility in an operator disclosure is a CUIDR-04 concern.
- Animated transition between proposal state and confirmed state — deferred; the task requires
  the state change, not the motion.

## Restart / Durability Posture

The receipt itself is durable: it is written by the governed write path (`app/panel/confirmation.py`
via `app/agents/panel/writeback.write_receipts`) and projected into the vault-browser
`notes[].receipts` aggregate. It survives server restart.

The in-place confirmed card is ephemeral session state: it is the rendered consequence of the
POST /api/panel/confirm response within the current page session. On reload, the rail returns to
its idle or active state as declared by the workspace aggregate; the confirmed-card ephemeral state
is not persisted and need not be.

If the receipts history store is unreachable at the moment the user activates the link control
(e.g. the overlay fragment fetch fails), the confirmed card remains visible in the rail, and the
overlay content area shows the calm degraded grammar from CUIDR-01:
"receipt recorded — history unavailable. Nothing was lost."
The confirmed card is not removed, overwritten, or replaced with an error state. The vault write
already happened; the degradation is only in the history view.

## Related Docs

- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt` — J6 verdict (S4 receipt buried; A2 recommendation)
- `companion-ui/companion-app/companion_ui/workspace/confirm_session.py` — ConfirmOutcome model; `is_executed` property; receipt field
- `companion-ui/companion-app/companion_ui/workspace/receipts_history.py` — receipts overlay; `RECEIPTS_OVERLAY_ID`; `receipts.open` intent
- `app/panel/confirmation.py` — server-side confirmation, receipt writing, WriteGuard
- `tests/companion_ui/test_panel_confirm_browser.py` — existing confirmation regression; `test_receipt_rendered_after_executed`
- `tests/companion_ui/test_receipts_history_surface.py` — receipts overlay surface contract
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/OVERLAY_MODAL_FRAME_SPEC.md` (CUIDR-02) — modal frame this task mounts through
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/RAIL_AMBIENT_UNTIL_ACTIVE.md` (CUIDR-03) — rail active state this task renders into

## Related GitHub Issues

Maps to child issue [Companion UI Deep-Review] governed-receipt-first-class; Wave 2; agent:blocked
until CUIDR-02 (OVERLAY_MODAL_FRAME_SPEC) and CUIDR-03 (RAIL_AMBIENT_UNTIL_ACTIVE) merge.
