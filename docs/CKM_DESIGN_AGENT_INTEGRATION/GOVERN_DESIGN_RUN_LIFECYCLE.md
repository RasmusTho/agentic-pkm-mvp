---
name: Govern Design-Run Lifecycle
description: Persist exact admission-bound design runs and append-only causal BuilderOps receipts.
task_id: CDH-03
github_issue: 4310
source_anchor: docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Cross-Task Invariants / Interaction Safety
parent_capability: CKM Design-Agent Integration Hub
prerequisites: [CDH-01, CDH-02]
depends_on: [DEFINE_DESIGN_RUN_CONTRACTS.md, REGISTER_DESIGN_AGENT_ADAPTERS.md]
can_parallelize_with: []
---

# Govern Design-Run Lifecycle

## Purpose

Ensure that no provider call occurs without exact admission/approval and that every observable run
state is derived from durable, tamper-evident BuilderOps evidence.

## What This Task Does

Adds one design-run semantic aggregate over existing BuilderOps storage/receipt primitives. It
loads `config/builderops/design_run_policy.json` as the repo-governed `DesignRunPolicyProfile`,
persists the request before execution, evaluates admission, validates optional local-operator
approval evidence, invokes exactly one design-agent domain adapter, and records every accepted
transition/refusal/failure/result as a prior-receipt-linked `BuilderOpsReceipt`.

## Concretely

- The bounded policy profile declares allowed deliverable kinds, maximum source/attachment counts,
  approval requirement, and visual Yggdrasil receipt requirement; its canonical hash is bound into
  admission.
- Policy returns `allow`, `deny`, or `approval_required`.
- The local BuilderOps CLI produces approval/revocation evidence using the authenticated OS
  principal and exact request/admission/policy hashes; caller-supplied actor identity is forbidden.
- Denied, pending, stale, or hash-mismatched admission invokes no adapter.
- Missing, stale, revoked, foreign, or mismatched approval invokes no adapter.
- Missing or token-drifted Yggdrasil evidence for a visual deliverable invokes no adapter.
- Visual admission reads `companion-ui/companion-app/colors_and_type.css` from the explicit repo
  root and binds the observed digest into admission; callers cannot supply or override current
  token parity.
- Accepted start is durable before provider execution.
- Each receipt predecessor has one deterministic next-receipt slot, and accepted start binds one
  unique execution actor; lease expiry cannot admit a second provider turn or sibling terminal
  receipt.
- Status is reconstructed from validated immutable artifacts and receipt ancestry.
- Returned handoff refs are accepted only from the strict
  `builderops.design-agent-turn.v1` response envelope. The exact returned UTF-8 artifact content,
  including whitespace, must match its digest without normalization, and the returned stable
  identity, sources, adapter, run, accepted-start receipt,
  limitations, and produced-at time must exactly match the predeclared binding. Plain prose,
  malformed output, digest drift, or foreign lineage records a typed failure, never success.
- Reuse the generic receipt envelope; add no receipt type, database, table, or PromotionIntent
  execution authority.

## Why This Matters

An editable status row or loosely worded approval could make an unapproved or different design run
look legitimate. Causal receipts preserve the exact decision and failure history.

## Acceptance Criteria

- [ ] Policy denial and approval-pending states produce zero adapter calls; exact matching approval
  is required when policy says `approval_required`.
  Verify: `tests/builderops/test_design_run_governance.py::test_policy_and_approval_gate_provider_execution`
- [ ] Policy evaluation loads only `config/builderops/design_run_policy.json`, binds its canonical
  hash, and fails closed on missing, malformed, or changed policy.
  Verify: `tests/builderops/test_design_run_governance.py::test_repo_governed_policy_is_the_only_admission_source`
- [ ] Approval is created/revoked only by the authenticated local operator path; stale, revoked,
  foreign, or mismatched evidence produces zero provider calls.
  Verify: `tests/builderops/test_design_run_governance.py::test_authenticated_approval_and_revocation_bind_exact_admission`
- [ ] A visual request with missing, stale, malformed, or token-drifted Yggdrasil evidence produces
  zero provider calls.
  Verify: `tests/builderops/test_design_run_governance.py::test_visual_admission_requires_current_yggdrasil_parity`
- [ ] Accepted start, transition, refusal, failure, and result receipts are append-only,
  idempotent, and linked to the previous receipt ID/hash.
  Verify: `tests/builderops/test_design_run_governance.py::test_design_run_transitions_are_append_only_and_receipted`
- [ ] Tampered, cyclic, missing, foreign-run, or hash-mismatched chains fail closed and never project
  partial success.
  Verify: `tests/builderops/test_design_run_governance.py::test_tampered_or_incomplete_receipt_chain_refuses_the_run`
- [ ] Design outputs have no direct Issue, PR, owner-doc, Product/Runtime, or human-knowledge
  mutation path; PromotionIntent remains a separate downstream proposal boundary.
  Verify: `tests/builderops/test_design_run_governance.py::test_design_outputs_have_no_direct_authority_or_writeback`
- [ ] A persistence failure before accepted-start durability produces no provider call; a terminal
  persistence failure never produces a success claim or fallback.
  Verify: `tests/builderops/test_design_run_governance.py::test_persistence_failures_remain_fail_closed`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/test_design_run_governance.py`
- `python3 -m pytest -q tests/builderops/test_model_inquiry_cli.py tests/builderops/test_model_inquiry_trace.py`
- `ruff check app tests`
- `mypy app`
- Run the state-machine/data/credential-durability convergence gate before expensive validation.

## Out of Scope

Generic policy platform, new control-plane cutover, new database/schema family, CLI presentation,
cockpit HTML, and automatic promotion.

## Restart / Durability Posture

Accepted start, admissions, approvals, transitions, refusals, failures, results, handoff refs, and
receipts survive restart in the selected BuilderOps store. In-flight provider execution is never
silently resumed or claimed successful after restart; recovery derives a typed incomplete/failed
state from durable evidence and requires an explicit new governed attempt when allowed.

## Related Docs

- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md`
- `docs/adr/ADR-0010-builderops-vault-authority-boundary.md`

## Related GitHub Issues

Create one high-risk child of #4131 after CDH-02 is terminal.
