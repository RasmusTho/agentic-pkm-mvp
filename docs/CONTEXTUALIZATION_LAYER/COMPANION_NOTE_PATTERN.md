State: Initial companion note pattern for the Contextualization Layer (docs-only, target-state framing).
Doc role: Concept pattern
Authority: Names placement, linkage, types, readability, editability, and durability rules for companion notes used by the Contextualization Layer. Not a storage schema, not a watcher implementation, not a migration plan, not a validation schema, not a governance model.

# Companion Note Pattern for the Contextualization Layer

## 1. Purpose

This document defines the **Companion Note Pattern**: how system or agent metadata may live near or beside a primary artifact, in its own Markdown note, without polluting the primary artifact.

It exists so that later companion-note implementation work (location convention, validation, watcher behavior, sync rules) can share a single pattern across artifact classes rather than each surface inventing its own.

It is explicitly:

- **Not a storage schema.** No tables, no indexes, no on-disk path is locked here.
- **Not a runtime discovery implementation.** No watcher, scanner, or resolver is specified.
- **Not a governance or authority model.** Trust tiers, write gating, and authority limits live in their own contracts.
- **Not a requirement that every artifact must have a companion note.** Companions exist when metadata genuinely needs to live beside the artifact; not before.

`docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` already defines a first concrete realization of this pattern for vault notes (1:1 companion file per vault note, currently under `vault/_system/companions/<uuid>.md`). This document sits above that contract as the layer-wide pattern; it does not replace it.

## 2. Relationship to Existing Contextualization Docs

This document builds directly on:

