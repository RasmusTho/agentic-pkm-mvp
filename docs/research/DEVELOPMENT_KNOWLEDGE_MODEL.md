State: Advisory research grounding + candidate subsystem specification (2026-07-07). Proposes a new Builder System subsystem — a continuously-synthesized, evidence-backed capability model of the Yggdrasil platform. Nothing here is built or ratified by this doc; it surfaces owner decisions (OD-K1..OD-K5) and, if accepted, would be enacted by a future ADR. Not Product/Runtime truth.
Doc role: Research / candidate subsystem proposal (SRS)
Authority: Advisory. Subordinate to `AGENTS.md :: Total Cost of Development`, `docs/adr/ADR-0010-builderops-vault-authority-boundary.md` (BuilderOps authority boundary), `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (capability/boundary decomposition), `docs/CAPABILITY_CONTRACT_MODEL.md` (what a capability is), and `docs/architecture/traceability-matrix.md` (the static precursor this generalizes). It does not introduce runtime behavior, a new authority class, or a new source of truth.
Owner: BuilderOps governance / Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed (external prior-art synthesis + this repo's canonical builder/architecture docs)
Last reviewed: 2026-07-07
Last verified against: docs/CAPABILITY_CONTRACT_MODEL.md, docs/SYSTEM_BREAKDOWN_STRUCTURE.md, docs/architecture/traceability-matrix.md, docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md, docs/adr/ADR-0010-builderops-vault-authority-boundary.md, docs/development/BUILDER_CAPABILITY_PORTFOLIO.md, docs/foundation/yggdrasil-architecture-context-packet.md, docs/testing/invariant-tests.md

# The Development Knowledge Model — Capability Knowledge Graph for the Builder System

> **Candidate subsystem proposal.** This document is the research grounding and draft Software Requirements Specification for a new Builder System subsystem that continuously constructs and maintains an evidence-backed model of *what the Yggdrasil platform currently is* — its capabilities, their maturity, and the evidence behind each. It is advisory. The binding decision, if the owner accepts, belongs in a future ADR. This doc changes no runtime behavior and claims no authority.

## TL;DR

- Yggdrasil's development knowledge is fragmented across code, git, PRs, Issues, ADRs, specs, tests, CI, and AI sessions. Every source describes *part* of the system; **none describes the system itself**. Traditional ALM answers "what's next / what's done." It cannot answer "what capabilities exist, how mature is each, where are the gaps."
- The proposed subsystem — provisionally the **Capability Knowledge Model (CKM)**, codename candidate **Kvasir** — inverts the primary abstraction. Instead of Issues/Commits/Docs as first-class entities, the primary entity is the **Capability**; every engineering artifact becomes **Evidence** about one or more capabilities; **maturity** is a synthesized, explainable judgment over that evidence.
- **Prior art verdict: genuine whitespace, precisely bounded.** Developer portals model *services* (deployable units), not capabilities. Engineering-intelligence platforms measure the *development process* (flow, DORA/SPACE), not *product state*. Architecture-KM tools *check the system against a human-authored model* (reflexion models, fitness functions, ADRs) or *recover structure* (vFunction, CAST) but never synthesize a per-capability maturity picture. AI-native tools circle the concept from four sides (repo maps, DeepWiki, agent memory, spec-driven dev) but none maintains a capability→evidence→maturity model. The **novel composition** is: capability nodes ← evidence-typed artifact edges → *synthesized, explainable maturity*, kept live.
- **Terminology discipline.** This is **not a "digital twin"** (that term requires automated bidirectional writeback per the ICSE-2025 taxonomy; a read/synthesis system is a **digital shadow / living model**). The strongest conceptual lineage is the **assurance case / Goal Structuring Notation** (claim ← evidence) and the **traceability** standards (OSLC/SEON). We adopt "capability," "evidence," and "assessment" deliberately from those lineages.
- **Fit to Yggdrasil.** This is the **continuously-synthesized generalization of the existing static `traceability-matrix.md`** (#2535), built on the **BuilderOps** evidence/receipt substrate (ADR-0010), reusing the **Capability Contract Model** definition and the **SBS** decomposition. It lives in the **analytical + projection** authority plane — it is *never* authority, *never* a source of truth, and must self-identify as a projection. It conforms to the doctrine's load-bearing rule that *derived views are candidate, not truth*.
- **Recommendation:** a Reality-MVP that (a) seeds capabilities from SBS + the Capability Contract Model, (b) ingests the artifacts the repo already emits, (c) computes a seven-dimension explainable maturity vector, and (d) publishes a read-only projection + the Development Overview UI. Five owner decisions (OD-K1..OD-K5) gate the build.

---

# Part I — Research

## 1. Literature Review

The vision touches five adjacent fields. Each has built part of the machinery; none has built this object. The consistent pattern: the industry has spent two decades fighting *architectural knowledge vaporization* (Jansen & Bosch 2005) either by asking humans to author a model and then policing drift against it, or by recovering code *structure* — never by reconstructing a **capability-maturity** model from the evidence the system already emits.

### 1.1 Architecture Knowledge Management & Living Architecture

The founding failure of AKM is **knowledge vaporization**: a system's real architecture is its set of design decisions plus rationale (Jansen & Bosch, *"Software Architecture as a Set of Architectural Design Decisions,"* 2005), most of which is never captured and evaporates as the system evolves. **ADRs** (Nygard; MADR, Log4brains, adr-tools) are the de-facto instrument — but they are *hand-authored* and capture nothing on their own.

Drift/erosion detection is mature but always **conformance against a human-authored intent**:
- **Reflexion Models** (Murphy, Notkin & Sullivan, 1995) — the seminal technique: a human posits a high-level model + a code→model mapping; the tool computes **convergences / divergences / absences**. Still the reference frame for erosion analysis.
- **Dependency Structure Matrices** (Lattix, Structure101) — discover the real dependency graph, enforce declared layering.
- **Architecture fitness functions** (Ford/Parsons/Kua, *Building Evolutionary Architectures*) and tools **ArchUnit / NetArchTest / NDepend CQLinq** — assert rules in CI. Fitness functions score *distance to a human-declared objective*; they never construct a model.
- **Living Documentation** (Martraire) anchors knowledge to a single source of truth and fails CI on divergence — but its "living diagrams" are *curated projections of human-annotated code*, not an independently discovered model.
- **C4 / Structurizr, arc42** — entirely hand-authored; do not inspect the codebase.

The vocabulary that frames all of this is **prescriptive vs. descriptive architecture**: erosion is the growing delta between the intended (forward-engineered) and the recovered (from implementation) model.

On the *synthesis* side (sparse): architecture **recovery/reconstruction** (Murphy source models; ARM), and evidence-constructors — **vFunction** (fuses static bytecode + dynamic runtime traces into a learned meta-model, then detects drift against it), **CAST Imaging** (richest static structural blueprint), **CAST Highlight** (the one tool framing output as *capability-readiness*: cloud/AI maturity scores — but via pattern heuristics on a snapshot, not a live evidence-built inventory), **CodeScene** (behavioral model from git history: hotspots, Conway's-Law alignment), **Moderne/OpenRewrite** (lossless semantic tree, aimed at transformation). The 2026 LLM wave — **AgenticAKM** (Extractor/Retriever/Generator/Validator agents that recover architecture and draft ADRs) — is the closest emerging analog, but produces *one-time ADR documentation*, estimates no maturity, and is not continuously maintained.

**Gap:** evidence synthesis into an *explainable, per-capability maturity estimate over heterogeneous artifacts* (code + ADRs + tests + docs + commits → maturity with rationale) has no direct prior art. The ingredients are proven in isolation; the composition is open.

### 1.2 Engineering Intelligence / Software Analytics (SEI)

Gartner formalized **Software Engineering Intelligence platforms** (2024 Market Guide): tools giving leaders "data-driven visibility into the engineering team's use of time and resources … and progress on deliverables." Two decisive facts: the **unit of analysis is the process** (teams, developers, PRs, deployments, cycle/lead time), and they "typically collect only **metadata**." The field maps cleanly onto process-measurement: **LinearB** (PR/cycle-time), **Jellyfish** (effort→investment-category alignment), **DX** (DORA + SPACE + surveys), **Swarmia, Sleuth** (deploy intelligence), **Faros AI** (200+ connectors → unified graph *of engineering operations*), **CodeScene / SonarQube / Sourcegraph Code Insights** (code-state: health, hotspots, coverage, migration progress — organized by *files/modules*, never capabilities).

Metrics frameworks reinforce this: **DORA** (four delivery-process metrics), **SPACE** (multi-dimensional productivity), academic **software analytics** (Menzies & Zimmermann — objects of study are defects, developer behavior, evolution). All answer *"how fast/well is the team producing changes?"* — never *"what does the system do and how complete is each capability?"*

The one field that genuinely maps capabilities↔code is academic and delivers **point techniques, not maintained models**:
- **Feature location** (Dit, Revelle, Gethers & Poshyvanyk, *JSME 2013* — 89-paper taxonomy: textual/static/dynamic/hybrid) answers "which code implements feature X" *per query, point-in-time*.
- **Requirements traceability / trace-link recovery** (20-year thread: IR/VSM/LSI → ML → LLM/RAG) links *stated requirements* to code/tests; presupposes a requirements corpus, produces a link matrix. Commercial RTM automation exists only in regulated ALM (Jama, Polarion, DOORS, Azure DevOps).

**Gap:** a subsystem that reconstructs and *continuously maintains* a capability/feature inventory with per-capability maturity sits in whitespace between metadata-only SEI (product-agnostic by design) and one-shot academic recovery.

### 1.3 Developer Portals / Service Catalogs

Every product here is organized around **services/components** (deployable, ownable units), not capabilities.
- **Backstage** — fixed System Model (`Component`/`API`/`Resource`/`System`/`Domain`), declared in `catalog-info.yaml` (manual/scaffolded/auto-discovered); scoring via **Tech Insights** Fact Retrievers → FactChecker rules → **Scorecards**.
- **Cortex** — Service + custom entity types (JSON Schema); aggressive auto-discovery; Scorecards in CQL; **Initiatives** drive migrations.
- **OpsLevel** — the maturity **Rubric**: Checks in Categories across ordered Levels (bronze/silver/gold); strict ladder (pass all checks at a level to attain it).
- **Port** — most explicitly graph-based: **Blueprints** + typed **Relations**; Scorecards 2.0 wire failed rules to self-service remediation actions.
- **Compass** — weighted criteria summing to 100%; metric thresholds (incl. JQL).

Cross-cutting: entity = deployable/ownership unit; maturity = **rule-over-current-state** (largely boolean); evidence = *ingested telemetry mapped to a service*; traceability = essentially none (`dependsOn`/`providesApi` are structural/runtime, not requirement→test→docs). None models a functional capability as first-class; none treats ADRs, design docs, or AI sessions as evidence at all.

**Gap:** the node is a deployable, not a capability; maturity is a checklist, not evidentiary confidence; there is no requirement→architecture→code→test→docs lineage.

### 1.4 Knowledge Graphs, Digital Twins, Capability-Centric Systems Engineering

**Software knowledge graphs** are mature but operate at the code/artifact level: the **Code Property Graph** (Yamaguchi; Joern), **SCIP/LSIF** (Sourcegraph), GitHub's dependency graph. Ecosystem/process graphs — **CHAOSS/GrimoireLab** (30+ sources → 150+ health metrics) — are the closest deployed "many artifacts → synthesized indicators," but the indicators are *project health*, not capability maturity. Ontology/traceability substrates exist: **SEON** (Software Engineering Ontology Network) and **OSLC** (OASIS standard; RDF/Linked-Data linking requirements↔change↔test↔architecture across tools). These give the *substrate* but stop short of capability-maturity synthesis.

**Digital twins.** The term is nascent and process-oriented. **Gartner DTO** (Digital Twin of an *Organization*) twins the business/process via EA + process mining. *"Digital Twins for Software Engineering Processes"* (Nier et al., **ICSE 2025 NIER**) finds explicitly that a holistic SE digital twin **does not yet exist**, and — critically — a true digital twin needs **automated bidirectional data flow** (senses *and* acts back). By the Kritzinger taxonomy, a read-only representation with automated one-way sync is a **digital shadow**; with manual sync, merely a **digital model**. **Calling this subsystem a "digital twin" would overclaim.**

**Capability-centric systems engineering.** "Capability" is a well-established first-class primitive — but at *enterprise/mission* altitude: **DoDAF Capability Viewpoint** (CV-1..CV-7; capability taxonomy, phasing, capability-to-services mapping), **ArchiMate** Capability (Strategy layer) + TOGAF **Capability-Based Planning** + **BIZBOK** business capability maps, **Arcadia/Capella** Operational Capabilities. Maturity modeling is established via **CMMI** (5 levels) — but CMMI measures *process* maturity, not product-feature maturity.

**Gaps & terminology guidance:**
- Capability-as-primitive is real, but every framework defines it at organizational altitude. This project's usage — *a functional ability of a software product* ("Semantic Search") — is a legitimate **product/application capability** specialization that must be explicitly disambiguated from the EA/DoDAF sense.
- The specific pattern — **capability nodes ← evidence-typed artifact edges → synthesized maturity** — has no direct precedent. The closest conceptual precedent is the **assurance/safety case** — **Goal Structuring Notation (GSN)** and OMG **SACM** — where claims are backed by *evidence* nodes. Adopt that vocabulary.
- Prefer **"capability knowledge graph / living model / digital shadow of the codebase's capabilities."** Reserve "digital twin" for a future closed-loop version that writes back.

### 1.5 AI-Native Development & Engineering Memory

The field circles this concept from four sides but occupies none of the center:
1. **Retrieval / repo maps** (dominant, but *not a maintained model*): **Aider** (tree-sitter symbol graph + PageRank ranking, regenerated per request), **Cursor** (tree-sitter chunks → embeddings + Merkle-tree change sync), **Sourcegraph Cody** (permissioned RAG at monorepo scale). Embeddings answer "where is code like X"; they hold no model of what the system *does*.
2. **Auto-generated wikis**: **Cognition DeepWiki** (architecture overview, diagrams, grounded Q&A with citations) — the closest shipped "knowledge model," but it produces *navigational/explanatory docs of current structure*, with **no capability inventory, no maturity scoring, no gap detection, no intended-vs-delivered axis**, and regenerates rather than being incrementally maintained. **Potpie** (AST→Neo4j graph) targets agent operation, not a maturity ledger.
3. **Agent memory**: **Letta/MemGPT** (tiered self-editing memory), **Zep/Graphiti** (temporal knowledge graph — facts with `valid_from`/`valid_to`, time first-class), **Mem0** ("remember your codebase"), **Cognee** (repo→AST→KG incl. architectural decisions), **CLAUDE.md/AGENTS.md auto-memory** (the one incumbent where an agent both reads and maintains a knowledge file — but unstructured prose, not a capability/maturity schema). Oriented at *interaction memory*, not product state.
4. **Spec-driven development** (structured, maintained, but anchored on *intent* not *assessed capability*): **AWS Kiro** ("spec is source of truth, code is a build artifact"; EARS requirements → design → tasks), **GitHub Spec Kit**, **Tessl** (spec registry + specs-as-long-term-memory).

Research on LLM maturity/gap estimation is thin and not codebase-scoped (postcondition maturity of *code LLMs*; per-file completeness checks) — none maintains a whole-repo capability→evidence→maturity ledger.

**Gap (the missing middle):** between *retrieval* ("where is code like this") and *interaction memory* ("what did we decide"), there is no **semantic model of the product's capabilities, each with realizing evidence and an assessed maturity, kept current by the same agents that build.** This is the exact object proposed here.

## 2. Competitive Analysis

| System / class | Primary entity | Maturity mechanism | Evidence model | Auto-constructed? | Requirement→test→docs traceability | Why it does *not* satisfy the vision |
| --- | --- | --- | --- | --- | --- | --- |
| Backstage / Roadie | Component/Service | Tech-Insights rules → Scorecards | Telemetry mapped to entity | Partly (YAML/discovery) | No | Node is a deployable, not a capability; boolean checks; ADRs/AI-sessions not evidence |
| Cortex / OpsLevel / Port / Compass | Service (+ custom types) | Rule ladders (bronze/gold) or weighted % | Integration telemetry | Partly | No | Same service-centric posture; maturity is a checklist over current infra state |
| LinearB / Jellyfish / DX / Faros | Team / PR / deploy | DORA/SPACE metrics | Process metadata | Yes | No | Measures the *process of building*, never the *state of what's built* |
| CodeScene / SonarQube / Sourcegraph | File / module / symbol | Code health, coverage, hotspots | Code + git history | Yes | Partial (code only) | Models *code structure/behavior*, organized by files — not capabilities or their maturity |
| vFunction / CAST Imaging | Component / dependency | Drift vs. learned baseline (vFunction); readiness heuristics (CAST Highlight) | Static + runtime | Yes | No | Recovers *structure*; CAST Highlight rates readiness on a snapshot, not a live per-capability evidence inventory |
| C4/Structurizr, arc42, ADRs | Hand-authored elements | None (or CI conformance) | None (human-authored) | No | Manual | Entirely hand-authored; the vaporization problem restated, not solved |
| DeepWiki / Potpie | File / symbol | None | Code (AST/embeddings) | Yes | No | Navigational docs of current structure; no maturity, no gaps, no intended-vs-delivered |
| Zep / Cognee / Mem0 / Letta | Fact / memory / code entity | None | Sessions + code KG | Yes | No | Interaction/session memory; not a capability-maturity ledger |
| Kiro / Spec Kit / Tessl | Spec / requirement | None (specs are intent) | Specs in-repo | Authored | Forward (spec→code) | Anchors on *intended* capability; no *assessment* of delivered capability from evidence |
| DoDAF CV / TOGAF-ArchiMate | Capability (enterprise) | CMMI-style / phasing | Manual EA models | No | Manual | Capability at organizational altitude; hand-modeled; not evidence-synthesized from a codebase |
| GSN / SACM assurance cases | Claim ← Evidence | Argument sufficiency (human) | Evidence artifacts | No | Manual | **Closest conceptual precedent** (evidence-backed claims) but hand-constructed, safety-scoped, no maturity synthesis |
| **CKM (this proposal)** | **Capability** | **Explainable 7-dim synthesized maturity** | **All artifacts as typed evidence** | **Yes (continuous)** | **Yes (capability→req→arch→code→test→docs→session)** | — |

**Reading of the table.** No incumbent occupies the intersection of *(capability as primary entity) × (heterogeneous artifacts as evidence) × (synthesized explainable maturity) × (continuous auto-construction) × (full vertical traceability)*. Each competitor owns one or two columns. The vision is the composition, and the composition is unclaimed.

## 3. Concept Proposal — Does This Already Exist? Terminology.

**Verdict: the *ingredients* exist and are proven; the *composition* is genuine whitespace.** The subsystem is best understood as the fusion of four proven ideas that have never been combined around *capabilities-with-maturity*:

1. **Traceability substrate** (OSLC/SEON, the repo's own `traceability-matrix.md`) — the artifact-linking graph.
2. **Assurance-case argumentation** (GSN/SACM) — claims backed by typed evidence, with an explicit sufficiency judgment.
3. **Capability-based modeling** (DoDAF CV / ArchiMate), re-scoped from enterprise to *product* capability.
4. **Agentic synthesis** (AgenticAKM, DeepWiki, LLM feature-location) — LLM reconstruction of meaning from heterogeneous artifacts.

### Recommended terminology

- **Do not call it a "digital twin."** It is a **digital shadow / living model** until it writes back (ICSE-2025 / Kritzinger). Reserve "twin" for a future closed-loop version.
- **Descriptive name (lead with this):** **Capability Knowledge Model (CKM)**, whose data structure is a **Capability Evidence Graph (CEG)**. This is parallel to, and deliberately distinct from, the existing **Capability *Contract* Model** (which defines *what a capability is*; the CKM *assesses which capabilities exist and how mature they are*).
- **Capability** — define explicitly as a **product/application capability**: a reusable, surface-independent functional ability of the Yggdrasil platform (e.g. "Semantic Search," "Voice Capture"). Note the relation to — and distinction from — the DoDAF/ArchiMate/BIZBOK *organizational* sense. This reuses the definition already in `docs/CAPABILITY_CONTRACT_MODEL.md`.
- **Evidence** — adopted from the assurance-case lineage: any artifact that raises or lowers confidence in a capability claim. Orthogonal to the existing `evidence_role` runtime dimension (see §Reconciliation; naming overlap is acknowledged and bounded).
- **Assessment / Maturity** — a *synthesized, explainable* judgment, never a boolean checklist.
- **Codename candidate: Kvasir.** In the Norse register already governing the ecosystem (ADR-0043: Yggdrasil, Mimer, Munin, Hugin, Heimdal, Bifrost), **Kvasir** is the being born from the synthesis of *all* the gods' knowledge, so wise he could answer any question — the exact function of this subsystem. Adopting it requires an ADR-0043 name-register entry; the descriptive term **CKM** remains primary in specs and code.

---

# Part II — Specification

## 4. Refined System Vision

> The **Capability Knowledge Model (CKM)** is the Builder System's architectural memory: a continuously-synthesized, evidence-grounded **digital shadow** of the Yggdrasil platform. It reconstructs — from the artifacts the system already emits — a hierarchical model of the platform's **capabilities**, treats every engineering artifact as **evidence** attached to one or more capabilities, and derives an **explainable maturity assessment** for each. It answers the questions no ALM tool answers: *what can this system do, how mature and how well-evidenced is each ability, where are the largest gaps, and how has the architecture evolved.* It is a **projection, never an authority**: its conclusions are candidate context for human and agent decisions, not truth, and it self-identifies as derived. Its primary product is the maintained model; the Development Overview UI is one consumer among many (agents, gates, reports).

This reframes the draft in systems-engineering terms:
- The **System of Interest** is the Yggdrasil *product* (Mimer + constituents). The CKM is an **enabling system** in the ISO/IEC/IEEE 15288 sense (per `docs/architecture/system-context-overlay.md`) — it observes and models the SoI without being part of its runtime.
- The model is a **descriptive** architecture representation (recovered from implementation) held against **prescriptive** intent (requirements/ADRs/SBS). Their delta *is* the gap/drift signal (reflexion-model framing).
- Maturity is an **assurance argument**: for each capability, "is there sufficient evidence that this ability exists, works, is integrated, is operable, and is stable?"

## 5. Software Requirements Specification

### 5.1 Introduction & Purpose

This SRS specifies the CKM subsystem of the Yggdrasil Builder System. Its purpose is to eliminate *development-knowledge fragmentation*: the condition where no single artifact describes the platform as a whole, forcing humans and agents to reconstruct system understanding ad hoc from a dozen partial sources. The CKM maintains that understanding as a first-class, queryable, continuously-updated model.

### 5.2 Scope

**In scope:** capability modeling, artifact ingestion, evidence association, capability-relationship inference, maturity assessment, gap/missing-evidence/drift detection, capability-evolution history, AI-assisted summarization, vertical navigation (capability → requirement → architecture → implementation → tests → docs → AI sessions), and read-only projection surfaces (API + Development Overview UI).

**Out of scope (Non-Goals):** the CKM is **not** Jira/GitHub Projects/Azure DevOps/Linear/Trello, **not** sprint planning, **not** story-point estimation, **not** a task board, and **not** a source of authority. It synthesizes; it does not plan work or mutate product/runtime truth. It complements ALM by reading it, not replacing it.

### 5.3 Definitions

| Term | Definition |
| --- | --- |
| **Capability** | A reusable, surface-independent functional ability of the Yggdrasil product (per `CAPABILITY_CONTRACT_MODEL.md`). The CKM's primary entity. |
| **Sub-capability** | A capability that is part-of a parent capability; the hierarchy is a decomposition, not containment of code. |
| **Evidence** | Any artifact (code, commit, PR, ADR, requirement, spec, test, coverage/benchmark result, doc, diagram, AI session, CI result) linked to a capability with a typed `evidence_kind`, a `polarity` (supports / weakens), and provenance. |
| **Assessment** | A synthesized maturity judgment for a capability across seven dimensions, with an explanation and the evidence citations that produced it. |
| **Capability Evidence Graph (CEG)** | The graph data structure: capability nodes, evidence nodes, artifact nodes, and typed edges. |
| **Gap** | A capability (or sub-capability) with weak/absent evidence in one or more maturity dimensions, or an architectural region with no capability coverage. |
| **Drift** | A growing delta between prescriptive intent (requirements/ADRs/SBS) and descriptive reality (recovered from code/tests). |
| **Projection** | A generated, self-identifying, non-authoritative view (per BuilderOps object model). Everything the CKM emits is a projection. |

### 5.4 Stakeholders

| Stakeholder | Primary need from the CKM |
| --- | --- |
| **Owner / Product architect** (Rasmus) | "What exists, how mature, where are the largest gaps, how has the architecture evolved" — for portfolio and sequencing decisions, at low cognitive load, lead-with-the-answer. |
| **Builder agents** (Claude Code / Codex) | A structured, current model of the platform to ground planning, decomposition, and implementation — the "missing middle" between retrieval and session memory. |
| **Coordinator / delivery skills** | Capability-level readiness signals to route and verify work (complements `deliver-issue-set`, `verification-and-closure`). |
| **Quality gates / CI** | Capability coverage and drift signals as fitness inputs. |
| **Future contributors** | Recover system understanding from the repo alone, without conversation history (the same goal as the architecture context packet). |

### 5.5 Assumptions

- The repo already emits rich, structured artifacts: ADRs with a house header contract, an invariant registry, a static traceability matrix, spec directories, a Capability Contract Model, an SBS, and BuilderOps receipts.
- BuilderOps (ADR-0010) is the governed home for builder-plane knowledge; the CKM is a BuilderOps subsystem and inherits its authority discipline.
- LLM inference (routed per TCD) is available for synthesis and summarization, with deterministic fallbacks required for local-first paths.
- Single-operator / trusted-LAN posture: security is TCD-gated, not a primary blocker; **data integrity and provenance correctness remain first-class** (a wrong maturity claim that reads as truth is the real risk).
- The model is *derived and rebuildable*; losing it loses no authority (it can be re-synthesized from evidence).

### 5.6 System Context

The CKM sits in the **BuilderOps plane** (governs the building system), strictly separated from the **product/runtime plane** (governs product truth) per ADR-0010. It *reads* product-plane artifacts (repo, git, docs, tests) and builder-plane artifacts (Issues, PRs, BuilderOps receipts, AI sessions) as evidence; it *writes* only projections and analytical records into the BuilderOps Vault; it *never* writes product/runtime truth and never crosses an authority boundary without an explicit, receipted promotion (which is a human decision, not a CKM action).

```
  Product/runtime plane (SoI)          Builder plane (BuilderOps, ADR-0010)
  ┌───────────────────────────┐        ┌──────────────────────────────────────┐
  │ source code, tests, docs, │        │ Issues, PRs, ADRs*, receipts,        │
  │ ADRs*, diagrams, CI,      │──read──▶│ AI/agent sessions, learning signals  │
  │ requirements, specs       │        │                                      │
  └───────────────────────────┘        │   ┌────────────────────────────┐     │
        (*ADRs are builder-plane        │   │   CKM (Kvasir)             │     │
         decisions about the product)   │   │  ingest → associate →      │     │
                                        │   │  assess → detect →         │     │
                                        │   │  project                   │     │
                                        │   └─────────────┬──────────────┘     │
                                        │                 │ projection only     │
                                        │                 ▼                     │
                                        │   Dev Overview UI · API · reports ·  │
                                        │   agent context · gate inputs        │
                                        └──────────────────────────────────────┘
