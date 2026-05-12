State: Concept contract companion (agent memory and knowledge; human-authored truth remains primary).

# Agent Memory and Knowledge Contract

## Purpose

This document defines the relationship between human-authored knowledge, agent memory, runtime state, and machine mirrors.

It exists so the repo can talk about memory without turning hidden runtime state into a secret source of truth.

Related docs:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/HUMAN-FLOWS.md`

## Contract boundary

This contract defines the target-state semantics of memory and knowledge.

It does not define:
- a specific vector store,
- a specific agent implementation,
- a hidden prompt cache,
- or a claim that durable memory already exists in the runtime exactly as described here.

## Core rule

Agent memory is the inspectable remembered support material that helps an agent or system surface, explain, and act on prior context.

It is not:
- human memory,
- human-authored knowledge,
- runtime state,
- machine mirrors,
- or context bundles.

The human-authored knowledge surface remains primary. Agent memory is supporting material, not the authority layer.

## What agent memory is

Agent memory is a governed remembered layer used to help future reasoning, recall, explanation, and continuity.

It may include:
- observations,
- prior task state,
- inferred links,
- preferences,
- procedural notes,
- commitments,
- and explanation aids.

The important property is not that it exists, but that it stays inspectable and correctable.

## What agent memory is not

Agent memory is not:
- a hidden source of truth,
- a replacement for human-authored artifacts,
- a substitute for explicit provenance,
- a substitute for write receipts,
- or a license to infer authority from repetition.

## Distinctions that must remain explicit

### Agent memory vs human memory

Human memory is the human's lived recall.

Agent memory is system-managed support material that may help the human remember, orient, or act.

### Agent memory vs human-authored knowledge

Human-authored knowledge is the primary meaning-bearing surface.

Agent memory may point at it, summarize it, or propose structure around it, but it cannot override it.

### Agent memory vs runtime state

Runtime state is operational execution state: queues, transient selections, in-flight decisions, tool calls, counters, and other live control data.

Agent memory is what can be recalled later as remembered support material.

### Agent memory vs machine mirrors

Machine mirrors are projections that preserve continuity, portability, or recovery.

Agent memory is about remembered support and explanation, not merely replication.

### Agent memory vs context bundles

A context bundle is a selected bridge object for a specific use.

Agent memory is what may be recalled across time and use cases.

The bundle can feed memory promotion, but the bundle itself is not memory.

## Memory classes

### Working context

Working context is short-lived recall used during an active task or interaction.

It is closest to the current conversation or execution window and should decay quickly.

### Episodic memory

Episodic memory records that something happened, when it happened, and what situation surrounded it.

It helps with continuity, review, and explanation.

### Semantic knowledge

Semantic knowledge is stabilized meaning that the system can reuse across situations.

It should converge on human-authored or human-reviewed truth, not unreviewed inference.

### Prospective memory

Prospective memory tracks future-oriented remembered obligations or intentions.

It must distinguish:
- commitment,
- reminder,
- waiting state,
- and candidate action.

Those are not interchangeable.

### Procedural memory

Procedural memory captures repeated ways of doing something.

If a procedure is used to drive repeated actions, it must be versioned or traceable.

### Preference memory

Preference memory captures stable or semi-stable user preferences, defaults, and styles.

It should remain editable and reviewable, especially when inferred rather than explicitly declared.

### Policy / authority memory

Policy / authority memory records boundaries, permissions, and safety rules that govern what the system may do.

It is not a convenience cache. It is part of the control surface.

## Lifecycle

The memory lifecycle is:

1. Observe
2. Candidate
3. Review
4. Promote
5. Reject
6. Revise
7. Decay / archive
8. Recall
9. Explain

The lifecycle is intentionally explicit so the system does not skip from observation to truth.

### Observe

The system notices an event, pattern, or candidate fact.

### Candidate

The observed item becomes a candidate memory, not yet truth.

### Review

The candidate is checked by human review, policy, source grounding, or stronger evidence.

### Promote

The candidate becomes a more durable memory class or enters a more stable knowledge surface.

### Reject

The candidate is not accepted into memory or knowledge.

### Revise

The memory is corrected, narrowed, or reclassified.

### Decay / archive

Stale or low-value memory should fall out of active use or move to archive while remaining inspectable if needed.

### Recall

The system brings the memory back into use for answering, orienting, resurfacing, or proposing.

### Explain

The system states why the recalled memory matters and what its provenance and authority are.

## Authority rules

- Agent memory must not become a hidden source of truth.
- Agent memory cannot override human-authored knowledge or authority contracts.
- Inferred memory must be marked as inferred unless human-reviewed.
- Imported memory must retain source provenance.
- Recall must remain bounded by trust, scope, and write policy.
- Memory may support suggestion or explanation, but not silent authority escalation.

## Review and promotion rules

Promotion should be explicit and reviewable.

At minimum:
- observed material starts as candidate,
- candidate material needs review or policy justification before promotion,
- inferred material keeps its inferred label until reviewed,
- and promotion must preserve source links and explanatory context.

Promotion into semantic knowledge should be stricter than promotion into episodic or working context.

## Contradiction and staleness handling

Memory can become wrong, stale, incomplete, or contradicted.

When that happens, the system should:
- surface the contradiction,
- preserve provenance,
- mark the memory as stale, revised, or rejected,
- and avoid silently overwriting human-authored knowledge.

The default posture is correction through visibility, not hidden replacement.

## Deletion and correction expectations

If memory is wrong, the system should be able to correct it without erasing the evidence trail.

Deletion should be narrow and explainable:
- remove the recalled support material if needed,
- keep receipts or audit traces where appropriate,
- and do not erase source provenance unless another contract explicitly says so.

## Relation to receipts

Receipts explain what happened, what was recalled, and why a memory was promoted, revised, or rejected.

Recall that influences answers, orientation, or write proposals must be explainable through receipts or equivalent review artifacts.

## Relation to vault artifacts

Vault artifacts remain the human-authored primary surface.

Memory may point to them, summarize them, or help retrieve them, but should not replace them as the canonical source of meaning.

## Relation to agents and orchestration

Agents may use memory to improve continuity and explainability.

Orchestration state still remains runtime state, not memory.

The agent may recall memory as part of a task, but the memory itself should remain reviewable and bounded by authority rules.

## Relation to companion UI and human review

Companion UI may surface memory candidates, promotions, contradictions, and correction paths.

The UI should expose:
- what was recalled,
- where it came from,
- whether it is inferred,
- and what review state it currently holds.

The UI is a support surface, not the authority layer.

## Illustrative target-state memory record

This is an illustrative target-state shape, not a claim about shipped schema.

```yaml
agent_memory:
  id: mem_20260512_001
  class: episodic
  status: candidate
  source:
    artifact_id: art_123
    provenance: vault note
    imported: false
  content:
    summary: user was reworking retrieval wording
    inferred: true
  review:
    state: pending
    reviewed_by: null
  authority:
    may_recall: true
    may_answer: true
    may_propose: true
    may_write: false
  lifecycle:
    observed_at: 2026-05-12T09:00:00Z
    promoted_at: null
    archived_at: null
  receipts:
    candidate_receipt: receipt_010
    promotion_receipt: null
    recall_receipt: null
```

## Normative rules

- Agent memory must not become a hidden source of truth.
- Agent memory cannot override human-authored knowledge or authority contracts.
- Inferred memory must be marked as inferred unless human-reviewed.
- Imported memory must retain source provenance.
- Prospective memory must distinguish commitment, reminder, waiting state, and candidate action.
- Procedural memory must be versioned or traceable when used to drive repeated actions.
- Recall must be explainable when it influences answers, orientation, or write proposals.
- Memory promotion must not silently erase the original source or its provenance.

## Relationship to shipped reality

Current runtime may already expose pieces of memory-adjacent behavior through retrieval, receipts, companion notes, and the read-only Chat cognition scaffold. This document does not claim a fully shipped agent-memory system. It defines the target-state relationship between memory, knowledge, runtime state, and machine mirrors.

