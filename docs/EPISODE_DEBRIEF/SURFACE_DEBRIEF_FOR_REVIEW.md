---
name: Surface Debrief for Review
description: Companion UI review of a fresh debrief with visual accept/dismiss producing a receipt; dismissal archives disposition, never deletes the artifact
task_id: DEBRIEF-03
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 4. Episode debrief
parent_capability: Episode Debrief
prerequisites: [DEBRIEF-02]
depends_on: [SYNTHESIZE_DEBRIEF_NOTE.md]
can_parallelize_with: []
---

# Surface Debrief for Review

## Purpose

A synthesized debrief nobody ever sees is no better than no debrief. This task gives the owner a
low-friction way to see a fresh debrief and dispose of it — while leaving the artifact itself intact
either way, since a debrief has residual value even when the owner's answer today is "not now."

## What This Task Does

1. **Companion UI surface** listing fresh debriefs (`review_state: draft`, the canonical
   `STATE_AXES_CONTRACT.md` no-stronger-posture-claimed value), read-only, backed by the durable debrief-
   note source — not any in-memory/session state (the `COMMITMENT_SURFACING` precedent: the route is a
   read-only projection of durable truth, never an inventor of state).
2. **Visual accept/dismiss** — an acceleration of the same governed checkbox-in-note semantics the
   Panel/Create acceptance path already establishes (`docs/PANEL_AGENT.md` :: "Companion UI read-mode
   clicks are an acceleration of this checkbox semantics"). A click is a transport of human intent, not a
   separate authority store; the underlying write still goes through the guarded seam.
3. **Accept** flips `review_state: reviewed` on the debrief note — the canonical value meaning "reviewed
   to a level that should affect automation behavior... more constrained, more attributable"
   (`STATE_AXES_CONTRACT.md`). **Dismiss** flips `review_state: archived` — the canonical value meaning
   "no longer part of the active mutable working set... mutation normally disallowed" — which is exactly
   "not fresh anymore, kept, not casually touched again," without inventing a new value outside the
   contract's closed vocabulary. **Neither action deletes the debrief note, its content, or its
   `debrief_ref` link from the Episode note.**
4. This is a deliberate divergence from EXP-4's `decline_draft` (which archives/removes a *pre-acceptance
   staging draft* — appropriate there because an unaccepted Create draft has no independent durable value
   yet). A debrief is already a durable candidate artifact by the time it reaches review (DEBRIEF-02
   wrote it, no expiry sweep applies), so its disposition is a status flip on the canonical axis, never a
   lifecycle removal.
