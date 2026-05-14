State: Initial conceptual vocabulary for the Contextualization Layer (docs-only, target-state framing).
Doc role: Concept vocabulary
Authority: Names the artifact classes used by the Contextualization Layer and the rules that separate them. Not an ontology, not a governance model, not a storage schema, not an implementation plan.

# Human and Agentic Artifacts in the Contextualization Layer

## 1. Purpose

This document defines the initial **artifact model** used by the Contextualization Layer.

It exists so that later work on companion metadata, artifact contracts, retrieval scope, and context activation can talk about the same kinds of things without each surface inventing its own vocabulary.

It is intentionally narrow:

- It defines *which classes of artifact* live in or near Markdown.
- It defines *what makes each class different* in audience, lifecycle, durability, and activation.
- It does not define a full ontology, a governance/authority model, a database schema, a prompt template, or a runtime implementation plan.

Related, more specific contracts already exist and remain authoritative for their own scope:

- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/ARTIFACT_MODEL_AND_LIFECYCLES.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md`
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`

This document sits above those contracts as a shared vocabulary, not as a replacement.

## 2. Core Principle

> **Markdown is the shared substrate, not the shared semantics.**

A `.md` file is a storage and editing format. It tells us almost nothing about what the file *is*, who it is *for*, how long it should *last*, or what *rights* it carries to influence an agent.

Implications:

- **Human knowledge** in Markdown remains primary and meaning-bearing. The Markdown belongs to the human.
- **Agentic memory** in Markdown is supporting material maintained for and around the human. The Markdown is human-readable on purpose, but it is not human-authored knowledge.
- **Machine mirrors** are technical projections. Even when they are serialized as Markdown for portability or inspection, they are not knowledge and they are not authoritative memory.

Three artifacts can sit side by side in the same folder, all be Markdown, and still be three different kinds of object. The Contextualization Layer must treat them as different.

## 3. Artifact Classes

The Contextualization Layer recognizes three initial classes:

1. **Human Knowledge Artifacts** — what the human writes, thinks with, and owns.
2. **Agentic Memory Artifacts** — what the system maintains so an agent can usefully support the human over time.
3. **Machine Mirror Artifacts** — rebuildable technical projections of the above for retrieval, indexing, and search.

These classes are *not* a complete ontology. They are the minimum needed so that later contracts can attach more specific semantics (lifecycle, authority, governance, sync rules) without conflating fundamentally different things.

## 4. Human Knowledge Artifacts

**Primary audience:** the human.

**Examples:**

- personal notes
- concepts and reference notes
- project documents
- decision records and design notes
- source notes (notes about a captured source)
- human reflections, journals, and working drafts

**System needs:**

- Readability for the human first, system second.
- Continuity across time and devices (rename, move, refactor without losing identity).
- Linking and backlinking that remain stable.
- Light review state (e.g. draft / working / settled), not a heavy workflow burden.
- Minimal frontmatter; the body is the artifact.
- **Companion metadata when system fields would otherwise pollute the primary note.**
- High durability. These are the artifacts the human relies on to think.

**Design rule:** the primary human note should remain something the human is comfortable reading, editing, and sharing in twenty years. System-required metadata that does not serve the reading experience should be moved out of the primary note rather than packed into its frontmatter.

## 5. Agentic Memory Artifacts

**Primary audience:** mixed — human and agent.

These are the artifacts the system maintains in order to support, explain, and continue agentic work over time without turning the agent into a hidden source of truth.

**Examples:**

- task snapshots (what an agent was doing, with what context, when)
- context bundles (the selected bridge object for a specific use, per `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`)
- activation traces (what context was actually used by an agent, and why)
- reflection records (post-hoc notes from an agent or from human review of an agent run)
- synthetic summaries (agent-produced condensations of human material)
- preference candidates (proposed durable preferences not yet promoted)
- procedural hints (small reusable how-do-I-do-X notes maintained near work)

**System needs:**

- Human-readable Markdown. Not a binary blob, not a base64 payload, not a screen of JSON the human cannot skim.
- Human-editable. The human must be able to open the file, correct it, and have the correction respected.
- Organized so a human can find them and understand what each one is. Folders, names, and links must remain legible.
- Clear, declared *purpose* per artifact (what is this for?).
- Explicit *source / provenance* references back to the human knowledge it is grounded in (and to the agent run that produced it, when relevant).
- Explicit *validity* or *staleness* posture — when does this stop being trusted? — consistent with `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`.
- Declared *activation policy* — see Section 9.
- Variable durability — see Section 8.

**Design rule:** agentic memory must not become an opaque machine file. The moment an agentic artifact stops being meaningfully human-readable and human-editable, it has stopped being agentic memory and has become a machine mirror (Section 6), and must be treated as such.

This class is supporting material. It does not override human-authored knowledge. The relationship between this class and the primary human surface is already constrained by `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`; this document only frames the artifact-level vocabulary.

## 6. Machine Mirror Artifacts

**Primary audience:** the system.

**Examples:**

- chunks (split fragments of a source for retrieval)
- embeddings and vector records
- indexes (full-text, structural, graph)
- caches and derived projections
- search results and ranked candidate lists
- graph projections of links and relations

**System needs:**

