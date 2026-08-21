State: Canonical hub client contract (owner rulings 2026-07-07, enacted via `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`; governed media and meeting lanes promoted 2026-08-01 after CDLM acceptance). Current-state contract over shipped surfaces; every named gap is marked as follow-on work, not claimed solved.
Doc role: Core SoT contract
Authority: Canonical for how external clients attach to Mimer: the callable surface, the two write transports (governed HTTP API and direct filesystem), the authority envelope, and the concurrent-writer client discipline. Serves BOTH client families — Bifrost native shells (`RasmusTho/bifrost`, ADR-0050) and external app agents (Claude app, Codex app, and peers). Subordinate to `docs/INTEGRATION_FABRIC_CONTRACT.md` (class taxonomy + authority rule), `docs/AGENT-FLOWS.md` (participation modes and zones), `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (the decided multi-writer mechanism, supersedes ADR-0053, resolves #3114; VMW-01 through VMW-04 and INV-VW2 are delivered, while versionless-writer migration remains in #3570), and `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md` / `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` (runtime write mechanics). `docs/ARCHITECTURE.md` and `docs/STATUS.md` win on current runtime truth.
Owner: Architecture spine (Rasmus)
Temporal class: strategic
Review cadence: event-driven (re-verify at each Epic B wave boundary and each remaining ADR-0055 enactment change)
Source of truth: mixed
Last reviewed: 2026-08-01

# Mimer Client Contract

## 1. Purpose and audience

This is the single hub contract for every external client of Mimer (the shipped knowledge-and-cognition constituent, `app/`). One contract, two client families:

- **Bifrost native shells** — the iPhone/Watch/iPad clients (Epic B #3020; B1 `bifrost#1`/#3023), which render Mimer and Heimdal surfaces and read/write the vault.
- **External app agents** — Claude app, Codex app, and any comparable agent runtime the human points at Mimer or the vault.

