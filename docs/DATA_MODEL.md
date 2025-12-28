State: SoT v4.10 (current; aligned with Core-6 vNext).
# Data Model (AMG/SetDB)

The DB is a normalized mirror of the note contract and system overlays. It is not the source of
truth for meaning; notes are the human contract surface and the Core-6 contract is authoritative.
See `docs/CORE_CONTRACT.md`.

## Canonical contract
- Core-6 (uuid, title, origin, source_ref, trust, review_state) is the minimal semantic contract.
- State axes (status, maturity, priority, temporal fields) are policy-selected and may be absent.
- Derived overlays (zone, metrics, embeddings, scores) are system-owned and computed from signals.

## Mirror rules
- Objects in the DB mirror notes and external sources; they do not override note meaning.
- Missing YAML does not imply missing semantics; Core-6 and state axes may be implicit or derived.
- Zones, metrics, embeddings, and scores are derived and can be rebuilt from the source content.

## Tables (vNext mirror surface)

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
