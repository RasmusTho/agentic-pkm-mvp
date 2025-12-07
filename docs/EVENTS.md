State: SoT v4.10 Reality-MVP (current core).
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

## Topics in use (Reality-MVP)

Canonical names live in `app/events/types.py`; tests enforce the envelope and type list. Key clusters in v4.10:

- Ingest/index: `ingest.object.created|updated|metadata`, `ingest.normalize.done`, `ingest.chunk.done`, `ingest.index.done`, `index.object.embedded`, `text.chunk.created`.
- Planner/orchestrator/MCP: `planner.plan.created|error|fallback`, `orchestrator.step.started|finished|error`, `mcp.tool.call.started|finished`.
- Agent-to-agent: `agent.request.created`, `agent.response.created`, `agent.error.created`.
- Curation/promotion: `curation.classify.done`, `curation.dedupe.done`, `curation.citation_check.done`, `promotion.*`, `promote.*`, `promotion.pending_move`.
- ASK and jobs: `ask.query.received`, `jobs.backfill.done`, `relation.missing`.

`instance_id` travels via the envelope when provided by emitters (`instance.id`, default `home`).
