State: Concept contract companion (context bundle as an inspectable bridge between retrieval, orientation, resurfacing, companion UI, and governed write proposals).

# Context Bundle Contract

## Purpose

This document defines the `context bundle` as the explicit, inspectable, auditable bridge between retrieval, orientation, resurfacing, companion UI, write proposals, provenance, and write guards.

It exists so the system can show the human what context was selected, why it was selected, what was excluded, and what authority the selected bundle does or does not carry. The bundle is a bridge object, not a new source of truth.

Related docs:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/README.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`

## Contract boundary

This contract defines a target-state bridge object for context selection and explanation.

It does not define:
- the current retrieval ranking implementation,
- a search result schema,
- a chat history format,
- agent internal state,
- memory storage,
- or prompt stuffing.

## Core rule

A context bundle is the explicitly selected set of artifacts, snippets, reasons, exclusions, and authority flags that a human can review.

It is not the same thing as:
- a search result, which is a candidate list produced by retrieval,
- chat context, which is the transient conversational window in a surface,
- agent state, which is runtime execution state,
- memory, which is durable or semi-durable remembered material,
- or prompt stuffing, which is an opaque concatenation of context into a model prompt.

The context bundle sits between those things and the human review surface.

## Why it exists

The system needs a portable way to explain:
- why these artifacts were brought together,
- why other artifacts were not,
- what trust state each included item carried,
- and whether the selected set may be used for answering, orienting, resurfacing, or proposing a write.

Without this bridge object, retrieval can return hits but not a reviewable explanation of selection. Orientation can surface threads but not show what was intentionally omitted. Write proposals can become detached from the evidence bundle that justified them.

## When it is created

A context bundle is created whenever the system needs a reviewable selection for one of these triggers:
- retrieval,
- orientation,
- resurfacing,
- or action.

The trigger determines the bundle's intended use, not its authority. A bundle created for answering may not be authoritative for writing.

## How it differs from nearby concepts

### Search result

A search result answers: what matched.

A context bundle answers: what was selected for this human-facing use, why it was selected, what was excluded, and what authority it carries.

### Chat context

Chat context is the transient conversation window used by an interaction surface.

A context bundle is a governed, inspectable selection that may inform that window, but it is not the same thing as conversational turn state.

### Agent state

Agent state is execution state inside an agent or runtime.

A context bundle is a human-reviewable artifact about selected context.

### Memory

Memory is durable or semi-durable remembered material.

A context bundle is not memory. It may point at memory, but it does not silently promote selected context into memory or knowledge.

### Prompt stuffing

Prompt stuffing is an opaque technical assembly of context for model consumption.

A context bundle is the opposite: visible selection logic, visible exclusions, and visible authority flags.

## Required fields

The target-state bundle should expose at least:
- identity,
- creation time,
- trigger,
- intended use,
- scope,
- included items,
- excluded items,
- authority flags,
- expiry,
- and receipts.

## Optional fields

Depending on the use case, a bundle may also expose:
- a human-readable summary,
- a selection rationale,
- a dominant source role,
- a trust posture summary,
- a freshness note,
- a downstream write proposal link,
- or a companion UI reference.

## Authority flags

Authority flags state what the bundle may support.

At minimum, they should distinguish:
- may answer,
- may orient,
- may resurface,
- may propose,
- may write.

These are separate permissions. A bundle may support an answer without supporting writeback.

## Lifecycle

The bundle lifecycle is intentionally simple:

1. Select context.
2. Record what was included and excluded.
3. Attach provenance and receipts.
4. Expose authority flags.
5. Present it for human review or downstream use.
6. Mark it stale or expired when its supporting assumptions no longer hold.

The lifecycle does not imply that a bundle becomes durable knowledge. It is a bridge artifact, not a promotion primitive.

## Relation to provenance and receipts

Provenance explains where the included and excluded items came from and why they are relevant.

Receipts explain why the bundle exists and how it was used.

If exclusion changes interpretation, the exclusion itself is part of provenance and must be visible enough for review. Omitted material can matter as much as included material.

## Relation to retrieval, orientation, and resurfacing

Retrieval selects candidates.

Orientation helps the human recover situation and open loops.

Resurfacing brings something back into view because it has become relevant again.

A context bundle is the bridge object that makes those selections reviewable and auditable. It is the evidence-bearing envelope around those capabilities, not a replacement for them.

## Relation to companion UI

Companion UI surfaces may display the bundle as an inspectable explanation of selected context.

The UI may render included items, exclusions, trust state, and authority flags, but the UI is not the authority. The bundle remains the readable bridge object underneath the surface.

## Relation to writeback and write guards

Write proposals should carry the bundle or a stable reference to it so the human can inspect the evidence behind the proposal.

Write guards must still run independently. A context bundle may support a proposal, but it must not bypass trust semantics, domain boundaries, or explicit APPLY rules.

## Stale and expiry handling

A bundle must carry a stale/expiry posture so downstream surfaces do not treat an old selection as current by default.

The bundle should expose:
- when it becomes stale,
- why it becomes stale,
- and what should happen when it is reused after expiry.

Expired bundles may still be inspectable for audit, but they should not silently inherit current authority.

## Exclusion tracking

Exclusions are not an implementation footnote.

If an item was intentionally excluded because it was out of scope, too low-trust, too stale, or too expensive to include, that exclusion can change the interpretation of the bundle and should be visible.

When exclusion affects interpretation, the exclusion record is part of provenance.

## Illustrative target-state YAML

This is an illustrative target-state shape, not a claim about shipped schema unless and until runtime docs say otherwise.

```yaml
context_bundle:
  id: cb_20260512_001
  created_at: 2026-05-12T09:00:00Z
  trigger:
    type: retrieval
    source: docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md
  intended_use:
    - answer
    - orient
    - resurface
    - propose_edit
  scope:
    sphere: work
    project: agentic-pkm-mvp
    vaults:
      - vault-main
  included:
    - artifact_id: art_123
      path: vault/notes/retrieval.md
      chunk_ids:
        - chunk_07
      reason: direct evidence for the user question
      source_role: evidence
      trust_state: reviewed
      review_state: confirmed
      retrieval_score: 0.92
      provenance:
        origin: vault note
        transformed_by: retrieval
  excluded:
    - artifact_id: art_999
      reason: out of scope for active sphere
  authority:
    may_answer: true
    may_orient: true
    may_resurface: true
    may_propose: true
    may_write: false
  expiry:
    stale_after: 2026-05-12T12:00:00Z
    reason: selection tied to a transient retrieval snapshot
  receipts:
    retrieval_receipt: receipt_001
    orientation_receipt: receipt_002
    write_proposal_receipt: null
