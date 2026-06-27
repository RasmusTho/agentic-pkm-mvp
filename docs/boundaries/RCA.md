# Boundary: RCA — Retrieval & Context Assembly

State: Boundary charter — Draft (control-boundary contract; docs-only, not a runtime service declaration)

**Source docs:** [SBS](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
[context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
[doctrine](../foundation/00-yggdrasil-doctrine.md) ·
[functional ontology](../architecture/functional-ontology.md) ·
[semantic dimensions](../architecture/semantic-dimensions.md) ·
[CrossScopeFlow](../architecture/cross-scope-flow.md) ·
[traceability matrix](../architecture/traceability-matrix.md)

**Canonical separation rule:** RCA **finds and packages candidate context/evidence**. It does not
decide truth, authority, or admissibility.

## Purpose

Own moment-specific finding, ranking, evidence selection, and context-bundle assembly — producing
*candidates*, with relevance explanation, for cognition and the human to use.

## Owns

- Search, ranking, reranking, retrieval strategy, evidence/candidate selection.
- Context bundles (`ContextBundle`), citation basis/packaging, relevance explanation, staleness signals.

## Does not own

- Truth / authority / final admissibility → **GOV** (admissibility) and **SIP** (standing of meaning).
- Machine-memory lifecycle → **MEM**; durable mutation → **HKA**/**GOV**.
- Policy decisions → **GOV**; embedding/index construction → **DRI**.

> **Ownership-drift rule.** Retrieval surfaces candidates; it never converts a candidate into evidence,
> authority, or a cross-scope right. Those are GOV/SIP decisions — defer, do not re-derive.

## Inputs

- Query/intent (CAO, HIX), `ActiveContextSet` (WSP), DRI projections, MEM recall, GOV filters/flows.

## Outputs

- `ContextBundle` / `RetrievalResult`: ranked **candidate** evidence with provenance and relevance explanation.

> **Naming note.** RCA produces the existing `ContextBundle` (scoped candidate evidence). The broader
> bounded agent-operating-context contract `ContextEnvelope` ([#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545))
> is a **distinct, later** contract that *composes* a `ContextBundle`; it does not replace it.

## Calls allowed

- **DRI** (projections/indexes), **MEM** (recall), **SIP** (provenance), **WSP** (scope), **GOV** (eligibility filters / `CrossScopeFlow`).

## Calls forbidden

- **Writing HKA** — retrieval becoming truth is forbidden.
- **Cross-scope by similarity** — must not retrieve/cite across a boundary without a GOV `CrossScopeFlow`.
- **Granting admissibility** — must not stamp `evidence_role` or `authority_state`.

## Required metadata

RCA **reads and preserves** `scope_binding`, `source_role`, `authority_state`, `evidence_role`,
`sensitivity`, `suppression_state`; it must **prefilter by scope/policy eligibility before ranking**
and carry every dimension forward into the bundle. It sets none of them as authority.

## Policy obligations

- Apply scope/policy eligibility (GOV) **before** ranking; exclude `suppressed`/out-of-scope material.
- Cross-scope candidates require a typed `CrossScopeFlow`; respect its `allowed_operations` (retrieve ≠ cite).

## Provenance obligations

- Every candidate carries provenance and relevance explanation; citation basis distinguishes authority from similarity.
- Never strip provenance during assembly.

## Invariants owned

- Retrieval produces candidate evidence, not truth (matrix #7).
- Similarity is not permission (matrix #1).
- Scope/policy eligibility precedes ranking (matrix #1, #6).
- A retrieved item is not automatically citable/mutable (matrix #1, #7).

## Failure modes

- **Retrieval-as-truth:** treating a top-ranked candidate as evidence/authority.
- **Similarity bypass:** crossing scopes because of embedding closeness.
- **Provenance loss:** bundles without citation basis or scope binding.

## Required tests

Future test names for the invariant registry ([#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550)) / eval corpus ([#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551)); skeletons in [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552). No tests created here.

- `retrieve_scope_prefilter`
- `similarity_not_permission`
- `retrieval_not_truth`
- `citation_distinguishes_authority`

## Related ADRs

- ADR-0024 (retrieval is candidate evidence).
- The doctrine/ontology/boundary decisions affecting this boundary (ADR-0026–ADR-0039, [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)) are mapped per boundary by the [traceability matrix](../architecture/traceability-matrix.md).

## Related schemas/contracts

- `RetrievalResult` — [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548); `ContextEnvelope` (composes `ContextBundle`) — [#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545); existing `ContextBundle` (SBS Part 5).

## Related issues

- Charter: [#2542](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2542) · Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) · Index: [README.md](README.md)
