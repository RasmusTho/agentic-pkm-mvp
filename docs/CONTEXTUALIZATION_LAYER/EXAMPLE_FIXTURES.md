State: Concrete example fixtures for the Contextualization Layer artifact model (docs-only, illustrative).
Doc role: Illustrative examples
Authority: Provides concrete, instantiated examples of how the five Contextualization Layer artifact classes coexist without semantic collapse. Not a storage schema, not a runtime implementation, not a governance model, not a final metadata format. Examples are intentionally illustrative and suitable for later conversion into formal test fixtures.

# Example Fixtures for the Contextualization Layer Artifact Model

## 1. Purpose

This document provides concrete, walkable examples of how the five artifact classes defined in the Contextualization Layer docs work in practice:

- Human knowledge artifacts
- Companion metadata notes
- Agentic memory artifacts
- Bridge / assembly artifacts
- Machine mirror artifacts

Each example instantiates the metadata contract and shows how these classes remain distinct even when they share a folder, reference each other, or exist in parallel.

## 2. Scenario

**Setup:** A human is designing a feature for agent memory in a PKM system. Over a three-day period:

1. The human writes and settles a concept note on agent memory (human knowledge artifact).
2. The system tracks metadata about that note without polluting it (companion metadata note).
3. An agent produces a task snapshot while working on agent-memory implementation (agentic memory artifact).
4. A context bundle is assembled to help the agent orient to the feature design (bridge / assembly artifact).
5. Later, the system builds chunks and embeddings from the concept note to support retrieval (machine mirror artifacts).

This scenario does **not** require runtime implementation. The examples below are human-readable and suitable for documentation, test fixtures, or later schema design.

## 3. Example: Human Knowledge Artifact

**File:** `docs/CONCEPTS/Agent Memory Design.md`

**Role:** Primary source of truth for agent memory feature design. Written and owned by the human. Serves the human's thinking and reading.

```yaml
---
artifact_class: human_knowledge
artifact_type: concept_note
title: Agent Memory Design
maturity: settled
created: 2026-05-10
updated: 2026-05-12
tags: [agent, memory, pkm, design]
---

# Agent Memory Design

## Core Principle

Agent memory is the system's maintained supporting material that allows an agent to
usefully support the human over time without becoming a hidden source of truth.

Agent memory artifacts are human-readable and human-editable. The moment an artifact
stops being meaningfully editable by a human, it transitions from agentic memory to a
machine mirror.

## Memory Types

Agents maintain several cognitive memory classes:

- **Working context**: Short-lived recall used during an active task. Example: "We're
  currently designing the retrieval scope for activated artifacts."
- **Episodic memory**: Records that something happened, when, and in what situation.
  Example: "On 2026-05-11, we discovered that the metadata contract's matrix scope
  was too broad."
- **Semantic memory**: Stabilized meaning the system can reuse across situations.
  Example: "Companion notes are not agentic memory; they are metadata carriers."

(... rest of note continues ...)
```

**Why this is human knowledge:**
- Written by a human for human reading and thinking
- Stays readable without any system metadata
- Owned by the human; agent actions support and reference it but don't override it

## 4. Example: Companion Metadata Note

**File:** `_system/companions/Agent Memory Design.agent.md` *(location convention illustrative; not final)*

**Role:** System and agent metadata about the human knowledge artifact, stored separately so it does not clutter the primary note.

```yaml
---
artifact_class: companion_metadata
artifact_type: companion_metadata
target_ref: "docs/CONCEPTS/Agent Memory Design.md"
target_artifact_class: human_knowledge
title: Companion metadata for Agent Memory Design
created: 2026-05-10
updated: 2026-05-12
---

## Activation Policy

- `activation_policy: explicit_or_contextual`
- `last_activated: 2026-05-12T14:30:00Z`
- `activation_count: 3`
- `last_processed: 2026-05-12T10:15:00Z`
- `processing_status: content_hash_current`

## Derived Links

The following candidate memory references were surfaced by the system while processing
this note. The human has not yet accepted or rejected them; they remain candidates.

- **Related to:** `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` (Section 2 — bridge
  artifacts carry context between memory and cognition, same boundary principle)
- **Related to:** `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` (Section
  6 — definition of agentic memory artifact metadata)

## Retrieval Tuning

- `retrieval_strategy: semantic_and_keyword_hybrid`
- `keyword_weight: 0.4`
- `semantic_weight: 0.6`
- `chunk_strategy: concept_boundary_sensitive`
- `min_chunk_size: 100`
- `max_chunk_size: 800`

(... additional system fields for ingest, cache state, etc. ...)
```

**Why this is companion metadata:**
- Exists to support system behavior without cluttering the primary note
- Tracks processing state, activation counts, derived links that the primary note's reader would find noisy
- Remains human-readable; a human can open it and understand what the system is tracking
- Supports the agent's continued work without overriding the human's ownership of the primary note

