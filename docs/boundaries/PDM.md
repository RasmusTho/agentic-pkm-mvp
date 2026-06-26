# Boundary: PDM — Persistence & Data Management

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** PDM says **how things are stored**. (HKA says what is durable; SIP
says how it means.)

## Purpose

Own storage technology abstraction and data-management mechanics so that storage can be replaced
without changing meaning, identity, or authority.

## Owns

- Storage abstraction and store ports (`StorePort`), `VaultRoot` storage topology.
- Migrations, backup, restore, snapshots, compaction, encryption-at-rest mechanics.
- Physical schemas, data lifecycle mechanics, store health, durable-vs-rebuildable store classification.

## Does not own

- Meaning / ontology → **SIP**.
- Durable-knowledge authority → **HKA**; authority transitions / policy → **GOV**.
- Retrieval ranking → **RCA**; memory promotion → **MEM**/**GOV**.
- Semantic conflict resolution → **SFC** stages, **GOV** decides; **never PDM**.

> **Ownership-drift rule.** A schema name is not an ontology term and a row is not an artifact. When
> meaning or standing is in question, defer to SIP/HKA/GOV — PDM stores bytes, it does not interpret them.

## Inputs

- Store/resolve/migrate/backup/restore requests from state-owning subsystems (HKA, GOV, MEM, DRI, SFC).
- Migration plans and lifecycle/retention commands.

## Outputs

- `StorePort` bindings, migration results, backup/restore reports, store-health signals.

## Calls allowed

- Serves **all state-owning subsystems** through store contracts (it is called, it does not drive semantics).

## Calls forbidden

- **Defining meaning** — must not encode ontology/policy/authority in schemas or infer them from storage shape.
- **Authorizing** — a persistence write is not an authority transition; PDM must not mint or imply `AuthorityReceipt`s.
- **Bypassing owners** — must not promote, rescope, or resolve semantic conflicts on its own.

## Required metadata

PDM **carries** the full [metadata bundle](../architecture/semantic-dimensions.md)
(`source_role`, `authority_state`, `evidence_role`, `scope_binding`, `sensitivity`,
`suppression_state`, `memory_state`, `sync_state`, `execution_state`) on persisted objects **without
defining or altering** any of it. It owns `vault_root_id` and storage location only.

## Policy obligations

- Enforce encryption/retention mechanics that GOV policy requires, but never make the policy decision.
- Preserve `suppression_state`/`sensitivity` at rest; honor deletion/tombstone as a mechanic, not as meaning-erasure.

## Provenance obligations

- Persist provenance/metadata intact; a storage backend change must round-trip the metadata bundle unchanged.
- Backups/restores preserve identity anchors and provenance exactly.

## Invariants owned

- Storage preserves but does not define meaning (matrix #12).
- Persistence writes are not authority transitions (matrix #9, #12).
- Storage backend changes must not change semantic identity (matrix #12, #16).
- Sync/replication through PDM stores preserves boundaries (matrix #14, with SFC).

## Failure modes

- **Storage leak:** subsystems building DSNs / touching tables outside PDM ports — detect direct table refs.
- **Schema-as-ontology:** schema names appearing as semantic terms in subsystem contracts.
- **Store-as-truth:** treating a persisted row as authoritative meaning without SIP/HKA/GOV.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `storage_not_meaning`
- `metadata_bundle_required`
- `sync_preserves_boundaries`

## Related ADRs

- ADR-0016 (contract-first, module-lazy SBS) — via [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549).

## Related schemas/contracts

- metadata bundle — [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544); existing `StorePort` concept (SBS Part 5).

## Related issues

- Charter: [#2541](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2541) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
