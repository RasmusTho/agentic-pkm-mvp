---
name: Synthesize Debrief Note
description: Create-engine synthesis of the debrief — decisions made, commitments taken, open loops, key captures, each provenance-linked — as a candidate artifact linked from the Episode note, never editing the note's human-owned content
task_id: DEBRIEF-02
source_anchor: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: §2 Create — synthesized outputs
parent_capability: Episode Debrief
prerequisites: [DEBRIEF-01]
depends_on: [TRIGGER_DEBRIEF_ON_CLOSURE.md]
can_parallelize_with: []
---

# Synthesize Debrief Note

## Purpose

This is the capability's actual value delivery — the retro the owner never has time to run. Rather than
building a parallel synthesis path, this task adds one new trigger-driven output kind to the already-
live Create engine (EXP-3/EXP-4, #2996/#2997, `docs/STATUS.md :: Cognitive Expansion`), reusing its
proven citation-validated, no-laundering-guarded, activation-gated draft lifecycle.

## What This Task Does

1. **New closed-enum entry**: add `create.episode_debrief` to `app/expansion/create.py::OutputKind` /
   `SUPPORTED_OUTPUT_KINDS` — the fourth kind after `overview`/`answer_note`/`digest`. Trigger = an
   eligible `debrief.trigger.created` record (DEBRIEF-01), **never** an explicit human ask (the whole
   point is that nobody has to ask). This is a cross-capability contract touch, not a silent one: the
   owning spec's output-kinds table
   (`docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2.1) gains this row in the same
   PR.
2. **Context assembly** over the episode's bound artifacts (via `episode_ref` bindings, ERE-05), through
   the existing retrieval seam, same scope prefilter + evidence-role clamp Create already enforces (no
   widening beyond the trigger's own scope — the capability's cross-task invariant):
   - **decisions made** — from the decision-receipt log (`docs/DECISION_RECEIPT_LOG/README.md`,
     `app/services/decisions.py`) filtered to receipts whose provenance falls within the episode's bounds
   - **commitments taken** — from the durable commitment artefacts (`docs/COMMITMENT_SURFACING/README.md`,
     `app/domain/commitments.py`) created or touched within bounds
   - **open loops** — commitments still `next_action`/`waiting` at closure time, plus any bound artifact
     flagged in-progress
   - **key captures** — Heimdal/vault/KAP artifacts bound to the episode (`episode_ref`) not already
     covered above
3. **Draft assembly** via the existing `proposal_builders.build_compilation_draft`
   (`CompilationDraft`/`SourceRef[]`), unchanged: the same no-laundering guard and the same
   "unresolvable citation blocks the draft loudly" rule EXP-3 already enforces apply per item — a
   decision/commitment/capture with no resolvable source is not a debrief line item, it is a blocked
   draft.
4. **Materialization, deliberately NOT under `_system/drafts/`.** A debrief note is written to its own
   staging-adjacent location (`_system/episode-debriefs/`), excluded from ingest indexing the same way
   `_system/drafts/`/`_system/companions` already are (candidate content, not yet retrieval-indexed) —
   but **not** subject to EXP-3's `sweep_expired_drafts` staleness sweep and carries no `expires` field.
   A debrief's lifecycle ends only via DEBRIEF-03's human disposition, never a timeout (unlike Create's
   ephemeral overview/answer_note/digest drafts, a debrief is meant to persist as retro material).
5. **Episode note cross-reference, additive only.** The Episode note gains one appended field,
   `debrief_ref: [debrief-id]`, through the same guarded seam ERE-05 uses for binding appends. This task
   asserts — as a hard invariant, extending ERE-07's engine-never-overwrites rule to this capability's own
   write — that no other field on the Episode note (`time`, `title`, `goal`, `space`, `protagonists`,
   `segmentation`, body) is ever touched.
6. **Frontmatter**: the debrief note lands `derived_by: synthesis`, `authority_state: proposal`
   (identical posture to a Create draft — no DecisionToken/AuthorityReceipt at creation) and
   `review_state: draft` (the canonical `STATE_AXES_CONTRACT.md` no-stronger-posture-claimed value — this
   task does **not** invent a new value; DEBRIEF-03 is the only task that advances it).
7. **Activation**: reuses the existing `synthesis_note_proposal` activation-gate record
   (`app/activation/expansion_records.py::evaluate_synthesis_note_proposal_activation`) unchanged — this
   is the same capability contract gaining a new trigger path, not a new capability requiring its own
   gate record.
8. **Idempotent per closure**: `debrief_id` (DEBRIEF-01) is the identity; re-running synthesis over an
   already-debriefed episode is a no-op — no second draft, no second `debrief_ref` append.

## Concretely

```
$ python -m app.cli episode-debrief synthesize --episode ep-2026-07-07-morning --json
{
  "kind": "create.episode_debrief",
  "draft": "_system/episode-debriefs/debrief-ep-2026-07-07-morning.md",
  "sections": {"decisions": 2, "commitments": 3, "open_loops": 1, "key_captures": 4},
  "episode_note_updated": true
}
```

## Why This Matters

If synthesis bypasses citation validation, the debrief becomes unsourced narrative masquerading as a
retro — the charter's named provenance-loss failure mode, here at its most damaging because it is the
one artifact meant to be trusted at a glance. If it edits the Episode note's dimensions or cut, it
violates the ERE-07 invariant the entire opt-out segmentation posture depends on. If it fuses across
scopes, it reopens — one layer downstream — the exact leak `GATE_CROSS_SCOPE_FUSION.md` was built to
close.

## Acceptance Criteria

- [ ] AC1: a debrief draft's four sections (decisions/commitments/open_loops/key_captures) each carry
  only items with a resolvable `SourceRef`; an unresolvable citation blocks the draft loudly (extends the
  existing `UnresolvableCitationError` path). Verify: `tests/episode_debrief/test_synthesis.py::test_debrief_sections_carry_resolvable_source_refs`
- [ ] AC2 (enforcement): synthesis never admits material outside the trigger's own scope — asserted at
  the production context-assembly call site (the same `cross_scope_no_flow` denial class ERE-08
  established, inherited unchanged, no separate widening path). Verify: `tests/episode_debrief/test_synthesis.py::test_synthesis_never_crosses_episode_scope`
- [ ] AC3 (enforcement): the write path never mutates the Episode note's five dimensions, title,
  segmentation/cut, or body — only the additive `debrief_ref` field is appended, asserted at the
  production write seam (an attempted mutation of a protected field is rejected + logged, note otherwise
  untouched). Verify: `tests/episode_debrief/test_synthesis.py::test_synthesis_never_mutates_episode_note_content`
- [ ] AC4: the debrief note lands `derived_by: synthesis`, `authority_state: proposal`,
  `review_state: draft` — no DecisionToken/AuthorityReceipt at creation. Verify: `tests/episode_debrief/test_synthesis.py::test_debrief_note_is_candidate_class_no_authority_receipt_at_creation`
- [ ] AC5: idempotent per closure — re-running synthesis on an already-debriefed episode produces no
  second draft and no second `debrief_ref` append. Verify: `tests/episode_debrief/test_synthesis.py::test_synthesis_idempotent_per_episode`
- [ ] AC6: a regressed `synthesis_note_proposal` activation posture yields blocked-with-reason, never a
  silent run. Verify: `tests/episode_debrief/test_synthesis.py::test_blocked_without_green_activation_record`
- [ ] AC7 (enforcement): debrief notes are excluded from ingest indexing (mirrors the existing
  `_system/drafts/` exclusion, extended to `_system/episode-debriefs/`) and carry no `expires` field —
  asserted against the production ingest call site. Verify: `tests/episode_debrief/test_synthesis.py::test_debrief_location_excluded_from_ingest_and_not_swept_by_draft_expiry`
- [ ] AC8: `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2.1 output-kinds table
  gains the `create.episode_debrief` row in the same PR (non-behavioral, owner-doc impact). Verify: doc
  writeback at `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: 2.1 Output kinds`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episode_debrief/test_synthesis.py tests/invariants/test_expansion_invariants.py
pytest -q -m "not pg"
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat
```

## Out of Scope

The trigger/eligibility decision (DEBRIEF-01); companion UI review/accept/dismiss (DEBRIEF-03);
cross-episode rollups; any change to `create.overview`/`answer_note`/`digest` behavior; a new activation-
gate record (this reuses `synthesis_note_proposal`'s existing one).

## Restart / Durability Posture

The debrief draft write and the Episode note's `debrief_ref` append are each a single atomic
WriteGuard-gated write (write-complete-or-none, per the `materialize_promoted_memory`/EXP-3 precedent) —
vault-durable once written. A crash mid-write leaves no half-written draft and no partial `debrief_ref`;
the next DEBRIEF-01 reconciliation tick re-attempts cleanly since idempotency keys on `episode_id`.

## Related Docs

- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2 (Create engine, reused unchanged)
- `docs/EPISODE_RESOLUTION_ENGINE/RESPECT_HUMAN_RECUT.md` (engine-never-overwrites precedent, extended)
- `docs/EPISODE_RESOLUTION_ENGINE/GATE_CROSS_SCOPE_FUSION.md` (scope discipline inherited unchanged)
- `docs/DECISION_RECEIPT_LOG/README.md`, `docs/COMMITMENT_SURFACING/README.md` (debrief inputs)
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md` (`review_state` canonical values — conformed to, not forked)
- `app/expansion/create.py`, `app/expansion/accept.py`, `app/activation/expansion_records.py`

## Related GitHub Issues

One issue: `[Episode Debrief] synthesize-debrief-note: Create-engine debrief synthesis linked from the
Episode note`. Blocked until DEBRIEF-01 merges (and transitively ERE-02/04/06).
