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
- `context_dimensions` (`object`, optional): named optional top-level field carrying separated
  scope/sphere/identity dimensions with SSI-01 canonical shape (`scope`, `sphere_memberships`,
  `situated_identity`). Omit entirely when the invocation had no separated-dimension context; do
  not emit an all-null block. Distinct from generic unknown additionals — this field has a defined
  contract. See `docs/SCOPE_SPHERE_SITUATED_IDENTITY/EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md` (SSI-03) for field semantics and guardrail notes.

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
- Dispatch-level infrastructure failures classified by the worker as transient (for example DB,
  network, or provider-throttling outages) keep the original DB outbox row pending for supervised
  retry and do not spend the poison-row dispatch-attempt budget.
- There is no dedicated DLQ service in the active runtime. When retry attempts are exhausted, the
  worker emits `outbox.event.dead_lettered` as a non-retry diagnostic event. When retry enqueueing
  fails before exhaustion, the worker logs the failure and leaves the condition observable through
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

SFC delivery seam: `watcher.run` is the first event path wrapped through the SFC
ReplicationEnvelope contract (`app.sfc.replication_envelope.wrap_as_replication_envelope`,
#2362). The adapter maps the event into a `SourceObservationEvent` and a
`ReplicationEnvelope` carrying node/replica identity placeholders, a stable
idempotency key derived from `event_id`, a replay/backfill cursor, observable
delivery/ack status, and a conflict-classification placeholder staged for GOV/HIX.
Per ADR-0020 the V1 posture is single-authoritative-node / no-op: the seam names
delivery semantics; it does not replicate. See `docs/contracts/REPLICATION_ENVELOPE.md`.

### `outbox.event.dead_lettered`

Emitted by the outbox worker when a transient retryable ingest or panel-scan event reaches the
bounded retry limit and will not be requeued, or when an unclassified poison dispatch failure spends
the configured DB-row dispatch-attempt budget. This is a diagnostic dead-letter signal, not an
automatic replay request, and it must not be consumed as the original event topic. Classified
dispatch-level infrastructure transients do not emit this event; they leave the original DB outbox
row pending for supervised retry.

Shared payload fields:
- `original_topic` (`string`): topic that exhausted retries.
- `original_event_id` (`string`): original event id when available, otherwise empty.
- `reason` (`string`): worker retry reason or dispatch poison marker.

Retry-exhaustion payload fields:
- `note_path` (`string`): note path associated with the failed work.
- `retry_count` (`int`): retry count at exhaustion.

Dispatch-poison payload fields:
- `outbox_id` (`string`): DB outbox row id that exhausted dispatch attempts.
- `attempts` (`int`): DB-row dispatch attempt count at exhaustion.
- `error` (`string`): final handler error string recorded for operator triage.

Operator visibility:
- inspect via `GET /api/events/tail?event_prefix=outbox.event` or `events-doctor` against
  `INDEX_OUTBOX_PATH`.
- the event is emitted separately from the original topic so it does not re-enter the transient
  retry path.

### `panel.intent.created`

Emitted when an AI panel is parsed for a note and actions are mapped.

Payload highlights:
- `note.uuid` (required), plus optional `note.path` / `note.origin`
- `panel.panel_id`, `panel.instruction`, optional `panel.raw_block`
- `actions[]`: `id`, optional `option_id`, `label`, `checked`, optional `mapping` (`intent_type`, `downstream_event`, `params`)

### `panel.intent.executed`

Emitted after the runtime interprets and handles a parsed panel.

Payload highlights:
- `note`, `panel`
- `actions[]`: `id`, `label`, `checked`, `status` (e.g. triggered/logged/skipped), optional `intent_type`, `emitted_events[]`
- `executed_action_ids[]`: stable `ai:id` values recorded for idempotency
- `cognition_mode`: `"rule"` or `"llm"` — top-level mirror of the cognition route used this pass.
- `cognition_metadata`: bounded LLM-route observability (see below). Same shape is mirrored on `panel.log.created` and on `panel.action.logged` receipts.

<!-- panel-agent-cognition-observability-metadata -->
#### PanelAgent cognition observability metadata

Bounded, scalar-only dictionary used to surface the LLM cognition route and fallback path. It is attached to:
- `panel.intent.executed` (`payload.cognition_metadata`)
- `panel.log.created` (`payload.cognition_metadata`)
- `panel.action.logged` receipts with `reason` in {`proposal_offered`, `no_actions_matched`, and other receipt reasons emitted via the runtime path}

Fields (all optional, defaults are empty dict / null):
- `cognition_mode` — `"rule"` or `"llm"`.
- `route` — `"rule"`, `"checkbox"`, or `"freeform"`.
- `provider` / `model` — provider and model identifier from the most recent `ReasoningFacade` telemetry record. `null` when the route did not invoke the facade.
- `fallback_used` (bool), `fallback_reason` (string or `null`) — one of `instruction_hint_fallback`, `llm_error:<ExcType>`, `no_catalog_available`.
- `proposal_candidate_count`, `proposal_accepted_count`, `proposal_rejected_count` — bounded counts of raw LLM-returned candidates and how many mapped to canonical catalog IDs.
- `no_match` (bool) — `true` when the cognition decision produced zero accepted catalog actions; drives the `no_actions_matched` receipt.

Backward compatibility: existing consumers that only read `cognition_mode` continue to work. The metadata dictionary is additive and intentionally bounded — it must not carry prompt bodies, raw LLM output, or secret material. See `docs/PANEL_AGENT.md` for the producer-side contract (#984).

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
- `promotion.transition.applied` = transition-accountability event / interim receipt-supporting
  record for admitted promotion applies

The event stream is not, by itself, the complete receipt model.
It is primarily an operational trace surface that may support later receipt or audit construction.
It is also not identical to the metadata mirror.

Promotion clarification (#1438):
- `PROMOTE_DONE` records execution/result semantics: which note was updated, which resulting
  `maturity` / `review_state` applied, and which source event drove execution.
- `PROMOTION_TRANSITION_APPLIED` records the current transition-accountability semantics:
  `note_uuid`, `note_path`, `transition_family`, `target_maturity`, `authority`, `basis`,
  `outcome`, and `artifact_linkage`.
- Receipt query decision (#1489): the v1 formal promotion receipt model is a typed, read-only
  query/projection over durable receipt-supporting audit records. For successful promotion applies,
  `PROMOTION_TRANSITION_APPLIED` is the receipt-supporting audit source for that query model.
- `PROMOTE_DONE` remains execution/result trace, ObjectStore `payload["promotion"]` remains
  machine-mirror provenance, and neither surface is the final durable/queryable receipt authority.
  Consumers that need promotion receipt posture must use the stable receipt query/projection
  contract instead of treating arbitrary outbox scans or ObjectStore inline metadata as authority.

## Receipt vs Event boundary

Events are operational traces. Receipts are structurally distinct accountability records.

In the governed mutation path (`POST /api/panel/confirm`), `OutboxEvent` and `Receipt` are
produced together but are never interchangeable:

- `OutboxEvent` carries `trace_id`, `event_id`, `source`, and `event` — runtime coordination
  fields. It does NOT carry `action_taken`, `inverse_action`, or `receipt`.
- `Receipt` carries `action_taken`, `outcome`, and `inverse_action` — accountability fields.
  It does NOT carry `trace_id`, `event_id`, or `source`.
- `ConfirmResponse.events_emitted` is a list of event trace names (strings); it is the
  operational trace summary. `ConfirmResponse.receipt` is the accountability record.

For read-only projection paths (orientation, resurfacing, vault browser reads), only
operational traces are emitted; no receipt is returned. Read-only responses must not carry
a top-level `receipt` field.

The authoritative concept contract for this separation lives in
`docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`. The runtime boundary is asserted by
`tests/runtime/test_receipt_event_boundary.py` (issue #1600).

## References

- `docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md` (canonical compatibility anchor)
