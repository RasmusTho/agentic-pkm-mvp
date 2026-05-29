State: SoT v5.5 baseline locked (v5.6 delivered, v6.0 seams shipped at capability-seam level); this document is target-state semantic framing and does not claim every layer is fully enforced in runtime today.
Doc role: Core SoT
Authority: Semantic architecture map. Owns the cross-cutting semantic topology — the semantic layers, the authority topology over artifacts and runtime structures, the artifact-flow topology, and the runtime-vs-durable boundary map. It integrates and indexes existing contracts; it does not replace them. Where a layer already has an owner doc, that owner doc remains authoritative for its own scope.
Owner: Semantic architecture map
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-29
Last verified against: docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md, docs/CONCEPTS/LAYERING_MODEL.md, docs/CONCEPTS/ONTOLOGY_VOCABULARY.md, docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md, docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/ARCHITECTURE.md, docs/EVENTS.md, docs/FRONTMATTER.md, epic #1363, issue #1364.

# Semantic System Architecture — Map

This document is the semantic spine for Yggdrasil. It exists because the system's semantics have grown across many strong but distributed contracts (Contextualization Layer, Companion UI, governance, runtime, machine mirrors, receipts, ontology), and the boundaries between them need one explicit, reviewable place to attach.

It is a docs-only integration artifact. It does not introduce new runtime behavior, new schema, or new events. It names the semantic layers, states who owns each, and draws the authority and flow topology that connects them.

## Relationship to the system-of-systems spine

`docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` decomposes Yggdrasil **structurally** into eight runtime subsystems (Human Surface, Knowledge & Artifact, Runtime Projection, Capability, Agent/Orchestration, Governance/Authority, Integration Fabric, Observability/Fitness).

This document decomposes Yggdrasil **semantically** into seven semantic layers (ontology, artifact model, representation, governance/authority, runtime, machine mirror, UI projection). The two views are complementary, not competing:

- The system-of-systems spine answers *"which subsystem runs this?"*
- This map answers *"what does this mean, what is authoritative, and how does meaning flow and mutate?"*

Where the two views describe the same boundary, the system-of-systems spine owns the structural decomposition and this document owns the semantic decomposition. If they conflict, resolve the boundary and update both in the same change.

## Authority of this document

- This document **owns**: the semantic-layer map, the authority topology, the artifact-flow topology, and the runtime-vs-durable boundary map at the integrating altitude.
- This document **does not own**: the detailed contracts for any individual layer. Those remain with their owner docs, listed per layer below.
- When this document restates a semantic rule inline, the restatement is a **summary for legibility**, not a new authority. The owner doc named in that section wins on any conflict, and this document is updated to match — never the reverse.

This is the rule that keeps an integrating document from becoming a second, drifting source of truth.

## The seven semantic layers

The layers below are **orthogonal concerns**, not a storage stack. A single Markdown file can participate in several layers at once (it is an ontological entity, an artifact of some class, with a representation, under some authority, possibly mirrored, possibly projected in the UI). Keeping the layers distinct is what prevents conflation — for example, treating a database row (representation/mirror) as if it carried ontological authority, or treating a UI panel (projection) as if it were a durable artifact.

### Layer 1 — Ontology

