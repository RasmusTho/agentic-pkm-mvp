---
name: Draft Journal Entry
description: Ghost-written, candidate-class journal draft synthesized from the reflection conversation plus day context, provenance-separated, one per day, idempotent under a repeated same-day session
task_id: JRNL-03
source_anchor: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md :: 2. Create — synthesized outputs (always a proposal)
parent_capability: Conversational Journaling
prerequisites: [JRNL-01, JRNL-02]
depends_on: [ASSEMBLE_DAY_CONTEXT.md, LEAD_REFLECTION_CONVERSATION.md]
can_parallelize_with: []
---

# Draft Journal Entry

## Purpose

The conversation (JRNL-02) produces a transcript; the day-context bundle (JRNL-01) carries the facts. Neither is a journal entry. This task is the ghost-writing step: synthesize both into one first-person draft in the owner's voice, staged as a governed candidate — never written to the canonical journal location until the owner accepts it (JRNL-04).

## What This Task Does

1. **Synthesizes from two inputs**: the reflection conversation's transcript (JRNL-02, the owner's own words — the primary voice source) and the day-context bundle (JRNL-01, supporting facts — commitments, receipts, captures). The draft is written in first person, in the owner's voice, using the conversation as the voice/content backbone and the day-context bundle to ground and enrich specific facts the conversation only alluded to.
2. **Reuses the Create engine's draft-lifecycle machinery, not a new architecture.** This task activates the same dormant cognition/compilation substrate `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` describes (`run_multi_note_reasoning`, `CompilationDraft`, `proposal_builders` — already built, dormant per that spec's build-on inventory) through its own Expansion Activation Gate record, mirroring how Create's own EXP-3 activates them — **this task does not depend on Create's EXP-3/EXP-4 issues merging first**; it is its own passage through the gate. If EXP-3 lands first, a future consolidation may converge shared draft-lifecycle helpers; that convergence is not a blocking dependency here.
3. **Candidate-class, governed staging write.** The draft is written to a journal-specific staging location analogous to Create's own undecided staging convention (`_system/drafts/` per `EXPANSION_CONNECT_AND_CREATE.md` §2.3, owner decision E1 — this task reuses that same open decision rather than opening a second staging-location question; recommended default `_system/drafts/journal/YYYY-MM-DD.md`). WriteGuard is asserted (`assert_writes_allowed("journal.draft.write")`) before any filesystem mutation; a blocked guard raises and leaves no file. The production writer opens every staging ancestor with no-follow semantics, rejects symlink/non-regular collisions, serializes the complete same-day read/compose/replace transaction, and performs a same-directory fsynced atomic replacement. This makes the candidate atomic-or-absent and prevents both retrieval-visible staging escape and concurrent lost updates.
4. **Frontmatter marks the draft unambiguously machine-authored-but-not-yet-owned**, reusing `docs/FRONTMATTER.md`'s existing draft convention: `derived_by: conversation` (a new value alongside the existing `synthesis`, declared independently — this task does not edit Create's closed output-kind enum, keeping it independently mergeable), `authority_state: proposal`, `sources:` (the conversation `session_id` plus every day-context item's provenance ref), created/expires timestamps. Source refs preserve their actual review posture: owner transcript and JRNL-01 draft captures remain cited `unreviewed` inputs to a SUGGEST proposal and are never relabeled reviewed knowledge. The current content-free gate receipt and retained earlier same-day receipts are embedded under `activation_receipts`; `activation_receipt_id` resolves inside the same atomically replaced artifact after restart. One in-draft Panel `AI-åtgärder` acceptance surface (accept / dismiss checkboxes) is written into the draft itself — the note is the review surface, the same convention already demonstrated in this repo's own UAT fixture (`docs/examples/vault_test_seed/reflection-journal.md`).
5. **Provenance separation, not flattened prose.** Every sentence or clause in the drafted first-person text that traces to a specific day-context item (a commitment, a receipt, a capture) carries a resolvable reference back to it, distinguishable from text that traces only to the conversation transcript (the owner's own words). This is a structural property of the draft's stored representation (e.g. per-section or per-span provenance tags), not merely a hope about prose style — it is what lets JRNL-04's review surface, and any future reader, tell "the owner said this" apart from "the system knew this and folded it in."
6. **One candidate per day, idempotent.** Composing again for the same day (a second conversation session before acceptance, or a retried draft after a prior failure) extends or **redrafts the same staged file** — it never creates a second competing candidate for the same day. Once the day already has an **accepted** entry (JRNL-04 has promoted it), a further draft for that day is instead labeled an **addendum candidate** — staged separately, explicitly marked as an addendum, never mutating or silently merging into the accepted note.
7. **Citation validation.** Every source reference the draft carries must resolve (the commitment/receipt/capture it points to exists); an unresolvable reference blocks the draft from being staged, loudly — never silently dropped, mirroring `CitationChecker`'s role in Create's own draft lifecycle.

## Concretely

```python
from app.journaling.draft import draft_journal_entry

result = draft_journal_entry(vault_context=ctx, for_date=date(2026, 7, 7), session_id="sess-abc")
# → staged at _system/drafts/journal/2026-07-07.md
# frontmatter: derived_by: conversation, authority_state: proposal,
#   sources: [session:sess-abc, commitment:hiring-123, receipt:...]
```

Re-running the same day before acceptance (idempotent redraft):

```python
result2 = draft_journal_entry(vault_context=ctx, for_date=date(2026, 7, 7), session_id="sess-abc-cont")
assert result2.path == result.path  # same staged file, extended/redrafted, not forked
```

Re-running after the day's entry was already accepted:

```python
result3 = draft_journal_entry(vault_context=ctx, for_date=date(2026, 7, 7), session_id="sess-later")
assert result3.is_addendum is True
assert result3.path != result.path  # a new, separately staged addendum candidate
```

## Why This Matters

If the draft flattened system-derived facts into undifferentiated first-person prose, an accepted journal entry would quietly become partly ghost-written fiction with no way to audit which parts were the owner's own reflection — a direct violation of the provenance-separation invariant this capability's README names. If a second same-day session could fork a competing draft, or worse, silently rewrite an already-accepted entry, the owner would lose trust in journaling as a durable, owned record — exactly the failure the never-overwrite invariant exists to prevent.

## Acceptance Criteria

- [ ] AC1: the draft synthesizes first-person text from both the conversation transcript and the day-context bundle, staged to the journal drafts location. Verify: `tests/journaling/test_draft_journal_entry.py::test_draft_synthesizes_from_transcript_and_context`
- [ ] AC2 (enforcement): the staging write asserts WriteGuard at the production seam before any filesystem mutation and leaves no file when blocked. Verify: `tests/journaling/test_draft_journal_entry.py::test_draft_write_asserts_guard_at_seam`
- [ ] AC3: the draft's frontmatter carries `derived_by: conversation`, `authority_state: proposal`, and a `sources` list covering both the conversation session and every day-context item folded in. Verify: `tests/journaling/test_draft_journal_entry.py::test_draft_frontmatter_carries_proposal_provenance`
- [ ] AC4: every clause traceable to a day-context item carries a resolvable provenance reference distinguishable from conversation-sourced text; an unresolvable reference blocks staging loudly rather than being silently dropped. Verify: `tests/journaling/test_draft_journal_entry.py::test_draft_preserves_provenance_separation`, `tests/journaling/test_draft_journal_entry.py::test_unresolvable_citation_blocks_staging_loudly`
- [ ] AC5: composing again for the same day before acceptance extends/redrafts the same staged file rather than forking a second candidate. Verify: `tests/journaling/test_draft_journal_entry.py::test_draft_is_idempotent_same_day`
- [ ] AC6 (enforcement): composing for a day whose entry is already accepted produces a distinctly labeled, separately staged addendum candidate, and never mutates the accepted note. Verify: `tests/journaling/test_draft_journal_entry.py::test_draft_after_acceptance_produces_addendum_not_overwrite`
- [ ] AC7: this task passes an Expansion Activation Gate record of its own (declared admissibility, `proposal` authority class) rather than assuming activation. Verify: `tests/activation/test_journal_draft_activation.py::test_draft_requires_activation_record`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/journaling/test_draft_journal_entry.py tests/activation/test_journal_draft_activation.py
pytest -q -m "not pg"
```

## Out of Scope

Assembling the day-context bundle (JRNL-01) and leading the conversation (JRNL-02) — this task only consumes their outputs; the review/accept surface and promotion to the canonical journal note (JRNL-04); mood/sentiment analysis of the transcript; adding a new output kind to Create's own closed enum (`EXPANSION_CONNECT_AND_CREATE.md` §2.1) — this task declares its own `derived_by: conversation` value in the shared frontmatter convention instead, to stay independently mergeable; multi-day rollups.

## Restart / Durability Posture

The staged draft is vault-durable once written (same durability class as Create's staging drafts and commitment artefacts) — no in-memory state needs to survive a restart to preserve it. The activation record is part of that same atomic artifact, so a visible `activation_receipt_id` cannot outlive or precede its durable receipt. UUID-addressable reasoning inputs are rebuildable machine mirrors of the cited transcript/context; a reasoning failure is recorded as degraded instead of being presented as successful cognition. If the draft-generation step itself crashes mid-synthesis (LLM call fails, process restarts), the atomic-or-absent write guarantees either no file or a complete one — never a half-written draft — and the underlying conversation transcript (JRNL-02) and day-context bundle (JRNL-01) remain intact and re-readable, so a retry after restart reproduces the same synthesis inputs. The owner never sees a corrupted draft; at worst, a retry is needed.

## Related Docs

- `docs/CONVERSATIONAL_JOURNALING/README.md` (capability spec, cross-task invariants — idempotency, addendum, provenance separation)
- `docs/CONVERSATIONAL_JOURNALING/ASSEMBLE_DAY_CONTEXT.md`, `docs/CONVERSATIONAL_JOURNALING/LEAD_REFLECTION_CONVERSATION.md` (this task's two inputs)
- `docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md` §2 (draft lifecycle, staging convention, citation validation, activation gate — the reused precedent)
- `docs/FRONTMATTER.md` (draft frontmatter convention: `derived_by`/`authority_state`/`sources`)
- `docs/examples/vault_test_seed/reflection-journal.md` (existing UAT fixture demonstrating the in-note `AI-åtgärder` review-surface convention)
- `docs/PANEL_AGENT.md` (the `AI-åtgärder` checkbox mechanism JRNL-04 will act on)

## Related GitHub Issues

One issue: `[Conversational Journaling] draft-journal-entry: ghost-written provenance-separated candidate draft, one per day`. `agent:blocked` until JRNL-01 and JRNL-02 merge.
