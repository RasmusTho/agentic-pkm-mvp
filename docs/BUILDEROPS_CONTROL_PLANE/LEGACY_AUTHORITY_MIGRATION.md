---
name: Legacy Authority Migration
description: Inventory and deterministically import every BuilderOps and dispatcher legacy authority.
task_id: BCP-03
github_issue: 3789
source_anchor: docs/BUILDEROPS_CONTROL_PLANE/README.md :: Cross-task invariants / partial-failure safety
parent_capability: BuilderOps independent control plane
prerequisites: [BCP-01]
depends_on: [POSTGRES_TRANSACTION_KERNEL.md]
can_parallelize_with: [BCP-02]
---

# Legacy Authority Migration

Delivery status: implemented in the development baseline by #3789/PR #3929
(`app/builderops/control_plane/legacy_migration.py`; mechanism only). Not deployed
or authoritative until the BCP-06 cutover; remote-host environment snapshots are a
recorded limitation (env-less hosts derive default paths only and are listed in
the preflight receipt).

## Purpose

Authority-bearing state currently exists in CWD/worktree-local BuilderOps SQLite (including the
CKM/Capability Evidence Graph tables written through the same store; ADR-0062 A3), dispatcher
SQLite/JSONL, file-first model inquiries/promotions, and epic-run JSON. Issue #3686 and PR #3695
prove path fragmentation; their host-stable SQLite destination is superseded, but their discovery and
host-identity lessons remain migration inputs.

The dispatcher store fragments the same way, and this is verified live rather than inferred. On
2026-07-29 Demerzel carried two dispatcher stores simultaneously, because
`app/dispatcher/config.py :: load_paths` falls through to `_default_state_dir`, which resolves the
state directory via `discover_primary_worktree(cwd=...)`:

| Checkout | Store | Live tasks |
| --- | --- | --- |
| `~/workspace` | `/Volumes/ColimaT7/workspace-root/runtime/dispatcher/dispatcher.sqlite3` | 431 |
| `~/agentic-pkm-builderops` | `~/agentic-pkm-builderops/runtime/dispatcher/dispatcher.sqlite3` | 27 |

The two are not views of one store: validating the same Signboard board against the first reported
zero cards absent, against the second 378. A `export-signboard --prune-absent` run from the second
checkout deleted 404 live cards; the board was rebuilt from the owning store, and #4370 (PR #4402,
merge `168edbe2`) added a store-ownership stamp so a mismatched prune now refuses.

This is the #3686 defect class one store over, and it is a concrete acceptance case for the
worktree-enumeration coverage this task already requires: an inventory that finds only the dispatcher
store belonging to the invoking checkout would silently omit the other, along with every task and
event recorded in it.

## What This Task Does

- derive an expected-source manifest from every repo-owned legacy producer/default-path rule, then
  enumerate the authorized MacBook and Demerzel hosts, registered Git worktrees, container mounts/
  volumes, automation configuration, and host-stable candidates against that manifest;
- freeze each source, record path/host/user/worktree, schema, size, timestamps, content hash, and
  writer status, and reject stale/foreign inventory acknowledgement;
- create versioned read-only adapters and deterministic normalized identities/provenance;
- derive `RepoRef`, scope, and stack only from recorded source evidence, registered worktree/repo
  identity, or an acknowledged deterministic mapping; quarantine evidence-only ambiguity and require
  authority-bearing ambiguity to be resolved or converted to duplicate-preventing tombstones;
- dry-run and import tasks/events/records/attempts/idempotency/artifact references/receipts —
  including the CKM/CEG tables (ADR-0062 A3), whose schema may keep growing until the freeze and
  must stay import-coverable — while reporting counts, deduplication, conflicts, omissions,
  quarantine, and tombstones;
- expire/tombstone all legacy live leases and create a new PostgreSQL authority epoch/fencing base;
- make import idempotent and restart-safe without mutating source files; and
- produce machine-readable preflight, dry-run, import, and reconciliation receipts consumed by BCP-06.

## Concretely

Given the fixed cutover host set, the migration command derives its expected roots and source classes
from producer/default-path inventory plus live Git/Docker/automation enumeration. The operator may
authorize access but cannot omit a producer or registered root. The command emits a coverage manifest
and hash, accepts a host/user/freshness-bound acknowledgement, runs a no-write dry import, and
produces a reconciliation ledger. Re-running the same inputs returns the same normalized result;
missing roots, changed inputs, or authority-bearing conflicts without resolved/tombstoned replay
protection block with explicit evidence.

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
- Conflicting equal identities never use last-write-wins. Evidence-only conflicts may remain plain
  non-authoritative quarantine. Authority-bearing conflicts block cutover until evidence-resolved or
  represented by a non-authoritative tombstone that preserves source hashes, reserves legacy
  identity/idempotency/operation keys, rejects retry as manual conflict, and cannot authorize an
  effect.
