---
name: Trigger Debrief on Closure
description: Subscribe to episode-closure events; apply eligibility (artifact-count floor, scope inheritance) and idempotency so exactly one debrief-trigger is produced per eligible closed episode, never lost on partial failure
task_id: DEBRIEF-01
source_anchor: docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md :: Closure event (job 3, outbox `episode.closed`)
parent_capability: Episode Debrief
prerequisites: [ERE-02, ERE-04, ERE-06]
depends_on: []
can_parallelize_with: []
---

# Trigger Debrief on Closure

## Purpose

ERE's `episode.closed` event today drives decay only (`EMIT_CLOSURE_AND_DERIVE_DECAY.md`); closure has
no other consumer, so "closure → synthesis is unwired" (the gap named in
`docs/research/yggdrasil-closed-loops-ideation.md :: 4. Episode debrief`). This task is that seam's
first half: turn a closure event into a durable, idempotent, scope-respecting decision that a debrief
is owed — without inventing a parallel source of truth alongside the episode projection ERE already
maintains.

## What This Task Does

1. **Subscribe** to the `episode.closed` outbox topic (ERE-06) via a durable per-consumer cursor,
   following the house pattern (`app/heimdal/cursor_store.py::get_cursor` / `advance_cursor`,
   `consumer_id="episode_debrief.trigger"`) — fold-by-key on `episode_id` so at-least-once redelivery
   never double-triggers (mirrors ERE's own INV-ERE-F).
2. **Eligibility, checked at consumption time:**
   - **Minimum in-bounds artifact count** — a named, single-sourced, provisional constant
     (`EPISODE_DEBRIEF_MIN_ARTIFACT_COUNT`, documented provisional; eventually Settings-Spine-governed
     per `docs/SETTINGS_SPINE/README.md`, never hardcoded permanently). An episode closing with fewer
     bound artifacts than the floor is skipped, not an error — a two-artifact episode has nothing worth
     retro-ing.
   - **Scope gating** — the trigger reads the closed episode's own `scope` (single-scope by construction
     per `GATE_CROSS_SCOPE_FUSION.md`'s split-per-scope default; a fused cross-scope episode's scope is
     whatever the explicit `CrossScopeFlow` fuse produced) and carries it unchanged. This task performs
     **no** scope widening or narrowing of its own — it is a pure pass-through of the episode's already-
     resolved scope, so the debrief that follows can never fuse across scopes the episode itself did not.
