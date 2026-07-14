---
name: Route Requests Through Active Context
description: Migrate production HTTP retrieval and governed-write paths to immutable request context
task_id: MVR-05
source_anchor: "docs/MULTI_VAULT_RUNTIME/README.md :: Active context and isolation"
parent_capability: Multi-vault runtime selection
prerequisites: [MVR-03]
depends_on: [VERSION_ACTIVE_CONTEXT_SELECTION.md]
can_parallelize_with: [Group Vault Bindings By Dimension, Bind Background Lifecycles]
---

# Route Requests Through Active Context

## Purpose

After the versioned context seam exists, production HTTP, retrieval, and governed-write paths must
stop resolving a process-global vault mid-request. This slice migrates request-bound consumers,
not background lifecycles.

## What This Task Does

- Inject the request's immutable `ActiveContextSet` into Companion/API routes and shared service
  calls that read, retrieve, capture, mutate, or emit receipts against content vaults.
- Resolve per-binding settings, paths, caches, retrieval scope, and write provenance from the
  snapshot.
- Make many-binding reads explicit and provenance-preserving; require an explicit target binding
  for writes unless the command contract already provides one unambiguously.
- Add an architecture guard against new direct process-global vault resolution in request code.

## Concretely

Two clients call the production retrieval and capture routes concurrently with contexts for vaults
A and B. Results, caches, governed writes, and receipts stay attributed to their own binding; an
unknown selection returns the explicit picker/error contract and touches neither vault.

## Why This Matters

A correct resolver is insufficient if a downstream route re-reads mutable global state. One such
call site can leak retrieval context or write to the wrong human artifact surface.

## Source Anchors

- `docs/MULTI_VAULT_RUNTIME/README.md :: Active context and isolation`
- `app/api/routes/companion.py :: vault-bound request paths`
- `app/api/routes/capture.py :: governed capture path`
- `docs/contracts/ACTIVE_CONTEXT_SET.md`

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): GOV, RCA, HKA, EBF, HIX, OEF
- Write class: existing governed human-artifact writes; no new write authority
- Authority impact: enforces per-binding authorization and explicit write target
- Persistence impact: none beyond existing content writes/receipts
- Derived/rebuildable impact: caches/retrieval results generation-keyed and rebuildable
- Human knowledge impact: preserves source vault and target attribution
- Memory impact: retrieval/memory reads are scoped to explicit bindings
- Retrieval/context impact: production request consumers adopt ActiveContextSet
- Sync/deployment impact: supports concurrent requests without process rebinding
- External boundary impact: API input maps to context selectors, not raw trusted paths
- New or changed contract: request-context propagation and explicit multi-binding write target
- Owner-doc impact: will-update-in-PR at `docs/ARCHITECTURE.md`
- Transition debt impact: reduces D1 and request-side D13 global-binding debt
- Fitness rule impact: adds production-entrypoint context-boundary guard

## Constraints

- No route accepts a client path as authority or silently falls back on selection failure.
- Cross-vault reads retain source provenance; writes name exactly one authorized target per
  operation unless an existing governed batch contract explicitly covers several.
- Preserve current response shapes for no-vault and single-vault callers unless additive context
  provenance is required.

## Acceptance Criteria

- [ ] Two production API sessions read different vaults concurrently without cross-talk or global
  mutation.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_two_sessions_use_distinct_vaults_without_cross_talk`
- [ ] Production retrieval over several bindings preserves source vault and context generation on
  every result and cache lookup.
  - Verify: `tests/retrieval/test_multi_vault_retrieval.py::test_production_retrieval_preserves_binding_provenance`
- [ ] Production capture/governed-write paths require one explicit authorized target and record
  vault/context provenance in their receipt.
  - Verify: `tests/api/test_multi_vault_governed_writes.py::test_capture_uses_explicit_authorized_target_and_receipt`
- [ ] Invalid or unauthorized request selection returns the explicit error/picker contract and
  never serves default, last-active, CWD, or another binding.
  - Verify: `tests/api/test_multi_vault_request_fail_closed.py::test_invalid_selection_never_falls_back`
- [ ] Request-bound production code cannot introduce new direct global vault resolution outside
  named compatibility adapters.
  - Verify: `tests/architecture/test_multi_vault_context_boundaries.py::test_request_consumers_use_context_seam`

## Out of Scope

- Watcher/worker lifecycle, UI switcher #2566, registry/default/dimension storage, or removing all
  compatibility adapters.

## How to Verify (Pre-Merge)

- `pytest -q tests/integration/test_multi_vault_request_isolation.py tests/retrieval/test_multi_vault_retrieval.py tests/api/test_multi_vault_governed_writes.py tests/api/test_multi_vault_request_fail_closed.py tests/architecture/test_multi_vault_context_boundaries.py`
- `ruff check app tests`

## Restart / Durability Posture

Request contexts are not durable. Durable effects remain the existing governed content writes and
receipts, now carrying binding/generation provenance. After restart, clients resolve a fresh
session/default context and never inherit an unrecorded process selection.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/contracts/ACTIVE_CONTEXT_SET.md`
- `docs/ARCHITECTURE.md`

## Related GitHub Issues

Create one child under #2143 after MVR-03. Terra/high is acceptable for the mechanical call-site
migration once the Sol-reviewed seam is fixed; escalate to Sol/high on any authority or cache
isolation ambiguity. #2566 remains the separate downstream UI issue.
