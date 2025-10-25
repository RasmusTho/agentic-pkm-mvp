# EVENTS

## Ingest
- ingest.normalize.request
- ingest.normalize.done
- ingest.chunk.request
- ingest.chunk.done
- ingest.index.request
- ingest.index.done

## Curation
- curation.classify.request
- curation.classify.done
- curation.dedupe.request
- curation.dedupe.done
- curation.citation.request
- curation.citation.checked
- curation.review.request
- curation.review.done
- curation.set.eval.request
- curation.set.eval.done

## Projector
- projector.sync.request
- projector.sync.done

## Contract
- Every `.done` carries a minimal contract payload used by downstream steps.
- All events are mirrored into `audit` with `action` equal to event and `details` containing payload diff.