```

## Normative rules

- A context bundle may support an answer without supporting writeback.
- A context bundle may include low-trust material only if its trust state remains visible.
- A context bundle must not silently promote retrieved context into memory or knowledge.
- A context bundle must not bypass write guards.
- Context selection must be explainable enough for human review.
- Exclusions are part of provenance when exclusion affects interpretation.
- A bundle created for resurfacing does not automatically authorize writing or promotion.
- A bundle may be inspectable after expiry, but expired authority does not persist by default.

## Bounded context admissibility posture

Context Bundles are bridge artifacts, not authority escalation primitives.

**`may_write=false` is the default and required posture for all bundles** unless a later
separately governed contract, with receipts and human review, explicitly changes that posture for
a specific bundle class.

Bundle-based context may support:

- proposal evidence — as cited support only, with provenance and review posture surfaced;
- read-side answering, orientation, and resurfacing — when provenance is visible and
  `may_write=false`.

Bundle-based context must not:

- authorize note writes, state transitions, or promotion moves on its own;
- promote selected context into memory or knowledge silently;
- set `may_write=true` without a separate governed contract that explicitly grants it;
- bypass WriteGuard, trust semantics, or domain boundaries.

This posture is consistent with the admissibility default in
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`. It applies to all existing shipped bundle
surfaces (retrieval, orientation, resurfacing, write-proposal linkage) until a follow-up governed
contract explicitly widens it.

## Examples

### Retrieval bundle

The human asks for a source. The system returns a bundle that shows the matched artifacts, why they were chosen, and what was excluded because it was too weak, too broad, or out of scope.

### Orientation bundle

The human returns after an interruption. The system returns a bundle showing where they left off, which open loops were active, and what changed while they were away.

### Resurfacing bundle

Something becomes relevant again without a query. The system returns a bundle that explains why this material deserves attention now and what evidence supports that judgment.

### Write proposal bundle

The system proposes an edit. The bundle shows the source artifacts, the trust state, the exclusions, and the explicit proposal receipt so the human can review the basis before APPLY.

## Relationship to shipped reality

Current runtime surfaces may already expose pieces of this behavior through retrieval, orientation, resurfacing, receipts, and companion-note related UI. This document does not claim that the full context-bundle contract is already shipped. It defines the target-state bridge object that those surfaces should converge on.

