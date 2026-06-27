---
name: Retrieval Prefilter Before Ranking
description: Scope/policy eligibility prefilter precedes ranking; cross-scope crossing only via typed CrossScopeFlow
task_id: YRS1-04
source_anchor: docs/architecture/retrieval-contract.md :: scope eligibility precedes ranking
parent_capability: Yggdrasil Runtime Vertical Slice 1
prerequisites: [YRS1-03]
depends_on: [DRI_SEGMENT_CARRIES_PROVENANCE.md]
can_parallelize_with: []
---

# Retrieval Prefilter Before Ranking

## Purpose

Establish the load-bearing retrieval rule: scope/policy eligibility is decided **before** ranking, so
similarity can never admit out-of-scope material, and cross-scope material crosses only through a
typed CrossScopeFlow — not because an embedding is close.

## What This Task Does

- Adds `yggdrasil_runtime/cross_scope.py` with
  `evaluate(source_scope, target_scope, operation, flow)` returning a decision with `.allowed: bool`
  and (when allowed) `.evidence_role_in_target`. With `flow=None` any cross-scope operation is denied.
- Adds `yggdrasil_runtime/retrieval.py` with `retrieve(query: str, active_scope_id: str)` that:
  1. loads candidates from the fixture corpus,
  2. **prefilters** to the eligible set (active scope, plus any scope reachable via an explicit flow)
     **before** ranking,
  3. ranks the eligible set by a trivial similarity helper,
  4. returns a result whose `.candidate_items` are all in-scope, each carrying `.metadata_bundle` and
     an `.admissibility_status`.
- Result asserts `scope_policy_prefiltered = true`.

## Concretely

```python
from yggdrasil_runtime import retrieval, cross_scope

r = retrieval.retrieve(query="telemetry state machine", active_scope_id="scope:work/project-alpha")
# Even though Project Beta is highly similar, admitted candidates are Alpha-only:
assert all(c.metadata_bundle.scope_id == "scope:work/project-alpha"
           for c in r.candidate_items if c.admissibility_status == "admitted")

cross_scope.evaluate("scope:general/programming", "scope:work/project-alpha", "cite", flow=None).allowed   # False
cross_scope.evaluate(
    "scope:general/programming", "scope:work/project-alpha", "cite",
    flow={"allowed_operations": ["retrieve", "surface", "cite"], "evidence_roles_allowed": ["background"]},
).evidence_role_in_target  # "background"
```

## Why This Matters

This is the invariant the whole architecture exists to protect: **similarity is not permission**. If
ranking ran first and scope filtered later, a Beta or private or RPG document could surface in a work
result because it embeds near the query. Prefilter-before-ranking, enforced at the `retrieve` call
site, is what makes that impossible.

## Acceptance Criteria

- [ ] All candidates in a result share the `active_scope_id` (out-of-scope excluded before ranking).
  - Verify: `tests/invariants/test_cross_scope_flow.py::test_retrieve_scope_prefilter` (xfail → passing)
- [ ] Highly-similar out-of-scope material is never `admitted`.
  - Verify: `tests/invariants/test_cross_scope_flow.py::test_similarity_is_not_permission` (xfail → passing)
- [ ] A cross-scope operation with `flow=None` is denied; with a valid flow allowing cite-as-background
  it is allowed and reports `evidence_role_in_target == "background"`.
  - Verify: `tests/invariants/test_cross_scope_flow.py::test_cross_scope_only_via_flow` and
    `tests/evals/test_general_knowledge_crosses_clean.py::test_general_knowledge_crosses_clean` (both xfail → passing)
- [ ] Private material does not appear in a work result without a governed flow.
  - Verify: `tests/evals/test_private_not_in_work_results.py::test_private_not_in_work_results` (xfail → passing)
- [ ] The prefilter is invoked from the `retrieve` production path before ranking (enforcement).
  - Verify: `tests/invariants/test_retrieval_runtime.py::test_prefilter_runs_before_ranking` asserts
    the eligible set is computed at the `retrieve` call site prior to scoring.

## How to Verify (Pre-Merge)

- Local: `pytest -q tests/invariants/test_cross_scope_flow.py tests/evals/test_private_not_in_work_results.py tests/evals/test_general_knowledge_crosses_clean.py`.
- Confirm `result.scope_policy_prefiltered is True` for every `retrieve` call.

## Out of Scope

- Full evidence-role monotonicity and RPG analogy handling (delivered by YRS1-05).
- The full policy engine, GOV receipts, AuthorityTransition runtime.
- Parent-scope aggregation (`yggdrasil_runtime.scope`) — left xfail.
- Embedding/reranking sophistication — a trivial similarity helper is sufficient.

## Related Docs

- `docs/architecture/retrieval-contract.md`, `docs/architecture/cross-scope-flow.md`
- Boundaries: GOV, RCA, WSP
- `schemas/retrieval-result.schema.json`

## Related GitHub Issues

One issue, `agent:ready` once YRS1-03 merges. Co-owns `retrieve()` with YRS1-05 — see README
Cross-Task Invariants (enrichment may narrow/annotate, never widen, the eligible set).
