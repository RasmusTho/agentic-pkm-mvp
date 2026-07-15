---
name: Legacy Authority Migration
description: Inventory and deterministically import every BuilderOps and dispatcher legacy authority.
task_id: BCP-03
source_anchor: docs/BUILDEROPS_CONTROL_PLANE/README.md :: Cross-task invariants / partial-failure safety
parent_capability: BuilderOps independent control plane
prerequisites: [BCP-01]
depends_on: [POSTGRES_TRANSACTION_KERNEL.md]
can_parallelize_with: [BCP-02]
---

# Legacy Authority Migration

## Purpose

Authority-bearing state currently exists in CWD/worktree-local BuilderOps SQLite, dispatcher
SQLite/JSONL, file-first model inquiries/promotions, and epic-run JSON. Issue #3686 and PR #3695
prove path fragmentation; their host-stable SQLite destination is superseded, but their discovery and
host-identity lessons remain migration inputs.

## What This Task Does

- derive an expected-source manifest from every repo-owned legacy producer/default-path rule, then
  enumerate the authorized MacBook and Demerzel hosts, registered Git worktrees, container mounts/
  volumes, automation configuration, and host-stable candidates against that manifest;
- freeze each source, record path/host/user/worktree, schema, size, timestamps, content hash, and
  writer status, and reject stale/foreign inventory acknowledgement;
- create versioned read-only adapters and deterministic normalized identities/provenance;
- dry-run and import tasks/events/records/attempts/idempotency/artifact references/receipts while
  reporting counts, deduplication, conflicts, omissions, and quarantine;
- expire/tombstone all legacy live leases and create a new PostgreSQL authority epoch/fencing base;
- make import idempotent and restart-safe without mutating source files; and
- produce machine-readable preflight, dry-run, import, and reconciliation receipts consumed by BCP-06.

## Concretely

Given the fixed cutover host set, the migration command derives its expected roots and source classes
from producer/default-path inventory plus live Git/Docker/automation enumeration. The operator may
authorize access but cannot omit a producer or registered root. The command emits a coverage manifest
and hash, accepts a host/user/freshness-bound acknowledgement, runs a no-write dry import, and
produces a reconciliation ledger. Re-running the same inputs returns the same normalized result;
missing roots, changed inputs, or conflicts block with explicit evidence.

## Why This Matters

Moving only the most obvious SQLite file would repeat #3686 at a larger scale and silently discard
dispatcher, inquiry, epic-run, or worktree-local history. Cutover is safe only when all candidates
are accounted for.

## Source Anchors

- `docs/builderops/BUILDEROPS_VAULT_STORE.md :: Store Location`
- `docs/AGENT_ISSUE_DISPATCHER.md :: Current-State Honesty`
- `docs/development/BUILDER_CONTROL_PLANE.md :: Recovery Tools`

## SBS Impact

Builder System data-migration work. It moves operational orchestration authority only; product
knowledge, runtime data, and GitHub/repo delivery authority are unchanged.

## Constraints

- Producer/default-path inventory is the expected-source authority; discovery must cover every
  registered worktree, container mount/volume, automation path, and host-stable candidate on both
  cutover hosts. Caller-supplied roots may add scope but never subtract expected coverage.
- An expected missing or inaccessible root is an explicit blocking receipt, not silent absence.
- Source adapters are read-only and hash-verify before and after import.
- Conflicting equal identities are quarantined; timestamps or path order never silently choose a
  winner.
- No legacy lease becomes a live PostgreSQL lease.
- Existing immutable inquiry artifacts may remain external by hash, but authoritative identity,
  state, promotion, and receipts import into PostgreSQL.
- Import is not production cutover and does not disable writers; BCP-06 owns the freeze window.

## Acceptance Criteria

- [ ] Static producer/default-path inventory plus MacBook/Demerzel Git-worktree, Docker-volume/mount,
  automation, and host-path enumeration proves the expected source/root universe; omitted or
  inaccessible expected coverage blocks and acknowledgement binds host/user/freshness/manifest hash.
  Verify: `tests/builderops/control_plane/test_legacy_inventory.py::test_producer_derived_inventory_covers_hosts_worktrees_containers_and_automations`.
- [ ] Re-running an unchanged import is idempotent, while a source changed after freeze fails hash
  verification and imports nothing further.
  Verify: `tests/builderops/control_plane/test_legacy_import.py::test_import_is_restart_safe_and_rejects_changed_source`.
- [ ] Equal identities with divergent content are quarantined with provenance and block cutover
  rather than last-write-wins resolution.
  Verify: `tests/builderops/control_plane/test_legacy_import.py::test_conflicting_identity_is_quarantined_and_blocks_cutover`.
- [ ] Legacy live leases import only as expired/tombstone evidence and cannot authorize mutation in
  the new epoch.
  Verify: `tests/builderops/control_plane/test_legacy_import.py::test_live_legacy_leases_do_not_cross_authority_epoch`.
- [ ] Inquiry/epic-run identities, transitions, promotions, and receipts are represented in
  PostgreSQL with content-hash references to immutable artifacts and no file-only terminal state.
  Verify: `tests/builderops/control_plane/test_legacy_artifact_import.py::test_file_first_authority_imports_envelope_and_receipts`.
- [ ] A reconciliation receipt accounts for every expected producer/root and every source item as
  imported, deduplicated, quarantined, explicitly missing/inaccessible, intentionally excluded, or
  archived, and cutover rejects any unresolved coverage gap.
  Verify: `tests/builderops/control_plane/test_legacy_reconciliation.py::test_reconciliation_accounts_for_expected_universe_and_blocks_coverage_gaps`.

## Out of Scope

- switching clients to the API;
- deleting/archive-moving legacy sources;
- Product route removal; and
- resolving quarantined semantic conflicts without evidence.

## How to Verify (Pre-Merge)

- construct fixtures for omitted caller roots, multiple worktrees, host/container path divergence,
  unmounted/inaccessible volumes, stale acknowledgements, partial imports, and source mutation;
- run importer twice and compare database/result hashes; and
- preserve #3686/PR #3695 evidence in the migration receipt.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- issue #3686 / PR #3695

## Related GitHub Issues

- [#3789](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3789), blocked on BCP-01.
- Reconciles issue #3686 / PR #3695 as discovery evidence with a superseded target.
