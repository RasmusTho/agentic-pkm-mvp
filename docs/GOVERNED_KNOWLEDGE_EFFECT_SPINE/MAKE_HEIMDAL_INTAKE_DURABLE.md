---
name: Make Heimdal Intake Durable
description: Prevent cursor advance until candidate persistence is durable and replay-safe.
task_id: GKES-02
source_anchor: app.heimdal.projector :: project_pending_observations
parent_capability: Governed Knowledge Effect Spine
prerequisites: [GKES-01]
depends_on: [DEFINE_EFFECT_SPINE_CONTRACTS.md]
can_parallelize_with: [ENFORCE_GOVERNED_EFFECT_TOKENS]
---

# Make Heimdal Intake Durable

## Purpose

Eliminate the confirmed cursor/data-loss seam in the Heimdal candidate projector.

## What This Task Does

Make candidate persistence, receipt/recovery record, and cursor advance an idempotent sequence. A blocked or partial write leaves the item replayable and visible; retry cannot duplicate the candidate.

## Concretely

Change only the projector/cursor/persistence seam and its producers, bootstrap paths and fixtures. Reuse the existing log/cursor and storage transaction mechanisms where sufficient; do not introduce a broker without a verified gap.

## Why This Matters

Silent evidence loss is irreversible and has the highest downstream reconstruction cost.

## Acceptance Criteria

- [ ] A blocked candidate write never advances the production projector cursor. Verify: `tests/heimdal/test_projector.py::test_cursor_does_not_advance_when_candidate_write_is_blocked`.
- [ ] Replay after a partial write materializes at most one candidate for an observation. Verify: `tests/heimdal/test_projector.py::test_projector_replay_is_idempotent_after_partial_write`.
- [ ] Restart resumes pending work without skipping a mixed batch. Verify: `tests/heimdal/test_projector.py::test_projector_restart_resumes_unpersisted_observation`.
- [ ] Bootstrap, existing-resource migration and fixtures satisfy the new precondition and fail loud when they do not. Verify: `tests/heimdal/test_projector.py::test_projector_preflight_rejects_missing_durable_intake_state`.

## How to Verify (Pre-Merge)

- `pytest -q tests/heimdal/test_projector.py tests/heimdal/test_observation_log.py`
- `ruff check app tests`

## Out of Scope

Semantic identity, HKA promotion, and DRI rebuild.

## Related Docs

- `docs/HEIMDAL/FABLE_COMPANION.md :: HEIM-9`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md :: Watcher lifecycle / wrong folder / crash`

## Related GitHub Issues

Blocked by GKES-01; unblocks GKES-03 and GKES-07.
