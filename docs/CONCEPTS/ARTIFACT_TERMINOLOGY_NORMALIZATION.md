State: Concept contract companion (normalized artifact/runtime/governance vocabulary; integrates existing owners).
Doc role: Reference
Authority: Normalizes the artifact, runtime, mirror, and governance terminology that the semantic layers use. It consolidates and cross-references existing owners; it does not redefine them. For domain/ontology terms it is subordinate to `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`; for field-level metadata it is subordinate to `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md`; for layer ownership it aligns to `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.
Last reviewed: 2026-05-29
Last verified against: docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/CONCEPTS/ONTOLOGY_VOCABULARY.md, docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md, docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md, docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md, docs/NOTE_KIND_POLICIES.md, docs/ARCHITECTURE.md, docs/GLOSSARY.md, epic #1363, issue #1366.

# Artifact Terminology Normalization

## Purpose

The repo has several terms that look alike but mean different things — `artifact_class`, `artifact_type`, `artifact_kind` / `kind`, `memory_type`, `note`, `object`, `projection`, `mirror`, `runtime artifact`, `workspace state`, and the conceptual `governance object`. The underlying semantics are already strong and mostly well-defined, but the definitions live in different documents and the lookalike names invite conflation.

This document does three things:

1. Gives each artifact/runtime/governance term a **single canonical definition** and the **semantic layer** it belongs to (using the seven layers in `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`).
2. Inventories the **deprecated / conflicting** uses and the **migration recommendation** for each.
3. Provides a **cross-reference map** so a reader can jump from a term to its owner contract.

It is deliberately *not* a new authority. Where it summarizes a field or term, the owner doc named in the cross-reference map wins on any conflict, and this document is updated to match.

Relationship to existing vocabulary owners:

- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md` owns the **domain/ontology** terms (`note`, `object`, `source`, `agent`, `memory`, `domain`, `bridge`, `projection`, `receipt`, etc.) and their drift map. This document does not restate that map; it points to it and adds the **field-level and layer-ownership** view that the ontology vocabulary does not cover.
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` owns the **field-level** definitions of `artifact_class`, `artifact_type`, and `memory_type`. This document reflects those definitions and aligns them to semantic layers.

## Canonical term table

Each term has exactly one canonical meaning and one owning semantic layer. "Field?" marks terms that are concrete frontmatter/metadata fields versus conceptual terms.

| Canonical term | Field? | Semantic layer | Canonical meaning | Owner doc |
| --- | --- | --- | --- | --- |
| `artifact_class` | Yes | Artifact model (L2) | The artifact **family**. Umbrella values: `human_knowledge`, `agentic_memory`, `bridge_artifact`, `machine_mirror`, `companion_metadata`. Concrete taxonomy class names (e.g. `evergreen_note`, `media_note`) imply their umbrella class and are preferred when known. | `ARTIFACT_METADATA_CONTRACT.md`, `LIFE_WIDE_ARTIFACT_TAXONOMY.md` |
| `artifact_type` | Yes | Artifact model (L2) | The **sub-type within a class** (e.g. `concept_note`, `task_snapshot`, `context_bundle`, `embedding_record`). Orthogonal to `memory_type`. | `ARTIFACT_METADATA_CONTRACT.md` |
| `memory_type` | Yes | Artifact model (L2), agentic only | The **cognitive class** of an agentic memory artifact (`working_context`, `episodic_memory`, `semantic_memory`, `prospective_memory`, `procedural_memory`, `preference_memory`, `policy_memory`). Applies only to `agentic_memory`; must not be conflated with `artifact_type`. | `ARTIFACT_METADATA_CONTRACT.md` |
| `kind` / `artifact_kind` / `policy_profile_kind` | Yes | Governance / authority (L4) | A **policy-routing signal** for notes/objects (e.g. `note`, `reference`, `log`). It routes which policy profile and state axes apply; it does **not** define structure, schema, or artifact family. Runtime object identity may remain `kind="note"` independent of this. | `NOTE_KIND_POLICIES.md`, `CORE_CONTRACT.md` |
| Human Knowledge Artifact | No | Artifact model (L2) | What the human writes, thinks with, and owns; meaning-bearing and primary. Authority role: authoritative-human. | `HUMAN_AND_AGENTIC_ARTIFACTS.md` §4 |
| Agentic Memory Artifact | No | Artifact model (L2) | System-maintained supporting material for the human; human-readable, never overriding human knowledge. Authority role: supporting-agentic. | `HUMAN_AND_AGENTIC_ARTIFACTS.md` §5, `AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` |
| Machine Mirror Artifact | No | Machine mirror (L6) | A rebuildable technical projection (chunks, embeddings, indexes, caches, search/graph projections). No independent authority; rebuildable from source. | `HUMAN_AND_AGENTIC_ARTIFACTS.md` §6, `ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` |
| Companion (metadata) Note | No | Artifact model (L2) | A first-class system artifact *about* a primary note, carrying continuity/repair metadata the primary note should not hold. | `COMPANION_NOTE_CONTRACT.md`, `COMPANION_NOTE_PATTERN.md` |
| Context bundle (bridge / assembly) | No | Artifact model (L2), bridge | A per-use selection/assembly of context for a specific operation. Not memory; does not inherit the lifecycle/activation of what it references. | `CONTEXT_BUNDLE_CONTRACT.md` |
| `projection` | No | Representation (L3) / mirror (L6) | A **bounded representation** of an artifact for a runtime, store, search, mirror, or API purpose — never the artifact itself. | `ONTOLOGY_VOCABULARY.md`, `ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` |
| `mirror` | No | Machine mirror (L6) | Shorthand for a Machine Mirror Artifact or a Mirror Artifact projection. Always rebuildable; never the primary human artifact. | `MIRROR_RECEIPT_DECISION.md`, `ONTOLOGY_VOCABULARY.md` |
| runtime artifact / runtime state | No | Runtime (L5) | State that exists only during execution (AgentState, session/workspace/panel/overlay/retrieval state). Ephemeral unless explicitly persisted under contract. | `SEMANTIC_SYSTEM_ARCHITECTURE.md` L5, `ARCHITECTURE.md`, #1369 follow-up |
| workspace state | No | Runtime (L5) / UI projection (L7) | Runtime aggregate of the active working surface; a projection/overlay, not a durable artifact. | `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`, #1368/#1369 follow-up |
| session state | No | Runtime (L5) | Per-session ephemeral execution state, including chat-session co-authoring state. | `ARCHITECTURE.md`, `CANVAS_CHAT_SURFACE/README.md` |
| overlay | No | Runtime (L5) / UI projection (L7) | A derived, non-durable shaping of attention/salience over artifacts (e.g. `zone`). Never a gate, never authority. | `LAYERING_MODEL.md` (Zone), `ONTOLOGY_VOCABULARY.md` |
| Receipt | No | Governance / authority (L4) | A human-legible record of what happened, with what authority, and with what result. Authority role: governance-recorded (durable). | `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`, `ONTOLOGY_VOCABULARY.md` |
| Proposal | No | Governance / authority (L4) | A staged, not-yet-adopted change. Authority role: proposal-bearing (non-durable until applied). | `ONTOLOGY_VOCABULARY.md`, #1371 follow-up |
| governance object | No | Governance / authority (L4) | **Conceptual umbrella** (not a frontmatter field) for the admissibility/audit/write-safety objects: policy profiles, write guards, action-catalog entries, proposals, receipts. Use the specific term, not this umbrella, in contracts. | `SEMANTIC_SYSTEM_ARCHITECTURE.md` L4, #1365/#1371 follow-up |

## Semantic layer ownership table

Which layer owns which vocabulary, for quick routing. This is the terminology view of the seven layers in `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.

