# Boundary: SIP — Semantic Identity & Provenance

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** SIP says **how things mean, derive, and relate**. (HKA says what is
durable; PDM says how it is stored.)

## Purpose

Own semantic identity, ontology, typed relations, attribution, lineage, and provenance/semantic
continuity over the identity and origin anchors that HKA preserves.

## Owns

- Semantic identity (`Concept`, `Claim` identity) and the ontology / relation vocabulary (`Relation`).
- Typed relations, attribution, and lineage / provenance views (`ProvenanceEvent`, `Source` attribution).
- Provenance continuity and semantic continuity across moves, representation changes, and migrations.

## Does not own

- Policy / admissibility decisions → **GOV**.
- Retrieval ranking and context assembly → **RCA**.
- Storage backend → **PDM**.
- Embeddings / indexes **as truth** → **DRI** (rebuildable projections, never source of truth).
- Execution → **EXE**; memory promotion → **MEM**/**GOV**.

> **Ownership-drift rule.** SIP describes meaning and lineage; it does not decide standing
> (`authority_state` is GOV) or admissibility. When standing or policy is needed, defer to GOV.

## Inputs

- HKA identity anchors and origin-provenance stamps.
- GOV `AuthorityReceipt`s and MEM records as provenance sources.
- Declared sources (via EBF adapters) and relation definitions.

## Outputs

- `SemanticIdentityContract`, provenance views, lineage graph, relation/ontology rules.
- Attribution and claim/evidence relationships consumed by RCA, GOV, MEM, HKA.

## Calls allowed

- **HKA** — read identity/provenance anchors (the durable substrate SIP builds upon).
- **GOV** — supply provenance/identity views for authority categories; defer policy.
- **WSP** — coordinate scope/context semantics.

## Calls forbidden

- **PDM internals / DRI vectors as truth** — must not treat a stored row or an embedding as semantic authority (`store_no_naked_vectors`).
- **RCA ranking** — must not rank or decide relevance; that is retrieval.
- **GOV's job** — must not assign `authority_state` or grant cross-scope use.

## Required metadata

SIP **owns `source_role`** (origin/provenance kind) and the provenance/lineage refs. It must keep
`source_role`, `authority_state`, and `evidence_role` **orthogonal** — never inferring one from
another (see [semantic dimensions](../architecture/semantic-dimensions.md)). Derived representations
it informs must carry `scope_binding` and `provenance_ref` forward.

> **Continuity-bearing, not fully rebuildable.** SIP is **not** rebuildable in the same sense as DRI
> indexes. Some projections of SIP may be rebuilt, but provenance and semantic-identity anchors are
> continuity-bearing system state. If losing SIP would lose the minimum origin identity required for
> human-knowledge survival, that data belongs in **HKA**, not SIP alone.

## Policy obligations

- Defer all admissibility / standing decisions to GOV; expose provenance views GOV needs.
- Honor `sensitivity` and `scope_binding` when exposing lineage/attribution.

## Provenance obligations

- Provenance carries **justification**, not just origin (matrix #3).
- Provenance must **survive derived use** — projections, embeddings, segments, and context bundles carry it forward.
- Every derived representation that references SIP material preserves metadata + provenance.

## Invariants owned

- Provenance carries justification (matrix #3).
- Provenance survives derivation (matrix #16).
- `source_role`, `authority_state`, `evidence_role` remain orthogonal (matrix #5).
- Derived/rebuildable representations preserve metadata and provenance (matrix #16).

## Failure modes

- **Naked vectors:** storing embeddings/segments without provenance/metadata — detect derived artifacts lacking `provenance_ref`.
- **Role collapse:** merging `source_role`/`authority_state`/`evidence_role` into one field.
- **Shadow origin store:** SIP holding the *only* copy of survival-critical identity (belongs in HKA).

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `provenance_survives_derivation`
- `metadata_bundle_required`
- `store_no_naked_vectors`

## Related ADRs

- ADR-0018 (provenance split).

## Related schemas/contracts

- metadata bundle — [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544); `RetrievalResult` (consumes provenance) — [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548).

## Related issues

- Charter: [#2541](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2541) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