## 5. Example: Agentic Memory Artifact

**File:** `_memory/agent_tasks/2026-05-11_implement_memory_feature_snapshot.md`

**Role:** A task snapshot produced by an agent during feature implementation work. Captures what the agent was doing, what context it was working with, what it completed, and what remains.

```yaml
---
artifact_class: agentic_memory
artifact_type: task_snapshot
memory_type: working_context
title: Agent Memory Feature Implementation (2026-05-11 EOD Snapshot)
purpose: Capture task progress, open blockers, and next-action plan for Agent Memory feature implementation
created: 2026-05-11T17:00:00Z
source_refs:
  - docs/CONCEPTS/Agent Memory Design.md
  - "issue:#900"
  - "issue:#941"
confidence: high
validity: valid_until_next_update
stale_after: 2026-05-13T17:00:00Z
activation_policy: explicit
human_review: required
author_type: agent
primary_audience: human
---

## Task Summary

Implementing the Contextualization Layer artifact model, specifically the example
fixtures that demonstrate how human knowledge, agentic memory, companion metadata,
bridge artifacts, and machine mirrors coexist without semantic collapse.

## Progress Completed (by 2026-05-11 EOD)

- [x] Read and synthesized all four Contextualization Layer docs (HUMAN_AND_AGENTIC_ARTIFACTS.md, ARTIFACT_METADATA_CONTRACT.md, COMPANION_NOTE_PATTERN.md, ARTIFACT_LIFECYCLE_MODEL.md)
- [x] Identified the five artifact classes and their key properties
- [x] Drafted scenario and examples for human knowledge + companion pair
- [x] Began agentic memory artifact example

## Open Blockers

- None blocking this work. The lifecycle docs merged cleanly; bridge/assembly and machine mirror examples are independent.

## Next Actions (for continuation)

1. Complete agentic memory task snapshot example with full metadata
2. Design a context bundle (bridge/assembly) example showing how it references source artifacts without promoting them to memory
3. Add machine mirror example showing chunks, embeddings, and rebuildability semantics
4. Cross-reference all examples to show linkage and semantic boundaries

## Context Used

- `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` — artifact vocabulary
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` — metadata fields and placement
- `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_LIFECYCLE_MODEL.md` — lifecycle state definitions
- `docs/CONTEXTUALIZATION_LAYER/COMPANION_NOTE_PATTERN.md` — companion note placement and boundary

## Decision Points Deferred to Next Snapshot

- Whether example fixtures should live in `docs/` (source-of-truth) or `_memory/` (example-only).
  Current approach: fixtures in docs/ as Markdown, with comments that they are illustrative.
- File naming and location convention for companion notes: sibling `.agent.md`, `.context/` subfolder,
  or centralized registry. Left open per COMPANION_NOTE_PATTERN.md Section 14.
```

**Why this is agentic memory:**
- Produced by an agent to support continued work and human understanding
- Fully human-readable and human-editable (the human can correct it or add notes)
- Carries working context and task state that helps the agent resume later
- Explicitly sources back to the human knowledge artifacts it is grounded in
- Declares its validity, activation policy, and review posture so the human can decide whether to trust it

## 6. Example: Bridge / Assembly Artifact (Context Bundle)

**File:** `_memory/context_bundles/2026-05-11_agent_memory_feature_orientation.md`

**Role:** A context bundle assembled to help an agent (or human) orient to the agent memory feature design and get productive quickly. This is a per-use selection, not retained memory.

```yaml
---
artifact_class: bridge_artifact
artifact_type: context_bundle
artifact_id: "bundle_2026_05_11_agent_memory_orientation"
title: Agent Memory Feature Orientation Bundle
purpose: Orient a new or returning agent to the scope, design, and status of the Agent Memory feature work
trigger: Agent asked to continue implementation on 2026-05-11
scope: Agent Memory feature design and implementation
assembled_for: "agent"
assembled_at: 2026-05-11T15:00:00Z
assembled_by: "system"
created: 2026-05-11T15:00:00Z
validity: valid
stale_after: 2026-05-13T23:59:59Z
source_refs:
  - docs/CONTEXTS/Agent Memory Design.md
  - "issue:#900"
  - "issue:#941"
  - "issue:#942"
  - "issue:#943"
---

## Bundle Contents

This bundle contains artifacts selected to give a new agent quick context on what the
Agent Memory feature is, why it matters, and what work remains.

### Included Artifacts