5. **`authority_state` is untouched by either action** — it stays `proposal` regardless of disposition.
   `review_state` and `authority_state` are distinct axes (`STATE_AXES_CONTRACT.md`'s core rule); accept
   is a review disposition, not an evidence-role promotion. This mirrors `EXPANSION_CONNECT_AND_CREATE.md`
   §2.3/§7 (E4)'s conservative default: reviewed-and-kept is still `derived_by: synthesis`, not
   machine-citable-as-settled.
6. **Receipts**: each action emits `episode_debrief.reviewed` / `episode_debrief.dismissed` (payload:
   `debrief_id`, `episode_id`, prior/new `review_state`). This is the seam a future Daily Briefing
   capability (`docs/DAILY_BRIEFING/`, not yet specified) could later consume — e.g. to skip already-
   reviewed debriefs or fold reviewed ones into a digest. This task does not build that consumption path;
   it only leaves the receipt legible enough to be a future input.
7. **No acceptance-by-silence.** Unlike ERE-07's episode proposals, an undisposed debrief has no quiet
   window and no timeout-to-`reviewed`: it stays `review_state: draft` indefinitely absent an explicit
   human action. A debrief is retro material, not a segmentation proposal — silence here means "not yet
   looked at," never "accepted."

## Concretely

```
GET /api/companion/episode-debriefs
→ {"fresh": [{"debrief_id": "...", "episode_id": "ep-2026-07-07-morning", "review_state": "draft", ...}]}

POST /api/companion/episode-debriefs/{debrief_id}/review {"disposition": "dismissed"}
→ {"review_state": "archived", "receipt": "episode_debrief.dismissed:..."}
# the note's file location and content are unchanged; only review_state + a receipt exist
```

## Why This Matters

If dismiss deleted the artifact, the owner loses the one thing this whole capability exists to produce,
the moment they decide "not now" instead of "never" — collapsing a two-state decision (interested later
vs. actively unwanted) into data loss. If accept silently advanced `authority_state`, the moat
(candidate-class synthesis, human disposes) would be breached exactly where
`EXPANSION_CONNECT_AND_CREATE.md` already drew the line.

## Acceptance Criteria

- [ ] AC1: a fresh (`review_state: draft`) debrief appears in the companion review surface, read-only,
  backed by the durable debrief-note source. Verify: `tests/episode_debrief/test_review.py::test_fresh_debrief_surfaced_from_durable_source`
- [ ] AC2: accept flips `review_state: reviewed` and emits a receipt; the note's content and its
  `debrief_ref` link from the Episode note are otherwise unchanged. Verify: `tests/episode_debrief/test_review.py::test_accept_flips_review_state_and_emits_receipt`
- [ ] AC3 (enforcement): dismiss flips `review_state: archived` and emits a receipt — the artifact file
  is NOT deleted and remains discoverable/linked, asserted at the production dismiss call site. Verify:
  `tests/episode_debrief/test_review.py::test_dismiss_does_not_delete_artifact`
- [ ] AC4: neither accept nor dismiss changes `authority_state` beyond `proposal` or asserts an evidence
  role. Verify: `tests/episode_debrief/test_review.py::test_review_actions_never_advance_authority_state`
- [ ] AC5: an undisposed debrief has no timeout-to-`reviewed` — it stays `review_state: draft`
  indefinitely absent a human action (no acceptance-by-silence). Verify: `tests/episode_debrief/test_review.py::test_no_acceptance_by_silence_for_debriefs`
- [ ] AC6: re-reviewing an already-disposed debrief (idempotent re-click, same disposition) does not
  emit a duplicate receipt or flip state twice. Verify: `tests/episode_debrief/test_review.py::test_review_disposition_idempotent`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episode_debrief/test_review.py
pytest -q -m "not pg"
```

## Out of Scope

Any bespoke re-cut UI; any automatic acceptance; cross-episode/rollup views; the Daily Briefing
consumption path itself (named as a future seam only, not specified or built here); deleting a
dismissed (`archived`) debrief (no deletion path exists anywhere in this task).

## Restart / Durability Posture

`review_state` is a vault-durable frontmatter field on the debrief note — it survives restart like any
note field. The companion UI holds no client-side-only disposition state: a page reload re-reads the
durable field, so a dismissed-but-not-yet-refreshed UI never re-shows a debrief as fresh after restart.
A lost receipt (at-least-once outbox) does not lose the disposition itself — the frontmatter flip is the
commit point, mirroring the Decision Receipt Log's receipt-before-ack posture applied to review state
instead of a governance verdict.

## Related Docs

- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2.4/§7 (E4 — conservative
  accepted-review-state default)
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md` (`review_state` canonical values — conformed to, not forked)
- `docs/PANEL_AGENT.md` (checkbox/receipt semantics; companion UI click acceleration)
- `docs/COMMITMENT_SURFACING/README.md` (read-only companion-route precedent)
- `docs/DECISION_RECEIPT_LOG/README.md` (receipt-before-ack precedent)
- `docs/DAILY_BRIEFING/` (future seam, not yet specified)
- `app/api/routes/companion.py`, `app/expansion/accept.py` (decline pattern this task deliberately diverges from)

## Related GitHub Issues

One issue: `[Episode Debrief] surface-debrief-for-review: companion UI accept/dismiss with a
never-deletes receipt`. Blocked until DEBRIEF-02 merges (and transitively ERE-02/04/06).
