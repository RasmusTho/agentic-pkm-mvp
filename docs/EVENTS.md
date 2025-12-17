State: v5.x — Outbox JSONL envelope + event catalog (contract-level).

# Events

This document describes the event artifacts emitted by the system and recorded in the Outbox (JSONL). It defines the **canonical envelope** and documents the meanings of key event types.

Compatibility and evolution are governed by `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`.

## Outbox envelope (canonical)

All Outbox records MUST include this minimal envelope:

- `event` (`string`): event type, e.g. `ingest.object.created`, `index.object.embedded`.
- `trace_id` (`string`): correlation id for a run/trace.
- `source` (`string`): emitting component identity (stable attribution label).
- `timestamp` (`string`, ISO-8601 UTC): emission time.
- `payload` (`object`): event-specific content.
- `meta` (`object`, optional): non-semantic metadata; when omitted it is treated as `{}`.

Notes:

- Producers MAY add additional top-level fields for compatibility or convenience; consumers MUST ignore unknown fields (see `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`).
- Some older producers emit a richer `source` object (e.g. `{component, trigger, sot}`) instead of a string. That shape is **legacy**; new producers should emit the canonical `source` string. Consumers should degrade safely by extracting a string attribution (typically `source.component`) when present.

### Example (canonical envelope)

```json
{
  "event": "ingest.object.created",
  "trace_id": "c41df3e7b7a94f1fbac93f6bafc8bd52",
  "source": "ingest",
  "timestamp": "2025-11-08T12:00:00Z",
  "payload": {
    "uuid": "abc-123",
    "kind": "capture_note",
    "source_ref": "vault/Notes/Capture.md"
  },
  "meta": {}
}
```

## Event catalog (selected)

This section documents the meaning and minimal payload shape of commonly used events.

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

Example:

```json
{
  "event": "watcher.run",
  "trace_id": "8f251f2d9a284f94a9d1f8a0f9a5c0d1",
  "source": "watcher",
  "timestamp": "2025-11-08T12:00:00Z",
  "payload": {
    "changed": 3,
    "ingest_attempted": 3,
    "ingested": 3,
    "panel_candidates": 2,
    "panel_runs": 2,
    "panel_promotions": 1,
    "panel_skipped_policy": 0,
    "panel_skipped_limit": 0,
    "errors": 0,
    "dry_run": false,
    "limit_exceeded": false,
    "snapshot_path": "tmp/snapshot.json",
    "vault_root": "vault"
  },
  "meta": {}
}
```

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

### `panel.action.triggered`

Emitted when a checked action is handled and turned into a downstream intent.

### `panel.action.logged`

Emitted when an action is valid but has no runtime handler (or is unmapped) and is recorded for visibility.

### `panel.log.created`

Emitted as a minimal human-facing marker summarizing a panel evaluation.

### `promote.intent.created`

Emitted when a panel action triggers promotion work.

Payload typically includes:
- `note` reference (uuid + optional path)
- `panel` reference
- `action` reference
- `instruction`

### `promote.done` / `promote.error`

Emitted by the promotion consumer when a promotion intent is applied (`promote.done`) or cannot be applied (`promote.error`).

Payload highlights:
- a stable note reference (e.g. `note_uuid`)
- outcome fields (e.g. `state` for done; `reason` for error)
- a reference to the originating intent (e.g. `source_event`)

### `index.object.embedded`

Emitted when an object is embedded and written to the index outbox.

Envelope fields are required. For compatibility, producers may also copy selected payload fields to the top level.

Example:

```json
{
  "event": "index.object.embedded",
  "trace_id": "trace-123",
  "source": "indexer",
  "timestamp": "2025-03-01T12:00:00Z",
  "payload": {
    "object_id": "obj-1",
    "kind": "note",
    "source_ref": "vault/demo.md",
    "embedding": [0.1, 0.2],
    "model": "mock-embedding",
    "topic": "index.object.embedded"
  },
  "meta": {}
}
```

## Legacy notes

### Legacy structured `source` object

Some older producers emit `source` as an object instead of the canonical string form.

This is legacy because it complicates downstream parsing and makes the envelope less uniform. Consumers should degrade safely by extracting a stable string attribution (typically `source.component`).

Example (legacy):

```json
{
  "event": "watcher.run",
  "trace_id": "8f251f2d9a284f94a9d1f8a0f9a5c0d1",
  "source": {"component": "watcher", "trigger": "runtime_loop", "sot": "v5.4"},
  "timestamp": "2025-11-08T12:00:00Z",
  "payload": {"changed": 0, "ingest_attempted": 0, "ingested": 0, "panel_candidates": 0, "panel_runs": 0, "panel_promotions": 0, "panel_skipped_policy": 0, "panel_skipped_limit": 0, "errors": 0, "dry_run": true, "limit_exceeded": false, "snapshot_path": "tmp/snapshot.json", "vault_root": "vault"},
  "meta": {}
}
```

## References

- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md` (canonical compatibility anchor)
