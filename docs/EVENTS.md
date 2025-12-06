# EVENTS

## Outbox contract

All events share a minimal envelope:

- `event` (`string`): event name, e.g. `ingest.object.created`, `index.object.embedded`.
- `trace_id` (`string`): correlation id for the run/trace.
- `source` (`string`): emitting component/agent (e.g. `indexer`, `ingest`).
- `timestamp` (`ISO-8601 string, UTC`): emission time; set automatically.
- `payload` (`object`): event-specific data (object_id, path, payloads, etc.).
- `meta` (`object`, optional): free-form metadata (defaults to `{}`).
- Additional legacy fields may be present alongside the envelope (e.g. `object_id`, `topic`) for backward compatibility.

Example (`index.object.embedded` as written by `app.outbox.events.emit_index_object_embedded`):

```json
{
  "event": "index.object.embedded",
  "trace_id": "c41df3e7b7a94f1fbac93f6bafc8bd52",
  "source": "indexer",
  "timestamp": "2025-03-01T12:00:00Z",
  "payload": {
    "object_id": "obj-1",
    "kind": "note",
    "source_ref": "vault/demo.md",
    "payload": {"trace_id": "c41df3e7b7a94f1fbac93f6bafc8bd52"},
    "embedding": [0.1, 0.2],
    "model": "mock-embedding",
    "topic": "index.object.embedded",
    "source": "indexer"
  }
}
```

All emitters must populate the envelope; schema is contract-tested under `tests/architecture/test_events_outbox_contracts.py`.

## Topics in use

### `ingest.object.created`

Minimal payload (fields may extend but these are guaranteed):

```json
{
  "event": "ingest.object.created",
  "uuid": "abc-123",
  "kind": "capture_note",
  "trace_id": "trace-1",
  "instance_id": "home",
  "ts": "2025-11-08T12:00:00Z"
}
```

`instance_id` is the canonical emitter identity in the envelope and comes from settings (`instance.id`), defaulting to `home`.

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
