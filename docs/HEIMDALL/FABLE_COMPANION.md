State: Draft (Fable window design output, 2026-07-05). The living companion document for the Heimdall Fable-5 architecture window: the proposed design for all 8 OPEN problems in `CAPABILITY_CHARTER.md`, anchored in the voice-memo v1 vertical. Advisory until owner-accepted and enacted via CES/ADR; creates no runtime behavior, no schemas-as-shipped, and no GitHub work.
Doc role: Companion / living design thread (Fable window) — prose-mirror contracts + proposed invariants
Authority: Authoritative for the *proposed* Heimdall design within the FIXED constraints of `CAPABILITY_CHARTER.md`. Subordinate to `OWNER_DECISIONS.md` (reserved calls stay reserved; this doc surfaces them, it does not take them), `ECOSYSTEM_SOS_MODEL.md` (container), and the existing SoT contracts it reconciles against (`docs/EVENTS.md`, `docs/KNOWLEDGE_ACQUISITION/*`, `docs/architecture/*`). Claims no shipped reality. Every schema sketched here is a prose mirror; the machine-readable schema (minted at enactment under `schemas/`) will be canonical.
Owner: Architecture / CES stewardship (Rasmus); authored in the Fable-5 window per `FABLE_WINDOW.md`
Temporal class: strategic
Review cadence: event-driven (owner review of this window's output)
Source of truth: this doc + `CAPABILITY_CHARTER.md`, `OWNER_DECISIONS.md`, `ECOSYSTEM_SOS_MODEL.md`, owner scope statement 2026-07-05 (voice-memo-first vertical)

# Heimdall Fable window — capability design (companion draft)

## Read first

- `docs/HEIMDALL/CAPABILITY_CHARTER.md` — FIXED vs OPEN; this doc solves the OPEN set within the FIXED set.
- `docs/HEIMDALL/OWNER_DECISIONS.md` — reserved decisions; §9 below routes back to them.
- `docs/HEIMDALL/ECOSYSTEM_SOS_MODEL.md` — where Heimdall sits (sibling constituent; Layer-2 substrate inventory).
- `docs/EVENTS.md` + `app/services/outbox.py` — the existing (Mimer-internal) event envelope and outbox mechanics this design reuses.
- `docs/KNOWLEDGE_ACQUISITION/README.md` + `SOURCE_PLUGIN_CONTRACT.md` — the KAP backbone this design shares primitives with but does not ride.
- `docs/architecture/metadata-bundle.md`, `functional-ontology.md`, `cross-scope-flow.md` — the Mimer-side contracts Heimdall's published events must project into cleanly.
- `docs/testing/invariant-tests.md` — the registry pattern §8's invariants follow.

**Naming note.** Per the ratified naming (ADR-0044 line): **Yggdrasil = the whole; Mimer = the undivided knowledge-and-cognition constituent (the current system); Heimdall = the sensor constituent; Hugin/Munin are RESERVED/INACTIVE.** `CAPABILITY_CHARTER.md` and `ECOSYSTEM_SOS_MODEL.md` still say "Munin/Hugin" — stale, pre-Mimer text; read **Mimer** wherever they appear. This doc uses Mimer throughout and flags the charter/SoS-model wording as enactment cleanup (#2890). `[conform — to ratified naming; charter text cleanup routed, not performed here]`

**Design stance.** Every load-bearing choice below is anchored in the owner's v1 vertical: **voice memos, deliberately recorded on Apple Watch / iPhone, landing via the existing iOS Voice Memos app + a Shortcut into an iCloud-synced folder — no custom capture app.** v1 is single-party, consent-trivial, batch, low-volume (a handful of memos per day). Always-on/ambient capture, third-party-in-the-room, and multi-sensor fusion are **v2**: each section states what v1 builds, what v1 only contracts, and what is deliberately deferred — and nothing in the design precludes v2.

---

## 1. Event contract / schema / ontology

### 1.1 What an event is

A **Heimdall observation event** is the published, minimized, attributed record that *something was observed in reality*: an interval of time, a set of actors and entities, observed content at a stated fidelity, a consent-state, and a provenance chain back to immutable raw evidence. It is the terminal artifact of Heimdall's responsibility (Charter FIXED #2) and the *only* thing that crosses the raw→published seam by default (FIXED #5).

Two event classes exist and must never be conflated `[extend]`:

1. **Published observation events** — the cross-constituent contract. Topic family `heimdall.observation.*`. These are what Mimer and future constituents consume. Everything in §1.3 is about these.
2. **Heimdall-internal pipeline events** — stage progress, capture receipts, retries. These stay inside Heimdall (mirroring how KAP stage events stay inside KAP) and ride whatever internal mechanics Heimdall wants; they are not part of the constituent seam and are not designed further here beyond conforming to the outbox idempotency discipline.

### 1.2 Reconciliation with the existing outbox envelope

**Recommendation: reuse the `docs/EVENTS.md` envelope verbatim as the outer envelope; all Heimdall-specific structure lives in `payload`.** `[conform — envelope; extend — payload]`

The existing canonical envelope (`event`, `event_id`, `trace_id`, `source`, `timestamp`, `payload`, `meta`, optional `context_dimensions`) already gives Heimdall: a topic key, a dedup identity, trace correlation, emitter attribution, and the `meta.payload_schema` registry tag (KERNEL-08). Reusing it means every existing consumer-side rule (dedup by `event_id`, unknown-field tolerance, schema-registry validation at write and dispatch, no embedding vectors in payloads) applies to Heimdall events with zero adapter cost. The per-topic JSON schema lands (at enactment, not now) as `schemas/events/heimdall.observation.published.v1.schema.json`; this section is its prose mirror.

One envelope field needs a reading rule: the envelope `timestamp` is **emission time** (when Heimdall published), never observation time. Observation time lives in the payload (§1.3 time family). Conflating them is the bitemporal failure §8 HEIM-10 exists to catch.

Alternatives considered:

- **(a) A new Heimdall-native envelope (CloudEvents-style).** Cleaner greenfield, standards-aligned. Rejected: it forks the event vocabulary inside one monorepo, forces a translation adapter at the Mimer boundary on day one, and buys nothing the existing envelope lacks. Standards are adapters, not the ontology (`docs/architecture/functional-ontology.md` §1); if external interop ever matters, a CloudEvents adapter at the boundary is cheap.
- **(b) Make the metadata bundle the event envelope.** Superficially attractive (one envelope everywhere). Rejected: the bundle describes *usable knowledge objects*; events are *operational records of occurrence* (`docs/EVENTS.md` normalization note says exactly this). An event's Mimer *projection* materializes bundle-carrying objects; the event itself is upstream of the bundle. Collapsing them would force every event to claim `authority_state`/`evidence_role` it does not have.
- **(c) Recommended: outer envelope reuse + observation payload contract.** Chosen for the reasons above.

### 1.3 The observation payload (prose-mirrored field table)

Style per `docs/architecture/metadata-bundle.md`: field families, then rules. The schema (at enactment) is canonical; this table is its prose mirror. `[extend]`

| Family | Fields | Notes |
| --- | --- | --- |
| **identity** | `observation_id`, `episode_id`, `sequence`, `revision_of`, `supersedes` | `observation_id` is the stable identity of this observation. `episode_id` groups observations from one continuous capture session (one voice memo = one episode). `sequence` is a monotone integer within the episode. `revision_of` marks re-processing of the same raw evidence through improved stages; `supersedes` marks a correction (§3.5). Both reference prior `observation_id`s — never edit, always append (HEIM-1). |
| **time** | `observed_at_start`, `observed_at_end`, `clock_basis`, `captured_at` | Bitemporal by construction: `observed_at_*` is when reality happened (ISO-8601 with offset); `captured_at` is when the raw evidence reached Heimdall's raw layer; envelope `timestamp` is publication. `clock_basis` names the clock trusted for `observed_at` (`device_metadata` for v1 — the Voice Memos file creation time — `ntp_host`, `inferred`). Uncertainty about time is representable (`clock_basis: inferred` + a confidence axis), never silently faked (HEIM-10). |
| **actors** | `attributions[]`: `{ mention_id, role, resolution, confidence, basis }` | Who was involved. `role` ∈ `speaker`, `subject`, `present`, `recorder`. `resolution` is one of the three attribution states of §3.3 (resolved register ref / ambiguous candidate set / unresolved provisional ref) — never a free-text name as canonical identity (HEIM-11). `basis` names how attribution was made (`capture_context`, `diarization`, `voiceprint`, `stated`, `inferred`). v1: exactly one `speaker` = the operator, `basis: capture_context`. |
| **entities** | `entity_mentions[]`: `{ mention_id, span, surface_form, kind_hint, resolution, confidence }` | First-class non-actor entity resolution (owner emphasis): companies, projects, people-mentioned, places, named things appearing in the observed content. Same three-state `resolution` as actors, against the same register (§3). `span` anchors the mention into `content`. Mentions are immutable observations; the register carries the evolving resolution graph (§3.4). |
| **content** | `modality`, `content`, `content_structure`, `raw_ref`, `withheld[]` | `modality` ∈ `speech` (v1), later `screen`, `location`, `biometric`, `ambient_audio`. `content` is the **minimized published form** — for v1, the attributed transcript text (bounded size; long/continuous content moves to by-reference in v2). `content_structure` carries segment boundaries + per-segment timing/confidence. `raw_ref` is a **reference** into the raw layer (opaque id) — the raw payload itself never crosses the seam (HEIM-4). `withheld[]` declares degraded/omitted spans and why (`third_party_speech`, `consent_degraded`) so absence is explicit, not silent. |
| **confidence** | `confidence`: per-axis block (§2) | Orthogonal axes, each `{ score, method, model_ref, calibration }`. Never a single scalar. |
| **provenance** | `provenance`: `{ sensor, capture_chain[], content_hash, content_identity, stage_versions, raw_ref }` | `sensor` identifies the capture adapter instance (adapter id + version + device). `capture_chain[]` lists every hop the evidence took before Heimdall (v1: `["ios_voice_memos", "icloud_drive", "folder_watch"]`) — the trust boundary is legible per event (§7). `content_hash` is sha256 of the canonicalized published content, stamped in the same durable write as the event (conform to KERNEL-06). `content_identity` is the hash of the **raw** evidence (KAP-compatible join key). `stage_versions` records ASR/attribution/resolution stage versions for replay lineage (§5.3). |
| **sensitivity / consent** | `sensitivity`, `scope_hint`, `consent`: `{ basis, granted_by, granted_at, third_party, grant_ref }` | `sensitivity` reuses the existing `_defs` value family `[conform]`. `scope_hint` names the capture scope stamped at capture (v1: the operator's dedicated high-sensitivity capture scope, §1.5). `consent` is required on every event (HEIM-3): `basis` ∈ `self_record` (v1), `place_optin`, `session_optin`; `third_party` ∈ `none`, `marked`, `detected`; `grant_ref` points into the consent ledger (§6). |

Payload rules (load-bearing, schema-enforced at enactment):

1. **No published event without**: `observation_id`, `episode_id`, `observed_at_start`, at least one attribution, `confidence`, `provenance.content_hash` + `content_identity` + `capture_chain`, `sensitivity`, and `consent`. (Mirrors "no usable object without the core set".)
2. **`raw_ref` is opaque.** It is resolvable only through the policy-gated raw read path (§7); it is not a URL, path, or key.
3. **No embedding vectors, ever.** `[conform — docs/EVENTS.md]`
4. **Withheld content is declared.** A degraded event states what was withheld and why; consumers can reason about absence.

### 1.4 How events relate: episodes, threads, corrections

- **Episode** = one continuous capture session under one consent basis. v1: one voice memo = one episode = (normally) one published observation event. The envelope supports many events per episode (`sequence`) so v2 always-on can publish segment-granular events under a shared `episode_id` without contract change. Granularity is **per-adapter policy, not contract**: the contract fixes the relation (episode → ordered observations), adapters choose the cut. `[extend]`
- **Threads / semantic correlation** (this memo continues yesterday's topic; these three memos are one project) are **downstream read-model concerns**, not Heimdall's. Heimdall correlates only what capture mechanics know (episode, device, place-session). Semantic threading is Mimer projection/retrieval work over the stream — putting it in Heimdall would smuggle interpretation into the sensor (Charter FIXED #2). Events may carry an optional `correlation_hints[]` (e.g. same place-session grant) but hints are advisory. `[conform — interpretation stays downstream]`
- **Corrections** are new events (`heimdall.observation.corrected`, §3.5) carrying `supersedes`; **revisions** (better stage re-runs over the same raw) are new events carrying `revision_of`. Projections must fold supersede/revision chains; the log never rewrites (HEIM-1).

### 1.5 Scope stamping at capture

Every published event carries `scope_hint` + `sensitivity` so the Mimer projection can stamp a valid metadata bundle without inventing meaning (`capture_stamps_scope` conform). **Recommendation:** all v1 voice-memo events land in one dedicated operator-private capture scope with `sensitivity` defaulted high; reclassification into work/project scopes happens downstream via governed flows, never at the sensor. Rationale: the sensor cannot know the audience/policy frame of what it heard; defaulting private-and-sensitive means mistakes fail closed. `[conform — private-by-default, cross-scope only via flow]`

v1 / v2 split: v1 builds the single-event-per-memo shape, one capture scope, inline transcript content. v2 adds segment-granular events per episode, by-reference content for continuous capture, additional modalities — all already representable in this contract.

---

## 2. Confidence model

### 2.1 Orthogonal axes, not a scalar

**Recommendation: confidence is a structured block of named orthogonal axes; there is no single top-level scalar.** `[extend]`

The axes, for v1 speech:

| Axis | Question it answers | v1 producer |
| --- | --- | --- |
| `transcription` | Is the published content a faithful rendering of the raw signal? | ASR segment scores (Whisper avg-logprob mapped to 0..1, marked heuristic) |
| `attribution` | Is the actor assignment correct? | `1.0` by construction for self-recorded single-party (`basis: capture_context`); diarization/voiceprint scores in v2 |
| `entity_resolution` | Is each mention linked to the right register entity? | Per-mention resolver score (§3) — carried per mention, with an aggregate floor on the event |
| `temporal` | Is `observed_at` trustworthy? | Derived from `clock_basis` (device metadata → high; inferred → low) |

Each axis is `{ score: 0..1, method, model_ref, calibration }` where `calibration` ∈ `calibrated`, `heuristic`, `by_construction`. The `calibration` marker is load-bearing: a Whisper logprob and a calibrated probability must never be compared as if commensurable, and downstream policy may legitimately treat `heuristic 0.9` as weaker than `calibrated 0.7`.

Why not one scalar: a scalar launders orthogonal failure modes into one number. "Perfect transcript, unknown speaker" and "garbled audio, certain speaker" both collapse to ~0.7 and downstream policy can no longer distinguish *what* is uncertain — which is exactly the distinction that decides whether an event is safe to cite, safe to attribute, or safe to timestamp a commitment against. Attribution honesty (HEIM-6) is only enforceable per-axis.

Why not include an `interpretation` axis: **interpretation certainty is deliberately excluded from Heimdall's contract.** The charter names it as likely orthogonal — it is, and precisely because it is orthogonal it belongs to whoever interprets. Heimdall ends at attributed observation (FIXED #2); summaries, claims, and action-item extractions are downstream (KAP-style extractor or Mimer cognition) and stamp their own confidence under the existing derivation fields (`ARTIFACT_METADATA_CONTRACT.md` §11 `confidence`). A sensor publishing interpretation confidence would be claiming cognition it must not own. `[conform — boundary honesty]`

Alternatives considered:

- **(a) Single scalar** — simplest, matches the existing single `confidence` derivation field. Rejected as primary model (lossy, above); note the Mimer projection MAY compute a scalar floor (min across axes) when filling the legacy `confidence` derivation field, declared as a downgrade-only summary.
- **(b) Coarse enum bands (high/medium/low per axis)** — robust against false precision. Rejected as the storage model (destroys replay comparability between stage versions) but endorsed as the *presentation* layer: human surfaces should render bands, not decimals.
- **(c) Full probabilistic lineage (per-token distributions, Bayesian fusion)** — over-modeling for a personal sensor; nothing downstream can consume it. Rejected (TCD).

### 2.2 How downstream must treat confidence

Contract rules (enforced by invariants HEIM-6 and the Mimer projection contract):

1. **Never silently upgraded.** A projection or consumer may downgrade or pass through a confidence; the only way a score improves is a new revision/correction event from re-processing (better model, human confirmation). Human confirmation of an attribution is itself a correction event with `basis: stated`, `calibration: by_construction`.
2. **Propagation is per-axis or min, never max.** A derived artifact citing an event inherits at most the event's per-axis scores; a summary over many events inherits at most the minimum of what it actually used.
3. **Thresholds are consumer policy, not Heimdall's.** Heimdall publishes low-confidence events rather than suppressing them (an unpublished observation is invisible uncertainty — worse). What a consumer does at `transcription < x` is that consumer's declared policy; the promotion gate (HEIM-8) is where low confidence must bite hardest.
4. **Low attribution confidence blocks canonical attribution downstream.** A projection must not present an `ambiguous`/`unresolved` actor as a named person/entity in any human surface without marking it as unresolved.

v1 / v2: v1 ships `transcription` + `attribution(by_construction)` + `entity_resolution` + `temporal`. v2 adds diarization/voiceprint scores under `attribution` and per-modality axes — additive, no contract change.

---

## 3. Attribution + entity resolution (and the register contract)

### 3.1 The coupling model: immutable mentions, evolving register

The load-bearing design decision `[extend]`:

> **Events carry immutable mention records with resolution refs; the shared register carries the mutable resolution graph. Identity improves by register evolution and correction events — never by editing the stream.**

A published event says "at 09:12 the operator mentioned surface form 'Northvolt-projektet', resolved to `ent:prov:7f3a…` with 0.62". That statement is forever true *as an observation of the pipeline's state at publication*. When the register later merges `ent:prov:7f3a…` into canonical `ent:2b91…` (the actual project), every consumer resolving through the register's redirect chain gets the improved identity — with the original event untouched. Event-level resolution errors (mention linked to the *wrong* entity) are fixed by correction events (§3.5). This is late binding for identity: append-only stream + convergent register.

### 3.2 The minimal register contract (Entity Register v0)

No register exists in code; only the `Concept` ontology stub (`concept_id`, `label`, `aliases` — `docs/architecture/functional-ontology.md` §3). D-IDENTITY fixes the register as shared Layer-2 substrate. **The register contract below is the minimal thing Heimdall needs; it is deliberately `Concept`-compatible — register entries are the operationalization of SIP's `Concept` for named entities, extended with kind, lifecycle, and resolution semantics — extension, not a fork.** `[extend — of the Concept stub; ownership/governance reserved, R-IDENTITY-OWNER]`

Register entry (prose mirror):

| Field | Meaning |
| --- | --- |
| `entity_id` | Stable id. Two id classes: canonical (`ent:<uuid>`) and provisional (`ent:prov:<uuid>`). Provisional ids are first-class and citable — they are how "unknown but recurring" is represented. |
| `kind` | `person`, `organization`, `project`, `place`, `agent`, `thing`. Extensible family; owned by the register contract, not by any one constituent. |
| `label`, `aliases[]` | Canonical label + surface forms. `[conform — Concept fields]` |
| `lifecycle` | `provisional` → `canonical` → `merged`. `merged` entries carry `merged_into` (redirect chain; consumers must follow it). Entries are never deleted — merged, deprecated, never removed (identity refs in the append-only stream must always resolve). |
| `sensitivity` | The register itself is high-sensitivity substrate (§7.4): it is a map of everyone and everything in the operator's life. Reads are governed. |
| `provenance` | Who/what minted or merged the entry, when, on what basis — register mutations are themselves receipted events (`register.entity.minted/merged/aliased`). |

Operations Heimdall needs (the whole v0 API surface):

1. `resolve(surface_form, kind_hint, context) → resolved(entity_id, confidence) | ambiguous(candidates[]) | unresolved` — resolution against labels/aliases + context. v1 resolver: LLM-based mention extraction and matching with the register as the candidate universe `[conform — LLM-classification-over-heuristics]`, deterministic acceptance rule on top (the gate stays deterministic).
2. `mint_provisional(surface_form, kind_hint) → ent:prov:<uuid>` — unknowns become durable provisional entities immediately, so recurrence is linkable from the first sighting.
3. `merge(from_id, into_id)` / `assert_alias(entity_id, alias)` — the convergence operations. **Merge is a governed mutation**: agent-proposed, human-confirmed by default (a wrong merge corrodes identity everywhere — `propose_when_uncertain` applies). Merge authority is part of R-IDENTITY-OWNER (§9-g).
4. `resolve_redirects(entity_id) → entity_id` — follow merge chains; every consumer of historical events uses this.

### 3.3 Representing unknown and ambiguous

Three resolution states, on every attribution and every entity mention (HEIM-6, HEIM-11):

- `resolved`: one `entity_id` + confidence. Only state a consumer may present as a named identity.
- `ambiguous`: ranked `candidates[]` (each `entity_id` + confidence), no winner asserted. Downstream surfaces render "possibly X or Y"; the disambiguation UI action produces a correction event.
- `unresolved`: a freshly minted (or matched) provisional `entity_id` + the surface form. Never a bare string: even the unknown is an id, so the third sighting of "Anna från gymmet" links to the same provisional entity as the first.

Guessing is structurally impossible to hide: a resolver that wants to assert identity must put a ref in `resolved` with its score and method on the record.

### 3.4 Non-person entities are the same machinery

Companies, projects, places, named systems ride the identical mention → resolve → register path with a different `kind`. This is deliberate (owner emphasis): the register is the join layer that lets a memo mentioning "the Heimdall design" link to the same project entity as a calendar event and a note. No separate "topic tagging" mechanism — one register, one resolution contract, all kinds. `[extend]`

### 3.5 Correction-as-new-event

Topic `heimdall.observation.corrected` (schema at enactment; prose mirror): `{ supersedes: observation_id, corrects: mention_id | attribution_id | time | consent, replacement: <same shape as the corrected fragment>, basis, actor }`. Rules:

1. Corrections are published events with full provenance (who corrected, on what basis — `stated` human corrections are the strongest evidence in the system).
2. Projections MUST fold corrections before presenting (a surface showing a superseded attribution unmarked is a defect).
3. Corrections can chain; the fold is last-correction-wins per corrected fragment, deterministic by `(sequence of publication)`.
4. Register merges do NOT require correction events (redirects handle them); only wrong-entity links do.

### 3.6 Build-now vs stub (recommendation)

**Build the register v0 before the first published event.** Rationale: retrofitting is the one thing the append-only model makes expensive — events published with bare-string mentions would need a mass correction wave to become linkable, and v1's entire value ("link everything") depends on refs existing from the first memo. The v0 scope is genuinely small (one table + four operations + provisional minting); what is deferred is everything hard: voiceprints, cross-constituent register federation, automated merging, governance UI. Surfaced as owner decision §9-b because D-IDENTITY makes the register shared substrate (R-PROMOTE adjacent) and its governance is R-IDENTITY-OWNER.

Alternatives: **(a) stub for v1** (publish surface forms, add refs later) — ships days earlier, but poisons the stream with unlinkable strings and buys a correction-wave debt; rejected. **(b) full Layer-2 register with governance, federation, UI first** — months of substrate before one memo flows; rejected (TCD; one-vertical-loop). **(c) recommended v0-before-first-event** — minimal but real.

v1 / v2: v1 = register v0 + LLM resolver + provisional entities + human-confirmed merges via correction/merge proposals. v2 = voiceprint-backed person resolution for third parties (consent-gated), place register entries bound to consent sessions, automated merge proposals with confidence gates.

---

## 4. Event-bus choice

### 4.1 What v1 actually needs vs what the outbox is

The existing DB outbox is a **work queue**: single logical consumer, `delivered_at` completion, FIFO poll, no per-consumer cursor, no replay, no DLQ-as-first-class. That is the right shape for "drive the Mimer worker" and the wrong shape for a **canonical constituent stream**, which needs: append-only permanence, *multiple independent consumers*, and *replay from an arbitrary point* (a new read-model must be able to rebuild from event zero — that is what "downstream constituents are read-models" means, FIXED #1/#3).

v1 volume makes the physical answer easy: a handful of memos per day is nothing. The design question is the *contract*, because the contract is what v2 inherits.

### 4.2 Recommendation: Heimdall-owned append-only log + per-consumer cursors, DB-native, outbox-disciplined

`[extend — generalizes the outbox pattern; does not change outbox ownership]`

- **The Heimdall observation log** is the canonical stream: an append-only Postgres table in the same database (monorepo, no split-trigger fired), rows = published events in envelope form, insert-only (no `delivered_at`, no updates, ever — enforced by grant/trigger at enactment).
- **Publication** conforms to the outbox write discipline: mandatory deterministic idempotency key via the shared `derive_idempotency_key(topic, source_id, content_fingerprint)` helper with `source_id = observation_id` and fingerprint = `content_identity ‖ stage_versions` — so a crash-retry of the same publication dedups, while a re-process with improved stages produces a *new* revision event by construction (different `stage_versions` → different key). Schema-registry validation at write, `meta.payload_schema` stamping. `[conform — KERNEL-02/KERNEL-08 discipline]`
- **Consumption** is log-and-cursor: each consumer (v1: exactly one, the Mimer projector) owns a durable `(consumer_id, cursor)` position and polls forward. Replay = rewind your own cursor; it cannot affect other consumers or the log. Delivery is at-least-once; consumer idempotency by `event_id` per the existing consumer contract. `[conform]`
- **Ordering**: total order within an episode by `sequence`; cross-episode order is `(created_at, id)` best-effort — consumers must not assume global causal order (two devices can capture concurrently in v2).
- **Backpressure** v1: none needed (batch, low volume); the contract point is that *the log absorbs, consumers lag* — a slow projector never blocks capture or publication. v2 always-on adds: bounded capture-side buffering in the adapter, publication-rate observability, and (only if measured volume demands) partitioning or a stream broker **behind the same publish/cursor contract** — the contract is the stable thing, the transport is swappable (contract-first, module-lazy `[conform]`).
- **The existing outbox is untouched.** Mimer's internal machinery keeps its queue; the Mimer projector consumes the Heimdall log via cursor and drives whatever internal outbox work it needs. No cross-constituent writes into each other's tables: Heimdall writes only its log; Mimer reads the log and writes only its own state. The seam is the log contract + read access, directional by construction.

### 4.3 Alternatives and trade-offs

- **(a) Reuse the outbox table directly** (Heimdall inserts into `outbox`, worker dispatches `heimdall.*` topics). Cheapest to ship — and wrong: single-consumer `delivered_at` semantics can't serve sibling read-models; rows-as-queue is not rows-as-canonical-log; and it makes Heimdall's canonical stream a Mimer-internal implementation detail, silently demoting Heimdall to a Mimer subsystem (violates FIXED #1). Rejected on architecture, not effort.
- **(b) Stream-native broker now** (NATS JetStream / Redis Streams / Kafka). Real replay/consumer-group semantics off the shelf, honest v2 posture. Rejected for v1: new always-on infrastructure on a 4 GB Colima host for ~5 events/day; a second persistence technology to operate, back up, and secure inside the raw-data trust boundary; and the DB-native log meets every stated v1 requirement. Named as the *designated v2 escape hatch* — the publish/cursor contract is written so a broker can implement it without consumer changes; adopting one is a §4.2 transport swap plus an ADR, not a redesign. Split-trigger note: if the privacy threat model ever requires Heimdall on separately credentialed infrastructure (SoS model §4 trigger 2), the broker question reopens as part of that move.
- **(c) File/JSONL-based stream over the synced vault** — rejected outright: file-sync is never an execution bus `[conform — KAP §SBS classification]`, and raw-adjacent event data must not ride iCloud in cleartext.

v1 / v2: v1 builds the log table + publish path + one cursor consumer. v2 contracts already held: multi-consumer cursors, transport swap seam, backpressure observability.

---

## 5. Heimdall vs KAP

> **Revised by owner decision §9-k (2026-07-05):** the owner has since confirmed **Heimdall = the ecosystem ingestion organ** (watch → fetch → transcribe → attribute for *all* external sources, not just voice). This demotes the §5.1 records-of-reality-vs-authored-content line from an *ownership boundary* to an event *typing*, and collapses §5.2's "separate backbones" toward one Heimdall acquisition backbone with Mimer downstream. §5 is retained for its reasoning; §9-k is the standing decision (a `reshape` → CES/ADR).

### 5.1 The boundary question, made concrete by the voice memo

Is a deliberately-recorded voice memo a Heimdall capture (observation) or a KAP source (authored artifact → candidate)? Both readings are defensible: the memo is discrete, batch, deliberately created, lands as a file — KAP-shaped mechanics; KAP even already specs an ASR stage (KA-02). But the memo also demands attribution, consent-state, episode time semantics, and the raw privacy seam — none of which KAP has or should grow.

**Recommendation: the voice memo is a Heimdall capture. The discriminator is the nature of the claim, not the mechanics of arrival** `[extend — proposed boundary rule]`:

> **KAP acquires *authored content* whose value is the content itself, detached from the moment (a video, a paper, a feed item). Heimdall captures *records of reality* where when/who/where is load-bearing (something happened, someone said something, at a time, in a context).**

A voice memo is a first-party record of lived reality: its provenance is "reality, via my sensor"; its timestamp, speaker, and mentioned entities are the point. Run it through KAP and the event semantics die at the door: KAP's `RawEvidence` has no consent-state, no attribution, no episode, no encrypted raw seam, and its terminal artifact (candidate) erases the fact-of-occurrence that makes a memo useful to a timeline or an agent's situational awareness. The cost of the Heimdall routing is building capture machinery KAP would have given for free — accepted, because that machinery is exactly what the Heimdall window exists to build.

Edge case honesty: a memo that is pure dictation ("draft: email to Anna about the invoice") is *authored content in an observational wrapper*. It still enters as a Heimdall capture (the sensor cannot classify intent at the seam, and must not — that is interpretation), and the Mimer projection turns it into a candidate note through the normal triage path. **The backbones meet at the candidate, not at acquisition** (§5.3): downstream of a published event, an "authored-artifact-shaped" observation flows into exactly the same candidate → triage → promotion path a KAP acquisition feeds. Nothing is lost; the event wrapper adds the timeline fact for free.

### 5.2 Backbone recommendation (D-BACKBONE): shared primitives, separate backbones

**Heimdall does not ride KAP's acquire→candidate→publish pipeline. Both backbones conform to a shared set of Layer-2 provenance/replay primitives, promoted from KAP's contracts.** `[extend — substrate promotion per SoS model §5; enactment is R-PROMOTE, owner-gated]`

The shared primitives (the "shared provenance standard" the owner fixed as guardrail, made concrete):

| Primitive | KAP form | Heimdall form |
| --- | --- | --- |
| Immutable raw evidence | `RawEvidence`, Level-`raw` | Raw layer record (encrypted, isolated — stricter posture, same immutability) |
| Content identity join key | `content_identity` | `content_identity` (identical semantics: same raw ⇒ same key) |
| Only one component touches the source | source plugin (egress boundary) | capture adapter (ingress boundary) — HEIM/KAP mirror of the same rule |
| Stage-local replay, zero source egress | re-run stages keyed on `content_identity` | re-run ASR/attribution/resolution on stored raw; **zero re-capture**, revision events with `stage_versions` lineage |
| Per-stage idempotent events | KAP stage events on the outbox | Heimdall-internal pipeline events (§1.1), same idempotency discipline |
| Provenance stamped with the durable write | KERNEL-06 pattern | identical (`provenance` written in the same statement as the event insert) |

Why separate backbones: the two constituents have different terminal artifacts (candidate vs published event), different sensitivity postures (KAP raw = re-fetchable public content; Heimdall raw = the most sensitive data in the ecosystem, encrypted + policy-gated), different lifecycles (KAP pull/scheduled; Heimdall capture-driven), and different governance surfaces (consent has no meaning for a YouTube caption). Forcing one backbone means either weakening Heimdall's seam to KAP's posture or dragging KAP's public-content pipeline behind Heimdall-grade controls — both bad trades.

What is concretely shared anyway: the **ASR engine** `[extend — owner-directed 2026-07-05; see §9-j]`. The system already has it — `app/media/transcribe.py` (faster-whisper): `run_asr()` is the reusable engine, while `download_audio` (egress) + `_record_outbox(kind=transcript)` are KAP's wrapper around it. The owner's rule is "no two whisper instances." **Resolution: the ASR engine is a shared Layer-2 substrate as a *library + model cache*, invoked in-process inside each constituent's own trust boundary — never a shared ASR *service* that raw audio is shipped to** (a shared service would puncture Heimdall's seam, FIXED #5). This preserves the seam exactly as well as a Heimdall-owned engine: Heimdall invokes the shared library on raw audio *inside its seam* (raw never leaves), Mimer/KAP invoke the same library on their own (public) content. Concrete refactor: extract `run_asr` + model cache to `app/media/asr_engine.py` (shared substrate); KAP keeps its wrapper; Heimdall adds an in-seam wrapper that emits an observation event instead of a `kind=transcript` record; additively expose per-segment `avg_logprob`/`no_speech_prob` for the transcription confidence axis (§2). Mechanism sharing without pipeline merging — and without a second instance.

Alternatives:

- **(a) Generalize KAP into a universal acquisition platform; Heimdall sensors become a source-plugin class.** One backbone, one contract set, plugins all the way down. Rejected: smears the raw privacy seam across a contract whose raw layer is neither encrypted nor consent-aware; makes attribution/consent optional plugin metadata instead of structural requirements; and inverts the SoS decision (Heimdall becomes a KAP tenant, not a sibling). This is the seductive wrong answer.
- **(b) Fully separate, including separate provenance vocabulary.** Maximum autonomy. Rejected: violates the fixed shared-provenance guardrail and forks `content_identity`/replay semantics the ecosystem needs to be able to join across constituents.
- **(c) Recommended: separate backbones on shared promoted primitives.** The middle that keeps the seam sharp and the provenance joinable.

v1 / v2: v1 promotes nothing formally (primitives are conformed-to by construction; promotion ADR is enactment work, §9-a). v2: when a second sensor modality lands, the shared-primitives layer is re-examined for formal Layer-2 promotion (R-PROMOTE).

---

## 6. Consent model (mechanism)

The posture is FIXED (single-party; always-on OFF by default; opt-in per place/session; third parties marked/degraded). This section designs the mechanism. `[extend — mechanism within fixed posture]`

### 6.1 The consent ledger

An append-only ledger of consent grants and revocations, held inside Heimdall, mutated only by explicit operator action, and itself evented (`heimdall.consent.granted` / `heimdall.consent.revoked` on the observation log — consent changes are observations about the operator's declared will).

Grant record (prose mirror): `{ grant_ref, basis, scope: (place | session | device+adapter), granted_by, granted_at, expiry, capture_profile, third_party_policy }`. `capture_profile` names what may be captured under this grant (modalities, degradation rules); `third_party_policy` ∈ `degrade` (default), `mark_only` (requires explicit per-session choice, v2).

Three bases:

1. **`self_record`** (v1): the act of deliberately recording *is* the grant. Modeled as one standing ledger entry per capture adapter ("operator-initiated recordings on this adapter are consented"), not per-memo ceremony. Consent for v1 is trivially satisfied — but it flows through the same ledger and stamps the same `consent` block on every event, so the mechanism is exercised from day one and v2 inherits it working.
2. **`session_optin`** (v2): an explicit, bounded "capture this meeting/conversation" activation; expires with the session; requires a `third_party_policy` choice at activation.
3. **`place_optin`** (v2): a standing grant bound to a place entity in the register (§3) — "capture is on in my office"; always-on capture exists *only* as the union of active place/session grants (the OFF-default is structural: no grant, no capture, HEIM-3).

### 6.2 Capture-time enforcement

The capture adapter resolves an active grant **before** admitting raw evidence; no grant → the adapter refuses ingestion and surfaces the refusal (loud, not silent drop). Every raw record and every published event carries `consent.grant_ref`. There is no code path from signal to raw store that bypasses the ledger check — this is the HEIM-3 enforcement point, and it is testable (a capture attempt with no active grant must fail in CI).

### 6.3 Third-party detection and degradation

v1 posture: memos are single-party by declaration, but the guard still runs — the ASR/diarization stage checks for multiple speakers. If detected: the event is stamped `consent.third_party: detected`, and third-party speech is **degraded by default**: not transcribed into published content; represented as a `withheld[]` span (`reason: third_party_speech`) plus an `attributions[]` entry with `role: present`, `resolution: unresolved` (or resolved *only* via a pre-existing consent-linked identity in v2). The operator's own speech in the same memo publishes normally. Raw retains the full signal behind the seam (D-PRIVACY: the owner chose retroactive re-analyzability; a later, consent-satisfying resolution — e.g. the third party grants consent — is a revision event, not a re-capture).

Important distinction the mechanism encodes: **mentions of people are not third-party capture.** The operator recounting a meeting ("Anna said the deadline moved") is single-party speech about others — published, with "Anna" as an entity mention. It is the third party's *voice/signal* that triggers degradation. `[extend — boundary rule]`

v2 adds: voiceprint-assisted detection, per-session `mark_only` escalation (owner explicitly chooses richer capture for a consenting group), and consent entities in the register (a person entity can carry a recorded consent state, R-EXTERNAL-adjacent — reserved).

### 6.4 Revocation and already-captured data

Revocation event → three distinct effects, honestly separated:

1. **Future capture**: the grant lapses immediately (ledger is checked at capture; nothing more needed).
2. **Raw layer**: revocation triggers hard deletion of covered raw records within the bounded hard-retention window (D-RETENTION) — raw is the one layer where true erasure exists, by design.
3. **Published events**: the log is append-only (HEIM-1); events are not unpublished. Revocation publishes a `heimdall.consent.revoked` event naming the covered episodes; **projections MUST suppress** covered content (`suppression_state` exists in the metadata bundle for exactly this `[conform]`), and the minimization seam (HEIM-4) bounds the damage — what was published was already the minimized, degraded form. This tension (append-only vs erasure) is real and is stated, not hidden: if legally-effective erasure of published events is ever required, that is R-EXTERNAL/R-RETENTION owner territory (§9-e).

---

## 7. Trust / threat model

Heimdall raw is the most sensitive data in the ecosystem. This section is written to be red-teamed; residual risks are stated, not massaged.

### 7.1 Assets and trust boundaries

Assets, most→least sensitive: (A1) raw audio; (A2) the entity register (a map of everyone/everything in the operator's life — sensitivity is *aggregate*: each entry is mild, the graph is not); (A3) published events (minimized but still private life-detail + timing metadata); (A4) the consent ledger; (A5) attribution/resolution models (voiceprints in v2).

Trust boundaries crossed in v1, in order: device (Watch/iPhone) → **Apple iCloud** → mac-mini host filesystem → Heimdall raw store (encrypted at rest) → [ASR/attribution stages, local] → observation log (DB) → Mimer projector → vault/companion surfaces.

**Stated honestly:** the v1 capture chain transits Apple's cloud *before* Heimdall's seam begins. Raw audio in iCloud is inside Apple's trust domain (consistent with the existing vault-on-iCloud posture, but audio is more sensitive than notes). The Heimdall raw seam begins at ingestion; hardening the pre-seam hop (direct device→host transfer, e.g. Tailscale-local shortcut upload) is a named v2 item, and accepting the v1 iCloud transit is an owner acknowledgment (§9-h). `capture_chain[]` (§1.3) makes this legible per event forever.

### 7.2 Adversaries and failure modes → mitigations

| # | Adversary / failure | Attack or failure mode | Mitigations (design-level) |
| --- | --- | --- | --- |
| T1 | External attacker with host access | Reads raw store / DB wholesale | Raw encrypted at rest with keys held outside the DB and outside the raw volume (FIXED #5); bounded hard retention shrinks the window (D-RETENTION); raw store on the single trusted host, never on synced storage; DB holds refs + minimized events, not audio. Residual: a root-level live compromise of the one host defeats at-rest encryption — the real counter is the SoS split-trigger 2 (separately credentialed raw host) which this design does not fire but names. |
| T2 | Over-permissioned / confused-deputy downstream agent | Exfiltrates via a legitimate CrossScopeFlow grant; chains a raw-read grant with an export path | Raw reads only via CrossScopeFlow grant + receipt, no ungoverned path (HEIM-5); `export` is its own operation, never implied (`cross-scope-flow.md` §2 `[conform]`); **grants do not compose** — material obtained under a raw-read grant carries its provenance and sensitivity, and an export of it requires an export grant evaluated against that provenance (proposed invariant HEIM-9-adjacent, §8 HEIM-12/HEIM-5); receipts make chains auditable after the fact. Residual: a trusted agent granted both read and export *is* authorized — governance quality, not mechanism, is the control; proportional-governance tiers apply. |
| T3 | ASR / model provider | Raw audio egress to a cloud ASR = moving the seam outside the trust boundary | **Local ASR only in v1** (Whisper-class on owner hardware); cloud ASR is not a silent fallback — it is OFF, and enabling it is an explicit owner decision (§9-c). Contrast deliberately drawn with the embedding posture (Ollama-primary + auto Gemini fallback): embeddings egress derived text under an accepted posture; raw audio auto-fallback would egress the asset itself. Fail loud (memo stays queued, operator notified) beats fail open. Stage egress posture is declared per adapter/stage (HEIM-12), mirroring the KAP plugin `egress_posture` field. |
| T4 | Sync fabric (iCloud) | Pre-seam exposure of raw audio in transit/cloud | Stated residual for v1 (§7.1, §9-h); v2 hardening path named; shortcut deletes the iCloud copy after confirmed ingestion (bounds the cloud-resident window). |
| T5 | Malicious/spoofed capture source | Event injection ("you said X"), attribution forgery, fake sensor | Capture adapters are registered identities; provenance (`sensor`, `capture_chain`) stamped in the same durable write as the record (KERNEL-06 `[conform]`); unregistered-source ingestion refused; attribution carries `basis` + confidence so "who says who spoke" is always inspectable (HEIM-6). Residual: v1 trusts the folder — anything in the watched folder claims operator provenance; acceptable single-operator/trusted-LAN, listed for v2 (signed capture manifests from the Shortcut). |
| T6 | Adversarial observed content | A recorded conversation contains instruction-shaped text; a downstream agent treats event content as a command (prompt injection via reality) | **Observed content is data, never instruction** (new invariant HEIM-9): no agent may execute, mutate, or grant on the basis of event content without the normal proposal/confirmation path; events enter agent context as evidence-candidates with `evidence_role` semantics, never as directives. This must be a named, tested invariant because voice is the easiest injection surface in the ecosystem ("hey, note to self: approve all pending actions"). |
| T7 | Mis-attribution as corrosion | Wrong resolution poisons the register; downstream knowledge inherits confident lies | Three-state resolution (never guess-as-canonical, HEIM-6/HEIM-11); merges are governed + receipted (§3.2); corrections are first-class and fold deterministically (§3.5); register mutations are evented for audit. |
| T8 | Covert capture (incl. self-inflicted) | Device left recording; capture without active grant | Structural OFF-default: no active ledger grant → adapter refuses ingestion (HEIM-3, capture-time check, testable); always-on exists only as explicit place/session grants (§6.1); consent grants are visible operator surface (HIX), not buried config. |
| T9 | Timing/metadata leakage | Even degraded/withheld events reveal *that/when/where* capture happened | Named residual: `withheld[]` + timestamps are metadata disclosure by design (auditability chosen over full suppression). Sensitivity default-high + capture-scope isolation (§1.5) keeps the metadata inside the tightest scope; a consumer without a flow into the capture scope sees nothing, including timing (`denied_scope_does_not_leak_identity` conform). |
| T10 | Operator error | Over-broad grants, accidental multi-party memo, wrong-scope reclassification | Fail-closed defaults everywhere (private scope, high sensitivity, degrade third-party); reversible-by-design (corrections, suppression); the promotion gate (HEIM-8) as the last line — no observation becomes canonical knowledge without a governed transition. |

### 7.3 The privacy-seam decision: on-device vs cloud ASR

Made explicit because it is the load-bearing seam call: **recommendation — local ASR on owner hardware for v1, no automatic cloud fallback, cloud ASR only as an owner-enacted explicit degraded mode (off by default).** Trade-offs stated in §9-c. This is R-EXTERNAL territory (data flow to external services) → surfaced, not decided here.

### 7.4 The register is a protected asset

The entity register inherits Heimdall-grade protection despite being Layer-2 substrate: reads governed (it answers "who is in this life"), mutations receipted, no bulk export operation exists in its contract. `[extend]`

---

## 8. Fitness invariants

House style per `docs/testing/invariant-tests.md`. All entries are `future_runtime` or partially `schema_enforced`-at-enactment today (nothing here is shipped); test paths are the *designated* future homes under `tests/invariants/`. Enforcement-level vocabulary conforms to the registry categories. `[extend — new registry entries; registration itself is enactment work]`

### heim_append_only_truth (HEIM-1)

- **Purpose:** A published event is immutable; corrections and revisions are new events (`supersedes`/`revision_of`), never edits or deletes of log rows.
- **Protected principle:** Charter FIXED #3 (event-log-vs-projection); doctrine — storage preserves meaning.
- **Affected boundaries:** Heimdall log (constituent-internal); PDM/SIP on the Mimer projection side.
- **Enforcement level:** `future_runtime` + `schema_enforced` in part at enactment (no update/delete grant on the log table; correction topic schema requires `supersedes`).
- **Future test path:** `tests/invariants/test_heimdall_stream.py::test_append_only_truth`.

### heim_provenance_survives (HEIM-2)

- **Purpose:** Every published event and every downstream projection of it resolves back to raw evidence: `content_identity` + `raw_ref` + `capture_chain` present at publication and preserved through Mimer projection (`derived_from` chain intact).
- **Protected principle:** Charter FIXED #8; `provenance_survives_derivation` (extends it upstream to the sensor).
- **Affected boundaries:** Heimdall pipeline; SIP, DRI on projection.
- **Enforcement level:** `schema_enforced` at enactment (required provenance family) + `future_runtime` (projection-side chain check).
- **Future test path:** `tests/invariants/test_heimdall_stream.py::test_provenance_survives`.

### heim_consent_gated_capture (HEIM-3)

- **Purpose:** No raw ingestion without an active consent-ledger grant; always-on is structurally impossible without explicit place/session grants; every event carries `consent` with a resolvable `grant_ref`.
- **Protected principle:** Charter FIXED #4 (D-CONSENT).
- **Affected boundaries:** Heimdall capture adapters + consent ledger; HIX (grant surface).
- **Enforcement level:** `future_runtime` (capture-attempt-without-grant must fail in test) + `schema_enforced` (`consent` required on every event).
- **Future test path:** `tests/invariants/test_heimdall_consent.py::test_consent_gated_capture`.

### heim_seam_minimization (HEIM-4)

- **Purpose:** Only minimized, attributed events cross the raw→published seam; `raw_ref` is opaque; no raw payload (audio bytes, full-fidelity signal) in any published event; withheld content is declared, not silently absent.
- **Protected principle:** Charter FIXED #5 (D-PRIVACY).
- **Affected boundaries:** Heimdall publish path; EBF-analog seam.
- **Enforcement level:** `schema_enforced` at enactment (no raw-payload field exists; `withheld[]` required when degradation applied) + `future_runtime` (negative test: raw bytes cannot be smuggled via `content`).
- **Future test path:** `tests/invariants/test_heimdall_seam.py::test_seam_minimization`.

### heim_policy_gated_raw_access (HEIM-5)

- **Purpose:** Raw-layer reads require a CrossScopeFlow grant and emit a receipt; no ungoverned raw read path exists in any surface (API, CLI, worker, agent).
- **Protected principle:** Charter FIXED #5; `cross_scope_only_via_flow` `[conform]`.
- **Affected boundaries:** Heimdall raw store; GOV (grant evaluation, receipts).
- **Enforcement level:** `future_runtime` (v1 interim: allowlist + receipts, honestly weaker — full CrossScopeFlow runtime is itself xfail-skeleton today; the invariant is written against the target and the interim is a declared gap, not a silent one).
- **Future test path:** `tests/invariants/test_heimdall_seam.py::test_policy_gated_raw_access`.

### heim_attribution_honesty (HEIM-6)

- **Purpose:** Confidence is never silently upgraded; unknown/ambiguous actors and entities are represented as `unresolved`/`ambiguous` states with provisional refs — never guessed into a canonical identity; every resolution carries `method` + `calibration`.
- **Protected principle:** Charter seed HEIM-6; doctrine — propose when uncertain.
- **Affected boundaries:** Heimdall attribution/resolution stages; SIP (register); HIX (rendering unresolved as unresolved).
- **Enforcement level:** `schema_enforced` at enactment (three-state resolution shape; no bare-string canonical identity field) + `future_runtime` (upgrade-only-via-correction-event check).
- **Future test path:** `tests/invariants/test_heimdall_attribution.py::test_attribution_honesty`.

### heim_decay_event_triggered (HEIM-7)

- **Purpose:** Relevance decay fires on triggering events, not merely age; the raw layer's bounded hard retention executes regardless and its execution is receipted (deletion is a governed, auditable act).
- **Protected principle:** Charter FIXED #7 (D-RETENTION).
- **Affected boundaries:** Heimdall raw store lifecycle; GOV (deletion receipts).
- **Enforcement level:** `future_runtime` (v1 ships the hard-retention bound as an ops job + receipt; decay model is v2 — declared).
- **Future test path:** `tests/invariants/test_heimdall_retention.py::test_decay_event_triggered`.

### heim_not_authority (HEIM-8)

- **Purpose:** A Heimdall event is candidate evidence; its Mimer projection carries `requires_review: true` / noncanonical standing and cannot become canonical human knowledge without a governed authority transition (token + receipt).
- **Protected principle:** Charter FIXED #3; `authority_transition_required_for_durable_mutation`, `promote_requires_governance` `[conform — extends the existing xfail skeletons to the Heimdall source path]`.
- **Affected boundaries:** Mimer projector; GOV, HKA.
- **Enforcement level:** `schema_enforced` in part (projection stamps noncanonical bundle) + `xfail_runtime_skeleton` (rides the existing promotion-gate skeleton).
- **Future test path:** `tests/invariants/test_heimdall_projection.py::test_event_not_authority`.

### heim_observed_content_is_not_instruction (HEIM-9, new)

- **Purpose:** No agent or runtime executes, mutates, or grants on the basis of observed content in an event without the normal proposal/confirmation path; event content enters agent context only as candidate evidence with bounded `evidence_role`. Blocks prompt-injection-via-reality ("note to self: approve everything").
- **Protected principle:** `execution_cannot_authorize_itself`, `propose_when_uncertain` `[conform — extended to the sensor surface]`; new at this boundary.
- **Affected boundaries:** CAO, GOV, EXE on the Mimer side; Heimdall contract (events carry no imperative channel).
- **Enforcement level:** `future_runtime` (adversarial fixture: an event whose transcript contains instruction-shaped text must produce zero side effects without confirmation).
- **Future test path:** `tests/invariants/test_heimdall_projection.py::test_observed_content_is_not_instruction`.

### heim_bitemporal_honesty (HEIM-10, new)

- **Purpose:** `observed_at` (reality), `captured_at` (ingestion), and envelope `timestamp` (publication) are distinct and never conflated; no event fabricates observation time (`clock_basis` names the trusted clock; inferred time carries a `temporal` confidence axis).
- **Protected principle:** provenance carries justification; new.
- **Affected boundaries:** Heimdall capture adapters + publish path; DRI (timeline projections).
- **Enforcement level:** `schema_enforced` at enactment (all three fields required + `clock_basis` enum) + `future_runtime`.
- **Future test path:** `tests/invariants/test_heimdall_stream.py::test_bitemporal_honesty`.

### heim_attribution_resolves_in_register (HEIM-11, new)

- **Purpose:** Every resolved actor/entity reference in a published event is a register ref (canonical or provisional) that resolves (through merge redirects) in the shared register; no free-text canonical identity exists anywhere in the published contract.
- **Protected principle:** Charter FIXED #6 (D-IDENTITY); single source of identity truth (`retrieval_candidate_identity_single_source` analog).
- **Affected boundaries:** Heimdall resolution stage; SIP (register).
- **Enforcement level:** `schema_enforced` at enactment (resolution shape admits only refs) + `future_runtime` (referential-integrity probe over log × register).
- **Future test path:** `tests/invariants/test_heimdall_attribution.py::test_attribution_resolves_in_register`.

### heim_declared_egress (HEIM-12, new)

- **Purpose:** Every capture adapter and every processing stage declares its egress posture (hosts, auth, what data class leaves); raw-class data (audio, full-fidelity signal) has zero egress unless an explicit owner-enacted grant exists; no silent cloud processing.
- **Protected principle:** privacy seam (D-PRIVACY); mirrors KAP plugin `egress_posture` `[conform — pattern reuse]`.
- **Affected boundaries:** Heimdall adapters/stages; EBF-analog; CES (posture review at adapter addition).
- **Enforcement level:** `static_test` at enactment (posture declaration exists and names no raw egress) + `future_runtime` (network-boundary probe where feasible).
- **Future test path:** `tests/invariants/test_heimdall_seam.py::test_declared_egress`.

### heim_revocation_propagates (HEIM-13, new)

- **Purpose:** A consent revocation event (a) lapses future capture immediately, (b) hard-deletes covered raw within the retention bound with a receipt, and (c) is honored by every projection via suppression — a surface presenting revoked-covered content unsuppressed is a defect.
- **Protected principle:** Charter FIXED #4/#7; `suppression_state` semantics `[conform]`.
- **Affected boundaries:** Heimdall consent ledger + raw store; Mimer projections (DRI/HIX).
- **Enforcement level:** `future_runtime`.
- **Future test path:** `tests/invariants/test_heimdall_consent.py::test_revocation_propagates`.

### heim_replay_is_stage_local (HEIM-14, new)

- **Purpose:** Re-processing raw evidence through improved stages performs zero re-capture and zero source egress; replay output is a revision event with `revision_of` + changed `stage_versions`, never an in-place change and never a duplicate-keyed publication.
- **Protected principle:** KAP replayability principle (Charter FIXED #8) `[conform — generalized]`; KERNEL-02 key discipline.
- **Affected boundaries:** Heimdall pipeline; shared Layer-2 replay primitives (§5.2).
- **Enforcement level:** `future_runtime`.
- **Future test path:** `tests/invariants/test_heimdall_stream.py::test_replay_is_stage_local`.

---

## 9. Owner decisions surfaced

Each per house form: Background / The decision / Options / Recommendation. (a)–(c) were required by the window scope; (d)–(h) were discovered.

### a. Heimdall-vs-KAP backbone (ratify D-BACKBONE)

- **Background:** Owner left the backbone open (D-BACKBONE) with the shared provenance standard fixed. §5 designs the answer.
- **The decision:** Ratify "separate backbones on shared promoted provenance/replay primitives" as the Heimdall–KAP relationship.
- **Options:** (1) One generalized KAP backbone, sensors as plugins — one contract set, but smears the privacy seam and demotes Heimdall to a KAP tenant. (2) Fully separate including provenance vocabulary — autonomy, but violates the fixed shared-provenance guardrail and forks join keys. (3) Separate backbones, shared primitives (`content_identity`, immutable raw, stage-local replay, single-touch source rule, KERNEL-06 stamping), shared ASR stage implementation — recommended.
- **Recommendation:** Option 3. Formal Layer-2 promotion of the primitives is deferred to its own ADR (R-PROMOTE) at the second-consumer moment.

### b. Entity register: build v0 now vs stub for v1

- **Background:** No register exists; D-IDENTITY fixes it as shared substrate; §3 specifies a minimal v0. Publishing events with bare-string mentions creates a correction-wave debt that append-only makes expensive.
- **The decision:** Build register v0 (one table, four operations, provisional entities, human-confirmed merges) before the first published event, or ship v1 with string mentions and retrofit.
- **Options:** (1) Stub — days faster, poisons the stream with unlinkable strings. (2) Full Layer-2 register with governance/federation/UI first — months of substrate before one memo flows. (3) v0-before-first-event — recommended.
- **Recommendation:** Option 3. Register *governance and ownership* remain reserved (R-IDENTITY-OWNER) — v0 assumes operator-owned, single-instance, monorepo-internal, which needs owner confirmation.

### c. On-device vs cloud ASR (the privacy-seam call)

- **Background:** ASR is the first processing stage touching raw audio; where it runs decides whether the most sensitive asset ever leaves owner hardware. Existing embedding posture (Ollama-primary + auto cloud fallback) is precedent for derived text, not for raw audio. R-EXTERNAL applies.
- **The decision:** Whether raw audio may ever be sent to a cloud ASR provider, and if so under what mode.
- **Options:** (1) Local-only, fail loud on failure (memo queues, operator notified) — strongest seam, requires capable local ASR (Whisper on the mini/gaming-PC; realistic). (2) Local-primary + automatic cloud fallback — best availability, but silent raw egress on exactly the days the local stack is broken; violates least-surprise for the seam. (3) Cloud-primary — fastest/best accuracy, seam moved wholesale outside the trust boundary; rejected. 
- **Recommendation:** Option 1 for v1, with cloud ASR contractually representable (HEIM-12 declared-egress + an explicit owner-enacted grant) but OFF. Revisit only on evidence local ASR quality/throughput fails the vertical.

### d. Voice-memo classification (ratify the §5.1 boundary rule)

- **Background:** The concrete boundary case the window had to make concrete. §5.1 recommends Heimdall-capture with the "record of reality vs authored content" discriminator, and routes dictation-shaped memos to candidates via Mimer projection.
- **The decision:** Ratify the discriminator rule as the standing Heimdall/KAP admission test for future inputs.
- **Options:** (1) Ratify as stated. (2) Route voice memos through KAP (simpler now, loses event semantics, entrenches KAP as the everything-pipeline). (3) Case-by-case without a rule (guarantees future relitigating).
- **Recommendation:** Option 1.

### e. Revocation semantics for already-published events

- **Background:** Append-only truth vs erasure (§6.4): raw hard-deletes; published events can only be suppressed, not unpublished. Touches R-RETENTION/R-PRIVACY, and any legal-erasure obligation is R-EXTERNAL.
- **The decision:** Accept suppress-don't-rewrite as the published-layer revocation semantic (with minimization bounding what was ever published).
- **Options:** (1) Suppress + tombstone event, log immutable — recommended; honest, auditable. (2) Cryptographic erasure of published event content (per-event keys, shred on revoke) — genuinely stronger erasure at real complexity cost; a v2 hardening candidate if third-party capture makes erasure obligations real. (3) Physical rewrite of the log — rejects HEIM-1; not offered.
- **Recommendation:** Option 1 for v1; explicitly re-open (2) before any v2 third-party/ambient capture ships. **Red-team update (F3):** the pass found suppress-only insufficient — plaintext, replayable content sits in the log forever and suppression is per-consumer etiquette while new consumers rebuild from event zero (§4). Upgraded recommendation: adopt per-episode content keys in v1 (trivial at v1 volume) so revocation becomes key shred, not just suppression, and move suppression into the log-read contract rather than consumer etiquette.

### f. Third-party degradation depth (v1 posture)

- **Background:** Even v1 self-recorded memos can accidentally contain another voice. §6.3 defaults to publish-own-speech-only + withheld markers, raw retained behind the seam.
- **The decision:** Confirm the v1 default when a third-party voice is detected: degrade-and-publish vs withhold-entire-memo vs mark-only.
- **Options:** (1) Degrade (own speech published, third-party speech withheld + presence marked) — recommended; preserves the operator's own record. (2) Withhold the entire memo pending operator review — most conservative, adds a review queue to v1. (3) Mark-only (publish everything, flag it) — weakest; inconsistent with "marked/**degraded**" in D-CONSENT.
- **Recommendation:** Option 1.

### g. Register merge authority

- **Background:** Merges rewrite identity ecosystem-wide via redirects; wrong merges are corrosive (R-IDENTITY-OWNER's stated reason).
- **The decision:** Who may merge register entities in v1.
- **Options:** (1) Human-confirmed only (agent proposes, owner clicks) — recommended for v1; matches propose-when-uncertain and current governance tiers. (2) Agent-auto above a confidence threshold with receipts — faster convergence, first identity error is silent; defer until calibration data exists. (3) Human-only including proposal — wastes the LLM's genuine strength at candidate generation.
- **Recommendation:** Option 1, revisit (2) with evidence after v1.

### h. iCloud in the v1 capture chain (acknowledge)

- **Background:** §7.1: v1 raw audio transits Apple's cloud before the seam begins — a deliberate consequence of "no custom app in v1". Consistent with the vault-on-iCloud posture but higher sensitivity. R-EXTERNAL.
- **The decision:** Acknowledge Apple/iCloud inside the v1 pre-seam trust boundary, with delete-after-ingest bounding residence time.
- **Options:** (1) Acknowledge + delete-after-confirmed-ingest + name direct-transfer as v2 hardening — recommended; keeps "no custom app" true. (2) Require direct device→host transfer in v1 (Tailscale/local upload Shortcut) — tighter, adds v1 friction and failure modes. (3) Silence — not offered; the chain is stamped on every event either way.
- **Recommendation:** Option 1. **Red-team update (F4):** acknowledgment must extend past the pre-seam hop — the Mimer projection lands candidates in the vault, which itself syncs via iCloud, so Heimdall-derived transcript transits Apple's cloud a second time, post-seam; delete-after-ingest also does not purge Voice Memos' own copy, Recently Deleted (30-day retention), or iCloud backups. HEIM-12 declared-egress must count vault-sync of Heimdall-derived content as declared egress, and this acknowledgment covers backup/residue, not just the capture-time transit.

### i. Published-content sensitivity / aggregate exposure (F1)

- **Background:** Red-team finding F1 (§10): v1 `content` is the full inline transcript, so life-content, the entity graph, and timing all cross the raw→published seam together — HEIM-4 guards the audio codec, not the secret. CrossScopeFlow (§7.2 T2) has no volume/aggregate dimension, so one grant is a firehose over an unbounded window, and revision events can leak previously withheld spans via diffing against the prior revision.
- **The decision:** Whether to treat published `content` itself as Heimdall-grade and add aggregate/expiry budgets to capture-scope flows, or accept the inline-transcript exposure as a stated v1 residual.
- **Options:** (1) Harden now — declare published content Heimdall-grade, add aggregate/expiry budgets to capture-scope CrossScopeFlow grants, require revisions to re-apply the strictest current degradation (never regress protection on re-publish). (2) Accept as written — ship v1 with the residual stated, revisit under evidence. (3) Move to by-reference content in v1 (no inline transcript ever crosses the seam) — closes the exposure at the root but is materially more build than the v1 scope committed to.
- **Recommendation:** Option 1 for the flow budgets and revision re-degradation (cheap, closes the diffing leak); accept inline transcript content for v1 with the budget as the mitigation rather than deferring to Option 3.

### j. ASR engine ownership — Heimdall-owned vs shared substrate (owner-directed 2026-07-05)

> **Superseded by §9-k (owner-confirmed 2026-07-05):** with Heimdall owning *all* ingestion and transcription, there is no competing Mimer transcription, so the "two instances" problem dissolves and ASR is simply **Heimdall-owned**. §9-j is retained for the reasoning; §9-k is the standing decision.

- **Background:** The system already has ASR (`app/media/transcribe.py`, faster-whisper; `run_asr()` engine + KAP outbox wrapper). The owner's constraint: **no two whisper instances.** Refines §5.2.
- **The decision:** Where the ASR engine lives — Heimdall-owned, or shared Layer-2 substrate.
- **Options:** (1) **Heimdall owns whisper**, Mimer takes over after transcription — clean for the seam, but forces KAP (which transcribes *public* content) to either duplicate the engine or depend on Heimdall (a public pipeline coupling to the most-private constituent). (2) **whisper = shared substrate.** Sub-variants matter: (2a) shared **library + model cache**, invoked in-process inside each constituent's boundary; (2b) shared **service** audio is sent to — **rejected**: shipping Heimdall raw audio to a shared service punctures the privacy seam (FIXED #5).
- **Recommendation:** **Option 2a.** It kills duplication *and* satisfies Option 1's intent: the engine is shared, but Heimdall still owns the *invocation on raw audio* inside its seam (raw never leaves), and Mimer takes over at the published event. Refactor: extract `run_asr` + model cache → `app/media/asr_engine.py`; KAP keeps its wrapper; Heimdall adds an in-seam, event-emitting wrapper; expose per-segment confidence additively. Validated: the v1 prototype was re-pointed at the real faster-whisper engine (one instance), whisper.cpp demoted to fallback.

### k. Heimdall as the ecosystem ingestion organ (owner-CONFIRMED 2026-07-05) `[reshape → CES/ADR]`

This is a confirmed owner decision (not merely surfaced), and it **reshapes the §5 boundary** — so it routes through CES/ADR at enactment.

- **Background:** The §5.1 discriminator drew the Heimdall/KAP line at *records-of-reality vs authored-content*, leaving KAP (in Mimer) owning YouTube/web watch → download → transcribe. The owner's reframe: *monitoring, downloading, and transcribing are sensing/capture activities — they belong to Heimdall, not Mimer,* for **all** external sources, not just voice.
- **The decision (confirmed):** **Heimdall is the ecosystem's ingestion/sensing organ.** It owns the front of the chain for every external source — **watch → fetch → transcribe → attribute → published event/candidate**. **Mimer** owns cognition from the handoff: **extract meaning → integrate → promote to knowledge**. Mimer never watches, fetches, or transcribes.
- **Handoff point:** Heimdall resolves *who/what was observed* (attribution, register refs, provenance, confidence); Mimer decides *what it means* (claims, summaries, promotion). Consistent with the interpretation boundary already fixed in §2.1 (interpretation is downstream).
- **What this supersedes / revises:**
  - **§9-j → moot:** ASR is **Heimdall-owned** (Heimdall owns all transcription; no competing Mimer instance). The `run_asr`/model-cache reuse is now an internal Heimdall implementation detail, not a cross-constituent shared substrate.
  - **§5.1 discriminator → demoted:** records-of-reality vs authored-content is no longer an *ownership* boundary; it becomes an event **typing** (a voice memo and a YouTube transcript both flow through Heimdall, carrying different `modality`/`sensitivity`/scope). §5.2's "separate backbones" collapses toward *one Heimdall acquisition backbone*, with Mimer downstream.
  - **KAP (spec #2786):** its acquisition front-end (source plugins, download, ASR) moves from Mimer to Heimdall; KAP's residual cognition/candidate-refinement stays in Mimer. Touches RESEARCH-08 and the constituent definitions in ADR-0043/0044 — a genuine `reshape`, to be enacted via an ADR.
- **OPEN sub-question (b) — watch-as-selection (owner UX inputs captured 2026-07-05; principle now resolved, ownership + detailed UX in a follow-on thread):** does Heimdall own *watch-as-selection* (what is worth monitoring / pulling in), or only fetch+transcribe once something is designated? **Principle resolved (2026-07-05, see input 3): "Markdown holds the record, the UI is the lens"** — the control surface is a markdown settings note in the vault; UI is a lens. The remaining ownership question + the full UI/UX are moving to a fresh Claude Design brief on Heimdall's UI/UX dimension. Captured owner UX inputs:
  1. **How a source is onboarded:** **inference from the principal's behaviour, with agent autonomy under hard quality gates + post-hoc steering.** The agent watches the principal's interests; the principal (principal–agent model) conveys **both explicit and implicit intent** to the agent.
  2. **How much to pull from a source:** **differs per source** — build for **filters that can be switched off in specific contexts.**
  3. **Control surface:** ✅ **RESOLVED (2026-07-05) — "Markdown holds the record. The UI is the lens."** Two independent explorations converged on the same verdict: the owner's Claude Design pass *and* this session's J3/J6 exploration both found the markdown-first principle **holds** for the watch/selection control surface — the `.md` settings/notes in the vault are the canonical source of record; any UI is a complementary lens (better ergonomics), never the sole home of a capability. No journey required a UI-only capability. The governing principle is settled; the detailed UI/UX design continues as a **separate thread** (a fresh Claude Design brief on Heimdall's UI/UX dimension). Design briefs/mockups stay outside the repo per convention.
  4. **Where it lives:** likely a **human-manageable `.md` settings surface in the vault** (writable settings, per the persistence-is-not-read-only rule).
  5. **Attention calibration** (intake volume vs noise vs misses): flagged as **one of the most important questions**, to be **approached in stages**, not settled in one shot.
  - **Emerging boundary read (advisory, not final):** because selection here is genuinely *cognitive* (inferring interests, relevance-filtering under quality gates), it leans **Mimer / the agent layer**, with Heimdall doing fetch+transcribe on designated targets. A clean loop falls out: **Heimdall senses behaviour → Mimer infers interests → designates sources/items → Heimdall fetches+transcribes → Mimer makes meaning.** To be confirmed after the Claude Design pass (input 3) and the staged attention-calibration work (input 5).

### Decision run — owner rulings (2026-07-05)

Batched build-gating rulings. Three confirmations + one reshape.

1. **Entity/identity register → Mimer-owned, markdown-built `[reshape → CES/ADR]`.** *Reverses D-IDENTITY / charter FIXED #6* (which fixed the register as a shared Layer-2 substrate owned by no constituent). Owner ruling: **the register belongs to Mimer (the system-of-record); Heimdall integrates with it, not owns it.** Source of record is **`.md` files in the vault** (markdown-first, companion-note style); a **graph database is a derived index** built *from* those notes to improve relationship functionality — never the canonical store. This is a genuine reshape of a FIXED constraint, so it routes through CES/ADR at enactment (same ADR as §9-k).
   - **v1 mechanic (interpretation — owner to confirm):** with the register on Mimer's side, **Heimdall emits entity _mentions_** (surface forms + provisional local refs) in its events; **canonical _resolution_ (which Anna, which Northvolt) is Mimer's** — identity is knowledge, and knowledge is Mimer. This refines the §9-k handoff (resolution moves from Heimdall to Mimer's side of the seam) and **de-risks v1**: Heimdall neither builds nor blocks on a register. Supersedes the companion's earlier "Entity Register v0 before the first event" as Heimdall's biggest trade-off — that trade-off now belongs to Mimer, on its own schedule.
2. **ASR location → local, fail-loud.** Confirms §7 rec: raw audio never leaves the machine; no silent cloud fallback. (Public YouTube audio may be allowed a cloud path later — separate, lower-sensitivity decision.)
3. **YouTube seam → Heimdall owns download + transcribe + attribute(mentions); Mimer owns extract-meaning → candidate.** Confirms §9-k for the concrete YouTube pipeline. **Watch-as-selection stays deferred** (UX-gated, §9-k(b) + input 3 above) — the *fetch+transcribe* front moves to Heimdall now; *what is worth watching* waits for the Claude Design pass.
4. **Voice-memo capture → iOS Shortcut → watched iCloud folder.** Zero manual per-memo work: a dedicated "Record Audio → Save File (iCloud)" Shortcut (no scraping of Voice Memos' TCC-protected store). One-time setup on the phone/Watch.

---

## 10. Red-team pass (adversarial review)

An independent Fable adversarial pass reviewed §3/§6/§7/§8; findings below are folded into the critical path and owner decisions.

| ID | Severity | Finding | Disposition |
| --- | --- | --- | --- |
| F2 | CRITICAL | Injection-via-reality has no neutralization point, only a label: transcript text flows into candidate artifacts / triage / prompt context while every cited guard (HEIM-8/HEIM-9, promotion gate) is future_runtime or rides the GOV xfail skeleton; the watched iCloud folder is unauthenticated so anyone who can write it injects agent context with operator provenance. | Hardening promoted to build-now: (a) projector-side content quarantine — observed content is framed as untrusted, fence-neutralized, and never placed in any auto-executing prompt path; (b) signed capture manifest from the Shortcut pulled from v2 into v1. Blocks the vertical until closed. |
| F5 | HIGH | Register merge is irreversible (no split/unmerge in the v0 API); one wrong human-confirmed merge conflates two identities across all history; correction events only fix per-event links. | Add `split(entity_id, partition_criteria)` to the Entity Register v0 contract (§3.2) as build-now, before the first merge ships. |
| F1 | HIGH | The seam minimizes the wrong asset: v1 `content` is the full inline transcript, so the life-content/entity-graph/timing all cross the seam; HEIM-4 guards the audio codec, not the secret; CrossScopeFlow has no volume/aggregate dimension (one grant is a firehose); revision events can leak previously withheld spans via diffing. | Owner-accepted residual OR hardening: declare published `content` itself Heimdall-grade; add aggregate/expiry budgets to capture-scope flows; revisions must re-apply the strictest current degradation. Surfaced as owner decision §9-i. |
| F3 | HIGH | Consent revocation is relabeled, not resolved: raw hard-deletes but the published transcript sits plaintext + replayable in the log forever; suppression is per-consumer etiquette, yet §4 says new consumers rebuild from event zero; third-party raw voice is retained with no revocation actor. | Recommend per-episode content keys now (trivial at ~5 events/day) so revocation = key shred; move suppression into the log-read contract, not consumer etiquette. Folded into owner decision §9-e as the recommended v1 choice (upgrade from suppress-only). |
| F4 | MEDIUM | 'Local-only ASR' is true about the wrong hop: the Mimer projection lands candidates in the vault, which syncs via iCloud, so derived transcript transits Apple's cloud post-seam; delete-after-ingest does not purge Voice Memos' own copy, Recently Deleted (30d), or iCloud backups. | HEIM-12 (declared egress) must count vault-sync of Heimdall-derived content as declared egress; extend §9-h acknowledgment to backup/residue. |
| F6 | MEDIUM | Confidence laundering: the projection MAY fill the legacy scalar `confidence` with no calibration marker, and a skim-confirming human mints by_construction 1.0 over a whole event; per-axis rules are all future_runtime. | The calibration marker must survive into the Mimer bundle; human confirmation is per-fragment not per-event. Folded into §2.2 rules as normative. |

**Verdict:** the threat model is unusually honest but not sufficient to build v1 on as written — F2 and F5 must be closed before the vertical; F1, F3, F4, F6 must be owner-accepted in writing if any hardening is deferred.

---

## 11. v1 voice-memo critical path

Minimal ordered build list to ship the vertical: capture → raw → ASR → attribution/entities → confidence+provenance → published event → Mimer projection → governed gate. Each item marked **build-now** or **contract-stub** (contract written + schema-representable, no runtime). Ordering is dependency-true; items 1–2 are the only genuinely blocking substrates.

| # | Item | Mode | Notes |
| --- | --- | --- | --- |
| 1 | **Entity register v0** — table, `resolve` / `mint_provisional` / `merge` (human-confirmed) / `resolve_redirects`, mutation events; includes reversible `split()` (red-team F5) | build-now | Before the first published event (§9-b). |
| 2 | **Observation log + publish path** — append-only table, envelope reuse, `derive_idempotency_key` discipline, per-consumer cursor read | build-now | The constituent seam. |
| 2a | **Content quarantine (projector)** — observed content framed untrusted, fence-neutralized, excluded from any auto-executing prompt path (red-team F2) | build-now | Blocks the vertical until closed (§10). |
| 3 | **Event contract schemas** — `heimdall.observation.published.v1` (+ consent-granted/revoked, corrected topics) | build-now (published topic) / contract-stub (corrected, revoked runtime) | This doc is the prose mirror; schemas become canonical at enactment. |
| 4 | **Consent ledger v0** — grants table + the standing `self_record` grant + capture-time check | build-now (mechanism is small; HEIM-3 must be real from day one) | Place/session grants: contract-stub. |
| 5 | **Voice-memo capture adapter** — watch the iCloud Shortcut folder, admit under grant, write raw record (encrypted at rest, `content_identity`, `capture_chain`, KERNEL-06 stamping), delete-after-confirmed-ingest | build-now | The only component touching the source. |
| 6 | **Raw store + gated read path** — encrypted blob store, opaque `raw_ref`, read via allowlist + receipt (interim for CrossScopeFlow) | build-now (store, receipts) / contract-stub (full CrossScopeFlow grant evaluation — declared gap per HEIM-5) | |
| 7 | **ASR stage** — local Whisper-class, segment output + confidences, `stage_versions`, multi-speaker guard, replayable | build-now | Shared stage implementation with KAP KA-02 (§5.2). |
| 8 | **Attribution + entity-mention stage** — self-attribution via capture context; LLM mention extraction → register resolve; three-state resolution | build-now | Diarization-based third-party degradation: minimal guard build-now, richer detection v2. |
| 9 | **Publish** — assemble payload (§1.3), validate, insert with revision-aware idempotency key | build-now | |
| 10 | **Mimer projector** — cursor consumer; projects events into bundle-carrying candidate artifacts (`requires_review: true`, noncanonical, capture scope, provenance chain) entering existing triage | build-now | The read-model that proves the seam. |
| 11 | **Governed promotion gate** — events → canonical knowledge only via authority transition | contract-stub (conform to the existing xfail skeleton; HEIM-8 rides it) | No new gate built; the existing GOV path is the gate. |
| 12 | **Correction events runtime** (fold logic in projector, correction UI action) | contract-stub | Schema in #3; runtime lands with the first real disambiguation need. |
| 13 | **Retention** — bounded hard-retention ops job + deletion receipts | build-now (the bound) / contract-stub (event-triggered decay model) | D-RETENTION's hard bound is a privacy control, not a nicety. |
| 14 | **Revocation + suppression propagation** | contract-stub | Trivial in v1 (self-consent); must exist on paper before v2 ambient. |
| 15 | **Invariant test skeletons** — HEIM-1..14 as xfail/static per §8 | build-now (skeletons) | Verify-the-verifier: the invariants land with the runtime, not after it. |

Note: F1/F3/F4/F6 dispositions are owner decisions §9-e/§9-h/§9-i; F2 quarantine and F5 split are build-now above.

Explicitly deferred to v2 (not precluded, contracts already hold them): always-on/ambient adapters, place/session grants runtime, diarization+voiceprint attribution, segment-granular episode events, by-reference content, stream-broker transport swap, cryptographic erasure, direct device→host capture transfer, second modality.

---

## 12. v1 prototype validation

`[extend]`

A throwaway on-device spike exercised the full v1 vertical (folder-watch capture under a self_record grant → openssl-encrypted raw + content_identity → on-device whisper.cpp Swedish ASR with per-token-probability transcription confidence → three-state register resolution with provisional-id minting → orthogonal-axis event payload → append-only publish → noncanonical candidate projection). It confirmed as buildable: append-only enforcement (HEIM-1), gated raw reads with receipts (HEIM-5), the F2 content-quarantine frame, and the noncanonical-candidate projection (HEIM-8). It also confirmed the honest limits: base/small local ASR on short Swedish audio degrades entity surface forms (e.g. proper nouns mis-transcribed), which is exactly why the LLM resolver (§3.2) and confidence calibration (§2) are load-bearing, not optional. The spike is not committed; productionization is Issue-first per repo governance.

---

## SBS reconciliation summary

| Claim / section | Reconciliation | Routing |
| --- | --- | --- |
| Outer envelope reuse, idempotency-key discipline, schema-registry pattern, no-vectors rule (§1, §4) | `conform` | none |
| Observation payload contract, episode model, two event classes (§1) | `extend` | schema minted at enactment |
| Bitemporal time model; scope-stamped, private-by-default capture scope (§1) | `extend` / `conform` (capture_stamps_scope, private-by-default) | none |
| Orthogonal confidence axes; interpretation excluded from sensor (§2) | `extend` / `conform` (boundary honesty) | none |
| Immutable mentions + evolving register; three-state resolution; correction-as-new-event (§3) | `extend` | none |
| Entity register v0 as operationalized `Concept` (§3.2) | `extend` — of the ontology stub, not a fork | register ownership/governance → owner (R-IDENTITY-OWNER) |
| Heimdall-owned log + cursors; outbox pattern generalized, outbox table untouched (§4) | `extend` — no outbox ownership change | transport swap, if ever → ADR |
| Voice memo = Heimdall capture; record-of-reality vs authored-content discriminator (§5.1) | `extend` — proposed boundary rule | owner ratification (§9-d) |
| Separate backbones on shared promoted provenance/replay primitives (§5.2) | `extend` | primitive promotion → ADR/CES (R-PROMOTE, §9-a) |
| Consent ledger, capture-time enforcement, degradation, revocation semantics (§6) | `extend` — mechanism within fixed D-CONSENT posture | revocation-vs-append-only semantics → owner (§9-e); degradation depth → owner (§9-f) |
| Local-ASR-only v1, declared egress (§7) | `extend` | cloud-ASR enablement → owner (§9-c, R-EXTERNAL) |
| iCloud inside the v1 pre-seam trust boundary (§7.1) | `extend` — stated residual | owner acknowledgment (§9-h, R-EXTERNAL) |
| HEIM-1..8 refined + HEIM-9..14 new invariants (§8) | `extend` | registry entry registration at enactment |
| Events-not-instruction, promotion-gate, suppression semantics riding existing contracts (§8) | `conform` — extends existing invariants/skeletons to the sensor path | none |
| Mimer naming used against stale charter/SoS-model "Munin/Hugin" text | `conform` — to ratified naming | text cleanup via #2890 (not edited here) |
| Red-team adversarial pass; F1/F3/F4/F6 dispositions routed to owner, F2/F5 promoted to build-now (§10) | `extend` | F1 → owner (§9-i); F3 → owner (§9-e); F4 → owner (§9-h); F6 → §2.2 norm; F2/F5 → critical path (§11) |
| v1 prototype validation spike, not committed (§12) | `extend` — advisory evidence only | none; productionization is Issue-first |
| Anything touching a FIXED constraint | none proposed | — (no reshape of FIXED discovered; all tensions surfaced as owner decisions) |

## References

- `docs/HEIMDALL/CAPABILITY_CHARTER.md` (A3), `OWNER_DECISIONS.md` (A4), `ECOSYSTEM_SOS_MODEL.md` (A1), `FABLE_WINDOW.md` (A5)
- `docs/EVENTS.md`, `app/services/outbox.py`, `docs/RUNTIME_CORRECTNESS_KERNEL/MANDATORY_OUTBOX_IDEMPOTENCY.md`
- `docs/KNOWLEDGE_ACQUISITION/README.md`, `SOURCE_PLUGIN_CONTRACT.md`, `REFINEMENT_PIPELINE_CONTRACT.md`
- `docs/architecture/metadata-bundle.md`, `functional-ontology.md`, `semantic-dimensions.md`, `cross-scope-flow.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`, `docs/testing/invariant-tests.md`
- ADR-0043/0044 (naming), ADR-0020 (ReplicationEnvelope V1 posture)
