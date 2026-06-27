State: Boundary-charter index. Docs-only control-boundary contracts for the architecture-foundation backlog (#2533–#2552). Does not claim shipped runtime behavior.
Doc role: Architecture / boundary-charter index
Authority: Index and entry point for the Yggdrasil boundary charters. Owns the list of Level 2 control boundaries and the CES stewardship practice, and routes to each charter. Subordinate to `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (boundary definitions), `docs/foundation/00-yggdrasil-doctrine.md`, and `docs/architecture/traceability-matrix.md`.
Owner: Architecture spine / CES practice
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (charter index); subordinate to the SBS it operationalizes
Last reviewed: 2026-06-26
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/foundation/yggdrasil-architecture-context-packet.md, docs/architecture/traceability-matrix.md

# Boundary Charters

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
Template: [\_template.md](_template.md)

## Why boundary charters exist

The [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) defines Yggdrasil's Level 2
control boundaries, but a list of boundaries is not enough to stop ownership drift. Each boundary
needs a repeatable charter that answers, concretely:

> What do I own? What must I never own? What do I receive? What do I emit? What metadata must I
> preserve? Which policies/provenance obligations apply? Which invariants protect me? Which tests
> will later enforce me?

A charter makes the forbidden ownership as explicit as the granted ownership, so that a future human
or AI agent cannot silently let storage become meaning, retrieval become truth, memory become
authority, execution authorize itself, or observability become policy.

## Relationship to the SBS

These charters operationalize [`docs/SYSTEM_BREAKDOWN_STRUCTURE.md`](../SYSTEM_BREAKDOWN_STRUCTURE.md).

They are **control-boundary contracts, not runtime service declarations**.

A boundary may later be implemented by one module, several modules, or no standalone runtime service.
The charter defines responsibility and forbidden ownership, not deployment topology. Per the SBS,
commit now to the macro-domains, dependency rules, and boundary distinctions; instantiate a distinct
runtime surface only when a second independent volatility clock justifies the split.

## Read first

- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md) — full synthesis behind the boundaries
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — the load-bearing commitments
- [Functional ontology](../architecture/functional-ontology.md) — the objects boundaries reason about
- [Semantic dimensions](../architecture/semantic-dimensions.md) — the orthogonal metadata boundaries must preserve
- [CrossScopeFlow](../architecture/cross-scope-flow.md) — governed cross-scope use
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — boundary definitions and forbidden dependencies
- [Traceability matrix](../architecture/traceability-matrix.md) — principle → boundary → contract → test → issue

## The fourteen Level 2 control boundaries (+ CES stewardship)

The first fourteen entries are **Level 2 control boundaries / bounded contexts**. CES is listed
separately because it is a **cross-cutting stewardship practice**, not a runtime subsystem or an
ordinary control boundary (see [CES.md](CES.md) and SBS Part 3).

| ID | Name | Kind | Charter | Primary invariant |
|---|---|---|---|---|
| HIX | Human Interaction & Intent | Control boundary | Pending ([#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)) | Human action is explicit and attributable |
| WSP | Workspace, Scope & Principal Context | Control boundary | [WSP.md](WSP.md) | Context is not identity |
| HKA | Human Knowledge & Artifact Substrate | Control boundary | [HKA.md](HKA.md) | Durable human knowledge changes only through governed authority transition |
| SIP | Semantic Identity & Provenance | Control boundary | [SIP.md](SIP.md) | Provenance survives derivation |
| GOV | Governance, Policy, Authority & Receipts | Control boundary | [GOV.md](GOV.md) | Authority transitions require governance and receipts |
| EBF | External Boundary Fabric | Control boundary | Pending ([#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)) | External mechanisms do not become authority |
| PDM | Persistence & Data Management | Control boundary | [PDM.md](PDM.md) | Storage preserves but does not define meaning |
| DRI | Derived Representation & Indexing | Control boundary | Pending ([#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)) | Derived representations are rebuildable and never source of truth |
| RCA | Retrieval & Context Assembly | Control boundary | [RCA.md](RCA.md) | Retrieval produces candidate evidence, not truth |
| MEM | Machine Memory & Learning | Control boundary | [MEM.md](MEM.md) | Agent memory is noncanonical until promoted |
| CAO | Cognitive Capability & Agent Orchestration | Control boundary | [CAO.md](CAO.md) | Agents reason and propose; they do not mutate or execute |
| EXE | Capability Execution & Automation | Control boundary | [EXE.md](EXE.md) | Execution cannot authorize itself |
| SFC | Synchronization, Federation & Consensus | Control boundary | [SFC.md](SFC.md) | Sync preserves boundaries |
| OEF | Observability, Evaluation & Fitness | Control boundary | [OEF.md](OEF.md) | Observability is not policy |
| CES | Contract & Evolution Stewardship | Stewardship practice | [CES.md](CES.md) | Architecture evolves explicitly |

## Canonical separation rules

The charters in this set enforce the canonical separation rules from the
[context packet](../foundation/yggdrasil-architecture-context-packet.md) §5:

- **HKA** says what is durable human knowledge.
- **SIP** says how it means, derives, and relates.
- **PDM** says how it is stored.
- **RCA** finds and packages candidate context/evidence.
- **CAO** reasons and proposes.
- **MEM** remembers and advises.
- **GOV** authorizes, delegates, approves, and receipts.
- **EXE** executes only authorized side effects.
- **WSP** owns current situated context.
- **SFC** owns replicated topology over time.
- **OEF** observes and evaluates; **GOV** gives normative meaning.
- **CES** stewards architecture and contracts. CES is not runtime.

## Charters in this batch

Delivered by [#2540](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2540)–[#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2543):

- Index + template: [README.md](README.md), [\_template.md](_template.md) — [#2540](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2540)
- Knowledge / identity / persistence: [HKA.md](HKA.md), [SIP.md](SIP.md), [PDM.md](PDM.md) — [#2541](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2541)
- Governed cognition / action: [GOV.md](GOV.md), [RCA.md](RCA.md), [MEM.md](MEM.md), [CAO.md](CAO.md), [EXE.md](EXE.md) — [#2542](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2542)
- Context / sync / observability / stewardship: [WSP.md](WSP.md), [SFC.md](SFC.md), [OEF.md](OEF.md), [CES.md](CES.md) — [#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2543)

## Pending (later backlog)

These are open issues, not gaps in reasoning:

- **Pending charters:** HIX, EBF, DRI — not in this batch; tracked under epic [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533).
- **Now delivered (no longer pending):** the schemas/contracts these charters reference — metadata bundle [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544), `ContextEnvelope` [#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545), `MemoryItem` [#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546), `AuthorityTransition` [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547), `RetrievalResult` [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548) — and the ADR set [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549).
- **Tests / evals:** invariant registry [#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550), anti-contamination eval corpus [#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551), xfail skeletons [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552).

The `Required tests` named in each charter are **future** test names for #2550–#2552; this batch
creates no tests.
