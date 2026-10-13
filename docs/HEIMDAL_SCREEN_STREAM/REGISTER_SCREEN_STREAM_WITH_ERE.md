---
name: Register Screen Stream With ERE
description: Register the screen modality as a live ERE stream per the signal contract — flip screen from future to live in the stream registry, mapping coalesced spans to the five-dimension signal shape; ERE-01 and SCREEN-02 prerequisites are delivered
task_id: SCREEN-04
source_anchor: docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md :: seeded inventory (future -> live)
parent_capability: Heimdal Screen Stream
prerequisites: [ERE-01, SCREEN-02]
depends_on: [DERIVE_ACTIVITY_OBSERVATIONS.md]
can_parallelize_with: []
---

# Register Screen Stream With ERE

## Purpose

The screen stream is *"the single richest episode-segmentation signal"* (ideation loop 6) — the event
motor's best feed. In the ERE stream registry the `screen` modality is currently declared
`status: future` with nothing behind it (`STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md`; README inventory).
This task flips it to **live**: a registry entry + the signal adaptation from coalesced screen spans to
the ERE normalized signal shape. It is the exact `future`→`live` transition
`LOCATION_STREAM_FUTURE_POSTURE.md` describes for its modality, applied to `screen` now that the
capture + derivation legs exist.

## Prerequisite status

