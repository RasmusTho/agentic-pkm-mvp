State: Specification directory — FILED (parent #3340; children #3341–#3346 filed 2026-07-07, all agent:blocked at filing per the uniform closed-loops filing policy). System-level source of truth for building the Heimdal Screen Stream: an always-on-while-at-computer desktop observer that extends Heimdal with a `screen` capture modality. Subordinate to the Heimdal charter (`docs/HEIMDAL/CAPABILITY_CHARTER.md`), the owner decisions register (`docs/HEIMDAL/OWNER_DECISIONS.md`), the Heimdal design companion (`docs/HEIMDAL/FABLE_COMPANION.md`), ADR-0049 (Heimdal ingestion organ + v1 enactment), ADR-0050 (Bifrost governed native-client repo), ADR-0054 (ERE is a Mimer organ), and the runtime model posture (`docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md`). Grounded in the owner ruling recorded in `docs/research/yggdrasil-closed-loops-ideation.md` (loop 6).
Doc role: Capability specification (feature-breakdown lane)
Temporal class: strategic
Review cadence: event-driven (task merges, parent-issue lifecycle)
Source of truth: this directory + the governing ADRs/charter; GitHub issues (#3340–#3346) are execution artifacts, this spec is the contract
Last reviewed: 2026-07-07

# Heimdal Screen Stream — Specification

A new Heimdal capture **modality** (`modality: screen`) and the reference desktop observer that
produces it. The observer keeps track of what the owner is doing whenever they are at a work
machine — periodic screenshots + frontmost app/window metadata + extensible local context
providers — and the host derives a privacy-conscious **textual activity observation** (markdown-first,
vision/LLM derivation) that ships through the **governed Heimdal capture path** already built for the
voice-memo vertical. One capture stream feeds three downstream tracks:

1. **The event motor** — `screen` becomes a registered ERE stream (the richest episode-segmentation
   signal), flipping it from `future` to live in the stream registry.
2. **Auto-journal raw material** — the observation stream is the automatic "what happened" skeleton
   consumed by the sibling **Conversational Journaling** capability (`docs/CONVERSATIONAL_JOURNALING/`).
   That capability owns the reflection layer; this spec only **names the seam** and does not design it.
3. **Time-spend analysis** — a rebuildable projection over the observations (by app / project / scope
   / day / week).

Owner framing (2026-07-07): *"keep track of what I'm doing all the time I'm on my computer …
turn this into many valuable tracks."*

Classification: **Product/Runtime System work**, extending the **Heimdal** sensor constituent
(a sibling constituent, not a Mimer subsystem — Heimdal charter FIXED #1). Primary SBS control
boundary: **EBF** (external boundary fabric — the observer is the ingress boundary and the capture
endpoint is the seam); secondary: **SIP** (observation schema, provenance, confidence, and the
`screen` stream identity), **HKA** (observation-candidate notes + the markdown time-spend
projection), **DRI** (the rebuildable time-spend projection), **GOV** (raw-frame read gating +
control-change receipts + consent). The reference client (SCREEN-03) is **external-boundary/client
work** whose default home is the **Bifrost** repo (see Topology below).

## Owner ruling (grounding)

The capture-posture fork (discrete vs always-on) is **decided for the desktop screen modality** and
recorded in `docs/research/yggdrasil-closed-loops-ideation.md` (loop 6, owner session 2026-07-07):

> always-on-while-at-computer is **approved** on the owner's single-operator machines, with **pause**
> and **app/scope exclusion controls** and a **derive-and-discard raw posture** as spec defaults. The
> **wearable/audio side of the fork remains an open owner decision.**

This is a genuine extension of the Heimdal consent posture (`OWNER_DECISIONS.md` D-CONSENT fixed
always-on capture OFF-by-default and opt-in per place/session). The owner has now opted in, once and
standing, for **the desktop screen modality on their own machines** — realized as a standing
`screen_always_on` consent grant that pause/disable revokes. It does not touch the always-off default
for any other modality, and the wearable/ambient-audio fork (`OWNER_DECISIONS.md` R-CONSENT) stays
reserved and out of scope here.

## Topology — client / host split and the Bifrost default

The runtime host is the **Mac mini** (the always-on channel with Postgres, Docker, the raw store, the
observation log, local model access). The owner works on **other machines (a laptop) that deliberately
carry no runtime dependencies** (no pg, no Docker, no ML deps — `reference_laptop_not_runtime`). The
observer is therefore a **native/local client** that posts to the governed capture endpoint on the
host; it is not part of the host runtime.

**Derivation runs host-side (spec default).** The client is thin: it captures frames + frontmost-app
metadata, applies exclusions **at capture time**, buffers offline, and ships **raw capture bundles**
to the host capture endpoint. The host lands them in the encrypted Heimdal raw store, **derives the
textual observation in-seam using a local vision model**, derive-and-discards the frames, and
publishes the minimized observation to the observation log — the exact shape the voice-memo vertical
uses (raw lands encrypted on the host; ASR runs in-seam; only the minimized observation crosses the
seam).

Why host-side is the default — three converging reasons:

1. **The always-on-local floor is binding.** Screen observation is an always-on loop. Per
   `RUNTIME_MODEL_POSTURE.md` §1/§4.2, always-on task kinds are `paid_eligible: false` **structurally**
   and the routing compiler **rejects** a paid model on them at every posture stage. So the derivation
   model must be **local**. The laptop has no local models by design, and duplicating a vision model
   onto every client contradicts the "no two engines" substrate rule (`FABLE_COMPANION.md` §9-j).
   Local derivation can therefore only happen on the Mac mini host.
2. **Heimdal v1 is host-side in-seam derivation.** Raw pixels are the screen analog of raw audio; the
   local ASR-in-seam posture (`FABLE_COMPANION.md` §7.3, T3) maps directly to local-vision-in-seam. A
   new modality **extends** Heimdal (reusing the raw store, gated read, retention, publish, projector),
   it does not fork it.
3. **The retention gate already exists on the host.** Host-side derivation's cost — "raw frames need a
   retention gate" — is already paid: the encrypted `heimdal_raw_record` store + `enforce_hard_retention_bound`
   + deletion receipts are live (#3025/#3032). The frame buffer is a *tightening* of that mechanism,
   not new machinery.

**The tradeoff, stated honestly.** Host-side means raw pixels — the most sensitive screen asset —
leave the client and transit the trusted LAN to the host. Mitigations: exclusions are honored at
**capture** time so excluded pixels never leave the client at all (INV-SCREEN-D); the transport is
loopback (when the client is co-located on the Mac mini) or Tailscale-local within the single-operator
trusted LAN (`SECURITY_TRUST_BOUNDARIES.md` environment boundary — LAN/Tailscale explicit and
proportionate); and on the host the frames land encrypted-at-rest, derive-and-discard, bounded
retention. **On-device derivation is the declared future/v2 posture:** when a capable local vision
model can run on the capture machine, derivation moves on-device under the **same** contract — the
endpoint already accepts pre-derived observations (mirroring the voice-memo "adapter emits observation"
seam and the `FABLE_COMPANION.md` §4.2 contract-first/module-lazy discipline). The contract accepts
**both** shapes; the default is host-derives.

**Client home = Bifrost (ADR-0050).** A native macOS client is a constituent-surface client; per
ADR-0050 its home is the governed **Bifrost** repo (topology C). SCREEN-03 (the reference client) may
**transfer** to `bifrost`; this repo keeps the **host-side contract** (SCREEN-01) fully specified so
the Bifrost client consumes it, mirroring how `docs/contracts/MIMER_CLIENT_CONTRACT.md` specifies the
host side for the Bifrost knowledge/capture clients. The host contract is the durable, in-repo
authority; the client is a consumer of it.

## Input-source / modality relationship to Heimdal and ERE

| Surface | Before this capability | After |
| --- | --- | --- |
| Heimdal `modality` vocabulary | `speech` (v1 live); `screen` declared for v2 (`FABLE_COMPANION.md` §1.3) | `screen` is a live capture modality with a reference client |
| ERE stream registry | `screen` is `status: future` with nothing behind it (`STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md`; README inventory) | `screen` flips to `live`, consumed via the registry (SCREEN-04) |
| Time-spend analysis | none anywhere | rebuildable markdown projection (SCREEN-05) |
| Auto-journal skeleton | none | the observation stream is the seam Conversational Journaling consumes |

## Implementation tasks (execution order)

| # | Task | id | Prereqs | Home |
| --- | --- | --- | --- | --- |
| 1 | [DEFINE_SCREEN_OBSERVATION_CONTRACT](DEFINE_SCREEN_OBSERVATION_CONTRACT.md) | SCREEN-01 | — | this repo |
| 2 | [DERIVE_ACTIVITY_OBSERVATIONS](DERIVE_ACTIVITY_OBSERVATIONS.md) | SCREEN-02 | SCREEN-01 | this repo |
| 3 | [BUILD_MACOS_OBSERVER_CLIENT](BUILD_MACOS_OBSERVER_CLIENT.md) | SCREEN-03 | SCREEN-01 (∥ SCREEN-02) | **Bifrost** (may transfer) |
| 4 | [REGISTER_SCREEN_STREAM_WITH_ERE](REGISTER_SCREEN_STREAM_WITH_ERE.md) | SCREEN-04 | SCREEN-02; **BLOCKED on ERE stream registry #3176** | this repo |
| 5 | [PROJECT_TIME_SPEND_ANALYSIS](PROJECT_TIME_SPEND_ANALYSIS.md) | SCREEN-05 | SCREEN-02 (∥ SCREEN-03, SCREEN-06) | this repo |
| 6 | [CONTROL_SURFACE_AND_EXCLUSIONS](CONTROL_SURFACE_AND_EXCLUSIONS.md) | SCREEN-06 | SCREEN-01, SCREEN-03 (∥ SCREEN-05) | this repo (client half in Bifrost) |

Flat order: **01 → 02‖03 → 05‖06 → 04**. SCREEN-04 is externally blocked on the ERE stream registry
(#3176) regardless of internal readiness; it is the parent-closure child once #3176 lands.

## Cross-Task Invariants / Interaction Safety

Multiple tasks read/write the frame buffer, the observation stream, the pause state, and the exclusion
list. These invariants hold *across* tasks; each names its partial-failure walk.

- **INV-SCREEN-A — raw frames never persist beyond the named retention buffer.** Derive-and-discard is
  the default: a frame is discarded as soon as its observation is derived (or coalesced into a span).
  A bounded reprocessing buffer holds frames only for a **named constant** window
  (`screen_frame_retention_minutes`, tight — minutes/low hours, distinct from and far shorter than the
  day-scoped `retention_window_days`, because frame volume dwarfs voice-memo volume). Frames past it are
  hard-deleted through the one governed append-only exception, each paired with a deletion receipt.
  **Partial failure — derivation down:** frames **age out of the buffer** (bounded, hard-capped) rather
  than accumulating unboundedly. Data loss here is **acceptable and must be legible** — the aged-out
  count is receipted/countered, never a silent drop and never unbounded growth. (Mirrors HEIM-7 hard
  retention; the trigger here is buffer-age/-cap, and loss-over-accumulation is the accepted trade.)
- **INV-SCREEN-B — observations are derived-class and provenance-stamped.** Every published screen
  observation carries provenance: **machine identity + observed-at window + derivation model_ref /
  stage_versions**, stamped in the same durable write as the observation (KERNEL-06; mirrors HEIM-2).
  It is `requires_review` / noncanonical evidence-candidate class, never canonical knowledge (HEIM-8).
  **Partial failure — derivation yields text but the provenance stamp is incomplete:** publish
  **refuses loudly**; an unprovenanced observation is never published.
- **INV-SCREEN-C — pause means PAUSED (no capture, no buffering, no shipping).** When paused, the
  client does **not sample** the screen (not "sample then drop"), the offline buffer does **not grow**,
  and **nothing ships**. Pause state is **durable**: a client that crashes or restarts while paused
  comes back **paused** — it never silently resumes capture. **Trust consequence:** if pause reset to
  "on" at restart, the owner would be observed without knowing; visible pause state (SCREEN-06) is the
  guarantee the owner can always see at a glance whether observation is on.
- **INV-SCREEN-D — exclusion is honored at CAPTURE time, not derivation time.** An excluded app's (or
  excluded scope's) pixels **never leave the client** — the frontmost app / active scope is checked
  **before** a frame is sampled; an excluded target is never captured, never buffered, never shipped.
  Exclusion is not a host-side redaction of already-transmitted pixels; the pixels do not exist off the
  client. **Partial failure — the frontmost app changes to an excluded app mid-cadence:** the next
  sample tick sees the exclusion and does not capture; any in-flight frame whose frontmost app is
  excluded is dropped before it touches the buffer.
- **INV-SCREEN-E — coalescing must not lose span boundaries the event motor needs.** Dedup/coalescing
  collapses unchanged activity into **spans**, but a span boundary is created on **any** dimension shift
  (frontmost app, window/document, scope, or derived-goal change) — because those boundaries are exactly
  the five-dimension shifts the ERE segmenter consumes (SCREEN-04). **Over-segmentation is preferred**
  (merge is a cheap downstream re-cut; a lost boundary is not recoverable), mirroring the ERE stance.
  **Partial failure — the coalescer over-merges two genuinely distinct activities:** it must not; the
  invariant test asserts a boundary survives on every dimension shift, so a merge that crosses a shift
  is a defect, not an acceptable coarsening.
- **INV-SCREEN-F — client offline buffers and backfills without duplicating observations.** Offline,
  the client buffers raw bundles locally (bounded, durable — see SCREEN-03 Restart posture); on
  reconnect it backfills. Idempotency is by **content_identity + capture timestamp**, reusing the raw
  store's existing idempotent-by-`content_identity` behavior. **Partial failure — client ships, host
  lands the frame, the ack is lost before the client marks it sent:** the client re-ships; the host
  **dedups** on `content_identity` (existing behavior) and no duplicate observation is produced.

If these invariants cannot all hold at the seam boundaries, the task cuts are wrong; re-cut before
filing issues.

## Provisional constants (named, single-sourced, tunable)

Like the ERE thresholds, the screen-stream tunables are **named constants documented as provisional**,
declared once and settings-governed (SETTINGS_SPINE posture, SCREEN-06), tuned after live data:

- `screen_capture_cadence_seconds` — sample interval (idle-adaptive: a locked/idle screen is not
  sampled). Default provisional.
- `screen_frame_retention_minutes` — the bounded raw-frame reprocessing buffer (INV-SCREEN-A).
- `screen_client_buffer_max` — bounded offline buffer cap (SCREEN-03 Restart posture).
- `screen_coalesce_*` — dedup/coalescing sensitivity (SCREEN-02), preferring over-segmentation.

## Capability acceptance criteria

- [ ] A `screen`-modality observation validates against the extended Heimdal observation schema and
      publishes through the governed capture path (no bespoke store, no bespoke publish).
      Verify: `tests/heimdal/test_screen_observation_contract.py::test_screen_observation_validates_and_publishes` (SCREEN-01)
- [ ] Raw frames are derive-and-discard: a published observation exists while its frames are gone past
      the named retention buffer, and derivation-down ages frames out with a receipt rather than
      accumulating. Verify: `tests/heimdal/test_screen_frame_retention.py::test_frames_age_out_bounded_and_receipted` (SCREEN-01/02)
- [ ] Exclusion is capture-time: an excluded app's pixels never reach the host (asserted at the client
      capture entrypoint). Verify: `tests/heimdal/test_screen_exclusion.py::test_excluded_app_never_captured` (SCREEN-03/06)
- [ ] Pause is durable and PAUSED means no capture/buffer/ship, visibly. Verify: `tests/heimdal/test_screen_pause.py::test_pause_is_durable_and_total` (SCREEN-03/06)
- [ ] `screen` is registered in the ERE stream registry as `live` and consumed only via the registry;
      coalesced span boundaries survive into the segmenter's signal shape. Verify: `tests/episodes/test_stream_registry.py::test_screen_stream_registered_live` + `tests/heimdal/test_screen_coalescing.py::test_span_boundaries_survive_on_dimension_shift` (SCREEN-02/04)
- [ ] A rebuildable time-spend projection reconstructs by app/project/scope/day/week from observations
      alone (no episode dependency), and rebuilds deterministically from the observation stream.
      Verify: `tests/heimdal/test_time_spend_projection.py::test_time_spend_rebuilds_from_observations` (SCREEN-05)
- [ ] Every control-surface change (pause/resume, exclusion edit, retention tunable) emits a durable
      actor-tagged receipt. Verify: `tests/heimdal/test_screen_control_receipts.py::test_every_control_change_receipted` (SCREEN-06)
- [ ] Live validation on the test channel: ≥1 real at-computer session on the operator's machine
      produces recognizable activity spans + a time-spend rollup; receipt posted to the parent issue.
      Verify: parent-issue validation receipt (mac mini test channel)
- [ ] Owner-doc promotion only after acceptance: `docs/HEIMDAL/` modality note + the ERE registry flip
      (`future`→`live`) + a Heimdal STATUS line updated to delivered truth. Verify: doc writeback at
      `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory` (screen row → live)

## Relationship to GitHub issues

**Filed 2026-07-07.**

- Parent feature issue: **#3340**, filed `Backlog` + `agent:blocked` as the live validation hub.
  Draft body: [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md).
- Children, in dependency order, all filed `agent:blocked`: SCREEN-01 → **#3343** is the sole
  dependency-free head (per its `prerequisites: []` frontmatter) and flips to `agent:ready` once this
  spec PR merges to `main`; SCREEN-02 → **#3344** and SCREEN-03 → **#3341** (Bifrost-transfer note)
  stay blocked until SCREEN-01/#3343 merges; SCREEN-05 → **#3345** stays blocked until SCREEN-02/#3344
  merges; SCREEN-06 → **#3342** stays blocked until SCREEN-01/#3343 and SCREEN-03/#3341 merge;
  **SCREEN-04 → #3346 stays blocked until SCREEN-02/#3344 merges and is additionally, externally
  blocked on the ERE stream registry (#3176)**.

The spec is the source of truth; issues track pickup state.

## Out of scope (capability level)

- **Wearable / ambient-audio always-on capture** — that fork remains an **open owner decision**
  (`OWNER_DECISIONS.md` R-CONSENT; ideation loop 6 "the wearable/audio side of the fork remains open").
  This capability is desktop screen only.
- **Keylogging or input capture of any kind** — never. No keystrokes, no clipboard, no input events.
- **Screen recording (video)** — periodic still frames only, and those are derive-and-discard.
- **Multi-user consent machinery** — single-operator instance; single-party by construction (the
  owner's own machine). No third-party detection/degradation (there is no third party on a personal
  desktop; that machinery stays with the wearable/ambient fork).
- **Cloud egress of raw frames** — structurally closed for the always-on screen loop by the
  `paid_eligible: false` floor (RUNTIME_MODEL_POSTURE §1). The **one deliberate egress seam** is the
  derivation model provider governed by RUNTIME_MODEL_POSTURE + HEIM-12 (`heim_declared_egress`); its
  **off-switch** is that the screen derivation task kind is pinned local (the compiler rejects any paid
  route), plus pause. Enabling cloud vision derivation of raw pixels would require reclassifying the
  task kind — an owner decision that contradicts the floor, out of scope here.
- **The Conversational Journaling reflection layer** (`docs/CONVERSATIONAL_JOURNALING/`) — this spec
  names the seam and produces its raw material; it does not design the journaling conversation.
- **The Episode Resolution Engine core** — SCREEN-04 registers the stream; the segmentation/closure
  engine is ERE's own capability.

## Related docs

- `docs/HEIMDAL/CAPABILITY_CHARTER.md` (FIXED constraints, HEIM invariants), `docs/HEIMDAL/OWNER_DECISIONS.md`
  (D-CONSENT / D-PRIVACY / D-RETENTION; R-CONSENT reserved for the wearable fork)
- `docs/HEIMDAL/FABLE_COMPANION.md` (observation payload §1.3, confidence §2, event bus §4, backbone
  §5.2, threat model §7, HEIM-12 declared egress, v1 critical path §11)
- `docs/EVENTS.md :: Heimdal raw-evidence store` / `:: Heimdal gated raw-read path` / `:: Heimdal
  hard-retention ops job` (the reused machinery + `HEIMDAL_RAW_READ_ALLOWLIST` / `HEIMDAL_RAW_STORE_KEY`)
- `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md`, `.../README.md :: Input-source
  inventory`, `.../LOCATION_STREAM_FUTURE_POSTURE.md` (the same future→live pattern applied to `screen`)
- `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` (always-on-local floor; the egress off-switch)
- `docs/adr/ADR-0050-cross-repo-governance-and-bifrost-client-repo.md` (client home), `docs/contracts/MIMER_CLIENT_CONTRACT.md`
  (host-contract-for-a-Bifrost-client mirror), `docs/adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md`
- `docs/SETTINGS_SPINE/README.md` (tunables + receipt-every-write posture), `docs/architecture/SBS_OPERATING_MODEL.md`
  (classification), `docs/SECURITY_TRUST_BOUNDARIES.md` (LAN/Tailscale environment boundary)
- `docs/research/yggdrasil-closed-loops-ideation.md` (loop 6 — the owner ruling this capability enacts)
