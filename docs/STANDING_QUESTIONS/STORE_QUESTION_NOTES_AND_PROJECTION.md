---
name: Store Question Notes and Projection
description: Note-serialized, human-terminal Question store (vault-canonical, WriteGuard-seam) + rebuildable PG projection for query; system-owned bounded fields for evidence/candidate-answer pointers, human-owned text/status
task_id: SQ-01
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: 3. Standing questions
parent_capability: Standing Questions
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Store Question Notes and Projection

## Purpose

Nothing durable exists today for "a question the owner wants answered eventually" — it lives in the
owner's head or scattered notes. This task builds the persistence substrate every other Standing
Questions task writes to or reads from: a vault-canonical Question note per standing question, and a
rebuildable Postgres projection for query, mirroring the Episode Resolution Engine's proven
note-store+projection pattern (`docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md`).

## What This Task Does

1. **Schema**: `schemas/question-note.schema.json` — `question_id` (`sq-<uuid>`), `scope`, `text` (the
   question itself, verbatim, human-owned), `status ∈ {open, answered, closed}` (human-terminal —
   see below), `created_at`, `registered_via ∈ {capture_intent, explicit}`, `standing_answer_ref`
   (pointer to the currently accepted answer note, null until first acceptance), `candidate_answer_ref`
   (pointer to a pending staged candidate-answer draft, null when none pending — system-owned bounded),
   `evidence` (system-owned, bounded, **append-only** list: `{artifact_ref, source_stream, matched_at,
   confidence_class, provenance_ref, quoted_span}`), `last_matched_at` / `last_refreshed_at`
   (system-owned bounded timestamps). Prose-mirror-of-schema section in this capability's README,
   consistent with `docs/architecture/*` contract style. The production validation seam enforces
   every non-null `format: date-time` value as RFC 3339 before guarded note writes and when notes are
   parsed for projection rebuild; enforcement does not depend on optional host checker registration.
2. **Ownership split, enforced not just documented** (`docs/FRONTMATTER.md :: Ownership: human vs
   system`): `text` and `status` are human-owned — the store's write path refuses any engine-authored
   mutation of these two fields at the seam, full stop, regardless of caller. `evidence`,
   `candidate_answer_ref`, `standing_answer_ref`, `last_matched_at`, `last_refreshed_at` are
   system-owned and bounded: the engine may append/update them, but every write is
   receipted and none is a second authoring surface for meaning.
3. **Store (guarded seam, same two-class write discipline as the Episode note store)**: writes route
   through `guard.assert_writes_allowed(action)` at the seam (action `standing_questions.write_note`),
   returning a `WriteReceipt`, following the `app/knowledge/write_ops.py` pattern
   (invariant `write_guard_asserted_at_every_write_seam`). Unlike the Episode note store's
   proposal-class default, a **newly created** Question note is written only via an already-confirmed
   registration (explicit human action, or an accepted capture-intent proposal per SQ-02) — there is
   no "proposed" Question-note state; the note either exists as an `open` question or it does not yet
   exist.
4. **Projection**: a rebuildable PG `standing_questions` projection (Alembic migration, forward-only,
   following the `decisions`/`episodes` projection precedent at `app/jobs/decisions_projection.py`) —
   vault notes are the SoR; the projection exists for query (open-question list, evidence-trail
   lookups, pending-candidate lookups) and must fully rebuild from vault (DRI discipline).
5. **Id minting**: `question_id = sq-<uuid>`, distinct namespace from `ep-*` (episodes) and any other
   entity id space in the vault — the store rejects a caller-supplied id that does not match the
   `sq-` prefix.

## Concretely

