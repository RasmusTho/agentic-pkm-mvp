---
name: Assemble Day Context
description: Deterministic assembly of the day's material — commitments touched/completed, decision receipts, captures/observations — into a provenance-cited context bundle for the ghost-writer conversation, degrading legibly on partial source failure
task_id: JRNL-01
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 7. Conversational journaling
parent_capability: Conversational Journaling
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Assemble Day Context

## Purpose

The ghost-writer conversation (JRNL-02) must open *informed* — "here's what I saw in your day" — rather than with a blank "how was your day?" prompt that forces the owner to reconstruct the day from memory himself, defeating the entire cognitive-prosthetic point. This task builds the assembler: a deterministic read of the day's already-durable material into one provenance-cited bundle, with no LLM involved in this step. It is the foundation every other task in this capability depends on.

## What This Task Does

1. **Reads three live sources, unmodified where a read path already exists:**
   - Commitments touched/completed today: `app/services/commitment_persistence.py::load_commitments` (all states, not the forward-looking `next`/`waiting` filter `query_next_and_waiting_commitments` applies), filtered to records whose persisted vault artifact changed within today's local calendar day. This is a new filter this task adds — reflection needs what *changed* today (a commitment marked `done`, a new `waiting` opened), not only what remains outstanding.
   - Decision receipts of the day: `app/receipts/decision_receipt_log.py::iter_decision_receipts`, filtered to today's local calendar day.
   - Captures/observations of the day: candidate/inbox artifacts newly written to the vault today, e.g. via `app/knowledge_acquisition/candidate_writeback.py::write_candidate_note`, filtered to today's creation timestamp. This is a new read function this task adds — no "captures created today" query exists yet.
2. **Assembles one context bundle** with one section per source, each item carrying a provenance reference resolvable back to its source artifact: `commitment_id` + before/after state for commitments, the receipt entry (`object_id`/`vault_uuid`/`key`/`created_at`) for decision receipts, the candidate/source note ref for captures. The bundle follows the `ContextBundle` envelope shape (`app/context_bundles/construction.py::build_inspectable_bundle`, `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`): `IncludedItem`/`ExcludedItem` with per-item provenance, and `may_write=false` — this bundle is read-only assembly; drafting a note is JRNL-03's separate, later, governed step.
3. **Fail-legible partial assembly.** If any one source read fails or raises, the bundle still assembles — with that section **explicitly named as missing** (a `degraded_sources: ["decision_receipts"]` marker), never a silently thinner bundle that looks complete. This is the same discipline `docs/DAILY_BRIEFING/COMPOSE_BRIEFING_ARTIFACT.md` established for its own composer, applied here to the evening context assembler.
4. **No fabricated absence.** Consistent with the `unknown`-not-empty discipline established across the repo (`docs/COMMITMENT_SURFACING/README.md` CI-2), a source that could not be read is marked degraded/unknown, never rendered as "nothing happened today" in that section.
5. **Determinism.** Assembling the bundle twice against the same underlying source state produces the same content — this is what makes a re-run (a retried assembly after a transient failure, or JRNL-02 restarting mid-conversation and needing the bundle again) safe to call more than once.

## Concretely

```python
from app.journaling.day_context import assemble_day_context

bundle = assemble_day_context(vault_context=ctx, for_date=date(2026, 7, 7))
assert bundle.may_write is False
assert bundle.degraded_sources == []
assert bundle.sections["commitments"][0].provenance_ref == "commitment-id-123"
```

When the captures read raises:

```python
bundle = assemble_day_context(vault_context=ctx, for_date=date(2026, 7, 7))
assert bundle.degraded_sources == ["captures"]
assert "could not be read" in bundle.sections["captures"].note
```

## Why This Matters

If the conversation opened uninformed, the owner would have to do the reconstruction work himself before the agent could add any value — exactly the burden a cognitive prosthesis exists to remove. If a degraded source were silently hidden, the owner would trust an opening line ("looks like a quiet day") that is actually just a read failure wearing the costume of a quiet day. The bundle being read-only (`may_write=false`) matters because context assembly and journal drafting are deliberately separate governed steps (JRNL-03) — this task never writes anything to the vault.

## Acceptance Criteria

- [ ] AC1: the assembler builds a context bundle from all three live sources (commitments touched/completed, decision receipts, captures) for a given day, each item carrying a resolvable provenance reference. Verify: `tests/journaling/test_assemble_day_context.py::test_assembles_full_context_with_provenance`
- [ ] AC2: a partial source failure (any one of the three reads raising or degrading) still produces a bundle, with the missing source explicitly named — never a silently thinner bundle. Verify: `tests/journaling/test_assemble_day_context.py::test_partial_source_failure_names_missing_source`
- [ ] AC3: the commitments read captures state *changes* within the day (done today, opened today), distinct from Daily Briefing's forward-looking next/waiting filter — a commitment marked done earlier today appears; one untouched today does not. Verify: `tests/journaling/test_assemble_day_context.py::test_commitments_filtered_to_todays_changes`
- [ ] AC4 (enforcement): the assembled bundle carries `may_write=false` per the `ContextBundle` contract, and no code path in this task performs a vault write. Verify: `tests/journaling/test_assemble_day_context.py::test_bundle_carries_no_write_authority`
- [ ] AC5: assembling the bundle twice for the same day against the same underlying source state is deterministic (identical content), so a repeated call (e.g. JRNL-02 restarting mid-conversation) is safe. Verify: `tests/journaling/test_assemble_day_context.py::test_assembly_is_deterministic_for_same_inputs_same_day`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/journaling/test_assemble_day_context.py
pytest -q -m "not pg"
```

## Out of Scope

The conversation itself (JRNL-02); drafting the journal entry (JRNL-03); the review surface (JRNL-04); any LLM-driven interpretation of the assembled facts (this task's output is deterministic structured data, never prose); episode debriefs and Heimdal screen-stream data (named future seams, not read here); any change to the underlying commitment/receipt/capture stores this task only reads.

## Restart / Durability Posture

The assembler is a pure read-then-return function with no persisted output of its own — it is invoked fresh by JRNL-02 whenever a conversation opens or resumes. A process restart mid-assembly leaves no partial state to worry about: the next invocation re-reads the same live sources from scratch and produces the same bundle (determinism, AC5). There is no in-memory "assembly in progress" state that could be lost.

## Related Docs

- `docs/CONVERSATIONAL_JOURNALING/README.md` (capability spec, day-context inventory, cross-task invariants)
- `docs/research/yggdrasil-closed-loops-ideation.md` (grounding, loop 7)
- `docs/DAILY_BRIEFING/COMPOSE_BRIEFING_ARTIFACT.md` (the sibling composer this task's fail-legible/provenance discipline mirrors)
- `app/services/commitment_persistence.py`, `app/domain/commitments.py` (commitments source)
- `app/receipts/decision_receipt_log.py` (decision-receipts source)
- `app/knowledge_acquisition/candidate_writeback.py` (captures source)
- `app/context_bundles/construction.py::build_inspectable_bundle`, `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` (the bundle envelope this task's output follows, including the `may_write=false` default)

## Related GitHub Issues

One issue: `[Conversational Journaling] assemble-day-context: commitments, receipts, and captures into one provenance-cited bundle`. Ready immediately — no prerequisites.
