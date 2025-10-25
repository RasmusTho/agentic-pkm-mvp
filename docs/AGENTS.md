# Agents (PER on LangGraph)

All agents implement a minimal PER loop: Plan → Execute → Reflect.
Each node emits a structured payload: {"event": "...", "object_id": "...", ...}

## Normalizer
Input: file_path
Output: objects row with payload.core6 populated
Emits: ingest.normalize.done

## Classifier
Input: object_id
Output: decisions: {"type": "...", "tags": [...], "trust": 0..1}
Emits: curation.classify.done

## Chunker
Input: object_id
Output: chunks rows (stable byte offsets), count
Emits: ingest.chunk.done

## Deduper
Input: [object_id]
Output: decisions duplicate_of {canonical_id, score}, audit marks
Emits: curation.dedupe.done

## CitationChecker
Input: object_id
Output: decisions missing_citations, trust adjustments
Emits: curation.citation_check.done

## Indexer
Input: object_id
Output: embeddings for chunks, bm25 refresh
Emits: ingest.index.done

## Reviewer
Input: object_id
Output: decision promote or feedback with reasons
Emits: curation.review.done

## SetEvaluator
Input: object_id
Output: membership rows per rules
Emits: curation.set_eval.done

## Projector
Input: object_id
Output: file frontmatter update (whitelist only)
Emits: ingest.project.done
