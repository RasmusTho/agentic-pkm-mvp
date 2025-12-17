State: v5.x — Outbox JSONL envelope + event catalog (contract-level).

# Events

This document describes the event artifacts emitted by the system and recorded in the Outbox (JSONL). It defines the canonical envelope and documents the meanings of key event types.

Compatibility and evolution are governed by `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`.

## Outbox envelope (canonical)

All Outbox records MUST include this minimal envelope:

- `event` (`string`): event type, e.g. `ingest.object.created`, `index.embedding.created`.
- `trace_id` (`string`): correlation id for a run/trace.
- `source` (`string`): emitting component identity (stable attribution label).
- `timestamp` (`string`, ISO-8601 UTC): emission time.
- `payload` (`object`): event-specific content.
- `meta` (`object`, optional): non-semantic metadata; when omitted it is treated as `{}`.

Notes:

- Producers MAY add additional top-level fields for compatibility or convenience; consumers MUST ignore unknown fields (see `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`).
- Some older producers emit a richer `source` object (e.g. `{component, trigger, sot}`) instead of a string. That shape is legacy; new producers should emit the canonical `source` string. Consumers should degrade safely by extracting a string attribution (typically `source.component`) when present.

## Embeddings and Outbox

Outbox events MUST NOT carry embedding vectors.

- Embeddings are computed in the indexer stage.
- Events may carry embedding metadata (dimension, model, counts) but not the raw vector payload.

## Event catalog (selected)

### `index.embedding.requested`

Requests that the indexer compute and upsert an embedding for an existing object.

Payload (minimum contract):
- `object_id` (`string`)

This record must not include an embedding vector.

### `index.embedding.created`

Emitted after the indexer computes and upserts an embedding.

Required top-level fields (in addition to the Outbox envelope):
- `uuid` (`string`)
- `metrics` (`object`): includes `vectors`, `dim`, `view`
- `provenance` (`object`): includes `model` and optional versioning

Example:

```json
{
  "event": "index.embedding.created",
  "trace_id": "tr-embed-0001",
  "source": "indexer",
  "timestamp": "2025-11-08T12:00:00Z",
  "payload": {"object_id": "00000000-0000-0000-0000-000000000000"},
  "meta": {},
  "uuid": "00000000-0000-0000-0000-000000000000",
  "metrics": {"vectors": 1, "dim": 1536, "view": "markdown.semantic"},
  "provenance": {"model": "nomic-embed-text:latest", "version": "1.0"}
}
```

### Legacy: `index.object.embedded`

`index.object.embedded` is a legacy alias for `index.embedding.created`.

- Legacy producers sometimes included an `embedding` vector field.
- New producers must not include embedding vectors in outbox events.

### `watcher.run`

Emitted after a watcher tick completes.

Payload (minimum contract):
- `vault_root` (`string`)
- `snapshot_path` (`string`)
- `changed` (`int`)
- `ingest_attempted` (`int`), `ingested` (`int`)
- `panel_candidates` (`int`), `panel_runs` (`int`), `panel_promotions` (`int`)
- `panel_skipped_policy` (`int`), `panel_skipped_limit` (`int`)
- `errors` (`int`)
- `dry_run` (`bool`)
- `limit_exceeded` (`bool`)

### `panel.intent.created`

Emitted when an AI panel is parsed for a note and actions are mapped.

Payload highlights:
- `note.uuid` (required), plus optional `note.path` / `note.origin`
- `panel.panel_id`, `panel.instruction`, optional `panel.raw_block`
- `actions[]`: `id`, `label`, `checked`, optional `mapping` (`intent_type`, `downstream_event`, `params`)

### `panel.intent.executed`

Emitted after the runtime interprets and handles a parsed panel.

Payload highlights:
- `note`, `panel`
- `actions[]`: `id`, `label`, `checked`, `status` (e.g. triggered/logged/skipped), optional `intent_type`, `emitted_events[]`

### `promote.intent.created`

Emitted when a panel action triggers promotion work.

Payload typically includes:
- `note` reference (uuid + optional path)
- `panel` reference
- `action` reference
- `instruction`

## References

- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md` (canonical compatibility anchor)
