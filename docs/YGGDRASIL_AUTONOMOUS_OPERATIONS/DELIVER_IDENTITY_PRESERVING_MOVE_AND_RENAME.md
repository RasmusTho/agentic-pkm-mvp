---
name: Deliver Identity-Preserving Move and Rename
description: Add governed placement changes that preserve artifact identity and refuse collisions or stale generations
task_id: AUTOOPS-05
github_issue: 5334
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Identity, path, and placement"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-02, AUTOOPS-04]
depends_on: [ENFORCE_OPERATION_EXECUTION_KERNEL.md, CONSOLIDATE_CREATE_AND_EDIT_OPERATIONS.md]
can_parallelize_with: []
---

# Deliver Identity-Preserving Move and Rename

State: AUTOOPS-05 source implementation, composed directly and dormant. Authenticated installation
and the pre-05C activation seal remain with #5352/#3861; this slice does not accept the parent capability.

## Purpose

Let humans and agents change artifact placement or display name without changing identity or clobbering data.

## What This Task Does

Implement owner-native move and rename handlers with destination reservation, expected generation,
collision refusal, stable ID preservation, projection convergence, and compensating recovery.

## Concretely

```text
artifact.move(id="a-17", destination="projects/x", expected_version=8)
  -> reserve -> owner move -> verify identity -> converge projections -> receipt
```

## Why This Matters

Path-based mutation makes references brittle and can turn a harmless rename into data loss.

## Acceptance Criteria

- [ ] Move and rename preserve stable artifact identity and update locator projections atomically or recoverably.
  Verify: `tests/operations/test_placement_operations.py::test_move_and_rename_preserve_identity_and_converge_locators`
- [ ] Destination collision, stale generation, and cross-vault scope mismatch fail before clobbering.
  Verify: `tests/operations/test_placement_operations.py::test_placement_refuses_collision_stale_generation_and_scope_mismatch`
