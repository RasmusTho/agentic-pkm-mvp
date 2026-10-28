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

State: AUTOOPS-05 source implementation, composed directly and dormant. Authenticated operations
installation remains with #5352; delivered MVR-05C/#3861 context/ownership rules apply. This slice
does not accept the parent capability.

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
the filesystem effect seam. Every invocation requires the server-resolved full `ActiveContextSetV1`,
one selected `target_binding_id` and the existing instance `VaultRegistryStore`; no legacy/unbound
placement writer is installed. The owner checks the configured instance and current selected root,
binds its own DecisionToken through GOV, and enters the existing `context_bound_write_window` before
its vault lock. The principal read fence, host ownership fence and shared selected-binding lease
remain held through source, AuthorityReceipt persistence and cleanup. Callback policy checks only
narrow this authority; they cannot replace the context/window or widen the selected set.

Recovery revalidates the persisted token against the exact trusted typed snapshot and selected target
and re-enters the same current GOV effect window. JSON evidence cannot construct a new context.
Expired/revoked/stale/missing context, unbound token, wrong instance/root/selected target and retired
source ingress refuse. All new direct-composition producers and fixtures use the existing WSP/GOV
selection and instance owners; no bearer, default selection, registry, role or effect lease is minted
by the placement owner. Kernel admission still owns bounded delegation and policy.

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
Protected system/capture zones use the existing filesystem-aware overlap rules, including aliases
of an absent capture leaf. Descriptor walks also require exact directory-entry spelling for every
parent and existing source leaf, so case or Unicode lookup aliases cannot become another authority
path on normalization-insensitive or case-insensitive filesystems.

The fixed private `.pkm-placement/` directory contains per-request placement intents, reservations,
phase records and GOV/source receipts. It is specific recovery evidence for this operation, not a
new artifact registry, append journal, source-identity authority or artifact-retention policy. Atomic
record replacement, file and parent-directory synchronization precede each subsequent phase. Source
bytes are synchronized and retained by a private hardlink before publication. Private byte links
are removed only after the source effect and AuthorityReceipt are recorded and a live destination
inode is verified; interrupted cleanup remains explicitly recoverable.

Recovery treats observed names as effect evidence, never as proof of successful synchronization.
Every transition re-establishes its required durability barriers even when an earlier invocation
already created or moved the entry:

| Observed transition | Required barrier before advancing the durable phase |
| --- | --- |
| Private recovery root or transaction directory exists | Synchronize its parent after checking the private directory, including on reopen |
| Exact retained `original` link exists | Synchronize the retained file bytes and transaction directory before `prepared` |
| Exact published destination exists | Synchronize the destination directory before verified `activated` |
| Exact captured `retired` source exists | Synchronize both source and transaction directories before the source/GOV receipt becomes `committed` |
| Private cleanup names are already absent | Synchronize the transaction directory before recording `cleanup_complete` |

Unavailable pre-commit synchronization keeps the intent recoverable and cannot create an applied
AuthorityReceipt. A later cleanup synchronization failure keeps cleanup incomplete while preserving
the already committed source receipt. Once the barrier is available, explicit recovery reconciles
the same observed effect, re-establishes durability and completes without repeating the namespace mutation.

## Finite transition and failure matrix

| Durable phase / failure | Authority and retained evidence | Allowed continuation |
| --- | --- | --- |
| Before reservation: unsupported filesystem, missing authority/context, wrong identity, stale source/absent-destination generation, collision, cross-vault or unsafe path | Original untouched; no source effect acknowledged | Typed refusal; changed intent uses a new request ID |
| `reserved`: exact intent, authority, generations and parent identities synchronized | Original source authoritative; destination reserved among participating owners | Explicit recovery may retain the exact original inode if source and destination preconditions still agree |
| `prepared`: synchronized original hardlink, source generation verified | Original source authoritative; retained representation survives restart | No-clobber link publication of that retained inode; a foreign destination remains untouched |
| `publishing`: publication intent synchronized before the public link syscall | Source remains authoritative; public namespace effect is unknown until verified activation | Reconcile exact inode/generation; equal bytes at a different inode are insufficient; never overwrite a winner |
| Link/fsync/activation-phase persistence returned ambiguously, phase `publishing` | Source retained; destination may contain the exact retained inode | Report source effect `unknown` and locator/Store/index/link repair required; ordinary replay never re-enters the effect |
| `activated`: destination identity/generation verified and phase synchronized | Destination is authoritative; original source still retained | Record retirement intent, then capture the source name with no-replace rename into private recovery storage |
| `retiring`: crash before/after source capture | Destination and retained original identify the effect; a captured source is inspectable | Resume only when exact source/retired-name evidence proves the transition; missing source alone is never success |
| Source replacement wins the retirement syscall | Expected artifact remains retained; raced replacement is retained separately | Restore the replacement only with no-replace semantics; preserve a second winner; return recovery-required |
| Destination/source/parent generation changes, malformed evidence, unavailable fsync or receipt persistence | Preserve all observed entries and any known receipt; no false success | Recovery-required; inspect the same request's durable evidence and current authority before continuation |
| Explicit recovery loses authority before historical evidence is readable | No new effect is admitted; the earlier attempt may already have published or retired the source | Refuse continuation and report source effect `unknown` with repair inspection required; refusal cannot imply the historical effect was not applied |
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
makes no automatic projection-convergence claim. MVR-05C/#3861 is delivered through PR #6349; its
context/token/effect-window and source-retirement rules are reused rather than replaced. #4659's
independent append mechanism and #4932's Canvas authority stay with their existing owners.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`

## Related GitHub Issues

AUTOOPS-02/#5331 and AUTOOPS-04/#5333 are delivered prerequisites. #5334 owns this placement source
implementation. Parent #5329 retains integrated acceptance; #5352 retains operations-runtime
installation, while delivered #3861 owns current context/ownership rules. TCD hint:
`fresh_issue_agent`, helper budget 1, strong reasoning due to data integrity and concurrency.
