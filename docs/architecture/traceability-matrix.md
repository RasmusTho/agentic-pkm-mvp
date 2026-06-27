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
it. The `Required tests / evals` column names the [invariant registry](../testing/invariant-tests.md)
entry that protects the row plus its current test path; the registry owns each invariant's
enforcement posture (schema-enforced, static test, or xfail runtime skeleton). `TBD (#NNNN)` means
the artifact belongs to a not-yet-delivered issue, not that the thinking is missing.

**Conventions.** All `#NNNN` references are issues/epics in `RasmusTho/agentic-pkm-mvp`. ADR ids
refer to files under [`docs/adr/`](../adr/INDEX.md). Control boundaries (HKA, SIP, GOV, WSP, RCA,
MEM, CAO, EXE, DRI, PDM, SFC, OEF, CES) are defined in the
[System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) and the
[boundary register](SBS_BOUNDARY_REGISTER.md), and chartered in
[`docs/boundaries/`](../boundaries/README.md). This matrix is append-friendly: future implementation
issues add rows without restructuring it.

## Matrix

| # | Principle / finding | Canonical doc | ADR | Ontology concepts | Semantic distinctions | Control boundaries | Contract / schema | Required tests / evals | Implementation issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Similarity is not permission. | [cross-scope-flow](cross-scope-flow.md) | ADR-0028, ADR-0039 | `CrossScopeFlow`, `RetrievalResult`, `Relation` | `scope_binding` ≠ permission; `evidence_role` ≠ retrieve/cite right | RCA, GOV, WSP | [retrieval-contract](retrieval-contract.md) / [schema](../../schemas/retrieval-result.schema.json); [metadata-bundle](metadata-bundle.md) (#2544, #2548) | [invariant registry](../testing/invariant-tests.md) `similarity_not_permission`; xfail [test_cross_scope_flow](../../tests/invariants/test_cross_scope_flow.py); eval [corpus](../../tests/evals/fixtures/README.md) (#2550, #2551, #2552) | #2539, #2548, #2551 |
| 2 | Scope is frame, audience boundary, policy boundary, and provenance context. | [functional-ontology](functional-ontology.md), [doctrine](../foundation/00-yggdrasil-doctrine.md) | ADR-0027 | `Scope`, `Sphere`, `Workspace`, `VaultRoot` | `scope_binding`, `sensitivity` | WSP, GOV, SIP | [metadata-bundle](metadata-bundle.md) / [schema](../../schemas/metadata-bundle.schema.json) (#2544) | [invariant registry](../testing/invariant-tests.md) `metadata_bundle_required`, `capture_stamps_scope`; [test_metadata_bundle](../../tests/invariants/test_metadata_bundle.py) (#2550, #2552) | #2537, #2538, #2544 |
| 3 | Provenance carries justification. | [functional-ontology](functional-ontology.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0018 | `ProvenanceEvent`, `Source`, `Claim` | `source_role`, `evidence_role` | [SIP](../boundaries/SIP.md), [GOV](../boundaries/GOV.md), [HKA](../boundaries/HKA.md), [PDM](../boundaries/PDM.md) | [metadata-bundle](metadata-bundle.md) / [schema](../../schemas/metadata-bundle.schema.json) (#2544) | [invariant registry](../testing/invariant-tests.md) `provenance_survives_derivation`; xfail [test_metadata_bundle](../../tests/invariants/test_metadata_bundle.py) (#2550, #2552) | #2537, #2544 |
| 4 | Agent memory is noncanonical by default. | [semantic-dimensions](semantic-dimensions.md), [functional-ontology](functional-ontology.md) | ADR-0025, ADR-0026, ADR-0030 | `MemoryItem`, `Proposal` | `source_role`, `authority_state`, `memory_state` | [MEM](../boundaries/MEM.md), [GOV](../boundaries/GOV.md), [HKA](../boundaries/HKA.md) | [memory-model](memory-model.md) / [schema](../../schemas/memory-item.schema.json) (#2546) | [invariant registry](../testing/invariant-tests.md) `memory_item_authority_is_noncanonical`, `remember_not_canonical`; [test_agent_memory](../../tests/invariants/test_agent_memory.py) (#2550, #2552) | #2538, #2546 |
| 5 | `source_role`, `authority_state`, and `evidence_role` are orthogonal. | [semantic-dimensions](semantic-dimensions.md) | ADR-0029 | `Artifact`, `Claim`, `MemoryItem`, `Projection` | the three role dimensions are non-collapsible | SIP, GOV | [metadata-bundle](metadata-bundle.md) / [schema](../../schemas/metadata-bundle.schema.json) (#2544) | [invariant registry](../testing/invariant-tests.md) `retrieval_cannot_upgrade_intrinsic_non_evidence`; [test_agent_memory](../../tests/invariants/test_agent_memory.py), [test_retrieval_result](../../tests/invariants/test_retrieval_result.py); eval [corpus](../../tests/evals/fixtures/README.md) (#2550, #2551, #2552) | #2538, #2544, #2550, #2551 |
| 6 | Typed `CrossScopeFlow` replaces any global `general_knowledge` bypass. | [cross-scope-flow](cross-scope-flow.md) | ADR-0028 | `CrossScopeFlow`, `Scope` | `source_role` (`general_knowledge` = eligibility, not bypass), `scope_binding` | GOV, RCA | [metadata-bundle](metadata-bundle.md) / [retrieval-result schema](../../schemas/retrieval-result.schema.json) (#2544, #2548) | [invariant registry](../testing/invariant-tests.md) `cross_scope_only_via_flow`; xfail [test_cross_scope_flow](../../tests/invariants/test_cross_scope_flow.py), [test_general_knowledge_crosses_clean](../../tests/evals/test_general_knowledge_crosses_clean.py) (#2550, #2551, #2552) | #2539, #2551 |
| 7 | Retrieval produces candidate evidence, not truth. | [cross-scope-flow](cross-scope-flow.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0024, ADR-0037, ADR-0039 | `RetrievalResult`, `Projection`, `Segment` | `evidence_role`, `authority_state` | [RCA](../boundaries/RCA.md), [GOV](../boundaries/GOV.md), [SIP](../boundaries/SIP.md) | [retrieval-contract](retrieval-contract.md) / [schema](../../schemas/retrieval-result.schema.json) (#2548) | [invariant registry](../testing/invariant-tests.md) `retrieval_candidate_identity_single_source`, `retrieve_scope_prefilter`; [test_retrieval_result](../../tests/invariants/test_retrieval_result.py) (#2550, #2552) | #2548, #2550 |
| 8 | Projection is not evidence. | [functional-ontology](functional-ontology.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0018, ADR-0022, ADR-0033, ADR-0037 | `Projection`, `Segment` | `evidence_role` (default `non_evidence`), `authority_state` | DRI, OEF, GOV | [context-envelope](context-envelope.md) / [schema](../../schemas/context-envelope.schema.json) (#2545) | [invariant registry](../testing/invariant-tests.md) `projection_not_evidence`; xfail [test_projection_not_evidence](../../tests/invariants/test_projection_not_evidence.py) (#2550, #2552) | #2537, #2538, #2545 |
| 9 | Authority transitions require governance and receipts. | [functional-ontology](functional-ontology.md), [doctrine](../foundation/00-yggdrasil-doctrine.md) | ADR-0017, ADR-0019, ADR-0031 | `AuthorityReceipt`, `AcceptedArtifact`, `Commitment` | `authority_state` | GOV, HKA | [authority-transition-flow](authority-transition-flow.md) / [schema](../../schemas/authority-transition.schema.json) (#2547) | [invariant registry](../testing/invariant-tests.md) `authority_transition_requires_decision_token_and_receipt`, `authority_transition_state_is_consistent`; [test_authority_transition](../../tests/invariants/test_authority_transition.py) (#2550, #2552) | #2547, #2550 |
| 10 | Execution cannot authorize itself. | [functional-ontology](functional-ontology.md) | ADR-0019, ADR-0031 | `ExecutionEffect`, `CapabilityGrant`, `AuthorityReceipt` | `execution_state`, `authority_state` | [CAO](../boundaries/CAO.md), [GOV](../boundaries/GOV.md), [EXE](../boundaries/EXE.md) | [authority-transition-flow](authority-transition-flow.md) / [schema](../../schemas/authority-transition.schema.json) (#2547); existing [EXECUTION_REQUEST.md](../contracts/EXECUTION_REQUEST.md) | [invariant registry](../testing/invariant-tests.md) `execution_cannot_authorize_itself`; xfail [test_authority_transition](../../tests/invariants/test_authority_transition.py) (#2550, #2552) | #2537, #2547 |
| 11 | Parent aggregation is not sibling sharing. | [cross-scope-flow](cross-scope-flow.md) | ADR-0034 | `Scope`, `CrossScopeFlow` | `scope_binding` | [SFC](../boundaries/SFC.md), [GOV](../boundaries/GOV.md), [WSP](../boundaries/WSP.md) | [metadata-bundle](metadata-bundle.md) / [schema](../../schemas/metadata-bundle.schema.json) (#2544) | [invariant registry](../testing/invariant-tests.md) `parent_aggregation_not_sibling_sharing`; xfail [test_cross_scope_flow](../../tests/invariants/test_cross_scope_flow.py); eval [corpus](../../tests/evals/fixtures/README.md) (#2550, #2551, #2552) | #2539, #2551 |
| 12 | Storage preserves but does not define meaning. | [functional-ontology](functional-ontology.md) | ADR-0016, ADR-0032, ADR-0038 | `VaultRoot`, `Artifact`, `Segment` | `source_role`, `scope_binding` | [HKA](../boundaries/HKA.md), [SIP](../boundaries/SIP.md), [PDM](../boundaries/PDM.md), DRI | [metadata-bundle](metadata-bundle.md) / [schema](../../schemas/metadata-bundle.schema.json) (#2544) | [invariant registry](../testing/invariant-tests.md) `store_no_naked_vectors`, `storage_write_is_not_authority_transition`; [test_metadata_bundle](../../tests/invariants/test_metadata_bundle.py), xfail [test_authority_transition](../../tests/invariants/test_authority_transition.py) (#2550, #2552) | #2537, #2544 |
| 13 | Observability is not policy. | [functional-ontology](functional-ontology.md), [doctrine](../foundation/00-yggdrasil-doctrine.md) | ADR-0022, ADR-0035 | `Projection`, `AuthorityReceipt`, `ProvenanceEvent` | `evidence_role`, `authority_state` | [OEF](../boundaries/OEF.md), [GOV](../boundaries/GOV.md) | [OEF](../boundaries/OEF.md) / [CES](../boundaries/CES.md) charter (#2543) | [invariant registry](../testing/invariant-tests.md) `observability_not_policy`; xfail [test_projection_not_evidence](../../tests/invariants/test_projection_not_evidence.py) (#2550, #2552) | #2537, #2543 |
| 14 | Sync preserves boundaries. | [functional-ontology](functional-ontology.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0034 | `Node`, `Replica`, `Device` | `sync_state`, `scope_binding`, `authority_state` | [WSP](../boundaries/WSP.md), [SFC](../boundaries/SFC.md), [GOV](../boundaries/GOV.md) | existing `REPLICATION_ENVELOPE.md`; [SFC](../boundaries/SFC.md) / [WSP](../boundaries/WSP.md) charter (#2543) | [invariant registry](../testing/invariant-tests.md) `sync_preserves_boundaries`; xfail [test_cross_scope_flow](../../tests/invariants/test_cross_scope_flow.py) (#2550, #2552) | #2537, #2538 |
| 15 | Human-authored material is not automatically canonical. | [doctrine](../foundation/00-yggdrasil-doctrine.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0017, ADR-0026 | `HumanArtifact`, `AcceptedArtifact` | `source_role` ≠ `authority_state` | HKA, GOV | [authority-transition-flow](authority-transition-flow.md) / [schema](../../schemas/authority-transition.schema.json) (#2547) | [invariant registry](../testing/invariant-tests.md) `promote_requires_governance`; xfail [test_authority_transition](../../tests/invariants/test_authority_transition.py) (#2550, #2552) | #2536, #2538, #2547 |
| 16 | Derived/rebuildable representations must preserve metadata and provenance. | [functional-ontology](functional-ontology.md), [semantic-dimensions](semantic-dimensions.md) | ADR-0018, ADR-0024, ADR-0033, ADR-0038 | `Segment`, `Projection`, `Source` | `source_role`, `scope_binding`, `evidence_role` | DRI, SIP, PDM | [metadata-bundle](metadata-bundle.md) / [schema](../../schemas/metadata-bundle.schema.json) (#2544) | [invariant registry](../testing/invariant-tests.md) `provenance_survives_derivation`; xfail [test_metadata_bundle](../../tests/invariants/test_metadata_bundle.py); eval [corpus](../../tests/evals/fixtures/README.md) (#2550, #2551, #2552) | #2537, #2544 |
| 17 | When uncertain, propose/confirm/escalate rather than silently act. | [doctrine](../foundation/00-yggdrasil-doctrine.md) | ADR-0026 | `Proposal`, `CapabilityGrant` | `authority_state` (`proposed`), confirmation semantics | CAO, GOV, HIX | [context-envelope](context-envelope.md) / [schema](../../schemas/context-envelope.schema.json) (#2545) | [invariant registry](../testing/invariant-tests.md) (propose/escalate — future runtime); [test_context_envelope](../../tests/invariants/test_context_envelope.py) (#2550, #2552) | #2536, #2545 |
| 18 | Standards are adapters, not the ontology. | [doctrine](../foundation/00-yggdrasil-doctrine.md) §2.7, [functional-ontology](functional-ontology.md) | ADR-0036 | `Concept`, `Source`, `ProvenanceEvent` | external standards do not redefine `source_role`/`authority_state`/`evidence_role` | EBF, SIP, GOV, CES | [`_defs.schema.json`](../../schemas/_defs.schema.json) (value families standards must not redefine) | [invariant registry](../testing/invariant-tests.md) `standards are adapters` — CES stewardship review; registry doc_only (#2550) | #2536, #2549 |

## Foundation docs delivered (this PR)

| Doc | Purpose | Issue |
| --- | --- | --- |
| [traceability-matrix.md](traceability-matrix.md) | This map: principle → implementation. | #2535 |
| [00-yggdrasil-doctrine.md](../foundation/00-yggdrasil-doctrine.md) | Repo-level north star. | #2536 |
| [functional-ontology.md](functional-ontology.md) | Canonical objects and their consequences. | #2537 |
| [semantic-dimensions.md](semantic-dimensions.md) | Orthogonal meaning-preserving metadata. | #2538 |
| [cross-scope-flow.md](cross-scope-flow.md) | Governed cross-scope use. | #2539 |

## Boundary charters delivered (#2540–#2543)

The boundary charters for the **delivered** boundaries are no longer pending. Eleven of the fourteen
Level 2 control boundaries — plus the CES stewardship practice (a twelfth charter, but not a control
boundary) — now have a charter under
[`docs/boundaries/`](../boundaries/README.md) stating what each owns, what it must never own, its
inputs/outputs, required metadata, policy/provenance obligations, invariants, failure modes, and the
future tests that will enforce it. **HIX, EBF, and DRI remain pending** (later backlog under #2533) —
do not treat this matrix as full boundary-charter coverage until all fourteen charters exist.

| Charter | Boundary | Enforces (principle rows) |
| --- | --- | --- |
| [HKA.md](../boundaries/HKA.md) | Human Knowledge & Artifact Substrate | #9, #15 (durable knowledge changes only by governed transition); #4 |
| [SIP.md](../boundaries/SIP.md) | Semantic Identity & Provenance | #3 (provenance carries justification); #5, #16 |
| [PDM.md](../boundaries/PDM.md) | Persistence & Data Management | #12 (storage preserves but does not define meaning) |
| [GOV.md](../boundaries/GOV.md) | Governance, Policy, Authority & Receipts | #9, #10 (authority transitions; execution cannot authorize itself); #6 |
| [RCA.md](../boundaries/RCA.md) | Retrieval & Context Assembly | #1, #7 (retrieval is candidate evidence, not truth) |
| [MEM.md](../boundaries/MEM.md) | Machine Memory & Learning | #4 (agent memory noncanonical until promoted) |
| [CAO.md](../boundaries/CAO.md) | Cognitive Capability & Agent Orchestration | #10, #17 (reason/propose, not mutate/execute) |
| [EXE.md](../boundaries/EXE.md) | Capability Execution & Automation | #10 (execution cannot authorize itself) |
| [WSP.md](../boundaries/WSP.md) | Workspace, Scope & Principal Context | #2, #11 (context is not identity; scope binding is not permission) |
| [SFC.md](../boundaries/SFC.md) | Synchronization, Federation & Consensus | #11, #14 (sync preserves boundaries; parent aggregation is not sibling sharing) |
| [OEF.md](../boundaries/OEF.md) | Observability, Evaluation & Fitness | #13 (observability is not policy) |
| [CES.md](../boundaries/CES.md) | Contract & Evolution Stewardship (practice, not runtime) | architecture evolves explicitly |

Index + template: [README.md](../boundaries/README.md), [\_template.md](../boundaries/_template.md).
Pending charters (later backlog): HIX, EBF, DRI.

Per-principle charter references:

- Storage preserves but does not define meaning (#12) → [HKA](../boundaries/HKA.md) / [SIP](../boundaries/SIP.md) / [PDM](../boundaries/PDM.md).
- Retrieval produces candidate evidence, not truth (#7) → [RCA](../boundaries/RCA.md) / [GOV](../boundaries/GOV.md) / [SIP](../boundaries/SIP.md).
- Agent memory is noncanonical (#4) → [MEM](../boundaries/MEM.md) / [GOV](../boundaries/GOV.md) / [HKA](../boundaries/HKA.md).
- Execution cannot authorize itself (#10) → [CAO](../boundaries/CAO.md) / [GOV](../boundaries/GOV.md) / [EXE](../boundaries/EXE.md).
- Observability is not policy (#13) → [OEF](../boundaries/OEF.md) / [GOV](../boundaries/GOV.md).
- Sync preserves boundaries (#14) → [WSP](../boundaries/WSP.md) / [SFC](../boundaries/SFC.md) / [GOV](../boundaries/GOV.md).
- Parent aggregation is not sibling sharing (#11) → [SFC](../boundaries/SFC.md) / [GOV](../boundaries/GOV.md) / [WSP](../boundaries/WSP.md).
- Provenance carries justification (#3) → [SIP](../boundaries/SIP.md) / [HKA](../boundaries/HKA.md) / [PDM](../boundaries/PDM.md).

## Contracts / schemas delivered (#2544–#2548)

The schemas/contracts batch turns the doctrine, ontology, semantic dimensions, and CrossScopeFlow
model into machine-readable contracts. Each architecture doc pairs one-to-one with a JSON schema; the
schemas share value families through [`schemas/_defs.schema.json`](../../schemas/_defs.schema.json) so
`source_role`, `authority_state`, and `evidence_role` cannot collapse. These contracts do **not**
implement runtime behavior.

| Doc | Schema | Object | Issue |
| --- | --- | --- | --- |
| [metadata-bundle.md](metadata-bundle.md) | [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json) | `MetadataBundle` | [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544) |
| [context-envelope.md](context-envelope.md) | [`context-envelope.schema.json`](../../schemas/context-envelope.schema.json) | `ContextEnvelope` (composes `ContextBundle`) | [#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545) |
| [memory-model.md](memory-model.md) | [`memory-item.schema.json`](../../schemas/memory-item.schema.json) | `MemoryItem` + promotion boundary | [#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546) |
| [authority-transition-flow.md](authority-transition-flow.md) | [`authority-transition.schema.json`](../../schemas/authority-transition.schema.json) | `AuthorityTransition` | [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547) |
| [retrieval-contract.md](retrieval-contract.md) | [`retrieval-result.schema.json`](../../schemas/retrieval-result.schema.json) | `RetrievalResult` | [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548) |

## ADR set delivered (#2549)

The doctrine/ontology/boundary decisions are now frozen as accepted ADRs **ADR-0026 through
ADR-0039** under [`docs/adr/`](../adr/INDEX.md). ADR-0026–ADR-0035 are the required doctrine set;
ADR-0036–ADR-0039 are follow-up records — optional additions beyond the ten ADRs #2549 requires,
kept because each freezes a schema- or doctrine-backed decision (their State/Status mark them
follow-up). The principle rows above and the new ADRs are kept bidirectionally consistent: every row
lists each new ADR (ADR-0026–ADR-0039) whose *Affected invariants* name that row, and each new ADR
names its rows in turn — including ADR-0036, which traces through row 18 (standards are adapters, the
doctrine §2.7 commitment). All new ADRs cross-reference the related existing decisions
(ADR-0015–ADR-0025) rather than re-deciding them.

## Fitness/eval surface delivered (#2550–#2552)

The architecture-foundation backlog's final batch turned the principle rows above into an executable
fitness/eval surface. The `Required tests / evals` column now points at concrete artifacts, not
`TBD`:

| Artifact | Path | Issue |
| --- | --- | --- |
| Invariant test registry | [docs/testing/invariant-tests.md](../testing/invariant-tests.md) | [#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550) |
| Anti-contamination eval fixture corpus | [tests/evals/fixtures/](../../tests/evals/fixtures/README.md) | [#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551) |
| Invariant/eval test skeletons (static + honest xfail) | [tests/invariants/](../../tests/invariants/), [tests/evals/](../../tests/evals/) | [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552) |

Each invariant's enforcement posture (schema-enforced, static test, or xfail runtime skeleton) and
its eventual test path are owned by the [invariant registry](../testing/invariant-tests.md). The
remaining work these skeletons protect is the first runtime vertical slice (Capture → MetadataBundle
→ DRI segment → retrieval prefilter → RCA result → ContextEnvelope), which will turn the `xfail`
skeletons into passing runtime tests.

## Related documents

- [Invariant test registry](../testing/invariant-tests.md) — principle → **named invariant** → enforcement → test
- [Anti-contamination eval fixtures](../../tests/evals/fixtures/README.md) — the synthetic contamination corpus
- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md) — full synthesis behind every row
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — control boundaries and forbidden dependencies
- [ADR index](../adr/INDEX.md) — accepted decisions referenced above