- [ ] Failure after reservation leaves the original authoritative and supports idempotent recovery.
  Verify: `tests/operations/test_placement_operations.py::test_partial_move_preserves_original_and_recovers_idempotently`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_placement_operations.py`
- `ruff check app tests`

## Out of Scope

- Cross-vault copy semantics, archive transitions, user-interface controls, or arbitrary filesystem moves.

## Restart / Durability Posture

Reservation, generation, terminal receipt, and recovery state survive restart. The source remains
authoritative until destination activation is verified.

## Implemented owner boundary

`app/operations/placement_operations.py` binds `artifact.move` and `artifact.rename` to
`app/knowledge/placement.py::KnowledgePlacementOwner`. The trusted composition binds one canonical
selected-vault root, immutable context/generation, actor, stable artifact ID and current source
locator. Operation arguments cannot select another root, owner or principal. The owner rechecks
WSP context, nested-vault membership, parent identities, WriteGuard and the GOV token binding at
the filesystem effect seam. The trusted composition must supply current-context and current
delegation/policy validators; both execution and recovery revalidate them before effects. Kernel
admission still owns bounded delegation and policy.

This bounded interface supports ordinary rewritten Markdown human notes with an existing identity.
It refuses retained Sources, append-only/control paths, hidden/system paths, companions and Canvas
chat-session artifacts. Rename changes one filename within its current parent; move takes one full
vault-relative destination. Both preserve every source byte, inode, access metadata, stable ID and
origin stamp. Display-title/frontmatter edits remain a separate owner-governed operation.

Source generations include the exact inode, content digest, size, modification time, permission
mode and owner. An absent-destination generation binds the canonical relative path, selected root and
destination parent inode. An existing destination always conflicts; no suffix allocation or
overwrite option exists.

## Supported filesystem assumptions

Direct composition must explicitly qualify `filesystem="local-posix-v1"`: a single local Linux or
macOS filesystem that honors regular-file hardlinks, directory-relative no-follow opens,
no-replace rename, advisory `flock`, file `fsync` and directory `fsync`. A bounded probe exercises
those mechanics in private recovery storage before any source-name effect. Cross-mount moves,
network/sync-provider filesystem durability, aliased roots/parents, initially hardlinked sources,
and filesystems without these mechanics are unsupported and fail closed. No fallback uses
`shutil.move`, copy-and-delete, replacement rename, or an Obsidian CLI command.

The selected directory topology and private owner-controlled recovery namespace must remain stable
during an effect. Participating placement owners share the same vault lock. Concurrent human leaf
edits/replacements and destination creation are handled by generation/identity checks and no-clobber
mechanics; privileged/same-user tampering with private recovery evidence or uncoordinated directory
reparenting is outside the supported storage contract. Each seam reopens and checks the current
root/parent route; detected topology drift stops recovery rather than guessing another root.

The fixed private `.pkm-placement/` directory contains per-request placement intents, reservations,
phase records and GOV/source receipts. It is specific recovery evidence for this operation, not a
new artifact registry, append journal, source-identity authority or artifact-retention policy. Atomic
record replacement, file and parent-directory synchronization precede each subsequent phase. Source
bytes are synchronized and retained by a private hardlink before publication. Private byte links
are removed only after the source effect and AuthorityReceipt are recorded and a live destination
inode is verified; interrupted cleanup remains explicitly recoverable.

## Finite transition and failure matrix

| Durable phase / failure | Authority and retained evidence | Allowed continuation |
| --- | --- | --- |
| Before reservation: unsupported filesystem, missing authority/context, wrong identity, stale source/absent-destination generation, collision, cross-vault or unsafe path | Original untouched; no source effect acknowledged | Typed refusal; changed intent uses a new request ID |
| `reserved`: exact intent, authority, generations and parent identities synchronized | Original source authoritative; destination reserved among participating owners | Explicit recovery may retain the exact original inode if source and destination preconditions still agree |
| `prepared`: synchronized original hardlink, source generation verified | Original source authoritative; retained representation survives restart | No-clobber link publication of that retained inode; a foreign destination remains untouched |
| Link returned ambiguously, phase still `prepared` | Source remains authoritative; destination may contain the exact retained inode | Reconcile exact inode/generation; equal bytes at a different inode are insufficient; never overwrite a winner |
| `activated`: destination identity/generation verified and phase synchronized | Destination is authoritative; original source still retained | Record retirement intent, then capture the source name with no-replace rename into private recovery storage |
| `retiring`: crash before/after source capture | Destination and retained original identify the effect; a captured source is inspectable | Resume only when exact source/retired-name evidence proves the transition; missing source alone is never success |
| Source replacement wins the retirement syscall | Expected artifact remains retained; raced replacement is retained separately | Restore the replacement only with no-replace semantics; preserve a second winner; return recovery-required |
| Destination/source/parent generation changes, malformed evidence, unavailable fsync or receipt persistence | Preserve all observed entries and any known receipt; no false success | Recovery-required; inspect the same request's durable evidence and current authority before continuation |
| `committed`: source effect and GOV AuthorityReceipt synchronized | Destination owns the stable identity; old source locator retired | Clean exact private links idempotently, return the same receipt; source is never applied again |
| Locator/Store/index/link lag | Unchanged destination bytes and durable old/new locator receipt remain authoritative | `convergence_pending` with explicit source-backed repair evidence; existing ingest/projection owners rebuild from the destination |

Ordinary operation/kernel replay returns its recorded observation and never retries a pending move.
The dormant `reconcile_placement_operation` seam explicitly reconciles the same immutable placement
intent under current server authority. Recovery does not rewrite a historical kernel observation;
callers retain its recovery reference and inspect the HKA receipt. A committed source remains
committed if a projection is unavailable.

The current compatibility `vault_sync.update_path` uses the legacy binding and is not installed as
a new context-aware writer by this slice. The existing source-backed ingest path is the repair
owner; the real-path test replays the moved/renamed source and proves stable Store and companion
locators converge. Source delivery alone installs no watcher, HTTP, GUI, MCP or singleton and
makes no automatic projection-convergence claim. #4659's independent append mechanism and #4932's
Canvas authority stay with their existing owners.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`

## Related GitHub Issues

AUTOOPS-02/#5331 and AUTOOPS-04/#5333 are delivered prerequisites. #5334 owns this placement source
implementation. Parent #5329 retains integrated acceptance; #5352/#3861 retain activation. TCD hint:
`fresh_issue_agent`, helper budget 1, strong reasoning due to data integrity and concurrency.