- Fully rebuildable from the human knowledge artifacts and (where relevant) agentic memory artifacts.
- Traceable back to a source artifact.
- No independent authority. A machine mirror cannot say something the human knowledge or agentic memory does not say.

**Design rule:** if a machine mirror disappears, it must be reconstructable. If reconstruction would lose information, the artifact is not really a mirror — it is either human knowledge or agentic memory, and is being misclassified.

This class is already constrained by `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md` and `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`; this document only names it as one of the three artifact classes.

## 7. Companion Note Pattern

Human knowledge artifacts should not be polluted with system metadata that does not serve the reading experience. When the system genuinely needs to track something *about* a primary note, the metadata should live in a **companion artifact** — near the note, distinguishable from it, and clearly subordinate to it.

The existing `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` defines the first concrete realization of this pattern for vault notes. The pattern is broader than that single contract:

- A companion artifact is *about* a primary artifact, not a replacement for it.
- A companion artifact may be agentic memory, a machine mirror, or both, depending on what it carries.
- The primary note should remain readable and editable without the companion present.

This document does not lock a single final file naming scheme. It records the alternatives the layer should remain open to:

- `Some Note.md` + `Some Note.agent.md` — sibling file, prefix or suffix-tagged.
- `Some Note.md` + `.context/Some Note.context.md` — parallel hidden directory, mirroring the note tree.
- A central companion registry keyed by note identity, if later operational needs justify centralization.

Each option has different consequences for visibility in the human's editor, portability across devices, and durability across renames. Picking one is a downstream contract decision, not a vocabulary decision.

## 8. Durability Tiers

Different artifact classes have legitimately different durability expectations. Naming them prevents the system from over-investing in fragile artifacts or under-investing in foundational ones.

| Artifact | Durability tier |
| --- | --- |
| Human-authored source knowledge (notes, concepts, source notes) | High |
| Decisions, design notes, and other settled-record artifacts | Very high |
| Agentic task snapshots | Medium |
| Context bundles and activation traces | Low to medium |
| Machine mirrors (chunks, embeddings, indexes, caches, search projections) | Low / rebuildable |

Interpretation:

- High durability means the system must work hard to never silently lose the artifact, even across format changes, device moves, and tool replacements.
- Medium durability means the artifact is expected to be retained over normal use but may be rotated, summarized, or pruned with a clear policy.
- Low / rebuildable means the artifact is allowed to disappear at any time, because it can be recreated from higher-durability sources.

These tiers are intentionally coarse. Finer-grained policy (retention windows, sync targets, backup obligations) belongs to later contracts.

## 9. Activation and Use Rights

Not every artifact in Markdown has the same right to influence an agent. The Contextualization Layer distinguishes at least the following rights:

- **Visible** — the artifact exists and the human can browse to it.
- **Retrievable** — the artifact is allowed to appear in retrieval / search results.
- **Activatable** — the artifact is allowed to enter an agent's working context for a task.
- **Instructional** — the artifact is allowed to influence how the agent reasons, not only what it knows.
- **Action-authorizing** — the artifact is allowed to justify a system action (a write, a notification, a downstream call).

These rights are cumulative-ish but not strictly hierarchical: an artifact may be retrievable without being activatable (e.g. a stale draft), or activatable without being action-authorizing (e.g. a preference candidate that has not yet been reviewed).

Defaults will differ by artifact class:

- Human knowledge artifacts default to *visible* and *retrievable*. Higher rights depend on artifact-specific signals (review state, trust posture).
- Agentic memory artifacts must declare their activation policy. They do not get *instructional* or *action-authorizing* rights by virtue of existing.
- Machine mirrors are typically *retrievable* but never *instructional* or *action-authorizing* on their own; their authority is the authority of the source they project.

The concrete rules for granting each right belong to a later authority/governance contract. This document only names the distinction so the later contract has something to attach to.

## 10. Non-goals

This document is explicitly **not**:

- A full cognitive or domain ontology. See `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md` and the broader concept-contract set for that work.
- A governance or authority model. Trust tiers, write gating, and authority boundaries live in their own contracts (`docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`, `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`, and related).
- A storage schema. No database tables, no JSON schema, no required frontmatter keys are defined here.
- A prompt template or retrieval recipe.
- An implementation plan or roadmap commitment.

Treat this document as vocabulary intake. Implementation lanes pick it up later through `docs-to-issue` or `feature-breakdown`.

## 11. Open Questions

The following are deliberately left open. They are recorded so later work can resolve them explicitly rather than by accident.

- **Where should companion notes live?** Sibling files, a parallel hidden directory, a central registry, or a mix per artifact subclass?
- **Which artifact classes need minimal frontmatter, and which need none?** What is the smallest set of fields that justifies inline metadata in a human-facing note?
- **Which agentic artifacts should be reviewed before activation?** In particular, which agentic artifacts may carry *instructional* or *action-authorizing* rights without a human review step?
- **How should stale agentic memory be surfaced to the human?** Quiet expiry, visible badge, prompt-on-use, or active review queue?
- **Which artifacts should be synced across devices and which can remain local or rebuildable?** Durability tier is a strong input but not the only one — privacy, cost, and device role also matter.

These questions are not blockers for naming the artifact classes. They are the first concrete things the layer will need to answer once it starts attaching contracts and runtime behavior to the vocabulary defined here.
