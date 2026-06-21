State: Target-state contract stub; current store abstractions are transitional evidence, not full target implementation.
Doc role: Contract stub
Authority: Owns PDM store resolution and persistence mechanics boundary.
Owner subsystem: PDM - Persistence & Data Management
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# StorePort

## Purpose

Keep storage technology from becoming architecture by routing persistence through PDM-owned store resolution, migration, backup, restore, and lifecycle mechanics.

## Inputs

- Store request from state-owning subsystem.
- Durable or rebuildable classification.
- Environment/channel/topology context.
- Migration plan or schema version.
- Backup/restore requirement.

## Outputs

- Store binding.
- Migration result.
- Backup/restore report.
- Store health and lifecycle status.
- Durable/rebuildable classification evidence.

## Commands

- Resolve store.
- Open store binding.
- Migrate schema.
- Backup.
- Restore.
- Compact.
- Check health.

## Queries

- Which store should this owner use?
- What is the migration state?
- Is the store durable or rebuildable?
- What recovery posture applies?

## Events

- `store.resolved`
- `store.migrated`
- `store.backed_up`
- `store.restored`
- `store.health_changed`

## Invariants

- State-owning subsystems own semantics; PDM owns storage mechanics.
- No private DSN/store construction outside PDM-owned paths.
- Durable and rebuildable stores are classified explicitly.
- Migrations are visible and attributable.

## Allowed Producers

- HKA, GOV, MEM, DRI, SFC, EXE, OEF requesting persistence mechanics.
- Operator/configuration inputs through approved settings paths.

## Allowed Consumers

- State-owning subsystems through StorePort, OEF health/trace views, SFC replication where storage state participates.

## Forbidden Use

- Do not put ontology or authority semantics in table names.
- Do not let storage backend choice define subsystem identity.
- Do not bypass PDM for migrations or persistent connection resolution.

## Failure Modes

- Storage leak.
- Schema names become ontology.
- Store lifecycle differs silently by caller.

## Transitional Implementation Notes

Existing ObjectStore, VectorIndex, RelationIndex, DB outbox, and other store interfaces should be mapped to StorePort classes during implementation slices before wider storage replacement work.

## Open Questions

- Which StorePort abstractions are sufficient to prevent storage leakage without hiding necessary operational detail?
- Which existing stores should be classified durable versus rebuildable first?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/ARCHITECTURE.md`
- `docs/DB_SCHEMA.md`
- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`
