State: Canonical Yggdrasil traceability matrix. Docs-only control document for the architecture-foundation backlog (#2533–#2552); maps each load-bearing principle to its doc, ADR, ontology, dimensions, boundaries, contract, tests, and implementation issues. Does not claim shipped runtime behavior.
Doc role: Architecture / traceability control document
Authority: Owns the climb-back map from doctrine principle to implementation. For any invariant it answers: which doctrine principle, which ontology concepts, which semantic distinctions, which control boundaries, which contract/schema, which test/eval, and which issue. Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/architecture/functional-ontology.md`, `docs/architecture/semantic-dimensions.md`, `docs/architecture/cross-scope-flow.md`, and `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`. `TBD` marks an artifact that genuinely belongs to a future issue, not missing thinking.
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (principle → artifact mapping); subordinate to the docs it maps
Last reviewed: 2026-06-26
Last verified against: docs/foundation/00-yggdrasil-doctrine.md, docs/architecture/functional-ontology.md, docs/architecture/semantic-dimensions.md, docs/architecture/cross-scope-flow.md, docs/foundation/yggdrasil-architecture-context-packet.md, docs/SYSTEM_BREAKDOWN_STRUCTURE.md

# Yggdrasil Traceability Matrix

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
Stabilized SBS: [#2534](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2534) ·
Context packet: [#2553](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2553)

This matrix is the map from principle to implementation. It exists so future work can climb back up
from any technical piece to the doctrine that requires it — and so no contract becomes an orphan
whose rationale is lost. Read the [doctrine](../foundation/00-yggdrasil-doctrine.md) and the
[context packet](../foundation/yggdrasil-architecture-context-packet.md) first.

**How to read a row.** Pick a principle, then trace: which canonical doc states it → which ADR
records the decision → which [ontology](functional-ontology.md) concepts it uses → which
[semantic distinctions](semantic-dimensions.md) it protects → which Level 2 control boundaries own
it → which contract/schema will express it → which test/eval protects it → which issue implements
it. `TBD (#NNNN)` means the artifact belongs to a not-yet-delivered issue, not that the thinking is
missing.

**Conventions.** All `#NNNN` references are issues/epics in `RasmusTho/agentic-pkm-mvp`. ADR ids
refer to files under [`docs/adr/`](../adr/INDEX.md). Control boundaries (HKA, SIP, GOV, WSP, RCA,
MEM, CAO, EXE, DRI, PDM, SFC, OEF, CES) are defined in the
[System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) and the
[boundary register](SBS_BOUNDARY_REGISTER.md). This matrix is append-friendly: future implementation
issues add rows without restructuring it.

## Matrix

| # | Principle / finding | Canonical doc | ADR | Ontology concepts | Semantic distinctions | Control boundaries | Contract / schema | Required tests / evals | Implementation issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Similarity is not permission. | [cross-scope-flow](cross-scope-flow.md) | TBD (#2549) | `CrossScopeFlow`, `RetrievalResult`, `Relation` | `scope_binding` ≠ permission; `evidence_role` ≠ retrieve/cite right | RCA, GOV, WSP | `CrossScopeFlow` / `RetrievalResult` schema — TBD (#2544, #2548) | anti-contamination eval — TBD (#2551); xfail skeleton (#2552) | #2539, #2548, #2551 |
| 2 | Scope is frame, audience boundary, policy boundary, and provenance context. | [functional-ontology](functional-ontology.md), [doctrine](../foundation/00-yggdrasil-doctrine.md) | TBD (#2549) | `Scope`, `Sphere`, `Workspace`, `VaultRoot` | `scope_binding`, `sensitivity` | WSP, GOV, SIP | metadata bundle schema — TBD (#2544) | invariant registry — TBD (#2550) | #2537, #2538, #2544 |
| 3 | Provenance carries justification. | [functional-ontology](functional-ontology.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0018 | `ProvenanceEvent`, `Source`, `Claim` | `source_role`, `evidence_role` | SIP, GOV | metadata bundle schema — TBD (#2544) | invariant registry — TBD (#2550) | #2537, #2544 |
| 4 | Agent memory is noncanonical by default. | [semantic-dimensions](semantic-dimensions.md), [functional-ontology](functional-ontology.md) | ADR-0025 | `MemoryItem`, `Proposal` | `source_role`, `authority_state`, `memory_state` | MEM, GOV, HKA | `MemoryItem` contract — TBD (#2546) | invariant (#2550); eval (#2551) | #2538, #2546 |
| 5 | `source_role`, `authority_state`, and `evidence_role` are orthogonal. | [semantic-dimensions](semantic-dimensions.md) | TBD (#2549) | `Artifact`, `Claim`, `MemoryItem`, `Projection` | the three role dimensions are non-collapsible | SIP, GOV | metadata bundle schema — TBD (#2544) | invariant (#2550) + anti-contamination eval (#2551) | #2538, #2544, #2550, #2551 |
| 6 | Typed `CrossScopeFlow` replaces any global `general_knowledge` bypass. | [cross-scope-flow](cross-scope-flow.md) | TBD (#2549) | `CrossScopeFlow`, `Scope` | `source_role` (`general_knowledge` = eligibility, not bypass), `scope_binding` | GOV, RCA | `CrossScopeFlow` schema — TBD (#2544, #2548) | anti-contamination eval — TBD (#2551) | #2539, #2551 |
| 7 | Retrieval produces candidate evidence, not truth. | [cross-scope-flow](cross-scope-flow.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0024 | `RetrievalResult`, `Projection`, `Segment` | `evidence_role`, `authority_state` | RCA, GOV, SIP | `RetrievalResult` contract — TBD (#2548) | invariant registry — TBD (#2550) | #2548, #2550 |
| 8 | Projection is not evidence. | [functional-ontology](functional-ontology.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0018, ADR-0022 | `Projection`, `Segment` | `evidence_role` (default `non_evidence`), `authority_state` | DRI, OEF, GOV | `ContextEnvelope` contract — TBD (#2545) | anti-contamination eval — TBD (#2551) | #2537, #2538, #2545 |
| 9 | Authority transitions require governance and receipts. | [functional-ontology](functional-ontology.md), [doctrine](../foundation/00-yggdrasil-doctrine.md) | ADR-0017, ADR-0019 | `AuthorityReceipt`, `AcceptedArtifact`, `Commitment` | `authority_state` | GOV, HKA | `AuthorityTransition` contract — TBD (#2547) | invariant registry — TBD (#2550) | #2547, #2550 |
| 10 | Execution cannot authorize itself. | [functional-ontology](functional-ontology.md) | ADR-0019 | `ExecutionEffect`, `CapabilityGrant`, `AuthorityReceipt` | `execution_state`, `authority_state` | EXE, GOV | `AuthorityTransition` (#2547); existing `EXECUTION_REQUEST.md` | invariant registry — TBD (#2550) | #2537, #2547 |
| 11 | Parent aggregation is not sibling sharing. | [cross-scope-flow](cross-scope-flow.md) | TBD (#2549) | `Scope`, `CrossScopeFlow` | `scope_binding` | WSP, GOV | `CrossScopeFlow` schema — TBD (#2544) | anti-contamination eval — TBD (#2551) | #2539, #2551 |
| 12 | Storage preserves but does not define meaning. | [functional-ontology](functional-ontology.md) | ADR-0016 | `VaultRoot`, `Artifact`, `Segment` | `source_role`, `scope_binding` | PDM, HKA, SIP, DRI | metadata bundle schema — TBD (#2544) | invariant registry — TBD (#2550) | #2537, #2544 |
| 13 | Observability is not policy. | [functional-ontology](functional-ontology.md), [doctrine](../foundation/00-yggdrasil-doctrine.md) | ADR-0022 | `Projection`, `AuthorityReceipt`, `ProvenanceEvent` | `evidence_role`, `authority_state` | OEF, GOV | OEF/CES charter — TBD (#2543) | invariant registry — TBD (#2550) | #2537, #2543 |
| 14 | Sync preserves boundaries. | [functional-ontology](functional-ontology.md), [semantic-dimensions](semantic-dimensions.md) | TBD (#2549) | `Node`, `Replica`, `Device` | `sync_state`, `scope_binding`, `authority_state` | SFC, GOV | existing `REPLICATION_ENVELOPE.md`; charter — TBD (#2543) | invariant registry — TBD (#2550) | #2537, #2538 |
| 15 | Human-authored material is not automatically canonical. | [doctrine](../foundation/00-yggdrasil-doctrine.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0017 | `HumanArtifact`, `AcceptedArtifact` | `source_role` ≠ `authority_state` | HKA, GOV | `AuthorityTransition` contract — TBD (#2547) | invariant registry — TBD (#2550) | #2536, #2538, #2547 |
| 16 | Derived/rebuildable representations must preserve metadata and provenance. | [functional-ontology](functional-ontology.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0018, ADR-0024 | `Segment`, `Projection`, `Source` | `source_role`, `scope_binding`, `evidence_role` | DRI, SIP, PDM | metadata bundle schema — TBD (#2544) | anti-contamination eval — TBD (#2551) | #2537, #2544 |
| 17 | When uncertain, propose/confirm/escalate rather than silently act. | [doctrine](../foundation/00-yggdrasil-doctrine.md) | TBD (#2549) | `Proposal`, `CapabilityGrant` | `authority_state` (`proposed`), confirmation semantics | CAO, GOV, HIX | `ContextEnvelope` / proposal contract — TBD (#2545) | invariant registry — TBD (#2550) | #2536, #2545 |

## Foundation docs delivered (this PR)

| Doc | Purpose | Issue |
| --- | --- | --- |
| [traceability-matrix.md](traceability-matrix.md) | This map: principle → implementation. | #2535 |
| [00-yggdrasil-doctrine.md](../foundation/00-yggdrasil-doctrine.md) | Repo-level north star. | #2536 |
| [functional-ontology.md](functional-ontology.md) | Canonical objects and their consequences. | #2537 |
| [semantic-dimensions.md](semantic-dimensions.md) | Orthogonal meaning-preserving metadata. | #2538 |
| [cross-scope-flow.md](cross-scope-flow.md) | Governed cross-scope use. | #2539 |

## Pending artifacts (later backlog)

These are the `TBD` targets above. They are open issues, not gaps in reasoning:

- Boundary charters — [#2540](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2540)–[#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2543)
- Schemas/contracts — metadata bundle [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544), `ContextEnvelope` [#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545), `MemoryItem` [#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546), `AuthorityTransition` [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547), `RetrievalResult` [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548)
- ADR set — [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)
- Invariant test registry — [#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550); anti-contamination eval corpus — [#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551); xfail invariant/eval skeletons — [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552)

## Related documents

- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md) — full synthesis behind every row
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — control boundaries and forbidden dependencies
- [ADR index](../adr/INDEX.md) — accepted decisions referenced above
