---
name: Compose Briefing Artifact
description: Deterministic composer that assembles commitments, CRE relevance picks, and decision receipts into one provenance-cited briefing note, written through the governed vault-write path
task_id: BRIEF-01
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 1. Daily briefing
parent_capability: Daily Briefing
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Compose Briefing Artifact

## Purpose

The three sources this capability depends on already exist and are already live — commitments, CRE relevance picks, decision receipts — but nothing assembles them into one artifact today. This task builds the composer: the deterministic function that reads all three, assembles one briefing note per day, provenance-links every item, and writes it through the existing governed write path. It is the foundation every other task in this capability depends on.

## What This Task Does

1. **Reads three live sources, unmodified:**
   - Commitments: `app/services/commitment_persistence.py::load_commitments` → `app/domain/commitments.py::query_next_and_waiting_commitments` for the active `next_action` / `waiting` / `review_return` set.
   - CRE relevance picks: `app/relevance/now_surface.py::collect_now_moments` for the current materialized Moments (already sorted by urgency).
   - Decision receipts: `app/receipts/decision_receipt_log.py::iter_decision_receipts` filtered to a recent window (e.g. since the last briefing or a fixed lookback).
2. **Assembles one briefing note** with one section per source, each item carrying a provenance reference resolvable back to its source artifact: `target_ref` for commitments, `moment_id` + `surfaced_refs` for CRE picks, the receipt entry (`object_id` / `vault_uuid` / `key` / `created_at`) for decision receipts.
3. **Fail-legible partial generation.** If any one source read fails or raises (e.g. the receipt log is unreadable, the commitment store is empty because of a degraded read), the composer still produces a briefing note — with that section **explicitly named as missing** (e.g. a `degraded_sections: ["decision_receipts"]` marker plus a rendered "this section could not be generated" line), never a silently thinner briefing that looks complete.
4. **Writes through the governed vault-write path**, following the existing companion-note / commitment-persistence pattern (`app/services/companion_note.py`, `app/services/commitment_persistence.py::persist_commitment`): asserts `DEFAULT_WRITE_GUARD.assert_writes_allowed("briefing.write_note")` before any filesystem mutation, writes one complete file (atomic-or-absent), returns a `WriteReceipt` (`app/knowledge/contracts.py::WriteReceipt`). A blocked guard raises and leaves no file.
5. **Storage location**: one dated note per day, `<system_dir>/briefings/YYYY-MM-DD.md` (`app/vault/paths.py::get_vault_system_dir_rel`), matching the `moments/*.md` / commitment-artefact family precedent — a new note class, not an overwrite of any human-authored note.
6. **Determinism**: composing from the same inputs on the same day produces the same content — this is what makes BRIEF-02's once-per-day trigger safe to call more than once without corrupting state, and what makes an explicit regenerate (any task's future concern) a harmless overwrite rather than a risky mutation.

## Concretely

```python
from app.briefing.compose import compose_briefing

receipt = compose_briefing(vault_context=ctx, for_date=date(2026, 7, 8))
# → WriteReceipt(operation="briefing.write_note", locator=vault://<system_dir>/briefings/2026-07-08.md)

note = load_briefing(vault_context=ctx, for_date=date(2026, 7, 8))
assert note.degraded_sections == []  # all three sources read cleanly
assert note.sections["commitments"][0].provenance_ref == "projects/hiring.md"
```

When the decision-receipt read raises:

```python
receipt = compose_briefing(vault_context=ctx, for_date=date(2026, 7, 8))
note = load_briefing(vault_context=ctx, for_date=date(2026, 7, 8))
assert note.degraded_sections == ["decision_receipts"]
assert "could not be generated" in note.sections["decision_receipts"]
```

## Why This Matters

Every downstream task (schedule, audio, UI, calendar) reads or triggers this composer; if it silently produced a thin briefing on partial failure, the owner would trust a briefing that quietly dropped a section — exactly the failure mode a low-cognitive-load, push-not-pull surface cannot afford, because the whole point is that the owner stops checking the underlying panels himself. If provenance were flattened into un-attributed prose, the briefing would become a second, ungrounded copy of the truth instead of a citation-backed view onto it.

## Acceptance Criteria

- [ ] AC1: the composer assembles a briefing note from all three live sources (commitments, CRE picks, decision receipts) when all read cleanly, each item carrying a resolvable provenance reference. Verify: `tests/briefing/test_compose_briefing.py::test_composes_full_briefing_with_provenance`
- [ ] AC2 (enforcement): the briefing write path asserts WriteGuard at the production seam before any filesystem mutation and returns a `WriteReceipt`; a blocked guard raises and writes nothing. Verify: `tests/briefing/test_compose_briefing.py::test_briefing_write_asserts_guard_at_seam` (blocked-health snapshot → `WritesBlockedError`, no file written)
- [ ] AC3: a partial source failure (any one of the three reads raising or degrading) still produces a briefing note, with the missing section explicitly named — never a silently thinner briefing. Verify: `tests/briefing/test_compose_briefing.py::test_partial_source_failure_names_missing_section`
- [ ] AC4: every item in every section carries a provenance ref that resolves back to its source artifact (commitment `target_ref`, moment `moment_id`/`surfaced_refs`, receipt entry fields). Verify: `tests/briefing/test_compose_briefing.py::test_every_item_carries_provenance_ref`
- [ ] AC5: composing twice for the same day against the same underlying source state is deterministic (identical rendered content), so a duplicate invocation is a harmless overwrite. Verify: `tests/briefing/test_compose_briefing.py::test_compose_is_deterministic_for_same_inputs_same_day`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/briefing/test_compose_briefing.py
pytest -q -m "not pg"
```

## Out of Scope

Scheduling or triggering when composition runs (BRIEF-02); audio rendering (BRIEF-03); the companion-UI card (BRIEF-04); the calendar/episodes section (BRIEF-05, blocked); any recomputation of commitment state, CRE salience, or decision-receipt content — this task only reads existing projections through their existing functions.

## Restart / Durability Posture

The composed briefing note is vault-durable (written through the governed write path, same durability class as commitment artefacts and Moments). No in-memory state survives or needs to survive a restart: the composer is a pure read-then-write function invoked fresh each time, and its output is fully recoverable from the note itself. A process restart mid-compose leaves either no file (guard blocked or crash before the atomic write) or a complete file — never a partial one.

## Related Docs

- `docs/DAILY_BRIEFING/README.md` (capability spec, sources-consumed table, cross-task invariants)
- `docs/research/yggdrasil-closed-loops-ideation.md` (grounding)
- `app/services/commitment_persistence.py`, `app/domain/commitments.py` (commitments source)
- `app/relevance/now_surface.py` (CRE Moments source)
- `app/receipts/decision_receipt_log.py` (decision-receipts source)
- `app/services/companion_note.py`, `app/knowledge/contracts.py::WriteReceipt` (governed-write pattern this task follows)
- `app/vault/paths.py::get_vault_system_dir_rel` (note location convention)

## Related GitHub Issues

One issue: `[Daily Briefing] compose-briefing-artifact: assemble commitments, CRE picks, and decision receipts into one provenance-cited note`. Ready immediately — no prerequisites.