- `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md`
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md`

And it cross-cuts:

- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md` — the existing vault-note companion contract.
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`

The load-bearing invariants from the prior Contextualization Layer docs:

- **Markdown is the shared substrate, not the shared semantics.** Primary notes and companions can both be Markdown and remain distinct kinds of object.
- **Metadata placement is part of artifact design.** Where metadata lives (inline, companion, structured artifact) is governed by the placement modes in `ARTIFACT_METADATA_CONTRACT.md` Section 3.
- **Human-facing notes should stay readable.** The primary note is for the human; its frontmatter must not grow into a system dumping ground.
- **Agentic artifacts should remain human-readable and editable.** Companion notes are themselves agentic artifacts (in the broad sense) and inherit that requirement.

## 3. Core Principle

> **Primary artifacts should preserve their human purpose. Companion notes carry metadata when that metadata is useful for system behavior but would reduce the clarity, portability, or readability of the primary artifact.**

Implications:

- Minimal, human-meaningful frontmatter may remain **inline** in the primary artifact (Section 3.1 of the metadata contract).
- Operational, machine-derived, or noisy metadata should usually **move to a companion note** (Section 3.2 of the metadata contract).
- Companion notes are still Markdown and should remain inspectable. A companion that becomes an opaque blob has stopped being a companion and has become a machine mirror; treat it as one.

## 4. When to Use a Companion Note

### Move to a companion when the metadata includes

- `activation_policy`
- retrieval hints
- `last_processed`
- `last_activated`
- `activation_count`
- `stale_after`
- derived / machine-suggested links
- candidate memory references
- processing state (ingest result, content hash, parser version, error state)
- agent annotations
- source mappings back to ingested raw material
- machine-derived summaries
- validation state

### Do not require a companion for

- simple human notes whose only metadata is minimal human-meaningful frontmatter
- temporary scratch notes
- machine mirrors that are rebuildable from sources
- agentic memory or bridge / assembly artifacts that already are structured operational artifacts (their metadata is part of the artifact itself, per `ARTIFACT_METADATA_CONTRACT.md` Section 3.3)

The principle in both directions: companion notes exist to avoid pollution and to give the system somewhere to write. If neither pressure applies, the companion does not justify itself.

## 5. Allowed Placement Patterns

The placement options below are **acceptable patterns**, not final mandates. The choice of default is a downstream contract decision (see Open Questions, Section 14).

### 5.1 Adjacent Companion File

```
Some Note.md
Some Note.agent.md
```

Pros:

- Easy for a human to inspect — the companion is right next to the note.
- Moves with the primary note when files are reorganized manually.

Cons:

- Can clutter folders, especially in directories with many notes.
- Rename/move handling needs care: the companion must follow the primary, or break linkage.

### 5.2 Hidden Local Context Folder

```
Some Note.md
.context/Some Note.context.md
```

Pros:

- Keeps the primary folder visually clean.
- Keeps metadata near the source folder.

Cons:

- Hidden folders may be awkward in some editors and sync tools.
- Move/rename handling still needs care.

### 5.3 Parallel Metadata Tree

```
Mimer/Concepts/Some Note.md
.agentic/context/Mimer/Concepts/Some Note.context.md
```

Pros:

- Keeps the human vault visually clean across the whole tree.
- Easier for the system to scan and manage as a coherent subtree.

Cons:

- Harder for humans to browse casually — companions are not adjacent.
- Requires reliable path mapping when the primary note moves.

### 5.4 Central Companion Registry

```
.agentic/companions/registry.md
.agentic/companions/<artifact_id>.md
```

Pros:

- Stable when primary notes are renamed or moved, as long as `artifact_id` is preserved.
- Good for ID-based lookup and bulk operations.

Cons:

- Less transparent — a human reading a primary note does not see the companion nearby.
- Requires stronger tooling to navigate from primary to companion.

These patterns can coexist. A single deployment may use adjacent companions for a small set of high-value notes and a central registry for ID-keyed companions, depending on artifact class.

## 6. Required Linkage

A companion note must be able to identify its target. The following are logical fields; their on-disk form is not locked here.

- `companion_for` — short identifier of what this companion is for (e.g. the target title or a stable handle).
- `target_artifact_id` *(optional)* — the stable `artifact_id` of the target, when one exists.
- `target_path` — current best-effort path to the target.
- `target_artifact_class` — one of the classes in `HUMAN_AND_AGENTIC_ARTIFACTS.md` (typically `human_knowledge`).
- `target_hash` *(optional)* — content hash of the target at the time the companion was last reconciled.
- `created`
- `updated`
- `generated_by` or `maintained_by` — which agent / pipeline / human is responsible for this companion's content.
- `companion_type` — see Section 8.

Linkage modes have a trade-off:

- **Path-based linkage** is easy to read and works without identifier infrastructure, but is fragile under renames and moves.
- **ID-based linkage** is stable across renames and moves, but requires an `artifact_id` to exist and to be reachable from the target.

A future implementation may support both, with the companion holding both fields and the system reconciling on whichever is currently valid.

## 7. Reverse Linkage from Primary Notes

Primary human notes should **not** be forced to link to their companion.

Allowed options, in order of decreasing invisibility to the human:

- **No reverse link.** The system resolves primary → companion through placement convention or `artifact_id` lookup.
- **Minimal frontmatter field** in the primary note, e.g. `companion: auto` or `companion: <relative_path>`.
- **Explicit link in a hidden / comment block** at the bottom of the primary note.
- **Explicit visible link**, used only for high-value artifacts where the human benefits from seeing the companion exists.

**Recommendation:** default to **no visible reverse link** unless the human benefits from seeing it. The companion's job is to absorb noise, not to advertise itself in the primary note.

## 8. Companion Note Types

A `companion_type` field declares what the companion is primarily carrying. A single companion may be `mixed_companion` when it spans multiple types.

- `processing_companion` — ingest state, content hashes, parser version, processing errors, retry posture.
- `activation_companion` — `activation_policy`, `last_activated`, `activation_count`, retrieval hints, salience signals.
- `retrieval_companion` — embedding pointers, chunking summary, dominant index hits, retrieval-time signals (without becoming a machine mirror).
- `provenance_companion` — `source_refs`, `derived_from`, import metadata, dominant source role, related-artifact graph hints.
- `review_companion` — `review_state`, human-review notes, decision history, flags raised by checks.
- `synthesis_companion` — machine-derived summaries, candidate memories, suggested links, synthetic outlines awaiting review.
- `mixed_companion` — when the companion carries more than one of the above; the `companion_type` value names that it is mixed and the body sections name which subtypes are present.

Companion type matters because consumers and review surfaces may want to filter by it (e.g. "show me all unreviewed `synthesis_companion` candidates"). The list is illustrative, not closed.

## 9. Human Readability Requirements

Companion notes are themselves human-inspectable artifacts. They should:

- have a clear title that names the target
- identify the target artifact (path and / or `artifact_id`)
- explain their purpose in plain language
- separate human-readable summary from machine-readable metadata, so a human scanning the file is not buried in tokens
- avoid opaque binary or base64 blobs when alternatives exist; large machine data belongs in a machine mirror, not a companion
- be safe for a human to inspect and edit without breaking the system (Section 10 expands on this)

### Suggested companion note structure

```markdown
# Companion Metadata: <Target Title>

