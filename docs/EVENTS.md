# EVENTS

## Outbox contract

| Column       | Type        | Semantics                                       |
|--------------|-------------|-------------------------------------------------|
| `id`         | `uuid`      | Message identifier referenced by `ack_outbox`. |
| `topic`      | `text`      | Event topic (e.g. `ingest.object.created`).     |
| `payload`    | `jsonb`     | Event body written by Stores/agents.           |
| `created_at` | `timestamptz` | Enqueue timestamp (UTC).                     |
| `delivered_at` | `timestamptz NULL` | Set when acked; `NULL` means pending. |
| `attempts`   | `int`       | Optional retry counter (worker maintained).    |

- `write_outbox_event(conn, topic, payload)` inserts the tuple `(id, topic, payload, created_at)` and opens/closes its own connection if `conn` is `None`.
- `poll_outbox_one(conn, handler) -> bool` invokes `handler(topic, payload)` whenever a message is available and returns `True` only in that case.
- `ack_outbox(msg_id, [conn]) -> bool` sets `delivered_at`, is idempotent (multiple calls are safe), and accepts an optional connection argument. Workers should `ack` even when handlers are re-entrant to avoid duplicates.

## Topics in use

### `ingest.object.created`

Minimal payload (fields may extend but these are guaranteed):

```json
{
  "event": "ingest.object.created",
  "uuid": "abc-123",
  "kind": "capture_note",
  "trace_id": "trace-1",
  "ts": "2025-11-08T12:00:00Z"
}
```

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
