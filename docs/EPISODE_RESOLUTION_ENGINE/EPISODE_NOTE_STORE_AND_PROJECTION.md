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

## Episode note shape (prose mirror of schema)

Machine-readable contract: [`schemas/episode-note.schema.json`](../../schemas/episode-note.schema.json). This section is its prose mirror, in the style of the `docs/architecture/*` contract docs (e.g. `metadata-bundle.md`).

| Family | Fields | Notes |
| --- | --- | --- |
| **identity** | `episode_id` | Fused id, `ep-<uuid>`. A disjoint identifier space from Heimdal's per-capture-session `episode_id` — `app/episodes/ids.py` rejects a fused `episode_id` that is not `ep-`-shaped, and rejects a fused id that echoes one of its own `derived_from` entries. |
| **frame** | `scope`, `title` | The scope this episode is bound to, and a human-legible title. Both required. |
| **temporal (situation-model dim.)** | `time.start`, `time.end`, `time.closed` | Minimal temporal commitment per ADR-0051 §3 item 6. `start` and `closed` are required; `end` is populated on closure. `closed` is load-bearing — it drives event-triggered relevance decay (Event Horizon Model), never a TTL. |
| **space (situation-model dim.)** | `space[]` | Place dimension of the situation model. |
| **protagonist (situation-model dim.)** | `protagonists[]` | Protagonist dimension of the situation model. |
| **goal (situation-model dim.)** | `goal[]` | Goal dimension; binds the episode upward to projects/areas. |
| **causation (situation-model dim.)** | `causation[]` | Causation dimension of the situation model. |
| **nesting** | `parent_episode` | Fused `episode_id` of a nesting parent episode, or `null`. Grain is non-canonical and nested (ADR-0051 §3 item 3). |
| **lifecycle** | `segmentation` | `proposed` \| `accepted` \| `re-cut`. `proposed` is a low-trust opt-out capture proposal carrying no DecisionToken/AuthorityReceipt (ADR-0051 §5); `accepted` is standing reached by silent acceptance; `re-cut` is a human correction (ERE-07). Every value writes through the same guarded seam — none of them passes through governed-write. |
| **provenance** | `derived_from[]` | Source ids this episode fused from — Heimdal per-session `episode_id`s and/or other stream boundary hints. Never equal to this note's own `episode_id`. |

Required top-level fields: `episode_id`, `scope`, `title`, `time`, `segmentation` (`time.start` and `time.closed` are required within `time`). `additionalProperties: false` at both levels — no undeclared field validates.

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
- [ ] AC5: projection rebuild from a fixture vault reproduces the projection exactly (drop → rebuild → identical rows); incremental emit, closure, and re-cut paths keep the rebuildable projection convergent. When redelivery finds a schema-valid vault-canonical note whose earlier best-effort emit sync was missed, the segmentation tick launches a detached supervisor rather than opening a database connection. At a fixed deadline its worker process group receives TERM, then KILL after a bounded reap window, so backend discovery, DNS, connection, and lock stalls cannot delay the tick. Retry, rebuild, and projection doctor share the same raw-frontmatter boundary: `artifact_class` metadata is allowed, while unknown episode fields are skipped. Verify: `tests/episodes/test_episode_projection.py::test_projection_rebuilds_from_vault` (pg-marked), `tests/episodes/test_episode_projection.py::test_raw_frontmatter_validation_allows_renderer_metadata_only`, and `tests/episodes/test_projection_retry.py::test_projection_retry_terminates_a_hung_worker`
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