```

### 5.7 Architecture (summary; detailed in Part III / §7)

Six modules behind a stable contract: **Ingestion & Adapters**, **Capability Registry**, **Evidence Association**, **Maturity Assessment**, **Analysis (gap/drift/relationship)**, and **Projection & Query**. The Capability Evidence Graph is the shared substrate. All heavy inference is asynchronous and rebuildable; all outputs are projections.

### 5.8 Functional Requirements

The eleven draft FRs, restated with acceptance framing. Each is a *projection* requirement — the output is candidate, explainable, and provenance-carrying.

- **FR-1 Capability model.** The CKM shall maintain a hierarchical capability model of the platform, seeded from the SBS decomposition and the Capability Contract Model, and extended by evidence-driven inference. *Accept:* every capability node has a stable id, a parent (or root), a definition, and a provenance for why it exists.
- **FR-2 Continuous ingestion.** The CKM shall ingest engineering artifacts continuously (event-driven where a signal exists — commit/PR/merge/ADR-add — and on a scheduled sweep otherwise). *Accept:* an artifact added to the repo appears as an evidence candidate within one ingestion cycle, with source provenance.
- **FR-3 Evidence association.** The CKM shall associate each artifact with one or more capabilities, typed by `evidence_kind` and `polarity`, with a confidence and an explanation. *Accept:* every association is inspectable, cites its basis, and is reversible.
- **FR-4 Capability relationships.** The CKM shall infer typed relationships between capabilities (`depends-on`, `part-of`, `realizes`, `conflicts-with`). *Accept:* relationships are visualizable and each carries its evidentiary basis.
- **FR-5 Maturity assessment.** The CKM shall compute an explainable maturity assessment per capability across the seven dimensions (§6/§5.11). *Accept:* the assessment is a vector, not a single opaque number; each dimension names the evidence that raised or lowered it; the aggregate function is transparent and reproducible.
- **FR-6 Gap detection.** The CKM shall detect architectural gaps — capabilities weak in a dimension, and SBS regions with no capability coverage. *Accept:* each gap is a specific, actionable statement ("capability C has no tests," "boundary X has no capability realizing it").
- **FR-7 Missing-evidence detection.** The CKM shall detect capabilities whose *claim* exceeds their *evidence* (e.g. a doc asserts "shipped" but no tests/PRs support it). *Accept:* a flagged claim names the asserting artifact and the missing evidence class.
- **FR-8 Drift detection.** The CKM shall detect drift between prescriptive intent (requirements/ADRs/SBS) and descriptive reality (code/tests), reported as convergence/divergence/absence (reflexion framing). *Accept:* a drift finding cites both the intent artifact and the reality signal.
- **FR-9 Dependency visualization.** The CKM shall expose capability dependency and relationship graphs. *Accept:* the graph is navigable and filterable by maturity/dimension/boundary.
- **FR-10 Evolution over time.** The CKM shall track capability and maturity evolution as a temporal series. *Accept:* one can query "maturity of capability C as of date D" and "capabilities added/changed between D1 and D2" (temporal-KG / bitemporal design).
- **FR-11 AI summaries.** The CKM shall generate AI-assisted natural-language summaries per capability and per architectural region, grounded in and citing the evidence. *Accept:* every summary sentence is traceable to evidence; summaries are labeled as generated projections.
- **FR-12 Vertical navigation.** The CKM shall support navigation Capability → Requirement → Architecture → Implementation → Tests → Documentation → AI sessions without loss of context. *Accept:* from any capability, every linked artifact in the chain is reachable in one hop with its provenance preserved.

### 5.9 Non-Functional Requirements

- **NFR-1 Explainability (load-bearing).** No score, association, or summary may be a black box. Every derived value carries its inputs, method, model/provider (if inferred), and confidence. This is the single most important NFR: an unexplained maturity number that reads as truth is the subsystem's chief failure mode.
- **NFR-2 Non-authority.** Every CKM output is a `projection`/`analytical` object per the BuilderOps object model; it must self-identify as derived and must never be consumable as a source of truth or as an admissibility upgrade.
- **NFR-3 Rebuildability.** The entire model must be reconstructable from evidence. No CKM-only fact is canonical; corruption or loss is recoverable by re-synthesis.
- **NFR-4 Provenance preservation.** Provenance and metadata survive every derivation step (mirrors the doctrine invariant `provenance_survives_derivation`).
- **NFR-5 Incrementality & scale.** Ingestion and assessment must be incremental (re-assess only capabilities whose evidence changed), bounded in cost, and viable on the operator's hardware profile (laptop dev has no heavy ML deps by design; heavy passes run where the substrate exists).
- **NFR-6 Determinism where possible.** Structural evidence (test↔code links, PR↔file, coverage) must be deterministic; LLM inference is confined to semantic association, summarization, and gap-hypothesis generation, always with a deterministic fallback and always labeled.
- **NFR-7 Cost discipline (TCD).** Synthesis must be cheap-model-first and event-driven; a full re-synthesis is a bounded, schedulable operation, not a per-PR tax. Model routing follows TCD (cheap/deterministic for mechanical linking; higher tiers only for hard semantic synthesis).
- **NFR-8 Auditability.** Every model transition is receipted (BuilderOps receipts), so "why did capability C's maturity change on date D" is answerable.
- **NFR-9 Freshness legibility.** Every projection states its ingestion watermark and staleness, so a consumer never mistakes a stale view for current truth.

### 5.10 Information Model — see §6.

### 5.11 Capability Model

- **Structure:** a forest of capabilities with `part-of` decomposition, roots seeded from the eight SBS macro-domains / fourteen Level-2 control boundaries, and leaves at the grain of the Capability Contract Model examples (Retrieval, Orientation, Resurfacing, …). Grain is non-canonical and nested (a capability may decompose further as evidence accumulates).
- **Identity:** a capability has a stable id independent of any single artifact; renaming or refactoring code does not destroy the capability node (only its evidence set changes).
- **Provenance of existence:** every capability records *why the CKM believes it exists* — seeded-from-SBS, declared-in-contract-model, or inferred-from-evidence (with the evidence cited). Inferred capabilities are candidates until confirmed.
- **Reuse:** the CKM does not fork the capability taxonomy; it *populates and assesses* the taxonomy that `CAPABILITY_CONTRACT_MODEL.md` and the SBS already own.

### 5.12 Evidence Model

- **Typed evidence:** each evidence edge has `evidence_kind` ∈ {requirement, spec, adr, design-doc, diagram, source, commit, pull-request, test, coverage, benchmark, ci-result, ai-session, learning-signal, doc}, a `polarity` ∈ {supports, weakens}, a `maturity_dimension` it bears on, a `confidence`, an `extraction_method` (deterministic | inferred, with model/provider), and full provenance.
- **Evidence ≠ authority.** An artifact being evidence about a capability grants it no runtime standing. The CKM's `evidence_kind` is a *builder-plane analytical typing* and is explicitly orthogonal to the product-plane `evidence_role` dimension (which governs what a runtime artifact may do). The naming overlap is bounded by this rule (see §Reconciliation; candidate owner decision OD-K3).
- **Weighting:** dimensions aggregate evidence with transparent weights; contradictory evidence (a "done" doc + zero tests) is surfaced as a *tension*, not silently averaged.

### 5.13 AI Integration

- **Where LLMs are used:** (1) semantic evidence association (which capability does this artifact bear on); (2) capability-existence hypotheses from clusters of evidence; (3) natural-language capability/region summaries; (4) drift/gap hypothesis generation; (5) the conversational query surface ("what's underdeveloped in retrieval?").
- **Where they are not:** structural linking (test↔code, PR↔file, coverage↔line) is deterministic; maturity *aggregation* is a transparent function, not an LLM guess; no LLM output is authority.
- **Guardrails:** every inferred edge/summary is labeled, carries model/provider provenance, has a deterministic fallback, and is a proposal the model records as candidate — mirroring the runtime doctrine "retrieval produces candidate evidence, not truth" and "propose/confirm rather than silently act."

### 5.14 Data Sources

Git (commits, diffs, blame, history), GitHub (Issues, PRs, reviews, Projects, labels), the repo tree (source, tests, `docs/**`, ADRs under `docs/adr/`, spec directories, diagrams, the invariant registry, the static traceability matrix), CI/CD results and coverage/benchmark artifacts, BuilderOps Vault records (worklogs, learning signals, promotion receipts, decision receipts), and AI development sessions (Claude Code / Codex transcripts and their receipts). All are read-only inputs; adapters normalize each into typed evidence.

### 5.15 Interfaces

- **Query API** (read-only): capability lookup, subtree, evidence-for-capability, maturity vector + explanation, gaps, drift, evolution series, and a grounded natural-language query endpoint. All responses carry provenance + freshness watermark and self-identify as projections.
- **Development Overview UI** (one consumer): capability map, maturity heatmap by dimension/boundary, gap/drift lists, capability detail with the full vertical navigation chain, and evolution timeline.
- **Agent context interface:** a structured capability-context bundle a builder agent can request to ground planning/decomposition.
- **Gate/report interface:** capability-coverage and drift signals as inputs to quality gates and periodic reports.
- **Ingestion adapters:** one per data source, each mapping a source into typed evidence with provenance.

### 5.16 Traceability

The CKM *is* the traceability engine — the continuously-synthesized generalization of the static `traceability-matrix.md` (#2535). It maintains the vertical chain (capability → requirement → ADR → boundary → contract/schema → code → test/eval → doc → AI session) as live graph edges rather than hand-maintained table cells, and it can *emit* the static matrix as one of its projections (keeping the human-authored control document and the synthesized model in agreement, as the architecture context packet requires).

### 5.17 Security & Authority

Single-operator/trusted-LAN posture: access control is TCD-gated, not a primary concern. The load-bearing constraints are **authority and provenance**, not confidentiality: (1) the CKM never holds or transfers authority (ADR-0010; all outputs are `projection`/`analytical`); (2) reading a product-plane artifact as evidence never upgrades that artifact's runtime standing; (3) crossing from a CKM observation to a product/backlog action (e.g. "file an issue for this gap") is an explicit, human-gated, receipted promotion — never an automatic CKM effect. Prompt-injection via operator-controlled vault/repo content is by-design-trusted input in this posture (consistent with the CodeQL default-setup ruling in memory).

### 5.18 Risks — see §8 (Critical Review).

### 5.19 Future Extensions

- **Closed-loop (true digital twin):** graduate from digital shadow to twin by letting the CKM *propose* backlog actions (gap→issue, drift→ADR-review) through the governed promotion path — writeback makes it a twin per the ICSE-2025 definition.
- **Predictive maturity:** forecast time-to-maturity from evolution series.
- **Cross-repo federation:** extend the model across the ecosystem constituents (Mimer, Bifrost, Heimdal) via the federation seam (SFC), respecting ADR-0047 topology.
- **Counterfactual / simulation:** "if we build capability X, which gaps close" — the simulation dimension that would complete the twin analogy.
- **Eval-corpus generation:** emit capability-scoped eval fixtures from weak-evidence dimensions.

---

# Part III — Model, Architecture, Critique

## 6. Information Model

Conceptual entities and relationships for the Capability Evidence Graph. Entities marked *(existing)* are reused, not redefined.

**Core nodes**

- **Capability** — id, name, definition, parent (`part-of`), existence-provenance, lifecycle (candidate | confirmed | deprecated). *Primary entity.*
- **Assessment** — capability-id, timestamp, seven-dimension vector, aggregate, explanation, evidence-citation set. Bitemporal (valid-time + assertion-time) for FR-10.
- **Evidence** — the typed edge/record linking an **Artifact** to a **Capability** (`evidence_kind`, `polarity`, `maturity_dimension`, `confidence`, `extraction_method`, provenance).
- **Artifact** — a normalized reference to a source item, specialized as: **Requirement**, **ADR** *(existing; `docs/adr/`)*, **Document**, **SourceFile**, **Test**, **PullRequest**, **Commit**, **Repository**, **AgentSession / AIConversation**, **Decision** *(existing; BuilderOps decision receipt)*, **Diagram**, **CIResult / Coverage / Benchmark**, **LearningSignal** *(existing; BuilderOps)*.
- **Relationship** — typed capability↔capability edge (`depends-on`, `part-of`, `realizes`, `conflicts-with`), with evidentiary basis.
- **Gap** / **Drift** — derived finding nodes (capability + dimension + statement + citations).
- **Boundary** *(existing; SBS Level-2 control boundary)* — the architectural region a capability maps into; the coverage target for FR-6.
- **Milestone**, **Risk**, **Dependency**, **QualityGate** — contextual nodes linking capabilities to schedule/risk/gate state (read from Issues/Projects/gates).

**Key relationships**

```
Capability --part-of--> Capability            (decomposition forest)
Capability --depends-on/realizes/conflicts--> Capability
Capability --maps-to--> Boundary(existing SBS)
Artifact   --is-evidence-for[kind,polarity,dim]--> Capability
Assessment --assesses--> Capability            (bitemporal series)
Assessment --cites--> Evidence                 (explainability)
Gap/Drift  --concerns--> Capability + Dimension --evidenced-by--> Artifact
Capability --traces-to--> Requirement --decided-by--> ADR --realized-by--> SourceFile
           --verified-by--> Test --documented-by--> Document --explored-in--> AgentSession
Decision(existing) / LearningSignal(existing) --is-evidence-for--> Capability
```

**Maturity dimensions (the Assessment vector), each evidence-backed:**

1. **Functional completeness** — requirements/specs realized by shipped code (weakened by stubs and unfinished-work markers).
2. **Test completeness** — tests + coverage + invariant/eval fixtures bearing on the capability.
3. **Documentation quality** — owner doc present, current, and consistent with code.
4. **Integration completeness** — capability wired to its callers/surfaces vs. built-but-dormant.
5. **Operational readiness** — health/observability/deploy evidence.
6. **Architectural stability** — churn/hotspot signal + drift findings (low drift = stable).
7. **Requirement coverage** — fraction of governing requirements/ADRs with realizing + verifying evidence.

Aggregation is a transparent, published function over the vector (e.g. weighted-min so a single starved dimension cannot be hidden by strong others — surfacing tensions per FR-7). The vector is always shown; the scalar is a convenience, never the source of the judgment.

## 7. Proposed Architecture

A modular subsystem inside the BuilderOps plane, behind a stable contract, every module replaceable without touching the kernel (per `MODULAR_ARCHITECTURE.md`). Heavy inference is asynchronous; the graph is the shared substrate; every egress is a projection.

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. INGESTION & ADAPTERS                                              │
│    git · GitHub · repo tree · CI/coverage · BuilderOps · AI sessions │
│    → normalize to typed Artifact records (event-driven + sweep)      │
├─────────────────────────────────────────────────────────────────────┤
│ 2. CAPABILITY REGISTRY                                               │
│    seed from SBS + Capability Contract Model; hold the capability    │
│    forest, ids, existence-provenance, lifecycle                      │
├─────────────────────────────────────────────────────────────────────┤
│ 3. EVIDENCE ASSOCIATION                                              │
│    deterministic linkers (test↔code, PR↔file, req↔ADR, coverage)    │
│    + LLM semantic association (labeled, fallback) → typed edges      │
├─────────────────────────────────────────────────────────────────────┤
│ 4. MATURITY ASSESSMENT                                               │
│    per-capability 7-dim vector; transparent aggregate; explanation;  │
│    incremental re-assess on changed evidence only                    │
├─────────────────────────────────────────────────────────────────────┤
│ 5. ANALYSIS  (relationship inference · gap · missing-evidence ·      │
│    drift[reflexion: convergence/divergence/absence] · evolution)     │
├─────────────────────────────────────────────────────────────────────┤
│ 6. PROJECTION & QUERY                                                │
│    read-only API · Dev Overview UI · agent context bundle · gate/    │
│    report signals · emits the static traceability matrix projection  │
└─────────────────────────────────────────────────────────────────────┘
         ▲ shared substrate: CAPABILITY EVIDENCE GRAPH (bitemporal) ▲
         ▲ every transition receipted (BuilderOps) · all egress = projection ▲
```

**Storage substrate (per the repo's storage framework — who-needs-it + lifetime):**
- The **CEG** is derived/rebuildable → a projection store (graph or relational-with-graph-views), *not* a source of truth. It may be re-synthesized at will.
- **Capability existence-provenance and confirmed-capability records** are longer-lived, human-relevant builder knowledge → BuilderOps Vault (analytical/decision objects), so they survive a graph rebuild.
- **Receipts** for every model transition → BuilderOps receipt objects (append-only, immutable).

**Model routing (TCD):** deterministic linkers first; cheap model for bulk semantic association; higher tier only for hard capability-existence synthesis and the conversational surface. Full re-synthesis is a bounded scheduled job, never a per-PR cost.

**Reconciliation vs. the SBS (conform / extend / reshape):**
- **Conforms to:** ADR-0010 (BuilderOps governs the building system; no silent authority transfer); the doctrine invariants that *projections are not evidence* and *derived views are candidate, not truth*; the Capability Contract Model definition of a capability; the SBS boundary ownership; the `provenance_survives_derivation` invariant.
- **Extends:** adds a continuously-synthesized **analytical/projection** layer (the CEG + maturity assessor + gap/drift detectors) over existing evidence. Introduces new BuilderOps object types (CapabilityAssessment, EvidenceEdge) *within* the existing object-model contract's `analytical`/`projection`/`receipt` classes.
- **Reshapes:** nothing normative. It must not become a new authority, a new capability taxonomy, or a new source of truth. If the owner ever wants CKM findings to *drive* action automatically, that is a genuine reshape (closed-loop twin) and requires its own ADR.

**Owner decisions this proposal surfaces:**
- **OD-K1 — Build vs. defer.** Is the trigger strong enough now? (The static matrix is hand-maintained and #2535's fine-grained mapping is unlanded; fragmentation is real and growing — but the Correctness Kernel's schema/registry substrate, which makes drift detection cheap, is still landing. Recommendation: build the seed + ingestion + assessment MVP now; defer heavy drift detection until the registry substrate exists, mirroring the Builder Capability Portfolio's "architectural regression detection = defer until KERNEL-08" ruling.)
- **OD-K2 — Codename.** Adopt **Kvasir** via an ADR-0043 name-register entry, or keep the descriptive **CKM** only?
- **OD-K3 — `evidence_kind` naming.** Confirm the builder-plane `evidence_kind` is explicitly orthogonal to the product-plane `evidence_role` (bounded by the §5.12 rule), or choose a non-colliding term to avoid semantic drift of a load-bearing runtime word.
- **OD-K4 — Store choice.** Projection store as graph DB vs. relational-with-graph-views, given the laptop-has-no-heavy-deps constraint and where synthesis runs (mac mini).
- **OD-K5 — Confirmation policy.** Do inferred capabilities/edges stand by default (silence = acceptance, opt-out re-cut, per the Episode segmentation precedent) or require confirmation before entering the confirmed set?

## 8. Critical Review

A candid challenge to the proposal — the weaknesses, assumptions, and failure modes, with mitigations.

**8.1 The maturity number is the central risk.** A synthesized maturity score that *reads as truth* is exactly the failure the doctrine warns against ("retrieval produces candidate, not truth"). If the Development Overview UI shows "Semantic Search: 72% mature," humans and agents will treat 72 as fact. *Mitigation:* NFR-1 (never a black box) + always-show-the-vector + weighted-min aggregation that surfaces starved dimensions + explicit `projection` labeling + freshness watermark. The scalar must be demonstrably a convenience over a visible, cited vector — if that discipline slips, the subsystem does net harm.

**8.2 LLM evidence-association is noisy and non-deterministic.** Semantic "does this artifact bear on capability C" is the soft joint. False links inflate maturity; missed links create phantom gaps. *Mitigation:* deterministic linkers carry the structural load (test↔code, PR↔file, coverage, req↔ADR); LLM inference is confined, labeled, confidence-scored, and fallback-guarded; associations are reversible and re-derivable. *Residual risk:* semantic drift over model upgrades — pin the assessment to model/provider provenance so a maturity change caused by a model change is distinguishable from a real one.

**8.3 Capability granularity is under-determined.** Grain is non-canonical (a call ⊂ a workday ⊂ a project, in the Episode framing). Too coarse and gaps hide inside big capabilities; too fine and the model becomes a code map. *Mitigation:* seed from the *already-agreed* SBS + Capability Contract Model grain rather than inventing one; let evidence *propose* finer decomposition as candidates (OD-K5), never auto-commit it.

**8.4 "Continuous" cost could balloon.** Per-PR full re-synthesis would be a heavy tax and violate TCD. *Mitigation:* strict incrementality (re-assess only capabilities whose evidence changed), event-driven ingestion, cheap-model-first, bounded scheduled full re-synthesis. If incrementality proves hard, the fallback is a nightly sweep — still far better than the current zero.

**8.5 It could quietly become an authority.** The most insidious failure: agents start treating CKM output as the plan, or the CKM starts filing issues / editing docs. That is an authority escalation ADR-0010 forbids. *Mitigation:* hard non-authority (NFR-2), projection-only egress, and any writeback gated as an explicit human-confirmed promotion (which also happens to be the graduation path to a true twin — so the boundary is a feature, not just a guardrail).

**8.6 Circularity / self-reference.** The CKM is a Builder System subsystem; will it model *itself*, and does that create instability? *Mitigation:* yes, it models itself like any capability, but as an ordinary evidence-backed node — no special casing, no feedback into its own assessment inputs.

**8.7 Does the whitespace exist because the object is not useful?** The honest counter-hypothesis: incumbents avoid capability-maturity synthesis because it is subjective and low-ROI, and DeepWiki/repo-maps are "good enough." *Rebuttal:* Yggdrasil is unusually well-suited — it *already* has the structured substrate (ADRs with header contracts, invariant registry, SBS, Capability Contract Model, BuilderOps receipts, spec directories) that makes synthesis tractable where a typical repo makes it guesswork. The subsystem is high-value *here* precisely because the evidence is already typed. This is a defensible reason the general market hasn't built it while this platform should.

**8.8 Alternative architectures considered.**
- **(a) Extend the static traceability matrix by hand / with a linter** — cheapest, but does not scale, does not assess maturity, and re-creates the vaporization problem. *Rejected as the endpoint; adopted as the seed and as one projection.*
- **(b) Buy/adapt a developer portal (Backstage + Tech Insights)** — mature scorecard machinery, but service-centric with no capability node and no artifact-as-evidence model; adapting it means fighting its ontology. *Rejected; possible inspiration for the scorecard UI only.*
- **(c) Pure agent-memory KG (Cognee/Zep-style)** — good substrate, but oriented at code entities/session facts, not capability-maturity. *Partially adopted:* the bitemporal-KG design (Zep/Graphiti) is the right model for FR-10.
- **(d) LLM-only "ask the repo" (DeepWiki-style)** — fast to stand up, but no maintained model, no maturity, no gaps, and non-reproducible. *Rejected as the model; adopted as the conversational query surface on top of the maintained graph.*
- **(e) The proposed hybrid** — deterministic structural spine + confined LLM synthesis + transparent assessment + projection-only egress. *Recommended.*

**8.9 Scalability.** At current repo scale the graph is small (hundreds of capabilities, thousands of artifacts) — trivial. The cost is *inference*, not storage; controlled by incrementality and model routing. Cross-repo federation (future) is where scale and permissioning become real, and is deferred behind the SFC seam.

**8.10 The strongest reason to proceed.** The gap the research found is not merely a market gap; it is *this platform's* daily friction: agents and the owner reconstruct system understanding from a dozen partial sources on every planning turn. The CKM converts that recurring human/agent cost into a maintained, cheap-to-query model — the exact TCD decision rule for building a builder capability. The strongest reason to *pause* is sequencing (OD-K1): let the Correctness Kernel's registry land so drift detection is cheap rather than speculative. The recommended path threads both: build the seed + ingestion + assessment now; stage drift detection behind the substrate.

---

## Appendix A — Provenance of this document

Internal grounding: `CAPABILITY_CONTRACT_MODEL.md`, `SYSTEM_BREAKDOWN_STRUCTURE.md`, `architecture/traceability-matrix.md`, `builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`, `adr/ADR-0010`, `development/BUILDER_CAPABILITY_PORTFOLIO.md`, `foundation/yggdrasil-architecture-context-packet.md`, `testing/invariant-tests.md`, `architecture/system-context-overlay.md`.

External prior-art synthesis (2026-07-07): developer portals (Backstage/Cortex/OpsLevel/Port/Compass); engineering-intelligence (Gartner SEI; LinearB/Jellyfish/DX/Faros/CodeScene/Sonar/Sourcegraph; DORA/SPACE; feature-location — Dit et al. 2013; trace-link recovery); architecture-KM (Jansen & Bosch 2005; reflexion models — Murphy/Notkin/Sullivan 1995; fitness functions — Ford/Parsons/Kua; ArchUnit; vFunction/CAST; Living Documentation — Martraire; AgenticAKM 2026); KG/twin/MBSE (Joern CPG; SCIP; SEON; OSLC; Gartner DTO; Digital Twins for SE Processes — ICSE 2025; Kritzinger model/shadow/twin; DoDAF CV; ArchiMate/TOGAF; Arcadia/Capella; CMMI; GSN/SACM); AI-native (Aider/Cursor/Cody repo context; DeepWiki/Potpie; Letta/Zep/Graphiti/Mem0/Cognee; Kiro/Spec Kit/Tessl; CLAUDE.md auto-memory).

## Appendix B — Open research questions (for a future ADR / grounding pass)

- **RQ-K1** Confirmation semantics for inferred capabilities/edges (OD-K5) — the Episode opt-out-re-cut precedent vs. explicit confirmation.
- **RQ-K2** The aggregation function — weighted-min vs. profile-based maturity levels (OpsLevel-style ladder) vs. keep-vector-only.
- **RQ-K3** Bitemporal model shape for evolution (Zep/Graphiti-style valid/assertion time) and its query cost.
- **RQ-K4** Where drift detection binds to the Correctness Kernel's schema/writer registry so it is a cheap diff over declared state (the Builder Capability Portfolio deferral rationale).
- **RQ-K5** The exact orthogonality contract between builder-plane `evidence_kind` and product-plane `evidence_role` (OD-K3).
