State: SoT v5.x forward line (on v4.10 base) — connectors, watchers, and inbox contracts aligned with local-first guardrails.

# Cloud connectors decision

## Decision
We standardize on outbound delta-fed connectors with adaptive polling/longpoll (Alternative D below) as the canonical path for SoT cloud connectors. That keeps watchers pulling from remote feeds, honoring the local-first constraint by avoiding default public inbound webhooks, and surfaces the health signals needed to detect silent failures and runaway automation before any promotion or inbox drain runs. Graph sources follow the same delta cursor/backpressure plumbing so their events, PanelAgent triggers, and inbox drains share context with the vault watcher, and the optional HTTP relay spool stays off unless a partner explicitly requests it.

- Delta feeds keep checkpoints, ack tokens, and rate-aware backpressure close to the runtime, so retries remain deterministic even when remote systems change their paths.
- Graph polling/longpoll remains outbound and is treated as yet another delta feed; the same event vocabulary keeps the architecture/event docs aligned with this concept (Connector → Watcher → Inbox → Contract).
- Inbound relay remains optional and locked behind guarded access because it introduces the automation safety hazards we try to avoid.

_Source memo: Swedish decision memo (draft translation) describing this connector path._

## Architecture alternatives

### Alternative A: Graph relay (inbound webhook)
Let Graph push to a public HTTP relay that writes directly into the inbox. The freshness is attractive, but it violates our local-first principle, is harder to harden for idempotent retries, and provides no native backpressure or silent failure signal because we cannot control what retries arrive and when. This pattern is reserved for pre-approved partners with private relays, but it is not the default architecture.

### Alternative B: Graph poll (outbound)
Poll the Graph change API with a cursor and optional longpolling. This adheres to outbound-only constraints, but Graph quotas and occasional duplicate batches force us to keep aggressive backpressure instrumentation on the watcher, and the polling interval is brittle when backlogs grow. We can make this safer, but it ends up looking like the delta feed model in Alternative D, so we treat it as a fallback/compatibility mode.

### Alternative C: Relay spool aggregator
Introduce a local spool that both inbound webhooks and outbound connectors feed into; watchers drain the spool. It centralizes dedup/backpressure logic, but it still requires an inbound surface, adds another sync layer, and complicates checkpointing because the spool state must recur across restarts. We prefer to keep this pattern limited to experimental partners only.

### Alternative D: Incremental delta feed + adaptive polling/longpoll (selected)
This is the chosen default. Remote services expose delta feeds (with cursors, ack tokens, and optional longpoll) and our connectors pull those feeds, adapt the poll cadence to backlog, and keep the checkpoint metadata in the watcher metadata mirror. We combine the delta cursor with local `content_hash_remote` vs `content_hash_local_sha256` comparisons to detect divergence, so each watcher run knows whether a new object genuinely changed. When rate limits bite, the watcher emits backpressure events and speeds up recovery once the backlog shrinks. This outbound-first approach keeps the automation surface narrow while still delivering near-real-time sync.

## Watcher matrix

| Watcher | Connector | Detection / Trigger | Poll cadence | Checkpoint / State | Backpressure / Rate limits | Inbox type | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Vault snapshot watcher | local:vault | Filesystem snapshot diff + metadata mirror journal | ~30 s scheduler + manual snapshot refresh | `snapshot_id` + mirror hash | Max-notes guard (200) + `limit_exceeded` dry-run action | `inbox.local:vault` | Drives `ingest.vault.*` and panel candidate pipeline; enforces frontmatter policy gating. |
| Graph delta poller | external:graph | Outbound delta poll to Graph change API (cursor + longpoll) | Configurable (base 60 s) with jitter/longpoll | `graph_delta_cursor` | Graph QPS quotas, backlog-driven poll interval expansion | `inbox.external:graph` | Backward-compatible fallback for Graph endpoints while staying outbound. |
| Delta feed connector | external:delta | Incremental delta feed handshake with optional longpoll ack/resume | Adaptive (base 30 s, double when idle, accelerate on backlog) | `delta_cursor` + `ack_token` | Adaptive longpoll backpressure + per-run `max_events` gating; watcher emits `connector.backpressure.engaged` | `inbox.external:delta` | Preferred default path; keeps control in the runtime and feeds PanelAgent/promotions with consistent context. |
| Inbound relay spool (optional) | relay:inbound | HTTP posts land in a relay spool (webhook) | Continuous spool drain (throttled by spool health) | `relay_message_id` + spool token | Relay enforces per-sender rate limits; watcher pauses ack when spool health is degraded | `inbox.relay` | Optional partner path; stays behind a guarded firewall and logging policy. |

