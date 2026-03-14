State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Current persistence and mirror model for the runtime; explains how Core-6 and derived system artifacts are represented without redefining semantic ownership.
# Data Model

The DB is a normalized mirror of the note contract and system overlays. It is not the source of
truth for meaning; notes are the human contract surface and the Core-6 contract is authoritative.
See `docs/CORE_CONTRACT.md`.

Related docs:
- `docs/CORE_CONTRACT.md` for the semantic contract mirrored here
- `docs/DB_SCHEMA.md` for table-level schema detail
- `docs/FRONTMATTER.md` for warm-surface metadata ownership

## Canonical contract
- Core-6 (uuid, title, origin, source_ref, trust, review_state) is the minimal semantic contract.
- State axes (status, maturity, priority, temporal fields) are policy-selected and may be absent.
- Derived overlays (zone, metrics, embeddings, scores) are system-owned and computed from signals.

## Mirror rules
- Objects in the DB mirror notes and external sources; they do not override note meaning.
- Missing YAML does not imply missing semantics; Core-6 and state axes may be implicit or derived.
- Zones, metrics, embeddings, and scores are derived and can be rebuilt from the source content.

## Canonical vs derived artifacts

Canonical artifacts are the durable sources of meaning:
- warm artifacts: human-authored, editable notes on the writing surface
- cold artifacts: archived source material that remains retrievable and citable without being forced into the writing surface

Canonical artifacts must remain portable, readable without the system, and carry stable identity plus provenance.

Derived artifacts are rebuildable views:
- indexes, embeddings, projections, caches, summaries, and other machine views
- operational traces, receipts, and audit records retained for observability and legibility

Derived artifacts may be persisted for performance and auditability, but they must never become the only remaining copy of meaning.

## Persistence surfaces

This system persists across three conceptual surfaces:

### Warm surface (human writing)
- canonical, editable notes
- minimal, human-first metadata
- no silent rewriting of meaning; durable changes require explicit review/apply intent

### Cold surface (archive brain)
- canonical source artifacts intended for retrieval and citation
- exposure is gated by domain + trust policy

### System plane (operations + audit)
- receipts, audits, traces, and other operational records
- rebuildable indexes and machine views
- configuration artifacts and their validation/audit receipts

System-plane persistence must avoid polluting the warm writing surface while remaining inspectable and portable.

## Audit and receipts

Receipts are first-class and must make meaningful system actions reconstructable. At minimum they should show:
- what happened
- which inputs or sources were used
- what boundary context was in effect
- what changed, if anything, and how to reverse it

Receipts may be surfaced through UI affordances, but they must remain available even if the presentation layer changes.

## Tables (current mirror surface)

### objects
- `id` uuid pk
- `kind` text
- `source_ref` text
- `ts` timestamptz default now()
- `payload` jsonb
- `search_vector` tsvector generated

The `payload` contains the Core-6 projection plus any policy-enabled state axes and overlays.

### chunks
- `id` uuid pk
- `object_id` uuid fk objects(id) on delete cascade
- `idx` int
- `offset_start` int
- `offset_end` int
- `text` text

### embeddings
- `id` uuid pk
- `object_id` uuid fk objects(id) on delete cascade
- `model` text
- `dim` int
- `vec` vector

### relations
- `id` uuid pk
- `src` uuid
- `dst` uuid
- `kind` text

### sets
- `id` uuid pk
- `slug` text unique
- `kind` text
- `title` text
- `rules` jsonb

### membership
- `id` uuid pk
- `set_id` uuid fk sets(id) on delete cascade
- `object_id` uuid fk objects(id) on delete cascade
- `reason` text
- `score` float

### decisions
- `id` uuid pk
- `object_id` uuid fk objects(id) on delete cascade
- `key` text
- `value` jsonb
- `created_at` timestamptz default now()

### audit
- `id` uuid pk
- `object_id` uuid null
- `agent` text
- `action` text
- `ts` timestamptz default now()
- `trace_id` text
- `details` jsonb
