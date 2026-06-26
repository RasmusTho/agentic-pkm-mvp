State: Repo-level architecture doctrine (north star). Docs-only; governs the architecture-foundation backlog (#2533–#2552). Does not claim shipped runtime behavior.
Doc role: Foundation doctrine
Authority: Concise statement of the load-bearing design commitments for Yggdrasil. It is the top of the doctrine → ontology → semantics → contracts chain and the operational north star for future humans and AI coding agents. Subordinate to its owner docs: `docs/COGNITIVE_PROSTHESIS_CHARTER.md` and `docs/PROJECT_KERNEL.md` on product intent, `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` on the target architecture, and `docs/ARCHITECTURE.md` / `docs/STATUS.md` on shipped behavior. It introduces no new architecture decisions; it distills the synthesis preserved in the context packet.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: subordinate (distills owner docs; does not replace them)
Last reviewed: 2026-06-26
Last verified against: docs/foundation/yggdrasil-architecture-context-packet.md, docs/SYSTEM_BREAKDOWN_STRUCTURE.md

# Yggdrasil Doctrine

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)

> Read this in under five minutes. It is the north star for every later architecture and
> implementation decision. When an implementation pressure tempts you to collapse a distinction
> below, **preserve the distinction and make the tradeoff explicit** instead.

This doctrine is short on purpose. The full rationale lives in the
[architecture context packet](yggdrasil-architecture-context-packet.md); the operational decomposition
lives in the [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md). This file states the
commitments those documents exist to protect.

## 1. What Yggdrasil is

Yggdrasil is a **cognitive prosthesis for a specific human**: an extended-mind store for
human-authored trails, plus a **low-trust agentic interlocutor** whose contributions must earn
promotion. It is a transactive-memory partner, not an oracle.

- It should **reduce friction, not intelligence.** It removes the cost of finding, relating, and
  recalling; it does not replace the human's judgment or take over authorship of meaning.
- The **human remains the locus of meaning and authority.** The system proposes, recalls, relates,
  and explains; the human decides what becomes durable knowledge.
- **Agent contributions are guests until promoted.** A machine suggestion, recall, or memory is
  advisory by default and becomes durable human knowledge only through an explicit, governed
  promotion — never by accumulation, similarity, or repetition.

Yggdrasil is **not** merely a database, note-search tool, RAG app, or chatbot wrapper, and it is
**not** an oracle.

## 2. The load-bearing commitments

These are settled, not open questions.

1. **Similarity is not permission.** Embedding or keyword similarity may *suggest* relevance. It
   never *grants* the right to retrieve across a boundary, cite, import, remember, or act. Only a
   typed [`CrossScopeFlow`](../architecture/cross-scope-flow.md) grants cross-scope use.
2. **Scope is frame, audience boundary, policy boundary, and provenance context — all four at
   once.** A scope is not merely a vault, a folder, or a device. It is the cognitive frame the
   material belongs to, the audience it may reach, the policy that governs it, and the provenance
   context that explains it.
3. **Provenance carries justification.** Every durable claim records not just *where it came from*
   but *why it has the standing it has*. Provenance survives derived use: projections, embeddings,
   and context bundles must carry it forward, not strip it.
4. **Memory is reconstructive and noncanonical until promoted.** Machine memory helps recall and
   reasoning. It is revisable, advisory, and **not** durable human knowledge until promoted into the
   Human Knowledge & Artifact Substrate (HKA) through governance.
5. **Projections are not evidence.** Dashboards, summaries, context bundles, embeddings, graph
   overlays, and agent answers are derived representations. They are not primary sources and cannot
   become evidence except by explicit, provenance-backed promotion.
6. **Human authority changes durable knowledge only through governed transition.** Agent proposals,
   memory promotion, repair, and sync conflict resolution must not mutate accepted human knowledge
   directly; they route through the Authority Transition / WriteGuard-equivalent governance path,
   which emits a receipt.
7. **Standards are adapters, not the ontology.** PROV-O, SKOS, ABAC/ReBAC, MCP, OpenTelemetry, and
   similar standards may be used as implementation or interoperability adapters. They do not define
   Yggdrasil's [functional ontology](../architecture/functional-ontology.md).

## 3. Distinctions that must not collapse

Future code must keep these as **different things**. Conflating any pair is an architecture
violation, not a convenience.

| Thing | What it is | What it is not |
| --- | --- | --- |
| **Human-authored material** | Content a human wrote or captured | Automatically canonical (see below) |
| **Accepted durable knowledge** | Material that has reached canonical authority state through governance | The same as merely being human-authored or merely being stored |
| **Agent memory** | Inspectable, revisable machine recall | Durable human knowledge; evidence by default |
| **Projection** | A derived/rebuildable representation (dashboard, summary, bundle, embedding) | A primary source; evidence by default |
| **Retrieval result** | Candidate evidence/context produced for a moment | Truth; authority; an admissibility decision |
| **Source artifact** | The thing material originated from | The same as the segment, projection, or claim derived from it |

The three **orthogonal role dimensions** — `source_role` (where it came from), `authority_state`
(what standing it has), and `evidence_role` (what it may do in reasoning) — answer different
questions and must never be merged into one field. See
[semantic dimensions](../architecture/semantic-dimensions.md).

> **Human-authored material is not automatically canonical.** Authorship establishes origin
> (`source_role`), not standing (`authority_state`). A captured note, a draft, and an accepted
> decision record can all be human-authored while holding different authority states. Authority is a
> governed transition, not a property of who typed the text.

## 4. How doctrine becomes real

Doctrine is inert unless it is enforced. This file constrains, in order:

1. the [functional ontology](../architecture/functional-ontology.md) — the canonical objects the
   system reasons about;
2. the [semantic dimensions](../architecture/semantic-dimensions.md) — the orthogonal metadata that
   preserves meaning across storage, indexing, retrieval, memory, and projection;
3. the [`CrossScopeFlow`](../architecture/cross-scope-flow.md) model — governed cross-scope use;
4. boundary charters, schemas/contracts, policy, ADRs, and tests/evals (later backlog items
   [#2540–#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533)).

Every principle above must trace to a control boundary, a contract, and a test/eval through the
[traceability matrix](../architecture/traceability-matrix.md). A doctrine statement with no
contract/test path is philosophy, not architecture — file the gap, do not leave it unbacked.

**When uncertain, the system proposes, confirms, or escalates rather than silently acting.**

## Related documents

- [Architecture context packet](yggdrasil-architecture-context-packet.md) — full synthesis and rationale
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) — macrodomains and control boundaries
- [Traceability matrix](../architecture/traceability-matrix.md) — principle → boundary → contract → test → issue
- [Functional ontology](../architecture/functional-ontology.md) — canonical objects
- [Semantic dimensions](../architecture/semantic-dimensions.md) — orthogonal meaning-preserving metadata
- [CrossScopeFlow](../architecture/cross-scope-flow.md) — governed cross-scope use
- Pending (later backlog): boundary charters ([#2540–#2543](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2540)), schemas/contracts ([#2544–#2548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2544)), ADRs ([#2549](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2549)), invariant/eval tests ([#2550–#2552](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2550))