## Inbox taxonomy

- `inbox.local:vault`: Handles local Obsidian changes, metadata mirror snapshots, and panel-driven promotions. Checkpoints live in `snapshot_id` + mirror hash, and duplicates are deduped via the mirror journal.
- `inbox.external:graph`: Drains Graph delta polls; each entry includes `graph_delta_cursor`, `origin=graph`, and optional `content_hash_remote`. Works with outbound Graph connectors only.
- `inbox.external:delta`: Receives the new delta feed packets. Entries carry `delta_cursor`, `ack_token`, and `backpressure_metadata`, enabling adaptive poll cadence and longpoll ack/resume loops.
- `inbox.relay`: Optional inbound spool populated by partner webhooks. Entries include `relay_message_id`, `source_secret_id`, and a rate-limiting footprint so watchers know when to throttle.

## Action vocabulary

### Minimal stable events (examples)
Example event names follow our `subject.verb.state` style; they are not yet implemented but describe the desired action surface.

| Event (subject.verb.state) | Description | Idempotency / Undo notes |
| --- | --- | --- |
| `connector.delta.poll.detected` | Watcher identifies new delta (Graph or feed) using the current cursor. | Deduplicate by `delta_cursor` + connector ID; detection is idempotent and has no undo. |
| `connector.delta.feed.synced` | Batch of delta records processed and written to the inbox. | Idempotent when keyed by `delta_cursor`/`batch_id`; undo by replaying the previous cursor or marking `sync_state=rollback`. |
| `connector.inbox.enqueue.received` | Connector enqueues a payload in the inbox after decoding the remote delta. | Deduplicate with `inbox_entry_id`; undo by tagging entry as `needs_review` or re-queueing when a downstream failure occurs. |
| `connector.inbox.dequeue.processed` | Downstream consumer (Normalizer/PanelWatcher) finishes processing an inbox entry. | Idempotent via `inbox_entry_id`; undo by re-queueing or marking the entry for manual review. |

## Unified Object Contract tweaks

- Identity vs location: `uuid` remains the stable identity surfaced to Core-6, while `source_ref`, `path`, and `connector.location_uri` capture the mutable location. Connectors must never conflate location with identity when deciding whether to ingest or dedupe.
- `content_hash_remote` vs `content_hash_local_sha256`: Remote connectors write `content_hash_remote` (as provided by the origin). Local watchers compute `content_hash_local_sha256` from the file mirror. Comparing both enables us to detect manual edits, remote drift, or replays without rewriting the entire object block.

## Guardrails

### Automation Safety Hazards

- Autopromotion loops when a watcher reprocesses the same cursor because no dedup or ack occurred; mitigated by pairing cursors with ack tokens and `connector.delta.feed.synced`.
- Silent watchers whose polls stop emitting events; they can leave the automation spine with stale context and no feedback. The health signals below defend against that.
- Secrets exposure from inbound webhooks when we accept unsecured payloads; the inbound relay stays opt-in, uses signed tokens, and is monitored separately.

### Required health signals

- `automation.silent_failure.detected` — emitted when a watcher misses its expected completion events for three consecutive intervals; surfaces a “silent failure” so operators know to restart the connector or adjust network policies.
- `automation.checkpoint.lagging` — emitted when the delta cursor falls behind a configurable window (e.g., 5× the median latency); highlights large backlogs before we retry aggressively.
- `automation.backpressure.engaged` — emitted whenever the watcher throttles its poll cadence or pauses consumption because a rate limit/backlog bound was hit.

## Open questions

- Relay vs polling for Graph: Do we ever let Graph push into our relay spool when the partner cannot expose an outbound delta feed, or do we insist on polling/longpoll for consistency and security?
- Storage of secrets: Where do Graph/delta credentials live? Vault settings/global `secrets` store, a dedicated keystore, or an external secret manager that still satisfies local-first constraints?
- Multi-account scaling: Should each account run its own watcher/inbox pipeline, or can we multiplex the delta feed checkpoints/backpressure by account within a shared runtime without risking cross-account pollution?
