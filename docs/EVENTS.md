State: v5.0 – PanelAgent runtime V1 (panel.intent.executed, promotion fan-out; base remains v4.10).
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

### `panel.intent.created`
- Emitter: PanelAgent runtime (`app/agents/panel_agent/agent.py`) via CLI `panel run --uuid ...`.
- When: after scanning a note’s AI panel(s) and mapping actions to panel action settings.
- Payload highlights:
  - `note.uuid` (+ optional `path`/`origin` from ObjectStore).
  - `panel.panel_id`, `panel.instruction`, optional `panel.raw_block`.
  - `actions[]`: `id` (mapping id or normalized label), `label`, `checked`, `mapping` (intent_type, downstream_event, params) or `null` if unmapped.
  - Envelope includes `version="1.0"` and `source={component:"panel_agent", trigger:"cli", sot:"v5.0-step1"}`.

### `panel.intent.executed`
- Emitter: PanelAgent runtime (post-processing of `panel.intent.created`).
- When: immediately after interpreting a parsed panel; summarizes action outcomes.
- Payload: `{note, panel, actions:[{id,label,checked,status,emitted_events,intent_type}]}`; source trigger is `runtime`, sot `v5.0-runtime1`.

### `panel.action.triggered`
- Emitter: PanelAgent runtime.
- When: a checked action is handled and turned into a downstream intent (e.g. promotion).
- Payload: `{note, panel_id, action:{id,label}, target_event}`.

### `panel.action.logged`
- Emitter: PanelAgent runtime.
- When: a checked action is valid but has no runtime handler yet (v5.x placeholder) or is unmapped.
- Payload: `{note, panel_id, action:{id,label,checked}, reason, mapping?}`.
- `intent_source`: `panel.note` for all panel-derived events (including downstream `promote.intent.created`).
- Receipts: runtime writes a receipt into the in-note AI status callout for each handled action (✅ success, ⚠️ failure, ⏳ pending), keeping the last 20; receipts are user-visible, not separate events.

### `watcher.run`
- Emitters: Runtime Loop CLI (`python -m app.cli runtime-loop`, every tick) and `vault-watcher-run` when the run executes (non-dry-run, not blocked by the max-notes guard).
- Envelope: `version="1.0"`, `timestamp`, `trace_id`, `event_id`, `source={component:"watcher", trigger:"runtime_loop"| "vault_watcher_run", sot:"v5.4"}`.
- Payload: `{changed, ingest_attempted, ingested, panel_candidates, panel_runs, panel_promotions, panel_skipped_policy, panel_skipped_limit, errors, dry_run, limit_exceeded, snapshot_path, vault_root}`.
- Observability: increments `watcher_runs_total/24h` in status counters; payload mirrors the CLI summary for regressions.

### `panel.log.created`
- Emitter: PanelAgent runtime.
- When: after evaluating a panel, as a minimal AI-log marker for humans and monitoring.
- Payload: human-readable log entry `{summary, note, panel_id, actions}`; also mirrored into `panel_logs` on the note’s object payload.

### `promote.intent.created`
- Emitter: PanelAgent runtime (from panel actions with `intent_type: promotion`).
- Payload: `{note, panel, action, instruction, maturity?, origin?, intent_source}` with `source="panel_agent.runtime"`; consumed by promotion flows.

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
### `promote.done`
Emitted by the promotion consumer when a promotion intent has been applied. Payload includes `note_uuid`, `state`, and `source_event` (the originating `promote.intent.created`).

### `promote.error`
Emitted by the promotion consumer when a promotion intent cannot be applied (missing uuid or note not found). Payload includes `reason`, optional `note_uuid`, and `source_event`.
