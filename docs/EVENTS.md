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
- `meta` (`object`, optional): non-semantic metadata; when omitted it is treated as `{}`. For DB
  outbox rows, `meta.payload_schema` (KERNEL-08, #2770) is the registry schema tag — see
  [Event Topic Schema Registry](#event-topic-schema-registry-normative) below.
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
- Every DB outbox insert MUST carry a deterministic idempotency key (KERNEL-02, #2764):
  `app/services/outbox.py::write_outbox_event` requires `idempotency_key` (a keyless call is a
  `TypeError`), the key becomes the row `id` with `ON CONFLICT (id) DO NOTHING`, and producers MUST
  derive it through the single shared helper
  `app/services/outbox.py::derive_idempotency_key(topic, source_id, content_fingerprint)`
  (`uuid5(namespace, sha256(topic ‖ source_id ‖ fingerprint))`). Ad-hoc key schemes are forbidden;
  `tests/architecture/test_outbox_producer_idempotency.py` gates every callsite.
- Per-topic fingerprints are chosen deliberately: vault-sync and watcher ingest events key on
  `(topic, object uuid/path, content fingerprint + observation marker)`, where the observation
  marker is the observed file stat mtime (vault-sync passes it as a fingerprint-only component; the
  watcher payload already embeds it). The API `/ingest` route embeds `content` in its payload and
  `object_store.save_object` keys on the durable payload's content fingerprint (#2863), so both emit
  on a content change; neither carries a file-observation marker, so a byte-identical A→B→A revert
  dedups — an accepted limitation on the API push path (decided #2902): no natural per-observation
  marker exists (an API push has no file stat mtime), and a caller-supplied idempotency token is
  rejected as an external-API footgun (a naive client sending a per-request UUID would defeat
  crash-retry dedup entirely, reintroducing the at-least-once bug KERNEL-02 kills). Residual revert
  divergence is reconcilable via the incremental reconcile / doctor staleness path (#2880); the full
  rationale lives in
  `docs/RUNTIME_CORRECTNESS_KERNEL/MANDATORY_OUTBOX_IDEMPOTENCY.md :: Known deferrals (tracked)`.
  The dedup scope is the SAME OBSERVATION — a crash/retry
  re-emission re-derives the identical key and dedups — never all-time content recurrence: outbox
  rows are not purged, so a bare content key would silently swallow an A→B→A content revert against
  the original A row while the object/file_state write still commits (over-dedup = silent projection
  divergence, worse than duplicates). Suppressing no-op emissions (pure metadata touch) is the
  upstream change detectors' job (content-hash comparison in vault-sync and the watcher scanner);
  after a watcher restart a touch may over-emit one content-identical event — the safe failure
  direction, since handlers are idempotent. Watcher-run audit events key on
  `(topic, relative path, run-window mtime+hash)`; worker retry/dead-letter events key
  on `(topic, original event/outbox id, attempt)` so intentional re-emissions are NOT swallowed;
  event-scoped emissions (panel projections, capture receipts, index-embedding requests) key on
  their `event_id`. Honest scope of `event_id` keying: it dedups only a double-insert of the same
  constructed event (producer retry after partial failure), not a logical re-emission that rebuilds
  the event — logical replay dedup requires a content-derived fingerprint, adopted per-topic as
  semantics allow.
- The worker's in-memory `_EventDedup` cache remains a fast-path optimization only; it is no longer
  load-bearing for duplicate suppression.
- `watcher.run` and watcher auto-exec events MUST be deduplicated to prevent duplicate panel intents or promotions.

See `docs/CONCURRENCY.md` for the broader concurrency and idempotency guardrails.

## Event Topic Schema Registry (normative)

Every topic dispatched by `app/workers/outbox_worker.py::_dispatch_topic` has a versioned per-topic
JSON Schema (KERNEL-08, #2770): `schemas/events/<topic>.v1.schema.json`. Today: `ingest.object.created`,
`ingest.vault.changed`, `ingest.object.deleted`, `panel.scan.requested`, `promote.intent.created`,
`note.move.workbench`, `index.embedding.requested`. Coverage is enforced dynamically —
`tests/events/test_topic_schema_registry.py::test_every_dispatched_topic_has_schema` enumerates the
live dispatch table via its AST and fails on any gap, so a newly dispatched topic without a schema
cannot ship silently.

- **Validation at write**: `app/services/outbox.py::write_outbox_event` validates the payload against
  its topic's registered schema before the DB insert (`app.events.topic_schema_registry`) and stamps
  `meta.payload_schema = "<topic>.v1"` on success. A violation raises
  `app.events.topic_schema_registry.TopicSchemaViolation` — the write does not happen.
- **Validation at dispatch**: `_dispatch_topic` validates again before invoking the real topic
  handler. An invalid payload against a registered schema dead-letters immediately with reason
  `schema_violation` via the existing `outbox.event.dead_lettered` path — never partial processing,
  and never a retry-budget spend (a schema violation is structural, not transient).
- **Grandfathering (cross-task invariant #1)**: a DB outbox row with no `meta.payload_schema` (nor
  the legacy `meta.schema_version`) tag predates the registry and is treated as `v0`. Grandfathered
  rows are validated **log-only** at dispatch — a violation is logged and the real handler still
  runs; grandfathered rows are never dead-lettered retroactively.
- Topics with no registered schema are dispatched unvalidated; schema coverage is a property of the
  registered set, not an implicit requirement on every possible topic string.

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

### Secondary per-consumer cursor readers (topic-scoped, `delivered_at`-independent)

`delivered_at` is the single shared flag the worker dispatcher owns; a second logical consumer that
also needs to read specific outbox topics (without competing for, or being gated on, the worker's own
delivery state) keeps its own independent, durable, per-consumer position instead. Introduced by the
Episode Resolution Engine's `vault.activity` stream (ERE-04, #3179):
`app/episodes/vault_activity_stream.py` reads `ingest.vault.changed` / `ingest.object.created` /
`ingest.object.deleted` rows ordered `(created_at, id)` ascending, strictly after its own last-seen
position (`episode_engine_state` table, `cursor:vault.activity:<consumer_id>` key,
`app/episodes/engine_state.py`), and never reads or writes `delivered_at`. This generalizes the
`heimdal_observation_cursor` per-consumer-cursor precedent (`app/heimdal/publish.py`) to the shared
`outbox` table for a topic-scoped subset. A future secondary reader of other outbox topics should
follow the same pattern rather than inventing a new one.

## Embeddings and Outbox

Outbox events MUST NOT carry embedding vectors.

- Embeddings are computed in the indexer stage.
- Events may carry embedding metadata (dimension, model, counts) but not the raw vector payload.

## Heimdal observation log (append-only, per-consumer cursor)

`app/heimdal/observation_log.py`, `app/heimdal/cursor_store.py`, `app/heimdal/publish.py` (#3039,
Epic #3019 slice A2; ratified by `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
§1; specified by `docs/HEIMDAL/FABLE_COMPANION.md` §4.2/§1.2).

This is a **separate canonical stream**, not a DB-outbox topic family. It reuses this document's
outbox envelope (`event`/`event_id`/`trace_id`/`source`/`timestamp`/`payload`/`meta`) verbatim via
`app.events.schema.make_outbox_event`, and reuses `derive_idempotency_key`/`payload_fingerprint`
verbatim from `app.services.outbox` — but writes to its own table
(`heimdal_observation_log`, migration `8b21e6a1f0c4`), never to `outbox`. The envelope `timestamp` on
a Heimdal observation event is emission time only; observation time (`observed_at_start`, etc.) lives
in the payload, per FABLE_COMPANION §1.2 / HEIM-10.

Contract:

- **Append-only (HEIM-1).** The log is insert-only: no producer, consumer, or operator path may
  update or delete an existing row. Enforced at two independent layers: the Python store
  (`app.heimdal.observation_log`) exposes no update/delete function at all, and the Postgres backend
  additionally installs a trigger that rejects any UPDATE/DELETE statement against the table
  (`heimdal_observation_log_no_update`, migration `8b21e6a1f0c4`) regardless of which code path or
  client issues it. Corrections and revisions are new rows, never rewrites of the original
  (`supersedes`/`revision_of` are payload fields the log itself has no opinion on).
- **Per-consumer cursor (`heimdal_observation_cursor`).** Each `consumer_id` owns its own
  `(consumer_id, position)` row. Reading (`read_observations_for_consumer`) never mutates the
  cursor; advancing (`advance_cursor_for_consumer`/`consume_observations`) is explicit, monotone
  (never rewinds), and touches only that consumer's row. A `consumer_id` seen for the first time
  starts at position 0 and can rebuild its entire projection by reading the whole log from event
  zero — this is what "downstream constituents are read-models" means in practice.
- **Idempotency (KERNEL-02 discipline, reused not forked).** `app.heimdal.publish.publish_observation`
  derives the row's id via the shared `derive_idempotency_key(topic, observation_id,
  content_fingerprint)`, where the fingerprint folds in the payload plus `stage_versions`
  (`app.heimdal.publish.observation_fingerprint`). A crash-retry re-publish of the same evidence at
  the same stage versions re-derives the same key and is swallowed (`ON CONFLICT (id) DO NOTHING`,
  same convention as `write_outbox_event`); a revision (changed `stage_versions`) or a correction
  (changed payload content) derives a distinct key and always produces a new row.
- **Seam discipline.** Consumers (Mimer) must read only through
  `app.heimdal.publish.read_observations_for_consumer` / `consume_observations` — never by importing
  `app.heimdal.observation_log` and querying the table directly. This keeps the boundary
  cursor-shaped, not a shared-table coupling (issue #3039 Constraints).
- **Out of scope for this slice:** the observation payload's own field schema (family, entity
  mentions, confidence axes — that landed as slice A4, #3041, below); any transport swap to
  a stream broker (v2, ADR-gated, FABLE_COMPANION §4.3(b)).

## Heimdal event contract schemas (published v1 build-now; consent/corrected contract-stubs)

`schemas/events/heimdal.observation.published.v1.schema.json`,
`schemas/events/heimdal.consent.granted.v1.schema.json`,
`schemas/events/heimdal.consent.revoked.v1.schema.json`,
`schemas/events/heimdal.observation.corrected.v1.schema.json` (Epic #3019 slice A4, #3041; ratified
by ADR-0049 §1/§5; specified by `docs/HEIMDAL/FABLE_COMPANION.md` §1.3, canonical at enactment — this
document and §1.3 are now consistent prose/schema mirrors of each other).

- **`heimdal.observation.published` (build-now, canonical).** The cross-constituent seam payload
  produced by `app.heimdal.publish.publish_observation` (A2, #3039) onto the append-only observation
  log above. Field families per FABLE_COMPANION §1.3: identity (`observation_id`, `episode_id`,
  `sequence`, `revision_of`, `supersedes`), time (bitemporal — `observed_at_start`/`observed_at_end`,
  `clock_basis`, `captured_at`), actors (`attributions[]` with three-state `resolution`), entities
  (`entity_mentions[]`, same three-state resolution), content (`modality`, `content`, `raw_ref`,
  `withheld[]`), confidence (per-axis block, never a scalar), provenance (`content_hash`,
  `content_identity`, `capture_chain`), and sensitivity/consent (`sensitivity`, `consent` with
  required `grant_ref`, HEIM-3). Validated via the same KERNEL-08 registry choke point
  (`app.events.topic_schema_registry.validate_topic_payload`) reused verbatim from the DB-outbox
  registry — not a forked validator. Envelope `timestamp` stays emission time only; all observation
  time lives in the payload (§1.2, HEIM-10).
- **`heimdal.consent.granted` / `heimdal.consent.revoked` / `heimdal.observation.corrected`
  (contract-stubs).** Schema-representable now — a well-formed payload validates against a registered
  schema — but no runtime producer or consumer lands with this slice. The consent ledger runtime
  (grants table, capture-time check) is Epic #3019 slice A5; corrected/revision fold logic is
  FABLE_COMPANION §11#12/§11#14. `heimdal.observation.corrected` carries `supersedes` (§3.5): a
  correction is a **new** published event, never an in-place edit of the superseded observation
  (HEIM-1). None of the three stub topics are branched on in
  `app.workers.outbox_worker._dispatch_topic`, and none are referenced by
  `app.heimdal.observation_log` / `app.heimdal.publish` / `app.heimdal.cursor_store`.
- **Out of scope for this slice:** the consent ledger runtime (A5); the corrected/revision fold logic
  (§11#12/§11#14); the entity register runtime (A1, already landed, #3038); the observation log /
  cursor mechanics (A2, already landed, #3039); capture, ASR, projector.

### Karakeep published-evidence profile (contract only)

Issue #3372 defines the target adapter profile at
`docs/KARAKEEP_MIMER_ACQUISITION/DEFINE_READING_SOURCE_AND_CANDIDATE_CONTRACT.md :: Published-v1 field map`.
Each Karakeep link, note, or highlight revision conforms to the existing
`heimdal.observation.published.v1` schema and the append-only log above; no Karakeep-specific topic,
log, read API, or cursor is introduced. Heimdal alone owns REST fetch, source identity/revision,
attribution, provenance, and publication. Mimer begins at the durable event and keeps the existing
`mimer.candidate_projector` cursor. This paragraph records the contract selected by KMA-01; the
Karakeep adapter and additive candidate behavior are not shipped by this docs/test slice.

## Heimdal consent ledger v0 + capture-time check (HEIM-3)

`app/heimdal/consent_ledger.py` (#3042, Epic #3019 slice A5; ratified by
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §3;
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §6.1/§6.2/§8 HEIM-3).

An append-only ledger of consent grants and revocations (its own table,
`heimdal_consent_grant`, migration `c4f7a1b2d9e3`), seeded with the standing
`self_record` grant (v1 Posture A — "the act of deliberately recording is
the grant", FABLE_COMPANION §6.1 basis 1). Grants are appended; a
revocation is a NEW row (`basis='revocation'`, `revokes_grant_ref` naming
the lapsed grant) — never an edit of the grant it lapses, same HEIM-1
discipline as `heimdal_observation_log`, enforced by an identical
DB-level append-only trigger.

Contract:

- **Capture-time check (HEIM-3), the one enforcement point.**
  `admit_raw_evidence(scope=...)` is the *only* sanctioned signal→raw
  admission call: it resolves an active grant for the scope BEFORE
  returning an admission decision. No active grant raises
  `ConsentRefusedError` loudly (never a silent drop). A future capture
  adapter (§11#5) is required to call this function rather than
  reimplement grant resolution — that is what keeps this the only
  signal→raw path, so no capture route can bypass the ledger.
- **`consent.grant_ref` stamping.** `stamp_consent_block(grant, ...)`
  builds the `consent` block (`basis`, `granted_by`, `granted_at`,
  `third_party`, `grant_ref`) every raw record and published event must
  carry, per FABLE_COMPANION §1.1's field family.
- **B-shaped fields present-but-dormant.** Every grant record carries
  `vad_gate`, `third_party`, `retention`, and `erasure` fields, populated
  with v1-inert defaults (`vad_gate.enabled = False`,
  `third_party.policy = "degrade"`, no retention/erasure runtime), so
  enabling Posture B later is a grant + adapter change, not a schema
  redesign (ADR-0049 §3).
- **Grant/revocation events reference the observation-log topic family by
  value only.** `heimdal.consent.granted` / `heimdal.consent.revoked`
  (FABLE_COMPANION §6.1) are referenced as string constants
  (`CONSENT_GRANTED_TOPIC` / `CONSENT_REVOKED_TOPIC`) in this module; the
  canonical `app/events/types.py` topic constants and the runtime wiring
  that actually publishes them onto `heimdal_observation_log` belong to
  sibling slice A4 (event contract schemas), not this module.
- **No direct DB imports across boundaries.** Other constituents reference
  consent by `grant_ref`, never by importing `app.heimdal.consent_ledger`
  and querying the table directly.
- **Out of scope for this slice:** the capture adapter itself (§11#5), ASR,
  third-party voice detection/degradation runtime (§6.3), place/session
  grant runtime (contract-stub only — `grant_consent(basis=...)` accepts
  `session_optin`/`place_optin` values but no adapter issues them yet),
  revocation → raw-erasure / published-event-suppression propagation
  (§11#14, contract-stub).

## Heimdal raw-evidence store + voice-memo capture adapter (§11#5 — delivered #3025)

`app/heimdal/raw_store.py` + `app/heimdal/capture_adapter.py` (#3025, Epic
#3019 slice A6; ratified by
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §1;
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §11#5).

The *watch* seam: `app/heimdal/capture_adapter.py` is the only component
that touches the iCloud Shortcut folder or deletes a source file. It
watches the folder for new voice-memo files (discrete capture, posture A),
admits each one under an active consent grant, encrypts it at rest, and
writes it to its own append-only table (`heimdal_raw_record`, migration
`d5a8e2f1b6c3`).

Contract:

- **Consent admission is the one enforcement point (HEIM-3), reused not
  reimplemented.** The adapter calls
  `app.heimdal.consent_ledger.admit_raw_evidence(scope=...)` directly — it
  does not resolve grants itself. No active grant propagates
  `ConsentRefusedError` un-caught: the candidate file is left in the
  watched folder (not deleted, not silently dropped), so the ledger stays
  the only signal→raw gate no capture route can bypass.
- **Sensor registration (T5 mitigation).** The adapter's identity
  (`sensor = {adapter, version, device}`) must be registered
  (`register_sensor`) before it may admit any file — an unregistered
  identity refuses loudly (`UnregisteredSensorError`).
- **Encrypted at rest.** Raw bytes are encrypted with AES-256-GCM
  (`app.heimdal.raw_store.encrypt_raw_bytes`) before the durable write;
  plaintext never reaches the store. The key is a caller-supplied 32-byte
  value from `HEIMDAL_RAW_STORE_KEY` — a missing key refuses loudly
  (`RawStoreKeyMissingError`), never falling back to writing plaintext.
- **Provenance stamped in the same durable write (KERNEL-06).**
  `insert_raw_record` writes `content_identity` (sha256 of the raw
  evidence, the KAP-compatible join key), `capture_chain`
  (`["ios_voice_memos", "icloud_drive", "folder_watch"]` for v1), `sensor`,
  and `consent` (the resolved `grant_ref`) in the single INSERT that lands
  the ciphertext — there is no separate "stamp provenance later" step.
- **Append-only (HEIM-1).** Same discipline as `heimdal_observation_log` /
  `heimdal_consent_grant`: the Python store exposes no update/delete
  function, and the Postgres backend installs an identical
  reject-mutation trigger (migration `d5a8e2f1b6c3`).
- **Idempotent by `content_identity`.** Re-admitting the same raw evidence
  (e.g. a crash-retry before delete-after-ingest fired) does not create a
  duplicate row — a unique index (Postgres) / in-process dict (memory)
  makes a repeat `insert_raw_record` call for the same hash return the
  existing row instead of writing a second one.
- **Delete-after-confirmed-ingest.** The source file is removed only after
  the durable write returns successfully. If the write fails, the source
  file is retained and the failure is loud (raised + logged) — the
  operator's only copy is never destroyed on a failed admission.
- **No direct DB imports across boundaries.** Other constituents never
  import `app.heimdal.raw_store` and query the table directly.
- **Out of scope for this slice:** the gated *read* path over the raw store
  (§11#6, a later slice, A7 — delivered, see below); ASR / transcription /
  attribution / publish (A7 onward); always-on/ambient adapters,
  place/session grants, direct device→host transfer (all v2); a second
  modality.

## Heimdal gated raw-read path (§11#6 — delivered #3027, HEIM-5)

`app/heimdal/raw_read_gate.py` (#3027, Epic #3019 slice A7; ratified by
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §11;
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §11#6). Sits over the raw
store built by A6 (`app/heimdal/raw_store.py`) and enforces `heim_policy_
gated_raw_access` (HEIM-5): "raw-layer reads require a CrossScopeFlow grant
and emit a receipt; no ungoverned raw read path exists in any surface."

Contract:

- **Opaque `raw_ref` handle.** `raw_ref_for(record)` mints
  `"heimraw:<uuid>"` from a durable `RawRecord`; callers outside this
  module never see or pass `source_path`, a DB row shape, or the table
  name. `read_raw_record` is the only function that resolves a `raw_ref`
  back to bytes.
- **Allowlist gate (interim CrossScopeFlow stand-in, declared HEIM-5
  gap).** `read_raw_record(raw_ref, reader=..., purpose=...)` refuses
  loudly (`RawReadRefusedError`) unless `reader` is on
  `HEIMDAL_RAW_READ_ALLOWLIST` (comma-separated reader ids; unset raises
  `RawReadAllowlistMissingError` — never default-allow every reader).
  Full CrossScopeFlow grant evaluation replacing this allowlist check is
  v2; the receipt contract does not change when that lands. Grants do not
  compose: this gate governs read only — export is a distinct, separately
  gated operation (T2 mitigation, ADR-0049 §11 SBS Impact).
- **Receipt on every successful read (HEIM-1).** A successful read appends
  exactly one `heimdal_raw_read_receipt` row (who: `reader`; what:
  `raw_ref` + `content_identity`, never `source_path`; when: `read_at`;
  why: `purpose`) in the same call that returns plaintext — there is no
  "read now, receipt later" step. A refused read raises before any
  decryption is attempted and writes no receipt.
- **Append-only receipts.** Same discipline as the raw store: no
  update/delete API; the Postgres backend installs an identical
  reject-mutation trigger (migration `f1c7e2a9b4d6`).
- **No direct DB imports across boundaries.** Other constituents never
  import `app.heimdal.raw_read_gate` and query the receipt table directly.
- **Out of scope for this slice:** full CrossScopeFlow grant evaluation
  (v2, declared HEIM-5 gap); export (its own operation); ASR / attribution
  / publish stages that will become the gate's first real callers;
  cryptographic erasure (v2).

## Heimdal hard-retention ops job + deletion receipts (§11#13 — delivered #3032, HEIM-7)

`app/heimdal/retention.py` (#3032, Epic #3019 slice A12; ratified by
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`;
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §11#13). Enacts Charter
FIXED #7 / D-RETENTION: the raw layer is the one place true erasure exists
by design, and its execution must be a governed, auditable, receipted act.

Contract:

- **Bounded hard-retention, executed regardless of decay signals.**
  `enforce_hard_retention_bound()` hard-deletes every raw record in
  `app.heimdal.raw_store` whose `ingested_at` is older than the configured
  window — unconditionally on age, not gated on any relevance-decay
  signal (§11#13: "build-now (the bound) / contract-stub (event-triggered
  decay model)").
- **Markdown-first policy (A14).** The retention window
  (`retention_window_days`) is read from `_heimdal/settings.md`
  (`app.heimdal.settings_notes.SETTINGS`), never a hidden store or
  env-var-only knob. An unset or non-positive window raises
  `RetentionWindowMissingError` — this job never assumes a default bound
  for an irreversible act.
- **Deletion is never silent.** Every hard delete is paired, in the same
  operation, with exactly one durable `heimdal_raw_deletion_receipt` row
  (what: `record_id` + `content_identity`; when: `deleted_at`; why:
  `reason` — always `"hard_retention_bound"` in v1; `retention_window_days`
  names the bound in force). A `RetentionEnforcementReceipt` is returned
  from every run, including the zero-deletions case (an honestly-receipted
  no-op, never a silent skip).
- **The one governed exception to append-only (D-RETENTION).**
  `app.heimdal.raw_store.hard_delete_raw_record` is the ONLY function that
  can remove a `heimdal_raw_record` row. The Postgres trigger
  (`heimdal_raw_record_reject_mutation`, updated by migration
  `a3f9d1c6e2b8`) rejects every UPDATE unconditionally and every DELETE
  *unless* the session-local setting `app.heimdal_retention_bypass` is
  `'true'` in the same transaction — a guard only that one function sets,
  immediately before the DELETE, so no other code path (including a
  hand-written SQL client) can hard-delete a raw record outside the
  governed job.
- **The observation log is untouched.** Retention operates on raw evidence
  and deletion receipts only; `app.heimdal.observation_log` (HEIM-1,
  append-only) and its projections are never read or written by this
  module. A published event's `raw_ref` becomes a **declared dangling
  reference** after its raw record is deleted — `app.heimdal.raw_read_gate.
  read_raw_record` already raises `RawReadRefusedError` (declared-absent,
  never a silent `None`) for any `raw_ref` that does not resolve to a known
  record, so A7's gate needed no change for this slice.
- **Out of scope for this slice (v2 contract-stubs, §11#13/#14):**
  event-triggered relevance decay (the decay-model half of HEIM-7);
  consent-revocation-triggered deletion runtime; cryptographic erasure of
  published event content.

## Heimdal aggregate capacity report (HAR-01 — delivered #3847)

`app.heimdal.archive_capacity` builds a rebuildable, aggregate-only capacity
receipt over the encrypted raw store. Operators emit the redacted receipt with
`python -m app.cli heimdal capacity --vault-root <vault>`; it is a health
surface, not a raw-read path or a persisted source of record.

Contract:

- **Metadata-only query.** The capacity query reads only `ingested_at` and the
  encrypted byte length. It never materializes raw paths, content identities,
  payloads, nonces, or ciphertext for reporting.
- **Honest tier projection.** Aggregate counts and encrypted-byte totals are
  partitioned into the first seven hot days, archive-eligible records inside
  the configured retention bound, and expired records. The bound comes from
  `_heimdal/settings.md`; a missing or invalid `retention_window_days` fails
  loud instead of inventing a forecast.
- **No archive lifecycle claim.** This slice measures capacity only. It does
  not mount storage, move audio, alter retention, or make the planned local
  cold tier a supported capability; those remain parent acceptance work.

## Heimdal capture-note + receipt / J0 (delivered #3035)

`app/heimdal/capture_note.py` (#3035, Epic #3019 slice A15; ratified by
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §2;
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §9-k). Enacts journey J0
(capture → receipt): a captured voice memo lands as a **dated vault note**
that is the record — the note, not any UI, holds the truth.

Contract:

- **One dated note per captured memo.** `record_capture` writes a
  companion-note-style markdown note at a deterministic path
  (`_heimdal/captures/YYYY-MM-DD-<memo_id>.md`, `capture_note_rel_path`) as
  soon as a memo is admitted — before ASR/attribution have run. The note
  exists and is readable at that point (fitness rule: UUID/UI is not a
  render gate).
- **`status:` frontmatter walks the pipeline, monotonically.** Exactly
  `captured` → `processing` → `in-vault` (`STATUS_ORDER`), agent-authored
  (pipeline-driven, never human-editable — mirrors the field-authority
  split in `app.heimdal.settings_notes`). `write_capture_note` refuses
  (`CaptureNoteStatusError`) any write whose target status ranks lower
  than the note's current on-disk status; the note is updated **in
  place** at each transition (`record_processing`, `record_in_vault`),
  never rewritten as a new file.
- **Self-describing without a UI.** `record_processing` folds in the A8
  `TranscriptResult` (on-device transcript + segments); `record_in_vault`
  folds in the A9 `AttributionResult` (self-record speaker attribution +
  entity mentions, three-state resolution). Both are written into the
  note's frontmatter and human-readable body — opening the raw file in
  Obsidian shows the full record with no UI involved.
- **The receipt is a lens, not a capability.** `build_capture_receipt`
  projects a `CaptureNote`'s own `status`/transcript-presence/
  attribution-presence into a small read-only `CaptureReceipt`. It
  performs no write and resolves no state beyond what the note already
  carries — removing the "receipt UI" leaves the note fully functional
  (ADR-0049 §2: "the UI is a lens").
- **Governed write, no hand-rolled YAML.** Every write goes through
  `app.knowledge.write_ops.write_note_relative` +
  `app.write_guard.DEFAULT_WRITE_GUARD` (action
  `heimdal.capture_note.write`), and frontmatter is parsed/dumped via
  `scripts.yaml_roundtrip` — mirroring `app.services.companion_note` and
  `app.heimdal.settings_notes` exactly.
- **Out of scope for this slice:** always-on/ambient capture note shape
  (posture B); segment-granular multi-note-per-episode writes (v2); the
  Mimer projection of the memo into a candidate (A11); native-app receipt
  rendering (Obsidian-usable markdown only in v1).

## Heimdal governed media ingress + durable receipts (CDLM-01 — delivered #4384)

`app/heimdal/media_ingress.py` + `app/heimdal/media_receipts.py` +
`app/api/routes/heimdal_capture.py` (#4384; specified by
`docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md`;
bound by INV-CDLM-1/INV-CDLM-3 in that directory's `README.md`). Gives every
capture client one governed answer to "is my original durably accepted?" —
the question #4369 could not answer, when recordings that "should have landed"
left an empty capture tree.

Contract:

- **A receipt means durable acceptance, not a successful HTTP call
  (INV-CDLM-1).** `POST /api/heimdal/capture/media` returns 2xx only after (1)
  the raw-store write is durable and (2) the `heimdal.capture.media.admitted`
  outbox event is committed. The receipt row is written **last**, because the
  receipt *is* the acknowledgement — the same outbox-before-ack ordering the
  governed text capture enforces (`docs/contracts/MIMER_CLIENT_CONTRACT.md`
  §4.1). A 2xx without both is a contract violation, not a receipt.
- **The failure path acknowledges nothing.** A failed event commit returns
  `500 {error: "admission_event_commit_failed", state: "not_acknowledged"}` and
  writes no receipt, so `GET /api/heimdal/capture/receipts` still answers
  `unknown`. The raw store is append-only, so a raw object written before the
  failed commit survives; it is *not* an acknowledged artifact, and the client's
  resend completes admission idempotently over it (partial-failure matrix,
  "hub crash between raw write and outbox commit").
- **Transfer identity is `(capture_id, content_sha256)` (INV-CDLM-3).**
  `receipt_id` is derived (uuid5) from that pair and is the receipt table's
  primary key, so a resend after a lost response returns the same receipt
  identity and leaves one raw object. What is guaranteed exactly: one receipt
  identity, one raw object, and one DB-outbox row per transfer identity (the
  outbox idempotency key is derived from that identity, not from a per-emission
  event id). An *already-acknowledged* identity emits no further admission event
  at all — the guard lives in the shared `record_media_admission` seam, so it
  also covers a watched-folder file re-admitted on every tick after a failed
  source delete. The guard keys on *receipt existence*, so the JSONL audit log can
  still record the same admission twice whenever no receipt yet exists: two
  genuinely concurrent first admissions, or a retry after the event committed but
  the receipt did not (500 `receipt_persistence_failed`). Under a pg backend the
  derived idempotency key collapses those to one outbox row; the JSONL log is an
  operational trace, not an acknowledgement, and the receipt stays single either
  way. **A consumer keys on `receipt_id`, never on event arrival count.**
- **Receipts are their own append-only store, not a raw-record field.** The raw
  store holds one object per *content hash* while receipts are keyed by transfer
  identity, and recovery queries by `capture_id` — a direction the raw store
  cannot answer. `heimdal_media_receipt` (migration `e3c1a7f5d2b8`) carries the
  same HEIM-1 append-only trigger as `heimdal_raw_record` /
  `heimdal_raw_read_receipt`. Answering a receipt query never touches raw
  evidence.
- **Named error states, never blind-retryable.** 415 `unsupported_media_kind`,
  413 `media_too_large` (with `max_bytes`), 422 `sidecar_schema_invalid` /
  `content_hash_mismatch`, 409 `consent_refused` (HEIM-3), and a
  `state: not_acknowledged` 500 family: `raw_write_failed`,
  `admission_event_commit_failed`, `receipt_persistence_failed`,
  `raw_store_key_unavailable`, `media_cap_misconfigured`, plus the
  `admission_failed` catch-all — no reachable failure on this seam may surface as
  an unnamed 500, because "never blind-retryable" only holds if the client always
  has an `error` to branch on. The receipt query answers 503
  `receipt_store_unavailable` rather than `unknown` when the store cannot be
  read: `unknown` is an answer a client deletes originals against, so it is never
  used to report a read failure. Per-kind caps default in
  `media_ingress.DEFAULT_MEDIA_KIND_MAX_BYTES` and are overridable per kind via
  `HEIMDAL_MEDIA_MAX_BYTES_<KIND>`; a present-but-unusable override fails loud
  rather than admitting evidence the operator believed was bounded.
- **Operator precondition.** Admission encrypts through
  `app.heimdal.raw_store`, so `HEIMDAL_RAW_STORE_KEY` must be provisioned to the
  process serving the API. Today `config/secrets/host_secret_contract.json`
  declares that secret for the `heimdal-capture-watch` consumer only, so an api
  process without it refuses every admission with 500
  `raw_store_key_unavailable` / `not_acknowledged` — named and remediable, never
  a silent or ambiguous failure. Provisioning it to the api consumer (which the
  pre-existing `POST /api/heimdal/screen/capture` needs equally) is tracked
  separately, not claimed here.
- **Receipts are not retention-aware, stated honestly.**
  `app.heimdal.retention.enforce_hard_retention_bound` hard-deletes raw records
  past the retention window without consulting receipts, so a receipt can outlive
  the raw object it attests to: the query would still answer `admitted` with a
  `raw_ref` that no longer resolves, and a resend short-circuits on that receipt
  rather than re-admitting the original. Latent today — nothing schedules that job
  — but CDLM-03 deletes client originals against an `admitted` answer, so a
  receipt-aware retention interaction must land before that. Tracked as a deferred
  defect on the Known Defects registry (#4172), not claimed as solved here.
- **Consent scope, stated honestly.** Every kind is admitted under the standing
  self-record grant the voice-memo lane uses
  (`consent_ledger.SELF_RECORD_SCOPE`), whose descriptive
  `capture_profile.modalities` names `speech` only. No modality enforcement reads
  that field today, so this is a provenance-accuracy gap rather than an
  admission bypass; giving the media lane its own grant naming its modalities is
  an owner decision tracked separately.
- **LAN/loopback/tailnet posture only.** Both routes refuse a peer outside
  loopback, RFC1918/ULA, link-local, or the tailnet CGNAT range with 403
  `public_ingress_refused`, judged on the immediate peer and never on
  `X-Forwarded-For`. Public ingress is owner-reserved; per-agent keys are the
  named next hardening slice (client-contract gap F2).
- **Both lanes share the seam.** A watched-folder admission
  (`app.heimdal.capture_adapter.admit_capture_file`) records a receipt through
  the same `record_media_admission` call, keyed by the HCAP-07 sidecar's
  optional `capture_id` when present and by content hash otherwise. It never
  gates that lane's delete-after-confirmed-ingest: receipt-gated retention is an
  outbox-lane property (CDLM-03), and claiming it for the legacy lane is the
  forbidden outcome in the vertical's partial-failure matrix.
- **Out of scope for this slice:** session/segment ledger semantics (CDLM-02 —
  `session_id`/`session_seq` are stored opaquely alongside the admission), ASR
  or any derivation (CDLM-06), streaming/resumable uploads, auth keys, public
  ingress, and any change to the watched-folder watcher (#4362 owns its
  env-delivery bug).

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
bounded retry limit and will not be requeued, when an unclassified poison dispatch failure spends
the configured DB-row dispatch-attempt budget, or when a registered-schema payload fails validation
at dispatch (`reason="schema_violation"`, KERNEL-08 #2770 — dead-lettered immediately, on the first
attempt, with no retry-budget spend since the failure is structural, not transient). This is a
diagnostic dead-letter signal, not an automatic replay request, and it must not be consumed as the
original event topic. Classified dispatch-level infrastructure transients do not emit this event;
they leave the original DB outbox row pending for supervised retry. Grandfathered (pre-registry) rows
never emit this event for a schema violation — see
[Event Topic Schema Registry](#event-topic-schema-registry-normative).

Shared payload fields:
- `original_topic` (`string`): topic that exhausted retries.
- `original_event_id` (`string`): original event id when available, otherwise empty.
- `reason` (`string`): worker retry reason, dispatch poison marker, or `schema_violation`.

Retry-exhaustion payload fields:
- `note_path` (`string`): note path associated with the failed work.
- `retry_count` (`int`): retry count at exhaustion.

Dispatch-poison / schema-violation payload fields:
- `outbox_id` (`string`): DB outbox row id that exhausted dispatch attempts (or violated its schema).
- `attempts` (`int`): DB-row dispatch attempt count at exhaustion (`0` for an immediate schema-violation dead-letter).
- `error` (`string`): final handler error string recorded for operator triage.

Operator visibility:
- inspect via `GET /api/events/tail?event_prefix=outbox.event` or `events-doctor` against
  `INDEX_OUTBOX_PATH`.
- the event is emitted separately from the original topic so it does not re-enter the transient
  retry path.

### `knowledge_acquisition.stage.completed`

Emitted by the Knowledge Acquisition refinement pipeline (KA-06, #2801) when a refinement
stage transition succeeds: `normalize`, each extractor run, and `candidate`. A lineage/audit
event recording that a stage transition happened, per
`docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` § Stage execution model / §
Lineage and replay. KA-06 shipped it deliberately unconsumed; KA-07 (#3107) added the first
consumer route in `app/workers/outbox_worker.py::_dispatch_topic`
(`handle_knowledge_acquisition_stage_completed`). The consumer's downstream action is
bounded and minimal, NOT the triage engine
(`docs/KNOWLEDGE_ACQUISITION/INGESTION_AND_TRIAGE_POLICY.md`/CONTEXTUALIZATION_LAYER own
that, still docs-only target state): only a `candidate`-stage completion (the pipeline's
terminal stage, where a candidate note now exists) emits a durable
`knowledge_acquisition.candidate.ready_for_triage` observability signal (JSONL audit sink +
DB outbox row when enabled); `normalize`/extractor-run completions are traced (dispatched,
logged) with no further action, since there is no candidate yet to mark ready. Because the
topic is now dispatched, KA-07 also registered its KERNEL-08 topic schema
(`schemas/events/knowledge_acquisition.stage.completed.v1.schema.json`), so
`emit_stage_completed` now hard-validates its payload against that schema and stamps
`meta.payload_schema` at write time via `write_outbox_event` (required fields: `stage`,
`stage_version`, `content_identity`).

Deterministic idempotency key (KERNEL-02, via `derive_idempotency_key`): keyed on
`(stage, stage_version, content_identity)` — plus `extractor_id` for extractor runs so two
extractors over the same content never collide. Re-running an unchanged stage at an
unchanged version re-derives the SAME key (idempotent no-op: exactly one row); a stage
version bump derives a DISTINCT key (a stage improvement re-runs the stage and is a
genuinely new lineage event, never swallowed against the old row). The consumer's
`ready_for_triage` signal re-derives its own key from the same
`(content_identity, stage-scope, stage_version)` fingerprint the producer used, so
redelivery of the identical stage-completed event converges to a single signal.

Payload fields (in addition to the envelope):
- `stage` (`string`): `normalize` | `extracted` | `candidate`.
- `stage_version` (`int`): the stage's / extractor's version.
- `content_identity` (`string`): the `raw` record's `content_identity` this artifact descends from.
- `extractor_id` (`string`, extractor runs only): the extractor that produced the artifact.
- `model_identity` (`object`, extractor runs only): `{provider, model}` lineage of the resolved LLM route.
- `artifact_path` (`string`, `candidate` stage only): the vault-relative note path.

### `knowledge_acquisition.stage.dead_lettered`

Emitted by the Knowledge Acquisition refinement pipeline (KA-06, #2801) when a stage fails
for one item: the loud, durable record that THIS item failed at THIS stage. Item-scoped —
a sibling item or sibling extractor is unaffected (contract § Stage execution model: "loud
and item-scoped: it dead-letters that item at that stage without blocking other items or
other extractors"). Distinct from `outbox.event.dead_lettered`, which is the worker's
DB-row dispatch-poison signal; this event is a KA stage-pipeline compute failure, never a
queued row the worker is dispatching. KA-07 (#3107) added the consumer route
(`handle_knowledge_acquisition_stage_dead_lettered`): it surfaces a durable, item-scoped
`knowledge_acquisition.stage.dead_letter_surfaced` observability signal (JSONL audit sink +
DB outbox row when enabled) and never raises, so a dead-lettered item never blocks dispatch
of a sibling item's event. Because the topic is now dispatched, KA-07 also registered its
KERNEL-08 topic schema (`schemas/events/knowledge_acquisition.stage.dead_lettered.v1.schema.json`),
so `emit_stage_dead_letter` now hard-validates its payload against that schema and stamps
`meta.payload_schema` at write time via `write_outbox_event` (required fields: `stage`,
`stage_version`, `content_identity`, `reason`, `error`). Its
deterministic key is content-scoped (fingerprint `<scope>:<stage_version>:dead_letter`), so
a duplicate delivery of the same failure dedups to one audit row; the consumer's surfaced
signal re-derives its own key from the same fingerprint shape and dedups identically.

Payload fields (in addition to the envelope):
- `stage` (`string`), `stage_version` (`int`), `content_identity` (`string`): as above.
- `extractor_id` (`string`, extractor-stage failures only).
- `reason` (`string`): failure class, e.g. `extraction_failed`.
- `error` (`string`): the underlying error string, preserved for triage (never swallowed).

### `heimdal.register.entity.minted`

Emitted by the Heimdal entity register v0 (Epic #3019 slice A1, #3038) when a new entity
note is created — either `mint_provisional` (an unknown surface form becomes a durable
provisional entity) or `mint_canonical` (a canonical entity is admitted directly). A
**lineage/audit** event, NOT a dispatched command, mirroring the Knowledge Acquisition
stage events above: it is deliberately absent from `app/workers/outbox_worker.py::
_dispatch_topic` and from the topic-schema registry. The canonical store for entity
identity is the `.md` note this event accompanies
(`app/heimdal/entity_register.py::render_entity_note`), never a DB row or graph — see
`docs/HEIMDAL/FABLE_COMPANION.md` §3.2 / §9 "Decision run" item 1.

Deterministic idempotency key (KERNEL-02, via `derive_idempotency_key`): keyed on the
minted `entity_id` plus a fingerprint scope naming the mint kind and surface form/label.

Payload fields (in addition to the envelope):
- `entity_id` (`string`): the minted `ent:<uuid>` (canonical) or `ent:prov:<uuid>` (provisional) id.
- `surface_form` / `label` (`string`): the text the entity was minted from.
- `kind_hint` / `kind` (`string`): `person` | `organization` | `project` | `place` | `agent` | `thing`.
- `lifecycle` (`string`): `provisional` | `canonical` at mint time.
- `aliases` (`array[string]`, canonical mints only).

### `heimdal.register.entity.merged`

Emitted by `EntityRegister.merge()` when a governed, human-confirmed merge folds one
entity into another (`docs/HEIMDAL/FABLE_COMPANION.md` §3.2 op 3 / §9-g). Append-only
(HEIM-1): the source entity's note is never deleted, only marked `lifecycle: merged` with
a `merged_into` redirect; the target note's aliases are folded to include the source's
label/aliases. Lineage/audit event, same non-dispatched posture as above.

Payload fields (in addition to the envelope):
- `from_id` (`string`): the entity_id that was merged away.
- `into_id` (`string`): the entity_id it was merged into.

### `heimdal.register.entity.split`

Emitted by `EntityRegister.split()` — the reversible un-merge the F5 red-team gate
requires before any merge ships (`docs/HEIMDAL/FABLE_COMPANION.md` §10 F5). One event per
resulting new entity. Splitting a merge target re-points any previously-merged child
entity whose aliases fall in the new partition, restoring `resolve_redirects()` to the
pre-merge identity — see `tests/heimdal/test_entity_register.py::test_split_reverses_merge`.

Payload fields (in addition to the envelope):
- `split_from` (`string`): the entity_id that was partitioned.
- `new_entity_id` (`string`): the newly minted canonical entity for this partition.
- `label` (`string`): the new entity's label.
- `aliases` (`array[string]`): the alias subset moved into the new entity.

### `heimdal.register.entity.redirect_resolved`

Emitted by `EntityRegister.resolve_redirects()` recording that a (possibly stale)
entity_id was followed through its merge-redirect chain to its current living identity.
Every consumer of historical Heimdal events uses `resolve_redirects` for this, per
`docs/HEIMDAL/FABLE_COMPANION.md` §3.2 op 4.

Payload fields (in addition to the envelope):
- `queried_entity_id` (`string`): the entity_id the caller asked to resolve.
- `resolved_entity_id` (`string`): the current (non-merged) entity_id it resolves to.

### `heimdal.capture.media.admitted`

Emitted by `app.heimdal.media_ingress.record_media_admission` once one media
original is durably in the encrypted raw store, and **before** the receipt that
acknowledges it exists (INV-CDLM-1, #4384). Not a dispatched command: no
`outbox_worker._dispatch_topic` branch and no registered topic schema. Its
committed presence is a *precondition* of the receipt, so a consumer treats the
`heimdal_media_receipt` row as the acknowledgement and this event as the
auditable record of how the admission happened. Payload is metadata only — the
bytes are durable in the encrypted raw store, never duplicated into event logs.

Payload fields (in addition to the envelope):
- `capture_id` (`string`): the client-minted transfer id; for a watched-folder
  admission with no sidecar `capture_id`, the content hash itself.
- `content_sha256` (`string`): the raw bytes' hash — the KAP-compatible join key
  and the raw record's `content_identity`.
- `raw_ref` (`string`): the opaque `heimraw:` handle, resolvable only through the
  gated read path (`app.heimdal.raw_read_gate.read_raw_record`).
- `kind` (`string`): one of `audio`, `image`, `video`, `document`.
- `lane` (`string`): `media_ingress` (governed HTTP) or `watched_folder` (legacy
  Model-1); the lane determines retention posture, not receipt shape.
- `receipt_id` (`string`): the derived receipt identity this admission will
  acknowledge under.
- `device_id`, `captured_at`, `schema_version`: client lineage, governed lane only.
- `session_id`, `session_seq`: **present only when the client sent them** — the
  keys are omitted rather than emitted as null, so a consumer must use a
  defaulting read. Carried opaquely for CDLM-02, which owns every ledger semantic
  over them; this lane never interprets or orders them.

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

### `settings.write.receipt`

Durable accountability record for every settings write (#2787, #3162). The shared seam in
`app/receipts/settings_write.py` is called by the API/CLI/MCP settings service, watcher file-delta
apply, compiler auto-heal writeback, and the pre-vault app-local store. Receipts observe writes and
never authorize or gate them. They preserve the existing best-effort dual-sink posture: JSONL audit
surface plus DB outbox, keyed via the shared `derive_idempotency_key` helper
(`app/services/outbox.py`, KERNEL-02) as an event-id-keyed emission (`EVENT_ID_FINGERPRINT`). A sink
failure cannot turn a successful settings write into a failed write.

Payload:
- `key` (`string`): the setting key written.
- `value` / `new_value` (any): the new value (`value` remains the compatibility field).
- `old_value` (any): the value observed before the write, or null when absent.
- `file` (`string` or null): the mutated settings file when the writer has one.
- `surface` (`string`): origin surface — `'api'`, `'cli'`, `'file'`, `'mcp'`, `'auto-heal'`, or
  `'app-local'`.
- `actor` (`string`): stable actor identity (`'human'`, `'agent'`, or `'system'` on current writers).
- `timestamp` (`string`, ISO-8601): receipt timestamp (mirrors the in-memory receipt's own
  timestamp, not necessarily the outbox envelope's `timestamp`).
- `is_runtime_gating` (`bool`): whether the key is in `RUNTIME_GATING_SETTINGS`.

Query/projection: `app/receipts/settings_receipts.py :: query_settings_receipts`, a typed
read-only projection over durable `settings.write.receipt` records — the same shape as
`app/receipts/promotion_receipts.py :: query_promotion_receipts`.

Interpretation:
- this is the accountability/receipt-supporting layer for settings writes, not an intent or
  execution-result event,
- durability is additive: `SettingsService.update_setting`'s return-value contract
  (`(EffectiveSetting, SettingsWriteReceipt)`) is unchanged,
- compiler auto-heal keys are file-qualified (for example `global.timeout_ms`), while app-local and
  canonical settings-service keys retain their native setting names; compiler-generated reference
  block mutations use the synthetic file-qualified key `<file>.__reference__`,
- deleting a settings key emits null for both `value` and `new_value`, while `old_value` preserves
  the removed value.

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
