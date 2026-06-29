State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Current persistence and mirror model for the runtime; explains how Core-6 and derived system artifacts are represented without redefining semantic ownership.
Temporal class: operational
Source of truth: code
Last verified against: app/stores/pg.py (2026-06-30)
# Data Model

The DB is a normalized mirror of the note contract and system overlays. It is not the source of
truth for meaning; notes are the human contract surface and the Core-6 contract is authoritative.
See `docs/CORE_CONTRACT.md`.

Related docs:
- `docs/CORE_CONTRACT.md` for the semantic contract mirrored here
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md` for canonical `review_state` / `maturity` semantics
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` for canonical mirror vs receipt separation
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` for the first-class system artifact used for note
  continuity and repair
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md` for surfaces, authority matrix, and healing order
- `docs/DB_SCHEMA.md` for table-level schema detail
- `docs/FRONTMATTER.md` for writing-surface metadata ownership
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md` for the current recommendation on separating
  human artifacts, projections, review posture, maturity, promotion, and execution plans

## Canonical contract
- Core-6 (uuid, title, origin, source_ref, trust, review_state) is the minimal semantic contract.
- State axes (status, maturity, priority, temporal fields) are policy-selected and may be absent.
- Derived overlays (zone, metrics, embeddings, scores) are system-owned and computed from signals.

Normalization note:
- `review_state` is currently the active review/mutation-posture axis.
- `maturity` is a distinct semantic axis where enabled, even if active runtime paths sometimes
  collapse promotion outcomes into `review_state`.
- legacy payload values such as `review_state: evergreen` should be treated as compatibility data,
  not canonical state-axis truth.
- `kind` is policy routing, not artifact ontology.

## Mirror rules
- Objects in the DB mirror vault notes and external source artifacts; they do not override artifact meaning.
- Missing YAML does not imply missing semantics; Core-6 and state axes may be implicit or derived.
- Zones, metrics, embeddings, and scores are derived and can be rebuilt from the source content.
- Companion notes are part of the file-based continuity set used to rebuild runtime state; DB is not
  the semantic authority from which companion notes are conceptually generated.

Projection clarification:
- a runtime/store row is a projection or record of an artifact,
- not the artifact's full ontology,
- even when the storage layer uses labels such as `kind="note"`.

## Canonical vs derived artifacts

Canonical artifacts are the durable sources of meaning:
- writing artifacts: human-authored, editable notes on the writing surface
- retained artifacts: retained source-rich material that remains retrievable and citable without being forced into the writing surface

Canonical artifacts must remain portable, readable without the system, and carry stable identity plus provenance.

Derived artifacts are rebuildable views:
- indexes, embeddings, projections, caches, summaries, and other machine views
- operational traces such as audit/event records, plus distinct receipt artifacts that may be assembled from those traces for observability and legibility

Derived artifacts may be persisted for performance and auditability, but they must never become the only remaining copy of meaning.

Companion-note clarification:
- companion notes are system artifacts, but they are not merely derived runtime caches
- they are durable file-based continuity artifacts alongside vault notes
- chunks, embeddings, and summaries remain the derivative layer

Execution plans belong to the derived/system side unless and until a separate human project model is
introduced.

## Semantic distinction reminder
- Human-facing artifacts are meaning-bearing and should remain readable as artifacts rather than as mere store rows.
- Commitment structures are a separate semantic class even when the current runtime stores some of their state near notes or artifact projections.
- System and receipt artifacts are accountability or execution surfaces; they may be durable and important without becoming the primary source of human meaning.

## Persistence surfaces

This system persists across three conceptual surfaces:

### Writing surface (human writing)
- canonical, editable notes
- minimal, human-first metadata
- no silent rewriting of meaning; durable changes require explicit review/apply intent

### Retention surface
- canonical retained artifacts intended for retrieval, citation, inspection, and later reuse
- exposure is gated by domain + trust policy

### System plane (operations + audit)
- receipts, audits, traces, and other operational records
- rebuildable indexes and machine views
- configuration artifacts and their validation/audit receipts
- companion notes and related continuity/repair artifacts

This plane may also contain:
- execution artifacts such as generated plans,
- mirror artifacts,
- and low-level event records.

System-plane persistence must avoid polluting the writing surface while remaining inspectable and portable.

## Identity-metadata and bounded history

Identity-related metadata may need bounded history over time.
Examples:
- `uuid` continuity records
- `source_ref` path changes
- title continuity where needed for repair
- ingest-state transitions relevant to continuity/recovery

Forward-line posture:
- SCD-style history applies only to identity-metadata fields
- it does not apply to chunks, embeddings, summaries, or other derived runtime artifacts
- derived runtime artifacts are invalidated and replaced rather than history-versioned as identity records

## Bidirectional recovery

The recovery relationship is bidirectional for resilience:
- vault note + companion note -> rebuild DB/runtime state
- DB/runtime identity metadata -> rebuild missing companion note when available

This does not make DB semantically primary.
It defines a recovery posture for a local-first single-user system.

## Companion note field set

The companion note field set is intentionally bounded and canonically defined in
`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`.

This document depends on that contract rather than redefining the field list here.
Only the persistence and rebuild implications belong in the data-model layer.

## Audit and receipts

Receipts are first-class and must make meaningful system actions reconstructable. At minimum they should show:
- what happened
- which inputs or sources were used
- what boundary context was in effect
- what changed, if anything, and how to reverse it

Receipts may be surfaced through UI affordances, but they must remain available even if the presentation layer changes.

Mirror/receipt clarification:
- mirror projections and receipt artifacts are related but distinct implementation concepts,
- and operational records such as audit rows are not automatically identical to receipt artifacts.

## Tables (current mirror surface)

Interpretation rule:
- table names and storage labels describe the current mirror/runtime surface.
- they do not, by themselves, define the canonical domain vocabulary.

Source-of-truth rule:
- The active runtime store tables below are created by **runtime DDL in `app/stores/pg.py`**
  (`_ensure_tables()`), not by Alembic migrations.
- `app/stores/pg.py` is the canonical shape for these tables; this section mirrors that code and is
  verified against it (see frontmatter `Last verified against`).
- These are still mirror/projection surfaces. Documenting them as canonical store tables does not
  grant the store semantic authority over the note contract or Core-6.

### `store_objects` (canonical)
- `object_id` uuid pk
- `kind` text not null
- `source_ref` text (nullable)
- `payload` jsonb not null
- `created_at` timestamptz not null default now()
- `updated_at` timestamptz not null default now()

The `payload` contains the Core-6 projection plus any policy-enabled state axes and overlays.
In current runtime practice it may also contain execution-state or legacy compressed semantics that
the ontology keeps separate.

Indexed/retrieved unit contract:
- `object_id` is the stable runtime id for the indexed unit; payload mirrors it as `artifact_id`
  and `stable_id` for payload-only consumers.
- `source_ref` is the persisted locator/path; payload mirrors it as `path` and `source_ref`.
- payload must carry `language` (`und` when undetermined), `origin`, `source_role`, `trust`, and
  canonical `review_state`.
- `uuid` from source-note frontmatter is lineage metadata. It improves continuity when present, but
  it is not a render/retrieval gate; uuid-less notes still produce a derived runtime `object_id`.

### `store_vector_index` (canonical)
- `object_id` uuid pk
- `kind` text not null
- `source_ref` text (nullable)
- `payload` jsonb not null
- `embedding` `double precision[]` not null
- `dim` integer not null
- `model` text not null
- `provider` text nullable
- `normalize` boolean nullable
- `updated_at` timestamptz not null default now()

The vector index is a derived runtime artifact. Embeddings are stored as a `double precision[]`
array (not a `vector`-extension column); similarity is computed in application code, and the index
is rebuildable from `store_objects` payloads. Every row is tagged with its generating embedding
identity: `provider`, `model`, `dim`, and `normalize` (older rows may backfill nullable provider /
normalize from `vector_index_meta`). The row payload must preserve the retrieved-unit metadata from
`store_objects` plus `embedding_identity` so retrieval consumers can inspect the evidence unit
without consulting hidden process state.

### `store_relations` (canonical)
- `src_id` uuid not null
- `dst_id` uuid not null
- `rel` text not null
- `payload` jsonb not null default `{}`
- `created_at` timestamptz not null default now()
- `PRIMARY KEY (src_id, dst_id, rel)`

### `store_relation_memberships` (canonical)
- `src_id` uuid not null
- `rel` text not null
- `value` text not null
- `payload` jsonb not null default `{}`
- `created_at` timestamptz not null default now()
- `PRIMARY KEY (src_id, rel, value)`

### `vector_index_meta` (canonical)
- `id` integer pk (`CHECK (id = 1)`; single-row identity record)
- `identity_json` text not null (serialized embedding identity: provider, model, dim, normalize)
- `updated_at` timestamptz not null default now()

This row pins the active embedding identity so the index can detect provider/model/dim drift and
require a rebuild rather than silently mixing dimensions.

## Historical migration lineage (legacy AMG-core)

The tables below are the legacy AMG-core schema created by Alembic migrations under
`app/alembic/versions/`. They are **not** the active runtime store and are retained here only as
historical lineage. The active runtime persistence is the `store_*` set above. Do not treat these
shapes as the current contract.

### `objects` (legacy)
- `id` uuid pk
- `kind` text
- `source_ref` text
- `payload` jsonb
- `created_at` / `updated_at` timestamptz default now()

### `chunks` (legacy)
- `id` uuid pk
- `object_id` uuid fk objects(id) on delete cascade
- `idx` int
- `offset_start` int
- `offset_end` int
- `text` text

### `embeddings` (legacy)
- `id` uuid pk
- `object_id` uuid fk objects(id) on delete cascade
- `model` text
- `dim` int
- `embedding` `double precision[]` (or `vector` in older vector-extension branches)

### `relations` (legacy)
- `id` uuid pk
- `src` uuid
- `dst` uuid
- `kind` text

### `sets` (legacy)
- `id` uuid pk
- `slug` text unique
- `kind` text
- `title` text
- `rules` jsonb

### `membership` (legacy)
- `id` uuid pk
- `set_id` uuid fk sets(id) on delete cascade
- `object_id` uuid fk objects(id) on delete cascade
- `reason` text
- `score` float

### `decisions` (legacy)
- `id` uuid pk
- `object_id` uuid fk objects(id) on delete cascade
- `key` text
- `value` jsonb
- `created_at` timestamptz default now()

These are system-side decision records, not durable proof that the corresponding semantic transition
has been accepted by the human unless an explicit receipt or confirmed mutation also exists.

### `audit` (legacy)
- `id` uuid pk
- `object_id` uuid null
- `agent` text
- `action` text
- `ts` timestamptz default now()
- `trace_id` text
- `details` jsonb

Audit rows are operational records.
They support accountability, but they are not identical to the full concept of a receipt unless the
owning contract says so.
