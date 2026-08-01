---
name: Validate the Design Hub End to End
description: Prove production-path provider/refusal behavior, final cockpit artifacts, owner-doc promotion, and parent acceptance readiness.
task_id: CDH-06
github_issue: 4313
source_anchor: docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Capability acceptance
parent_capability: CKM Design-Agent Integration Hub
prerequisites: [CDH-01, CDH-02, CDH-03, CDH-04, CDH-05]
depends_on: [DEFINE_DESIGN_RUN_CONTRACTS.md, REGISTER_DESIGN_AGENT_ADAPTERS.md, GOVERN_DESIGN_RUN_LIFECYCLE.md, EXPOSE_DESIGN_RUN_CLI.md, PROJECT_DESIGN_RUNS_IN_COCKPIT.md]
can_parallelize_with: []
---

# Validate the Design Hub End to End

## Purpose

Close the gap between locally correct slices and one accepted capability on the real composition
path.

## What This Task Does

Adds the exact production-path acceptance matrix, reruns final deterministic/JS-off/print evidence,
and hands parent #4131 a complete conditional-acceptance ledger without changing supported owner
truth or closing the parent from the child.

## Concretely

- Exercise no adapters, unknown/unavailable adapter, policy denial, approval pending, malformed
  output, timeout, provider failure, one governed success per headless-registered adapter, and an
  exact zero-provider-call `interactive_subscription_only` refusal for every interactive-only
  registered adapter (see `README.md :: Capability acceptance` for why the partition is required by
  INV-CDH-5A and does not relax the refusal requirement).
- Exercise missing/stale/revoked/mismatched approval and missing/drifted Yggdrasil parity with zero
  provider calls.
- Prove one provider call at most, no fallback, exact admission/approval binding, causal receipt
  chain, validated handoff digest, and no direct authority crossing.
- Generate byte-identical final cockpit HTML from fixed inputs and attach a reviewed print artifact
  or deterministic print receipt.
- Keep CKM and Builder System owner docs pre-acceptance. Independent parent acceptance must first
  authorize the later docs-only promotion PR.

## Why This Matters

The capability is not delivered if its providers, governance, and projection only work in isolated
unit tests or if owner docs claim support before merged-main acceptance.

## Acceptance Criteria

- [ ] Production composition proves the complete success/refusal matrix, no fallback, and no
  ungoverned provider call.
  Verify: `tests/builderops/test_design_hub_acceptance.py::test_design_hub_production_matrix_is_fail_closed`
- [ ] Exact output proves validated handoff lineage and no direct Issue/PR/owner-doc/Product/HKA
  mutation.
  Verify: `tests/builderops/test_design_hub_acceptance.py::test_design_hub_outputs_remain_unaccepted_builder_material`
- [ ] Final cockpit HTML is deterministic, JS-off complete, print-complete, and incapable of
  execution across every terminal/refusal state.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_design_hub_projection_preserves_direction_b_authority`
- [ ] The named focused design-run, CKM, and model-inquiry regression set is complete at the PR
  head and every acceptance `Verify:` target resolves to a defined test. Head-bound pass evidence
  for that set is the `Unit tests (not pg)` CI check run on the PR head plus the evidence pack, not
  a literal recorded inside the test.
  Verify: `tests/builderops/test_design_hub_acceptance.py::test_focused_regression_set_is_complete_and_verify_targets_resolve`
- [ ] Local spec state and parent #4131 receive the exact final child, Yggdrasil, artifact,
  transition-debt, and conditional-acceptance handoff receipts without changing supported owner
  truth.
  Verify: `runtime receipt: ckm_design_hub.cdh06_completion_handoff.v1`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/test_design_hub_acceptance.py`
- `python3 -m pytest -q tests/builderops/test_design_run_contract.py tests/builderops/test_design_agent_adapters.py tests/builderops/test_design_run_governance.py tests/builderops/test_design_run_cli.py`
- `python3 -m pytest -q tests/builderops/ckm tests/builderops/test_model_inquiry_*.py`
- `ruff check app tests`
- `mypy app`
- `python3 scripts/docs_guard.py`

## Out of Scope

Closing parent #4131 from the child PR, owner-doc support promotion before conditional parent
acceptance, production deployment/promotion, Product/Runtime changes, automatic issue creation, and
future adoption observation.

## Related Docs

- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`

## Related GitHub Issues

Create one terminal child of #4131 after CDH-05 is delivered. Parent closure is a separate
independent acceptance action.
