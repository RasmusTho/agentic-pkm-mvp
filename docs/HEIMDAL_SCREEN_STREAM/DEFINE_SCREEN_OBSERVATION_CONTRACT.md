---
name: Define Screen Observation Contract
description: The host-side contract for the screen modality — observation schema (extends heimdal.observation.published.v1), the capture ingestion endpoint obligations, client obligations, and the derive-and-discard raw-frame posture with a named retention buffer
task_id: SCREEN-01
source_anchor: docs/HEIMDAL_SCREEN_STREAM/README.md :: Topology — client / host split
parent_capability: Heimdal Screen Stream
prerequisites: []
depends_on: []
can_parallelize_with: [Build macOS Observer Client]
---

# Define Screen Observation Contract

## Purpose

The screen modality needs a **host-side contract** before either the derivation stage (SCREEN-02) or
the client (SCREEN-03) can be built against it. This task fixes three things: (1) the **observation
schema** for `modality: screen` (an extension of `heimdal.observation.published.v1`, not a new event
family); (2) the **capture ingestion endpoint** obligations (what the host accepts, admits, lands, and
acks); (3) the **raw-frame posture** (derive-and-discard by default; a bounded reprocessing buffer with
a named retention constant). It is the `docs/contracts/`-level addition plus a host endpoint skeleton,
mirroring how `docs/contracts/MIMER_CLIENT_CONTRACT.md` specifies the host side that a Bifrost client
consumes.

## What This Task Does

