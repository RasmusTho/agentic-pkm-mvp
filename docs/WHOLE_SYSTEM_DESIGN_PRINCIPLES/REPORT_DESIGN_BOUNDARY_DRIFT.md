---
name: Report Design Boundary Drift
description: Add a read-only doctor for principle mappings, owner references, effect classifications, and packet drift.
task_id: DSP-05
github_issue:
source_anchor: "docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/README.md :: Capability Acceptance"
parent_capability: Whole-System Design Principle Routing
prerequisites: [DSP-02, DSP-04]
depends_on: [DSP-02, DSP-04]
can_parallelize_with: []
---

# Report Design Boundary Drift

## Purpose

Give maintainers one typed, non-mutating view of routing and effect-boundary drift before it becomes
silent design divergence.

## What This Task Does

Add a bounded doctor/report command that checks stable IDs, exact owner references, packet
determinism, duplicate rule ownership, unclassified effects, and enforcement posture. Results are
redacted, canonical, and explicitly advisory evidence.

## Concretely

Tests run the production command over healthy and intentionally drifted fixture trees and assert
typed status, stable ordering, no writes, and nonzero refusal for invalid authority metadata.

## Why This Matters

Routing metadata is useful only while it remains aligned with the documents and enforcement it
points to.

## Acceptance Criteria

- [ ] The doctor reports healthy, stale-reference, duplicate-authority, packet-drift, and
  unclassified-effect states with stable typed output.
  - Verify: `tests/governance/test_design_boundary_doctor.py::test_doctor_reports_typed_boundary_drift`
- [ ] Running the doctor changes no repository, GitHub, BuilderOps, runtime, or owner state.
  - Verify: `tests/governance/test_design_boundary_doctor.py::test_doctor_is_read_only`
- [ ] The report names source evidence and uncertainty without claiming acceptance or repair.
  - Verify: `tests/governance/test_design_boundary_doctor.py::test_doctor_output_is_evidence_not_authority`

## How To Verify Pre-Merge

- `pytest -q tests/governance/test_design_boundary_doctor.py`
- `git diff --exit-code` after running the command on a clean fixture checkout.

## Out Of Scope

- Auto-repair, issue creation, background monitoring, a daemon, or runtime health mutation.

## Related Docs

- `docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/README.md`
- `docs/architecture/SBS_FITNESS_RULES.md`

## Related GitHub Issues

Shared parent epic: #5258.
