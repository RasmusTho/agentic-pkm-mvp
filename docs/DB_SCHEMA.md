State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Human-readable snapshot of the current database schema and DB outbox bootstrap; migrations and bootstrap code remain the executable source of truth.
Temporal class: operational
Source of truth: code
Last verified against: app/stores/pg.py + app/alembic/versions/e6c4a2b8d1f3_mvr05a3_store_object_binding_keys.py + app/alembic/versions/f4a05a4b0001_mvr05a4_ingest_projection_binding_keys.py + app/alembic/versions/f7a05a4b0001_seed_membership_prerequisites.py + app/alembic/versions/f5a05a5b0001_mvr05a5_replay_projection_binding_keys.py + app/services/outbox.py + app/workers/outbox_binding_gate.py + app/instance/mvr05_cutover.py + app/alembic/versions/f3a1c9d2e4b7_kernel05_outbox_schema_in_migrations.py + app/heimdal/observation_log.py + app/heimdal/cursor_store.py + app/alembic/versions/8b21e6a1f0c4_heim_observation_log_and_cursor.py + app/services/vault_sync.py + app/alembic/versions/c7f4b1a83d29_mvr05a0_file_state_binding_key.py + app/alembic/versions/d1e8a0c5f37b_mvr05a1_objects_agent_memories_adoption.py + app/db/db.py + tests/architecture/durable_table_classification.json (2026-08-16)

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# DB Schema (Current Reality)