ERE-01 (#3176) and SCREEN-02 (#3344) are delivered, so the prerequisites for this bounded slice are
met. The `screen` registry entry remains `future` until SCREEN-04 (#3346) lands. This slice registers
already-published observations; it does not start screen capture, change a consent grant, or promote
observations to authoritative knowledge.

## What This Task Does

1. **Flip the registry entry.** `screen` moves from `status: future` to `status: live` in the
   markdown-first stream registry, with: `transport: observation_log cursor (modality-filtered)`,
   `consent_class: heimdal_gated`, `owner_constituent: heimdal`, `cadence: continuous`, and
   `dimensions_fed: [time, space, protagonist, goal, causation]` (declared per axis; its design
   strengths are high for time/protagonist/goal, medium for causation, and low for space). The
   registry declares supported axes as the existing ERE contract requires; each normalized signal
   carries observation-derived `ConfidenceScore`s. The consent class describes the existing
   published-observation gate; registering the stream does not grant consent.
2. **Signal adaptation.** A screen span observation maps to the ERE normalized signal shape:
   `stream_id: screen`, `signal_id` (idempotency = observation_id), `observed_at` (span start;
   `emitted_at` separate — bitemporal, mirroring `heimdal.observation.published`), `dimensions_fed`
   with per-dimension confidence carried from the observation's confidence axes, `scope_binding` from
   the span's `scope_hint`, and `provenance_ref` to the canonical Heimdal observation identity
   (`heimdal.observations:<observation_id>`). The registry `stream_id` remains `screen`; provenance
   identifies the source row so first-time screen consumption can replay records already represented
   by the former generic observation consumer without changing their identity.
3. **Span boundaries are the segmentation signal (INV-SCREEN-E closes here).** The whole point of
   preserving span boundaries in SCREEN-02 is this consumer: each boundary (app/window/scope/goal shift)
   is a candidate five-dimension shift the segmenter evaluates. This task asserts the boundaries survive
   into the signal shape — a coalescer that dropped a boundary would be caught here as a lost segment.
4. **Consume via the registry only.** Per ERE-01 AC5 (enforcement), the engine enumerates sources only
   via the registry; `screen` is consumed like any other registered stream, no engine change beyond the
   entry + adapter.

## Concretely

```
$ python -m app.cli episodes streams --json | jq '.streams[] | select(.stream_id=="screen") | .status'
"live"
$ python -m app.cli episodes tick --json     # consumes already-published screen observations through the registry
{"proposed_episodes": 6, "streams_consumed": ["screen", "vault.activity", "calendar", ...]}
```

## Why This Matters

Registering `screen` is what turns the observation stream into the event motor's richest feed —
without it the spans are a time-spend log but not an episode-segmentation signal. Doing it *through the
registry* (not a hardcoded consumer) is what keeps the ERE's "every input source declared and consumed
via contract" invariant intact; a bespoke screen consumer would silently reshape the segmenter.

## Acceptance Criteria

- [ ] AC1: the registry carries `screen` as `status: live` with transport, consent_class, cadence,
      owner_constituent, and per-axis `dimensions_fed` declared; registry validation accepts it (live
      entry binds to an existing transport — the observation-log cursor). Verify: `tests/episodes/test_stream_registry.py::test_screen_stream_registered_live`
- [ ] AC2: a screen span observation adapts to a valid ERE normalized signal (bitemporal, per-dimension
      confidence, provenance_ref, scope_binding). Verify: `tests/episodes/test_screen_stream_adapter.py::test_screen_span_maps_to_signal_contract`
- [ ] AC3 (enforcement): the segmenter consumes `screen` **only** via the registry — a hardcoded /
      unregistered screen consumer is rejected at the engine's consumption entrypoint (rides ERE-01 AC5).
      Verify: `tests/episodes/test_stream_registry.py::test_engine_consumes_only_registered_streams` (extended with the screen case)
- [ ] AC4: span boundaries survive into the signal shape — each app/window/scope/goal shift is a
      distinct signal the segmenter can treat as a candidate dimension shift. Verify: `tests/episodes/test_screen_stream_adapter.py::test_span_boundaries_become_distinct_signals`
- [ ] AC5 (non-behavioral): the ERE inventory table flips the `screen` row `future`→`live` and the
      capability README reflects the live registration. Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory` (screen row → live)

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_stream_registry.py tests/episodes/test_screen_stream_adapter.py
```

The PR test selector adds the focused subsystem suite for changed runtime paths. This bounded Tier 2
slice does not prescribe the repository-wide `pytest -q -m "not pg"` lane; run broader coverage only
when a named failure mode or the current selector requires it, per
`GOVERNANCE_PROPORTIONALITY.md :: Evidence reuse and stop rule` and
`TEST_STRATEGY_HOT_PATH.md :: Runtime / Code PRs`.

ERE-01 (#3176) is already delivered; this slice uses its registry, signal contract, and
`test_stream_registry.py` enforcement.

## Out of Scope

The ERE segmentation core, closure, and decay (ERE's own tasks — this task only registers the stream);
the derivation/coalescing (SCREEN-02); the episode-level time-spend rollup (SCREEN-05 future enrichment
seam). No change to any other registry entry.

## Restart / Durability Posture

The adapter itself is stateless. Its `provenance_ref` retains the canonical Heimdal observation
identity, so ERE's existing exact-scope open-segment and canonical-note admission remains idempotent
when the screen cursor first replays rows already handled by the former generic consumer. Cursor and
canonical-note durability remain ERE-01/04's posture; SCREEN-04 adds no separate state surface.

## Related Docs

- `docs/EPISODE_RESOLUTION_ENGINE/STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md` (the signal + registry-entry contract)
- `docs/EPISODE_RESOLUTION_ENGINE/LOCATION_STREAM_FUTURE_POSTURE.md` (the same `future`→`live` pattern, mirrored)
- `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Input-source inventory` (the row this flips)
- `docs/HEIMDAL_SCREEN_STREAM/README.md :: Cross-Task Invariants` (INV-SCREEN-E closes at this consumer)

## Related GitHub Issues

One issue: #3346 `[Heimdal Screen Stream] register-screen-stream: flip screen from future to live in the ERE registry`. Its prerequisites ERE-01 (#3176) and SCREEN-02 (#3344) are delivered. This is the bounded implementation child of the still-open parent validation hub #3340; live capture and broader capability acceptance remain outside this slice.
