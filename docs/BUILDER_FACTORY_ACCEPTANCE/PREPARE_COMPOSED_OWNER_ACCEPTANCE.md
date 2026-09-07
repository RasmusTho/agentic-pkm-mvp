---
name: Prepare composed owner acceptance
description: prepare whole owner-platform acceptance over existing workflow proofs
task_id: FCA-07
github_issue: 5406
source_anchor: docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent
parent_capability: Builder Factory Acceptance
prerequisites: [FCA-03, FCA-05, FCA-06]
depends_on: [COMPOSE_LLM_ASSISTED_OWNER_OVERVIEW.md, PRODUCE_OWNER_DECISION_AND_TRIAL_FACTS.md, QUALIFY_SECOND_CONSUMER_REPOSITORY.md]
can_parallelize_with: []
---

State: Target-state task specification; not implemented or runtime acceptance.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Prepare composed owner acceptance

## Purpose

The owner prioritizes useful oversight and control; complete deterministic orchestration is not the goal of the first acceptance. Existing VM102, DevUI, FCP and DDO hubs each prove bounded parts, so their receipts must be composed rather than duplicated or treated as interchangeable.

## What This Task Does

Add a bounded acceptance harness/scenario specification that composes the admitted DevUI overview/Focus, LLM synthesis, exact action handoff, existing agent workflow, actual receipt readback, candidate tryability and owner trial/acceptance. Cover normal work, one real owner decision, technical wait, stale/contradictory evidence, model unavailable, ambiguous action start and owner-client disconnection. Exercise the selected workflow's existing pause/revocation/recovery proof; reuse #4170 if DDO is selected, without making DDO mandatory. Record predeclared questions and observable success criteria for the owner. The parent retains live VM102/second-repo pilot and explicit owner acceptance; this child delivers the reusable harness, receipt validator and procedure, not owner acceptance itself.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is prepare whole owner-platform acceptance over existing workflow proofs.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] The composed harness proves see -> explain -> exact approval -> existing workflow -> actual readback -> try/trial flow, and cannot render a model claim as delivery or acceptance.
  - Verify: `tests/builderops/test_builder_owner_acceptance.py::test_composed_owner_flow_preserves_real_effect_and_trial_evidence`
- [ ] A missing required component/receipt, stale candidate, disconnected client or unknown effect yields an explicit incomplete result; no component-pass count or closed-issue count produces overall acceptance.
  - Verify: `tests/builderops/test_builder_owner_acceptance.py::test_incomplete_or_stale_evidence_cannot_pass_acceptance`
- [ ] The parent pilot plan names exact identities, owner questions, LLM availability/failure cases, selected workflow mode, delegated authority, stop/recovery proof, residual limits and explicit owner validation.
  - Verify: runtime receipt: builder_owner_platform_acceptance_plan.v1

## How to Verify (Pre-Merge)

Run named harness tests plus the production source/action fixture suite. Validate source/receipt references and publish an operator-readable pilot procedure. At parent validation collect exact VM102 source/image/epoch, second consumer and owner observation; do not close this child as a claimed live factory deployment.

## Out of Scope

No new workflow engine, global autonomy score, full DDO dependency, performance instrumentation project, actual deployment/merge/pilot without its own authorization or fabrication of human acceptance.

## Restart / Durability Posture

No new parallel authority store is introduced. Source facts and authorized operation receipts retain the durability of their existing owner. LLM text and views are derived; after restart regenerate them from current sources, show any unavailable history explicitly, and never redispatch an ambiguous action from the regenerated text. A previously accepted/tried fact must come from its durable source rather than memory of this view.

## Related Docs

- `docs/BUILDER_FACTORY_ACCEPTANCE/README.md`
- `docs/audits/BUILDER_SYSTEM_VISION_DELIVERY_2026-09-07.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`

## Related GitHub Issues

- #4749
- #4697
- #4982
- #5181

Execution context: `fresh_issue_agent`; issue-local helper budget: 1.
Capability recommendation: Tier 2/3 composed verification; fresh issue agent, configured Codex high reasoning; helper budget 1 for independent acceptance review.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
