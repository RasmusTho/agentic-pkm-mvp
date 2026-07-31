---
name: PostgreSQL Transaction Kernel
description: Establish the single PostgreSQL authority and atomic orchestration/outbox primitives.
task_id: BCP-01
github_issue: 3792
source_anchor: docs/BUILDEROPS_CONTROL_PLANE/README.md :: Cross-task invariants / partial-failure safety
parent_capability: BuilderOps independent control plane
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# PostgreSQL Transaction Kernel

Delivery status: implemented in the development baseline by #3792/PR #3852; not deployed or
authoritative until the later deployment/cutover slices complete.

## Purpose

BuilderOps and dispatcher currently split records, tasks, leases, idempotency, receipts, events, and
file projections across multiple SQLite/filesystem authorities. The control plane needs one storage
port and PostgreSQL implementation before network deployment or migration can be safe.

## What This Task Does

- define a domain-neutral BuilderOps store port used by API/services without importing SQLite or a
  concrete PostgreSQL adapter, including replay, orphaned-claim recovery, unknown-effect marking,
  reconciliation, status reads, and receipt-backed record, attempt, promotion, and lease operations;
- add an independent BuilderOps PostgreSQL schema/migration lineage for repo-scoped tasks, attempts,
  records, transitions, fenced leases, idempotency, append-only receipts, and outbox/dead letters;
- require `RepoRef`, `scope`, `stack`, actor, source references, and schema version on every
  authority-bearing record, with repo-namespaced leases, idempotency keys, outbox operations, and
  promotions;
- make guarded state + idempotency result + receipt + outbox intent one transaction;
- expose the committed receipt sequence and PostgreSQL recovery LSN for observability and
  post-restore reconciliation (ADR-0062 A1: acknowledgement, replay, dependent transitions, and
  outbox eligibility require the local PostgreSQL commit only);
- implement atomic claim/heartbeat/release/complete with monotonically fenced ownership;
- implement an outbox claim/retry/reconciliation state machine with deterministic operation keys, a
  fenced pre-effect attempt/receipt, and an idempotent append-only reconciliation receipt bound to
  the exact claim and readback outcome;
- retain SQLite only as an explicitly injected test/migration adapter, never an automatic runtime
  default; and
- expose schema/authority-epoch metadata needed by readiness and cutover.

## Concretely

The slice provides a PostgreSQL-backed store contract that integration tests can start against a
disposable database. A representative transaction creates/claims a repo-scoped task, commits its
state transition, receipt, idempotent response, and outbox row, then exposes the same committed
result to a retry. Fault injection at each pre-commit step exposes no partial state.

## Why This Matters

Every later slice depends on this correctness kernel. A service or migration built before the
atomic store contract would merely relocate split-brain and crash-window defects to a network host.

## Source Anchors

- `docs/adr/ADR-0010-builderops-vault-authority-boundary.md :: Decision`
- `docs/AGENT_ISSUE_DISPATCHER.md :: Current-State Honesty`
- `docs/builderops/BUILDEROPS_VAULT_STORE.md :: Multi-Agent Safety`

## SBS Impact

Builder System enabling-system work. No Product SBS owner changes; the storage port/schema is owned
by BuilderOps governance and remains outside Product persistence authority.

## Constraints

- No Product database tables or Product Alembic lineage own this schema.
- GitHub effects do not run inside the transaction; only durable outbox intent does.
- A timed-out external call stays `unknown` until reconciled.
- Stale fencing tokens cannot mutate after lease expiry/reassignment.
- File projections/artifacts cannot be the sole terminal-state or receipt authority.
- A transaction result binds its committed receipt sequence and recovery LSN for observability and
  post-restore reconciliation; acknowledgement, replay, and outbox eligibility require the local
  PostgreSQL commit only (ADR-0062 A1).
- If a response is lost after that local commit but before its observability LSN is bound, replay,
  outbox claim, or status read completes the local binding under the committed identity; no
  independent recovery proof may gate the committed operation.
- Initialization verifies exact migration names/checksums and refuses newer, missing, gapped, or
  inconsistent lineage/epoch metadata. Ledger-free bootstrap requires a genuinely empty schema:
  no BuilderOps-named table, index, sequence, other relation, or function may already exist.
- Missing/ambiguous repo scope fails closed; an identity, lease, idempotency key, or promotion in one
  repo namespace cannot collide with or authorize another. GitHub owner/repository identity is
  canonicalized to lowercase before persistence so case aliases cannot split one authority namespace.
- Do not yet switch production clients or remove Product routes.

## Acceptance Criteria

- [x] One PostgreSQL transaction atomically commits idempotency, guarded state, append-only receipt,
  and outbox intent, and fault injection before commit exposes none of them.
  Verify: `tests/builderops/control_plane/test_postgres_transaction_kernel.py::test_state_receipt_idempotency_and_outbox_commit_atomically`.
- [x] Equal retries return the original committed result while conflicting reuse of an idempotency
  key fails closed.
  Verify: `tests/builderops/control_plane/test_postgres_transaction_kernel.py::test_idempotency_replay_and_conflict`.
- [x] Concurrent claim/heartbeat/reassignment uses fencing so a stale worker cannot transition the
  task after losing its lease, including across process restart.
  Verify: `tests/builderops/control_plane/test_postgres_leases.py::test_stale_fencing_token_cannot_mutate_after_reassignment`.
- [x] Outbox claims are crash-recoverable and a timed-out external effect enters reconciliation
  rather than immediate replay or terminal success.
  Verify: `tests/builderops/control_plane/test_outbox_recovery.py::test_unknown_external_effect_requires_readback_before_retry`.
- [x] Production construction requires a PostgreSQL DSN and never selects/creates SQLite implicitly;
  the SQLite adapter is available only through explicit test/migration injection.
  Verify: `tests/builderops/control_plane/test_store_selection.py::test_production_store_fails_closed_without_postgres`.
- [x] BuilderOps migrations are versioned independently of Product migrations and readiness can
  report the authority epoch and schema version.
  Verify: `tests/architecture/test_builderops_migration_boundary.py::test_builderops_migrations_do_not_use_product_lineage`.
- [x] Every authority-bearing row rejects a missing mandatory multi-repo envelope, and task/lease/
  idempotency/outbox/promotion identities are repo-namespaced so repo A cannot collide with or
  authorize repo B.
  Verify: `tests/builderops/control_plane/test_multirepo_namespace.py::test_authority_envelope_is_required_and_repo_namespaces_are_isolated`.
- [x] Each accepted transaction returns a committed receipt sequence and recovery LSN bound to its
  idempotent result for observability and post-restore reconciliation.
  Verify: `tests/builderops/control_plane/test_postgres_transaction_kernel.py::test_transaction_result_binds_receipt_sequence_and_recovery_lsn`.

## Out of Scope

- network API/authentication and Compose deployment;
- importing legacy data;
- adapting MacBook or Demerzel clients; and
- removing current Product routes.

## How to Verify (Pre-Merge)

- run the focused PostgreSQL integration tests with concurrent writers and fault injection;
- run existing BuilderOps/dispatcher semantic tests against the new store port; and
- run `ruff check app tests` for touched Python surfaces.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/audits/BUILDEROPS_CONTROL_PLANE_2026-07-15.md`

## Related GitHub Issues

- [#3792](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3792), the first executable child
  (PR #3691 merged 2026-07-15; amended by ADR-0062 A1 on 2026-07-16).
