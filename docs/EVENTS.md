# Events

All events include: type, attrs, trace_id, ts.

## ingest.normalize.done
attrs: { object_id }

## curation.classify.done
attrs: { object_id, type, tags, trust }

## ingest.chunk.done
attrs: { object_id, chunks }

## curation.dedupe.done
attrs: { pairs: [[a,b,score], ...] }

## curation.citation_check.done
attrs: { object_id, missing: bool }

## ingest.index.done
attrs: { object_id, embeddings }

## curation.review.done
attrs: { object_id, promoted: bool, confidence: float }

## curation.set_eval.done
attrs: { object_id, memberships: [set_id] }

## ingest.project.done
attrs: { object_id, frontmatter_keys: [key] }
