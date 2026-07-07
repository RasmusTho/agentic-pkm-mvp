---
name: Two-Stream Segmentation Core
description: The segmenter — consume Heimdal observations + vault activity via the stream registry, detect five-dimension shifts, emit proposed Episode notes with derived_from provenance
task_id: ERE-04
source_anchor: docs/research/EPISODE_RESOLUTION_ENGINE.md :: The three jobs (job 1) + Suggested build order (step 1)
parent_capability: Episode Resolution Engine
prerequisites: [ERE-01, ERE-02]
depends_on: [STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md, EPISODE_NOTE_STORE_AND_PROJECTION.md]
can_parallelize_with: []
---

# Two-Stream Segmentation Core

## Purpose

The engine's first job: turn the signal timeline into *proposed* Episodes. Per the research build order, two streams first — Heimdal voice observations + vault activity — enough to prove segmentation end-to-end without waiting on the open RQ-E1 threshold research.

## What This Task Does

1. **Consumers** (resolved via the ERE-01 registry only):
   - `heimdal.observations`: an observation-log cursor consumer, `consumer_id = "mimer.episode_resolution_engine"`, using the canonical `app/heimdal/publish.py` read path (`read_observations_for_consumer` / `advance_cursor_for_consumer`; never direct table imports, per #3039). At-least-once: segmentation must be idempotent under redelivery (fold-by-key, following `candidate_projection.py::_fold_key` precedent).
   - `vault.activity`: an outbox consumer on `ingest.vault.changed` / `ingest.object.created` / `ingest.object.deleted` per the `docs/EVENTS.md` consumer contract, enriched with `extract_context_dimensions_for_note` frontmatter dimensions.
2. **Single-stream hints as input, per ADR-0054**: Heimdal's per-session `episode_id` on each observation is consumed as a boundary *hint* (a session = a candidate atomic segment). No Heimdal-side change — the hint already exists on the envelope.
3. **Five-dimension shift detection** (ADR-0051 commitment 2) with **conservative initial thresholds**, declared as named constants in one place and documented as provisional pending RQ-E1: time-gap (default: >45 min without signals closes the open segment window), goal shift (different Project/Area binding of touched notes), protagonist shift (attribution change across observations), place shift (absent in v1 — space is unfed until calendar/location streams land), causal break (explicit `supersedes`/new-session markers). Over-segmentation is preferred over under-segmentation: merging is a cheap human re-cut; splitting a wrongly-fused episode is costlier.
4. **Emission**: a detected segment becomes a `segmentation: proposed` Episode note via the ERE-02 store (proposal class), with `derived_from` carrying every supporting signal ref (observation ids, vault event ids) and `time.start/end` from bitemporal `observed_at`, never emission time.
5. **Tick integration**: runs as a deterministic tick (watcher-tick style, following `run_watcher_tick` / `relevance_tick.py` precedents), not a daemon; each tick consumes deltas, updates open-segment state in the projection, and emits any completed proposals.

## Concretely

```
$ python -m app.cli episodes tick --json
{"consumed": {"heimdal.observations": 4, "vault.activity": 12}, "proposed": ["ep-..."], "open_segments": 1}
# rerunning the tick with no new signals proposes nothing (idempotent)
```

## Why This Matters

This is the organ ADR-0051 presupposed and nobody built. If it over-fuses, unrelated situations blur (bad retrieval context); if it double-emits under redelivery, the vault fills with duplicate episodes; if it consumes sources outside the registry, the input-source architecture (ERE-01) is fiction.

## Acceptance Criteria

- [ ] AC1: given a fixture stream (two Heimdal sessions + interleaved vault edits with a >45 min gap), the segmenter proposes exactly two episodes with correct bitemporal bounds and complete `derived_from`. Verify: `tests/episodes/test_segmentation_core.py::test_two_stream_fixture_segments_into_expected_episodes`
- [ ] AC2: redelivered observations (cursor replay) do not double-propose — idempotent under at-least-once. Verify: `tests/episodes/test_segmentation_core.py::test_segmentation_idempotent_under_redelivery`
- [ ] AC3: Heimdal per-session `episode_id` acts as a boundary hint — one session never spans two proposed episodes. Verify: `tests/episodes/test_segmentation_core.py::test_heimdal_session_hint_respected`
- [ ] AC4 (enforcement): consumers are resolved through the stream registry at the production entrypoint; a live-but-unregistered source is not consumed. Verify: `tests/episodes/test_stream_registry.py::test_engine_consumes_only_registered_streams` (shared with ERE-01 AC5, now against the real segmenter body)
- [ ] AC5: proposed notes carry `segmentation: proposed` and pass the episode-note schema; the proposal-class write discipline of ERE-02 holds on this path. Verify: `tests/episodes/test_segmentation_core.py::test_proposals_are_schema_valid_proposal_class`
- [ ] AC6: threshold constants are named, single-sourced, and documented as provisional (RQ-E1). Verify: doc writeback at `docs/EPISODE_RESOLUTION_ENGINE/README.md :: Provisional thresholds (RQ-E1)`
- [ ] AC7: signals lacking scope context never cause a cross-scope fuse — segments are keyed per-scope in v1 (posture enforced fully in ERE-08; this AC pins the default). Verify: `tests/episodes/test_segmentation_core.py::test_segments_keyed_per_scope_by_default`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/
pytest -q -m "not pg"          # full suite: hot-path shared consumers
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat  # vault/hot-path change → opt-in UAT gate
```

## Out of Scope

`episode_ref` assignment to other artifacts (ERE-05); closure detection (ERE-06); re-cut handling (ERE-07); cross-scope fusion beyond the per-scope default (ERE-08); calendar/location streams (ERE-09/ERE-10); RQ-E1 threshold tuning against the real vault (parent-issue validation phase).

## Restart / Durability Posture

Open-segment state lives in the PG projection (rebuildable) and cursors are durable DB rows; a restart resumes from cursors and re-derives open segments. Nothing user-facing depends on in-memory state; worst case after a crash is a re-proposed (idempotency-deduped) episode.

## Related Docs

- [ADR-0054](../adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) §3 (the seam), [ADR-0051](../adr/ADR-0051-episode-as-ontological-primitive.md) commitment 2 (shift detector)
- `app/heimdal/publish.py` (cursor consumer contract), `app/heimdal/candidate_projection.py` (fold precedent)
- `docs/EVENTS.md` §Outbox consumer contract; `app/watcher/vault_watcher.py::extract_context_dimensions_for_note`

## Related GitHub Issues

One issue: `[Episode Resolution Engine] segmentation-core: two-stream five-dimension segmenter emitting proposed episodes`. Blocked until ERE-01 + ERE-02 merge.