## Source Of Truth
- The **active store** tables (`store_objects`, `store_vector_index`, `store_relations`,
  `store_relation_memberships`, `vector_index_meta`) are **migration-owned** (KERNEL-04, #2766):
  Alembic revision `c2766a04d001` creates them, and `app/stores/pg.py::_ensure_tables()` is
  assert-only outside tests — a Postgres runtime with a missing store table raises with a
  "run migrations" hint instead of creating schema. Test fixtures opt in to create-on-demand via
  `STORE_SCHEMA_AUTOCREATE=1`. Schema parity between the migration and the audited
  `_ensure_tables()` shape is asserted by `tests/migrations/test_store_schema_parity.py`.
- MVR-05A3 revision `e6c4a2b8d1f3` rekeys all five store projections by
  `vault_binding_id` and converts every live canonical-object child reference in the same
  forward-only transaction. The migration derives its effective FK inventory from PostgreSQL,
  preserves FK actions and deferral posture, and refuses any zero/many/cross-binding backfill
  rather than guessing a binding. The historical `membership.set_id` endpoint is converted only
  when its live FK targets `store_objects`; the fresh `sets(id)` FK remains unchanged.
- The **DB outbox** table (canonical queue) is **migration-owned** (KERNEL-05, #2850, follow-up to
  KERNEL-04): Alembic revision `f3a1c9d2e4b7` creates it, and
  `app/services/outbox.py::bootstrap()` is assert-only outside tests — a Postgres runtime with a
  missing outbox table/column raises `OutboxSchemaMissingError` with a "run migrations" hint instead
  of creating schema (the prior silent `except Exception: pass` around `ensure_schema` is gone). Test
  fixtures opt in to create-on-demand via the same `STORE_SCHEMA_AUTOCREATE=1` flag KERNEL-04
  established. Schema parity between the migration and the audited `bootstrap()` shape is asserted by
  `tests/migrations/test_outbox_schema_parity.py`.
- MVR-05A8 (#4582) completes the binding-keyed cutover without another schema revision. Before any
  binding-aware migration or runtime can write, deployment resolves the effective channel Compose
  graph and requires every service to carry a DB role, stops all clients except the unique
  `run_migrations.sh` authority, proves both the host-wide Docker/native inventory and PostgreSQL
  client-session population quiescent, and records `minimumRuntimeSchema: mvr-05` with the
  fence receipt in private instance state. Existing scalar producers remain live through the sole
  `write_outbox_event` compatibility translator: it resolves the configured root to exactly one
  active registry binding, obtains a GOV verdict, and stamps binding id, authorization epoch,
  revision, and root on the envelope, so
  new rows never use the legacy sentinel. The worker admits only its live binding, migrated
  compatibility history, or explicitly-global rows; binding-scoped dispatch, retry/dead-letter
  receipts, and acknowledgement share one per-binding effect lease. A stale binding/revision/root
  remains pending while later global work remains processable and worker readiness reports
  `blocked_pending_mvr06`. The checked-in GOV revocation producer inventory is empty and CI derives
  the matching mutation-seam population from source. This delivery admits no production revocation
  entrypoint or revocation-bearing authority state: a non-empty constructor revocation and
  `set_binding(..., revoked=True)` both fail closed, while revoked-verdict consumer tests use a
  test-only protocol implementation outside `app/`. The canonical non-revoking state and mutation
  definitions are source-pinned, so a future change must first add the sole governed
  ownership-fence/exclusive-lease entrypoint and evolve the inventory gate in the same reviewed
  change; manifest booleans cannot
  self-certify a source path.
- The **entity-review operation journal** table (`entity_review_operations`) is **migration-owned**
  (EROJ-01, #4350): Alembic revision `e7a2b9c4d1f8` creates it, and
  `app/heimdal/entity_review_operation_journal.py::ensure_journal_schema()` is assert-only outside
  tests — a Postgres runtime with the table or a column missing raises
  `EntityReviewOperationSchemaMissingError` with a "run `alembic upgrade head`" hint instead of
  creating schema. Test fixtures opt in to create-on-demand via the same `STORE_SCHEMA_AUTOCREATE=1`
  flag KERNEL-04 established. Schema parity between the migration and the module's audited shape is
  asserted by `tests/migrations/test_entity_review_operation_journal_schema_parity.py`. One row per
  deterministic entity-review merge operation: the row commits **before** the first register note
  effect, its terminal `event_committed` state commits atomically with the operation's
  `heimdal.register.entity.merged` outbox row, and a merge queue entry leaves
  `entities/review.md` `pending` only after a **fresh** connection observes both committed rows
  (INV-EROJ-3; see `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`). Operational coordination
  evidence only — entity notes remain canonical identity truth. Target-evolution lineage recovery
  (EROJ-02) and globally unique split complements (EROJ-03) are not delivered by this table.
- **No durable DDL executes outside the Alembic revision chain** (MVR-05A1, #4560). Until this
  slice, `app/db/db.py::ensure_schema` replayed `app/db/migrations_obsidian.sql` on the first
  `conn_rw()` of **every process**. That file has been deleted, along with its second caller
  `scripts/run_migration.py`; `scripts/run_migrations.sh` (`alembic upgrade head`) is the single
  migration authority, and every runtime container already gates on it. `ensure_schema` now issues
  no statements at all unless the `STORE_SCHEMA_AUTOCREATE=1` test-fixture flag KERNEL-04 (#2766)
  established is set. Even then it declares a table only when that table is
  absent — an existence probe, not `IF NOT EXISTS`, because `CREATE TABLE IF NOT
  EXISTS` no-ops silently on an older shape while the statements after it still
  run against it — and it issues only `CREATE`, never `ALTER` or `DROP`. Guarded by
  `tests/architecture/test_durable_table_ownership.py::test_no_durable_ddl_executes_outside_the_revision_chain`,
  which asserts the behaviour on a recording connection rather than only the file's absence.
- **Every durable table carries a binding classification, and an unclassified durable table fails
  CI** (MVR-05A2, #4576). `tests/architecture/durable_table_classification.json` holds one entry per
  durable table — classification (`binding-scoped` or `explicitly-global`), a written reason, the
  owning Alembic revision, whether the row identity already carries a binding column, every
  `app/**` module that mutates it, and which cutover-escalation conditions it trips. The gate
  `tests/architecture/test_multi_vault_projection_inventory.py` derives the table population from
  `app/alembic/versions/**` and fails on the set difference
  `discovered_durable_tables - classified_tables`, so a table introduced by a revision that does not
  exist today fails CI until a human classifies it. The manifest has no default classification and
  no wildcard entry: `explicitly-global` is a written claim, never a fallback, and the gate proves
  it by removing each entry in turn and asserting the failure lands on exactly that table. The same
  gate fails when a mutation, replacement or `TRUNCATE` path under `app/**` resolves to no
  classified producer entry.
- **`app/stores/pg.py` now has the behavioural proof `app/db/db.py` has had since MVR-05A1**
  (MVR-05A2, #4576). `test_the_store_seam_never_reshapes_a_table_that_already_exists` runs
  `_ensure_tables()` against a recording connection and reads the statements back: without the
  `STORE_SCHEMA_AUTOCREATE` opt-in it issues no schema statement against either an empty or a
  populated database; with the opt-in it creates the five store tables on an empty one; and against
  tables that already exist it issues **zero** schema statements. That last case is the guard. It
  found `_ensure_tables()` running three unconditional
  `ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS` statements in its autocreate branch;
  the branch is now grouped by table behind the same `to_regclass` probe `app/db/db.py` uses.
- **The durable-DDL guard's seam population is derived, not named** (MVR-05A2, #4576). Alongside the
  two behavioural proofs, a derived scan covers every durable DDL statement anywhere under `app/**`
  — the Heimdal bootstrap modules, the entity-review journal, the knowledge-acquisition stores,
  `app/services/outbox.py` — and requires each to be behind the `STORE_SCHEMA_AUTOCREATE`
  test-fixture opt-in, and to target a table the revision chain owns. Its vocabulary covers DDL
  against objects *attached to* a durable table (indexes, triggers, rules) as well as the table
  itself, because an index or trigger dropped and recreated against a migration-owned table is the
  same drop-and-re-add mechanism MVR-05A1 removed from `objects_pkey`.
- **Forty-five attached-object statements across fourteen modules run without an existence probe,
  and are recorded rather than fixed** (MVR-05A2, #4576).
  `tests/architecture/durable_table_classification.py::RECORDED_ATTACHED_DDL_DEBT` pins them by
  (module, verb, table) with a count. **It is a measurement, not a clean bill of health.** Six of
  the fourteen modules issue a `DROP TRIGGER` / `CREATE TRIGGER` pair against a table whose trigger
  a migration already owns — `app/heimdal/raw_read_gate.py`'s own docstring records that
  `f1c7e2a9b4d6` installs an identical reject-mutation trigger. MVR-05A2's acceptance criteria ask
  for the existence probe in exactly one place (`app/stores/pg.py`, delivered), so repairing the
  rest and shrinking that mapping is owned by
  [#4598](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4598). A statement that retires must
  come off the pin; a statement that appears is in neither the pin nor the exclusion and fails the
  guard.
- **`app/db/sql/relations_init.sql` is deleted** (MVR-05A2, #4576). It declared a primary-key-less
  `relations` shape disagreeing with its Alembic owner
  (`202510241200_sot41_amg_core.py`) and had zero readers repo-wide; its absence and the absence of
  any referrer under `app/`, `scripts/` and `.github/` are asserted by
  `tests/architecture/test_multi_vault_projection_inventory.py::test_orphaned_relation_artifacts_are_removed_or_classified`.
  MVR-05A4 (#4578) removes `app/store/relation_index.py` rather than reviving its incompatible
  six-column SQL writer. The retained non-writing `RelationIndex`/edge/slice contract now lives at
  `app/objects/relation_types.py`; `relations` still has no production writer.
- The **vault-sync `file_state`** table is **migration-owned** (MVR-05A0, #4543): Alembic revision
  `c7f4b1a83d29` creates it, adopts a database where the legacy runtime bootstrap already created
  it, and rekeys it from `path` to `(vault_binding_id, path)`.
- Both tables have a **fail-loud preflight** at the vault-sync seam
  (`app/services/vault_sync.py::_prepare`): `app/db/db.py::assert_file_state_schema` and
  `::assert_objects_schema`. A database that never ran the owning revision is rejected with a
  message naming `alembic upgrade head`, before any effect, rather than failing part-way through a
  watcher tick. The `objects` half is new in #4560 and closes something that slice opened: until the
  runtime bootstrap was deleted, a stale `objects` was silently reshaped at process boot, so the
  stale state was survivable; now it is not, so it is refused.
- The **`objects`** table and **`agent_memories`** are **migration-owned** (MVR-05A1, #4560):
  Alembic revision `d1e8a0c5f37b` adopts both, takes over the `source_ref` column, the legacy
  `uuid`→`id` backfill and the two remaining `objects` indexes the bootstrap owned, and rekeys
  `objects` to `(vault_binding_id, id)` with `objects_uuid_idx` scoped to
  `UNIQUE (vault_binding_id, uuid)`. `agent_memories` had **zero** references anywhere in the
  revision chain before this and is adopted verbatim, with no shape change. **`objects.path`** keeps
  its MVR-05A0 owner. Every adopted table now has exactly one production owner and — for the first
  time — is reachable by `alembic upgrade head`.
- The adoption, row-survival, rekey, restart and single-vault-equivalence guards for both revisions
  are `pg`-marked and run in **both** lanes that execute `-m "pg"`: `ci-smoke / index_pg` on the PR
  path, and `integration-nightly / pg-contracts` nightly. Both select files by explicit allow-list
  and `index_pg` is additionally paths-filtered, so
  `tests/architecture/test_durable_table_ownership.py::test_durable_ownership_pg_targets_run_in_both_pg_lanes`
  pins the allow-lists and
  `::test_the_pr_path_pg_lane_is_triggered_by_the_sources_it_guards` pins the paths filter — every
  other lane runs `-m "not pg"`, so an unlisted `pg`-marked test would execute in no CI lane at all.
  Test fixtures opt in to create-on-demand via `STORE_SCHEMA_AUTOCREATE=1`
  (`app/db/db.py::_autocreate_migration_owned_schema`); its shape parity with the revisions,
  adoption idempotency, existing-row survival, and bootstrap-origin/Alembic-origin convergence are
  asserted by `tests/migrations/test_file_state_adoption.py` and
  `tests/migrations/test_objects_adoption.py`.
- The active legacy **`decisions`** writer schema is **migration-owned** (#3488, MVR-05A5):
  Alembic revisions `e1d2c3b4a5f6` and `f5a05a5b0001` carry forward the table's creation,
  compatibility columns, generated UUID default, mandatory `vault_binding_id`, and nullable
  `object_id` / `ON DELETE SET NULL` FK. The neutral database seam
  `app/db/decisions_schema.py::assert_decisions_schema()` is shared by the retained compatibility
  adapter and projection rebuild, and only asserts that shape before either can mutate the
  projection; it directs a stale database to `alembic upgrade head` and never runs runtime DDL.
  The migration proof is
  `tests/migrations/test_decisions_schema_parity.py` and
  `tests/migrations/test_decisions_fk_set_null.py`.
- Alembic migrations under `app/alembic/versions/` define the legacy AMG-core
  (`objects`/`chunks`/`embeddings`/...) lineage; see "Historical migration lineage" below. Most of
  these are historical-only, **but `objects` and `decisions` remain on active compatibility paths**:
  the filesystem watcher maintains `objects` as a continuity mirror while canonical ingest writes
  `store_objects`, and `app/services/decisions.py` reads/writes the rebuildable `decisions`
  projection. `chunks`/`embeddings`/`membership` are still touched by the canonical-source backfill
  job (`app/jobs/backfill.py`) and `app/store/membership_store.py` rather than purely historical.

This document is a human-readable snapshot of what the code creates/uses in the v5.5 baseline. The
runtime store shape is mirrored from `app/stores/pg.py`; if you change the store schema there, update
this doc in the same PR.

Related docs:
- `docs/DATA_MODEL.md` for semantic ownership and persistence-surface meaning
- `docs/EVENTS.md` for the canonical outbox envelope carried in `outbox.payload`
- `docs/OPERATIONS.md` for runtime health checks involving the DB outbox
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` for the file-based continuity artifact related to
  note identity repair
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md` for the current normalization recommendation on
  artifact/projection boundaries and compressed state vocabulary

Interpretation rule:
- schema terms such as `objects`, `kind`, `payload`, and `outbox` describe the current physical
  representation layer.
- they must not be read as the canonical ontology of the domain.
- DB state is rebuildable from vault notes + companion notes; schema descriptions here must not be
  interpreted as making DB semantically primary.

## Identity-metadata history (forward-line direction)

Forward-line documentation now reserves SCD-style history for identity-metadata fields only.

Typical identity-metadata fields:
- `uuid`
- `source_ref`
- bounded title continuity metadata when needed for repair
- continuity-oriented ingest/healing state

Expected physical shape when implemented:
- identity tracking table with `valid_from` / `valid_to`
- one active row per identity-metadata dimension under current validity

Scope limit:
- this SCD-style posture applies only to identity-metadata history
- it does not apply to chunks, embeddings, or summaries

## Derived-layer invalidation rule

Chunks, embeddings, and similar derived runtime artifacts should not use SCD-style history as the
default continuity model.

Instead they are:
- invalidated when source content or model assumptions change,
- replaced/rebuilt,
- and interpreted as derivative runtime state rather than identity ledger rows.

## Core Tables (Store)

The active store tables are migration-owned: created by Alembic revision `c2766a04d001` and
binding-rekeyed by `e6c4a2b8d1f3`
(KERNEL-04, #2766), with `app/stores/pg.py::_ensure_tables()` asserting their presence (and running
the idempotent identity **data** backfill) rather than creating schema outside tests. The shapes
below mirror the migration (verified per the `Last verified against` frontmatter). They remain
mirror/projection surfaces and do not hold semantic authority over the note contract.

### `store_objects`
- `vault_binding_id` (`text`, `NOT NULL`)
- `object_id` (`uuid`, `NOT NULL`)
- `PRIMARY KEY (vault_binding_id, object_id)`; no global one-column unique object-id index
- `kind` (`text`, `NOT NULL`)
- `source_ref` (`text`, nullable)
- `payload` (`jsonb`, `NOT NULL`)
- `created_at` / `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Notes:
  - `kind="note"` is a runtime/storage label and may represent a projection of a vault note rather
    than the full semantic class of the human artifact.
  - The retrieved-unit payload contract requires `artifact_id` / `stable_id`, `path`, `source_ref`,
    `language`, `origin`, `source_role`, `trust`, and canonical `review_state`. These are persisted
    in `payload` because the active table has no separate columns for those semantic projection
    fields beyond `object_id`, `kind`, and `source_ref`.
  - A source note's frontmatter `uuid` is lineage metadata. It may seed continuity, but a missing
    source-note `uuid` must not prevent indexing; runtime identity can be derived and persisted as
    `object_id`.
  - StorePort classification: rebuildable. The current object-store path is resolved through
    `app.stores.resolve_object_store_port`, with recovery posture anchored in vault notes and
    companion-note identity continuity rather than in this table as semantic authority.

### `store_vector_index`
- `vault_binding_id` (`text`, `NOT NULL`)
- `object_id` (`uuid`, `NOT NULL`)
- `PRIMARY KEY (vault_binding_id, object_id)`
- `kind` (`text`, `NOT NULL`)
- `source_ref` (`text`, nullable)
- `payload` (`jsonb`, `NOT NULL`)
- `embedding` (`double precision[]`, `NOT NULL`)
- `dim` (`integer`, `NOT NULL`) — the configured embedding guardrail dimension (`EMBED_DIM`, default `1536` from `DEFAULT_EMBED_DIM`); this is the requested/configured dimension, distinct from `nomic-embed-text`'s native `768`. See `docs/EMBEDDINGS.md`.
- `model` (`text`, `NOT NULL`)
- `provider` (`text`, nullable) — the embedding provider that generated this row's vector (e.g. `ollama`, `gemini`). Added in the EMBEDREL-06 Phase A migration; backfilled from `vector_index_meta` for pre-existing rows.
- `normalize` (`boolean`, nullable) — whether this row's vector was L2-normalized. Added with `provider` in the same migration and backfilled the same way.
- `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Interpretation:
  - the vector index is a derived runtime artifact, rebuildable from `store_objects` payloads
  - embeddings are stored as a `double precision[]` array; there is no `vector`-extension column, and
    the primary key is `(vault_binding_id, object_id)` (one row per whole note per binding) — similarity is computed in
    application code
  - every row carries its full generating embedding identity tuple `(provider, model, dim, normalize)`; the index-level primary identity lives in `vector_index_meta`
  - the row `payload` carries the same retrieved-unit metadata as `store_objects` plus
    `embedding_identity`, so retrieval/ContextPack consumers can inspect stable id, locator,
    language, provenance/source-role, trust/review posture, and embedding identity from the
    retrieved unit
  - **chunk metadata schema v1 (#2323):** `app/ingest/chunk_policy.py::build_chunks` produces
    per-chunk metadata (`chunk_id`, `source_id`, `heading_path`, `char_start`, `char_end`,
    `language`, `provenance`; see `docs/EMBEDDINGS.md :: Oversized input handling` and
    `docs/DATA_MODEL.md :: store_vector_index`) reusing this table — no new chunk store or
    `chunk_id`-keyed table. `chunk_id` is a plain string compatible with
    `IncludedItem.chunk_ids: list[str]`. This does not change the PK or the served unit: rows stay
    keyed by whole-note `object_id` until an explicit, documented chunk-level-serving switch lands
  - an ordinary upsert must match the primary identity; a reconcilable fallback write may record a divergent per-row `provider`/`model`/`normalize` (with the same `dim`), making fallback-written vectors visible and reconcilable (EMBEDREL-06 Phase A, `app/stores/pg.py::PgVectorIndex.upsert`)
  - the `dim` guard is unconditional — a dimension mismatch fails loud and writes no row
  - embeddings do not participate in the identity-history/SCD pattern
  - **transform provenance stamp (KERNEL-06, #2768):** `payload.provenance` carries `{source_ref,
    content_hash, chunk_policy_version, pipeline_version, embedding_identity}`, written in the same
    upsert statement as the vector (never a separate write). `content_hash` is a `sha256` of the
    exact embedded text. Canonical source selection is `content` → `text` → `raw_text`; AI panels
    are stripped to a fixed point once per producer before the provider call, and that exact result
    is used for embedding, hashing, and assignment (not `setdefault`) into the derived row's
    `content`/`text` retrieval aliases. A post-panel remainder containing only whitespace is
    non-indexable: producers do not embed or upsert it and remove any prior derived vector instead.
    A legacy precomputed vector is accepted only when its selected payload text is already canonical
    byte-for-byte. The index doctor's read-only missing-vector and staleness checks use that
    same canonical predicate. `index reconcile` re-embeds only rows that drifted; when a present
    authoritative `store_objects` row has become canonically non-indexable, explicit reconcile
    selects it for purge independently of stored hash or embedding identity, then re-reads and locks
    the source row and conditionally purges only its derived vector in that same transaction. A source
    that became indexable is reclassified and embedded; one that disappeared retains the existing
    vector-payload fallback. Reconcile never mutates the source row.
    A B-tree expression index on `payload->>'content_hash'` (migration `699c97b7c007`) backs the
    staleness scan.

### `store_relations`
- `vault_binding_id` (`text`, `NOT NULL`)
- `src_id` (`uuid`, `NOT NULL`)
- `dst_id` (`uuid`, `NOT NULL`)
- `rel` (`text`, `NOT NULL`)
- `payload` (`jsonb`, `NOT NULL`, default `{}`)
- `created_at` (`timestamptz`, `NOT NULL`, default `now()`)
- `PRIMARY KEY (vault_binding_id, src_id, dst_id, rel)`

### `store_relation_memberships`
- `vault_binding_id` (`text`, `NOT NULL`)
- `src_id` (`uuid`, `NOT NULL`)
- `rel` (`text`, `NOT NULL`)
- `value` (`text`, `NOT NULL`)
- `payload` (`jsonb`, `NOT NULL`, default `{}`)
- `created_at` (`timestamptz`, `NOT NULL`, default `now()`)
- `PRIMARY KEY (vault_binding_id, src_id, rel, value)`

### `vector_index_meta`
- `vault_binding_id` (`text`, `NOT NULL`)
- `id` (`integer`, `CHECK (id = 1)`)
- `PRIMARY KEY (vault_binding_id, id)` — one identity record per binding
- `identity_json` (`text`, `NOT NULL`) — serialized embedding identity (provider, model, dim, normalize)
- `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Interpretation:
  - pins the active embedding identity so the index can detect provider/model/dim drift and require a
    rebuild rather than silently mixing dimensions.

## Historical migration lineage (legacy AMG-core)

The tables below are the legacy AMG-core schema defined by Alembic migrations under
`app/alembic/versions/`. The primary runtime store is the `store_*` set above, but **`objects` and
`decisions` from this set remain on active compatibility paths** (the filesystem watcher maintains
the `objects` continuity mirror; `app/services/decisions.py` reads/writes the `decisions`
projection), and `chunks`/`embeddings`/`membership` are exercised by the canonical-source backfill
job and `membership_store`. The
remaining shapes here are historical lineage. Do not read these shapes as the current contract. Note
there is no `search_vector` column anywhere in the schema (active or legacy).

## #3510 legacy-FK cutover (current reality)

Alembic revision `7e4f2a1c9d30` first moved every inventoried live single-column FK that referenced
`objects.id` to `store_objects.object_id`. MVR-05A3 revision `e6c4a2b8d1f3` converts that effective
inventory to `store_objects(vault_binding_id, object_id)`, preserving its `ON UPDATE`, `ON DELETE`, and deferral
semantics. Before retargeting it transactionally backfills a missing canonical parent from each
retained legacy row and refuses unknown, composite, orphaned, or `objects.uuid`-referencing FKs with
repair-and-rerun guidance; it is forward-only.

`objects` remains a readable continuity and filesystem-watcher mirror. Watcher frontmatter and
`file_state` retain `objects.uuid`, but the watcher resolves a retained `objects.uuid` to its
`objects.id` before writing, updating, or deleting the canonical `store_objects` row. Thus an
historical row whose `id != uuid` has exactly one canonical parent and decision/audit children use
that `id`; fresh canonical-only ingest uses its canonical id directly. Canonical backfill scans
`store_objects`. Store reset takes an explicit binding and deletes only that binding's derived rows
and CASCADE children. Nullable decisions/audit receipts survive parent deletion with only
`object_id = NULL`; their known `vault_binding_id` provenance remains.

### `objects` (legacy, migration-owned since MVR-05A1)

The filesystem-watcher continuity mirror. Canonical ingest writes `store_objects`; this table is
maintained alongside it and is actively written by `app/services/vault_sync.py`.

- `id` (`uuid`, `NOT NULL`, no server default) — in practice the note's artifact UUID: the
  vault-sync producer writes `id = uuid`, and the legacy backfill set `id = uuid` for rows that
  predate the column
- `uuid` (`uuid`, nullable) — the note's frontmatter uuid
- `kind` (`text`, `NOT NULL`)
- `payload` (`json`, `NOT NULL`, default `'{}'::jsonb`) — declared `sa.JSON()` by the historical
  root revision, so the deployed column type really is `json`, not `jsonb`
- `created_at` / `updated_at` (`timestamptz`, nullable, default `now()`)
- `path` (`text`, nullable) — added by Alembic revision `c7f4b1a83d29` (MVR-05A0, #4543); the
  continuity mirror's locator
- `source_ref` (`text`, nullable) — adopted by `d1e8a0c5f37b` (MVR-05A1, #4560)
- `vault_binding_id` (`text`, `NOT NULL`, default `'legacy-compatibility-binding'`) — the same
  stable binding namespace and sentinel `file_state` uses, not a second scheme
- `PRIMARY KEY (vault_binding_id, id)`
- Index: `objects_uuid_idx`, `UNIQUE (vault_binding_id, uuid)`
- Indexes: `objects_created_at_idx` on `(created_at DESC)`, `objects_source_ref_idx` on
  `(source_ref)`, `objects_kind_idx` on `(kind)`, `ix_objects_payload` GIN on `(payload::jsonb)`

Interpretation:

- Until #4560 this table had **two** DDL owners. Alembic created it, and the runtime bootstrap SQL
  re-shaped it on the first `conn_rw()` of every process — including
  `ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey` followed by
  `ADD CONSTRAINT objects_pkey PRIMARY KEY (id)`. Any binding-keyed primary key a migration
  installed was therefore reverted at the next process boot, and on a single-binding instance the
  re-add **succeeded with no error**. Nothing failed; the constraint was simply gone, and only then
  did rows begin overwriting. Superseding those statements was not enough while the file still ran,
  so the file was deleted.
- The key was `PRIMARY KEY (id)` before #4560. Because the producer writes `id = uuid`, that made
  two registered bindings holding the same artifact UUID mutually exclusive — the overwrite
  MVR-05A's AC-1 forbids. No additive column reaches that defect: the key itself was the defect.
- `objects_uuid_idx` was **globally unique on `(uuid)`** on any database whose `objects` was created
  by the bootstrap before Alembic ran, and **non-unique** wherever Alembic created the table first
  (the historical root creates it that way and the bootstrap's `CREATE UNIQUE INDEX IF NOT EXISTS`
  matched on name and silently no-opped). Both converge on `UNIQUE (vault_binding_id, uuid)`:
  uniqueness is scoped to the binding, not removed.
- Rows written before the rekey are attributed to the explicit sentinel
  `legacy-compatibility-binding`, not guessed onto a registry binding. MVR-05A owns the sentinel →
  real-binding backfill and its ambiguity/quarantine rules.
- The migration **refuses** three states rather than damaging data: an inbound foreign key still
  referencing `objects` (the #3510 cutover moves every reviewed consumer to `store_objects`), and
  duplicate `(vault_binding_id, uuid)` rows, which are physically possible on a database whose
  `objects_uuid_idx` was non-unique. `app/objects/identity.py` already refuses to resolve a
  duplicated `objects.uuid`; the migration raises with a reconcile hint instead of deduplicating by
  guess.
- Every `objects` **upsert** in `app/services/vault_sync.py` is binding-scoped, because
  `ON CONFLICT (id)` and `ON CONFLICT (uuid)` no longer match a unique index. The binding comes from
  the same `app/services/vault_sync.py::_binding_id` seam `file_state` uses. The table's UUID-keyed
  `UPDATE`/`SELECT` statements — in `_update_path_only`, `update_path`, `delete_note` and
  `_object_materialization_state` — are **not** yet binding-scoped. That is safe only because
  `_binding_id()` returns a constant, so no shipped code path can produce a second binding value and
  every row carries the same one; it is not safe once MVR-05A (#3859) makes that seam variable, and
  #3859 owns scoping them in the same change. The warning on `_binding_id` states this at the
  source, so the next agent cannot read "one seam to replace" and stop there.
- **Single-vault behaviour is unchanged.** With one binding value in every row,
  `(vault_binding_id, id)` has exactly the uniqueness and upsert semantics `(id)` had
  (`tests/integration/test_single_vault_compatibility.py::test_objects_rekey_preserves_single_vault_behaviour`).
- **A stray single-column unique index on `uuid` *or* `id` is refused too.** The rekey replaces the
  index literally named `objects_uuid_idx`, so one under any other name would survive and silently
  re-impose the global uniqueness AC-1 forbids. Both columns matter, and for the same reason: `id`
  is the second primary-key column — the structural analogue of `file_state`'s `path` — and the
  producer writes `id = uuid`, so one unique row per `id` is one row per artifact UUID across every
  binding. `app/db/sql/objects_uuid_unrestrict.sql` created exactly such an index
  (`objects_uuid_unique_idx`) and had no caller anywhere; #4560 deleted the file, but deleting it
  cannot remove the index from a database where it was ever run, so the migration checks by shape
  rather than by name — the same check `assert_file_state_schema` performs for `file_state`.
- **The read seam has not been cut over.** `app/objects/identity.py` still raises
  `ambiguous retained vault UUID mapping` when one `objects.uuid` resolves to more than one row, so
  the two-binding state this rekey *permits* is not yet one the canonical identity resolver
  tolerates. That cutover is MVR-05A (#3859)'s, together with the producer call sites; #4560
  delivers the schema precondition only.
- **Forward-only, with both rollback outcomes measured.** On a **single-binding** database an older
  image starts and its startup bootstrap silently restores `PRIMARY KEY (id)`; every row survives.
  On a database that already holds **two bindings for one artifact UUID** the old image cannot start
  at all: `conn_rw()` raises `UniqueViolation: could not create unique index "objects_pkey"`, and
  because the bootstrap ran in one transaction the schema is left untouched. In both cases
  `objects_uuid_idx` stays binding-scoped, because `CREATE UNIQUE INDEX IF NOT EXISTS` matches on
  name and never restores a `(uuid)`-only unique index — so the older image's third `objects` upsert
  fallback, `on conflict (uuid)`, raises `InvalidColumnReference`. Its primary `on conflict (id)`
  path works again once the bootstrap has restored the old key, so ingest continues; only that
  fallback is dead. A rollback must therefore be followed by re-running `alembic upgrade head`
  against a post-#4560 image before a second binding is created. Per
  `docs/RELEASE_CHANNELS/README.md :: Rollback posture` this is permitted with operator
  acknowledgement that rollback cannot restore DB shape. MVR-05A (#3859) records the corresponding
  minimum-runtime floor; #4560 deliberately does not.

### `agent_memories` (short-term agent memory, migration-owned since MVR-05A1)

Append-only working memory with timestamp decay, written and read only by `app/memory_kv/store.py`.
Lossy by design: decay is the contract, and the module falls back to an in-process dict when the
table is absent. Before #4560 it was created **only** by the runtime bootstrap SQL, with zero
references anywhere in the Alembic chain — the same condition `file_state` was in before #4543.
Alembic revision `d1e8a0c5f37b` adopts it verbatim; no column, key, or index changed.

- `id` (`uuid`, PK)
- `run_id` (`uuid`, nullable)
- `layer` (`text`, `NOT NULL`)
- `payload` / `provenance` (`jsonb`, `NOT NULL`, default `'{}'::jsonb`)
- `created_at` (`timestamptz`, `NOT NULL`, default `now()`)
- Index: `agent_memories_created_at_idx` on `(created_at DESC)`

### `file_state` (vault-sync bookkeeping, migration-owned since MVR-05A0)

One row per (vault binding, absolute note path). It is what `app/services/vault_sync.py` compares a
filesystem observation against to decide *skip*, *resync*, *rename*, or *delete*, so a lost or
mis-keyed row causes vault content to be silently re-synced or silently skipped rather than failing
loudly. Rebuildable by a full resync, but not disposable.

- `path` (`text`, `NOT NULL`) — the resolved absolute note path
- `uuid` (`text`, nullable) — the note's frontmatter uuid (`objects.uuid` lineage)
- `fm_hash` / `body_hash` (`text`, nullable) — last observed frontmatter/body digests
- `mtime` (`timestamptz`, nullable) — last observed filesystem mtime
- `last_seen` (`timestamptz`, default `now()`)
- `vault_binding_id` (`text`, `NOT NULL`, default `'legacy-compatibility-binding'`) — the stable
  registry binding id (`app/instance/vault_registry.py::VaultRegistration.vault_binding_id`)
- `PRIMARY KEY (vault_binding_id, path)`
- Index: `file_state_uuid_idx` on `(uuid)`

Interpretation:

- The key was `path text PRIMARY KEY` before #4543. That made two registered vault bindings holding
  the same path mutually exclusive — binding B's row silently replaced binding A's — which is the
  overwrite MVR-05A's AC-1 forbids. No additive column reaches that defect, because the key itself
  was the defect.
- Rows written before the rekey are attributed to the explicit sentinel
  `legacy-compatibility-binding`, not guessed onto a registry binding. A pre-MVR-05 database is
  single-binding by construction, so this attribution is provable; MVR-05A owns the sentinel →
  real-binding backfill and its ambiguity/quarantine rules.
- Adoption backfills only rows whose `vault_binding_id` is NULL. A row that somehow already carries a
  real binding id is preserved, not overwritten — but `_binding_id()` returns the sentinel until
  MVR-05A ships the translator, so such a row would not be read and its note would re-sync. Nothing
  writes that column before this revision, so the state is unreachable today; MVR-05A's backfill AC
  owns it.
- Every `file_state` statement in `app/services/vault_sync.py` is binding-scoped, including the two
  formerly UUID-keyed rename deletes (`delete from file_state where uuid = %s and path <> %s`) and
  the delete/last-remaining-path count in `delete_note`, which were only safe while `path` was the
  primary key. `app/services/vault_sync.py::_binding_id` is the single seam that resolves the
  binding; MVR-05A replaces that function rather than re-auditing the SQL.
- **Single-vault behaviour is unchanged.** With one binding value in every row,
  `(vault_binding_id, path)` has exactly the uniqueness, upsert, and delete semantics `(path)` had
  (`tests/integration/test_single_vault_compatibility.py::test_file_state_rekey_preserves_single_vault_sync`).
- **Forward-only.** Measured against a migrated database, an older image's `file_state` **upserts**
  fail loudly (`ON CONFLICT (path)` has no matching unique index, so Postgres raises
  `InvalidColumnReference`), while its reads and its path/uuid deletes still execute and remain
  correct for as long as only one binding exists — the only state an older image can be rolled back
  into, since it cannot create a second binding. A scalar rollback therefore stops vault-sync ingest
  loudly instead of silently mis-keying rows. Per
  `docs/RELEASE_CHANNELS/README.md :: Rollback posture` this is permitted with operator
  acknowledgement that rollback cannot restore DB shape. MVR-05A (#3859) records the corresponding
  minimum-runtime floor; #4543 deliberately does not.

### `chunks` (legacy)
- `vault_binding_id` (`text`, `NOT NULL` after MVR-05A3)
- `id` (`uuid`, PK)
- `UNIQUE (vault_binding_id, id)` (composite inbound-FK endpoint after MVR-05A4)
- `(vault_binding_id, object_id)` (composite FK → `store_objects`, `ON DELETE CASCADE`)
- `idx` (`int`)
- `offset_start` / `offset_end` (`int`)
- `text` (`text`)
- `created_at` (`timestamptz`, default `now()`)

### `embeddings` (legacy, **deprecated — kept, not dropped**)

KERNEL-03 (#2765) caller inventory: the only store-layer code path writing this table
(`app/store/vector_store.py`) had zero callers and was deleted; no writer of `embeddings` remains
anywhere in `app/` (guard:
`tests/architecture/test_single_store_writer.py::test_one_writer_per_table` asserts zero writers).

KERNEL-04 (#2766) decision: the table is **deprecated in this document and NOT dropped**; the
`c2766a04d001` migration intentionally does not touch it, because the zero-**readers**
precondition is not met — one read reference remains (`app/jobs/backfill.py` uses a
`NOT EXISTS (... FROM embeddings ...)` predicate when selecting objects to backfill, and
`view_chunks_missing_embeddings` reads it). The drop is a named follow-up recorded on issue
#2766: remove/replace the backfill read predicate and the view, then drop `embeddings` in its
own forward-only migration.

- `id` (`uuid`, PK; default varies by migration)
- `vault_binding_id` (`text`, `NOT NULL` after MVR-05A3)
- `(vault_binding_id, object_id)` (composite FK → `store_objects`, `ON DELETE CASCADE`)
- `chunk_id` (`uuid`, nullable; composite FK with `vault_binding_id` →
  `chunks(vault_binding_id, id)`, `ON DELETE CASCADE` after MVR-05A4)
- `provider` (`text`, default `mock`)
- `dim` (`int`, default `1536`)
- `embedding` (either `double precision[]` with a cardinality check, or `vector` when vector extension is enabled in older branches)
- `created_at` (`timestamptz`, default `now()`)

### `relations` (legacy, retained projection)
- `id` (`uuid`, PK; globally minted identity retained by MVR-05A4)
- `vault_binding_id` (`text`, `NOT NULL` after MVR-05A3)
- `src_id` / `dst_id` (`uuid`, `NOT NULL`; each forms a composite FK with
  `vault_binding_id` to `store_objects(vault_binding_id, object_id)`, `ON DELETE CASCADE`)
- `type` (`text`, `NOT NULL`)
- `payload` (`jsonb`, `NOT NULL`, default `{}`)
- Binding-aware indexes cover `(vault_binding_id, src_id)` and
  `(vault_binding_id, dst_id)`. There is no production row writer; MVR-05A4
  retired the incompatible `app/store/relation_index.py` SQL seam.

### `decisions` (legacy lineage, active writer schema)
- `id` (`uuid`, PK; default `gen_random_uuid()` after `e1d2c3b4a5f6`)
- `vault_binding_id` (`text`, `NOT NULL` after MVR-05A5; object deletion clears only `object_id`
  and preserves binding provenance)
- `object_id` (`uuid`, nullable; composite FK with `vault_binding_id` → `store_objects`,
  `ON DELETE SET NULL (object_id)` after MVR-05A3, preserving binding provenance; previously
  #3510; the pre-cutover `objects.id` FK was realigned to the `audit.object_id` posture by
  `1a739d9494af_decisions_fk_set_null.py`, #2788; it was
  `ON DELETE CASCADE` and `NOT NULL` before this migration, see D-5/D-7 in
  `docs/architecture/runtime-semantics.md :: Divergences`)
- `agent` (`text`, optional)
- `kind` (`text`, optional)
- `key` (`text`)
- `value` (`jsonb`)
- `created_at` (`timestamptz`, default `now()`)
- Typical indexes:
  - `decisions_object_id_idx`, `decisions_key_idx`
  - `(object_id, key, created_at desc)` for “latest decision” reads

Interpretation:
- rows in `decisions` are operational/system-side decision records.
- they are not automatically equivalent to human-approved commitments or receipts.
- like `audit`, decisions now **survive** object deletion (`object_id` goes `NULL` instead of the
  row being cascade-deleted), so judgment history is not silently lost if object cleanup (owner
  decision D-2 on #2778) ever lands.
- the writer (`app/services/decisions.py::insert_decision`/`latest_decision`) is fail-loud: a
  Postgres-configured-but-unreachable database raises instead of silently falling back to an
  in-process memory store; the memory path is reachable only via an explicit
  `STORE_BACKEND=memory` opt-in (mirrors the KERNEL-03 store-backend contract in
  `app/stores/provider.py::_resolved_backend`).

### `audit` (legacy lineage, active compatibility writer)
- `id` (`uuid`, PK)
- `vault_binding_id` (`text`, nullable only when an already-null object reference had no source)
- `object_id` (`uuid`, nullable; composite FK with `vault_binding_id` → `store_objects`,
  `ON DELETE SET NULL (object_id)` so the audit row keeps binding provenance)
- `agent` / `action` (`text`, `NOT NULL`), `ts` (`timestamptz`), `trace_id` (`text`),
  `details` (`jsonb`)
- `app/services/audit.py` always supplies the compatibility binding. If its first insert finds no
  canonical parent, the fallback preserves the attempted object identifier in
  `details.object_ref`, clears only `object_id`, and retains `vault_binding_id`.

### `membership` (legacy)
MVR-05A4 derives the effective primary-key lineage from the catalog: the fresh
chain uses `(vault_binding_id, id)` while the retained historical chain uses
`(vault_binding_id, object_id, set_id)`. It never infers a key from a later
`CREATE TABLE IF NOT EXISTS` declaration. Unsupported key or inbound-FK state
fails before any schema or row change; it does not re-attribute, quarantine,
copy, or delete rows.
- `vault_binding_id` (`text`, `NOT NULL` after MVR-05A3)
- `(vault_binding_id, object_id)` (composite FK → `store_objects`, `ON DELETE CASCADE`)
- `set_id` (`uuid`, `ON DELETE CASCADE`; fresh lineage keeps its FK to `sets.id`, while #3510
  retargets only retained legacy objects-as-sets schemas; MVR-05A3 makes that historical endpoint
  a composite `store_objects(vault_binding_id, object_id)` FK)
- The projector/backfill producer accepts a set name, resolves it through the retained `sets`
  registry, and writes the resolved UUID. On the historical objects-as-sets lineage that same UUID
  must also exist in binding-scoped `store_objects`. Revision `f7a05a4b0001` seeds the named
  `published` set for both supported lineages and mirrors its resolved UUID into the compatibility
  binding's `store_objects` only on the historical lineage. A later missing registry or endpoint
  row still fails the write with migration guidance instead of fabricating membership.
- `created_at` (`timestamptz`, default `now()`)
- `PRIMARY KEY (vault_binding_id, object_id, set_id)` on the retained lineage

### Views / Helpers (legacy)
- `view_chunks_missing_embeddings`
- `view_objects_ready_for_projection`
- `latest_decision(object_id uuid, key text) -> jsonb`

The retired runtime bootstrap SQL used to `DROP VIEW IF EXISTS` the first two on every process boot,
while Alembic revision `5b8ff54bed0f` originally created them — a third instance of the same
split-ownership pattern. MVR-05A4 revision `f4a05a4b0001` now recreates both retained views during
upgrade, including on a long-running database where the bootstrap had dropped them. Their exposed
column order remains compatible and every chunk/embedding or decision/membership comparison joins
on the same `vault_binding_id`; the guarded test-autocreate path reproduces the same definitions only
when it creates a fresh fixture schema.

## Canonical Queue (DB Outbox)
Migration-owned (KERNEL-05, #2850): Alembic revision `f3a1c9d2e4b7` creates the table exactly as the
audited `app/services/outbox.py::bootstrap()` produced it; `bootstrap()` is assert-only outside tests
(`STORE_SCHEMA_AUTOCREATE=1` opts test fixtures into create-on-demand):
- `outbox`
  - `id` (`uuid`, PK, default `gen_random_uuid()`)
  - `topic` (`text`)
  - `payload` (`jsonb`) (stores the serialized event envelope)
  - `created_at` (`timestamptz`, default `now()`)
  - `delivered_at` (`timestamptz`, nullable)
  - `attempts` (`int`, default `0`)
  - Indexes: `outbox_created_idx`, `outbox_delivered_idx`

Interpretation:
- the outbox is the canonical runtime queue,
- but the event payload is still an operational artifact layer rather than the whole domain model.

### Self-owned write durability policy (`required_db`)

Source: `app/services/outbox.py::_self_owned_outbox_write_policy` (#4064 / #4203 / #4214).

A *self-owned* write is a `write_outbox_event()` / `insert_object_and_outbox()` call that passes no
`conn`. For those calls only, the connection decision is resolved from the environment **before** any
connection is opened, so a memory-backed runtime never triggers a DSN fallback whose DNS resolution
could stall:

| `STORE_BACKEND` | Database named? | `required_db=False` (default) | `required_db=True` |
| --- | --- | --- | --- |
| `memory` | either | skip, return `""` | connect |
| `pg` | either | connect | connect |
| unset | yes | connect | connect |
| unset | no | skip, return `""` | connect |
| any other value | any | `RuntimeError` | `RuntimeError` |

- **"Database named?"** is `app/config/database.py::explicit_runtime_database_url(os.environ)`, the
  same resolution the connection performs (`conn_rw()` -> `_psycopg_dsn()` ->
  `resolve_runtime_database_url(os.environ)`). It is **not** just `DATABASE_URL`/`DB_DSN`: it is any
  key in `RUNTIME_DATABASE_ENV_KEYS` (`DATABASE_URL`, `DB_DSN`, `PKM_DB_NAME_DEV/TEST/PROD`,
  `POSTGRES_USER`, `POSTGRES_PASSWORD`, `PKM_DB_HOST`, `PKM_DB_PORT`). "No" means every input the
  resolver would use is a built-in default, so the DSN it synthesizes is the compose-shaped fallback
  nobody asked for. Reading a narrower key set was #4214 D1: a runtime that named its database
  through `PKM_DB_*`/`POSTGRES_*` connected successfully while the skip predicate called it
  unconfigured and dropped the write.
- `required_db` is keyword-only and defaults to `False`; `insert_object_and_outbox()` forwards it
  unchanged. It is a **caller-resolved durability requirement**, not a runtime probe.
- A skip returns `""` — the same no-insert result already used for a deduplicated event. Only a
  caller that passed `required_db=True` may treat a return from these functions as evidence that the
  DB path actually ran. A caller that must distinguish the two without requiring the DB asks
  `self_owned_write_would_skip(required_db=...)`, which delegates to the same policy.
- An unsupported explicit `STORE_BACKEND` fails loud before any connection attempt, rather than
  degrading to a silent skip.
- A supplied `conn` is authoritative and caller-owned: it bypasses this policy entirely and is never
  closed by the outbox helper.

**Required (DB-durable) producers.** These call sites are load-bearing — a silent skip would let a
projection, receipt, acknowledgement, or HTTP 2xx advance past an event that was never queued — so
they pass `required_db=True` and fail loud instead:

| Producer | Source |
| --- | --- |
| Episode closure (outbox-before-projection boundary) | `app/episodes/closure.py` |
| Promotion receipts | `app/promotion/consumer.py` |
| Embedding requests | `app/outbox/events.py` |
| Explicit panel DB persistence | `app/agents/panel_agent/execution.py` |
| Durable object saves | `app/objects/__init__.py` |
| Worker transient retries | `app/workers/outbox_worker.py` |
| Watcher `panel.scan.requested` / `ingest.vault.changed` (when `db_outbox_required()`) | `app/watcher/registry.py` |
| `POST /ingest` (the route's only persistence side effect) | `app/api/routes/ingest.py` |
| Vault-watcher delete tombstone (`db_outbox_required()` **or** a named database) | `app/watcher/vault_watcher.py` |
| Knowledge-acquisition stage transitions | `app/knowledge_acquisition/stage_events.py` |

Optional, best-effort, and compensated producers keep the default `required_db=False` behavior.

**This table is not the contract — the gate is.** A hand-maintained list can only show that the
producers someone named are classified, never that the set is complete, which is how the `/ingest`
route and the delete tombstone were missed (#4214 D2/D3/D5).
`tests/architecture/test_outbox_producer_durability.py` is the enforcing gate: every self-owned
producer in `app/` must pass `required_db=` or appear on a reviewed allowlist that states why a
silent skip is survivable there (in practice: a compensating JSONL sink that outlives the skip). The
gate also fails on a stale allowlist entry, so exemptions cannot accumulate.

### Watcher required-delivery cursor semantics

Source: `app/watcher/registry.py::_emit_changed_entry` (#4203 / #4214).

`app/watcher/registry.py::db_outbox_required()` is `True` when `WATCHER_REQUIRE_DB_OUTBOX` is set
**or** when `STORE_BACKEND=pg` — the shipped production default (`config/runtime.defaults.env`). It
reads like an opt-in switch; it is not, and production runs with required delivery on.

Scope of the guarantee below: **the emission step only.** Once `_emit_changed_entry` reaches the
emission, the emission and its durable observation cursor are one state transition:

- if the emission raises, the pre-observation `state.files` entry is restored (or removed when the
  file was previously unseen) and the exception propagates, so the next tick re-observes the
  unchanged file instead of treating it as already delivered. The restore is **not** gated on
  `required_db` (#4214 D6): `append_jsonl_outbox_event` is unwrapped, so the non-required path can
  also raise with neither sink written;
- the cursor advances exactly once, after a successful emission; a subsequent tick over the same
  unchanged file emits nothing.

**Known gap this guarantee does NOT cover.** `_emit_changed_entry` advances the `mtime`/`hash` cursor
*before* the debounce/rate-limit check, and that check `return None`s without emitting and without
rolling the cursor back; `_collect_changed_entries` then never re-detects the file. With the shipped
`configs/watchers.yaml` (`rate_limit_per_min: 30`, `debounce_ms: 1500`) a bulk vault change
permanently drops every observation past the limit. This drop is pre-existing and out of scope here —
it is documented rather than claimed away.

### Vault-watcher delete tombstone durability

Source: `app/watcher/vault_watcher.py::_emit_watcher_delete_event` (#4214 D3).

The tick's delete-reconciliation path has no compensating JSONL sink, and its caller both increments
`deleted_purged` and lets `refresh_snapshot()` drop the path from the snapshot. So the false purge is
the only signal anyone would ever get for a tombstone that never landed. Two rules follow.

**The write is required whenever a database is named.** The delete path resolves
`required_db = db_outbox_required() or runtime_database_is_named(os.environ)`. Left optional, the
policy would skip the enqueue under `STORE_BACKEND=memory` even with an explicit DSN and drop the
tombstone with no purge, no error and no message — a silent, permanent loss on a runtime that does
have a durable queue and a durable projection, and a change to the delivery semantics a properly
configured runtime has today. The widening keeps `STORE_BACKEND=pg` and explicit-DSN runtimes exactly
as they are, and makes an unreachable database raise loudly instead of vanishing.

**Only a tombstone that landed is counted.** The emitter reports its outcome explicitly rather than
as a bool — note these are strings, so `"not_queued"` is truthy and callers must compare, never test
truthiness:

- `"emitted"` — the tombstone reached the outbox (or deduped against an identical one); the purge is
  counted;
- `"superseded_by_rename"` — no tombstone is owed, the identity is alive at a path this tick already
  re-ingested;
- `"not_queued"` — the runtime names no database, so the optional write skipped and no event exists.
  The purge is **not** counted.

A required enqueue that raises is caught by the reconciliation loop, counted as an error, and
surfaced as an `unable to reconcile deletion` message.

**Termination policy for an unlanded tombstone.** `vault_sync.delete_note` first applies the same
self-owned connection classification as the outbox policy. An unnamed `STORE_BACKEND=memory` runtime
does not open the synthesized fallback DSN; it returns `False`, so the watcher can resolve the
missing durable queue explicitly. A named database remains required (including an explicit DSN under
the memory backend), so configured-runtime delivery semantics still fail loud rather than silently
skip.

The watcher retries an unreconciled deletion at most **three total observations**. Retryable entries
live in `<snapshot>.unreconciled-deletions.json`, not in the snapshot itself. Every `VaultWatcher`
snapshot writer — including the bare `refresh_snapshot()` callers in the runtime and CLI — merges that
bounded state back before saving, so it cannot be silently erased between ticks. A landed tombstone or
rename removes the entry immediately. On the third unsuccessful observation the entry is removed, the
run records `unreconciled_deletions_terminated=1`, and an operator-visible retry-budget-exhausted
warning is emitted with the normal watcher-run receipt. Thus a permanently absent database has two
bounded retry errors followed by a terminal report, not a permanent per-tick error loop or an
unbounded retention sidecar. Coverage:
`tests/services/test_vault_sync_delete_note_policy.py::test_delete_note_memory_mode_does_not_connect`
and
`tests/watcher/test_vault_watcher_delete_required_outbox.py::test_unreconciled_delete_retries_then_terminates`.

### Producers that read a normal return as a commit

`write_outbox_event` returns `""` for both a skipped write and an ON CONFLICT no-op. A producer whose
idempotency key is derived from stable identity may legitimately read `""` as *proof of a prior
commit* — the Heimdal meeting family does, because treating a dedup as failure would refuse the same
capture forever. That reading is only sound while a normal return cannot mean "skipped", so those
producers guard their DB branch with `self_owned_write_would_skip()` rather than re-deriving a
`STORE_BACKEND`/DSN predicate of their own (#4214). One consequence is explicit: under an explicit
memory backend the DB outbox mirror does not run for them, and their unconditional JSONL append is
the sink of record.

Producers whose key is per-emission (`app/api/routes/capture.py`, `app/panel/confirmation.py`) take
the other correct route — `emitted = emitted or bool(stored_id)` — where a skip simply leaves
`emitted` unchanged.

Contract regression coverage: `tests/services/test_outbox_memory_mode.py`,
`tests/services/test_outbox_required_policy_callers.py`,
`tests/watcher/test_registry_required_outbox.py`,
`tests/watcher/test_vault_watcher_delete_required_outbox.py`,
`tests/api/test_ingest_required_outbox.py`,
`tests/architecture/test_outbox_producer_durability.py`.

## Entity-Review Operation Journal

Migration-owned (EROJ-01, #4350): Alembic revision `e7a2b9c4d1f8` creates the table exactly as the
audited `app/heimdal/entity_review_operation_journal.py` autocreate shape;
`ensure_journal_schema()` is assert-only outside tests (`STORE_SCHEMA_AUTOCREATE=1` opts test
fixtures into create-on-demand):
- `entity_review_operations`
  - `operation_id` (`uuid`, PK) — deterministic over the INV-EROJ-2 tuple (the selection-owned,
    vault-scoped `active_vault_id`,
    queue entry id, decision-list position, SHA-256 digest of the exact human decision mapping,
    original `from_id`, original `into_id`)
  - `vault_identity` (`text`)
  - `queue_entry_id` (`text`)
  - `decision_position` (`integer`)
  - `decision_digest` (`text`)
  - `from_id` / `into_id` (`text`) — the original, immutable human-decided pair
  - `state` (`text`, default `'claimed'`, CHECK `claimed | event_committed | cleared`, monotonic)
  - `outbox_event_id` (`uuid`) — the operation's deterministic merged-event idempotency key
  - `created_at` / `updated_at` (`timestamptz`, default `now()`)
  - Indexes: `entity_review_operations_active_entry_idx` — partial UNIQUE on
    `(vault_identity, queue_entry_id) WHERE state <> 'cleared'`, the fail-closed guard that a
    changed decision mapping cannot mint a colliding second active operation

Interpretation:
- the journal is operational coordination evidence for restart-safe entity-review merges: the row
  commits before the first register note effect, the terminal state commits atomically with the
  `heimdal.register.entity.merged` outbox row, and only a fresh transaction's read of both
  committed rows authorizes clearing the `entities/review.md` `pending` entry (INV-EROJ-3),
- it never decides identity: `_heimdal/register/*.md` notes remain canonical identity truth and
  `entities/review.md` remains the human decision history.

## Heimdal Observation Log (append-only, per-consumer cursor)

Migration-owned (#3039, Epic #3019 slice A2): Alembic revision `8b21e6a1f0c4` creates both tables;
`app/heimdal/observation_log.py`/`app/heimdal/cursor_store.py::_bootstrap_pg()` are assert-only
outside tests (`STORE_SCHEMA_AUTOCREATE=1` opts test fixtures into create-on-demand), mirroring the
KERNEL-04/KERNEL-05 precedent. See `docs/EVENTS.md :: Heimdal observation log` for the full contract.

- `heimdal_observation_log` — the canonical Heimdal <-> Mimer constituent seam; a separate table from
  `outbox`, never a `outbox` topic family.
  - `id` (`uuid`, PK) — the row id is the caller-derived idempotency key (same convention as
    `outbox.id`), not a random default.
  - `topic` (`text`, `NOT NULL`)
  - `payload` (`jsonb`, `NOT NULL`) — the reused outbox envelope (see `docs/EVENTS.md`)
  - `created_at` (`timestamptz`, `NOT NULL`, default `now()`)
  - `sequence` (`bigserial`, `NOT NULL`) — monotone log position; the basis for cursor reads
  - Indexes: `heimdal_observation_log_seq_idx`, `heimdal_observation_log_topic_idx`
  - **No `delivered_at`/`attempts` columns** — unlike `outbox`, this is not a single-consumer work
    queue; every consumer reads the same rows independently via its own cursor.
  - **Append-only enforced by DB trigger** (`heimdal_observation_log_no_update`, HEIM-1): any
    UPDATE or DELETE against this table raises, independent of caller. The Python API also exposes
    no update/delete function.
- `heimdal_observation_cursor` — one row per consumer; consumers never share or affect each other's row.
  - `consumer_id` (`text`, PK)
  - `position` (`bigint`, `NOT NULL`, default `0`) — the next unread `sequence` for this consumer
  - `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)

Interpretation:
- the log is Heimdal's durable evidence stream; it is not authority over knowledge (HEIM-8),
- consumer projections built by replaying the log from a cursor are derived and rebuildable.

## Episode Resolution Engine tick-runtime state

MVR-05A5 revision `f5a05a5b0001` binds all six replay projections. Existing rows are assigned to
`legacy-compatibility-binding` only when that attribution is provably unambiguous; a partially
converted database carrying another binding raises before DDL or row mutation. Every binding
column below is `text NOT NULL`, and test-only `STORE_SCHEMA_AUTOCREATE=1` reproduces the same final shapes:

- `standing_questions`: primary key `(vault_binding_id, question_id)` and unique
  `(vault_binding_id, source_path)`; rebuild deletes and replays one binding.
- `episodes`: primary key `(vault_binding_id, episode_id)`; rebuild and incremental episode writers
  address one binding.
- `episode_engine_state`: primary key `(vault_binding_id, key)`.
- `episode_artifact_binding`: primary key
  `(vault_binding_id, artifact_ref, episode_id)`.
- `decisions`: UUID `id` remains the primary key; `vault_binding_id` is mandatory and rebuild deletes
  and replays only that binding.
- `decision_outcomes`: UUID `id` remains the primary key; uniqueness is
  `(vault_binding_id, decision_uuid, rung_index)`.

The shared `app/db/replay_projection_schema.py` preflight rejects pre-MVR-05A5 key shapes before a
producer mutates them. No replay producer performs a table-wide replacement.

Migration-owned (ERE-04, #3179): Alembic revision `a1b2c3d4e5f6` creates the table and MVR-05A5
rekeys it; `app/episodes/engine_state.py` is assert-only in production (fail-loud
`EngineStateSchemaMissingError` preflight with a migration hint on every query). See
`docs/EVENTS.md :: Secondary per-consumer cursor readers` for the consumer contract.

- `episode_engine_state` — generic key/value state for the segmentation tick
  (`app/episodes/segmenter.py::run_segmentation_tick`).
  - `vault_binding_id` (`text`, first part of PK)
  - `key` (`text`, second part of PK) — namespaced row families:
    - `cursor:vault.activity:<consumer_id>` — the engine's own durable read position over the
      `outbox` table's vault-activity topics (independent of `outbox.delivered_at`, which the
      worker dispatcher owns);
    - `open_segment:<scope>` — one scope's currently-open (not yet proposed) segment state.
    - `calendar_consumed_signal:<len(scope)>:<scope>:<signal_id>` — a closed calendar signal's
      durable fixed-window idempotency boundary. `scope` is length-prefixed netstring-style
      (`app/episodes/segmenter.py::_calendar_consumed_signal_key`) so an embedded `:` in either
      `scope` or `signal_id` cannot shift the key boundary. It prevents a later poll from
      replaying evidence after the originating open segment was deleted; changed calendar
      identities remain distinct.
  - (No `stream_watermark` row family: the quiescence-closure frontier is a per-scope
    read position computed fresh from each tick's own consumed signals, not carried durably.)
  - `value` (`jsonb`, `NOT NULL`)
  - `updated_at` (`timestamptz`, `NOT NULL`, default `now()`)

Interpretation:
- the cursor/open-segment rows are rebuildable tick-runtime bookkeeping; Episode notes in the vault
  remain the source of record (ADR-0051 OD-1/OD-2) and the `episodes` table remains a rebuildable
  projection;
- `calendar_consumed_signal:` is a durable idempotency boundary, not ordinary resettable runtime
  state. Recovery MUST preserve it: there is no supported blanket `episode_engine_state` reset or
  paired cursor reset until an explicit full historical calendar rebuild exists. Clearing it can
  replay stale fixed-window calendar evidence into a later segment (see the migration docstring).

## Episode-artifact binding ledger

Migration-owned (ERE-05, #3180): Alembic revision `b7c8d9e0f1a2` creates the table and MVR-05A5
rekeys it;
`app/episodes/assignment.py` is assert-only (fail-loud `EpisodeAssignmentSchemaMissingError`
preflight with a migration hint on every query that touches `episode_artifact_binding` OR
`episodes`; production remains assert-only). See
`docs/EPISODE_RESOLUTION_ENGINE/ASSIGN_EPISODE_REF_TO_ARTIFACTS.md` for the assignment rule and
write discipline.

- `episode_artifact_binding` — one row per `(vault_binding_id, artifact_ref, episode_id)` tuple: the assignment
  PROVENANCE record (which episode, which rule, basis, confidence, when), not the artifact's own
  bundle.
  - `vault_binding_id` (`text`, first part of PK)
  - `artifact_ref` (`text`, part of PK) — the SAME provenance-ref shape segmentation signals carry
    (`heimdal.observations:<observation_id>` / `vault.activity:<outbox_row_id>`,
    `app/episodes/segmenter.py`), so a binding always resolves back to the exact signal/event that
    earned it.
  - `episode_id` (`text`, part of PK)
  - `scope` (`text`, `NOT NULL`)
  - `basis` (`text`, `NOT NULL`, `CHECK IN ('provenance', 'time_overlap')`) — `provenance`: the
    artifact's `artifact_ref` appears in the episode's own `derived_from` (binding-strength,
    confidence `1.0`); `time_overlap`: bounds-only match (proposed-only, confidence `0.5`) — the
    HEIM-6-honest confidence floor, never a confident claim from a weak correlation.
  - `confidence` (`double precision`, `NOT NULL`)
  - `binding_state` (`text`, `NOT NULL`, default `'active'`, `CHECK IN ('active', 'corrected')`)
  - `rule` (`text`, `NOT NULL`) — the assignment-rule identifier (`ASSIGNMENT_RULE`), so a future
    rule revision is distinguishable from this one in the audit trail.
  - `assigned_at` (`timestamptz`, `NOT NULL`, default `now()`)
  - `corrected_at` (`timestamptz`, nullable) — stamped when a re-cut (ERE-07) invalidates a prior
    `active` binding; the row is flipped to `corrected`, never deleted (provenance survives the
    correction).
  - PRIMARY KEY `(vault_binding_id, artifact_ref, episode_id)` — the idempotency mechanism per binding and (artifact, episode):
    re-ticking the same pair is an UPSERT, never a duplicate row.
  - Indexes: `episode_artifact_binding_episode_idx`, `episode_artifact_binding_scope_idx`,
    `episode_artifact_binding_state_idx`.

Interpretation:
- **rebuildable, never authoritative**: this ledger is the DB-side projection of a derived fact
  (which in-bounds artifacts bind to which episodes) over vault-canonical episode notes +
  segmentation signals; it never emits or requires an `AuthorityReceipt`, and `episode_ref` on the
  artifact's own bundle is `pending` (not authority) until an ERE-07 acceptance/re-cut transition —
  pending-is-not-authority (`docs/architecture/semantic-dimensions.md :: episode_ref`);
- **the ledger row is not the artifact's own bundle**: the actual knowledge-layer write is the
  artifact's `episode_ref` field, upgraded in place on `store_objects`/`store_vector_index.payload`
  (see `## Core Tables (Store)` above — this is the row `app/retrieval/envelope.py` actually reads)
  and, for a vault-serialized artifact, on the note's own frontmatter through the guarded write
  seam (`app.knowledge.write_ops.write_note_from_absolute`, ADR-0055 multi-writer rules). Both are
  union-merges (never overwrite) so a multi-episode (nested) artifact accumulates every binding;
  `app/episodes/assignment.py::commit_assignment_diff` performs both bundle mutations in the SAME
  guarded commit as the ledger write, never touching `evidence_role`/`authority_state`/
  `scope_binding`;
- a `heimdal.observations:<id>`-anchored `artifact_ref` records a ledger row (provenance tracking)
  but does NOT resolve to a bundle today — raw Heimdal observations are never themselves indexed
  into `store_objects`/`store_vector_index` (HEIM-2: Heimdal is forbidden to do assignment, and
  there is no "Heimdal observation's downstream candidate" bundle-minting path yet); this is a
  documented scope boundary, not a silent gap;
- forward-only (no downgrade path — see the migration docstring), same posture as
  `episode_engine_state`/HEIM/ERE-02/ERE-04.

## Explicit Deltas / Known Gaps
- The primary runtime store is the `store_*` set, migration-owned since Alembic revision
  `c2766a04d001` (KERNEL-04; `_ensure_tables()` is assert-only outside tests). The AMG-core tables
  under `app/alembic/versions/` are mostly legacy lineage,
  **except `objects` and `decisions`, which remain on active compatibility paths** (the watcher
  maintains the retained `objects` continuity mirror; `app/services/decisions.py` reads/writes the
  rebuildable `decisions` projection); `chunks`/`embeddings`/`membership` are touched by the
  canonical-source backfill job and `membership_store`. An earlier
  revision of this doc mis-attributed the store tables to Alembic, listed a fabricated `search_vector`
  column, and over-broadly claimed none of the AMG-core tables were active — all corrected here.
- This repo still contains historical migration lineage and merge history under `app/alembic/versions/`. If you hit unexpected columns or migration conflicts, inspect the migration set and record the intended baseline delta in the same change.
- Companion-note and identity-history tables described in forward-line docs may not yet exist in
  the current physical schema; where absent, read them as forward-line schema direction rather than
  as already-shipped baseline tables.
