---
name: Refresh Answer on Evidence Delta
description: When accumulated evidence crosses a threshold, the Create engine re-drafts a provenance-cited candidate answer; a contradicting refresh is explicitly surfaced rather than silently rewritten; a refresh never clobbers a candidate answer the human is mid-reviewing
task_id: SQ-04
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 3. Standing questions
parent_capability: Standing Questions
prerequisites: [SQ-01, SQ-03]
depends_on: [STORE_QUESTION_NOTES_AND_PROJECTION.md, MATCH_EVIDENCE_TO_OPEN_QUESTIONS.md]
can_parallelize_with: []
---

# Refresh Answer on Evidence Delta

## Purpose

Evidence accumulating with nobody ever re-answering the question is the same dead end as no evidence
at all. This task closes the loop: when the evidence trail crosses a threshold, a candidate answer is
(re-)drafted, provenance-cited and candidate-only — and if the new evidence disagrees with what the
owner currently believes (the standing answer), that disagreement is surfaced explicitly, never
smoothed over by a confident-sounding rewrite.

**Named external dependency (load-bearing, read before starting this task).** This task does not
reimplement synthesis. It reuses the Create engine's `create.answer_note` kind — draft assembly via
`CompilationDraft`, cognition via `run_reasoning`/`run_multi_note_reasoning`, citation validation,
staging write with an in-draft `AI-åtgärder` acceptance checkbox, expiry sweep — from
`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2 (EXP-3). **EXP-3 has not merged
as of this spec's writing** (that spec's own header states "advisory until child issues are
delivered"). This task's own contribution is the trigger (evidence-delta, not explicit-ask), the
contradiction-flagging extension to the draft, and the pending-review-not-clobbered discipline —
none of which can be implemented before EXP-3 exists. See Context in this task's GitHub issue draft
for how its ready/blocked label should actually read.

## What This Task Does

1. **Trigger**: after each SQ-03 matching tick, for every `open` question whose evidence accumulated
   since its `last_refreshed_at` crosses the RQ-SQ1 threshold (named, single-sourced, provisional
   constant — see README), a refresh is scheduled. Threshold crossing is evaluated on the current
   evidence log state, never on a separately stored counter (so a crash between evidence-attach and
   refresh-scheduling loses nothing — the next tick re-derives the delta from the log itself).
2. **Pending-review guard (INV-SQ-D, the seam this task exists to walk)**: before drafting, the
   refresh checks `candidate_answer_ref` — if a prior candidate-answer draft is still pending (not yet
   accepted, dismissed, or expired), the refresh **defers**: evidence keeps accruing in the log, no
   second draft is generated, and the deferral is not itself persisted as a decision — the next tick
   re-checks fresh. This is a read of current vault state, not a stored flag, precisely so a crash
   mid-check can never leave a stale "don't refresh" marker behind.
3. **Draft assembly (reusing EXP-3)**: context assembly through the retrieval capability seam at
   cited-proposal admissibility tier (scope prefilter + evidence-role clamp intact, same-scope only —
   consistent with SQ-03's discipline), sources = the question's evidence-log entries (their
   `provenance_ref`s resolved, never re-fetched); cognition run through the Create engine's existing
   `create.answer_note` path; citation validation (every cited source resolves, quoted spans verbatim)
   blocks the draft loudly on any unresolvable citation — never silently pruned.
4. **Contradiction flag (this task's schema extension to the Create draft frontmatter)**: the drafting
   call additionally asks the model, schema-constrained (`app/components/llm/constrained.py::
   constrained_completion`, same pattern as SQ-02/SQ-03), whether the new draft's conclusion
   contradicts the current `standing_answer_ref` content (when one exists): `{"contradicts_standing_answer":
   bool, "contradiction_basis": "..." | null}`. A validated `true` sets `contradiction: true` +
   `contradiction_basis` on the draft's frontmatter and the draft surfaces with a distinct visual
   marker (consumed by SQ-05); a schema-validation failure/degrade on *this specific judgment* does not
   block the draft from existing, but forces the conservative default `contradiction: unknown` —
   rendered to the human as "comparison inconclusive, please compare yourself" — never a silent `false`
   the system could not actually verify.
5. **No auto-supersession, ever.** The draft never overwrites `standing_answer_ref`; that pointer only
   changes at explicit human acceptance (owned by SQ-05's accept action, materializing through the
   existing governed-acceptance path EXP-4 defines).
6. **`last_refreshed_at` update**: only on successful draft materialization (staging write receipted)
   — a failed/blocked draft attempt does not advance `last_refreshed_at`, so the delta that triggered it
   is not silently lost from future evaluation.

## Concretely

```
$ python -m app.cli questions tick --json
{"refresh_candidates": ["sq-abc"], "deferred_pending_review": ["sq-def"], "drafted": 1}
$ python -m app.cli questions show sq-abc --json
{"candidate_answer_ref": "vault://_system/drafts/sq-abc-answer-2026-07-07.md", "last_refreshed_at": "..."}
# Draft frontmatter: derived_by: synthesis, authority_state: proposal, contradicts_standing_answer: true,
# contradiction_basis: "New evidence states X, standing answer asserted not-X (2026-06-01)."
```

## Why This Matters

If a refresh fires while the human is reading the previous draft, the review the human already started
vanishes mid-read — trust-destroying in exactly the way the Episode Resolution Engine's re-cut
invariant protects against on the segmentation side. If a contradicting refresh just quietly replaces
the standing answer's *content* in the next draft with no flag, the owner loses the exact moment
their own understanding was wrong and would most want to know it — the entire point of carrying a
standing question rather than re-asking ASK cold every time.

## Acceptance Criteria

- [ ] AC1: a fixture question whose evidence log crosses the RQ-SQ1 threshold triggers exactly one
      candidate-answer draft, citation-valid and provenance-cited to its evidence-log entries. Verify:
      `tests/standing_questions/test_answer_refresh.py::test_delta_threshold_triggers_one_draft`
- [ ] AC2 (enforcement): a fixture question with a pending (un-actioned) candidate-answer draft does
      not receive a second draft even when new evidence crosses the threshold again — asserted at the
      production refresh entrypoint. Verify:
      `tests/standing_questions/test_answer_refresh.py::test_pending_review_not_clobbered_by_new_delta`
- [ ] AC3: the pending-review check is derived fresh from vault state each tick, not a stored decision
      — a fixture that simulates a crash between "detected pending" and any write leaves no residue
      the next tick must clean up (next tick re-evaluates identically). Verify:
      `tests/standing_questions/test_answer_refresh.py::test_deferral_is_derived_not_persisted`
- [ ] AC4: a fixture refresh whose drafted conclusion contradicts the current standing answer is
      flagged `contradicts_standing_answer: true` with a quoted contradiction basis, before any human
      review. Verify:
      `tests/standing_questions/test_answer_refresh.py::test_contradiction_surfaced_not_silently_rewritten`
- [ ] AC5: a degraded/UNKNOWN contradiction-judgment fixture lands the draft with
      `contradiction: unknown` (never a silent `false`) while the draft itself still materializes.
      Verify: `tests/standing_questions/test_answer_refresh.py::test_degraded_contradiction_judgment_lands_unknown_not_false`
- [ ] AC6: no code path sets `standing_answer_ref` from a drafted (unaccepted) candidate — asserted at
      the production draft-materialization entrypoint. Verify:
      `tests/standing_questions/test_answer_refresh.py::test_draft_never_sets_standing_answer_ref`
- [ ] AC7: `last_refreshed_at` advances only on successful draft materialization; a blocked draft
      (e.g. unresolvable citation) leaves it unchanged so the triggering delta remains evaluable next
      tick. Verify:
      `tests/standing_questions/test_answer_refresh.py::test_last_refreshed_at_only_advances_on_success`
- [ ] AC8 (enforcement): `status: answered` is asserted unreachable from this task's write path — this
      task's own production entrypoint never sets `status`. Verify:
      `tests/standing_questions/test_answer_refresh.py::test_refresh_path_never_writes_status`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/standing_questions/test_answer_refresh.py
pytest -q -m "not pg"          # full suite: retrieval + Create-engine reuse hot path
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat   # vault write-path change
```

