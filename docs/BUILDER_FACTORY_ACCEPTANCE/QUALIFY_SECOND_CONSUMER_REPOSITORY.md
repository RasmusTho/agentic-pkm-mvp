---
name: Qualify a second consumer repository
description: qualify Builder against an explicitly addressed second repo
task_id: FCA-06
github_issue: 5405
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent"
parent_capability: Builder Factory Acceptance
prerequisites: [FCA-04, FCA-08, ARO-09, "implemented selected production admission/read/launch seams"]
depends_on: [ISOLATE_BUILDER_PACKAGE_BOOT.md]
can_parallelize_with: []
---

State: Implemented pre-merge conformance harness and incomplete pilot-plan validator; live second-consumer acceptance remains parent-owned.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Qualify a second consumer repository

## Purpose

RepoRef and delivery manifests already support multiple repositories with no policy borrowing. There is no inspected acceptance proving that the running Builder can govern an independent consumer without implicit Yggdrasil/Product or laptop-runtime dependencies.

## What This Task Does

Create a bounded conformance/pilot harness over existing manifest routing, DevUI read composition and the admitted agent/workflow launcher. Exercise two explicitly different repo identities with separate policies/credentials and a third unauthorized identity. The second consumer must have its own source/skill delivery contract and must not require a Product Runtime DB/vault/service or hub-specific default. A local fixture establishes pre-merge behavior; a separately authorized low-risk live second-consumer pilot belongs to parent validation. The pilot may use existing governed agent workflows and does not require full DDO. Select the live repo/branch/allowed effects explicitly in its admission receipt; do not create a repo or grant credentials in this child.

## Pickup, owned work and later validation

Pickup requires accepted FCA-08/ARO-09 contracts, delivered independent package boot, and the
selected operation's actual production admission/read/launch seams. The first inquiry adapter
belongs to #4697; an Issue-delivery workflow has separate admission and cannot borrow inquiry
permissions. If a consumed seam is absent, preserve that exact external implementation blocker.

This child owns the composed conformance fixtures/tests, receipt validator and self-contained
`builder_second_consumer_pilot_plan.v1` procedure. Those deliverables are not pickup prerequisites.
No live #5181 deployment, #3793 authority cutover, selected real repository/credentials or #4749
owner pilot is required to build them. Parent #5399 must later qualify independent authority and
VM102, explicitly admit the real consumer/repo/branch/effects and collect actual result/readback.
Neither a fixture nor the plan receipt satisfies those live obligations.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is qualify Builder against an explicitly addressed second repo.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] The composed production admission/read/launch path resolves the addressed consumer policy and never borrows hub defaults, references or credentials; a third unconfigured repo is refused.
  - Verify: `tests/builderops/test_standalone_consumer_conformance.py::test_composed_path_is_repo_scoped_without_hub_fallback`
- [ ] Consumer boot/read/agent handoff works in the test harness with Product services absent and all host-local provider dependencies explicitly declared; disconnecting an owner UI does not lose the admitted workflow identity.
  - Verify: `tests/builderops/test_standalone_consumer_conformance.py::test_consumer_has_no_product_or_owner_client_runtime_dependency`
- [ ] A self-contained live-pilot procedure enumerates repo/branch/effects, credential boundaries, expected source/run/result receipt and stop/readback behavior, reserving external authorization and actual evidence for the parent.
  - Verify: runtime receipt: builder_second_consumer_pilot_plan.v1

## How to Verify (Pre-Merge)

Run the composed conformance tests plus existing delivery-manifest routing tests and affected code baseline. Publish the fixture/procedure and exact entrypoints. Parent validation records the real repo/commit and authorized effect readback; fixture success alone is not live acceptance.

The delivered `tests/builderops/test_standalone_consumer_conformance.py` composes authenticated
`issue_delivery_preview`/`issue_delivery_start`, `admit_issue_delivery_task`, native TaskRecord
and DevUI Overview/Focus reads, `dispatch_issue_sessions`, `IssueDeliveryOperationAdapter`, the
content-only launcher and protected host executor. The shared production harness uses real
PostgreSQL, credential registry and temporary Git roots. External GitHub/model/OS/secret-provider
I/O is substituted; production admission, source-pair, policy, credential and launch verdicts are
not replaced. Hub v1 and Bifrost v2 stay distinct; missing/borrowed policy, credential, workflow
reference and an unavailable source refuse before entry. A clean interpreter boots without
Product configuration; closing the approving client preserves the server workflow identity.
Host dependencies are explicitly listed in the plan below, not assumed to exist on a laptop.

