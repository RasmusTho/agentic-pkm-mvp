# Boundary: DRI — Derived Representation & Indexing

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md) ·
[System of Systems Architecture](../SYSTEM_OF_SYSTEMS_ARCHITECTURE.md)

**Canonical separation rule:** DRI owns **rebuildable machine representations**. Everything DRI owns
must be rebuildable from declared sources or reclassified into HKA, MEM, GOV, or SIP — DRI never
becomes the source of truth (`SYSTEM_BREAKDOWN_STRUCTURE.md:836-837`).

## Purpose

Own embeddings, chunking, lexical/vector indexes, graph/relation projections, derived overlays, and
machine-readable mirrors — plus the rebuild, invalidation, and staleness-detection machinery that
keeps them disposable — so machine representations can be replaced or rebuilt without ever becoming
hidden knowledge. This is the "runtime persistence/index implementations behind the durable surface"
named in the extension fabric (`docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md:58`: "Postgres/pgvector,
embedding stacks, relation stores, future stores" are replaceable and must not weaken kernel
constraints to be replaced).

## Owns

- Embeddings, chunking, lexical indexes, vector indexes, graph/relation projections, derived
  overlays, machine-readable mirrors (`SYSTEM_BREAKDOWN_STRUCTURE.md:816-822`).
- Rebuild pipelines, staleness detection, derived-artifact invalidation, embedding identity
  contracts.
- Derived source-set declarations — DRI states what sources built a given projection so it is
  provably rebuildable.

## Does not own

- Storage backend / persistence mechanics → **PDM** (DRI's projections are *stored* through PDM
  ports; DRI does not own the store technology).
- Human knowledge → **HKA**; memory semantics → **MEM**; policy → **GOV**.
- Retrieval answer composition / ranking → **RCA** (DRI supplies projections/indexes that RCA
  queries; DRI does not decide what is relevant or admissible).
- UI → **HIX**; agent runtime → **CAO**.
- Provider/model mechanics → **EBF** (DRI depends on EBF's embedding/model providers but does not
  own the adapter itself).

> **Ownership-drift rule.** Everything DRI owns must be rebuildable from declared sources
> (HKA/SIP/MEM/PDM anchors) and provider configuration (EBF), or it does not belong in DRI — it
> must be reclassified into HKA, GOV, or MEM. "Derived representations contain non-rebuildable
> meaning" is a named failure mode this charter forbids
> (`SYSTEM_BREAKDOWN_STRUCTURE.md:1883-1896`): if DRI loss would destroy accepted human knowledge,
> artifact-origin facts, or governance receipts, that material was never DRI's to hold.

## Inputs

- Declared source sets from **HKA**, **SIP**, **MEM** (`SYSTEM_BREAKDOWN_STRUCTURE.md:1443`).
- Store access via **PDM**; embedding/model providers via **EBF**.
- Invalidation triggers from authority transitions (HKA update), memory promotion (MEM/GOV), and
  sync convergence (SFC) — per the canonical flows, DRI invalidates/rebuilds after each
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1356,1374,1380,1392`).

## Outputs

- `DerivedRepresentationContract` — defines rebuildable projections, embeddings, indexes, and source
  sets (`SYSTEM_BREAKDOWN_STRUCTURE.md:1500`).
- Indexes, projections, and staleness reports made available for **RCA** (retrieval) and **MEM**
  (memory representations) to consume. RCA and MEM initiate these calls into DRI
  (`docs/boundaries/RCA.md :: Calls allowed`, `docs/boundaries/MEM.md :: Calls allowed`;
  `SYSTEM_BREAKDOWN_STRUCTURE.md:1444-1445`) — DRI does not call RCA or MEM itself, consistent with
  DRI's own "Calls allowed" section below, which does not name RCA or MEM as callees.

## Calls allowed

- **HKA, SIP, MEM** (declared source sets), **PDM** (store access), **EBF** (embedding/model
  providers) (`SYSTEM_BREAKDOWN_STRUCTURE.md:1443`).

## Calls forbidden

- **Holding non-rebuildable meaning** — a derived record that cannot be rebuilt from HKA/GOV/MEM
  source anchors and provider configuration is a DRI violation, not a DRI artifact
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1883-1896`).
- **Becoming source of truth** — RCA, CAO, or HIX treating a DRI projection as authoritative instead
  of candidate is a downstream violation DRI must not enable by mislabeling a projection as
  canonical.
- **Owning storage backend decisions** — DRI stores through PDM ports; it must not construct its own
  private persistence mechanism (mirrors the PDM "storage leak" failure mode from the DRI side).

## Required metadata

DRI **reads and preserves** `source_role`, `scope_binding`, `sensitivity`, and `suppression_state`
on the material it derives from, carrying them into projections so RCA can prefilter correctly
downstream. DRI **owns no authority-bearing dimension** (`authority_state`, `evidence_role`) — a
projection's freshness/staleness is DRI's own signal, not a promotion of the underlying material's
standing.

## Policy obligations

- Suppressed or out-of-scope source material must not appear in a rebuilt projection — DRI honors
  `suppression_state` and `scope_binding` at rebuild time, it does not decide them.
- Rebuild/invalidation triggered by an authority transition or memory promotion must complete (or be
  visibly pending) before the corresponding projection is presented as current.

## Provenance obligations

- Every `DerivedRepresentationContract` names its declared source set so any projection is
  independently verifiable as rebuildable.
- Staleness must be detectable and reported, not silently tolerated — a stale index presented as
  current is a provenance failure.

## Invariants owned

- Derived representations are rebuildable and never source of truth (`docs/boundaries/README.md`;
  matrix row DRI, `SYSTEM_BREAKDOWN_STRUCTURE.md:1341`).
- No naked derived representations — every projection has a declared, verifiable source set
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1341`).
- DRI contains non-rebuildable meaning is a forbidden dependency
  (`SYSTEM_BREAKDOWN_STRUCTURE.md:1464`).

## Failure modes

- **Naked vector / non-rebuildable projection:** a derived artifact with no traceable source set
  (named failure mode, `SYSTEM_BREAKDOWN_STRUCTURE.md:1883-1896`; see also SIP's
  `store_no_naked_vectors` cross-reference, `docs/boundaries/SIP.md:57`).
- **Stale-as-current:** a projection presented as fresh without staleness detection having run.
- **Storage leak from the DRI side:** DRI constructing direct storage access instead of routing
  through PDM ports.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `derived_representations_rebuildable`
- `no_naked_derived_representations`
- `staleness_detected_before_served`

## Related ADRs

- The doctrine/ontology/boundary decisions affecting this boundary (ADR-0026–ADR-0039, [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)) are mapped per boundary by the [traceability matrix](../architecture/traceability-matrix.md).

## Related schemas/contracts

- `DerivedRepresentationContract` (SBS Part 5); existing `ContextBundle` consumer contract owned by
  RCA ([#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545)–[#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548)).

## Related issues

- Charter: [#2836](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2836) (SBI-7) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