| Semantic layer | Owns these terms | Vocabulary owner doc |
| --- | --- | --- |
| Ontology (L1) | entity, relation, actor, `System Agent`, commitment, `Cognitive Artifact`, `Sphere`, `Context` | `ONTOLOGY_VOCABULARY.md`, `COGNITIVE_ONTOLOGY.md` |
| Artifact model (L2) | `artifact_class`, `artifact_type`, `memory_type`, Human Knowledge / Agentic Memory / Machine Mirror / Companion / Bridge artifact classes | `ARTIFACT_METADATA_CONTRACT.md`, `HUMAN_AND_AGENTIC_ARTIFACTS.md` |
| Representation (L3) | frontmatter fields, `source_ref`, UUID identity, path, `projection`, companion placement | `FRONTMATTER.md`, `CORE_CONTRACT.md`, `ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` |
| Governance/authority (L4) | trust tiers, `kind`/policy profile, write guard, proposal, receipt, governance object | `TRUST_SEMANTICS_CONTRACT.md`, `NOTE_KIND_POLICIES.md`, `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` |
| Runtime (L5) | runtime artifact, runtime/session/workspace state, AgentState, overlay | `ARCHITECTURE.md`, #1369 follow-up |
| Machine mirror (L6) | `mirror`, chunk, embedding, index, cache, search/graph projection | `MIRROR_RECEIPT_DECISION.md`, `EMBEDDINGS.md`, #1370 follow-up |
| UI projection (L7) | panel, workspace projection, runtime overlay (UI), proposal staging surface | `companion-ui/docs/**`, #1368 follow-up |

