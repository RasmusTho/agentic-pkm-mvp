State: Concept contract companion (agent memory and knowledge; human-authored truth remains primary).
Changed: 2026-06-13 — Durable Memory and Recall shipped review-decision receipts, queue reconciliation, governed semantic-memory materialization, guarded recall receipts, and Companion provenance surfacing. `may_write=false` remains the default for recalled memory unless a future governed owner contract changes it.
Changed: 2026-06-12 — `docs/AGENT-FLOWS.md` explicitly declines the `may_write` widening slot reserved below for Yggdrasil-mediated agent memory; `may_write=false` remains universal unless a future governed owner contract changes it. Human-declared direct filesystem write zones (see `docs/AGENT-FLOWS.md` §7) are a separate human-delegated access mode, not a `may_write` widening and not agent memory.

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
- or a claim that every target-state lifecycle transition already exists in runtime.

Current shipped runtime covers the durable-memory subset named in
`docs/DURABLE_MEMORY_AND_RECALL/`: vault-scoped review-decision receipts, review-queue
reconciliation, governed materialization of promoted semantic memory, guarded recall receipts, and
Companion surfacing. Broader lifecycle management such as archive/cold-storage policy and complete
forget/tombstone flows remains future governed work unless promoted by a later issue and receipt.

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

Orientation surfaces may emit a bounded, reference-only `MemoryCandidate`
intent as a handoff hint only under
`docs/adr/ADR-0009-orientation-memory-candidate-intent.md`. That intent is not
candidate creation and must not store candidate content. Candidate creation,
review, promotion, rejection, and revision remain explicit memory lifecycle
transitions outside the read-side orientation projection.

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

Archive/cold-storage posture is a lifecycle state, not the same thing as a salience score or
storage-temperature metaphor. Archived memory should remain durable, provenance-preserving, and
explicitly retrievable, while default recall and resurfacing exclude it unless the caller or policy
opts into archive recall. A future implementation must preserve the existing boundary that zone and
salience influence rank, not authority, scope, or trust.

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

Complete forgetting is stronger than archiving. A future forget flow should be a governed
destructive lifecycle transition: remove the semantic memory from normal recall and derived
indexes, preserve only a minimal non-semantic tombstone/receipt needed for accountability, and avoid
repeating the forgotten content in receipts, summaries, or recall projections.

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

Companion Workspace Orientation may surface only server-declared, reference-only
MemoryCandidate intents. The UI must not classify candidate-worthiness locally,
create candidates from orientation, or treat an orientation intent as recalled
memory.

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

## Bounded memory/context admissibility default

> **Superseded for the admit-by predicate (#2023).** The **inbound admit-by predicate** — *what
> context/memory is eligible to enter a proposal, answer, or action* — is now owned by
> `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`. The conservative default recorded here (the
> #1598 default) remains valid as the *influence* posture for already-admitted material and is
> consistent with the tiers in that contract, but it is no longer the authoritative admissibility
> statement. For admission decisions, read the admissibility contract first.

This section records the conservative admissibility default in force until a separate governed
contract explicitly changes it. It governs how memory and context may be used across three
influence tiers.

**Read-side awareness, orientation, and resurfacing (allowed).**
Memory and context may support read-side awareness, orientation, and resurfacing when provenance
is visible (source, review state, and authority are surfaced rather than hidden) and the authority
posture is non-write (`may_write=false`). Recall at this tier must not silently promote retrieved
context into memory or knowledge.

**Proposal influence (allowed only as cited support).**
Memory and context may support proposal evidence when the recall is cited explicitly (not used as
a hidden background signal), the review/provenance posture is surfaced to the human or reviewer,
and the proposal is produced through the governed write-proposal path. Uncited background
influence from memory or context is disallowed.

**Mutation authority (disallowed from memory/context alone).**
Memory or context alone must not authorize mutations, note writes, or state transitions.
`may_write=false` is the required posture for any memory record or context bundle unless a
separate governed contract explicitly changes it with receipts and human review. Promotion from
candidate to active memory must not occur silently from context influence; explicit lifecycle
transitions with receipts are required.

`docs/AGENT-FLOWS.md` has explicitly declined this widening slot for Yggdrasil-mediated agent
memory; the slot remains reserved for a future governed owner contract. Note the distinction in
`docs/AGENT-FLOWS.md` §4/§7: Markdown written by human-delegated direct filesystem agents in
declared workspace roots is an observed external artifact, not agent memory and not a mediated
write — it carries no memory authority flags and enters knowledge only through the normal
review/promotion path.

This default is the design-intent posture documented here. Runtime enforcement may be partial at
any given point. Where the runtime does not yet enforce a tier, the constraint remains normative
for new work and should drive follow-up implementation issues when a concrete enforcement gap is
identified.

## Relationship to shipped reality

Current runtime now ships the Durable Memory and Recall subset:

- review decisions persist as vault-scoped receipts/traces and survive restart;
- the review queue reconciles against terminal persisted decisions while pending candidates remain
  runtime-only;
- promote-to-semantic decisions materialize an agent-promoted vault artifact only through
  `proposal -> WriteGuard -> receipt -> artifact`, and become terminal only after materialization
  succeeds;
- blocked or failed materialization records a failed-attempt receipt and keeps the promotion
  actionable;
- guarded recall invokes the memory authority guard, emits a recall receipt, and does not persist
  activation state as artifact authority;
- Companion surfaces materialized-memory provenance, recall provenance, and authority posture.

This shipped subset does not introduce a vector-store choice, context-bundle persistence,
archive/cold-storage lifecycle management, complete forgetting, or memory-authorized mutation.
Those remain governed follow-up areas under this contract and the runtime-vs-durable boundary.
