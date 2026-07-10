---
name: Surface Question List and Review
description: Companion UI surface — open-question list, per-question evidence trail, candidate-answer review with visual accept/dismiss; acceptance is the only path to lifecycle state answered, reusing the existing Panel checkbox-projection acceleration rather than a new authority store
task_id: SQ-05
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 3. Standing questions
parent_capability: Standing Questions
prerequisites: [SQ-01, SQ-02, SQ-03, SQ-04]
depends_on: [STORE_QUESTION_NOTES_AND_PROJECTION.md, REGISTER_QUESTIONS_FRICTION_FREE.md, MATCH_EVIDENCE_TO_OPEN_QUESTIONS.md, REFRESH_ANSWER_ON_EVIDENCE_DELTA.md]
can_parallelize_with: []
---

# Surface Question List and Review

## Purpose

Everything SQ-01..04 build is invisible without a surface. This task gives the owner one place to see
their open questions, read what evidence accumulated on each, and review a candidate answer with a
visual accept/dismiss — no typing, no path-picking, consistent with the dyslexia-friendly,
visual-pick-over-typing posture that governs every companion UI surface in this repo.

## What This Task Does

1. **Open-question list**: a companion UI view backed by the SQ-01 projection — every `open` question
   (including those with a pending candidate answer, which are still `open` until accepted), showing
   `text`, evidence count, and a "has a candidate answer" indicator. `answered`/`closed` questions are
   reachable but not the default view (they are resolved, not the owner's current cognitive load).
   Design precedent to reuse the interaction pattern from:
   `companion-ui/design_handoff/2026-05-14-memory-candidate-review/` (closest existing candidate-review
   shape in this repo — read its `state-gallery.md`/`edge-states.md` before designing a new pattern).
2. **Per-question evidence trail**: selecting a question shows its `evidence` log
   (`artifact_ref`, `source_stream`, `matched_at`, `quoted_span`, `confidence_class`) — read-only,
   sourced from the SQ-01 projection, each entry linking back to its originating artifact (read-only
   navigation, this surface never opens a write path into the evidence artifact itself, per SQ-03's
   own invariant).
3. **Candidate-answer review**: when `candidate_answer_ref` is set, the draft's rendered content
   (with its `contradicts_standing_answer` state visually distinguished — a contradiction gets an
   unmissable visual marker, not the same treatment as an ordinary refresh) is shown alongside **accept**
   and **dismiss** actions.
   - **Accept** is a companion-UI read-mode click that projects the same checked-checkbox semantics
     the draft's own in-draft `AI-åtgärder` acceptance checkbox carries (`docs/PANEL_AGENT.md`:
     "Companion UI read-mode clicks are an acceleration of this checkbox semantics... must not become
     an authority store separate from the vault-visible Panel state") — reusing the existing
     `POST /api/panel/checkbox-projection` runtime-mediated projection, not a new endpoint or a new
     authority model. Acceptance executes the governed materialization EXP-4 defines (draft →
     `standing_answer_ref`) **and**, in the same governed transaction, flips `status: answered` on the
     Question note — the single explicit human act that is the *only* path to that lifecycle state
     (INV-SQ-C).
   - **Dismiss** routes the draft into the existing declined-proposal ledger
     (`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: 3`) — the question stays
     `open`, `candidate_answer_ref` clears, evidence keeps accumulating, and a future threshold
     crossing may draft again (content-based reset: dismissing today's draft does not suppress a
     materially different future draft).
4. **Explicit close**: a human-terminal action lets the owner mark a question `closed` without ever
   answering it ("I don't need this anymore") — a direct note edit or an explicit companion-UI action,
   no gate beyond the human's own click, since closing is reversible (re-open = edit `status` back).
5. **No new authority surface**: every mutating action on this page (accept, dismiss, close) is a thin
   client that calls an existing or SQ-04-delivered governed endpoint; the companion UI itself never
   decides acceptance, never computes contradiction, never writes a Question note field directly.

## Concretely

```
GET /api/standing-questions              # open-question list from the projection
GET /api/standing-questions/sq-abc       # question detail: text, evidence trail, candidate_answer_ref
POST /api/panel/checkbox-projection      # accept: projects the draft's in-draft AI-åtgärder checkbox
POST /api/standing-questions/sq-abc/dismiss   # dismiss: declined-ledger entry, candidate cleared
POST /api/standing-questions/sq-abc/close     # explicit human-terminal close
```

## Why This Matters

If accept/dismiss invent a parallel confirmation model instead of projecting the vault-visible
checkbox, Standing Questions becomes the second place in the repo where "accepted" can mean something
different depending on which surface you used — exactly the authority-store-outside-the-vault failure
`docs/PANEL_AGENT.md` already rules out for every other Panel action. If the list defaults to showing
resolved questions alongside open ones, the surface adds cognitive load instead of removing it — the
opposite of this capability's purpose.

## Acceptance Criteria

- [ ] AC1: the open-question list shows every `open` question from the projection (including
      pending-candidate ones) and excludes `answered`/`closed` from the default view. Verify:
      `tests/standing_questions/test_question_list_api.py::test_list_shows_open_excludes_resolved_by_default`
- [ ] AC2: the evidence-trail view renders every entry in a fixture question's `evidence` log with its
      provenance, and each entry links to (never mutates) its source artifact. Verify:
      `tests/standing_questions/test_question_detail_api.py::test_evidence_trail_renders_provenance_read_only`
- [ ] AC3: a candidate answer with `contradicts_standing_answer: true` renders with a visually distinct
      marker from an ordinary (non-contradicting) refresh. Verify:
      `tests/companion_ui/test_standing_question_review.py::test_contradiction_marker_visually_distinct`
- [ ] AC4 (enforcement): the accept action calls the existing checkbox-projection endpoint (no new
      parallel authority path) and, on success, both materializes the answer and flips
      `status: answered` in the same governed transaction. Verify:
      `tests/standing_questions/test_question_review_actions.py::test_accept_projects_checkbox_and_flips_status_atomically`
- [ ] AC5: dismiss records a declined-ledger entry, clears `candidate_answer_ref`, and leaves `status`
      unchanged (`open`); a subsequent materially-different draft is not suppressed by the earlier
      dismissal. Verify:
      `tests/standing_questions/test_question_review_actions.py::test_dismiss_declines_without_closing_question`
- [ ] AC6: explicit close sets `status: closed` directly from a human action with no candidate-answer
      requirement; a closed question can be reopened by editing `status` back to `open`. Verify:
      `tests/standing_questions/test_question_review_actions.py::test_explicit_close_and_reopen`
- [ ] AC7 (enforcement): no companion-UI code path writes `status` or `standing_answer_ref` directly —
      every mutation on this surface calls an existing or SQ-04-delivered governed endpoint. Verify:
      `tests/standing_questions/test_question_review_actions.py::test_ui_never_writes_authority_fields_directly`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/standing_questions/test_question_list_api.py tests/standing_questions/test_question_detail_api.py tests/standing_questions/test_question_review_actions.py
pytest -q -m "not pg"
cd companion-ui/companion-app && <companion-ui test command per its own CONTRIBUTING/test docs>
```

## Out of Scope

Voice-native review (Mimer voice loop, a separate future capability); a briefing/push surface for
open questions or fresh candidates (future `docs/DAILY_BRIEFING/` seam, named not built); question
sharing/federation UI (capability-level out of scope); bulk accept/dismiss across multiple questions
at once (a later convenience, not required for the first surface).

## Restart / Durability Posture

Every durable fact this surface displays (question text, status, evidence log, candidate-answer
content, acceptance/dismissal outcome) is vault- or projection-backed and survives restart intact.
What does **not** survive a page reload or process restart: the companion UI's own client-side
review-session state — which question is currently selected, any in-progress typed dismiss note
before it is submitted, scroll position, and open/collapsed evidence-trail sections. If the human is
mid-typing a custom dismiss reason and the browser reloads, that unsent text is lost — the question,
its evidence trail, and its pending candidate answer are entirely unaffected and the review can simply
be resumed.

## Related Docs

- `docs/PANEL_AGENT.md` (checkbox-projection acceleration model this surface's accept action reuses
  verbatim — read before designing a separate confirm mechanism)
- `companion-ui/design_handoff/2026-05-14-memory-candidate-review/` (closest existing design precedent
  for a candidate-review list+detail+accept/dismiss shape)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: 2.4` (governed acceptance),
  `:: 3` (declined-proposal ledger, reused by dismiss)
- [REFRESH_ANSWER_ON_EVIDENCE_DELTA](REFRESH_ANSWER_ON_EVIDENCE_DELTA.md) (produces what this surface
  reviews)

## Related GitHub Issues

One issue: `[Standing Questions] surface-question-list-and-review: companion UI open-question list,
evidence trail, and candidate-answer accept/dismiss`. Blocked until SQ-01/02/03/04 merge (SQ-04's own
external EXP-3 dependency propagates here — this surface has nothing to review until a candidate
answer can exist). TCD hint: Sonnet / medium effort — UI implementation over existing projections and
an existing checkbox-projection endpoint (reuse, not new authority mechanics); escalate to high effort
only if the accept action's atomic materialize+status-flip wiring (AC4) surfaces edge cases the
existing endpoint does not already handle.
