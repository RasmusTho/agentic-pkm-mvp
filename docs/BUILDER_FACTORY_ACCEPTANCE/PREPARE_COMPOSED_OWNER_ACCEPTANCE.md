---
name: Prepare composed owner acceptance
description: prepare whole owner-platform acceptance over existing workflow proofs
task_id: FCA-07
github_issue: 5406
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent"
parent_capability: Builder Factory Acceptance
prerequisites: [FCA-03, FCA-05, "implemented selected production read/action seams", "applicable design contract"]
depends_on: [COMPOSE_LLM_ASSISTED_OWNER_OVERVIEW.md, PRODUCE_OWNER_DECISION_AND_TRIAL_FACTS.md]
can_parallelize_with: []
---

State: Implemented pre-merge acceptance harness and receipt validator (#5406); live platform/owner acceptance remains incomplete and parent-owned.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Prepare composed owner acceptance

## Purpose

The owner prioritizes useful oversight and control; complete deterministic orchestration is not the goal of the first acceptance. Existing VM102, DevUI, FCP and DDO hubs each prove bounded parts, so their receipts must be composed rather than duplicated or treated as interchangeable.

## What This Task Does

Add a bounded acceptance harness/scenario specification that composes the admitted DevUI overview/Focus, LLM synthesis, exact action handoff, existing agent workflow, actual receipt readback, candidate tryability and owner trial/acceptance. Cover normal work, one real owner decision, technical wait, stale/contradictory evidence, model unavailable, ambiguous action start and owner-client disconnection. Exercise the selected workflow's existing pause/revocation/recovery proof; reuse #4170 if DDO is selected, without making DDO mandatory. Record predeclared questions and observable success criteria for the owner. The parent retains live VM102/second-repo pilot and explicit owner acceptance; this child delivers the reusable harness, receipt validator and procedure, not owner acceptance itself.

## Pickup, owned work and later validation

Pickup requires implemented FCA-03 synthesis, FCA-05 outcome/readback and the selected production
read/action seams with applicable design authority. A missing consumed producer or admission seam
is a real external implementation prerequisite; this child does not implement it through mocks.
#4697 owns the first inquiry seam. A full Issue delivery needs its separately accepted operation;
#4169/#4170 are dependencies only for DDO-specific initiation/recovery. #4982 design is required only
where the selected visual surface changes within its scope.

The child owns its composed scenario harness, validator and operator-readable
`builder_owner_platform_acceptance_plan.v1`. It may reuse FCA-06's procedure/fixtures when delivered,
but neither #5405's live second-repo pilot nor #4749/#5181 live evidence is a pickup prerequisite.
The plan must enumerate those pending receipts as incomplete, including real second-consumer
scope, exact VM102 identity/epoch, selected workflow effects, operator acknowledgement and explicit
owner trial/acceptance. #5399 retains every obligation; pre-merge fixture success cannot pass the
live plan. The read-only #4749 acknowledgement is distinct from effectful owner acceptance.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is prepare whole owner-platform acceptance over existing workflow proofs.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [x] The composed harness proves see -> explain -> exact approval -> existing workflow -> actual readback -> try/trial flow, and cannot render a model claim as delivery or acceptance.
  - Verify: `tests/builderops/test_builder_owner_acceptance.py::test_composed_owner_flow_preserves_real_effect_and_trial_evidence`
- [x] A missing required component/receipt, stale candidate, disconnected client or unknown effect yields an explicit incomplete result; no component-pass count or closed-issue count produces overall acceptance.
  - Verify: `tests/builderops/test_builder_owner_acceptance.py::test_incomplete_or_stale_evidence_cannot_pass_acceptance`
- [x] The parent pilot plan names exact identities, owner questions, LLM availability/failure cases, selected workflow mode, delegated authority, stop/recovery proof, residual limits and explicit owner validation.
  - Verify: runtime receipt: builder_owner_platform_acceptance_plan.v1

## How to Verify (Pre-Merge)

Run named harness tests plus the production source/action fixture suite. Validate source/receipt references and publish an operator-readable pilot procedure. At parent validation collect exact VM102 source/image/epoch, second consumer and owner observation; do not close this child as a claimed live factory deployment.

The executable composition is `tests/builderops/test_builder_owner_acceptance.py`, reusing
`tests/builderops/issue_delivery_production_harness.py`: real authenticated service/PostgreSQL
kernel, approval, task admission, protected destination/worker/executor, host outbox and independent
delivery readback. Only external GitHub, model, host isolation and worker transports are doubled.
The scenario binds typed deployment fixture evidence and FCA-09 confirmed outcome writes to the
same exact candidate and subject. These test writes never claim live human acceptance.

Run the named tests with both `DATABASE_URL` and `BUILDEROPS_DATABASE_URL` set to the same explicit
scratch database per `docs/development/DEV_WORKFLOW.md :: Pointing the PG lane at a scratch database`.
The shared fixture creates and drops only its unique schema. A skipped PG test is missing proof.
The source/action regression suite includes `test_issue_delivery_operation.py`,
`test_issue_delivery_readback.py`, `test_issue_delivery_effect_executor.py`,
`test_owner_fact_producers.py`, `test_devui_owner_synthesis.py`, and the typed runtime receipt tests.

`app.builderops.owner_acceptance.read_owner_acceptance` is a read-only source composition for
acceptance tooling, with authenticated delivery client, native task, independent GitHub reader,
authenticated current-owner-outcome reader, connection state and observation clock as explicit
inputs. It returns `builder_owner_acceptance_evidence.v1`, exact receipt references and a bounded
missing-evidence list. It checks source freshness (default 300 seconds), production delivery
readback, candidate/profile/epoch identity, outcome integrity and current trial/decision lineage,
then rereads owner selection and epoch to detect change during composition. Its result is
rebuildable and unpersisted; failures return `incomplete`. `evidence_complete` means only that
the supplied current source chain joined consistently. Hashes are not source authentication.
The caller must use authenticated source owners; arbitrary offline JSON is not trusted proof.
`platform_acceptance` remains `incomplete` in every result. There is no model call, command, provider
activation, execution permission or new storage in the validator.

## Operator procedure and live plan

[The operator plan](owner_platform_acceptance_plan.json) is the explicit
`builder_owner_platform_acceptance_plan.v1` artifact. Every missing live receipt has status
`incomplete`, a null receipt reference and the exact identity fields still required. It is a
procedure, not a signed receipt, deployment instruction or owner decision. Preserve it as the
pre-merge template; collect actual receipts on parent #5399 through their existing owners.

1. Read the plan's owner questions and observable success criteria before the trial. Identify the
   exact live candidate source/image/config, VM102 identity, component inventory, control-plane
   epoch and operator scope from current authenticated sources. Leave missing rows incomplete.
2. Use the currently admitted hub-only `deliver_ready_issue` operation. Follow Overview to Focus,
   inspect source-linked synthesis, and inspect the exact action preview. An explicit owner Start
   authorizes only the bound issue/workflow/effects; Hold starts nothing. Inquiry admission does not
   supply Issue-delivery permission. This child changes no visual surface or admission scope.
3. Read reservation, attempt, entry, terminal and protected host effect receipts, then independently
   inspect GitHub head/check/review/merge/closure evidence. A worker message or closed-issue count
   cannot substitute. Exercise technical wait, model failure, revocation, ambiguous start and
   client disconnection as described in the plan. On reconnect, observe the same operation key;
   never redispatch from reconstructed UI/model text. Existing revocation stops later effects and
   does not roll back an already committed effect.
4. Read the deployment owner's current readiness/candidate/profile binding. Under separate owner
   authority, the owner tries that candidate and submits the explicit FCA-09 trial and decision.
   Read both immutable receipts and current selection. Missing, corrected, stale, contradictory or
   rejected evidence cannot pass. Read-only #4749 acknowledgement is not this effectful acceptance.
5. Retain actual second-repository admission, effects, scope and independent authority as missing
   until #5405's live qualification is performed under its own authority. The harness never widens
   the current hub operation. Keep #5399 open until all platform and explicit owner criteria pass;
   fixture success, this child merge and baseline browser tests cannot close that live plan.

Semantic usefulness, live model access, actual host isolation, complete VM102 deployment and real
second-consumer operation remain unproved by these tests. The plan records those residual limits.

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

- #4749 and #5181 — retained parent runtime/read-only pilot gates, not child pickup edges
- #4697 — selected inquiry seam; separate admission for an Issue-delivery operation
- #4982 — applicable design scope only
- #5405 — reusable conformance procedure and separately retained real second-consumer acceptance

Execution context: `fresh_issue_agent`; issue-local helper budget: 1.
Capability recommendation: Tier 2/3 composed verification; fresh issue agent, configured Codex high reasoning; helper budget 1 for independent acceptance review.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