## Purpose

One-line explanation of what this companion exists for.

## Target

- target_path: ./Some Note.md
- target_artifact_id: 01HF...
- target_artifact_class: human_knowledge

## Human Summary

A short, plain-language description of what the companion currently records about the target.

## System Metadata

Machine-readable fields in a fenced block or YAML frontmatter, grouped so a human can skim them.

## Derived Links

Machine-suggested links awaiting review, with confidence and source.

## Candidate Memories

Candidate memory artifacts the system would like to promote, with provenance.

## Processing Log

Append-only entries describing ingest, reconciliation, and validation events.
```

Sections are not all required. A companion that only carries processing state can omit `Derived Links` and `Candidate Memories`.

## 10. Editability and Conflict Handling

Principles:

- **Human edits to companion notes should be respected.** A human who corrects a candidate memory or removes a wrong derived link is correcting the system, not breaking it.
- **Agent and system updates should avoid overwriting human-authored sections.** Sections written or modified by the human must not be silently replaced.
- **Future implementations should separate managed blocks from human-editable blocks.** A clear marker for "this block is system-managed" lets the system rewrite the block safely while the human owns the surrounding context.
- **If the target artifact changes substantially**, companion metadata should be re-validated. `target_hash` can drive this without forcing a full re-derivation on every edit.

Managed-block markers, conflict resolution, and three-way reconciliation are **not implemented here**. This section only records that the future implementation will need them.

## 11. Durability and Sync

Companion durability follows the target, not a single universal rule.

- Companion notes for **durable human knowledge** (concepts, decisions, project documents) may need higher durability, because losing them loses context the human accumulated.
- Companion notes for **transient task snapshots** or short-lived agentic memory may be lower durability and may be safely rotated.
- **Some companion metadata may be local-only** — device-specific signals (last open time, local activation count) that should not propagate.
- **Some companion metadata should sync with the vault** — provenance, review state, candidate memories that belong to the artifact regardless of device.
- **Machine mirrors should remain rebuildable** and should not require companion notes. If a machine mirror has metadata that needs to survive, that metadata is companion-shaped and the mirror itself should be reclassified.

`ARTIFACT_METADATA_CONTRACT.md` Section 10 already defines the staleness / validity fields companion notes can use; this section only states that the durability tier of a companion is a function of its target.

## 12. Examples

These three examples are illustrative. Field names, file naming, and on-disk shape are not normative here.

### 12.1 Adjacent companion for a human concept note

`Mimer/Concepts/Contextualization Layer.md` (primary, unchanged):

```yaml
---
artifact_class: human_knowledge
artifact_type: concept_note
title: Contextualization Layer
maturity: working
created: 2026-05-14
updated: 2026-05-14
---
```

`Mimer/Concepts/Contextualization Layer.agent.md` (adjacent companion):

```markdown
---
artifact_class: companion_metadata
companion_for: Contextualization Layer
target_path: ./Contextualization Layer.md
target_artifact_class: human_knowledge
companion_type: mixed_companion
created: 2026-05-14
updated: 2026-05-14
generated_by: indexer
---

