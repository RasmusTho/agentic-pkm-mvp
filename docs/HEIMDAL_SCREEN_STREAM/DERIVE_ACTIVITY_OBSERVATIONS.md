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
   loop** → its task kind (`heimdal.screen_derivation`) is `paid_eligible: false` in the provider census;
   the routing compiler **rejects** any paid assignment (RUNTIME_MODEL_POSTURE §1/§4.2). Derivation
   therefore resolves to a **local vision model** (Ollama-servable, census-declared `ollama/llava:7b`).
   This is the structural off-switch for the raw-pixel egress seam — cloud vision derivation is not
   reachable for this task kind without an owner reclassification that contradicts the floor.

   **Declared egress posture (HEIM-12), delivered:** this stage declares **zero raw egress** — raw-class
   evidence (`screen_frame`) never leaves the host trust boundary, and the stage's only model destination
   is the host-local vision model. The declaration is structured and machine-checkable
   (`app/heimdal/screen_derivation.py :: DECLARED_EGRESS`), not prose, and it is enforced on **both**
   halves of the seam:

   - *the provider*: `resolve_derivation_route` refuses to compile a route at all when the census claims
     this task kind as paid-eligible or when the resolved provider is not `tier: local`, so the refusal
     lands before a single frame is read;
   - *the destination*: a census entry proves a provider **name** is local, never that the socket a
     decrypted frame is about to be written to is on this machine. The endpoint must be loopback, or
     a hostname the operator explicitly declared host-local in
     `HEIMDAL_SCREEN_VISION_HOST_LOCAL_HOSTS` (the container-network case), or the derivation is
     refused before the frame is attached to any request. Three escapes off that validated
     destination are closed explicitly, because each was found reachable in review: an ambient
     `HTTP_PROXY` (the request runs with `trust_env` disabled), an HTTP **redirect** (refused, never
     followed — a local model has no reason to redirect `/api/chat` elsewhere), and a **URL-parser
     differential** (host-locality is asserted on the exact prepared URL the client will dial, using
     the client's own parser, so a validated destination and a dialled destination cannot diverge).

   Enforced by `tests/invariants/test_heimdal_seam.py::test_declared_egress`, the §8-reserved home
   HEIM-12's static half now graduates into, plus
   `tests/heimdal/test_screen_derivation_routing.py::test_raw_frames_refuse_a_destination_that_is_not_host_local`.
4. **Coalesce into spans (INV-SCREEN-E).** Consecutive frames whose activity is unchanged collapse into
   one span observation with real `observed_at_start`/`observed_at_end` duration. A span boundary is
   created on **any** dimension shift — frontmost app, window/document, scope, or derived-goal change —
   because those are the ERE segmenter's five-dimension shifts (SCREEN-04). **Over-segmentation is
   preferred** (merge is a cheap downstream re-cut; a lost boundary is unrecoverable). Three rules
   enforce that preference in the delivered stage:

   - a context provider that declares a **segmenter axis of its own** cuts spans on it too, so the
     built-in four are a floor, not a ceiling; and two providers may not claim one axis (the later
     write would move a boundary invisibly, so it is refused);
   - **unknown is not evidence of sameness**: a frame with *no* known dimension at all always starts
     its own span, so a fully blind client over-segments rather than collapsing a long window into
     one observation. One unknown axis does not switch coalescing off — that would flood the stream —
     so a client that loses `app`/`window` but still reports `scope` (the partial-Accessibility case)
     does still coalesce on what it knows;
   - a frame **out of capture order** forces a boundary instead of publishing a span that ends before
     it began.

   Coalescing sensitivity is `screen_coalesce_*` (provisional constants, SCREEN-06-governed); this
   slice ships no max-gap bound, so two identical frames far apart still merge — SCREEN-05's
   time-spend rollup should not assume a bounded gap until SCREEN-06 lands.
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

- [x] AC1: a frame bundle + app metadata derives one activity observation with a textual summary,
      entity mentions, and per-axis confidence, published through `publish_full_observation` (governed
      path, not a bespoke insert). Verify: `tests/heimdal/test_screen_derivation.py::test_bundle_derives_and_publishes_observation`
- [x] AC2 (enforcement): derivation reads raw only via the gated read path with a receipt, and the
      resolved model is local — asserted at the derivation call site: the router is invoked with the
      `heimdal.screen_derivation` task kind and a paid route is rejected. Verify: `tests/heimdal/test_screen_derivation_routing.py::test_screen_derivation_is_paid_ineligible_and_reads_raw_gated` (asserts `paid_eligible=false` rejection at the compiler + `read_raw_record` receipt at the production call site)
- [x] AC3: unchanged consecutive frames coalesce into one span with real start/end duration; a
      dimension shift (app/window/scope/goal) always creates a new span boundary — a merge across a
      shift fails the test. Verify: `tests/heimdal/test_screen_coalescing.py::test_span_boundaries_survive_on_dimension_shift`
- [x] AC4: provenance (machine + observed-at window + derivation `stage_versions`/`model_ref`) is
      stamped in the same durable write as the observation; a bundle that derives text but cannot stamp
      complete provenance refuses to publish (INV-SCREEN-B). Verify: `tests/heimdal/test_screen_derivation.py::test_unprovenanced_observation_refuses_publish`
- [x] AC5: local context providers are pluggable — adding a provider changes the derived summary/mentions
      without changing the observation contract or the derivation entrypoint signature. Verify: `tests/heimdal/test_screen_context_providers.py::test_provider_registry_extensible`
- [x] AC6 (non-behavioral): the declared egress posture for the screen-derivation stage names zero raw
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
replay) and no raw frame (frames stay in the buffer until derived or aged out). This is why frame
discard is gated on successful publish, not on the tick starting.

**As delivered, a batch has no open span**: `derive_activity_observations` flushes its final span
before returning, and `observation_id` is derived from the covered frames' content identities, so a
re-derive of the *same* grouping dedups exactly. The consequence to know before building the tick
driver (SCREEN-06): an activity still ongoing at the batch boundary is published as a closed span, and
a later batch that groups those frames differently mints a different identity over overlapping frames
rather than extending the earlier span. Carrying an open span across ticks — the reconstruction this
section originally described — needs durable cross-tick span state and belongs with the tick driver,
not here. SCREEN-04's segmenter can merge adjacent spans; that is the cheap direction.

## Related Docs

- `docs/HEIMDAL/FABLE_COMPANION.md` §5.2 (in-seam derivation, shared engine as library not service), §7.3/T3 (local-only derivation), HEIM-12 (declared egress)
- `docs/MIMER_CAPABILITY_HARDENING/RUNTIME_MODEL_POSTURE.md` §1/§4.2 (always-on-local floor — the binding routing constraint)
- `docs/EVENTS.md :: Heimdal gated raw-read path` (`HEIMDAL_RAW_READ_ALLOWLIST`, read receipts) / `:: Publish` (governed publish path)
- `docs/HEIMDAL_SCREEN_STREAM/README.md :: Cross-Task Invariants` (INV-SCREEN-B, INV-SCREEN-E)

## Related GitHub Issues

One issue: #3344 `[Heimdal Screen Stream] derive-activity-observations: local-vision derivation + span coalescing + governed publish` — **delivered**. Its dependency SCREEN-01/#3343 merged first, as planned; every acceptance criterion above is checked against a passing named test. Delivered opus-tier (derivation-model routing, coalescing invariant, privacy seam).