## Deprecated / conflicting term inventory

| Usage to avoid | Why it conflicts | Migration recommendation |
| --- | --- | --- |
| Using `artifact_kind` as a synonym for `artifact_class` | `kind` is a **policy-routing** signal (L4), `artifact_class` is the **artifact family** (L2). They answer different questions. | Keep `kind` / `policy_profile_kind` for policy routing only. Use `artifact_class` for family. Do not introduce new `artifact_kind` frontmatter as a family field. |
| Using `artifact_type` and `memory_type` interchangeably | `artifact_type` is form/sub-type; `memory_type` is cognitive memory class (agentic only). Orthogonal axes. | Keep both; never collapse. `memory_type` only on `agentic_memory` artifacts. |
| Using `object` as a domain term | `object` drifts across store row, file surrogate, payload, and domain artifact. | Use `Cognitive Artifact` / artifact-class language in docs; reserve `object` for storage/runtime per `ONTOLOGY_VOCABULARY.md`. |
| Using `note` to mean any artifact | `note` drifts across vault note, markdown file, object kind, content unit. | Use `Vault Note` for the writing-surface note; `artifact` / artifact-class for the general case. |
| Using `projection` for the artifact itself | A projection is a bounded representation, not the artifact. | Reserve `projection` for representations/mirrors; name the artifact by its class. |
| Using `mirror`, `note log`, and `receipt` as synonyms | They are related but distinct: mirror (L6 rebuildable), receipt (L4 governance-recorded). | Keep distinct per `MIRROR_RECEIPT_DECISION.md`; a receipt is durable accountability, a mirror is rebuildable. |
| Using `workspace state` as if durable | Workspace state is a runtime/UI projection (L5/L7), not a durable artifact. | Treat as ephemeral; persist only via explicit governed transition. |
| Using `governance object` in normative contracts | It is a conceptual umbrella, not a single type or field. | Name the specific object (policy profile, write guard, proposal, receipt). |
| Temperature metaphors (`hot`/`warm`/`cold`) for cognitive function | Storage-temperature ≠ cognitive function. | Use `writing plane` / `retention plane` / salience per `ONTOLOGY_VOCABULARY.md` and `LAYERING_MODEL.md`. |

## Cross-reference map between major contracts

Where to go for the authoritative definition, by concern:

- **Artifact families & field-level metadata** → `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` (with `LIFE_WIDE_ARTIFACT_TAXONOMY.md` for concrete class names).
- **Artifact-class vocabulary & the "Markdown is substrate not semantics" rule** → `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md`.
- **Domain/ontology terms & drift map** → `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`.
- **Policy routing (`kind`)** → `docs/NOTE_KIND_POLICIES.md` + `docs/CORE_CONTRACT.md`.
- **Trust tiers & authority language** → `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`.
- **Mirror vs receipt** → `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md` + `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.
- **Representation/frontmatter** → `docs/FRONTMATTER.md` + `docs/CORE_CONTRACT.md`.
- **Semantic layer ownership** → `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.
- **Per-entity authority flags** → semantic authority matrix (#1365 follow-up).
- **Relation terms** → relation taxonomy (#1367 follow-up).

## Usage rule

When a term appears in multiple layers, the **owning layer's** canonical meaning (per the canonical term table) wins. Implementation terms may remain in code and migration-era docs but should be read through this normalization. If a runtime/schema term conflicts with these definitions, the ontology/contract defines meaning, architecture defines current wiring, and schema/code define current representation — and these layers must not be silently collapsed (consistent with `ONTOLOGY_VOCABULARY.md` source-of-truth rule).

## Verification path

This document is verified by the existence of:
- a **canonical term table** giving each artifact/runtime/governance term one meaning and one owning semantic layer;
- a **semantic layer ownership table** mapping each of the seven layers to the terms it owns;
- a **deprecated / conflicting term inventory** with migration recommendations; and
- a **cross-reference map** routing each concern to its owner contract.

No contradictory artifact terminology is introduced: `artifact_class`, `artifact_type`, `memory_type`, and `kind` are kept on distinct axes, matching `ARTIFACT_METADATA_CONTRACT.md` and `NOTE_KIND_POLICIES.md`.
