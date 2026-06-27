---
name: RetrievalResult Candidate Semantics
description: Full RetrievalResult contract — admissibility states, non-upgrading evidence role, content-free denied list
task_id: YRS1-05
source_anchor: docs/architecture/retrieval-contract.md :: candidate semantics
parent_capability: Yggdrasil Runtime Vertical Slice 1
prerequisites: [YRS1-04]
depends_on: [RETRIEVAL_PREFILTER_BEFORE_RANKING.md]
can_parallelize_with: []
---

# RetrievalResult Candidate Semantics

## Purpose

Enrich the `retrieve()` output from YRS1-04 into the full RetrievalResult contract: candidate
admissibility semantics, an evidence role that can be downgraded but never upgraded, and a
content-free denied/escalated list — so retrieval produces *candidate evidence*, not truth.

## What This Task Does

- Extends `yggdrasil_runtime/retrieval.py` so each candidate carries `admissibility_status` from the
  surfaceable set (`candidate`/`admitted`/`redacted`/`requires_confirmation`) and an
  `evidence_role_in_context` that is ordinally `<=` its intrinsic `metadata_bundle.evidence_role`
  (never upgraded toward `evidence`).
- Adds the `denied_or_escalated_candidates` content-free list (closed `scope_denial` shape: `reason`,
  `denial_class`, `escalation_recommended` — never `scope_id`, `object_id`, content, or provenance).
- RPG/worldbuilding material, if it appears at all in a work scope, appears only as
  `analogy`/`inspiration` in context — never as `evidence`.
- Candidate identity comes only from the embedded `metadata_bundle` (single source of truth; no
  sibling `object_id`).
- The emitted result validates against `schemas/retrieval-result.schema.json`.

## Concretely

```python
order = ["non_evidence", "inspiration", "analogy", "reference", "background", "evidence"]
r = retrieval.retrieve(query="state machine authority rules", active_scope_id="scope:work/project-alpha")
for c in r.candidate_items:
    assert order.index(c.evidence_role_in_context) <= order.index(c.metadata_bundle.evidence_role)
# RPG fiction never crosses as real-world evidence:
for c in r.candidate_items:
    assert c.metadata_bundle.scope_id != "scope:rpg/worldbuilding" or \
           c.evidence_role_in_context in {"analogy", "inspiration"}
```

## Why This Matters

A top-ranked candidate is not evidence and not authority (`RCA.md`). Upgrading an analogy or a
background note into `evidence` because it ranked highly is precisely how fiction gets mistaken for a
real software spec, or a private note becomes a work citation. The monotonicity rule and the
content-free denied list are what keep retrieval honest and non-leaking.

## Acceptance Criteria

- [ ] For every candidate, `evidence_role_in_context` is ordinally `<=` the intrinsic
  `metadata_bundle.evidence_role`.
  - Verify: `tests/invariants/test_retrieval_result.py::test_retrieval_full_evidence_monotonicity_runtime`
    (kept green — auto-enabled when YRS1-04 created `retrieval.py`; this task adds the explicit
    downgrade logic and must not regress it)
- [ ] RPG/worldbuilding material is never admitted as `evidence` in a work scope.
  - Verify: `tests/evals/test_rpg_not_confused_with_software.py::test_rpg_not_confused_with_software`
    (kept green — auto-enabled at YRS1-04; this task hardens the analogy/inspiration handling without
    regressing it)
- [ ] `denied_or_escalated_candidates` entries are content-free (`scope_denial` shape only).
  - Verify: `tests/invariants/test_retrieval_result.py::test_retrieval_denied_candidates_are_content_free` (kept green) +
    `tests/invariants/test_retrieval_runtime.py::test_runtime_denied_list_is_content_free` over a real `retrieve` call.
- [ ] `retrieval_candidate_identity_single_source` stays green; the runtime candidate exposes identity
  only via its bundle.
  - Verify: `tests/invariants/test_retrieval_result.py::test_retrieval_candidate_identity_single_source`
- [ ] The emitted RetrievalResult validates against `schemas/retrieval-result.schema.json`.
  - Verify: `tests/invariants/test_retrieval_runtime.py::test_retrieval_result_validates_against_schema`

## How to Verify (Pre-Merge)

- Local: `pytest -q tests/invariants/test_retrieval_result.py tests/evals/test_rpg_not_confused_with_software.py tests/invariants/test_retrieval_runtime.py`.
- Confirm YRS1-04's tests stay green (no re-admission of prefilter-excluded candidates).

## Out of Scope

- `denied`/`escalated` full governance routing and audit refs beyond the content-free shape.
- ContextEnvelope assembly (YRS1-06).
- Reranking sophistication.

## Restart / Durability Posture

RetrievalResult is computed per call over the in-memory corpus; nothing persists. Not a user-facing
durable surface.

## Related Docs

- `docs/architecture/retrieval-contract.md`, `docs/architecture/semantic-dimensions.md`
- `schemas/retrieval-result.schema.json`, `schemas/_defs.schema.json`
- Boundaries: RCA, SIP, GOV

## Related GitHub Issues

One issue, `agent:ready` once YRS1-04 merges. Co-owns `retrieve()` with YRS1-04 — must not widen the
eligible set (README Cross-Task Invariants).
