---
name: Gap and Missing Evidence Detection
description: Specific, cited gap findings — starved dimensions, uncovered boundaries, and claim-exceeds-evidence tensions
task_id: CKM-08
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.8 FR-6 / FR-7
parent_capability: Capability Knowledge Model
prerequisites: [CKM-07]
depends_on: [MATURITY_ASSESSMENT_ENGINE.md]
can_parallelize_with: []
---

# Gap and Missing Evidence Detection

## Purpose

Convert assessments into the actionable question the owner actually asks: *where are the largest gaps, and which claims outrun their evidence?* Findings are specific and cited — never a vague "coverage is low."

## What This Task Does

Implements `app/builderops/ckm/gaps.py` producing `ckm_finding` rows, each `(kind, capability, dimension, statement, citations[])`, deterministic over the current assessment + edge state:

- **Starved-dimension gaps** (`kind=gap`): a dimension below a configurable floor while sibling dimensions are healthy — e.g. "`orientation`: test completeness 0.2 vs functional 0.8; 1 test edge (cite) against 14 source edges."
- **Uncovered-boundary gaps** (`kind=gap`): a seeded SBS boundary whose mapped capabilities have zero `source`/`pull_request` evidence — the "designed but unbuilt" signal.
- **Claim-exceeds-evidence tensions** (`kind=missing_evidence`): a doc/spec artifact whose `State:` header (captured at ingest) claims delivered/live/baseline for a capability whose functional or test dimension is below the floor — citing both the claiming artifact and the missing evidence class. This is FR-7's "tension surfaced, not averaged."
- **A dimension implies a finding only if it was measured** (fixed 2026-07-29, #4257). Both detectors above gate on `assessment.dimension_status[dimension] == "measured"` before treating a low score as a finding: `starved_dimension` skips a target dimension whose status is `missing`/`unassessed`/`unsupported`, and only counts a sibling as "healthy" if that sibling is itself `measured`; `claim_exceeds_evidence` skips a claim comparison against an unmeasured `functional_completeness`/`test_completeness`. **Chosen treatment: exclusion, not a distinct finding kind.** An unmeasured dimension is stored as `0.0` purely because nothing populated it, so treating that placeholder as a real weak score is what produced 22 of 50 false findings in the 2026-07-28 run (`docs/adr/ADR-0057-capability-knowledge-model-kvasir.md :: Measured state, 2026-07-28`). A new `kind` (e.g. `instrument_gap`) would need its own store validation, CLI summary line, and consuming-surface handling for a fact that is already durably recorded and queryable on the assessment row itself (`dimension_status`, `app/builderops/ckm/models.py:342`) — the boring fix is to stop double-counting it as a finding, not to add a second finding taxonomy for the same fact. The state stays fully discoverable: read the capability's latest assessment's `dimension_status` for any dimension not currently producing a finding.
- Findings are regenerated (delete + recreate) per run against the newest assessments — they are derived views of derived views, the most disposable layer (INV-CKM-4).
- CLI: `python -m app.builderops ckm gaps`.

## Concretely

```bash
python -m app.builderops ckm gaps
# → "17 findings: 9 starved-dimension, 3 uncovered-boundary, 5 claim-exceeds-evidence"
# e.g. "missing_evidence: docs/X.md claims 'delivered' for <cap> but test completeness 0.1 (0 test edges); missing: test"
```

## Why This Matters

FR-6/FR-7 are the vision's payoff — this is the layer that answers "which architectural areas are underdeveloped" and catches docs asserting more than the code proves (the false-green class the repo has been burned by before).

## Acceptance Criteria

- [ ] Every finding names capability + dimension + a concrete statement and cites ≥1 evidence edge or artifact (no citation-less findings can be written), asserted via the store write path (enforcement AC).
  - Verify: `tests/builderops/ckm/test_gap_detection.py::test_findings_name_capability_dimension_and_citation`
- [ ] The three detector families each fire correctly on a synthetic fixture graph designed to trigger exactly them.
  - Verify: `tests/builderops/ckm/test_gap_detection.py::test_three_detector_families_on_fixture`
- [ ] Claim-exceeds-evidence pairs the claiming artifact with the missing evidence class in one finding.
  - Verify: `tests/builderops/ckm/test_gap_detection.py::test_tension_cites_claim_and_missing_class`
- [ ] Findings regenerate deterministically: two runs over unchanged state yield identical finding sets.
  - Verify: `tests/builderops/ckm/test_gap_detection.py::test_regeneration_deterministic`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_gap_detection.py -q`
- Live run; verify at least one known-true gap appears (e.g. a Planned-maturity contract capability shows an uncovered/starved finding) and no finding is absurd on its face.
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- Drift detection FR-8 (deferred per OD-K1). Auto-filing issues from findings (INV-CKM-2; human decision).
- Severity ranking/prioritization policy beyond the floor thresholds (owner iterates via config).

## Related Docs

- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: FR-6/FR-7`, `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-07. TCD hint: Sonnet / medium (three bounded detectors over a tested substrate).
