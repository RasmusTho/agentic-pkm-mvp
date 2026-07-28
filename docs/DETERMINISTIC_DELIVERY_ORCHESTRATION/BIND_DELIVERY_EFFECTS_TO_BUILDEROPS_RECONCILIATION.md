---
name: Bind Delivery Effects to BuilderOps Reconciliation
description: Bind reducer effects to the existing fenced transaction/outbox substrate and prove restart convergence.
task_id: DDO-05
github_issue: 4168
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Architecture reconciliation after DDO-03
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
- [ ] Merge and closure recovery preserve exact-head and verified issue-set authority.
  - Verify: `tests/builderops/test_delivery_orchestration_recovery.py::test_merge_and_closure_recovery_preserves_exact_authority`.
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

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/development/BUILDER_CONTROL_PLANE.md`
- `docs/audits/BUILDER_DELIVERY_AGENT_OS_2026-07-28.md`

## Related GitHub Issues

Live task: [#4168](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4168), blocked on DDO-04
[#4167](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4167). Reconcile its execution timing
with open BCP cutover #3793; do not duplicate that work.
