# AGENTS

## Patterns
- All agents expose a simple `run(...) -> dict` and a LangGraph PER wrapper `invoke(...) -> {"output": ...}`.
- Idempotent writes: re-running must not duplicate rows.
- Every agent logs to `audit` with `agent`, `action`, `trace_id`, and `details`.

## Normalizer
- Input: file path
- Output: `{"event":"ingest.normalize.done","object_id", "core6":{id,type,title,created,updated,origin}}`
- Side effects: `objects` upsert, initial `payload` with `core6`, `text`

## Classifier
- Input: `object_id`
- Output: `{"event":"curation.classify.done","type","confidence"}`
- Side effects: `decisions(key="type")`, `audit`

## Chunker
- Input: `object_id`, `max_tokens`, `overlap`, `strategy`
- Output: `{"event":"ingest.chunk.done","chunks":N}`
- Side effects: inserts/updates in `chunks` with offsets into source text

## Deduper
- Input: `[object_id...]`, `threshold`
- Output: `{"event":"curation.dedupe.done","pairs":[(a,b,score),...]}` 
- Side effects: `decisions(key="duplicate_of")`, relations from duplicate→canonical, `audit`

## CitationChecker
- Input: `object_id`
- Output: `{"event":"curation.citation.checked","missing_citations":bool,"trust":"own|provisional|external|conflict"}`
- Side effects: `decisions(key="missing_citations")`, `decisions(key="trust")`, `audit`

## Indexer
- Input: `object_id`
- Output: `{"event":"ingest.index.done","embeddings":N}`
- Side effects: BM25 update and pgvector upsert per chunk, `audit`

## Reviewer
- Input: `object_id`
- Output: `{"event":"curation.review.done","promote":true|false,"reason"}`
- Policy: gate on trust, citation status, confidence thresholds
- Side effects: `decisions(key="promotion")`, `audit`

## SetEvaluator
- Input: `set_id`
- Output: `{"event":"curation.set.eval.done","score","issues":[...]}`

## Projector
- Input: `object_id`
- Output: `{"event":"projector.sync.done","files":[...]}`
- Rule: write-only mirror of whitelisted fields (never mutates DB truth)
