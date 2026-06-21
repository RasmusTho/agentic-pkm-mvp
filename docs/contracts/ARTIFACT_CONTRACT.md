State: Target-state contract stub; current vault/companion artifact contracts remain current-state references.
Doc role: Contract stub
Authority: Owns target human artifact identity, origin, survivability, and lifecycle expectations for HKA.
Owner subsystem: HKA - Human Knowledge & Artifact Substrate
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# ArtifactContract

## Purpose

Protect durable human-authored and human-accepted knowledge artifacts so human knowledge survives loss of machine-generated artifacts.

## Inputs

- Human-authored artifact content.
- Human-accepted machine contribution.
- Source-at-entry and artifact-origin facts.
- Ownership markers: human, system, imported, agent-promoted.
- Durability class and lifecycle state.

## Outputs

- Human artifact identity.
- Portable representation.
- Artifact-origin provenance carried with or recoverable from the artifact.
- Lifecycle state and migration status.
- Source references for SIP/DRI/RCA/MEM projections.

## Commands

- Create artifact.
- Apply governed mutation.
- Accept machine contribution.
- Migrate representation.
- Export or recover artifact.

## Queries

- What is the human artifact identity?
- What origin facts must survive?
- Which representation is portable?
- Which projections can be rebuilt from this artifact?

## Events

- `artifact.created`
- `artifact.governed_mutation_applied`
- `artifact.machine_contribution_accepted`
- `artifact.representation_migrated`

## Invariants

- Human knowledge remains usable if machine artifacts disappear.
- Artifact-origin facts that must survive do not live only in SIP/DRI.
- HKA owns durable human artifact lifecycle, not storage backend mechanics.
- Human/system ownership markers are explicit.

## Allowed Producers

- HIX human creation/acceptance flows.
- GOV-approved mutation paths.
- EBF import/source adapters under HKA rules.

## Allowed Consumers

- SIP, DRI, RCA, MEM, CAO, HIX, GOV, SFC, OEF.

## Forbidden Use

- Do not store only derived semantic meaning in HKA without a human-readable/exportable representation.
- Do not let RCA, MEM, CAO, EXE, EBF, or HIX directly mutate HKA without GOV/HKA path.
- Do not use storage schema as artifact ontology.

## Failure Modes

- Derived representations contain non-rebuildable meaning.
- SIP becomes irreplaceable shadow store.
- UI state becomes authoritative.

## Transitional Implementation Notes

Current vault notes and companion notes are the main durable artifact surface. This target contract generalizes the artifact boundary beyond vault/Markdown while preserving human readability/exportability.

## Open Questions

- What minimum ArtifactContract supports no-vault operation while preserving human comprehensibility?
- Which artifact-origin facts must live inside the artifact versus in adjacent durable receipts?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md`
- `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
