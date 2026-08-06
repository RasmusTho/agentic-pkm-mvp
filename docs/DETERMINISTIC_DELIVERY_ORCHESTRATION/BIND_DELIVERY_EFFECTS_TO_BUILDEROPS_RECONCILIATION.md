---
name: Bind Delivery Effects to BuilderOps Reconciliation
description: Bind reducer effects to the existing fenced transaction/outbox substrate and prove restart convergence.
task_id: DDO-05
github_issue: 4168
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Architecture reconciliation for autonomous scheduled bug delivery
parent_capability: Deterministic Delivery Orchestration
prerequisites: [DDO-04]
depends_on: [ADVANCE_DELIVERY_RUNS_DETERMINISTICALLY.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / xhigh"
capability_rationale: "Data, concurrency, crash recovery, fencing, and external-effect reconciliation."
---

# Bind Delivery Effects to BuilderOps Reconciliation

## Purpose

Make effectful delivery restart-safe without constructing a second orchestration database or
weakening GitHub authority.

## What This Task Does

- Maps reducer effect identities and expected-state guards onto the delivered #3792 BuilderOps
  PostgreSQL transaction/outbox contract.
- Adds the minimum delivery-specific adapter payloads, readback evidence, fencing, claim, and
  reconciliation behavior.
- Persists worker invocation correlation and reattachment evidence.
- Reconciles unknown effects against GitHub/dispatcher/worktree/CI truth before retry.
- Publishes a rebuildable `DeliveryRunView.v1` from the journal/reducer for active status without
  making that view or CKM authoritative.
- Proves the provider-neutral worker-runtime port against crash-before-start,
  start-acknowledgement-loss, active reattachment, terminal-result-loss, and cancel-during-effect
  cases.
- Preserves the ADR-0062 degraded-mode contract.
- Binds the repository-scoped generic `delivery-lane:type:bug` fence as serial admission for the
  scheduled bug profile without letting that generic lease authorize task or external effects.
- Reconciles the same active attempt before selection and observes/waits on foreign claims,
  workers, worktrees, PRs, and incomplete closure without adopting them.
- Adds a versioned `preparing` reducer phase and dormant WorkerRuntime state. The exact Codex
  thread, branch, worktree, base SHA, and one `prepared` generation in the existing worktree
  registry are read back before claim; successful claim promotes that same generation `active`
  before the same invocation receives implementation authority.
- Persists the cross-surface identity as an append-only graph and emits an additive
  `DeliveryAttemptTerminalReceipt.v1`. A PR-bearing attempt emits it only after #3604-owned closure
  and owner-doc evidence are complete; a no-delivery attempt instead proves zero unresolved
  effects, claims, workers, attributable PRs, and undisposed prepared worktrees.

## Concretely

A crash after GitHub accepts a write but before the local success receipt produces an unknown
outbox state. On restart, the runner reads the external object, proves whether the exact intended
effect happened, records one reconciliation receipt, and either advances or retries without a
duplicate logical effect.

## Why This Matters

Without durable effect identity and reconciliation, unattended orchestration can duplicate workers,
comments, merges, or closures after a crash.

## Acceptance Criteria

- [ ] A conformance map proves which #3792 transaction/outbox primitives are reused and identifies
  no parallel journal authority.
  - Verify: doc writeback at `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Prior work reused rather than duplicated`.
- [ ] Two concurrent scheduled ticks for one repository produce one fenced
  `delivery-lane:type:bug` winner and zero duplicate Issue selections, claims, or worker starts.
  The generic lane lease cannot authorize task/dispatcher/outbox/GitHub effects.
  - Verify: `tests/builderops/control_plane/test_delivery_lane.py::test_concurrent_scheduler_ticks_share_one_fenced_bug_attempt`.
- [ ] Every tick resumes only the matching active attempt before selection. A foreign live claim,
  worker, worktree/branch, PR, or incomplete closure is reported and waited on, never adopted or
  overwritten.
  - Verify: `tests/builderops/control_plane/test_delivery_lane.py::test_resume_and_foreign_census_precede_new_selection`.
- [ ] Selection is confined to one exact approved request/plan/profile; neither cron nor CKM may
  authorize a backlog-wide search or expand the approved set.
  - Verify: `tests/builderops/control_plane/test_delivery_lane.py::test_selection_requires_exact_approved_scope`.
- [ ] Every effect binds run, plan, Issue, PR/head where relevant, effect type, expected state, and
  a stable operation key.
  - Verify: `tests/builderops/control_plane/test_delivery_outbox.py::test_delivery_effect_identity_is_complete_and_stable`.
- [ ] Fault injection before commit, after commit/before effect, after external effect/before
  receipt, and during reconciliation converges.
  - Verify: `tests/builderops/control_plane/test_delivery_outbox.py::test_delivery_effect_fault_matrix_converges`.
- [ ] Worker launch recovery reattaches to the correlated active invocation or returns its terminal
  result without launching the same invocation again.
  - Verify: `tests/builderops/test_delivery_orchestration_recovery.py::test_worker_recovery_never_duplicates_invocation`.
- [ ] A lost start acknowledgement produces `unknown` and forces inspect/readback/reattach. The
  same invocation/idempotency key starts only if readback proves `not_started`; terminal readback
  returns the prior result. Any later repair attempt requires a new reducer-authorized effect and
  invocation identity.
  - Verify: `tests/builderops/test_delivery_orchestration_recovery.py::test_unknown_worker_start_requires_readback_before_retry`.
- [ ] Detached Codex project-worktree bootstrap follows one recoverable
  `preparing`→`prepared`→claim→same-generation `active`→activate sequence. Prepared state grants no
  Issue claim, edit, implementation turn, active-worker authority, or GitHub mutation; unknown
  preparation reattaches to the same invocation/thread.
  - Verify: `tests/builderops/test_delivery_worker_runtime.py::test_detached_project_worktree_prepares_then_claims_then_activates`.
- [ ] The existing worktree lifecycle registry promotes the same generation from `prepared` to
  `active` after claim; same-attempt readback reattaches, while a mismatched generation fails
  closed.
  - Verify: `tests/ops/test_agent_worktree.py::test_prepared_generation_promotes_active_without_rebinding`.
- [ ] The cleanup doctor preserves prepared, active, dirty, locked, claimed, PR-bound, and foreign
  worktrees and reports their collision/ownership evidence without destructive inference.
  - Verify: `tests/ops/test_agent_worktree.py::test_prepared_generation_cleanup_preserves_foreign_or_active_state`.
- [ ] `AGENTS.md` and `issue-to-code` use the same pre-claim prepared versus post-claim active
  authority boundary, so no producer grants edits or implementation turns from prepared state.
  - Verify: `tests/governance/test_agent_instruction_contracts.py::test_prepared_worktree_authority_requires_claim_before_active`.
- [ ] The attempt identity persists as an append-only graph; adding a new PR head preserves prior
  nodes but invalidates all earlier head-bound CI/review proof before another transition.
  - Verify: `tests/builderops/control_plane/test_delivery_outbox.py::test_attempt_identity_graph_appends_head_evidence_and_invalidates_prior_head_proof`.
- [ ] Merge and closure recovery preserve exact-head and verified issue-set authority.
  - Verify: `tests/builderops/test_delivery_orchestration_recovery.py::test_merge_and_closure_recovery_preserves_exact_authority`.
- [ ] Lane release requires an additive `DeliveryAttemptTerminalReceipt.v1` binding the immutable
  `DeliveryReceipt.v2`, merge/closure identity, exact owner-doc receipt, dispatcher/label cleanup,
  worker/worktree terminality, and zero unresolved effects. Existing v1/v2 bytes retain their
  meaning; a proved no-delivery outcome includes zero undisposed prepared worktrees.
  - Verify: `tests/builderops/test_delivery_orchestration_recovery.py::test_lane_release_requires_complete_terminal_identity_chain`.
- [ ] Adding `DeliveryAttemptTerminalReceipt.v1` leaves serialized `DeliveryReceipt.v1` and
  `DeliveryReceipt.v2` bytes and validation semantics unchanged and readable.
  - Verify: `tests/builderops/test_delivery_orchestration_recovery.py::test_attempt_terminal_receipt_preserves_delivery_receipt_v1_v2_bytes`.
- [ ] Control-plane unavailability permits ordinary direct repo work but blocks orchestration-gated
  effects without fabricated success.
  - Verify: `tests/builderops/control_plane/test_delivery_outbox.py::test_degraded_mode_preserves_direct_work_and_blocks_gated_effects`.
- [ ] `DeliveryRunView.v1` is reproducible from the authoritative journal, includes wave/step/wait/
  exact-head/next-gate/control state, and cannot authorize an effect.
  - Verify: `tests/builderops/control_plane/test_delivery_run_projection.py::test_active_run_view_is_rebuildable_and_non_authoritative`.
- [ ] A carrier can be replaced while preserving the exact canonical plan and reducer-authorized
  worker-launch effect identity and producing the same normalized delivery-domain result. Every
  result retains mandatory invocation/carrier/provider/model/session/usage/provenance envelope
  fields whose values and bytes may differ. Missing envelope fields and mismatched
  plan/effect/Issue/head references fail conformance rather than being normalized away; no carrier
  journal, queue, or workflow ID becomes a second delivery authority.
  - Verify: `tests/builderops/control_plane/test_delivery_worker_carrier_conformance.py::test_carriers_share_semantics_without_authority`.

## How to Verify (Pre-Merge)

- Run all named control-plane, recovery, active-projection, and carrier-conformance tests.
- Run the existing outbox, fencing, verified-merge, and closure focused suites.
- Run `ruff check app tests` and `mypy app`.
- Run the data/concurrency/external-API/state-machine convergence review before expensive validation.

## Out of Scope

- Replacing #3792 storage or migrations.
- Completing BCP-06 cutover issue #3793.
- Product Runtime deployment.
- Weakening recovery or merge authority.
- Selecting or adopting an external workflow engine before the conformance gate is proven.
- Defining #3604's closure policy, activating BCP-06/#3793, creating a second worktree registry, or
  enforcing seriality on direct manual pickup outside the participating DDO/BuilderOps scheduler.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/development/BUILDER_CONTROL_PLANE.md`
- `docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md`
- `docs/audits/AUTONOMOUS_BUG_DELIVERY_ARCHITECTURE_2026-08-05.md`

## Related GitHub Issues

Live task: [#4168](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4168), blocked pending live
prerequisite/readiness reconciliation. Reuse BCP-05 #3603, closure recovery #3604, and delivered
#3792; reconcile execution timing with BCP cutover #3793 and autonomous CI repair #4466 without
duplicating their policy or activation work.
