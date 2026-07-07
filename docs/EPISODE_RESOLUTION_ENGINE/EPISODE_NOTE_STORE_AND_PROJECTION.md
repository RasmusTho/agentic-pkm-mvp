---
name: Episode Note Store and Projection
description: Note-serialized Episode store (vault-canonical, WriteGuard-seam) + rebuildable PG projection for query; episode id minting that cannot collide with Heimdal's per-session episode_id
task_id: ERE-02
source_anchor: docs/adr/ADR-0051-episode-as-ontological-primitive.md :: Decision (OD-1/OD-2)
parent_capability: Episode Resolution Engine
prerequisites: []
depends_on: []
can_parallelize_with: [Stream Registry and Signal Contract, Thread episode_ref into Metadata Bundle]
---

# Episode Note Store and Projection

## Purpose

ADR-0051 (OD-1/OD-2) fixed the Episode as a note-serialized, vault-canonical Artifact — but no schema, store, or projection exists (`schemas/` has no episode schema; `app/` has zero episode code). This task builds the persistence substrate every other ERE task writes to or reads from.

## What This Task Does

1. **Schema**: `schemas/episode-note.schema.json` implementing the ADR-0051 note-serialized situation model exactly — `episode_id`, `scope`, `title`, `time {start, end, closed}`, `space[]`, `protagonists[]`, `goal[]`, `causation[]`, `parent_episode`, `segmentation ∈ {proposed, accepted, re-cut}`, `derived_from[]`. Prose-mirror-of-schema doc section in the capability README, consistent with `docs/architecture/*` contract style.
2. **Id minting + non-collision rule**: fused episode ids are `ep-<uuid>`; Heimdal's per-capture-session `episode_id` (required on `heimdal.observation.published.v1`) is a **different identifier space** consumed as a single-stream boundary *hint* — it may appear in `derived_from`, never as the fused note's `episode_id`. The store rejects an id that echoes a raw Heimdal session id.
3. **Store (two write classes, kept explicit)**:
   - Writes go through the guarded knowledge-write seam (`app/knowledge/write_ops.py` pattern: `guard.assert_writes_allowed(action)` at the seam, action `episodes.write_note`, returning a `WriteReceipt`) — this is the *health/fail-closed* gate every vault-write seam must assert (invariant `write_guard_asserted_at_every_write_seam`).
   - **No human confirm gate**: a `segmentation: proposed` episode is a low-trust opt-out proposal per ADR-0051 §5 — no DecisionToken/AuthorityReceipt, standing by default. Canonical standing arrives via acceptance (silence) or human re-cut (ERE-07), not via a governed transition.
4. **Projection**: a rebuildable PG `episodes` projection (Alembic migration, forward-only, following the `decisions` projection precedent at `app/jobs/decisions_projection.py`) — vault notes are the SoR; the projection exists for query (open episodes, bounds lookup for assignment, closure scans) and must fully rebuild from vault (DRI discipline).

## Concretely

```
$ python -m app.cli episodes create --title "..." --start ... --scope work   # dev/test path
→ WriteReceipt(operation="episodes.write_note", locator=vault://episodes/ep-...)
$ python -m app.cli episodes rebuild-projection   # projection rebuilds from vault, row-for-row
```

## Why This Matters

Every ERE behavior — assignment bounds, closure, re-cut — reads or writes this substrate. If proposal-vs-canonical write classes blur here, segmentation proposals silently gain authority; if the projection is treated as truth, a projection loss corrupts episodes instead of being a rebuild.

## Acceptance Criteria

- [ ] AC1: Episode notes validate against `schemas/episode-note.schema.json`; a note missing `time.closed` or with an unknown `segmentation` value fails. Verify: `tests/episodes/test_episode_note_schema.py::test_episode_note_schema_validates_adr0051_shape`
- [ ] AC2 (enforcement): the episode write path asserts WriteGuard **at the production seam** before any filesystem mutation (guard-at-seam, per #2910 precedent) and returns a `WriteReceipt`. Verify: `tests/episodes/test_episode_store.py::test_episode_write_asserts_guard_at_seam` (blocked-health snapshot → `WritesBlockedError`, no file written)
- [ ] AC3: a proposed episode write produces **no** DecisionToken/AuthorityReceipt (proposal class), and the note lands with `segmentation: proposed`. Verify: `tests/episodes/test_episode_store.py::test_proposed_episode_is_proposal_class_no_authority_receipt`
- [ ] AC4: fused `episode_id` minting cannot collide with a Heimdal per-session `episode_id`; store rejects raw-session-id reuse. Verify: `tests/episodes/test_episode_store.py::test_fused_id_space_disjoint_from_heimdal_session_ids`
- [ ] AC5: projection rebuild from a fixture vault reproduces the projection exactly (drop → rebuild → identical rows); projection is never written except by the projector. Verify: `tests/episodes/test_episode_projection.py::test_projection_rebuilds_from_vault` (pg-marked)
- [ ] AC6: Alembic migration applies + is recorded forward-only, consistent with house migration style. Verify: `tests/episodes/test_episode_projection.py::test_episodes_projection_migration_applies` (pg-marked)

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_episode_note_schema.py tests/episodes/test_episode_store.py
pytest -q -m pg tests/episodes/test_episode_projection.py   # on a pg-capable channel (mac mini)
pytest -q -m "not pg"
```

Laptop has no pg by design — pg-marked ACs execute on the mac mini test channel per house practice; the PR states which gate ran where.

## Out of Scope

Segmentation logic and when episodes get created in production flow (ERE-04); `episode_ref` on other artifacts (ERE-03/ERE-05); closure semantics (ERE-06); re-cut handling (ERE-07).

## Restart / Durability Posture

Episode notes are vault-durable (SoR). The PG projection is rebuildable; losing it loses only query speed, never episodes. No in-memory state survives restart, and nothing user-facing depends on in-memory state.

## Related Docs

- [ADR-0051](../adr/ADR-0051-episode-as-ontological-primitive.md) (OD-1 Artifact, OD-2 note-serialized, §5 proposal class)
- [ADR-0054](../adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) (Mimer placement)
- `app/knowledge/write_ops.py` (guard-at-seam precedent), `app/knowledge/contracts.py::WriteReceipt`
- `docs/testing/invariant-tests.md` §Vault multi-writer (ADR-0055) — episode notes obey the same optimistic-write rules

## Related GitHub Issues

One issue: `[Episode Resolution Engine] episode-note-store: vault-canonical Episode notes + rebuildable projection`. Ready immediately. **Tier 3 flag: ships an Alembic migration** — the PR must declare it.
