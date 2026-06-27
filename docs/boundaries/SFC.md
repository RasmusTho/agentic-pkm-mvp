# Boundary: SFC — Synchronization, Federation & Consensus

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** SFC owns **replicated topology over time** — distributed state across
nodes. (WSP owns current situated context.) Sync preserves boundaries; it never silently resolves
semantic authority.

## Purpose

Own synchronization, replication, federation, node identity, causal ordering, conflict handling, and
convergence — moving state across nodes without changing its meaning, scope, or authority.

## Owns

- Sync, replication, federation; node identity (`Node`), replica identity (`Replica`).
- Causal ordering, conflict detection/classification/staging, convergence strategy, distributed receipt continuity.

## Does not own

- Current situated context → **WSP**.
- Semantic conflict **resolution** without governance → **GOV** decides.
- Permission / authority → **GOV**; sibling visibility → governed by scope + `CrossScopeFlow`.

> **Ownership-drift rule.** SFC may *detect and stage* conflicts; resolving an authority-bearing
> semantic conflict is a GOV decision. SFC does not promote, rescope, or last-writer-wins over meaning.

## Inputs

- Topology, replica state, sync deltas, node identity, GOV conflict policy.

## Outputs

- `ReplicationEnvelope`, conflict candidates, convergence state, `sync_state` transitions.

## Calls allowed

- **WSP** (topology), **PDM** (stores), **GOV** (conflict policy / resolution), **HKA**/**SIP** (identity references).

## Calls forbidden

- **Silent semantic resolution** — must not resolve authority-bearing conflicts without GOV policy.
- **Granting authority/permission** — sync is not a source of new authority.
- **Sibling sharing** — parent aggregation does not make sibling/descendant scopes mutually visible.

## Required metadata

SFC **owns `sync_state`** (`local_only`/`pending`/`synced`/`conflicted`/`diverged`) and preserves
`scope_binding`, `authority_state`, `source_role`, `provenance_ref` across replicas unchanged. Sync
never infers authority, scope, or evidence from replication status.

## Policy obligations

- Authority-bearing conflict resolution requires a GOV-authorized policy for that conflict class.
- Cross-scope/sibling visibility requires a typed `CrossScopeFlow`; replication alone grants nothing.

## Provenance obligations

- Replication preserves identity anchors and provenance exactly; convergence carries distributed receipts.
- A conflict is staged with provenance for governed resolution, not silently merged.

## Invariants owned

- Sync preserves boundaries (matrix #14).
- Parent aggregation is not sibling sharing (matrix #11).
- Sync cannot silently resolve semantic authority conflicts (matrix #14, with GOV).

## Failure modes

- **Sync-as-authority:** last-writer-wins resolving meaning without governance.
- **Sibling leak:** parent aggregation exposing sibling scopes.
- **Rescope-on-replicate:** replication changing an artifact's scope/authority.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `sync_preserves_boundaries`
- `parent_aggregation_not_sibling_sharing`
- `sync_conflict_requires_governance`

## Related ADRs

- ADR-0020 (SFC single-node upgrade path).

## Related schemas/contracts

- existing `ReplicationEnvelope` (SBS Part 5); metadata bundle (`sync_state`) — [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544).

## Related issues

- Charter: [#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2543) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
