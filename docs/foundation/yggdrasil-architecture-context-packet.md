State: Draft architecture context packet. Preserves the #2533–#2552 synthesis. Docs-only; does not claim shipped runtime behavior.
Doc role: Reference / architecture context packet
Authority: Context-preservation summary for the Yggdrasil architecture-foundation backlog (#2533–#2552). It summarizes and links the doctrine, functional ontology, semantic distinctions, system breakdown, separation rules, and load-bearing invariants behind that backlog. It is subordinate to its owner docs: `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` on the target SBS, `docs/COGNITIVE_PROSTHESIS_CHARTER.md` and `docs/PROJECT_KERNEL.md` on product intent, and `docs/ARCHITECTURE.md` / `docs/STATUS.md` on current shipped behavior. It does not introduce new architecture decisions.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: subordinate (summarizes owner docs; does not replace them)
Last reviewed: 2026-06-26
Last verified against: docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/COGNITIVE_PROSTHESIS_CHARTER.md, docs/PROJECT_KERNEL.md, docs/architecture/SBS_OPERATING_MODEL.md

# Yggdrasil Architecture Context Packet

Status: Draft / Architecture context packet
Parent issue: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)
Created for: [#2553](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2553)
Purpose: Preserve the doctrine, ontology, semantic, and system-design synthesis behind #2533–#2552 so future work does not depend on conversation history.

> Audience: any human or AI agent about to work on the architecture-foundation backlog (#2533–#2552). Read this packet before opening those issues. It is context preservation, not a replacement for an issue body or an owner doc.

---

## 1. Why this packet exists

The architecture-foundation work produced a deliberate chain:

`dogma → cognitive grounding → functional ontology → semantic distinctions → system breakdown → contracts → tests → implementation`

Each child issue in #2533–#2552 is mostly self-contained for local execution, but the full rationale — *why* the issues exist and *how* they fit together — still lived partly in the conversation that produced them. This packet exists to make the repository independent of that conversation. A future human or AI agent should be able to recover the architecture direction from the repo alone.

The risk this packet addresses is silent collapse of the distinctions the backlog is meant to protect. Without preserved context:

- Future agents may execute local issues without understanding the whole doctrine → ontology → semantics → system-design chain.
- The system breakdown may degrade into documentation instead of remaining an architecture force.
- `general_knowledge: true` may reappear as a global cross-scope bypass.
- `source_role`, `authority_state`, and `evidence_role` may be collapsed into one field again.
- Scope may be treated as vault / folder / device instead of frame / audience / policy / provenance context.
- Memory, retrieval, projection, execution, observability, and storage may drift into hidden authority.

This packet is intended to be stable. Changes to it should be intentional and traceable.

## 2. Final governing thesis

> Yggdrasil is a cognitive prosthesis for a specific human: an extended-mind store for human-authored trails, plus a low-trust agentic interlocutor whose contributions must earn promotion. Its functional ontology is a scoped provenance-and-capability graph. A scope is simultaneously a cognitive frame, an audience boundary, a policy boundary, and a provenance context. Similarity may suggest relevance, but only typed CrossScopeFlow grants permit cross-scope use. Provenance carries justification; authority is a governed state transition; memory is reconstructive and revisable; agent memory is noncanonical by default. Deterministic components enforce these distinctions through metadata propagation, retrieval prefilters, authority-transition gates, audit traces, and regression tests.

Clarifications:

- Yggdrasil is **not** merely a database, note-search tool, RAG app, or chatbot wrapper.
- It is also **not** an oracle.
- The human remains the locus of meaning and authority.
- The system should reduce friction, not intelligence.

## 3. Settled corrections from the synthesis

These are settled decisions, not open questions.

1. **Standards are adapters, not the ontology.** PROV-O, SKOS, ABAC/ReBAC, MCP, OpenTelemetry, and similar standards may be used as implementation or interoperability adapters, but they do not define Yggdrasil's ontology by themselves.
2. **`general_knowledge: true` is not a universal bypass.** General reusable knowledge can exist, but cross-scope use must be governed by typed flows — never by a global boolean that waves material across every scope.
3. **Typed `CrossScopeFlow` replaces global cross-scope booleans.** Cross-scope movement must specify source scope, target scope, operation, evidence role, redaction, confirmation, expiry, audit, and provenance requirements.
4. **`source_role`, `authority_state`, and `evidence_role` are orthogonal.** Do not collapse them into one field. Origin, standing, and reasoning-use answer different questions.
5. **Retrieval produces candidate evidence/context, not truth.** Retrieval may find and rank candidates. It does not create authority, admissibility, or evidence status by itself.
6. **Projection is not evidence.** Dashboards, summaries, context bundles, embeddings, graph projections, and agent answers are derived representations. They are not primary sources unless explicitly stored and promoted through governance.
7. **Agent memory is advisory and noncanonical until governed promotion.** Machine memory may help recall and reasoning, but it is not durable human knowledge by default.
8. **Durable human knowledge changes only through Authority Transition Flow / WriteGuard-equivalent governance.** Agent proposals, memory promotion, repair, and sync conflict resolution must not mutate durable knowledge directly.
9. **Parent/master aggregation is not sibling sharing.** A parent/master vault may aggregate configured descendants. Child and sibling scopes remain isolated unless an explicit cross-scope allowance exists.
10. **Observability is not policy.** OEF can show and evaluate what happened. GOV gives normative meaning, policy decisions, authority receipts, and accountability.

## 4. Current system breakdown position

This section summarizes the target architecture defined in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`.

> Important: the system breakdown is the **target** architecture, not necessarily an exact map of what is already built in runtime. Current shipped behavior remains owned by `docs/ARCHITECTURE.md` and `docs/STATUS.md`.

### Level 1 macrodomains

| Macrodomain | Meaning |
| --- | --- |
| Human Authority Kernel | Human authority, durable knowledge, semantic identity, provenance, policy, and receipts. |
| Cognitive Context & Topology | Workspace, scope, principal, device, replica, sync posture, and situated context. |
| Human Experience | Human-facing reading, writing, approval, rejection, correction, explanation, and navigation. |
| External Boundary | Providers, tools, models, parsers, editors, APIs, and other external adapters. |
| Machine Substrate | Persistence, indexes, embeddings, projections, and rebuildable representations. |
| Cognitive Augmentation | Retrieval, context assembly, memory, learning, capabilities, and agent orchestration. |
| Governed Execution | Authorized side effects, tool use, automation, dry-run, preview, rollback, and execution status. |
| Trust, Fitness & Evolution | Observability, evals, audit visibility, architecture fitness, contracts, ADRs, and evolution. |

### Level 2 control boundaries

| ID | Boundary |
| --- | --- |
| HIX | Human Interaction & Intent |
| WSP | Workspace, Scope & Principal Context |
| HKA | Human Knowledge & Artifact Substrate |
| SIP | Semantic Identity & Provenance |
| GOV | Governance, Policy, Authority & Receipts |
| EBF | External Boundary Fabric |
| PDM | Persistence & Data Management |
| DRI | Derived Representation & Indexing |
| RCA | Retrieval & Context Assembly |
| MEM | Machine Memory & Learning |
| CAO | Cognitive Capability & Agent Orchestration |
| EXE | Capability Execution & Automation |
| SFC | Synchronization, Federation & Consensus |
| OEF | Observability, Evaluation & Fitness |
| CES | Contract & Evolution Stewardship |

> Level 2 entries are control boundaries / bounded contexts. They are not necessarily one-to-one runtime services. Commit now to the macrodomains, the dependency rules, and the boundary distinctions; instantiate a distinct Level 2 implementation surface only when a second independent volatility clock justifies the split.

## 5. Control-boundary separation rules

Canonical separation rules:

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
- **OEF** observes/evaluates.
- **GOV** gives normative meaning.
- **CES** stewards architecture and contracts. CES is not runtime.

Why these rules matter — each prevents a specific collapse:

- HKA / SIP / PDM prevent storage or indexes from becoming meaning.
- RCA / GOV / SIP prevent retrieval from becoming truth.
- MEM / GOV / HKA prevent memory from becoming hidden authority.
- CAO / GOV / EXE prevent agents and execution from becoming superusers.
- WSP / SFC prevent current context from being confused with replicated topology.
- OEF / GOV prevent observability from becoming policy.
- CES prevents architecture process from becoming runtime control.

## 6. Load-bearing invariants

1. Similarity is not permission.
2. Scope is frame, audience boundary, policy boundary, and provenance context.
3. Provenance carries justification.
4. `source_role`, `authority_state`, and `evidence_role` are orthogonal.
5. Agent memory is noncanonical by default.
6. Cross-scope use requires typed `CrossScopeFlow`.
7. Retrieval is candidate generation, not truth.
8. Projection is not evidence.
9. Durable human knowledge changes only through governed authority transition.
10. Execution cannot authorize itself.
11. Storage preserves but does not define meaning.
12. Parent aggregation is not sibling sharing.
13. Sync preserves boundaries.
14. Observability is not policy.
15. Standards are adapters, not the ontology.
16. Human-authored material is not automatically canonical; authority state still applies.
17. Context bundles are projections, not primary sources.
18. Memory promotion requires governance and materialization into HKA.
19. Derived/rebuildable representations must preserve metadata and provenance.
20. When uncertain, the system should propose, confirm, or escalate rather than silently act.

## 7. Core artifact chain

The intended climb-out sequence — conceptual and contract spine first, runtime last:

`SYSTEM_BREAKDOWN_STRUCTURE → traceability matrix → doctrine → ontology → semantic dimensions → CrossScopeFlow → boundary charters → schemas/contracts → ADRs → invariant registry → eval fixtures → xfail tests → runtime vertical slice`

This order exists to prevent jumping into runtime implementation before the conceptual and contract spine is stable. Each step constrains the next: the doctrine governs the ontology, the ontology grounds the semantic dimensions, the semantic dimensions and CrossScopeFlow shape the charters and contracts, and the contracts are what the eval fixtures and xfail tests pin down before any runtime code is written.

## 8. First later runtime vertical slice

The first later implementation slice was:

`Capture → Metadata bundle → DRI segment → Retrieval prefilter → RCA result → ContextEnvelope`

> **Status (2026-06-28): DELIVERED.** Runtime Slice 1 (epic [#2578](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2578), children #2579–#2586) implemented this chain as the new top-level **`yggdrasil_runtime`** package — a corpus-backed conformance harness over `tests/evals/fixtures/` (NOT an `app/` rewire). Entry points: `yggdrasil_runtime.capture.capture`, `.dri.derive_segment`, `.retrieval.retrieve`, `.cross_scope.evaluate`, `.context.assemble_envelope`, over a shared immutable `yggdrasil_runtime.metadata.MetadataBundle`. The eight targeted invariants are now `runtime_test`-enforced (see the invariant registry Coverage map and traceability-matrix rows 1–3, 5–7, 16); the deliberately-left future-slice invariants remain xfail, locked by `tests/invariants/test_invariant_residue.py`. The "Intentionally later" items below are still deferred.

> Naming note (do not duplicate an existing contract): `ContextEnvelope` (#2545) is a **new** contract for the *bounded agent operating context*. It is distinct from the existing RCA `ContextBundle` (`docs/contracts/CONTEXT_BUNDLE.md`), which carries scoped candidate evidence with provenance and relevance explanation. The envelope is expected to **compose** an RCA `ContextBundle` (plus scope, authority posture, and memory bindings) — not rename or replace it. When the need is evidence packaging, extend `ContextBundle`; define `ContextEnvelope` only for the bounded operating-context contract in #2545.

Intentionally later (not in scope for the foundation backlog, and explicitly deferred):

- memory runtime;
- durable mutation;
- sync;
- external execution;
- full agent orchestration;
- broad policy engine;
- production cross-scope automation.

## 9. Child issue map

Epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) — stabilize doctrine, ontology, semantics, and system contracts.

| Order | Issue | Purpose |
| --- | --- | --- |
| 0 | [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) | Epic: stabilize doctrine, ontology, semantics, and system contracts. |
| 1 | [#2553](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2553) | Create this self-contained architecture context packet. |
| 2 | [#2534](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2534) | Stabilize `SYSTEM_BREAKDOWN_STRUCTURE.md` language and control-boundary ownership. |
| 3 | [#2535](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2535) | Create traceability matrix from doctrine to implementation issues. |
| 4 | [#2536](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2536) | Create concise Yggdrasil doctrine as repo-level north star. |
| 5 | [#2537](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2537) | Define canonical functional ontology terms. |
| 6 | [#2538](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2538) | Define orthogonal semantic dimensions. |
| 7 | [#2539](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2539) | Define typed `CrossScopeFlow` and retire global `general_knowledge` bypass semantics. |
| 8 | [#2540](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2540) | Create boundary charter template and index. |
| 9 | [#2541](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2541) | Create HKA, SIP, and PDM charters. |
| 10 | [#2542](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2542) | Create GOV, RCA, MEM, CAO, and EXE charters. |
| 11 | [#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2543) | Create WSP, SFC, OEF, and CES charters. |
| 12 | [#2544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544) | Define metadata bundle schema. |
| 13 | [#2545](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2545) | Define `ContextEnvelope` contract (bounded agent operating context; new — distinct from the existing RCA `ContextBundle`, see §8). |
| 14 | [#2546](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2546) | Define `MemoryItem` contract and promotion boundary. |
| 15 | [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547) | Define `AuthorityTransition` contract. |
| 16 | [#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2548) | Define `RetrievalResult` contract and candidate-evidence semantics. |
| 17 | [#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549) | Create ADR set for doctrine, ontology, and boundary decisions. |
| 18 | [#2550](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550) | Create invariant test registry. |
| 19 | [#2551](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2551) | Create anti-contamination eval fixture corpus. |
| 20 | [#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2552) | Add initial xfail invariant/eval test skeletons. |

Recommended execution order:

`#2553 → #2534 → #2535 → #2536 → #2537 → #2538 → #2539 → #2540 → (#2541 / #2542 / #2543) → (#2544 / #2545 / #2546 / #2547 / #2548) → #2549 → #2550 → #2551 → #2552`

The grouped issues (#2541–#2543 boundary charters, and #2544–#2548 contracts) can each be worked in parallel within their group once the preceding spine (doctrine, ontology, semantic dimensions, CrossScopeFlow, charter template) is stable.

The traceability matrix that connects doctrine → ontology → boundaries → contracts → issues is itself a backlog item (#2535). Once it lands, this packet's child issue map and the matrix should agree; the matrix is the finer-grained, maintained mapping and this packet is the one-sitting overview.

## 10. How future agents should use this packet

- Read this packet before working on #2534–#2552.
- Treat this packet as **context preservation**, not as a replacement for the specific issue body. The issue is still the binding task contract.
- If an issue seems locally clear but conflicts with this packet, **stop and raise an architecture question** rather than resolving the conflict silently.
- If a new term, boundary, or invariant is introduced, update the traceability matrix (#2535) and consider an ADR (#2549).
- If implementation pressure suggests collapsing a distinction (for example, merging `source_role` / `authority_state` / `evidence_role`, or re-adding a global `general_knowledge` bypass), **preserve the distinction and make the tradeoff explicit** instead.
- Do not rely on conversation history. If something needed to proceed is not in the repo, that is a gap to file, not a reason to reconstruct intent from chat.
