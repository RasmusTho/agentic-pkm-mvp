---
name: Produce owner decision and trial facts
description: produce and project explicit owner decision and trial receipts
task_id: FCA-05
github_issue: 5404
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent"
parent_capability: Builder Factory Acceptance
prerequisites: [FCA-02, "#4169"]
depends_on: [DEFINE_OWNER_FACT_AND_ACTION_CONTRACT.md]
can_parallelize_with: []
---

State: Target-state task specification; not implemented or runtime acceptance.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Produce owner decision and trial facts

## Purpose

The future fact contract in FCA-02 replaces neither GitHub nor deployment authority. Its admitted facts must be produced before DevUI can show real owner decisions or try/accept states; LLM proposals remain separately labelled.

## What This Task Does

Implement only the four fact producers and read transport enumerated by the accepted FCA-02 contract, using its named existing authenticated writer and BuilderOps/GitHub receipt boundary. Bind asks to exact subjects/options/authority class; bind tryability to exact candidate, environment and deployment/evidence identity; record explicit owner trial/acceptance/rejection. Project them through existing DevUI Overview/Focus inputs with exact-source links and invalidation on supersession. Prefer extending the existing receipt schema/transport; no new generic store, queue or command service. #4169 remains action-boundary owner; after FCA-01 reconcile its prerequisite to the admitted bounded action, not unconditional full DDO completion.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is produce and project explicit owner decision and trial receipts.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] The production writer requires the authorized subject/version and uses the FCA-02 source boundary; replay and concurrent attempts do not duplicate an accepted fact.
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_production_writer_is_authorized_version_bound_and_idempotent`
- [ ] Deployed candidate, verification, ready-to-try, trial and acceptance remain distinct; a new candidate invalidates old try/accept projection rather than borrowing its result.
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_changed_candidate_cannot_inherit_trial_or_acceptance`
- [ ] Overview/Focus production composition distinguishes canonical asks, technical waits and LLM suggestions and withdraws stale/unavailable source claims.
  - Verify: `tests/api/test_devui_owner_facts.py::test_production_reads_use_source_facts_without_label_or_model_inference`
- [ ] After interruption between the authorized fact write and downstream projection, readback/retry returns the existing receipt and rebuilding the view preserves the outcome.
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_restart_reconciles_written_fact_before_projection`

## How to Verify (Pre-Merge)

Run named producer/API tests against the production call sites, auth/receipt regressions and normal code baseline. Include simulated post-write interruption. UI pilot is FCA-07; this child proves production data and write authority only.

## Out of Scope

No new authority store, visual shell or decision classifier based only on a label; no deployment, actor credential provisioning or duplicate #4169 command API.

## Restart / Durability Posture

No new parallel authority store is introduced. Source facts and authorized operation receipts retain the durability of their existing owner. LLM text and views are derived; after restart regenerate them from current sources, show any unavailable history explicitly, and never redispatch an ambiguous action from the regenerated text. A previously accepted/tried fact must come from its durable source rather than memory of this view.

## Related Docs

- `docs/BUILDER_FACTORY_ACCEPTANCE/README.md`
- `docs/audits/BUILDER_SYSTEM_VISION_DELIVERY_2026-09-07.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`

## Related GitHub Issues

- #4169

Execution context: `fresh_issue_agent`; issue-local helper budget: 1.
Capability recommendation: Tier 3 authenticated durable-state boundary; fresh issue agent, configured Codex high reasoning, independent mechanism review; helper budget 1.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
