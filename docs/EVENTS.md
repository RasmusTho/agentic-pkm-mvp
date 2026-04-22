State: v5.5 baseline + v5.6 forward line — event envelope + event catalog (contract-level).
Doc role: Core SoT
Authority: Canonical event envelope and event meaning contract for emitted runtime events; authoritative unless superseded by an explicit compatibility contract update.

# Events

This document describes the event artifacts emitted by the system and recorded in the outbox path.
In the active baseline, the DB outbox is canonical and JSONL remains audit/diagnostic only. This document defines the canonical event envelope and the meanings of key event types.

Reading note:
- this document owns the current event contract,
- not the full target-state architecture,
- and not the permanent decomposition of system behavior into event-emitting agents.

Compatibility and evolution are governed by `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`.
Mirror/receipt separation is governed conceptually by `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`.
Receipt/trace/accountability distinctions are clarified in
`docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.

Connector/watcher/inbox action vocabulary and delta feed guardrails are captured in `docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md`, so the event catalog and the new connector terminology stay aligned.

Normalization note:
- events are operational artifacts, not the full ontology of the domain,
- `source` in an event means emitter attribution, not automatically a `Source Artifact`,
- transition families such as review and promotion may require separate intent/execution/receipt
  layers even when the current event catalog is not yet fully normalized.
- event flow remains part of current runtime coordination, but should not by itself be read as the
  architectural center of interaction, cognition, or execution design.


## Outbox envelope (canonical)

All outbox records MUST include this minimal envelope:

- `event` (`string`): event type, e.g. `ingest.object.created`, `index.embedding.created`.
- `event_id` (`string`): unique event identifier used for deduplication and replay safety.
- `trace_id` (`string`): correlation id for a run/trace.
- `source` (`string`): emitting component identity (stable attribution label).
- `timestamp` (`string`, ISO-8601 UTC): emission time.
- `payload` (`object`): event-specific content.
- `meta` (`object`, optional): non-semantic metadata; when omitted it is treated as `{}`.

Notes:

- Producers MAY add additional top-level fields for compatibility or convenience; consumers MUST ignore unknown fields (see `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md`).
- Some producers emit a richer `source` object (e.g. `{component, trigger, sot}`) instead of a string, especially for watcher/panel runtime events. Consumers MUST support both shapes and degrade safely by extracting a string attribution (typically `source.component`) when present. New event producers should prefer a string unless the `component/trigger/sot` trio is required for auditability.
- New or changed event families MUST keep envelope versioning explicit. The active envelope version is
  carried by `version` when a typed event model exposes it, or by `meta.version` for generic
  `OutboxEvent` emitters. Compatibility-only legacy events may omit version only when the owning
  compatibility contract documents the exception.
- Representative CI coverage must include watcher, panel/promotion, orchestrator, and MCP/tool event
  families so envelope regressions fail before runtime rollout.

## Event Idempotency (normative)

- Every event MUST carry a unique `event_id`.
- Consumers MUST deduplicate by `event_id` and treat duplicates as no-ops.
- Producers SHOULD use deterministic `event_id` values for retry safety.
- `watcher.run` and watcher auto-exec events MUST be deduplicated to prevent duplicate panel intents or promotions.

See `docs/CONCURRENCY.md` for the broader concurrency and idempotency guardrails.

## Outbox consumer contract

The DB outbox is the canonical worker queue. JSONL event files are audit/diagnostic surfaces unless
an explicitly configured file-backed worker queue says otherwise.

Current consumer expectations:

- Ordering is FIFO by `created_at` for undelivered DB rows.
- Delivery completion is recorded by `delivered_at`; rows without `delivered_at` remain pending.
- Worker handlers propagate `trace_id` from the event envelope or payload into downstream spans and
  emitted retry events.
- Consumer idempotency is keyed by `event_id`; duplicate event ids are skipped without replaying
  mutation work.
- Transient note-read failures in ingest and panel-scan handlers are requeued with
  `_worker_retry_count`, `_worker_retry_reason`, and `_worker_retry_enqueued_at` metadata up to the
  bounded retry limit.
- There is no dedicated DLQ service in the active runtime. When retry enqueueing fails or retry
  attempts are exhausted, the worker logs the failure and leaves the condition observable through
  worker logs, status/heartbeat signals, and the undelivered DB outbox row.

## Embeddings and Outbox

Outbox events MUST NOT carry embedding vectors.

- Embeddings are computed in the indexer stage.
- Events may carry embedding metadata (dimension, model, counts) but not the raw vector payload.

## Event catalog (selected)

## Interpretation rules

- `object_id` and related fields are runtime/store identifiers unless explicitly qualified as human
  artifact identifiers.
- `note` payload fragments usually point to a vault note reference, not to the entire ontology of an
  artifact.
- `promote.*` and `promotion.*` names currently coexist; read them as belonging to the same broad
  transition family in the current runtime, not as proof of a finalized naming model.

### `index.embedding.requested`

Requests that the indexer compute and upsert an embedding for an existing object.

Payload (minimum contract):
- `object_id` (`string`)

This record must not include an embedding vector.

### `ingest.object.deleted`

Emitted when a vault note path is removed from `file_state` **and** the note UUID has no remaining `file_state` references.

Payload (minimum contract):
- `deleted` (`bool`, must be `true`)
- `path` (`string`, resolved note path)
- `uuid` (`string`)
- optional attribution fields such as `reason` / `source`

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

Current emission note:
- `index.embedding.created` is the current indexer event.
- `index.object.embedded` is a legacy alias kept only for compatibility with older consumers.
- Producers must not include embedding vectors in outbox events.

### `watcher.run`

Emitted after a watcher tick completes.
The registry watcher appends `watcher.run` audit events with `source.trigger=registry:<watcher_name>` so status can count runtime ticks; the legacy snapshot watcher still emits the same event with `source.trigger=vault_watcher_run`. Registry watcher health is also tracked through heartbeat and tick signals surfaced via health/status.

Payload (minimum contract):
- `vault_root` (`string`)
- `snapshot_path` (`string`; empty for registry watcher ticks that do not use a snapshot file)
- `changed` (`int`)
- `ingest_attempted` (`int`), `ingested` (`int`)
- `panel_candidates` (`int`), `panel_runs` (`int`), `panel_promotions` (`int`)
- `panel_skipped_policy` (`int`), `panel_skipped_limit` (`int`)
- `panel_skipped_auto_exec` (`int`)
- `panel_skipped_allowed_actions` (`int`)
- `skipped_dedup` (`int`)
- `skipped_idempotent` (`int`)
- `skipped_writes_blocked` (`int`)
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
- `executed_action_ids[]`: stable `ai:id` values recorded for idempotency

### `promote.intent.created`

Emitted when a panel action triggers promotion work.

Payload typically includes:
- `note` reference (uuid + optional path)
- `panel` reference
- `action` reference
- `instruction`

Interpretation:
- this is an intent event,
- not the promotion transition itself,
- and not a human-legible receipt.

## Event-family normalization guidance

The active runtime still mixes:
- transition-family names (`promotion.*`)
- imperative/process names (`promote.*`)
- and state-mutation consequences carried elsewhere in runtime data.

Until a later migration normalizes event names, interpret them through these layers:
1. intent event
2. execution/result event
3. receipt/accountability artifact

Examples in the current runtime:
- `panel.intent.created` = intent-creation layer
- `promote.intent.created` = transition intent layer
- `promote.done` / `promote.error` = execution-result layer
- `promotion.transition.applied` = human-legible transition receipt layer for admitted promotion applies

The event stream is not, by itself, the complete receipt model.
It is primarily an operational trace surface that may support later receipt or audit construction.
It is also not identical to the metadata mirror.

## References

- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md` (canonical compatibility anchor)
