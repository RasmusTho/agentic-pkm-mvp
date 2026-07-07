---
name: Assign episode_ref to Artifacts
description: The assignment half — stamp episode_ref (pending) on artifacts that originated within an episode's bounds; the operational meaning of "assign situation context to information"
task_id: ERE-05
source_anchor: docs/research/EPISODE_RESOLUTION_ENGINE.md :: The three jobs (job 2)
parent_capability: Episode Resolution Engine
prerequisites: [ERE-02, ERE-03, ERE-04]
depends_on: [EPISODE_NOTE_STORE_AND_PROJECTION.md, THREAD_EPISODE_REF_INTO_METADATA_BUNDLE.md, TWO_STREAM_SEGMENTATION_CORE.md]
can_parallelize_with: [Emit Closure and Derive Decay, Respect Human Re-cut]
---

# Assign episode_ref to Artifacts

## Purpose

The knowledge-layer write that forced the Mimer placement (ADR-0054 ground 1): for every artifact that originated within a proposed episode's bounds — vault note, chat session, Heimdal observation's downstream candidate — upgrade its bundle `episode_ref` from `unbound` to `pending [ep-...]`. This is what makes episodes *useful*: information gains situation context.

## What This Task Does

1. **Assignment rule**: an artifact whose bundle `created_at`/provenance timestamps fall within a proposed/accepted episode's `time.start..end` **and** whose signal appears in (or correlates with) the episode's `derived_from` receives `episode_ref: pending [episode_id]` in its metadata bundle. Multiple overlapping (nested) episodes → multiple refs, per the doctrine's "zero or more".
2. **Confidence floor, HEIM-6-honest**: assignment by direct provenance (the artifact's signal is in `derived_from`) is binding-strength; assignment by mere time-overlap is proposed only when scope matches — never a confident claim from a weak correlation. The per-axis confidence from the signal contract (ERE-01) travels into the assignment record.
3. **Write discipline**: bundle mutation on vault-serialized artifacts routes through the guarded write seam (same two-class rule as ERE-02: health-gate asserted, no human confirm — `pending` is proposal class); DB-side bundle rows update transactionally with an assignment provenance ref (which episode, which rule, when).
4. **Assignment runs in the tick** after segmentation, over the same delta window; late-arriving artifacts (indexed after their episode closed) still receive assignment on their ingest tick — late signals attach as bindings, never re-cut bounds (RQ-E3's conservative half; bound-changing fusion of late evidence stays out of scope).
5. **Un-assignment**: when a human re-cut (ERE-07) invalidates a binding, assignment corrects `episode_ref` on the affected bundles on the next tick — corrections are ordinary bundle updates with provenance, never silent.

## Concretely

```
$ python -m app.cli episodes tick --json
{"assigned": {"pending": 9}, "corrected": 0}
$ python -m app.cli episodes show ep-... --json   # lists bound artifacts with binding basis
```

## Why This Matters

Assignment is the operational meaning of "tilldela session-kontext till information" — and it is the half Heimdal is forbidden to do (HEIM-2). If bindings are stamped confidently from weak overlap, wrong context poisons retrieval; if they never upgrade from `unbound`, the whole capability is inert; if they bypass the guarded seam, the multi-writer vault rules (ADR-0055) break.

## Acceptance Criteria

- [ ] AC1: fixture artifacts inside a proposed episode's bounds receive `episode_ref: pending [ep-...]`; artifacts outside receive none. Verify: `tests/episodes/test_assignment.py::test_in_bounds_artifacts_get_pending_binding`
- [ ] AC2: a `derived_from`-anchored artifact binds even with imperfect time overlap; a time-overlap-only artifact in a *different scope* does not bind (scope discipline; ERE-08 pins the full posture). Verify: `tests/episodes/test_assignment.py::test_binding_basis_provenance_beats_overlap_and_respects_scope`
- [ ] AC3: nested/overlapping episodes yield multiple refs, schema-valid. Verify: `tests/episodes/test_assignment.py::test_overlapping_episodes_yield_multiple_refs`
- [ ] AC4 (enforcement): the assignment write path asserts the guard at the production seam and never emits an AuthorityReceipt for a `pending` binding. Verify: `tests/episodes/test_assignment.py::test_assignment_write_guarded_proposal_class`
- [ ] AC5 (enforcement): assigned bindings survive derivation on the production path — the ERE-03 invariant probe extended with an end-to-end case: assign → chunk/derive → binding present on the derived bundle. Verify: `tests/invariants/test_episode_binding.py::test_observation_episode_binding_survives` (end-to-end case added)
- [ ] AC6: assignment is idempotent per (artifact, episode) — re-ticks don't duplicate refs; corrections carry provenance. Verify: `tests/episodes/test_assignment.py::test_assignment_idempotent_and_corrections_provenanced`
- [ ] AC7: late-arriving artifacts bind to already-closed episodes without altering episode bounds. Verify: `tests/episodes/test_assignment.py::test_late_artifact_binds_without_recutting_bounds`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_assignment.py tests/invariants/test_episode_binding.py
pytest -q -m "not pg"          # full suite: bundle hot path
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat
```

## Out of Scope

Retrieval/salience consumption of bindings (ERE-06); `pending → accepted` lifecycle (rides on episode acceptance, ERE-07); cross-scope binding beyond deny-by-default (ERE-08); re-deriving Heimdal attribution (Heimdal owns attribution — consumed, never recomputed).

## Related Docs

- `docs/architecture/semantic-dimensions.md` §episode_ref (pending-is-not-authority; never upgrades evidence_role)
- [ADR-0054](../adr/ADR-0054-episode-resolution-engine-is-a-mimer-organ.md) ground 1 (assignment is a Mimer write)
- `docs/architecture/metadata-bundle.md`; `docs/testing/invariant-tests.md` §observation_episode_binding_survives

## Related GitHub Issues

One issue: `[Episode Resolution Engine] episode-ref-assignment: stamp pending bindings on in-bounds artifacts`. Blocked until ERE-02/03/04 merge.