- **Question it answers:** What kinds of things exist, and how are they related?
- **What it is:** The entity and relation vocabulary — actors, context structures, artifacts, commitments, operations, and the relations among them. It says what a "note", "source", "commitment", "agent", or "relation" *is*.
- **What it is not:** It does **not** decide authority, admissibility, or write permission. Ontology says a thing can exist and can relate to another thing; it does not say which instance is authoritative or who may change it.
- **Owner docs:** `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` (canonical ontology), `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md` (normalized term set + drift map), `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md` (agent/role/delegation ontology), `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` (commitment structures). Relation semantics are owned by the relation taxonomy: `docs/CONCEPTS/RELATION_TAXONOMY.md` (#1367).

### Layer 2 — Artifact model

- **Question it answers:** What class of object is this, who is it for, how durable is it, and what right does it have to influence an agent?
- **What it is:** The classification of every durable or semi-durable object into a small set of artifact classes, each with its own audience, durability tier, and activation/use-right defaults. The canonical classes are **Human Knowledge Artifact**, **Agentic Memory Artifact**, **Machine Mirror Artifact**, plus the **Companion (metadata) Note** pattern and the **Bridge / Assembly** carve-out for context bundles.
- **Core principle (owner: Contextualization Layer):** *Markdown is the shared substrate, not the shared semantics.* Three files can sit in the same folder, all be `.md`, and still be three different kinds of object.
- **Use rights (owner: `CONTEXT_ACTIVATION_SEMANTICS.md`):** `visible` → `retrievable` → `activatable` → `instructional` → `action_authorizing`. These are not granted by virtue of existing; they are granted per class and lifecycle state.
- **Owner docs:** `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` (artifact classes), `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md`, `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md`, `docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md`, `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`, `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`.

### Layer 3 — Representation

- **Question it answers:** How is an artifact serialized, stored, and located, without changing what it means?
- **What it is:** The substrate and locators — Markdown body, frontmatter fields, file paths, `source_ref`, UUID identity, companion-file placement. Representation is *how* an artifact is written down.
- **Hard rule:** Representation changes (moving a file, changing its path, splitting metadata into a companion) must **not** change the artifact's class, domain, trust, or authority. Plane changes do not redefine meaning (owner: `LAYERING_MODEL.md`, rule 4).
- **Owner docs:** `docs/FRONTMATTER.md` (frontmatter write contract), `docs/CORE_CONTRACT.md` (Core-6 fields + projection rules), `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`, `docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md`, `docs/GLOSSARY.md` (`source_ref`, `Healing`, identity order).

### Layer 4 — Governance / Authority

- **Question it answers:** What is authoritative, what is admissible, what evidence is required, who may mutate, and how is escalation handled?
- **What it is:** The admissibility, approval, audit, and write-safety layer. It owns trust tiers (`assert` / `suggest` / `apply`), write guards, APPLY gates, proposal/receipt semantics, policy profiles, and the rule that **authority lives with the human and with explicit governance — not with whichever runtime component happened to write a value.**
- **Kernel binding (owner: system-of-systems spine):** human-first authority; provenance, receipts, and write guards; authority separation between subsystems.
- **Owner docs:** `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` (trust tiers, gating, write constraints), `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`, `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`, `docs/PANEL_AGENT.md` (panel action catalog/provenance), `docs/NOTE_KIND_POLICIES.md`, `docs/ARCHITECTURE.md` (`Concurrency & Idempotency`, `Boundary Enforcement`), `docs/INTERACTION_SURFACES_AND_AUTHORITY/**`. The consolidated authority matrix is owned by the semantic authority matrix (#1365 follow-up). Workflow mutation semantics are owned by #1371 follow-up.

### Layer 5 — Runtime

- **Question it answers:** What state exists only while the system is running, and is therefore non-durable unless explicitly persisted under a contract?
- **What it is:** AgentState, session/workspace state, panel/overlay state, retrieval state, active proposals before application, traces, decisions, and policy evaluations. Runtime state is **ephemeral by default**.
- **Hard rule:** Runtime state must not contaminate durable semantics. A runtime-derived value becomes durable only by passing through governance (Layer 4) into an artifact (Layer 2) — never by silent persistence.
- **Owner docs:** `docs/ARCHITECTURE.md` (current runtime surfaces, AgentState), `docs/LANGGRAPH_AGENT_ARCHITECTURE.md`, `docs/AGENTS.md`, `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` (runtime vs memory boundary). The consolidated runtime-vs-durable boundary contract is owned by #1369 follow-up.

### Layer 6 — Machine mirror

- **Question it answers:** Which structures are rebuildable, optimized projections of authoritative artifacts, carrying no authority of their own?
- **What it is:** DB object/store projections, vector indexes, retrieval caches, render caches, full-text/graph indexes, workspace aggregates, search projections. Every mirror must be **fully reconstructable** from the human-knowledge + agentic-memory set; if reconstruction would lose information, the object is misclassified and is really an artifact.
- **Hard rule:** A machine mirror cannot say something the source does not say. Its authority is the authority of the source it projects (owner: `HUMAN_AND_AGENTIC_ARTIFACTS.md` §6).
- **Owner docs:** `docs/COMPONENTS.md`, `docs/EMBEDDINGS.md`, `docs/RETRIEVAL.md`, `docs/DB_SCHEMA.md`, `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`, `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`. The consolidated machine-mirror/DB authority contract is owned by `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (#1370).

### Layer 7 — UI projection

- **Question it answers:** What does the Companion UI (and other interaction surfaces) render, overlay, summarize, stage, and route — without becoming authoritative?
- **What it is:** Companion UI panels, workspace projections, runtime overlays, proposal staging surfaces, provenance visibility. The UI **projects and mediates**; it does not own semantic truth. Server-side governance classifies mutation authority, not the UI.
- **Hard rule:** No UI-owned semantic truth; no implicit authority escalation through a UI flow. A canvas/body edit and a governance-bearing mutation are distinct lanes even when they share a surface.
- **Owner docs:** `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`, `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`, `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`, `companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/COMPANION_UI_PRODUCT_SPEC.md`. Consolidated projection alignment is owned by #1368 follow-up.

## Authority topology

Every semantic object in the system falls into exactly one **authority role**. The role determines whether the object can be a source of truth, whether it survives a rebuild, and whether it may originate or authorize change.

| Authority role | Meaning | Survives full rebuild? | Can originate durable meaning? | Examples |
| --- | --- | --- | --- | --- |
| **Authoritative (human)** | The durable source of meaning; the human is the final author | Yes (it *is* the durable set) | Yes | Human Knowledge Artifacts (vault notes, decisions, source notes) |
| **Authoritative (governance-recorded)** | A settled record produced under governance that is durable and auditable | Yes | Yes, within its recorded scope | Receipts, promotion-transition records, applied proposals |
| **Supporting (agentic)** | System-maintained material that supports the human; never overrides human knowledge | Conditionally (retained, not rebuilt-from-nothing) | No — must be promoted through governance to gain durable authority | Agentic Memory Artifacts (task snapshots, activation traces, preference candidates) |
| **Derived (machine mirror)** | Rebuildable projection; authority is borrowed from its source | No (rebuildable) | No | DB rows, embeddings, indexes, caches, search/graph projections |
| **Runtime (ephemeral)** | Exists only during execution; non-durable unless explicitly persisted | No (discardable) | No | AgentState, session/workspace state, panel/overlay state, retrieval state |
| **Proposal-bearing** | A staged, not-yet-applied change awaiting governance | No (until applied) | No (only after application, as a governance-recorded record) | Write proposals, panel action proposals, memory candidates pending review |
| **Projection (UI)** | A rendering/mediation surface over the above | No | No | Companion UI panels, workspace aggregates, overlays |

Reading rules for the topology:

1. **Authority never flows downward by accident.** A derived, runtime, proposal, or projection object can only *acquire* durable authority by an explicit governance transition into an authoritative artifact. There is no implicit promotion path.
2. **The stricter boundary wins** when an object's role is ambiguous (consistent with `LAYERING_MODEL.md` rule 7): treat it as the lower-authority role until explicitly classified.
3. **Rebuildability is a tell.** If losing an object loses information, it is not derived/runtime — it is an artifact and must be governed as one.
4. **Provenance is mandatory across roles.** Every system-originated change to an authoritative object carries provenance and produces a human-legible receipt (kernel constraint).

The consolidated, per-entity authority matrix (with all flags: authoritative / rebuildable / temporary / machine-derived / governance-owned / human-editable / runtime-only / proposal-bearing / receipt-bearing / retrieval-visible / activatable / instructional / action-authorizing) is owned by `docs/SEMANTIC_AUTHORITY_MATRIX.md` (#1365). This section is the topology; that matrix is the per-entity detail.

## Artifact-flow topology

This is the canonical path meaning travels from human authorship to a durable, governed mutation. Each hop changes layer and authority role; no hop may skip governance to reach a durable artifact.

```
Human note            (Layer 2 artifact, Authoritative-human)
  └─▶ Companion note   (Layer 2 companion, Supporting/governance-recorded metadata about the note)
        └─▶ Machine mirror   (Layer 6, Derived: chunks, embeddings, index rows)
              └─▶ Context bundle   (Layer 2 bridge/assembly, per-use selection; NOT memory)
                    └─▶ Runtime projection   (Layer 5/7, Ephemeral: AgentState + UI overlay)
                          └─▶ Proposal   (Proposal-bearing: staged change, not yet durable)
                                └─▶ Receipt   (Authoritative governance-recorded)
                                      └─▶ Durable mutation   (back into Layer 2 artifact, under governance)
```

Invariants on the flow:

- **Forward-only authority gain.** Authority is only gained at the `Proposal → Receipt → Durable mutation` governance step. Everything before it is supporting, derived, ephemeral, or staged.
- **The bundle is a bridge, not memory.** A context bundle may *reference* agentic memory and mirrors, but it does not inherit their lifecycle or activation rights — those belong to the underlying artifacts (owner: `CONTEXT_BUNDLE_CONTRACT.md`, `HUMAN_AND_AGENTIC_ARTIFACTS.md` §5).
- **Mirrors never re-enter as authority.** A machine mirror feeds retrieval and bundles, but a value read from a mirror cannot become durable meaning without tracing back to its authoritative source and passing through governance.
- **Every durable mutation has a receipt.** No durable write to the human surface exists without a provenance-bearing receipt (kernel constraint; owner: Layer 4 docs).

## Runtime boundary map

This map states what is durable, what is rebuildable, and what is discardable. It is the integrating summary; the full persistence-rule contract is owned by #1369.

| State | Layer | Persistence class | May persist to vault? | May persist to DB? | Discardable? |
| --- | --- | --- | --- | --- | --- |
| Human Knowledge Artifact | 2 | Durable (authoritative) | Yes (it is the durable surface) | Mirrored only | No |
| Companion note | 2 | Durable (system-owned) | Yes | Mirrored only | No |
| Agentic Memory Artifact | 2 | Retained (supporting) | Yes (human-readable) | Mirrored only | With policy |
| Receipt | 4 | Durable (governance) | Yes (system surface) | Mirrored only | No |
| Context bundle | 2 (bridge) | Per-use / rebuildable | No (assembly artifact) | Optionally | Yes |
| Machine mirror (DB/index/cache) | 6 | Rebuildable | No | Yes (it lives there) | Yes (rebuild) |
| AgentState / session state | 5 | Runtime-only | No | Only as explicit runtime record | Yes |
| Workspace / panel / overlay state | 5/7 | Runtime-only | No | Only as explicit runtime record | Yes |
| Retrieval state / ranked candidates | 5/6 | Runtime-only / rebuildable | No | No (derived) | Yes |
| Active proposal (pre-apply) | proposal | Staged | No (until applied) | As staging record | Yes (on reject) |

Leakage-prevention rules (integrating summary; owner: #1369, #1370):

- **No UI/session leakage into durable note semantics.** Panel state, overlays, and workspace aggregates are runtime/projection; they must not be written into frontmatter or note bodies as if authoritative.
- **No retrieval state as semantic truth.** Ranked candidates and salience scores are derived projections, never durable authority.
- **No runtime metadata polluting frontmatter.** Only the governed frontmatter contract (`docs/FRONTMATTER.md`) defines durable fields; runtime fields do not silently appear there.
- **No machine-mirror override of the vault.** A mirror that disagrees with the vault is stale and must heal toward the vault, never the reverse.

## Companion UI projection semantics (integrating summary)

The Companion UI is a **semantic projection layer** (Layer 7). It is rendered over the authoritative surfaces; it is not one of them. Detailed alignment is owned by #1368 and the `companion-ui/docs/**` contracts.

- **Project / summarize / overlay:** allowed freely — these are read-side projections of authoritative or derived state.
- **Stage / queue / propose:** allowed — but produces a proposal-bearing object that is non-durable until governance applies it.
- **Mutate durably:** only through the governed mutation path, with server-side authority classification and a receipt. The UI does not classify its own writes as authoritative.
- **Provenance visibility:** the UI must keep provenance and the fact/inference/stale distinction visible; it must not flatten a derived or inferred value into an apparent fact.

## How this map is used

- **Before adding a new artifact, store, surface, or flow:** locate it in the seven layers and assign its authority role. If it does not fit, that is a signal the change crosses a boundary and needs an architecture-level decision, not a feature-level one.
- **When reviewing a change:** check that authority is not gained except at the governance step, that mirrors stay rebuildable, and that runtime/UI state is not silently persisted.
- **When terminology is unclear:** defer to the normalized vocabulary (#1366 / `ONTOLOGY_VOCABULARY.md`); this map uses those canonical terms.

## Cross-references and downstream contracts

This map is the parent for the rest of epic #1363. Each sibling contract owns its layer's detail:

- Terminology normalization — #1366 (`docs/CONCEPTS/ONTOLOGY_VOCABULARY.md` + glossary alignment)
- Semantic authority matrix — #1365 → `docs/SEMANTIC_AUTHORITY_MATRIX.md` (per-entity authority detail under Layer 4)
- Relation taxonomy — #1367 → `docs/CONCEPTS/RELATION_TAXONOMY.md` (relation detail under Layer 1)
- Machine mirror / DB authority contract — #1370 → `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (Layer 6 detail)
- Runtime vs durable state boundary — #1369 (Layer 5 detail)
- Companion UI projection alignment — #1368 (Layer 7 detail)
- Workflow mutation & governance semantics — #1371 (Layer 4 mutation detail)
- Semantic drift & boundary audit — #1372 (validates this map against the repo)

## Out of scope for this document

- New runtime behavior, schema, events, or on-disk layout — none introduced here.
- The detailed per-layer contracts — owned by the docs named per layer above.
- Current shipped-vs-planned runtime status — owned by `docs/ARCHITECTURE.md` and `docs/STATUS.md`.
- The structural subsystem decomposition — owned by `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`.

## Verification path

This document is verified by the existence of:
- a **seven-layer semantic map** that names ontology, artifact model, representation, governance/authority, runtime, machine mirror, and UI projection, each with its owner doc(s) and an explicit non-conflation rule;
- an **authority topology** that assigns every semantic object an authority role and states that authority is never gained except through an explicit governance transition;
- an **artifact-flow topology** covering `human note → companion → machine mirror → context bundle → runtime projection → proposal → receipt → durable mutation`;
- a **runtime boundary map** stating persistence/discardability per state; and
- explicit framing of the **Companion UI as a non-authoritative projection layer**.

`docs/DOCS_INDEX.md` and `docs/ARCHITECTURE.md` point to this document without duplicating its content.
