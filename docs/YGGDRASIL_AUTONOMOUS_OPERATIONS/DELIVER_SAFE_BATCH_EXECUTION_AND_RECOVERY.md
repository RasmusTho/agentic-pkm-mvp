---
name: Deliver Safe Batch Execution and Recovery
description: Execute bounded homogeneous operation batches with item receipts, truthful partial failure, cancellation, and resume
task_id: AUTOOPS-08
github_issue: 5337
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Batch semantics"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-03, AUTOOPS-04, AUTOOPS-05, AUTOOPS-06, AUTOOPS-07]
depends_on: [CONSOLIDATE_DISCOVERY_AND_READ_OPERATIONS.md, CONSOLIDATE_CREATE_AND_EDIT_OPERATIONS.md, DELIVER_IDENTITY_PRESERVING_MOVE_AND_RENAME.md, DELIVER_CLASSIFICATION_TAGGING_AND_ORDERING.md, COMPOSE_ARCHIVE_AND_RESTORE_OPERATIONS.md]
can_parallelize_with: []
---

# Deliver Safe Batch Execution and Recovery

## Purpose

Let a bounded delegation act over many artifacts without concealing per-item effects or demanding repeated approval.

## What This Task Does

Implement preview, bounded selection, per-item execution, aggregate progress, cancellation, restart-safe
resume, and recovery for supported operation kinds. Reuse the single-operation kernel for each effect.

## Dormant implementation and supported boundary

`app/operations/batch_operations.py::BatchOperationCoordinator` provides finite composition over
an explicitly supplied `OperationExecutionKernel` and its existing `JsonReceiptStore`. #5337
delivered this initially dormant coordinator. #6456 installs its authenticated HTTP lifecycle through
`app.api.batch_operation_runtime.build_production_batch_runtime`, reusing #5352's canonical
`build_production_operation_runtime`, scoped owners and the same host-owned journal object.
#5329 retains complete capability acceptance and owner-doc promotion; #5339 and #5340 retain their
GUI and MCP v2 implementation/proof. No singleton, scheduler, supervisor or new receipt store is added.

The installed kind set is the finite set below intersected with production-qualified handlers:
body-only `artifact.update` and, on qualified local POSIX filesystems, `artifact.move` and
`artifact.rename`. Semantic classification/tags/order remain unavailable because their human
approval producer is absent. Discovery reports `operation.batch` with `supported_kinds`,
`max_targets: 100` and `partial_success_policy: independent`; it cannot activate a missing owner.

The shared HTTP lifecycle is:

| Method and path | Bounded input / result |
| --- | --- |
| `POST /api/operations/batches/preview` | `batch_id`, `operation_id`, original `active_context_ref` / `vault_generation`, one selected `target_binding_id`, 1..100 `items` (`request_id`, stable `artifact_id`, `expected_version`, owner `arguments`), optional `limit` and `partial_success_policy: independent`. Freezes the exact host-admitted plan without source effects. |
| `GET /api/operations/batches/{batch_id}?expected_digest=...` | Authenticated, scoped retained inspection of the original confirmation digest and per-item truth. |
| `POST /api/operations/batches/{batch_id}/execute` | Only `expected_digest`. The existing coordinator executes pending items or reconciles uncertain original items; this is also the retained recovery entrypoint. |
| `POST /api/operations/batches/{batch_id}/cancel` | Only `expected_digest`. Persists cancellation before suppressing pending starts; started effects retain reconciliation. |

All responses carry preview/candidate/selector/argument/delegation digests, cardinality, original
policy ceiling, aggregate `status` / `counts`, `cancel_requested` and exact item outcomes. The
response's `current_admission: original` means the request still matches the original frozen
selection/context; each effect separately rechecks current GOV, versions and native fences.
`current_admission: refused` can accompany retained committed/unknown evidence. Neither readback
nor a journaled grant can authorize a new effect. Unknown native results remain recovery-required;
source commitment and Store/index/link lag stay separate. Missing/corrupt/foreign or insufficiently
host-admitted state returns `batch_state_unavailable` (or a scoped unavailable response) before
source effects. Clients cannot submit selector reconstruction, delegations, policy, tokens, paths,
keys, readers or receipts. Exact preview retries return the existing token identities and deadline;
changed intent under that batch identity refuses.

