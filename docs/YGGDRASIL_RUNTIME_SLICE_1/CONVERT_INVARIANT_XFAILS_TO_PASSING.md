---
name: Convert Invariant Xfails to Passing
description: Verify the targeted xfails pass and the deliberately-left xfails remain explicit; lock the green suite as a gate
task_id: YRS1-07
source_anchor: docs/testing/invariant-tests.md :: Coverage map
parent_capability: Yggdrasil Runtime Vertical Slice 1
prerequisites: [YRS1-06]
depends_on: [CONTEXT_ENVELOPE_ASSEMBLY.md]
can_parallelize_with: []
---

# Convert Invariant Xfails to Passing

## Purpose

Confirm the runtime slice has honestly converted the targeted skeletons — no faked passes — and that
every invariant still requiring future runtime remains an explicit xfail. Lock the result as a
repeatable gate.

## What This Task Does

- Runs the full `pytest -q tests/invariants tests/evals` and confirms the eight targeted xfails now
  pass via real assertions (they auto-flip once the `yggdrasil_runtime` modules exist, because
  `require_future_runtime` imports the now-present module and runs the body).
- Confirms the deliberately-left invariants are still xfail (promotion, authority transition,
  execution, sync, parent aggregation, projection, observability, storage-write, propose-when-uncertain).
- Adds/adjusts any runtime conformance tests created by tasks 2–6 so the corpus anti-contamination
  scenarios are all exercised, and ensures no test relies on a now-removed xfail.
- Records the expected xfail/xpass split so a future regression (a skeleton silently going xfail
  again, or a "leave for later" invariant accidentally passing without its runtime) is caught.

## Concretely

```
pytest -q tests/invariants tests/evals -rxX
# Expected: the 8 targeted skeletons PASS; the documented residual set stays XFAIL; no XPASS surprises.
```

## Why This Matters

The danger in a slice like this is a *false green*: a skeleton that imports the module but never
asserts, or a "later" invariant that appears to pass because its guard isn't actually wired. This
task is the honesty gate — it proves the conversions are real and the residue is intentional.

## Acceptance Criteria

- [ ] The eight targeted invariants pass with real assertions (not xfail, not skipped).
  - Verify: `pytest -q tests/invariants tests/evals` — the named tests in the README "turns green"
    table all pass.
- [ ] The deliberately-left invariants remain xfail with their stated reasons.
  - Verify: `tests/invariants/test_invariant_residue.py::test_expected_xfail_set_is_unchanged`
    asserts the residual xfail slugs match the documented "left for later" list.
- [ ] All five anti-contamination fixture scenarios are exercised by a passing runtime test.
  - Verify: `pytest -q tests/evals tests/invariants/test_cross_scope_flow.py` — `tests/evals` covers
    the general/private/RPG scenarios, but the **work Alpha/Beta sibling-contamination** scenario is
    guarded by `tests/invariants/test_cross_scope_flow.py::test_retrieve_scope_prefilter` and
    `::test_similarity_is_not_permission` (a Beta doc highly similar to an Alpha query must not be
    admitted). `pytest -q tests/evals` alone would miss the Beta-leakage case.
- [ ] No targeted skeleton can silently revert to xfail without failing CI.
  - Verify: `tests/invariants/test_invariant_residue.py::test_targeted_invariants_are_runtime_passing`

## How to Verify (Pre-Merge)

- Local: `pytest -q tests/invariants tests/evals -rxX` and diff the xfail/xpass summary against the
  README tables.
- Confirm the residue test fails if any "later" invariant is removed from the expected set or any
  targeted invariant regresses.

## Out of Scope

- Making any "left for later" invariant pass (that is a future slice).
- Changing the invariant registry/matrix text — that writeback is YRS1-08.

## Related Docs

- `docs/testing/invariant-tests.md`, `tests/invariants/`, `tests/evals/`
- Boundaries: OEF (visibility only; never sets policy)

## Related GitHub Issues

One issue, `agent:ready` once YRS1-06 merges. Mostly verification + a residue-guard test.
