---
name: Thread Scope, Sphere, and Identity Through Runtime Paths
description: Specify where the separated context dimensions enter, transform, and exit runtime surfaces.
task_id: SSI-02
source_anchor: docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md :: Priority 2b — Scope, sphere, and situated identity as distinct properties (v6.0 enabling)
parent_capability: Scope, sphere, and situated identity as distinct properties
prerequisites: [SSI-01]
depends_on: [DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md]
can_parallelize_with: [EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS]
---

# Thread Scope, Sphere, and Identity Through Runtime Paths

## Purpose

Define a bounded runtime threading map so separated context dimensions survive through ingest/orchestrator/panel paths without semantic collapse.

## What This Task Does

- Enumerates runtime entrypoints where context is read.
- Enumerates transformation points where context must preserve dimension separation.
- Enumerates output surfaces where context dimensions must remain explicit.

## Concretely

- Add path map for watcher/orchestrator/panel/receipts surfaces.
- Add explicit "must preserve" checkpoints and failure modes.
- Add compatibility notes for incremental rollout.

## Why This Matters

Without a threading map, implementation can partially preserve dimensions in one path and lose them in another, creating hidden regressions.

## Acceptance Criteria

- [ ] Runtime path map names entry, transform, and output points that touch context semantics.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`.
- [ ] Each path stage includes preservation checkpoints for scope/sphere/identity separation.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`.
- [ ] Incremental rollout and compatibility notes are explicit.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`.

## How to Verify (Pre-Merge)

- `rg -n "entry|transform|output|checkpoint|compatibility" docs/SCOPE_SPHERE_SITUATED_IDENTITY/THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md`
- Reviewer confirms each AC has explicit corresponding passages.

## Out of Scope

- Implementing runtime code.
- Updating owner-doc support claims.

## Related Docs

- `docs/ARCHITECTURE.md`
- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md`

## Related GitHub Issues

- Parent: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/PARENT_FEATURE_ISSUE.md`
- Follow-up implementation issue: to be created from this task spec.