## Out of Scope

Re-implementing any part of the Create engine (EXP-3 owns `CompilationDraft`, staging,
citation validation, expiry — this task only adds a new trigger and the contradiction extension);
the accept/dismiss action itself (SQ-05 owns the human-facing checkbox; this task only produces the
draft the checkbox acts on); tuning the RQ-SQ1 threshold value (research, post-live-data); any
deletion of evidence or drafts.

## Restart / Durability Posture

The pending candidate-answer draft is a vault-durable staging note (reusing Create's existing staging
area, e.g. `_system/drafts/`) — a restart loses no pending review. The pending-review check itself
holds no in-memory state (AC3): it is recomputed from vault content on every tick, so a crash at any
point during the check leaves nothing to reconcile.

## Related Docs

- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: 2` (the Create engine this task
  reuses without modification to its own contract) and `:: 3` (declined-proposal ledger, reused by
  SQ-05's dismiss path, not this task)
- `docs/RUNTIME_CORRECTNESS_KERNEL/STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md` (the schema-constrained +
  explicit-UNKNOWN pattern the contradiction judgment follows)
- [MATCH_EVIDENCE_TO_OPEN_QUESTIONS](MATCH_EVIDENCE_TO_OPEN_QUESTIONS.md) (the evidence log this task
  reads)

## Related GitHub Issues

One issue: `[Standing Questions] refresh-answer-on-evidence-delta: threshold-triggered candidate
re-drafting with explicit contradiction surfacing`. **Hard-blocked on the external EXP-3 (Create
engine) dependency in addition to SQ-01/SQ-03** — do not pick this up until EXP-3 has merged, even if
its drafted GitHub issue carries a `ready`-shaped label at filing time; verify EXP-3's live state
before starting. TCD hint: Opus / high effort — mirrors EXP-4's own "Opus (authority semantics)"
rating; the pending-review-not-clobbered race (AC2/AC3) and the contradiction-never-silently-dropped
guarantee (AC4/AC5) are exactly the kind of subtle correctness/authority-adjacent work the repo routes
above Sonnet.