The families share almost the entire seam (same HTTP API, same vault, same invariants, same auth gap), so one artifact serves both; where postures differ, the difference is stated per family in place. This closes audit item T2 (`docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §10): "Mimer client contract" now greps to a real file, and `bifrost#1`/#3023 Source Anchors can resolve here.

**What this contract is not.** It is not an SDK or a consistency mechanism. The published `_heimdal/**` schema is a client-facing manifest, while runtime parsing/enforcement remains in `app/heimdal/settings_notes.py`; the full multi-writer mechanism remains follow-on work (§9 F6).

## 2. Classification and transports

### Integration classes (per `docs/INTEGRATION_FABRIC_CONTRACT.md`)

- An external app agent is an **Agent runtime** (class 10). When it renders Mimer content to the human it additionally answers the **External UI shell** (class 8) fields.
- A Bifrost shell is an **External UI shell** (class 8) and, as the surface the human types into, participates in the **Human surface** (class 1) role. The human driving either family always remains class 1 — the client never absorbs the human's authority.
- Per-class contract-field answers are in §8.

### Participation modes (per `docs/AGENT-FLOWS.md` §3)

A client under this contract operates in two modes simultaneously:

- **API-mediated caller** — governed writes and retrieval through the HTTP surface (§4). Mediated-write semantics apply (AGENT-FLOWS §4).
- **Mode (c) direct filesystem agent** — direct reads and writes of vault Markdown under the human's delegation (§5). Observed-write semantics apply: Mimer observes, classifies, and indexes the result; a direct write is not APPLY, produces no Mimer receipt of its own, and confers no authority.

**MCP is not a transport of this contract.** The `mcp.vault.append_note` descriptor is an internal orchestrator descriptor (`docs/settings/tools/mcp.vault.append_note.yaml`), not an externally callable endpoint; no MCP server exists in `app/`, and the MCP topology stance is owner-deferred (ADR-0047). This contract does not reopen that deferral. Mode (d) MCP/RBAC attachment remains future work.

## 3. Authority envelope — the three hard invariants

Every client, both families, both transports:

1. **Never semantic authority.** The client never decides what a vault note means, never owns a Core-6 field, and never treats its own output as human-canonical. Client output enters at the zone posture of where it lands (AGENT-FLOWS §7); promotion to human-canonical knowledge is a human act through the trust path (`docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`).
2. **Every durable mutation stays inside a named transport.** There are exactly two: the governed API path (§4) and the direct-filesystem path (§5). No bespoke side channels, no client-invented write mechanisms, no local write queue that replays into the vault without the human.
3. **Never a hidden source of truth.** No client-local store may hold meaning that the vault + companion set cannot rebuild (`docs/INTEGRATION_FABRIC_CONTRACT.md` authority rule). Client caches are opaque external durability: rebuildable, never written back as authority.

How each transport stays inside the envelope:

- **API transport — safe by construction.** The capture endpoint runs the full governed chain (WriteGuard → DecisionToken → deterministic append → AuthorityReceipt → outbox event; §4.1), so invariants hold mechanically: the write is admissible before mutation and accountable after it.
- **Filesystem transport — safe by discipline plus observation.** The filesystem cannot enforce governance, and Mimer does not pretend it can (AGENT-FLOWS §12). The envelope holds through the client discipline of §6, the zone/exclusion rules of §5, and Mimer's post-hoc observation: the watcher ingests the changed file (mtime + sha256, `app/watcher/watcher.py`), classifies it by zone and provenance, and the result stays non-canonical until the human promotes it. A blocked or failed governed API write must never be re-routed as a direct filesystem write — that is a governance bypass, not a degradation.

## 4. Callable HTTP surface (v1, shipped)

Base URL: the Mimer runtime API (`app/api/app.py`). All routes below exist on `main` today. Trace correlation: send `x-trace-id` on every call; the runtime's TraceIdMiddleware propagates it into spans, receipts, and events.

**v1 auth posture (owner ruling):** LAN/loopback-only. The client-facing routes below carry no auth dependency today; `X-API-Key` machinery exists (`app/auth.py`) but is applied to only three routes in `companion.py`. A client under this contract MUST refuse to operate against a Mimer host that is not loopback, LAN, or tailnet (`docs/SECURITY_TRUST_BOUNDARIES.md`). Per-agent identity/keys is the named first hardening slice (§9 F2), not a v1 blocker.

| Operation | Method + path | Purpose | Provenance/trace | Governance |
| --- | --- | --- | --- | --- |
| Capture (write) | `POST /api/companion/capture` | Friction-free intake into the vault inbox note | `x-trace-id`; actor currently fixed (§9 F1) | Full governed chain (§4.1) |
| Media capture (write) | `POST /api/heimdal/capture/media` | Admit one captured original (audio/image/video/document) and return its durable-acceptance receipt | `x-trace-id` / response `trace_id`; client-minted `capture_id` + `content_sha256` | Governed chain, acknowledged only on durable acceptance (§4.4) |
| Receipt query | `GET /api/heimdal/capture/receipts?capture_id=` | Answer `admitted`, `erased`, or `unknown` per capture id — the reconnect/recovery answer after a lost response | `x-trace-id` / response `trace_id` | Read-only; discloses admission state, same LAN posture (§4.4) |
| Meeting session (write) | `POST /api/heimdal/meeting/session` | Open or replay one client-minted meeting session | `x-trace-id` / response `trace_id`; stable `session_id` | Durable idempotent ledger write (§4.5) |
| Meeting close + finalization (write) | `POST /api/heimdal/meeting/{session_id}/close` | Record the final segment count and trigger idempotent finalization | `x-trace-id` / response `trace_id`; stable `session_id` | Durable close; finalization status is explicit (§4.5) |
| Meeting gap report | `GET /api/heimdal/meeting/{session_id}/segments` | Return received and missing sequence numbers, conflicts, and completeness | `x-trace-id` / response `trace_id` | Read-only projection over the durable ledger (§4.5) |
| Meeting live projection | `GET /api/heimdal/meeting/{session_id}/projection` | Return revisable transcript/default-analysis blocks plus finalization receipt | `x-trace-id` / response `trace_id`; revision/provenance per block | Read-only, derived, never canonical (§4.5) |
| User note (write) | `POST /api/heimdal/meeting/{session_id}/user-note` | Persist one editor-authored note revision without exposing it to derived writers | `x-trace-id` / response `trace_id`; `(note_block_id, revision)` | Editor-only fail-closed block guard; durable ack (§4.5) |
| Retrieve | `GET /search?q=` | Hybrid retrieval over the durable index (KERNEL-05) | `x-trace-id` | Read-only |
| Ask | `POST /api/ask` | Grounded Q&A with per-source citations | `x-trace-id` | Read-only |
| Voice ask | `POST /api/ask/voice` | One turn from transient audio to a grounded ASK answer and optional local speech | `x-trace-id` / response `trace_id` | **Read-only**; no transcript, capture intent, or audio is written |
| Read note | `GET /api/artifacts/note?note_path=` | Fetch one note's title/body/hash by vault-relative path | `x-trace-id` | Read-only; traversal-guarded |
| Health | `GET /healthz`, `GET /readyz`, `GET /api/status`, `GET /version` | Liveness/readiness/status/build discovery | — | Read-only |

### 4.1 `POST /api/companion/capture` (the governed write)

Implementation: `app/api/routes/capture.py`. Request body is exactly `{"text": "<non-empty string>"}` — the schema is `extra="forbid"`, so any additional field (including a provenance or due-date field) is rejected with 422. The write is an append-only timestamped bullet (`- [<utc-iso>] <text>`) to the vault inbox note (`<inbox_dir_rel>/inbox.md` by convention).

Governed chain, in order: WriteGuard gate (`companion.capture.append`) → GovernedWriteAdapter issues a DecisionToken (write class `vault_capture_append`) → deterministic append via `app.knowledge.write_ops.append_note_relative` returning a runtime `WriteReceipt` → AuthorityReceipt recorded → `capture.inbox.appended` outbox event (JSONL audit log + DB outbox mirror) persisted **before** success is acknowledged.

Success response (`200`): `{outcome: "written", note_path, operation, adapter, captured_at, trace_id, events_emitted, governed_write, ingest_warning}` — `governed_write` carries the PolicyDecision, DecisionToken, and AuthorityReceipt verbatim; `ingest_warning` (nullable) is set when the write landed but downstream ingest signaling degraded — the capture is durable, the index may lag. The client MUST surface this receipt, not fabricate its own acknowledgement.

Error contract (a client must handle each named state; never retry blindly):

| Status | `error` | Meaning | Client behavior |
| --- | --- | --- | --- |
| 422 | (schema) / `empty_capture` | Extra fields, or whitespace-only text; nothing written | Fix the request; surface to human |
| 409 | `writeguard_blocked` | WriteGuard denies writes; `reason` included; nothing written | Surface reason verbatim; do NOT fall back to a direct FS write |
| 409 | `inbox_convention_unresolved` | Inbox note convention could not resolve; nothing written | Surface to human |
| — | vault-selection state (structured JSON: `{state: "vault_selection_required", reason, …}` — `reason` ∈ `vault_root_misconfigured` / `no_vault_bound` / `uninitialized`; there is no `error` field) | No active vault selected | Match on `state`, not `error`; surface; the human selects a vault; never guess a vault |
| 500 | `authority_receipt_persistence_failed`, state `not_acknowledged` | **The append may have landed** but its AuthorityReceipt could not be persisted | Do NOT blind-retry (duplicate-append risk). Verify by reading the inbox note (§6 W5) or hand to the human |

### 4.2 Read surface and the uuid→path gap

- `GET /search?q=` returns `{"results": [{uuid, title}, …]}`, fixed k=10. A retrieval failure propagates as an error — no silent filler (#2989).
- `POST /api/ask` takes `{"question": …}` (alias `query`; optional `zone_strategy`) and returns an answer with per-source attribution: each source carries `uuid, title, origin, plane, zone, path`.
- When the ASK model backend accepts a connection but fails to respond before the configured LLM timeout,
  `POST /api/ask` returns HTTP 504 with FastAPI detail
  `{error: "llm_backend_timeout", provider, timeout_seconds, trace_id, message}`. Clients must surface
  this as degraded model-provider availability, not as an empty grounded answer and not as an
  invitation to answer from client memory.
- `GET /api/artifacts/note?note_path=` reads a note **by vault-relative path** (absolute paths and traversal rejected with 400 `invalid_path`; missing note → 404 `note_not_found`). Response: `{artifact_id, note_path, title, body, content_hash}` — note the response's `note_path` is the **absolute resolved filesystem path**, not the vault-relative path the request took; clients must not echo it to other hosts or store it as a stable identifier.

**The gap, stated honestly:** search returns *uuid*; note-fetch keys by *path*; no endpoint resolves uuid→path. **v1 posture: thin read + filesystem enrichment.** A client that needs the body behind a search hit either (a) uses `/api/ask`, whose sources include `path`, or (b) resolves the uuid itself against its filesystem view of the vault (frontmatter `uuid` field). A uuid-resolving fetch or enriched search payload is follow-on work (§9 F3), not something a client may emulate by inventing a hidden uuid→path store it treats as authoritative (invariant 3: any such cache is rebuildable and disposable).

**Index-lag honesty:** the retrieval index is a rebuildable projection that trails the vault (watcher → ingest → index). A client MUST NOT present a retrieval miss as absence-of-knowledge without saying the index may lag, and MUST NOT assume read-your-write through `/search` after any write (§6 W6). The vault note outranks any projection of it (AGENT-FLOWS §10).

### 4.3 `POST /api/ask/voice` (read-only voice ASK turn)

Implementation: `app/api/routes/ask.py`. Send a multipart request with one required `audio` part and optional `session_id` and `zone_strategy` form fields. v1 accepts WAV, M4A/MP4, WebM, and Ogg containers (`audio/wav`, `audio/m4a` or `audio/mp4`, `audio/webm`, `audio/ogg`); it is turn-based, not streaming. Audio is capped at 5 MiB before STT work. Oversize input returns `413 {error: "audio_too_large", trace_id}` and an unsupported or undecodable container returns `415 {error: "audio_undecodable", trace_id}`.

On a successful grounded turn, the response is `{transcript, detected_language, answer, sources, speech_plan, audio_url?, degraded, reason?, session_id?, trace_id}`. `answer` and `sources` retain the `POST /api/ask` `AskResponse` meaning and source attribution; `speech_plan` is the local TTS plan; `audio_url` is present only when local TTS synthesis produced a cached audio result. `detected_language` is STT-detected rather than client-pinned, and drives the local speech plan.

This endpoint has no vault-content write path. A capture-intent utterance is returned as a suggestion with `degraded: true` and `reason: "capture_intent_surfaced"`; the client must call the governed capture endpoint (§4.1) only after explicit user intent to save it.

Clients must handle the three named voice-leg degradation states without inventing an answer from client or model memory:

| Condition | Response | Client behavior |
| --- | --- | --- |
| STT unavailable or yields no transcript | `503 {error: "stt_unavailable", trace_id}` | Surface the failure; do not substitute an empty or guessed answer. |
| Grounded ASK unavailable after transcription | `503 {error: "ask_unavailable", transcript, detected_language, session_id?, trace_id}` | Preserve and show the heard transcript; do not answer from client/model memory. |
| Local TTS unavailable or disabled | `200` grounded text response with `degraded: true`, `reason: "tts_unavailable"`, and no `audio_url` | Show the grounded answer and sources as text; do not fail the turn solely because speech is unavailable. |

### 4.4 `POST /api/heimdal/capture/media` + `GET /api/heimdal/capture/receipts` (the governed media lane)

Implementation: `app/api/routes/heimdal_capture.py` over `app/heimdal/media_ingress.py` and
`app/heimdal/media_receipts.py`. Shipped by #4384 / PR #4400. The runtime event contract and the
lane's known limitations are owned by `docs/EVENTS.md :: Heimdal governed media ingress + durable
receipts`; the task specification is
`docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md`. This section
states only what a client may call and must handle.

**Request.** Multipart with two parts: `media` (the original's bytes) and `sidecar` (JSON). The
sidecar may be sent as a plain form field or as a named part with a filename; both are accepted. It
carries at minimum `capture_id` (client-minted UUID), `content_sha256`, `kind` ∈ `{audio, image,
video, document}`, `captured_at` (ISO-8601), `device_id`, and `schema_version`, plus optional
`session_id`/`session_seq` which this lane stores opaquely. Unknown fields are retained as opaque
lineage rather than rejected, so the sidecar composes with the capture-time metadata sidecar
(`docs/HEIMDAL_CAPTURE_CLIENT/CAPTURE_TIME_METADATA_SIDECAR.md`) instead of forking it.

**A 2xx is a receipt, not transport success.** The response exists only after the original is
durably written to the encrypted raw store **and** the `heimdal.capture.media.admitted` outbox event
is committed; the receipt is persisted last, because the receipt *is* the acknowledgement. This is
the same outbox-before-ack ordering as §4.1. Success (`200`):
`{outcome: "admitted", capture_id, content_sha256, receipt_id, raw_ref, kind, admitted_at, trace_id, response_lease}`
plus `idempotent_replay: true` when this identity was already acknowledged. A client MUST surface
this receipt and never fabricate its own. `response_lease` is bound to the exact raw liveness
generation and includes `lease_id`, `liveness_generation`, `issued_at`, and `expires_at`. It is the
validity window for receipt-gated local cleanup; after expiry, retain the original and re-query.

**Idempotency identity is `(capture_id, content_sha256)`** — the client-visible key §9 F5 asks for,
delivered here for the media lane. `receipt_id` is derived from that pair, so re-sending after a lost
response returns the same receipt identity, leaves one raw object, and re-admits nothing. UUID
spelling is canonicalized (uppercase, braced, unhyphenated, and `urn:uuid:` forms are one identity),
but a client should still persist and re-send one stable spelling. **Key on `receipt_id`, never on how
many admission events arrived** — the audit log may record one admission twice while the receipt
stays single.

**Recovery.** `GET /api/heimdal/capture/receipts?capture_id=…` takes the parameter repeatably, up to
100 ids per call, and answers `{receipts: [...]}` with one entry per requested id, echoing the id you
asked for so answers stay alignable with the request. Each entry is either
`{capture_id, outcome: "admitted", receipt_id, content_sha256, raw_ref, kind, lane, admitted_at, response_lease}` or
`{capture_id, outcome: "erased", receipt_id, content_sha256, raw_ref, kind, lane, admitted_at}` or
`{capture_id, outcome: "unknown"}`. `unknown` means *never arrived* and is a first-class answer, not
an error — it is how a client distinguishes a lost response from a capture that never reached the hub.
`erased` means governed retention removed the raw evidence after the immutable admission receipt was
written: retain the local original, surface the terminal state, and do not treat that historical
receipt as permission to delete or as a normal idempotent replay.
An active answer is backed by a short-lived response lease; retention uses the same liveness fence
and will not erase that generation while the lease is valid. Once retention claims the generation,
the claim records a finite lease-drain frontier and subsequent polling cannot renew or reopen a
lease; PostgreSQL enforces that boundary at the lease write trigger as well. Raw absence without a governed
tombstone is `503 receipt_store_unavailable`/`raw_liveness_unavailable`, never `erased`.

Error contract (a client must branch on `error`; never retry blindly):

| Status | `error` | Meaning | Client behavior |
| --- | --- | --- | --- |
| 403 | `public_ingress_refused` | Peer is outside the loopback/LAN/tailnet posture; nothing admitted | Fix the host; do not retry from a public network |
| 415 | `unsupported_media_kind` | `kind` outside the four admitted kinds | Fix the request; surface to human |
| 413 | `media_too_large` | Over the per-kind cap, or over the coarse cross-kind bound | Do **not** treat `max_bytes` as a size that would be accepted — it may be the coarse bound |
| 413 | `sidecar_part_too_large` | Sidecar beyond any legitimate metadata size | Fix the request |
| 422 | `multipart_invalid` / `media_part_required` / `sidecar_part_required` | Malformed body or a missing part | Fix the request |
| 422 | `sidecar_schema_invalid` | Sidecar fails the admission schema (`violations` included) | Fix the request; surface to human |
| 422 | `content_hash_mismatch` | Received bytes do not hash to `content_sha256`; nothing admitted | Re-read the source and re-hash before resending |
| 409 | `consent_refused` | No active consent grant (HEIM-3); nothing admitted | Surface the reason verbatim; never fall back to a direct FS write |
| 410 | `media_evidence_erased`, state `erased` | The immutable receipt remains auditable but its exact raw evidence was governed-erased | Retain the local original and surface the terminal outcome; do not retry the same transfer identity as an idempotent replay or delete against it |
| 500 | `raw_write_failed`, `admission_event_commit_failed`, `receipt_persistence_failed`, `raw_store_key_unavailable`, `media_cap_misconfigured`, `admission_failed` — all with `state: "not_acknowledged"` | Nothing was acknowledged | Safe to re-send the same `capture_id` + `content_sha256`; admission is idempotent. Retain the original |
| 503 | `receipt_store_unavailable` | The receipt store or raw-state metadata lookup could not be read | Treat as *no information*, **never** as `unknown` or `erased`; retry the read |

The v1 auth posture above is unchanged for these routes: no per-agent identity, LAN/loopback/tailnet
only. The posture is enforced hub-side on the immediate peer and deliberately ignores
`X-Forwarded-For`, so a client behind a relay cannot present itself as local.

**One operator precondition, stated honestly:** admission encrypts through the raw store, so the api
process needs `HEIMDAL_RAW_STORE_KEY`. Provisioning is delivered (#4422): the api process is a
declared consumer of `heimdal.raw-store-key` (`heimdal-api-ingress`, dev/test/prod), the governed
deploy wrapper materializes its secret layer, and an api startup preflight reports the ingress lanes
`unavailable` on `/api/status` before first use rather than letting the lane look healthy. What
remains is the operator step of placing key material into the Keychain item for that consumer per
channel; until that is done for a channel, every admission there still answers
`500 raw_store_key_unavailable` / `not_acknowledged` rather than a receipt. See
`docs/STATUS.md :: Runtime verification`.

### 4.5 Governed meeting lane (session, projection, notes, and finalization)

Implementation: `app/api/routes/heimdal_meeting.py` over the durable ledger, projection,
block-ownership, and finalization modules in `app/heimdal/`. Shipped by CDLM-02/06/07/08 and
consumed by the Bifrost live-meeting surface delivered in bifrost#60. Every route has the §4
LAN/loopback/tailnet posture; none is a public-ingress surface.

**Session and segment identity.** `POST /api/heimdal/meeting/session` takes
`{session_id, device_id, template_selection}` and replays the recorded open for the same
client-minted `session_id`. Media parts join the session through §4.4 sidecar fields
`(session_id, session_seq)`: the ledger admits one content hash per pair, preserves the original on
conflict, and exposes exact gaps through `GET .../segments`. Reconnect clients ask for that durable
gap set and resend only missing segments; they never infer completeness from a local prefix.

**Projection is revisable evidence, not truth.** `GET .../projection` returns sequence-ordered
transcript blocks with explicit gaps and `generic-default@1` analysis blocks. Derived blocks carry
revision, `derived_from`, template, and engine provenance. Template resolution is user selection
over explicitly permitted metadata over the default; the current shipped template set contains
only the default. Late segments create a new convergent revision. No voice, face, diarization, or
other uncertain signal assigns a participant, person, or owner.

**User notes are a separate authority class.** `POST .../user-note` takes a client-minted UUID
`note_block_id`, client-monotonic `revision`, `text`, and `editor_identity`. It is idempotent by
`(note_block_id, revision)` and returns 2xx only after the text is durable and the
`heimdal.meeting.user_note.written` event commits. `user_note` is writable only through the user
editor seam. Analysis, reconciliation, template rerender, and finalization are structurally
confined to `derived_projection`; unknown or conflicting ownership fails closed with the existing
note bytes untouched. The client UI must keep “your notes” separate from “AI keeps updating.”

**Close and final artifacts.** `POST .../close` takes `{final_seq_count}` and never reopens a
session. It triggers idempotent finalization and returns its status explicitly; a gap remains
`needs_attention` with exact missing sequence numbers. The resulting transcript, final analysis,
and verbatim user notes are three separate create-once Sources-zone artifacts. Late admission
supersedes with lineage rather than rewriting the previous artifacts. The iPad presents these
separately and never merges user notes into derived analysis.

This lane grants no entity-merge authority. Bifrost may project candidates and carry an explicit
human approval, but the Hub alone executes and journals entity merges under
`docs/ENTITY_REVIEW_OPERATION_JOURNAL/`; the client never emits a canonical merge command.

## 5. Direct-filesystem write transport (owner-permitted, 2026-07-07)

The owner has ruled that direct filesystem vault writes by external clients are **permitted now** — this extends the writer set that `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` governs (Mac runtime, Obsidian human, iCloud sync, Bifrost clients) with the external-app-agent class, ahead of that model's complete enactment. Enacted via ADR-0056. Permission is not safety; §6 is the discipline that makes the permission survivable while versionless writers remain in migration.

### Where a client may write

- **Declared agent workspace roots** (AGENT-FLOWS §7) are the default write surface for app agents: drafting, synthesis, notes the client itself authors. Output lands at draft-zone standing — observed, classified, never auto-canonical.
- **Human-directed edits to any vault note** are permitted when the human directs the edit in the live session (matching ADR-0055's writer set, which does not restrict which notes the human's own session may touch). The client discipline of §6 (read-fresh, ownership courtesy, atomic replace) applies with full force here, because this is exactly the surface where a collision destroys human-authored prose — and it is exactly the "rewritten note class" ADR-0055 targets for its stale-detection + conflict-staging mechanism once enacted.
- **Bifrost shells** additionally read/write the `_heimdal/**` control surface (settings/interests/consent/attention) — that is their product surface. Its versioned client schema is [`schemas/heimdal-control-notes.schema.json`](../../schemas/heimdal-control-notes.schema.json), mechanically checked against the runtime registry in `app/heimdal/settings_notes.py`. The schema is a published contract view; the registry remains the runtime authority.

### Sources zone — sensor/acquisition landing zone

Sensor-captured material has its own vault zone, separate from the human's quick-capture inbox and
from human-authored notes. The default relative root is `Sources/`, with user-relevant default
subfolders `Sources/Voice memos/`, `Sources/Video & podcasts/`, and `Sources/Articles/`. These are
**settings-resolved defaults**, not fixed paths: the setting key follows the existing
`inbox_dir_rel` convention, and its concrete settings/UI enactment remains follow-on work. Clients
and writers therefore must not hardcode the displayed names.

Only Heimdal-side sensor/acquisition writers create material notes in this zone. App agents and the
capture endpoint are excluded; human edits are allowed but never required. Sources notes are
`create-once` / append-only material: a re-derivation creates a new note, or uses a governed update,
never silently rewrites the original. A Sources note becomes durable knowledge only through the
governed candidate → proposal → human-confirm path (`WriteGuard` → `DecisionToken` →
`AuthorityReceipt`). Moving or renaming the note into the knowledge tree is not a promotion.

The shipped YouTube acquisition candidate is one narrow create-once producer in this zone. Long
source work and rendering hold no zone-wide writer lock. After WriteGuard, it prepares only its own
vault-relative parent chain, stages complete bytes under an extensionless hidden name, and uses the
supported local filesystem's atomic no-replace operation plus parent durability fence. An existing
regular target or atomic race winner is preserved byte-for-byte. A pre-publication failure remains
rebuildable from retained raw evidence; a post-rename fence failure preserves the complete target
for retry. This single-user macOS/Linux mechanism does not make `Sources/` a global initialized
resource, coordinate other producers, or claim network/distributed semantics.

The zone is attention-free by design: it is an archive, not an unread queue or processing
obligation; material reaches the human only through governed Mimer proposals. The owner selected the
default **Sources** on 2026-07-10 from the shortlist Observationer, Källor, Referenser, Corpus,
Underlag, Captured, Records, and Sources. The choice favors intuitive, user-visible names; “Evidence”
was deliberately excluded because it collides with the ontology's `evidence_role`.

### Exclusion list — never direct-write, either family

| Surface | Why |
| --- | --- |
| The capture inbox note (`<inbox_dir_rel>/inbox.md` or `VAULT_CAPTURE_NOTE_REL` override) | It is the runtime's actively-appended governed target; a client rewrite races the governed append and LWW can silently drop a capture. Intake goes through `POST /api/companion/capture` only. |
| The capture inbox — **sensor/acquisition writers** | Sensor material belongs only in the Sources zone; the inbox remains human quick-capture through the governed capture endpoint. |
| The Sources zone (`<sources_dir_rel>/`, default `Sources/`) — **app agents and the capture endpoint** | This archive is reserved for Heimdal-side sensor/acquisition writers; it is not an alternative client workspace or capture target. |
| Companion notes (`⚙️ System/companions/`, legacy `_system/companions/`) | KnowledgePort-only, system-owned (`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md`). |
| System-plane settings/bootstrap notes and other system-owned paths | Runtime-owned via KnowledgePort; a direct edit forks runtime state. |
| `_heimdal/**` — **app agents only** | It is Bifrost's/the runtime's control seam; app agents have no role there. (Bifrost writes it by design, above.) |
| iCloud "conflicted copy" artifacts | Never create, never silently resolve; surface to the human (§6 W8). |

### Provenance on direct writes (the transport's governed-write equivalent)

The filesystem does not enforce attribution (AGENT-FLOWS §4: best effort), so the client supplies it. Every file an external client **creates** in the vault MUST carry a provenance frontmatter block; every substantive edit to an existing note SHOULD append to it:

```yaml
agent_provenance:
  author: <client-id>        # e.g. claude-app, codex-app, bifrost-ios
  model: <model-id>          # where applicable
  written_at: <utc-iso>
  origin: direct-fs
  trace: <trace-id or session ref, if any>
```

This is a v1 convention owned by this contract: advisory to the runtime today (observation-time classification may read it; nothing enforces it), binding on clients now, and the input to the per-agent identity slice (§9 F2). It exists so the AGENT-FLOWS §13 questions ("who wrote this, under what delegation, into which zone") stay answerable without the runtime.

### Bifrost coordinated filesystem access

Per ADR-0055 item 5, Bifrost uses Apple's coordinated-access APIs — `NSFileCoordinator` / `UIDocument` — for vault files, not plain `FileManager` I/O. This preserves offline-first operation while cooperating with iCloud's coordination layer; it does not replace the hub's stale-detection or conflict-artifact responsibilities.

### Entity-review approval boundary (target-state; not shipped)

The planned entity-review operation-journal contract in
`docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md` narrows Bifrost's entity-review role further: an
iPad action may record a proposal-bound approval, rejection, or permitted pre-application undo for
a displayed Hub proposal, but it is never the canonical merge command. The Hub alone canonicalizes
an approval into an operation, executes every register merge, and records the durable outcome. This
paragraph describes the pending EROJ delivery contract only; it does not claim the transport or
runtime behavior is implemented.

## 6. Concurrent-writer safety model

This is the load-bearing section. The writer set over one iCloud-synced vault is now: the Mac runtime, the human in Obsidian, Bifrost shells, and external app agents — plus iCloud sync as a transport that can materialize conflicts as files.

### Substrate guarantee, stated honestly

**Decided and enacted at the shared seams, with progressive caller migration remaining.** `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` (Accepted 2026-07-07, supersedes ADR-0053, resolves #3114) is the owner's ruling on the full multi-writer model: atomic writes everywhere; stale-detection + detect-and-stage conflict artifacts for **rewritten note classes**; last-write-wins retained for **append-only classes**; iCloud conflicted-copy quarantine at ingest; writer-identity/timestamp provenance tagging; enforcement at GATE tier via `WriteGuard`, generalized to also cover `append_note_relative` (closing INV-VW2). VMW-01 (#3450) enacted the shared runtime classification, expected-version request path, receipt provenance, and conflict-artifact grammar. VMW-02 (#3451) consumes that request path at the shared filesystem seam: an initially stale opted-in rewritten write leaves the canonical note unchanged, durably publishes the caller's exact proposal through the shared sibling grammar, and returns its path plus writer provenance in a `conflict_staged` receipt. VMW-03 (#3452) consumes the same grammar at the production vault Markdown iterator, excludes conflict artifacts before watcher/ingest/index parsing, preserves them on disk, and emits a quarantine classification receipt. INV-VW2 was delivered independently by #3129: `append_note_relative` now asserts `WriteGuard` before resolving the port or mutating the vault. VMW-04 (#3453) reconciled INV-VW1/INV-VW3 and the parent acceptance evidence. Migration of remaining versionless rewritten writers remains progressive work in #3570, so this contract does not claim those callers already receive expected-version protection.

### Note-classification contract (ADR-0055 item 6)

All writers consume this table; individual runtime code must not create a competing class mapping. `rewritten` means atomic replace plus the stale-detection/conflict-staging mechanism for callers that supply `expected_version` during the progressive migration. `append-only` means atomic append with no stale check; `create-once` is the Sources-zone variant, where a re-derivation creates a new note rather than rewriting the original.

| Path / note pattern | Class | Contract posture |
| --- | --- | --- |
| `_heimdal/**` frontmatter and full-note writes (except the explicit body-append operations below) | rewritten | Control notes use the published schema; stale detection and conflict staging apply when enacted. |
| body steering entries in `_heimdal/steering.log.md` | append-only | Immutable steering entries append through the governed append seam; bookkeeping frontmatter remains rewritten. |
| body steering entries in `_heimdal/watchlist.md` and `_heimdal/never.md` | append-only | `append_inflow_steering` appends durable in-flow watch/never entries; their frontmatter remains a rewritten control surface. |
| human-authored Markdown outside managed append-only zones | rewritten | Preserve human prose; never silently overwrite a stale version. |
| `⚙️ System/companions/**`, legacy `_system/companions/**` | rewritten | Runtime-owned companion notes; direct client writes remain forbidden. |
| `<inbox_dir_rel>/inbox.md` | append-only | Governed capture endpoint only; direct filesystem writes are forbidden. |
| event-log producer paths | append-only | Append-only event history; no rewritten-note stale check. |
| `Sources/**` (settings-resolved default root) | append-only / create-once | Sensor/acquisition writers create material notes; re-derivation makes a new note, never a silent rewrite. |
| Episode notes (the Episode Note Store's materialized Markdown) | rewritten | Re-cut/re-time and human edits, including `closed`, require rewritten-note protection. |

Today's same-note substrate is progressively enforced. A legacy rewritten writer that omits `expected_version` still takes the versionless migration path and can resolve concurrent edits as silent last-write-wins. A filesystem caller that supplies the raw-byte SHA-256 version it read uses the descriptor-anchored atomic exchange path. If that version is already stale at the first seam comparison, VMW-02 stages the exact proposal as a sibling Markdown conflict artifact without changing the canonical note; the low-level adapter returns `outcome="conflict_staged"`, `conflict_artifact`, `writer_identity`, and `written_at`. The shared production helpers raise `KnowledgeWriteConflict` carrying that receipt by default, so existing callers cannot mistake sibling staging for a canonical success; only an explicitly conflict-aware helper caller receives the staged receipt normally and must branch on `outcome`. Missing targets and races after the first comparison retain the fail-closed exchange/rollback behavior and internal displaced-inode preservation. Append-only operations do not enter the stale path; independently, `append_note_relative` asserts `WriteGuard` before port resolution or mutation (INV-VW2 / #3129). VMW-03 quarantines both iCloud and runtime-staged artifacts at the shared production iterator before ordinary ingestion; VMW-04 reconciled the final INV-VW1/INV-VW3 registry truth.

Therefore: the rules below remain **binding client discipline around the progressively enforced substrate**. They shrink collision windows for direct filesystem clients and versionless legacy writers, and complement the VMW-02/VMW-03 runtime mechanisms for callers that use the shared expected-version seam. They are **binding on external app agents** (the writer class this contract admits) and **recommended for Bifrost during B1** (per the ADR-0056 §3 amendment of 2026-07-11: ADR-0055 superseded ADR-0053 in full, so nothing is "carried forward" — Bifrost's B1 free pass is an **explicit owner extension for the enactment gap**, ending with a forced re-decision (a) before the mechanical-hygiene auto-apply flip (ADR-0048 / G2-3) turns on and (b) immediately on the first observed same-note data-loss incident).

### Client write discipline (normative)

- **W1 — Prefer governed append for durable intake.** Anything shaped like "remember/capture this" goes through `POST /api/companion/capture`. Appends through one governed writer serialize at the runtime and carry receipts; they are the lowest-risk durable write in the system.
- **W2 — Read-fresh, write-promptly, verify-staleness.** Before any whole-file write: read the file and record its raw-byte content hash; keep the read→write window as short as possible; immediately before writing, re-check the hash. Callers using the shared Mimer filesystem seam pass that hash as `expected_version` with their `writer_identity`, so VMW-02 can write atomically or stage an initially stale proposal. A direct filesystem client outside that seam must still re-read and re-apply its edit when the hash changed; its check remains advisory and the TOCTOU window remains real.
- **W3 — Ownership courtesy.** Default to creating and editing files the client itself authored (workspace roots, §5). Edit a human-authored note only on explicit human direction in the live session, and prefer append/patch-shaped edits over whole-file rewrites of prose the human may have open in Obsidian.
- **W4 — Atomic replace.** Whole-file writes land as write-to-temp-then-rename within the same directory, so the watcher and other readers never observe a half-written note. Never leave temp files in the vault on failure.
- **W5 — Idempotency by verification, not by retry — except on the receipted media/meeting lanes.** No client-supplied idempotency key exists on the *text* capture endpoint today (the runtime derives an idempotency key for the outbox *event*, not the write — §9 F5). So for `POST /api/companion/capture` and direct FS writes: after `not_acknowledged` (500) or a transport timeout where the response was lost, the write may have landed. Verify by reading the target before any retry. Direct FS whole-file writes are idempotent by content; appends are not. **The §4.4/§4.5 lanes are the exception:** retain the original/note revision until a durable ack, then resolve ambiguity through the stable capture/session/note identity and the matching receipt or ledger query. Never mint a replacement identity for a retry. `erased` / `media_evidence_erased` is not an ambiguous retry: preserve the original, surface the terminal retention state, and follow an explicitly governed recovery path rather than deleting or silently reminting identity.
- **W6 — Write-ordering vs the watcher.** The watcher detects changes by mtime + sha256 and feeds ingest; the index trails the file. After a write, the file is truth and the index is eventually consistent. Never re-write a file to "fix" perceived index lag, and never treat index state as evidence the write failed.
- **W7 — One transport per note; reconciling FS vs API writes.** The only note both transports touch by design is excluded from FS writes (the capture inbox, §5), so a governed API write and a direct FS write to the same note should not occur under this contract. If a client nevertheless observes it caused such a collision (e.g. it rewrote a note between another writer's read and write), the reconciliation is: the file's current content is the outcome (LWW), the AuthorityReceipt/outbox event remains the truthful record of *what the governed write did at its time*, and the client surfaces the suspected collision to the human rather than silently re-asserting its own version. Receipts are authoritative for what happened, never for what is currently true (AGENT-FLOWS §10).
- **W8 — iCloud conflict artifacts.** If a client encounters a `… (conflicted copy …)` sibling, it must not merge, delete, or adopt it silently: surface it to the human. The production vault Markdown iterator uses the VMW-01 shared classifier to quarantine both iCloud and runtime-staged conflict artifacts before watcher/ingest/index parsing, preserves the artifact on disk, and emits a legible classification receipt (VMW-03 / #3452). VMW-04 / #3453 reconciled this as shipped INV-VW3 enforcement.
- **W9 — Meeting block ownership is not presentation convention.** A Bifrost client keeps user-note edits on the §4.5 editor endpoint and treats transcript/analysis as revisable projections. It must not copy a derived block into a user-note write, rewrite a `user_note` from reconciliation/template/finalization output, or turn an entity approval into a canonical merge command.

### Failure modes and degradation (both transports)

| Condition | Client behavior |
| --- | --- |
| API unreachable | Degrade to read-only over the declared filesystem roots (if granted) and say so. No shadow write queue that replays later without the human (invariant 3: hidden truth in transit). |
| WriteGuard blocked / vault unselected | Surface the structured reason verbatim. Never fall back from a blocked governed write to a direct FS write (invariant 2). |
| `not_acknowledged` (500) | Text capture/direct FS: verify by read (W5). Receipted media/meeting lane: retain local custody and retry/query with the same stable identity (§4.4/§4.5). |
| Retrieval/ask failure | Propagate; never answer from client memory while claiming vault grounding. |
| Suspected same-note collision | Report to the human with both versions' evidence; do not silently re-write (W7). |
| Filesystem access absent | Operate API-only; the contract's API surface is sufficient for capture/retrieve/ask. |

## 7. Health and observability duties

- Check `GET /healthz` (or `/api/status`) before entering a write flow; use `GET /version` to record which runtime build served a session when reporting anomalies.
- Send `x-trace-id` on every call and log it client-side, so a capture, its receipt, and its outbox event are joinable across the seam.
- Surface — verbatim, to the human — every named error state in §4.1. Degradation must be legible (`docs/INTEGRATION_FABRIC_CONTRACT.md` health field): a client that silently absorbs `writeguard_blocked` or `not_acknowledged` violates this contract.
- Direct FS writes have no runtime receipt; the client's own log plus the provenance block (§5) is the audit trail until ADR-0055's item 4 (writer provenance) enactment lands at the substrate.

## 8. Integration-fabric contract fields

Answers per `docs/INTEGRATION_FABRIC_CONTRACT.md` §Contract fields.

### External app agent (Agent runtime, class 10; + External UI shell, class 8, when rendering)

| Field | Answer |
| --- | --- |
| Allowed role | Capability + interface: retrieve/ask over indexed material; governed capture to the vault inbox; drafting/synthesis via direct FS in workspace roots; human-directed note edits; relaying human intent (UI control-action boundary #2475 — transport of intent, no approval loop). |
| Authority limits | The three invariants (§3); plus: no promotion, no lifecycle/frontmatter mutation of human notes beyond human-directed edits, no companion/system-plane/`_heimdal` writes, no capture-inbox FS writes, no runtime-settings mutation. |
| Persistence class | Durable human meaning: only via governed capture or observed workspace/human-directed Markdown at its zone standing. Runtime projection: none owned. External durability (agent memory/caches): opaque, rebuildable, never authoritative. |
| Provenance requirement | `x-trace-id` on every API call; provenance frontmatter block on created files (§5); per-request agent identity is F1/F2 follow-on — until then the capture actor is fixed at `companion.capture` and API-side attribution is honestly weak. |
| Event boundary | API side effects cross via the runtime's outbox events (`capture.inbox.appended` with DecisionToken/AuthorityReceipt ids). FS side effects cross via watcher ingest (mtime + sha256), classified at observation time. No bespoke side channels. |
| Health / observability | §7 duties; failures degrade legibly per §6's table. |
| Replacement strategy | The coupling is this contract's HTTP calls + Markdown-in-vault. Any HTTP-capable agent attaches by implementing the same calls; removing an agent loses no meaning (nothing authoritative lives client-side). Its workspace files remain plain Markdown in the vault. |

### Bifrost native shell (External UI shell, class 8; participates in Human surface, class 1)

| Field | Answer |
| --- | --- |
| Allowed role | Interface: render Mimer/Heimdal surfaces; capture into the receipted outbox; show durable transfer state; record meetings; edit user notes; project revisable transcript/analysis; review/steer/confirm hot paths; read/write permitted vault/control notes (design-of-record: `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md`). |
| Authority limits | The three invariants (§3); the shell transports the human's actions and never originates semantic authority. It cannot mutate `user_note` from a derived context and cannot execute a canonical entity merge; Hub guards and journals those effects. No journey becomes app-only. |
| Persistence class | Captured originals and unacknowledged user-note revisions may live durably client-side only as transfer custody, retained until the Hub's durable receipt. Transcript/analysis caches are rebuildable projections. No client-local meaning becomes canonical. |
| Provenance requirement | `x-trace-id` on API calls; provenance block on created notes (§5); per-device identity is F2 follow-on (audit: "no per-device identity/session model"). |
| Event boundary | HTTP API + watcher ingest, as above. |
| Health / observability | §7; additionally B1 cites ADR-0055, not a client-side invention, as its consistency posture. |
| Replacement strategy | Delete the app, lose nothing: vault + companion set rebuild everything; the contract surface lets a successor shell attach without hub changes. |

## 9. Runtime gaps — feature-breakdown inputs (deferred, not solved here)

Named follow-on work; each routes through `feature-breakdown`/`docs-to-issue`, none blocks v1 clients operating under the postures above:

- **F1 — Capture provenance field + per-agent actor.** The capture schema is `{text}` with `extra="forbid"`; the actor is hardcoded `companion.capture`, so a Claude-app capture and a Bifrost capture are indistinguishable in DecisionToken/AuthorityReceipt/event. Add an optional provenance object to the schema and thread it through the governed chain.
- **F2 — Auth coverage + per-agent/per-device identity (first hardening slice).** Apply the existing `X-API-Key` machinery to the client-facing routes and introduce per-client identity/keys; serves both families (and Bifrost B1's remote posture). Owner-ruled as the first hardening slice, not a v1 blocker.
- **F3 — uuid-resolving note fetch or enriched search payload.** Close the §4.2 uuid→path gap at the API instead of by client-side filesystem enrichment.
- **F4 — API versioning + published OpenAPI for the client surface.** The hub API is unversioned and `api/openapi.yaml` documents 2 of 23+ route modules (audit §3; the surface is still growing); a client-publishable contract needs both.
- **F5 — Client-visible idempotency key on the *text* capture endpoint.** Still open for `POST /api/companion/capture`: no client-supplied key exists there, so a client must verify-by-read after `not_acknowledged`/timeout instead of retrying (§6 W5). **Delivered for the media lane** by #4384 / PR #4400: `POST /api/heimdal/capture/media` takes `(capture_id, content_sha256)` as its client-minted identity and answers a resend with the same `receipt_id` (§4.4), so that lane retries safely and needs no verify-by-read.
- **F6 — Multi-writer consistency progressive caller migration.** The shared ADR-0055 enactment is delivered: #3131 supplies the published note-classification table; VMW-01 supplies the shared request/receipt/provenance/classifier substrate; VMW-02 stages initially stale rewritten proposals; VMW-03 quarantines shared artifacts before ordinary ingestion; VMW-04 reconciles INV-VW1/INV-VW3 and parent acceptance; and #3129 independently closes INV-VW2 by guarding `append_note_relative` at the seam. Remaining #3570 work migrates versionless rewritten writers to opt into `expected_version`; until then those callers still use the recorded last-write-wins migration posture. This contract's §6 discipline complements that progressive enforcement and does not overstate it.
- **F7 — `_heimdal/**` published note-shape schema (audit G3): delivered by #3131.** [`schemas/heimdal-control-notes.schema.json`](../../schemas/heimdal-control-notes.schema.json) publishes the registry's note kinds, paths, authorities, sections, and field-authority split. `tests/heimdal/test_published_control_surface_schema.py` prevents drift from `settings_notes.py`; schema-version evolution remains a future contract change, not a silent runtime edit.

## 10. SBS reconciliation

Per the repo's architecture-artifact convention (binding classification against the operating model and owner docs):

| Claim | Class | Basis |
| --- | --- | --- |
| One hub contract answering per-class fields for a multi-class integration | **Conform** | `docs/INTEGRATION_FABRIC_CONTRACT.md` multi-class precedent (Obsidian) and contract fields answered as required |
| Governed API write chain as described (§4.1) | **Conform** | Restates shipped behavior (`app/api/routes/capture.py`); GOV invariants per `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` |
| Direct-FS participation as mode (c) with observed-write semantics | **Conform** | `docs/AGENT-FLOWS.md` §3/§4/§7 already define the mode; this contract binds clients to it |
| Admitting external app agents to the live writer set | **Extend** | Owner ruling 2026-07-07, enacted via ADR-0056; extends the writer set ADR-0055 governs (supersedes ADR-0053) to a new writer class; VMW-01 through VMW-04 and INV-VW2 are delivered, while #3570 preserves the progressive versionless-caller migration boundary |
| Client write discipline W1–W8 | **Extend** | New client-side obligations; introduces no runtime mechanism, forks no `GOVERNED_WRITE_PROTOCOL`/`OBSIDIAN_KNOWLEDGE_PORT` semantics, and defers to ADR-0055's enactment for real enforcement |
| Provenance frontmatter convention (§5) | **Extend** | New convention on a surface AGENT-FLOWS §4 names as best-effort; advisory to the runtime until F1/F2 land, anticipates ADR-0055 item 4 |
| MCP-transport assumption retired for clients | **Conform** | ADR-0047 (deferred stance) and the audit's A2-class finding; no stance is reopened |

No reshape: no existing boundary, charter, contract, or ADR is altered. The one authority-affecting change (new writer class) is routed through ADR-0056 as required.

## 11. References

- `docs/adr/ADR-0056-mimer-client-contract-and-transports.md` — the enacting decision (T2 closure, transport set, writer-set extension).
- `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` — the decided multi-writer mechanism (supersedes ADR-0053, resolves #3114); VMW-04 reconciled the invariant/parent evidence, and remaining versionless-writer migration is tracked by #3570.
- `docs/audits/YGGDRASIL_ECOSYSTEM_2026-07-06.md` §2/§3/§9/§10/§11 — evidence base (G1–G7, T1–T6, INV-VW1..3).
- `docs/INTEGRATION_FABRIC_CONTRACT.md` — class taxonomy, contract fields, authority rule.
- `docs/AGENT-FLOWS.md` §3/§4/§7/§10/§12/§13 — participation modes, observed writes, zones, provenance rules.
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`, `docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md` — the write machinery this contract rides.
- `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`, ADR-0047 — why MCP is not a client transport today.
- `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` — Bifrost topology design-of-record; Epic B #3020, B1 #3023/`bifrost#1`; ADR-0050.
- `app/api/routes/{capture,search,ask,artifacts}.py`, `app/auth.py`, `app/knowledge/{adapters,write_ops}.py`, `app/components/concurrency.py`, `app/watcher/watcher.py` — implementation evidence (descriptive, not normative; `docs/ARCHITECTURE.md` owns runtime truth).
- `docs/MIMER_VOICE_LOOP/SHARE_TRANSCRIPTION_CAPABILITY.md` — VOICE-02's internal shared-ASR seam: Heimdal capture and Mimer voice-ask reuse `app.media.transcribe.run_asr`; this is not a client transport.
