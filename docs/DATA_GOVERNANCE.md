# DATA GOVERNANCE

## Truth sources
- AMG/SetDB in Postgres is the cognitive source of truth.
- File-frontmatter mirrors only a whitelist via Projector (Core-6 is never mutated).

## Core-6
- id, type, title, created, updated, origin
- Stored in payload->core6 for objects; read-only through Projector.

## Trust & Provenance
- trust: own|provisional|external|conflict
- Provenance is preserved through audit trail and decisions table.
- Normalizer preserves content byte-fidelity; any derived data references object_id + offsets.

## Promotion gates (Reviewer)
- If confidence ≥ 0.7 and no blocking conditions, seed→note auto-promotes.
- Blocking examples: trust in [external, conflict] AND missing_citations=true.
- All gate outcomes are logged to audit with decision rationale.

## Idempotency & Duplicates
- Agents are idempotent. Running the same step twice must not create duplicates.
- Deduper writes decisions(key=duplicate_of) and relations(canonical).

## Audit/Decisions
- audit: event_id, object_id, agent, action, ts, trace_id, details
- decisions: per-object key/value JSON decisions (e.g., type, duplicate_of, missing_citations)

## Retention
- objects/chunks/embeddings are persistent.
- feedback and reviewer outputs are retained for later evaluation.
