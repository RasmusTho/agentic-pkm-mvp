---
name: Define Design-Run Contracts
description: Define strict provider-neutral design descriptors, briefs, requests, admissions, statuses, results, handoffs, and canonical hashes.
task_id: CDH-01
source_anchor: docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Reuse boundary and external prerequisite
parent_capability: CKM Design-Agent Integration Hub
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Design-Run Contracts

## Purpose

Create one exact vocabulary shared by CKM, BuilderOps governance, adapters, CLI, and projections
before any of those surfaces are implemented.

## What This Task Does

Adds immutable provider-neutral domain contracts for `DesignAgentDescriptor`,
`CuratedDesignBrief`, `YggdrasilGateReceipt`, `DesignRunPolicyProfile`, `DesignRunRequest`,
`DesignRunAdmission`, `DesignRunApprovalEvidence`, `DesignRunStatus`, `DesignRunResult`, typed
handoff refs, and typed refusal detail. It reuses canonical JSON/hash mechanics without importing
inquiry roles or runner semantics.

`DesignAgentHandoffOutput` is the strict `builderops.design-agent-turn.v1` provider-return
envelope. It carries transient artifact content only so the lifecycle can verify the returned
digest before discarding the content and persisting the non-authoritative `DesignHandoffRef`.
Unstructured prose is not a handoff.

## Concretely

- Require explicit sorted source refs and digest-bound attachment refs.
- Bind brief, request, adapter, policy, admission, and approval identities with canonical hashes.
- Let visual admission bind the trusted repo-token digest observed by the lifecycle producer while
  non-visual admission requires no token observation; callers do not supply that observation.
- Require current exact Yggdrasil system/token parity evidence for typed visual deliverables while
  keeping typed non-visual deliverables explicitly exempt.
- Reject ambient/unbounded context markers, unknown fields, malformed refs, duplicate identities,
  invalid state transitions, and raw secret/path fields.
- Define distinct unknown, unavailable, denied, approval-pending, malformed, timed-out, failed,
  running, and succeeded states.

## Why This Matters

Without a strict neutral contract, CKM can accidentally absorb provider commands or BuilderOps
authority, and later slices cannot prove that an approval applies to the exact request executed.

## Acceptance Criteria

- [ ] Briefs bind only explicit source and attachment refs, projection identity, constraints, and
  requested deliverable and produce a deterministic content hash.
  Verify: `tests/builderops/test_design_run_contract.py::test_curated_brief_is_bounded_provenanced_and_deterministic`
- [ ] Request/admission/approval hashes bind one adapter and the exact same brief and reject scope
  expansion, staleness, unknown fields, and mismatches.
  Verify: `tests/builderops/test_design_run_contract.py::test_admission_and_approval_bind_the_exact_request`
- [ ] Visual deliverables require a complete exact Yggdrasil receipt whose live/repo token hashes
  match the current repo token source; non-visual deliverables are explicitly typed and exempt.
  Verify: `tests/builderops/test_design_run_contract.py::test_visual_deliverables_bind_current_yggdrasil_gate_receipt`
- [ ] Status, result, handoff, and refusal contracts use closed vocabularies and reject secret,
  command, raw stderr, and host-local path fields.
  Verify: `tests/builderops/test_design_run_contract.py::test_result_and_refusal_contracts_are_closed_and_secret_safe`
- [ ] Existing model-inquiry request/response contracts remain unchanged and are not imported as
  design-run semantics.
  Verify: `tests/builderops/test_design_run_contract.py::test_design_contract_reuses_hashing_without_inheriting_inquiry_roles`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/test_design_run_contract.py`
- `python3 -m pytest -q tests/builderops/test_model_inquiry_contract.py`
- `ruff check app tests`
- `mypy app`

## Out of Scope

Adapters, provider execution, persistence, policy evaluation, CLI, HTML, and owner-doc promotion.

## Related Docs

- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/adr/ADR-0064-model-access-substrate.md`

## Related GitHub Issues

Create one bounded child of #4131 after this specification merges.
