---
name: Produce owner decision and trial facts
description: produce and project explicit owner decision and trial receipts
task_id: FCA-05
github_issue: 5404
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent"
parent_capability: Builder Factory Acceptance
prerequisites: [FCA-02, FCA-08, FCA-09]
depends_on: [DEFINE_OWNER_FACT_AND_ACTION_CONTRACT.md, DEFINE_BOUNDED_ACTION_ADMISSION.md, DEFINE_OWNER_OUTCOME_AUTHORITY.md]
can_parallelize_with: []
---

State: Target-state task specification; not implemented or runtime acceptance.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Produce owner decision and trial facts

## Purpose

The future fact contract in FCA-02 replaces neither GitHub nor deployment authority. Its admitted facts must be produced before DevUI can show real owner decisions or try/accept states; LLM proposals remain separately labelled.

## What This Task Does

Implement the four FCA-02 fact producers and read transport, with trial/acceptance governed by the separate [FCA-09 outcome contract](../builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md#candidate-bound-owner-outcome-contract-fca-09) in the existing authenticated BuilderOps service and receipt owner. Bind asks to exact subjects/options/authority class; bind tryability to exact candidate, environment and deployment/evidence identity; record explicit owner trial/acceptance/rejection. Project them through existing DevUI Overview/Focus inputs with exact-source links and invalidation on supersession. Prefer extending the existing receipt schema/transport; no new generic store, queue or command service. The accepted [FCA-08 bounded admission contract](README.md#bounded-action-admission) retains the existing service and selected destination owners. #4697 owns the first inquiry admission/reservation/readback seam; #4169 is required only for a selected DDO operation. Inquiry approval or generic record storage supplies neither owner confirmation nor permission for an Issue-delivery operation.

Pickup requires the accepted FCA-02/FCA-08/FCA-09 contracts and the selected operation's separately
implemented authenticated admission and destination reservation/readback prerequisites. It does
not require this task's four producers, outcome validation/atomic write, or read transport to
already exist: those are its owned implementation. Runtime projection/activation additionally
requires that delivered writer, source authority/deployment and actual candidate/readiness/profile
readback. Missing external evidence remains blocked; no full DDO portfolio is imposed on inquiry.
The retained P1 on #5404 remains unresolved until this task proves the repaired production path;
#5503's specification delivery alone does not resolve its source review thread.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is produce and project explicit owner decision and trial receipts.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] The production writer in the existing BuilderOps service authenticates the directly submitting profile-designated human principal with the dedicated outcome-confirm grant, repository/subject and finite FCA-09 payload, checks current permission/epoch and source versions, and commits guarded receipt selection, idempotency result and projection intent atomically. The existing service issues/verifies inline confirmation in that same outcome transaction; no separate confirmation source is inferred. Generic agent write permission, a mismatched owner principal, caller-supplied human identity/confirmation metadata and absent explicit confirmation refuse without an outcome. An owner request confirmed at T1 retains the same request hash when the server commits at T2; recorded time and confirmation/receipt metadata are outside that immutable request, and replay returns the original receipt.
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_production_writer_is_authorized_version_bound_and_idempotent`
- [ ] Equal-key/equal-payload replay returns the original receipt; changed payload under the same key returns `idempotency_conflict`. Two different-key initial submissions (`accepted` versus `rejected`, or equal outcomes) against the same predecessor yield one commit and one `current_receipt_conflict`, never two current decisions. A correction requires new explicit owner confirmation of the current predecessor. Trial and acceptance share the binding guard: trial correction first makes a concurrent old-trial acceptance refuse; acceptance first is withdrawn by the later trial correction, and a delayed projection cannot restore it.
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_conflicting_submissions_require_explicit_correction`
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_acceptance_and_trial_correction_share_serialization`
- [ ] Deployed candidate, verification, ready-to-try, trial and acceptance stay distinct. C/P1's trial and decision remain historical when C2, environment E2, profile/AC P2, readiness binding or material limits change; the new binding has neither trial nor acceptance. Correcting the referenced trial withdraws its acceptance. A rejected decision without a trial creates no trial, and `unable_to_try` cannot support acceptance.
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_changed_candidate_cannot_inherit_trial_or_acceptance`
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_changed_profile_and_trial_correction_withdraw_acceptance`
- [ ] Overview/Focus production composition reads exact source receipt lineage and current bindings, distinguishes canonical asks, technical waits and LLM suggestions, and withdraws stale/unavailable/incompatible/conflicting claims. An unavailable or unadmitted writer returns a typed unavailable/refusal with no new outcome; it cannot fabricate rejection, trial, acceptance or an empty successful result. An unavailable read never proves no prior commit.
  - Verify: `tests/api/test_devui_owner_facts.py::test_production_reads_use_source_facts_without_label_or_model_inference`
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_unavailable_writer_does_not_create_owner_outcome`
- [ ] A pre-commit interruption exposes no confirmation, receipt or projection intent. A lost response after commit is reconciled by the same key/payload; post-write projection failure preserves the exact committed outcome and returns unavailable projection evidence until source readback rebuilds it. Restart cannot issue a duplicate outcome or infer consent when authority history is missing.
  - Verify: `tests/builderops/test_owner_fact_producers.py::test_restart_reconciles_written_fact_before_projection`

These are FCA-05's future production-path proofs. FCA-09 verifies this finite expected-outcome
matrix as a document target; it does not claim that these tests or the production writer exist.

## How to Verify (Pre-Merge)

Run named producer/API tests against the production call sites, auth/receipt regressions and normal code baseline. Include simulated post-write interruption. UI pilot is FCA-07; this child proves production data and write authority only.

## Out of Scope

No new authority store, visual shell or decision classifier based only on a label; no deployment, actor credential provisioning, content-retention programme or duplicate action command API.

## Restart / Durability Posture

No new parallel authority store is introduced. Source facts and authorized operation receipts retain the durability of their existing owner. LLM text and views are derived; after restart regenerate them from current sources, show any unavailable history explicitly, and never redispatch an ambiguous action from the regenerated text. A previously accepted/tried fact must come from its durable source rather than memory of this view.

## Related Docs

- `docs/BUILDER_FACTORY_ACCEPTANCE/README.md`
- `docs/audits/BUILDER_SYSTEM_VISION_DELIVERY_2026-09-07.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`

## Related GitHub Issues

- #5502, #5503, #4697; #4169 only when the selected operation uses DDO.

Execution context: `fresh_issue_agent`; issue-local helper budget: 1.
Capability recommendation: Tier 3 authenticated durable-state boundary; fresh issue agent, configured Codex high reasoning, independent mechanism review; helper budget 1.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
