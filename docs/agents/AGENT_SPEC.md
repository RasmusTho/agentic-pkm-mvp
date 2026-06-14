State: Historical (SoT v4.x). Contracts here are not guaranteed to match v5.5; prefer `docs/AGENTS.md` + `docs/EVENTS.md` for current contracts.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Agent-spec (PER + kontrakt)

## Normalizer
Input: path
Output: event `ingest.normalize.done`, `object_id`, `core6` (id,type,title,created,updated,origin)
Writes: `objects` UPSERT, `audit` normalize-event
Idempotens: samma path ⇒ samma id

## Classifier
Input: object_id
Output: `curation.classify.done`, decisions{type, tags, trust}
Writes: `decisions` UPSERT, `audit` metadata.changed

## Chunker
Input: object_id, params{max_tokens, overlap, strategy}
Output: `ingest.chunk.done`, chunks-count
Writes: `chunks` med offsets, `audit`

## Deduper
Input: object_ids
Output: `curation.dedupe.done`, pairs[(a,b,score)]
Writes: `decisions.duplicate_of`, `relations(canonical)`, `audit`

## CitationChecker
Input: object_id
Output: `curation.citation.checked`, missing_citations bool
Writes: `decisions.missing_citations`, `audit`

## Indexer
Input: object_id
Output: `ingest.index.done`, embeddings-count
Writes: pgvector `embeddings`, ev. BM25, `relations`, `audit`

## Reviewer
Input: object_id + rules
Output: `curation.review.passed|blocked|feedback`
Writes: `decisions.maturity`, `audit`

## SetEvaluator
Input: object_id
Output: `curation.sets.updated`
Writes: `membership`, `relations(IN_SET)`, `audit`

## Projector
Input: object_id
Output: `curation.projector.written`
Writes: uppdaterar frontmatter endast för whitelist; Core-6 lämnas orörd.