# Companion Metadata: Contextualization Layer

## Purpose

Carry processing, activation, and derived-link signals for the concept note
without cluttering the primary frontmatter.

## System Metadata

- last_processed: 2026-05-14T19:00:00Z
- target_hash: sha256:...
- activation_policy: explicit_or_contextual
- last_activated:
- activation_count: 0

## Derived Links

- [[Artifact Metadata Contract]] — confidence: 0.92

## Candidate Memories

(none)
```

### 12.2 `.context` folder companion for a project document

`Projects/Mimer Alpha/Plan.md` (primary, unchanged): minimal inline frontmatter only.

`Projects/Mimer Alpha/.context/Plan.context.md` (hidden adjacent companion):

```markdown
---
artifact_class: companion_metadata
companion_for: Plan
target_path: ../Plan.md
target_artifact_class: human_knowledge
companion_type: review_companion
created: 2026-05-12
updated: 2026-05-14
maintained_by: review_agent
---

# Companion Metadata: Mimer Alpha — Plan

## Purpose

Carry review state and human-review notes without altering the primary plan note.

## Target

- target_path: ../Plan.md
- target_artifact_class: human_knowledge

## System Metadata

- review_state: reviewed
- last_validated: 2026-05-14

## Processing Log

- 2026-05-12: ingested
- 2026-05-14: reviewed by human, marked `reviewed`
```

### 12.3 Central registry companion keyed by `artifact_id`

`.agentic/companions/01HF...abcd.md`:

```markdown
---
artifact_class: companion_metadata
companion_for: Decision — Adopt Companion Note Pattern
target_artifact_id: 01HF...abcd
target_path: Decisions/Adopt Companion Note Pattern.md
target_artifact_class: human_knowledge
companion_type: provenance_companion
created: 2026-05-14
updated: 2026-05-14
generated_by: provenance_pipeline
---

# Companion Metadata: Adopt Companion Note Pattern

## Purpose

Carry provenance and derived-link signals for a decision record by stable id,
so renames and moves of the primary file do not break the linkage.

## Target

- target_artifact_id: 01HF...abcd
- target_path: Decisions/Adopt Companion Note Pattern.md
- target_artifact_class: human_knowledge
- target_hash: sha256:...

## System Metadata

- source_refs:
    - docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md
    - docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md
- derivation_method: review

## Derived Links

- [[Contextualization Layer]]
- [[Artifact Metadata Contract]]
```

## 13. Non-goals

This document is explicitly **not**:

- a final filename standard,
- a watcher implementation,
- a migration plan from current vault layouts,
- a validation schema,
- a governance or authority model,
- a requirement that every note has a companion.

The placement options in Section 5 are alternatives, not a chosen default. The fields in Sections 6 and 8 are logical, not on-disk.

## 14. Open Questions

The following are deliberately left open. They are recorded so later contracts and implementation work can resolve them explicitly.

- **Which placement pattern should be default for Alpha?** Adjacent (Section 5.1), hidden adjacent (5.2), parallel tree (5.3), central registry (5.4), or a mix per artifact class?
- **Should stable human artifacts receive `artifact_id` automatically**, and if so by which surface (capture, ingest, review)?
- **Should companion notes be created lazily** (only when the system has something to write) **or eagerly** (alongside every artifact of a given class)?
- **Should companion notes sync across devices by default**, or is the default local-only with explicit promotion to vault sync?
- **How should rename / move detection work** when the chosen placement is path-based and the primary note moves?
- **Which sections should be system-managed vs human-managed** in the companion body, and how should that boundary be expressed in Markdown?

These questions are not blockers for naming the pattern. They are the first concrete decisions later companion-note implementation work will need to make.
