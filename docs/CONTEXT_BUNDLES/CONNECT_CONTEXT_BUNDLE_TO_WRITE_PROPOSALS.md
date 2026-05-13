---
name: Connect Context Bundle to Write Proposals
description: Specify how governed write proposals retain bundle linkage without bypassing write guards.
task_id: CONTEXT-BUNDLES-05
source_anchor: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to writeback and write guards
parent_capability: Context Bundles
prerequisites: [CONTEXT-BUNDLES-01, CONTEXT-BUNDLES-02]
depends_on: [DEFINE_CONTEXT_BUNDLE_SCHEMA.md, EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md]
can_parallelize_with: []
---

# CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS

## Purpose

Specify how a context bundle supports governed write proposals while preserving the contract rule
that bundle evidence does not bypass write guards or silently become write authority.

## What This Task Does

This task defines the implementation contract for linking bundles to proposals, staging, and review
surfaces. It specifies:

- what bundle or bundle reference a proposal carries,
- how the proposal records its evidence basis,
- and how proposal, stage, apply, and log remain distinct.

## Concretely

A later implementation should be able to produce a write proposal that includes:

- a stable bundle identifier or embedded bundle reference,
- the affected artifact or artifacts,
- explicit proposal basis tied to bundle evidence,
- and authority posture showing that the bundle may propose without itself authorizing apply.

## Why This Matters

The contract is explicit that a context bundle may support a proposal but must not bypass trust
semantics or APPLY rules. This task is the point where that boundary becomes implementation-ready.
If it is vague, evidence-bearing proposals can silently turn into hidden write authorization.

## Acceptance Criteria

- [ ] The proposal contract requires a bundle or stable bundle reference to travel with governed
  write proposals. Verify: `tests/writeback/test_context_bundle_write_authority.py::test_context_bundle_may_propose_without_write`
- [ ] Proposal linkage preserves affected artifacts, proposal basis, and authority posture
  separately. Verify: `tests/writeback/test_context_bundle_write_authority.py::test_write_proposal_preserves_bundle_basis_and_authority_flags`
- [ ] The implementation spec distinguishes propose, stage, apply, and log rather than collapsing
  them into one mutation step. Verify: `tests/writeback/test_context_bundle_write_authority.py::test_context_bundle_write_flow_distinguishes_propose_stage_apply_and_log`
- [ ] The proposal contract explicitly forbids bundle linkage from bypassing write guards or
  upgrading `may_propose` into `may_write`. Verify: `tests/writeback/test_context_bundle_write_authority.py::test_context_bundle_cannot_bypass_write_guards`

## How to Verify (Pre-Merge)

- Add or update the writeback-facing tests named in the acceptance criteria.
- Confirm the proposal payload or typed model contains bundle linkage plus explicit authority state.
- Confirm the proposal path still requires the normal governed write boundary before any apply step.

## Out of Scope

- Executing write proposals.
- Receipt persistence after apply.
- Memory promotion from write outcomes.
- Defining UI rendering for proposal review.

## Related Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`

## Related GitHub Issues

Not created in this PR. When filed later, use this task spec as the child implementation issue
contract for bundle-to-proposal linkage.