Not yet implemented (#3532 audit finding): this task (SQ-01) has not shipped, and no `questions`
CLI group exists in `app/cli/` today — `python -m app.cli questions ...` does not currently run.
The block below is the TARGET shape this task builds toward, mirroring the already-shipped
`episodes` CLI (`app/cli/episodes.py`), not a description of current behavior.

```
$ python -m app.cli questions create --text "Should we migrate the retrieval index to BGE-M3 fully?" --scope work
→ WriteReceipt(operation="standing_questions.write_note", locator=vault://questions/sq-...)
$ python -m app.cli questions rebuild-projection   # projection rebuilds from vault, row-for-row
$ python -m app.cli questions show sq-... --json
{"question_id": "sq-...", "status": "open", "text": "...", "evidence": [], "standing_answer_ref": null}
```

## Why This Matters

Every downstream Standing Questions behavior — matching, refresh, review — reads or writes this
substrate. If the human/system field-ownership split blurs here, evidence-matching or answer-drafting
can silently rewrite the owner's own question text or flip its lifecycle state without an explicit
accept — exactly the failure mode the whole capability exists to avoid (candidate, not authority,
until the human decides).

## Acceptance Criteria

- [ ] AC1: Question notes validate against `schemas/question-note.schema.json`; a note with an
      unknown `status` value or a `question_id` outside the `sq-` namespace fails. Verify:
      `tests/standing_questions/test_question_note_schema.py::test_question_note_schema_validates_shape`
- [ ] AC2 (enforcement): the write path asserts WriteGuard **at the production seam** before any
      filesystem mutation and returns a `WriteReceipt`. Verify:
      `tests/standing_questions/test_question_store.py::test_write_asserts_guard_at_seam`
      (blocked-health snapshot → `WritesBlockedError`, no file written)
- [ ] AC3 (enforcement): an engine-authored write attempting to mutate `text` or `status` on an
      existing note is rejected at the production seam — the note is left byte-for-byte unchanged, and
      the rejection is logged/receipted. Verify:
      `tests/standing_questions/test_question_store.py::test_engine_cannot_overwrite_human_owned_fields`
- [ ] AC4: system-owned bounded fields (`evidence`, `candidate_answer_ref`, `standing_answer_ref`,
      timestamps) can be appended/updated by the engine, each write receipted, without touching
      `text`/`status`/`created_at`. Verify:
      `tests/standing_questions/test_question_store.py::test_engine_may_append_system_owned_fields_only`
- [ ] AC5: projection rebuild from a fixture vault reproduces the projection exactly (drop → rebuild →
      identical rows); projection is never written except by the projector. Verify:
      `tests/standing_questions/test_question_projection.py::test_projection_rebuilds_from_vault`
      (pg-marked)
- [ ] AC6: Alembic migration applies and is recorded forward-only, consistent with house migration
      style. Verify:
      `tests/standing_questions/test_question_projection.py::test_standing_questions_projection_migration_applies`
      (pg-marked)

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/standing_questions/test_question_note_schema.py tests/standing_questions/test_question_store.py
pytest -q -m pg tests/standing_questions/test_question_projection.py   # on a pg-capable channel (mac mini)
pytest -q -m "not pg"
```

Laptop has no pg by design — pg-marked ACs execute on the mac mini test channel per house practice;
the PR states which gate ran where.

## Out of Scope

Registration paths (how a note first comes to exist — SQ-02); evidence matching logic (SQ-03);
candidate-answer drafting/refresh (SQ-04); companion UI review surface (SQ-05); question
deduplication/near-duplicate detection (a future refinement, not required for the first store).

## Restart / Durability Posture

Question notes are vault-durable (SoR), including their system-owned bounded fields. The PG projection
is rebuildable; losing it loses only query speed, never a question, an evidence link, or an answer
pointer. No in-memory state survives restart, and nothing user-facing depends on in-memory state.

## Related Docs

- `docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md` (the pattern this task copies
  structurally)
- `docs/FRONTMATTER.md :: Ownership: human vs system` (the field-ownership contract enforced here)
- `app/knowledge/write_ops.py` (guard-at-seam precedent), `app/knowledge/contracts.py::WriteReceipt`
- `docs/testing/invariant-tests.md` §Vault multi-writer (ADR-0055) — question notes obey the same
  optimistic-write rules

## Related GitHub Issues

One issue: `[Standing Questions] store-question-notes-and-projection: vault-canonical Question notes +
rebuildable projection`. Ready immediately (no prerequisites). **Tier 3 flag: ships an Alembic
migration** — the PR must declare it.