3. **Idempotency**: `debrief_id = hash(episode_id)` (deterministic, one-to-one with the episode). If a
   debrief artifact already exists for `episode_id` (checked against the Episode note's `debrief_ref`
   field, ERE-02's store), the trigger is a no-op — including under redelivery, manual re-tick, or a
   crash-and-retry.
4. **No new durable queue table.** The unit of durable state is: the outbox consumer cursor (position),
   plus the fact that "closed, eligible, undebriefed" is *derivable* by joining the rebuildable episodes
   projection (ERE-02) against debrief-artifact existence — never held only in memory. This mirrors
   ERE's own tick-idempotency discipline (INV-ERE-F) rather than introducing a second source of truth
   for "what still needs a debrief."
5. **Output**: emits `debrief.trigger.created` (payload: `episode_id`, `debrief_id`, `scope`, bound-
   artifact count) — plumbing DEBRIEF-02 consumes. The episode projection + debrief existence is the
   truth; a lost event self-heals at the next reconciliation tick (INV-ERE-C's pattern, applied here).

## Concretely

```
$ python -m app.cli episode-debrief tick --json
{"triggered": ["debrief-ep-2026-07-07-morning"], "skipped_ineligible": 1, "skipped_already_debriefed": 0}
```

## Why This Matters

Without a durable, idempotent, scope-respecting trigger: either closure never produces a debrief
(the gap stays unwired beyond decay), or a redelivered event produces duplicate debriefs (noisy,
untrustworthy retros), or a trigger silently widens scope and hands DEBRIEF-02 material the episode
itself never fused — reopening the exact leak `GATE_CROSS_SCOPE_FUSION.md` closed, one layer downstream.

## Acceptance Criteria

- [ ] AC1: an eligible closed episode (bound-artifact count ≥ the floor) produces exactly one trigger; a
  sub-floor episode produces none. Verify: `tests/episode_debrief/test_trigger.py::test_eligible_closure_produces_exactly_one_trigger`
- [ ] AC2 (enforcement): redelivery of the same `episode.closed` event never produces a second trigger —
  asserted at the production consumer entrypoint, not just on the fold-by-key helper in isolation.
  Verify: `tests/episode_debrief/test_trigger.py::test_redelivered_closure_is_idempotent_at_consumer_entrypoint`
- [ ] AC3: the trigger's `scope` field is always identical to the source episode's `scope` — no widening,
  no narrowing, no default substitution. Verify: `tests/episode_debrief/test_trigger.py::test_trigger_scope_matches_episode_scope_no_widening`
- [ ] AC4: a still-open episode never triggers; only `time.closed: true` episodes are eligible at all.
  Verify: `tests/episode_debrief/test_trigger.py::test_open_episode_never_triggers`
- [ ] AC5 (enforcement): a crash/failure after the trigger is emitted but before DEBRIEF-02's synthesis
  completes leaves the episode's undebriefed state derivable and re-triggerable on the next reconciliation
  sweep — asserted end-to-end at the tick entrypoint (simulate partial failure, re-run, assert exactly one
  eventual trigger, never zero). Verify: `tests/episode_debrief/test_trigger.py::test_partial_failure_after_trigger_is_retried_not_lost`
- [ ] AC6: `EPISODE_DEBRIEF_MIN_ARTIFACT_COUNT` is a named, single-sourced constant documented as
  provisional. Verify: doc writeback at `docs/EPISODE_DEBRIEF/README.md :: Provisional thresholds`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episode_debrief/test_trigger.py
pytest -q -m "not pg"
```

Blocked until ERE-02 (#3177) / ERE-04 (#3179) / ERE-06 (#3181) merge — this task cannot run against a
real `episode.closed` event until then. Tests in the interim run against a synthetic closure payload
shaped to the ERE-06 schema; the merge-blocking dependency stands regardless (`agent:blocked` until then).

## Out of Scope

Eligibility beyond artifact-count and scope (no content-quality judgment, no "is this episode
interesting" heuristic); the synthesis itself (DEBRIEF-02); re-triggering a dismissed debrief (idempotency
alone governs re-trigger — a dismissed debrief still exists, so `debrief_id` collision still applies;
DEBRIEF-03 owns disposition, not this task); calendar/location stream nuances (ERE's concern, consumed
as-is via the episode projection).

## Restart / Durability Posture

The outbox consumer cursor is durable (per-consumer position, `app/heimdal/cursor_store.py` pattern —
survives restart). The "closed, eligible, undebriefed" set is *derived* from the rebuildable episodes
projection (ERE-02) plus debrief-artifact existence, never computed only in memory: a process restart
mid-tick loses nothing user-facing — the next tick recomputes the same set and re-emits exactly the
triggers still owed, with no duplicates (idempotent) and no silent loss.

## Related Docs

- `docs/EPISODE_RESOLUTION_ENGINE/EMIT_CLOSURE_AND_DERIVE_DECAY.md` (the `episode.closed` event this
  task consumes)
- `docs/EPISODE_RESOLUTION_ENGINE/GATE_CROSS_SCOPE_FUSION.md` (scope pass-through discipline)
- `docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md` (the projection this task reads)
- `app/heimdal/cursor_store.py` (durable per-consumer cursor precedent)
- `docs/SETTINGS_SPINE/README.md` (future home for the eligibility floor)

## Related GitHub Issues

One issue: `[Episode Debrief] trigger-debrief-on-closure: durable idempotent trigger from episode
closure`. Blocked until ERE-02 (#3177) / ERE-04 (#3179) / ERE-06 (#3181) merge.
