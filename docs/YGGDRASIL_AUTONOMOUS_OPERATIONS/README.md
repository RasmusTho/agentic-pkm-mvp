State: Filed target-state capability specification. Parent #5329 is the blocked validation hub; child Issues #5330-#5340 own delivery. No runtime support is claimed by this directory.

# Yggdrasil Autonomous Operations

This directory specifies the missing cross-surface operations capability defined by
`docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`. It turns the accepted architecture
direction into bounded implementation contracts for one shared operations layer, a complete human
flow in Companion, and a complete agent flow through MCP v2. ADR-0061's five-tool MCP v1 profile
remains a compatible, independently deliverable subset.

## Capability Boundary

The capability coordinates existing domain owners; it does not replace them. It normalizes request,
outcome, conflict, receipt, and recovery semantics while StorePort, governed writes, archival,
indexing, links, and multi-vault context remain authoritative in their existing subsystems.

## Implementation Tasks

1. [Establish Operation Contracts](ESTABLISH_OPERATION_CONTRACTS.md) — #5330 (`agent:ready` at filing)
2. [Enforce the Operation Execution Kernel](ENFORCE_OPERATION_EXECUTION_KERNEL.md) — #5331
3. [Consolidate Discovery and Read Operations](CONSOLIDATE_DISCOVERY_AND_READ_OPERATIONS.md) — #5332
4. [Consolidate Create and Edit Operations](CONSOLIDATE_CREATE_AND_EDIT_OPERATIONS.md) — #5333
5. [Deliver Identity-Preserving Move and Rename](DELIVER_IDENTITY_PRESERVING_MOVE_AND_RENAME.md) — #5334
6. [Deliver Classification, Tagging, and Ordering](DELIVER_CLASSIFICATION_TAGGING_AND_ORDERING.md) — #5335
7. [Compose Archive and Restore Operations](COMPOSE_ARCHIVE_AND_RESTORE_OPERATIONS.md) — #5336
8. [Deliver Safe Batch Execution and Recovery](DELIVER_SAFE_BATCH_EXECUTION_AND_RECOVERY.md) — #5337
9. [Design the Human Operations Flow](DESIGN_HUMAN_OPERATIONS_FLOW.md) — #5338 (`agent:ready` at filing)
10. [Implement the Companion Operations Workspace](IMPLEMENT_COMPANION_OPERATIONS_WORKSPACE.md) — #5339
11. [Expose and Prove MCP v2 Parity](EXPOSE_AND_PROVE_MCP_V2_PARITY.md) — #5340

## Execution Order

Use the numbered order above as the flat pickup order. Task 9 may run beside Tasks 1-3 because it
owns design artifacts only. Task 7 waits for the governed archival owner chain rather than
reimplementing it. Task 11 is the terminal cross-surface proof and parent-closure handoff.

## Cross-Task Invariants / Interaction Safety

- An operation is terminal only when its owner-native effect and receipt agree; a recorded intent
  with a failed downstream effect remains recoverable, never successful.
- Stable artifact identity survives placement and naming changes. A path is locator data, not
  identity authority.
- GUI, HTTP, and MCP adapters cannot add write authority, retry an ambiguous effect, or invent a
  success that the operation kernel did not return.
- Source mutation and Store/index/link convergence are separate observable phases. Projection lag
  is explicit and repairable; it never rolls back an already committed source mutation silently.
- A batch cannot hide partial completion. Each item has an outcome and the aggregate result names
  completed, refused, conflicted, and recoverable work.
- Delegated scope is bounded once by operation family, vault/workspace, object set or selector, and
  policy ceiling. Crossing that boundary returns a typed refusal rather than a new implicit prompt.
- Recovery is idempotent and generation-aware. Replaying a completed effect returns its existing
  receipt; replaying stale intent cannot overwrite newer state.

Partial-failure walkthrough: if a source write commits but index convergence fails, the kernel
returns a recoverable success-with-lag receipt and schedules or exposes bounded repair. If a move
reserves a destination but cannot activate it, the original remains authoritative and retry uses the
same operation identity. If a batch stops mid-run, completed items retain their receipts and pending
items remain unexecuted. If an adapter disconnects after an ambiguous write, it queries the operation
receipt before any retry.

## Capability-Level Acceptance

- [ ] The operation matrix in the governing contract has one owner-native implementation path and
      the same typed outcome semantics from direct, GUI, HTTP, and MCP v2 entrypoints.
- [ ] The Companion human flow supports discovery, scoping, one-time bounded delegation, progress,
      receipts, conflicts, and recovery without requiring a per-file confirmation loop.
- [ ] MCP v2 supports the same operation families and policy limits while MCP v1 remains compatible.
- [ ] Cross-surface conformance, failure injection, restart, concurrency, and recovery evidence is
      recorded on the parent validation issue before owner docs claim support.

## Relationship to GitHub Issues

`PARENT_FEATURE_ISSUE.md` mirrors blocked validation hub #5329. Each task file maps to one
bounded child issue through its `github_issue` frontmatter. GitHub owns live lifecycle state; this
directory owns stable target behavior and verification shape.

## Owner-Doc Promotion

Only the terminal parity task may hand the parent to capability acceptance. Once its current-SHA
evidence is accepted, update current-state owner docs and this directory's State line in one
post-acceptance docs change. Until then, all language here is target state.
