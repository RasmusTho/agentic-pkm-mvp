---
name: Derive Activity Observations
description: The host-side derivation stage — screenshot + app metadata + local context providers become one textual activity observation via a local vision model, coalesced into spans, published markdown-first through the governed path
task_id: SCREEN-02
source_anchor: docs/HEIMDAL_SCREEN_STREAM/README.md :: Topology (derivation runs host-side)
parent_capability: Heimdal Screen Stream
prerequisites: [SCREEN-01]
depends_on: [DEFINE_SCREEN_OBSERVATION_CONTRACT.md]
can_parallelize_with: [BUILD_MACOS_OBSERVER_CLIENT]
---

# Derive Activity Observations

## Purpose

This is the in-seam derivation stage — the screen analog of Heimdal's ASR stage. It reads raw frame
bundles from the encrypted store, combines each frame with its frontmost-app metadata and any local
context providers, and produces **one textual activity observation** (markdown-first, minimized) that
publishes through the governed observation path. It also **coalesces** unchanged activity into spans so
the stream is not 120 identical "still writing the same doc" observations per hour — while preserving
the span boundaries the event motor needs.

## What This Task Does

1. **Read raw in-seam.** The stage reads frame bundles via the gated raw-read path
   (`read_raw_record(raw_ref, reader=..., purpose="screen_derivation")`), so the derivation reader is on
   `HEIMDAL_RAW_READ_ALLOWLIST` and every read is receipted (HEIM-5). Raw pixels never leave the host
   trust boundary.
2. **Derive one activity observation.** frame + frontmost app/window + local context providers →
   a concise textual activity summary (what the owner is doing: "editing the ERE spec in Obsidian",
   "reviewing PR #3185 in the browser"), plus surfaced entity mentions (apps, projects, docs, URLs).
   **Local context providers are extensible**: the frontmost-app/window is provider #1; others (active
   calendar event, current git branch of the frontmost editor, playing-media) plug in as declared
   providers without changing the derivation contract. Providers run host-side over the bundle; none
   re-reads the screen.
3. **Model routing per RUNTIME_MODEL_POSTURE (the binding floor).** Screen derivation is an **always-on
   loop** → its task kind is `paid_eligible: false` in the provider census; the routing compiler
   **rejects** any paid assignment (RUNTIME_MODEL_POSTURE §1/§4.2). Derivation therefore resolves to a
   **local vision model** (Ollama-servable). This is the structural off-switch for the raw-pixel egress
   seam — cloud vision derivation is not reachable for this task kind without an owner reclassification
   that contradicts the floor. The declared egress posture (HEIM-12) for this stage names **zero raw
   egress**.
4. **Coalesce into spans (INV-SCREEN-E).** Consecutive frames whose activity is unchanged collapse into
   one span observation with real `observed_at_start`/`observed_at_end` duration. A span boundary is
   created on **any** dimension shift — frontmost app, window/document, scope, or derived-goal change —
   because those are the ERE segmenter's five-dimension shifts (SCREEN-04). **Over-segmentation is
   preferred** (merge is a cheap downstream re-cut; a lost boundary is unrecoverable). Coalescing
   sensitivity is `screen_coalesce_*` (provisional constants, SCREEN-06-governed).
5. **Publish markdown-first through the governed path.** The stage assembles the SCREEN-01 payload and
   publishes via the existing `heimdal.publish.publish_full_observation` (schema-validated,
   `content_hash` stamped in the same write, revision-aware idempotency key). The Mimer candidate
   projector then writes the `heimdal_observation_candidate` note (`requires_review`, noncanonical,
   capture scope) through WriteGuard — reused, not reimplemented. The observation store is the record;
   any UI is a lens.
6. **Discard frames.** On successful publish (or coalesce-into-open-span), the covered frames become
   eligible for discard; the retention buffer (SCREEN-01 AC4) enforces the bound. Provenance is stamped
   before discard (INV-SCREEN-B) so the observation survives its frames.

## Concretely

```
$ python -m app.cli heimdal screen-derive --tick --json
{"frames_read": 24, "observations_published": 3, "spans_open": 1, "coalesced": 21, "model": "ollama:llava-*", "raw_egress": "none"}
# three published observations = three distinct activities in the last window; 21 unchanged frames coalesced into their spans
$ python -m app.cli heimdal screen-derive --route-explain
task_kind=heimdal.screen_derivation paid_eligible=false -> local vision model (compiler rejects any paid route)
```

## Why This Matters

