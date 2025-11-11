# STATUS — Snapshot (2025-11-08)

**Status:** v4.5 stable — CI green (memory-mode)

## Highlights
- Search flow locked to FT-first hybrid ordering with rerank + guardrails; outputs cite sources + trace IDs.
- Ingest delegation restored end-to-end: CLI → Normalizer → ObjectStore (`emit_outbox=True`) → Index Outbox.
- Smoke CI matches local expectations (`STORE_BACKEND=memory`, `LLM_PROVIDER=mock`, `SKIP_CLASSIFIER_TESTS=1`) and requires no Postgres services.
- Audit logging now buffers JSONL events in memory when Postgres is disabled, keeping traces visible during tests.

## Next focus (Reasoning prep)
- Finish Store contract docs/tests (ObjectStore, VectorIndex, RelationIndex) so Promotion Agent + QA share the same abstractions.
- Wire Indexer agent to consume Outbox events deterministically in memory mode before enabling RDF/OWL reasoning.
- Promotion v2: capture provenance edges + publish intent/done events that the upcoming reasoning layer can validate.

## Known limitations
- Event schemas rely on convention; schema lint is tracked in `docs/ROADMAP.md`.
- Reasoning/RDF exports are drafted but not yet runnable in CI.
