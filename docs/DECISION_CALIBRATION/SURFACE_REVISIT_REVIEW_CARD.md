---
name: Surface Revisit Review Card
description: Companion UI card asking "you decided X on <date> — did it hold?" with the outcome vocabulary as pure visual picks, zero typing required; answering writes through the governed path, dismissing defers
task_id: CAL-03
source_anchor: app/api/routes/companion.py :: WorkspaceStateResponse
parent_capability: Decision Calibration
prerequisites: [CAL-01, CAL-02]
depends_on: [DEFINE_OUTCOME_RECEIPT_MODEL.md, SCHEDULE_DECISION_REVISITS.md]
can_parallelize_with: []
---

State: Depends on CAL-01 (governed write path) and CAL-02 (which decision is due). Last task in the
capability's execution order. Code-affecting (companion route + companion UI).

# Surface Revisit Review Card

## Purpose

Everything upstream — the outcome-receipt model, the scheduler — exists to make this card trustworthy.
This task is where the capability becomes real for the owner: a companion UI card that asks "you
decided X on \<date\> — did it hold?" with the outcome vocabulary as pure visual picks (per the owner's
dyslexia-friendly, no-manual-paths posture: selection is a visual pick, zero typing required for the
core answer; the note stays genuinely optional).

## What This Task Does

- Extends the companion workspace-state response with a `calibration_revisit` field (read projection
  of CAL-02's `due_revisits()`), following the same additive, degrade-honestly pattern
  `docs/COMMITMENT_SURFACING/EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE.md` established: when the read
  degrades (scheduler unavailable, decision note unreadable), the field reports a degraded state, never
  a confident "nothing pending" when the scheduler cannot actually tell.
- Adds two companion routes, mirroring the memory-review-queue pair
  (`/memory/review-queue`, `/memory/review-queue/{candidate_id}/decision`):
  - `POST /companion/calibration/revisits/{decision_id}/decision` — body `{outcome, note?}`; calls
    CAL-01's `append_outcome_receipt` through the governed write path (WriteGuard asserted at this call
    site, not just in the service function).
  - `POST /companion/calibration/revisits/{decision_id}/dismiss` — calls CAL-02's dismissal-ledger
    append.
- Renders the card in the Panel/Companion UI: the decision's short title (from `decision-record.md`'s
  `# {{Decision: ...}}` heading), `decided_on` date, and the four outcome values as tappable/clickable
  visual picks — no free-text field required to submit; an optional note field is present but never
  blocks submission when left empty.
- On answer: the card clears and the workspace re-reads the (now empty-for-this-rung) pending revisit
  state. On dismiss: the card clears the same way, with no outcome recorded (CAL-02 owns that
  distinction; this task must not conflate the two client-side).
- Degrades honestly: if the workspace-state field reports a degraded read, the UI shows a
  degraded/unavailable state rather than silently rendering "no revisits pending."

## Concretely

Workspace state includes:

```json
{"calibration_revisit": {"decision_id": "8f2e...", "title": "Postgres as projection, not source of truth",
                          "decided_on": "2026-06-23", "rung_days": 14, "degraded": false}}
```

The Panel/Companion UI shows: "You decided **Postgres as projection, not source of truth** on
2026-06-23 — did it hold?" with four buttons (Held / Partly held / Did not hold / Not sure yet) and an
optional note field. Clicking a button submits immediately; the note is never required.

## Why This Matters

If the card required typing to answer, it would violate the exact accessibility posture the whole
companion surface exists to serve (dyslexia-friendly, visual picks over typing) and the owner would
simply stop answering — silently defeating the capability's entire value. If answering and dismissing
were not clearly distinguished in the UI and the write path, the calibration profile (CAL-04) would
conflate "the owner said it held" with "the owner never looked at it," corrupting the exact signal the
capability exists to produce.

## Acceptance Criteria

- [ ] The workspace-state API exposes the pending revisit (if any) as a read-only field, additive and
      backward-compatible with older clients that ignore it.
  - Verify: `tests/api/test_companion_calibration_revisit.py::test_workspace_state_exposes_pending_revisit`
- [ ] When the read degrades, the API reports a degraded state rather than a confident empty surface.
  - Verify: `tests/api/test_companion_calibration_revisit.py::test_degraded_read_reports_degraded_not_empty`