The finite supported kinds are `artifact.update` with body-only arguments, `artifact.move`,
`artifact.rename`, `artifact.classify`, `artifact.tags.add`, `artifact.tags.remove`, and
`collection.reorder`. Each item retains its actual write, placement, or semantic owner. The trusted
producer must bind the appropriate owner for each frozen target; a handler for another target
refuses. Every item passes through `OperationExecutionKernel.execute`, including its explicit
owner-reconciliation mode. The default single-operation historical replay stays unchanged.

Capture and creation have no existing versioned target to freeze. Proposal application can produce
diagnostic source writes with a separately pending semantic effect. Read owners use their existing
read adapter rather than this mutating kernel path. Archival owners have their own generation and
GAF receipt protocol, but their delivered operation interface supplies no read-first recovery lookup
for an exact original operation after its active representation changes. This bounded batch seam
therefore refuses capture, creation, proposal application, reads, archive/restore, and unknown kinds
at preview, before any effect. Delivered prerequisites remain delivered; this is an explicit
supported-kinds boundary, not another prerequisite or a claim of complete operation parity.

Preview accepts one to 100 unique stable targets with unique operation identities, original source
versions, one kind/context/vault generation, and bounded JSON arguments. It durably freezes the
entire requests, selector, candidate/argument/delegation digests, policy ceiling, limit, and the
`independent` partial-success policy. An explicit conflicting atomic/staged policy refuses. The
confirmation digest binds every frozen field; reusing a batch identity for different intent or
executing a different digest refuses. No selector runs during execution or resume. The owner still
checks current identity, original CAS, context, approval and authority at its actual effect seam.
The opt-in kernel handoff supplies that original delegation to each native owner. Its unchanged
absolute deadline is checked after owner waits at the local body CAS/conflict-publication seam,
after the semantic owner's final approval/selection observations, and at every placement namespace
seam including prepared recovery. A later native context expiry cannot extend an earlier delegated
deadline. This is a per-call constraint, not an ambient callback or a new authority policy.

Batch snapshots are a bounded extension inside the existing kernel JSON journal, not mutation
receipts. Atomic file replacement and file/directory synchronization precede acknowledgement.
A process-held run fence serializes consumers of one batch. A separate snapshot fence protects
progress and cancellation; the snapshot and global journal locks are released before owner work.
One original-request effect window additionally spans initial reservation, native work and kernel
finalization as well as recovery. A competing consumer reads current history after that same window
wait, so it cannot reconcile a still-running initial effect or overwrite completed proof with a
stale recovery snapshot. No independent lease or registry is added. The durable start marker
distinguishes an in-flight item from a pending item. Cancellation persists before pending starts
are suppressed, while already-started items retain receipt reconciliation. A competing executor
rechecks cancellation after its run-fence wait. The coordinator re-reads state after each owner
call so it cannot overwrite a concurrent cancellation.

On restart, the coordinator reads kernel history by the original operation identity before any
effect. Completed/conflicted/refused items keep their outcomes. An uncertain kernel reservation
never invokes the ordinary mutation handler again. A trusted producer may supply the existing
placement reconciliation seam, which can complete a proven prepared placement under original
versions and current owner authority. Semantic/body-edit reconciliation only reads the exact
durable owner outbox receipt and verifies its original intent and source result. A missing receipt
or later source change remains recoverable, without inferring a receipt from source bytes. Expired
or refused recovery retains known committed/unknown source truth, native receipts and repair work.
No new issuer, TTL, authority refresh, rollback, or recovery policy is introduced.
The existing kernel reservation/outcome also records a non-secret digest of its original policy
decision identity. Recovery may veto that decision but cannot replace it with a same-version new
token. Missing original binding remains recoverable without starting another source effect.
Before any potentially mutating native recovery callback, the existing kernel journal durably
records an uncertain new attempt. An older `not_applied` result cannot describe that attempt after
process loss. Failure to persist the marker prevents the callback. Previously committed source
and native/GOV receipt evidence remains immutable and is retained from the batch's durable copy
when a kernel reservation or current refusal is weaker. That retained proof never becomes a new
success acknowledgement; current recovery admission and source/repair truth remain separate.