| Artifact | Role | Authority | Purpose |
| --- | --- | --- | --- |
| `docs/CONCEPTS/Agent Memory Design.md` | concept note | may_answer, may_orient | Primary design doc; defines memory types, boundaries, and rationale |
| `issue:#900` | feature spec | may_answer, may_orient | Parent feature tracking; shows scope and sequencing decisions |
| `docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md` | vocabulary | may_answer | Defines artifact classes; required context for understanding design |
| `docs/CONTEXTUALIZATION_LAYER/ARTIFACT_METADATA_CONTRACT.md` | contract | may_answer | Defines metadata shapes; needed to design fixtures correctly |
| `_memory/agent_tasks/2026-05-11_implement_memory_feature_snapshot.md` | task snapshot | may_propose | Captures prior agent's progress and open questions |

### Excluded Artifacts

- Runtime implementation issues (#944–#950). These are out of scope for orientation.
- Internal design discussions in PR review comments. Primary source is the docs, not comments.

## Authority Flags

The bundle declares what it may support:

- `may_answer: true` — bundle contains the facts needed to understand the feature
- `may_orient: true` — bundle helps the agent (re)orient to the scope and status
- `may_resurface: false` — bundle is not a memory artifact and should not be retained as settled memory
- `may_propose: false` — bundle references a task snapshot but does not itself propose actions
- `may_write: false` — bundle is read-only; any writes must be sourced from the primary artifacts or new task snapshots

## Construction Method

- `construction_method: manual_selection` (assembled by human or system policy, not automated retrieval)
- Selected to hit a breadth-first path: why → what → how → who (design, scope, prior work)

## Expiry

Bundle expires 2 days after assembly unless explicitly renewed. After expiry, a new
bundle assembly is required; the old one is not retained as memory.

### Consumption

This bundle was created but has not yet been consumed (no agent has used it for a task).
Once consumed, the outcome should be recorded in `consumed_by` and `receipts`.
```

**Why this is a bridge / assembly artifact (not agentic memory):**
- It is a per-use selection, not retained durable memory
- It references agentic memory and human knowledge but does not inherit their memory semantics
- It declares explicit authority flags; the agent may use it to answer questions but not to make autonomous decisions
- After use, it expires and is discarded; it does not get promoted into memory
- The content remains authoritative in its source artifacts; the bundle is just a curated view

## 7. Example: Machine Mirror Artifacts

**File:** `_indexes/agent_memory_concept_chunks.jsonl` *(illustrative; actual format and location TBD)*

**Role:** Rebuildable chunks created from the human knowledge artifact for retrieval and embedding. These are technical projections, not knowledge or memory.

```json
{
  "artifact_class": "machine_mirror",
  "artifact_type": "chunk",
  "source_ref": "docs/CONCEPTS/Agent Memory Design.md",
  "source_hash": "sha256:a1b2c3d4e5f6...",
  "chunk_id": "agent_memory_design_chunk_001",
  "chunk_sequence": 1,
  "generated_at": "2026-05-12T10:15:00Z",
  "generator": "semantic_chunk_splitter_v3",
  "rebuildable": true,
  "content": "Agent memory is the system's maintained supporting material that allows an agent to usefully support the human over time without becoming a hidden source of truth. Agent memory artifacts are human-readable and human-editable. The moment an artifact stops being meaningfully editable by a human, it transitions from agentic memory to a machine mirror.",
  "span_start": 0,
  "span_end": 342,
  "content_hash": "sha256:xyz789..."
}

{
  "artifact_class": "machine_mirror",
  "artifact_type": "chunk",
  "source_ref": "docs/CONCEPTS/Agent Memory Design.md",
  "source_hash": "sha256:a1b2c3d4e5f6...",
  "chunk_id": "agent_memory_design_chunk_002",
  "chunk_sequence": 2,
  "generated_at": "2026-05-12T10:15:00Z",
  "generator": "semantic_chunk_splitter_v3",
  "rebuildable": true,
  "content": "Memory Types: Working context (short-lived recall during active tasks), Episodic memory (records of what happened and when), Semantic memory (stabilized meaning reusable across situations).",
  "span_start": 400,
  "span_end": 620,
  "content_hash": "sha256:abc123..."
}

{
  "artifact_class": "machine_mirror",
  "artifact_type": "embedding_record",
  "source_chunk": "agent_memory_design_chunk_001",
  "source_ref": "docs/CONCEPTS/Agent Memory Design.md",
  "embedding_model": "text-embedding-3-small",
  "embedding_dim": 1536,
  "generated_at": "2026-05-12T10:20:00Z",
  "generator": "openai_embedding_service_v1",
  "rebuildable": true,
  "vector": [0.012, -0.045, 0.083, ..., -0.021],
  "projection_type": "semantic_vector"
}
```

**Why these are machine mirror artifacts:**
- Completely rebuildable from the source human knowledge artifact
- Carry no independent authority; they are projections of the source
- Should be disposable; if lost, they are rebuilt
- Not human-readable in primary form (chunks are readable but are extracts; embeddings are vectors)
- Not agentic memory; they are technical infrastructure

## 8. Artifact Class Summary Table

| Class | Primary Audience | Durability | Authority | Editability | Example |
| --- | --- | --- | --- | --- | --- |
| **Human Knowledge** | Human | Very High | Authoritative source | Human-editable | Concept note on Agent Memory Design |
| **Companion Metadata** | Agent/System | High (paired to source) | Derivative; supports source | Human-editable | Activation policy and derived links for the concept note |
| **Agentic Memory** | Mixed (human + agent) | Medium | Supporting material; defers to sources | Human-editable | Task snapshot capturing progress and blockers |
| **Bridge / Assembly** | Agent (primarily) | Per-use / Rebuildable | Delegated by sources; ephemeral | Human-editable (rare) | Context bundle selected to orient the agent |
| **Machine Mirror** | System | Low / Rebuildable | None (carries source authority) | Machine-only | Chunks and embeddings derived from the concept note |

## 9. Semantic Boundaries in Action

This scenario demonstrates three critical boundaries:

### 9.1 Companion ≠ Agentic Memory

Both the companion metadata note and the task snapshot are human-readable and human-editable. But:

- The **companion** is *about* the human knowledge artifact. It carries metadata for system behavior.
- The **task snapshot** is *work product* of the agent. It is grounded in human knowledge but stands on its own as a record of progress.

A human might correct a derived link in the companion or update the activation count. A human might add a note to the task snapshot about a decision or correction. But the semantic role differs: one is metadata, one is memory.

### 9.2 Bridge / Assembly ≠ Agentic Memory

Both the context bundle and the task snapshot may cite the same source (the concept note). But:

- The **context bundle** is ephemeral; it expires after use and is not retained as memory.
- The **task snapshot** may be retained, updated, or queried later as part of the agent's memory across time.

A context bundle may contain a task snapshot, but the bundle itself does not become memory by virtue of containing it.

### 9.3 Machine Mirror ≠ Knowledge or Memory

The chunks and embeddings are semantic projections of the concept note. But:

- They carry no independent authority. If the concept note changes, chunks must be regenerated.
- They are not human-editable; they are machine-generated and machine-consumed.
- They are not retrievable for human reading directly (though a human could open them as JSONL for inspection).
- They should be discardable and rebuildable.

## 10. How These Artifacts Support the Agent over Time

This scenario shows the full lifecycle:

1. **Human writes and settles the concept note.** This is the durable, authoritative source.

2. **Companion metadata tracks processing and usage.** The system knows when the note was last used and suggests related artifacts.

3. **Agent produces a task snapshot during work.** This records what the agent was trying to do, what it learned, and what remains. The human can read it and provide corrections or context.

4. **Context bundle orients the agent.** When the agent resumes work, a fresh bundle is assembled from the sources. The bundle is read-only and does not persist.

5. **Machine mirrors support retrieval.** Chunks and embeddings allow the concept note to be found in search and reasoning tasks. If lost, they are rebuilt.

Over time:

- The **human knowledge artifact** remains the ground truth and can be revised by the human.
- The **companion** tracks operational state without cluttering the primary note.
- The **agentic memory** builds up a history of work and insights the agent (and human) can draw on.
- **Context bundles** help the agent get oriented without burdening the memory system with ephemeral selections.
- **Machine mirrors** fade in and out as needed, supporting retrieval and reasoning without claiming authority.

## 11. Non-Goals and Out of Scope

This document provides **illustrative examples**, not:

- A storage schema or database design
- A metadata format specification (frontmatter keys, serialization, etc.)
- A runtime implementation or validator
- A governance or authority model
- A final companion-note location convention
- A deployment or rollout plan

These examples are suitable for documentation, test fixtures, and design reference. Implementation teams can use them to ground future schema, validator, and runtime work.

## 12. Notes for Future Implementation

When this example becomes a test fixture or schema reference:

1. **Metadata fields** in the examples above are logical names; final on-disk field names are a downstream decision.

2. **File locations** (e.g., `_system/companions/`, `_memory/agent_tasks/`, `_indexes/`) are illustrative patterns, not mandates.

3. **YAML frontmatter** format is for human readability here; actual serialization could be YAML, JSON, TOML, or a mixed embedded format per placement mode.

4. **Linkage** between artifacts (via `source_refs`, `target_ref`, `source_chunk`) would need a stable identity scheme (UUID, content hash, file path + fragment, or other). The examples assume stable references work correctly.

5. **Validity semantics** (e.g., `stale_after`, `validity`) are named here; the precise rules for what "stale" means in a runtime are defined by `docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md` and will be enforced by implementation lanes.

6. **Activation and authority** (e.g., `activation_policy`, `may_answer`, `may_write`) are declared in the examples; runtime enforcement of these flags is out of scope for this document and belongs to later activation semantics work (see issue #943).