- [ ] Answering a revisit calls the governed write path; WriteGuard is asserted at this route's call
      site (enforcement — not only unit-tested on the guard function in isolation).
  - Verify: `tests/api/test_companion_calibration_revisit.py::test_answer_revisit_writes_outcome_receipt_via_writeguard`
- [ ] Dismissing a revisit calls CAL-02's dismissal path and writes no outcome receipt.
  - Verify: `tests/api/test_companion_calibration_revisit.py::test_dismiss_defers_without_outcome_receipt`
- [ ] The Panel/Companion UI renders the four outcome values as visual picks; submitting an answer
      requires no typing (the note field is optional and never blocks submission).
  - Verify: `tests/companion_ui/test_calibration_revisit_card.py::test_answer_submits_without_typing`
- [ ] The rendered card visually distinguishes "answer" actions from the "dismiss" action, so the owner
      cannot mistake one for the other.
  - Verify: `tests/companion_ui/test_calibration_revisit_card.py::test_answer_and_dismiss_are_visually_distinct`
- [ ] When the API reports a degraded or absent revisit, the UI shows a degraded/unavailable state
      rather than crashing or implying zero decisions are pending.
  - Verify: `tests/companion_ui/test_calibration_revisit_card.py::test_degraded_or_absent_revisit_renders_safely`

## How to Verify (Pre-Merge)

- `pytest -q tests/api/test_companion_calibration_revisit.py tests/companion_ui/test_calibration_revisit_card.py`
- `pytest -q tests/api tests/companion_ui -k calibration` — broader sweep, matching the commitment
  -surfacing precedent's validation breadth.
- `ruff check app tests` and `mypy app` (code-affecting change).
- Render to static HTML via `render_index_html` and visually confirm the visual-pick affordance and the
  answer/dismiss distinction (companion UI local UAT pattern), since the companion UI render path is
  pure and does not require a live runtime.

## Restart / Durability Posture

The pending-revisit computation (CAL-02) and any dismissal are vault-canonical and durable — they
survive a process restart exactly as CAL-01's outcome receipts do. What does **not** survive a restart:
an in-progress, unsubmitted optional note the owner was typing into the card before restart — that text
is client-side/in-memory only and is lost, reappearing as an empty note field, never as a fabricated
answer. The user experience on restart: the same card, if still pending, reappears with its outcome
buttons intact and its due date unchanged; a dismissed or answered card does not reappear (the ledger/
receipt already recorded the action before the restart). If the answer or dismiss request was in flight
at the moment of restart and never reached the server, the card correctly reappears as still pending —
this is the honest outcome (the action never durably happened), not a bug.

## Out of Scope

- Episode-closure-triggered revisit cards (future, dependent on the Episode Resolution Engine).
- Briefing delivery / any notification, digest, or push surface (`docs/DAILY_BRIEFING/`, future seam).
- The outcome-receipt persistence and idempotency mechanics (CAL-01) and the scheduler/ladder/dismissal
  -ledger mechanics (CAL-02) — this task only calls them.
- The calibration-profile aggregation and rebuild (CAL-04).
- Any affordance to edit or re-answer a rung once its outcome receipt exists (immutability, per
  INV-CAL-A) — a corrected answer, if ever needed, is a new capability decision, not a silent edit here.

## Related Docs

- `docs/DECISION_CALIBRATION/README.md` — capability grounding and cross-task invariants
- `docs/DECISION_CALIBRATION/SCHEDULE_DECISION_REVISITS.md` — the scheduler this task's routes call
- `docs/COMMITMENT_SURFACING/RENDER_COMMITMENTS_IN_PANEL_UI.md`,
  `docs/COMMITMENT_SURFACING/EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE.md` — the read-only card-surface
  exemplar this task's route/render pattern follows (this task differs by adding one governed write)
- `app/api/routes/companion.py` — `_memory_review_decision_store`/`post_memory_review_decision` as the
  closest existing "answer a card through a governed write" precedent
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`; `reference_companion_ui_local_uat` (render-to-static UAT)

## Related GitHub Issues

One issue: `[Decision Calibration] surface-revisit-review-card: companion UI card, visual-pick outcomes,
governed-write answer`. Blocked on CAL-01 and CAL-02 merging — the final slice; its delivery readies the
capability for end-to-end validation on the parent feature issue.