For an initially stale source, HKA's shared conflict publisher repeats the native final guard and
original deadline after candidate write/flush/fsync and before each actual public link, including
collision retries. A valid already-public conflict artifact is retained and accounted for if its
subsequent verification or durability work crosses expiry. No blanket post-effect rejection or
rollback erases that evidence.

Successful mutating items require the preserved native source receipt and applicable durable GOV
AuthorityReceipt. A kernel summary, diagnostic, queued effect, or completed projection is
insufficient. Per-item outcomes retain those native receipts separately from Store/index/link lag.
Aggregate counts expose completed, conflicted, refused, ambiguous, pending, cancelled, recoverable,
and convergence-pending work. A partial batch is never wholly successful; durable source effects
with outstanding projection repair remain `convergence_pending`.

## Concretely

```text
batch.preview(kind="artifact.tags.add", selector=..., limit=100) -> immutable candidate digest
batch.execute(preview_id=..., delegation=...) -> completed=73 conflicted=2 refused=1 pending=24
```

## Why This Matters

Batch autonomy is useful only when partial completion is inspectable and replay cannot duplicate effects.

## Acceptance Criteria

- [x] Preview binds selector, candidate digest, policy ceiling, operation kind, and bounded cardinality.
  Verify: `tests/operations/test_batch_operations.py::test_batch_preview_binds_scope_digest_policy_and_limit`
- [x] Execution records an item outcome/native receipt and a truthful aggregate for mixed success, conflict, and refusal.
  Verify: `tests/operations/test_batch_operations.py::test_batch_execution_preserves_every_item_outcome_and_aggregate_truth`
- [x] Cancellation, process loss, and resume never duplicate completed effects or skip unresolved items.
  Verify: `tests/operations/test_batch_operations_restart.py::test_batch_cancel_and_restart_resume_are_idempotent`
- [x] Candidate drift after preview is detected per item and cannot expand delegated scope.
  Verify: `tests/operations/test_batch_operations.py::test_batch_candidate_drift_conflicts_without_scope_expansion`
- [x] Supported production callsites retain owner effects/GOV receipts and reconcile ambiguous or receipt-pending effects without blind retry.
  Verify: `tests/operations/test_batch_operations.py::test_batch_production_owner_receipt_is_required_before_success`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_batch_operations.py tests/operations/test_batch_operations_restart.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_production_batch_runtime.py tests/api/test_operation_batches_api.py tests/api/test_operation_batches_api_restart.py tests/architecture/test_autonomous_operations_boundaries.py`
- `ruff check app tests`

## Out of Scope

- Distributed transactions, unbounded jobs, cross-vault batches, or automatic rollback of valid committed items.

## Restart / Durability Posture

Preview identity, candidate digest, item states, receipts, cancellation, and recovery cursor are durable.
After restart, the user sees exact completed and unresolved work rather than a reset progress bar.
A rebuilt runtime/coordinator can resume only while the original WSP record/context, original GOV
kernel decision identity and deadline remain current. The host reconstructs an owner from its
journaled original locator/token only after exact comparison with current host authority; it never
looks up a later locator as replacement authority. Resolution precedes the captured-record window,
which is held per native effect rather than over the complete batch run.

A full WSP process reset invalidates the old bearer. A new authenticated selection with proper
current read scope may inspect/cancel retained work and read exact durable body/native/GOV evidence,
but cannot rebind an old batch, extend its expiry or start its pending/uncertain effects. A native
receipt readback can enrich evidence while `recovery_required` and refused admission remain visible.
An admitted cancellation persists concurrently with a started owner; a queued executor rechecks it
after the existing run-fence wait. No background consumer is installed.
Missing or corrupt frozen state raises `BatchStateUnavailable` before any new effect. It is never
reconstructed from a selector, progress counter, diagnostic, or projection.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`

## Related GitHub Issues

AUTOOPS-03 through AUTOOPS-07 are verified-delivered prerequisites. #5337 delivers this dormant
bounded composition; #6456 owns production HTTP installation and parent #5329 retains final acceptance.
Execution uses a fresh Issue owner with configured provider-neutral capability selected for the
durability, concurrency, and state-machine risk.