1. **Observation schema (`modality: screen`).** Extends the Heimdal observation payload
   (`FABLE_COMPANION.md` §1.3) — no new required fields beyond what a screen observation genuinely
   carries; conform to the existing families:
   - **identity**: `observation_id`, `episode_id` (one continuous at-computer session under the
     standing grant = one episode; coalesced spans are `sequence`-ordered observations within it),
     `sequence`, `revision_of` / `supersedes`.
   - **time**: `observed_at_start`, `observed_at_end` (**spans carry real duration — load-bearing for
     time-spend**, SCREEN-05), `clock_basis: device_metadata` (the client machine clock), `captured_at`.
   - **machine**: the **work-machine identity** (stable device id + human label) — the provenance axis
     screen adds over voice (multi-machine); part of `provenance.sensor` and surfaced for the time-spend
     rollup and INV-SCREEN-B.
   - **content**: `modality: screen`; `content` = the **derived textual activity summary** (minimized,
     markdown-first — the observation is *text*, never pixels); `content_structure` = span boundaries +
     per-span frontmost app / window / scope; `raw_ref` = opaque handle into the frame buffer (resolves
     only via the gated read path; discarded after retention → becomes a declared dangling ref);
     `withheld[]` = excluded spans declared (`excluded_app`, `excluded_scope`) so absence is explicit.
   - **actors**: exactly one `speaker`/`recorder` = the operator, `resolution: resolved`,
     `basis: capture_context`, confidence `by_construction` (single-party, the owner's own machine).
   - **entities**: `entity_mentions[]` — apps, projects, documents, URLs surfaced in the derived
     summary, three-state resolution against the shared register (§3).
   - **confidence**: per-axis block (never scalar): `derivation` (vision/LLM certainty, `heuristic`),
     `activity_classification` (how sure the activity label is), `attribution` (`by_construction`),
     `temporal` (from `clock_basis`).
   - **provenance**: `sensor = {adapter, version, machine}`, `capture_chain[]`
     (e.g. `["macos_screen_observer", "loopback_capture_post"]` co-located, or
     `["macos_screen_observer", "tailscale_capture_post"]` cross-machine — the trust boundary legible
     per observation, §7), `content_hash`, `content_identity` (of the raw frame bundle),
     `stage_versions` (vision + derivation stage), `raw_ref`.
   - **sensitivity / consent / scope**: `sensitivity` default high; `scope_hint` = the capture scope
     stamped per span (reclassification only downstream via governed flows — conform §1.5);
     `consent = { basis: screen_always_on, grant_ref, third_party: none }`.
2. **Ingestion endpoint obligations.** The host capture endpoint (an extension of the Heimdal capture
   path, not a bespoke server):
   - Admits each bundle under the **standing `screen_always_on` consent grant** via the existing
     `consent_ledger.admit_raw_evidence` gate — no active grant ⇒ refuse loudly, the one signal→raw
     gate no route bypasses (HEIM-3).
   - Requires the posting client to be a **registered sensor** (`register_sensor`); an unregistered
     identity refuses loudly (T5).
   - Lands raw frames in the encrypted `heimdal_raw_record` store (reuse — `HEIMDAL_RAW_STORE_KEY`,
     AES-256-GCM, append-only, provenance stamped in the same write), **idempotent by `content_identity`**.
   - Accepts **two bundle shapes**: `raw_capture_bundle` (frames + metadata → host derives; the
     **default**) and `derived_observation` (client already derived → the declared **future** on-device
     path; the contract holds it now, SCREEN-02 does not build it). This is the contract-first/module-lazy
     seam that lets derivation move on-device later without a contract change.
   - Returns a durable **ack** the client uses to release its offline-buffer entry (INV-SCREEN-F).
3. **Client obligations (contract side).** The endpoint contract declares what a conforming client must
   do; SCREEN-03 implements it: cadence + idle-adaptivity, batching, durable offline buffering with
   backfill, exclusion honored at capture, pause honored locally. Stated here so the Bifrost client has
   a repo-durable contract to build against.
4. **Raw-frame posture (the load-bearing privacy decision).**
   - **Derive-and-discard is the default**: a frame is discarded as soon as its observation is derived
     or coalesced (SCREEN-02).
   - **Bounded reprocessing buffer**: frames are retained only for `screen_frame_retention_minutes`
     (named constant, markdown-first in `_heimdal/settings.md`, fail-loud if unset — same posture as
     `retention_window_days`; **tight**, minutes/low hours, because frame volume dwarfs voice-memo
     volume). Past the window they are hard-deleted through the one governed append-only exception,
     each paired with a `heimdal_raw_deletion_receipt` (reason `screen_frame_retention_buffer`).
   - **Derivation-down ages frames out** (INV-SCREEN-A): bounded loss, receipted, never accumulation.

## Concretely

```
# schema validates a screen observation and the publish path accepts it
$ python -m app.cli heimdal validate-observation --modality screen fixtures/screen_obs.json
ok: heimdal.observation.published.v1 (modality=screen)

# the frame retention buffer is a named, fail-loud constant
$ python -m app.cli heimdal screen-retention --explain
screen_frame_retention_minutes=45 (source: _heimdal/settings.md)   # unset -> RetentionWindowMissingError-analog, never a default
```

## Why This Matters

Without the host contract fixed first, SCREEN-02 and SCREEN-03 would each invent a shape and drift, and
the "derive-and-discard, bounded buffer" privacy posture would be an afterthought rather than the
schema-and-endpoint-level guarantee it must be. Fixing the two accepted bundle shapes now is what lets
derivation move on-device (v2) without breaking the client or re-cutting the stream.

## Acceptance Criteria

- [ ] AC1: a `modality: screen` observation validates against the (extended) `heimdal.observation.published.v1`
      schema — required families present (identity, time incl. `observed_at_end`, machine, content,
      attribution=operator, per-axis confidence, provenance, consent). Verify: `tests/heimdal/test_screen_observation_contract.py::test_screen_observation_validates_and_publishes`
- [ ] AC2 (enforcement): the ingestion endpoint admits a bundle **only** through the existing
      `consent_ledger.admit_raw_evidence` gate and refuses an unregistered sensor — asserted at the
      endpoint's production call site, not on the gate in isolation. Verify: `tests/heimdal/test_screen_capture_endpoint.py::test_endpoint_admits_only_via_consent_gate_and_registered_sensor` (asserts the endpoint handler invokes `admit_raw_evidence` + `register_sensor` before any raw write)
- [ ] AC3: raw frames land in the shared encrypted `heimdal_raw_record` store, idempotent by
      `content_identity` (a re-posted bundle returns the existing row, no duplicate). Verify: `tests/heimdal/test_screen_capture_endpoint.py::test_frame_bundle_lands_encrypted_idempotent`
- [ ] AC4: `screen_frame_retention_minutes` is read markdown-first from `_heimdal/settings.md`, fail-loud
      when unset (never a default bound for an irreversible act); frames past it hard-delete with a
      deletion receipt. Verify: `tests/heimdal/test_screen_frame_retention.py::test_frames_age_out_bounded_and_receipted`
- [ ] AC5: the endpoint accepts both `raw_capture_bundle` and `derived_observation` bundle shapes at the
      contract level (the latter routed to publish directly; the former to the host derivation seam).
      Verify: `tests/heimdal/test_screen_capture_endpoint.py::test_both_bundle_shapes_accepted`
- [ ] AC6 (non-behavioral): the host-side contract is written as a `docs/contracts/`-level doc that a
      Bifrost client consumes (mirroring `MIMER_CLIENT_CONTRACT.md`). Verify: doc writeback at `docs/contracts/HEIMDAL_SCREEN_CLIENT_CONTRACT.md :: Observation schema` and `:: Ingestion endpoint obligations`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/heimdal/test_screen_observation_contract.py tests/heimdal/test_screen_capture_endpoint.py tests/heimdal/test_screen_frame_retention.py
pytest -q -m "not pg"        # full suite: capture path is shared/hot-path
```

AC2's call-site assertion lands even before SCREEN-02's derivation body exists (a `raw_capture_bundle`
lands in the raw store and returns an ack; derivation is SCREEN-02).

## Out of Scope

The derivation logic itself (SCREEN-02); the client (SCREEN-03); the on-device `derived_observation`
producer (declared future — the contract holds the shape, no producer built); the ERE registry entry
(SCREEN-04); the time-spend projection (SCREEN-05); the control surface (SCREEN-06). No change to the
voice-memo modality.

## Restart / Durability Posture

Not applicable to this task's own deliverables (schema + endpoint skeleton are stateless request
handlers over the durable raw store). The durability-sensitive surfaces — the client offline buffer and
the pause state — are SCREEN-03's; the frame retention buffer is durable on the host raw store and
governed by AC4. This task fixes the **contract** those durability postures satisfy.

## Related Docs

- `docs/HEIMDAL/FABLE_COMPANION.md` §1.3 (observation payload), §2 (confidence axes), §7 (threat model)
- `docs/EVENTS.md :: Heimdal raw-evidence store + voice-memo capture adapter` (the reused store + endpoint discipline; `HEIMDAL_RAW_STORE_KEY`)
- `docs/contracts/MIMER_CLIENT_CONTRACT.md` (the host-contract-for-a-Bifrost-client mirror pattern)
- `docs/HEIMDAL_SCREEN_STREAM/README.md :: Cross-Task Invariants` (INV-SCREEN-A/B/F)

## Related GitHub Issues

One issue: `[Heimdal Screen Stream] screen-observation-contract: schema + capture endpoint + derive-and-discard raw posture`. Ready immediately (no prerequisites). Likely **opus-tier** (contract/provenance/privacy-seam design). See scratchpad draft.
