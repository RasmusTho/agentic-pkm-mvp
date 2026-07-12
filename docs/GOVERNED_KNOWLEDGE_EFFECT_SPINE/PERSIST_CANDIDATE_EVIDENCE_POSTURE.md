---
name: Persist Candidate Evidence Posture
description: Preserve evidence_role across candidate persistence and replay.
task_id: GKES-03
source_anchor: docs/architecture/semantic-dimensions.md :: evidence_role
parent_capability: Governed Knowledge Effect Spine
prerequisites: [GKES-01, GKES-02]
depends_on: [DEFINE_EFFECT_SPINE_CONTRACTS.md, MAKE_HEIMDAL_INTAKE_DURABLE.md]
can_parallelize_with: []
---

# Persist Candidate Evidence Posture

## Purpose

Keep Heimdal output explicitly evidence/candidate material after persistence.

## What This Task Does

Persist and validate `evidence_role` in candidate frontmatter/schema, migrate old candidates through an observable compatibility path, and preserve the role on read/replay.

## Concretely

Build on existing frontmatter/schema validation. No inference may silently upgrade an old candidate to authoritative knowledge.

## Why This Matters

The cheap metadata repair prevents expensive later ambiguity at the Heimdal–Mimer seam.

## Acceptance Criteria

- [ ] Persisted candidates round-trip an allowed evidence role. Verify: `tests/heimdal/test_projector.py::test_persisted_candidate_round_trips_evidence_role`.
- [ ] Legacy candidates without the field take one documented, observable compatibility path. Verify: `tests/heimdal/test_projector.py::test_legacy_candidate_missing_evidence_role_is_observable`.
- [ ] Invalid or authority-bearing roles are rejected at the production persistence call site. Verify: `tests/heimdal/test_projector.py::test_projector_rejects_invalid_candidate_evidence_role`.

## How to Verify (Pre-Merge)

- `pytest -q tests/heimdal/test_projector.py tests/heimdal/test_content_quarantine.py`

## Out of Scope

Retrieval permission, HKA promotion, or canonical identity resolution.

## Related Docs

- `docs/architecture/semantic-dimensions.md`
- `docs/boundaries/SIP.md`

## Related GitHub Issues

Blocked by GKES-01 and GKES-02; unblocks GKES-04.
