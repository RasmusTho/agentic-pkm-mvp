State: SoT v4.10 Reality-MVP (current).
# Data Governance (Reality-MVP)

Lightweight governance for the single-user Reality-MVP. Stores and VaultMirror form the source of truth; heavy SetDB/AMG governance is out of scope for v4.10.

## Truth sources
- Stores: `store_objects`, `store_vector_index`, `store_relations` (memory/pg) hold Core-6 payloads, embeddings, and relations.
- VaultMirror: per-note `uuid.md` under `System/Metadata/VaultMirror/**` mirrors Core-6 and ingest fingerprint; frontmatter in the vault remains human-owned.
- Outbox/audit: ingest/panel/promotion events are written to `INDEX_OUTBOX_PATH` (JSONL) and logs; used for provenance and replay.

## Core-6 (projection)
- `uuid/id`, `title`, `origin` (vault/external), `review_state`, optional `trust`, `source_ref`.
- Stored inside store payloads and VaultMirror; frontmatter only requires `uuid` and human-facing fields.

## Trust & provenance
- Trust values are heuristics (`own|provisional|external|conflict`) proposed by classifiers; humans can override in frontmatter.
- Provenance is maintained via outbox events and VaultMirror logs; panel content is stripped before indexing.

## Promotion / gating
- Reviewer/SetEvaluator/Promotion flows exist but are flag-gated; no automatic auto-promotion in Reality-MVP. Any gating logic should be treated as experimental unless explicitly enabled.

## Idempotency & duplicates
- Ingest uses fingerprints (text SHA + mtime) to skip unchanged notes unless `--force` is set. UUID is the canonical identity; frontmatter wins on conflicts.
- Deduper emits duplicate hints; relations are recorded via RelationIndex when possible. Avoid relying on automatic canonicalization.

## Retention
- Stores persist objects/embeddings/relations in Postgres when `STORE_BACKEND=pg`; memory backend is ephemeral (CI/smoke).
- Outbox JSONL is append-only; rotate per `docs/OPERATIONS.md`. VaultMirror files travel with the vault for provenance.