Derivation is where raw pixels turn into privacy-conscious text and where the volume problem is solved.
Get the model routing wrong and an always-on loop silently bills cloud calls on raw screenshots (the
exact failure the always-on-local floor exists to prevent). Get coalescing wrong in the merge direction
and the event motor loses the boundaries it segments on; get it wrong in the split direction and the
stream floods — the invariant test pins the boundary-preserving direction.

## Acceptance Criteria

- [ ] AC1: a frame bundle + app metadata derives one activity observation with a textual summary,
      entity mentions, and per-axis confidence, published through `publish_full_observation` (governed
      path, not a bespoke insert). Verify: `tests/heimdal/test_screen_derivation.py::test_bundle_derives_and_publishes_observation`
- [ ] AC2 (enforcement): derivation reads raw only via the gated read path with a receipt, and the
      resolved model is local — asserted at the derivation call site: the router is invoked with the
      `heimdal.screen_derivation` task kind and a paid route is rejected. Verify: `tests/heimdal/test_screen_derivation_routing.py::test_screen_derivation_is_paid_ineligible_and_reads_raw_gated` (asserts `paid_eligible=false` rejection at the compiler + `read_raw_record` receipt at the production call site)
- [ ] AC3: unchanged consecutive frames coalesce into one span with real start/end duration; a
      dimension shift (app/window/scope/goal) always creates a new span boundary — a merge across a
      shift fails the test. Verify: `tests/heimdal/test_screen_coalescing.py::test_span_boundaries_survive_on_dimension_shift`
- [ ] AC4: provenance (machine + observed-at window + derivation `stage_versions`/`model_ref`) is
      stamped in the same durable write as the observation; a bundle that derives text but cannot stamp
      complete provenance refuses to publish (INV-SCREEN-B). Verify: `tests/heimdal/test_screen_derivation.py::test_unprovenanced_observation_refuses_publish`
- [ ] AC5: local context providers are pluggable — adding a provider changes the derived summary/mentions
      without changing the observation contract or the derivation entrypoint signature. Verify: `tests/heimdal/test_screen_context_providers.py::test_provider_registry_extensible`
- [ ] AC6 (non-behavioral): the declared egress posture for the screen-derivation stage names zero raw
      egress (HEIM-12). Verify: doc writeback at `docs/HEIMDAL_SCREEN_STREAM/DERIVE_ACTIVITY_OBSERVATIONS.md :: What This Task Does` (step 3) + `tests/invariants/test_heimdal_seam.py::test_declared_egress` extended with the screen stage

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/heimdal/test_screen_derivation.py tests/heimdal/test_screen_derivation_routing.py tests/heimdal/test_screen_coalescing.py tests/heimdal/test_screen_context_providers.py
pytest -q -m "not pg"        # full suite: shared publish + routing hot path
```

## Out of Scope

The capture endpoint + schema (SCREEN-01); the client (SCREEN-03); ERE consumption of the spans
(SCREEN-04); the time-spend rollup over observations (SCREEN-05); the control surface (SCREEN-06). No
diarization/third-party analog (single-party by construction). No cloud vision path (structurally
rejected).

## Restart / Durability Posture

The derivation stage is a stateless tick over durable inputs (the raw store) and durable outputs (the
observation log): a crash mid-tick loses no published observation (idempotency-keyed publish dedups on
replay) and no raw frame (frames stay in the buffer until derived or aged out). An **open span**
(activity still ongoing at crash) is reconstructed on the next tick from the buffered frames — nothing
user-facing is lost. This is why frame discard is gated on successful publish, not on the tick starting.

## Related Docs

- `docs/HEIMDAL/FABLE_COMPANION.md` §5.2 (in-seam derivation, shared engine as library not service), §7.3/T3 (local-only derivation), HEIM-12 (declared egress)
- `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` §1/§4.2 (always-on-local floor — the binding routing constraint)
- `docs/EVENTS.md :: Heimdal gated raw-read path` (`HEIMDAL_RAW_READ_ALLOWLIST`, read receipts) / `:: Publish` (governed publish path)
- `docs/HEIMDAL_SCREEN_STREAM/README.md :: Cross-Task Invariants` (INV-SCREEN-B, INV-SCREEN-E)

## Related GitHub Issues

One issue: `[Heimdal Screen Stream] derive-activity-observations: local-vision derivation + span coalescing + governed publish`. Blocked until SCREEN-01 merges. Likely **opus-tier** (derivation-model routing, coalescing invariant, privacy seam). See scratchpad draft.