Run the two exact AC targets and the module's refusal/validator cases with the explicit disposable
PostgreSQL configuration described in `docs/development/DEV_WORKFLOW.md`. Never record raw DSNs.
The tests prove finite repository conformance, not installation of a real host transport, live
candidate preparation or a second-consumer delivery. Existing production routing and affected
admission/read/launch regression suites remain required.
The existing `pr-index-pg-contracts` CI job selects the validator/test paths and executes this
module's PostgreSQL cases. Its enrollment is guarded by
`tests/ops/test_ci_workflow.py::test_pr_index_pg_contracts_run_exact_acceptance_surface`;
the unchanged 30-minute job budget and a not-pg pass do not replace executed PG evidence.

## Pilot procedure and receipt validator

The self-contained [pilot plan](second_consumer_pilot_plan.json) is the
`builder_second_consumer_pilot_plan.v1` receipt. It enumerates the ordered procedure, the finite
repository/path/effect envelope, host dependencies, separate credential/policy boundaries and
expected source/run/result/readback and human outcome receipts. No real branch, candidate,
operation, credential or human decision is selected. All live evidence is explicitly absent.

```sh
python3 -m app.builderops.second_consumer \
  docs/BUILDER_FACTORY_ACCEPTANCE/second_consumer_pilot_plan.json
```

`validate_pilot_plan` is an active, read-only preparation validator for operators and conformance
tests. It accepts the closed plan shape, returns a content digest and explicit missing-evidence
list, and has no I/O, persistence, side effects or model dependency. Malformed input returns
`invalid` (CLI exit 1); a valid preparation receipt returns `incomplete` (CLI exit 0), always with
`start_authorized: false`. Exit 0 validates structure, not evidence authenticity or live readiness.
The validator rejects offline completion claims and populated live-evidence fields. Later live
receipts remain under their existing authenticated production readers and parent validation;
do not rewrite this preparation artifact into a signed approval or a second authority store.
Replacing this validator must preserve that fail-closed distinction and its receipt contract.

Before any live Start, parent #5399 must supply qualified independent authority, concrete host
transport/bootstrap **and host candidate preparation/stage/commit**, an authenticated M2 UI,
separately prepared Bifrost policy/governance and exact selected-operation stop/recovery/rollback
proof. Issue #5593 supplies the dormant repository candidate producer through the protected local
fence, not an installed or qualified live composition. `PublicationTarget` expects an independently
observed head; the content worker still cannot write Git metadata. The launcher reports stop as unsupported; that limitation and an
existing bob deployment rollback cannot substitute for real selected-operation rollback proof.

The single candidate/continuation owner is
[FCA-ID-HOST-CANDIDATE](README.md#fca-id-host-candidate--protected-candidate-and-continuation-contract).
It distinguishes the implemented dormant local-effect fence and versioned candidate/readback
chain from later remote transport and continuation. Disposable production-composed proof permits
raw external I/O fixtures, not authority verdicts or live qualification. This does not complete
the pilot; the live requirements above remain pending.

Consumer preparation must preserve Bifrost Issue25/PR26's local-Issue and foreign-auto-closer
policy. Hub-tracked v2 needs its own bounded preparation, not retargeting or policy weakening.
The permitted envelope remains exact regular non-executable `docs/*.md` files; root README is
outside it. Learning `lrn_20260917192047_850a746b` remains unresolved here. No preparation,
credential activation, host deployment, recovery operation or live pilot is performed by #5405.
Only independently observed source/result/readback and candidate-bound human trial/acceptance
can satisfy the later pilot. Parent #5399 remains open even after this child is merged.

## Out of Scope

No new routing/provider/tenant system, source extraction, mass portability refactor, repository creation, credential grant or live delivery effect in this pre-merge slice.

## Restart / Durability Posture

No new parallel authority store is introduced. Source facts and authorized operation receipts retain the durability of their existing owner. LLM text and views are derived; after restart regenerate them from current sources, show any unavailable history explicitly, and never redispatch an ambiguous action from the regenerated text. A previously accepted/tried fact must come from its durable source rather than memory of this view.

## Related Docs

- `docs/BUILDER_FACTORY_ACCEPTANCE/README.md`
- `docs/audits/BUILDER_SYSTEM_VISION_DELIVERY_2026-09-07.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`

## Related GitHub Issues

- #3793 and #5181 — retained parent live qualification/authority gates, not pre-merge scheduling edges
- #4697 — first inquiry seam when selected; separate Issue-workflow admission when delivery is selected
- #5504 — managed source/runtime and ordered evidence contract

Execution context: `fresh_issue_agent`; issue-local helper budget: 1.
Capability recommendation: Tier 3 multi-repo/auth boundary; fresh issue agent, configured Codex high reasoning, independent mechanism review; helper budget 1.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