- No legacy lease becomes a live PostgreSQL lease.
- Existing immutable inquiry artifacts may remain external by hash, but authoritative identity,
  state, promotion, and receipts import into PostgreSQL.
- Unknown/ambiguous repo provenance is never defaulted from CWD or import target. Plain quarantine is
  limited to evidence-only records. Authority-bearing ambiguity blocks cutover until evidence-
  resolved or converted into the duplicate-preventing tombstone form; a possible prior external
  effect must be reconciled against GitHub before any successor operation.
- Import is not production cutover and does not disable writers; BCP-06 owns the freeze window.

## Acceptance Criteria

- [x] Static producer/default-path inventory plus MacBook/Demerzel Git-worktree, Docker-volume/mount,
  automation, and host-path enumeration proves the expected source/root universe; omitted or
  inaccessible expected coverage blocks and acknowledgement binds host/user/freshness/manifest hash.
  Verify: `tests/builderops/control_plane/test_legacy_inventory.py::test_producer_derived_inventory_covers_hosts_worktrees_containers_and_automations`.
- [x] Re-running an unchanged import is idempotent, while a source changed after freeze fails hash
  verification and imports nothing further.
  Verify: `tests/builderops/control_plane/test_legacy_import.py::test_import_is_restart_safe_and_rejects_changed_source`.
- [x] Equal authority-bearing identities with divergent content block cutover rather than using
  last-write-wins or plain quarantine; activation becomes eligible only after evidence resolution or
  a non-authoritative tombstone reserves all legacy identity/idempotency/operation keys and makes
  replay fail closed.
  Verify: `tests/builderops/control_plane/test_legacy_import.py::test_conflicting_identity_requires_resolution_or_duplicate_preventing_tombstone`.
- [x] Legacy live leases import only as expired/tombstone evidence and cannot authorize mutation in
  the new epoch.
  Verify: `tests/builderops/control_plane/test_legacy_import.py::test_live_legacy_leases_do_not_cross_authority_epoch`.
- [x] Inquiry/epic-run identities, transitions, promotions, and receipts are represented in
  PostgreSQL with content-hash references to immutable artifacts and no file-only terminal state.
  Verify: `tests/builderops/control_plane/test_legacy_artifact_import.py::test_file_first_authority_imports_envelope_and_receipts`.
- [x] CKM/Capability Evidence Graph tables (ADR-0057 substrate, ADR-0062 A3) are inventoried and
  imported with the same identity/provenance discipline, covering any schema additions made between
  spec acceptance and freeze.
  Verify: `tests/builderops/control_plane/test_legacy_import.py::test_ckm_ceg_tables_are_inventoried_and_imported`.
- [x] Legacy `RepoRef`/scope/stack is backfilled only from evidence-bound mappings. Evidence-only
  ambiguity may remain plain non-authoritative quarantine; authority-bearing ambiguity must be
  evidence-resolved or duplicate-preventing tombstoned and cannot authorize a lease, effect,
  promotion, or merge.
  Verify: `tests/builderops/control_plane/test_legacy_import.py::test_authority_ambiguity_requires_resolution_or_duplicate_preventing_tombstone`.
- [x] A reconciliation receipt accounts for every expected producer/root and every source item as
  imported, deduplicated, evidence-quarantined, duplicate-preventing tombstoned, explicitly missing/
  inaccessible, intentionally excluded, or archived, and cutover rejects any unresolved coverage or
  authority-replay gap.
  Verify: `tests/builderops/control_plane/test_legacy_reconciliation.py::test_reconciliation_accounts_for_expected_universe_and_blocks_coverage_gaps`.

## Out of Scope

- switching clients to the API;
- deleting/archive-moving legacy sources;
- Product route removal; and
- resolving quarantined semantic conflicts without evidence.

## How to Verify (Pre-Merge)

- construct fixtures for omitted caller roots, multiple worktrees, host/container path divergence,
  unmounted/inaccessible volumes, ambiguous/missing repo provenance, stale acknowledgements, partial
  imports, and source mutation;
- run importer twice and compare database/result hashes;
- exercise the verified Demerzel two-dispatcher-store case from Purpose: an inventory run from one
  checkout must still enumerate the dispatcher store belonging to the other, and the reconciliation
  receipt must account for both rather than reporting the invoking checkout's store as the universe;
  and
- preserve #3686/PR #3695 evidence in the migration receipt.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- issue #3686 / PR #3695

## Related GitHub Issues

- [#3789](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3789), blocked on BCP-01.
- Reconciles issue #3686 / PR #3695 as discovery evidence with a superseded target.
- [#4370](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4370) (closed by PR #4402) records the
  verified Demerzel two-dispatcher-store condition described in Purpose. It shipped a guard at the
  projection layer; the underlying CWD-derived fragmentation is this task's to migrate.
