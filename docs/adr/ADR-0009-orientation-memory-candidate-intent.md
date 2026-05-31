State: Accepted - implemented by the read-only runtime seam in issue #1457.

# ADR-0009: Orientation MemoryCandidate Intent Threshold and Trace Semantics

**Date:** 2026-05-31
**Status:** Accepted - runtime seam implemented by #1457

---

## Context

ADR-0007 introduces a note-independent Workspace Orientation Snapshot for `GET /api/companion/orientation`.
That surface may expose bounded `mutation_intents`, but it remains a read-side runtime/UI projection:
it does not mutate durable artifacts, session state, memory state, governance receipts, or WriteGuard
state. ADR-0008 then admits the leave-point cursor only as bounded operational trace, preserving the
same discardability rule.

Phase 3 needs a safe handoff from orientation to the existing MemoryCandidate review queue. The risk is
that an orientation read could become an implicit memory dump: raw chat or runtime material is observed,
classified as useful by a model or UI, and quietly accumulated as candidate memory without explicit
review. That would violate the agent-memory contract: observation must not skip directly to truth, and
candidate material must pass through review before promotion.

This ADR decides the threshold for a `MemoryCandidate` `mutation_intent` from orientation and whether
that intent needs trace or receipt semantics. Runtime implementation is shipped by #1457 under this
boundary.

## Decision

`GET /api/companion/orientation` may emit a bounded `MemoryCandidate` `mutation_intent` only as a
reference-only handoff hint to the existing MemoryCandidate review queue. The orientation surface must
never create a `MemoryCandidate`, accept or promote memory, store memory content, write candidate
content, persist semantic workspace state, or perform autonomous mutation.

Intent emission requires an operational trace event for observability. Intent emission does not produce
a governance receipt, because no durable semantic transition has occurred. Receipt semantics belong to
later candidate creation, acceptance, promotion, rejection, revision, or other durable/governed memory
transitions.

## Accepted Threshold Model

A `MemoryCandidate` `mutation_intent` is admissible only when all required gates pass and the signal
threshold is met.

Required gates:

- The source item is already present in an admissible, provenance-bearing runtime or orientation source.
- The source item carries `authority_role` and `source_ref`.
- The orientation payload references the source item only by bounded source reference; it does not carry raw candidate content.
- The candidate reason is explicit and human-legible.
- The intent target is the existing MemoryCandidate review queue or its implementation successor.
- The orientation read creates no raw memory candidate.
- The orientation read writes no candidate content.
- The orientation read persists no semantic state.

Signal threshold:

- At least two independent signals must be present.
- Salience may contribute one signal, but salience alone is never sufficient.
- LLM judgment may explain or normalize the declared reason only when grounded in the explicit signals; it is not an independent gate by itself.

Admissible independent signals include:

- repeated resurfacing across time;
- explicit human interaction or activation;
- high salience score from the salience layer;
- unresolved open loop with provenance;
- repeated reference in reviewed artifacts;
- explicit user-authored marker or review cue;
- recent receipt, audit, or governance evidence indicating durable relevance.

## Trace vs Receipt Decision

When orientation emits a `MemoryCandidate` `mutation_intent`, it must emit an operational trace event recording that the intent was emitted.

The trace must include:

- `trace_id`;
- `source_ref`;
- `threshold_signals`;
- `intent_id`;
- `emitted_at`;
- target queue reference.

The trace must not include raw candidate content, note body, chat transcript, agent scratchpad, summary of candidate content, embeddings, or accepted memory content.

No governance receipt is created at intent emission. A receipt is required only if a later durable semantic or governed transition occurs, such as creating a candidate record, accepting a candidate, promoting memory, rejecting memory with accountable review semantics, or revising candidate material.

## Invariants

- Orientation is read awareness plus intent only.
- `mutation_intents` are proposals or handoff hints, not execution.
- Candidate content is absent from the orientation payload.
- The UI renders server-declared intents only and must not classify candidate-worthiness locally.
- The target queue remains the review boundary; unreviewed candidates are not recallable as authoritative memory.
- Discarding the orientation projection loses no memory meaning.
- WriteGuard is not involved in read-side intent emission; it remains relevant to later governed write paths.
- #1455 leave-point cursor semantics are unchanged.

## Forbidden Paths

The orientation surface must not:

- create a `MemoryCandidate`;
- accept, promote, reject, revise, or store memory;
- store orientation summaries;
- store raw candidate content;
- store raw chat content or agent scratchpad content;
- use salience score alone as the gate;
- use LLM/freeform judgment alone as the gate;
- use UI click alone without `source_ref` as the gate;
- use cursor/leave-point presence alone as the gate;
- use resurfacing presence alone without provenance as the gate;
- ask the UI to own candidate classification;
- involve WriteGuard in read-side intent emission;
- mix this decision with push or ambient resurfacing work (#1458);
- mix this decision with multi-agent read work (#1459).

## Rejected Alternatives

### 1. No MemoryCandidate intents from orientation

This is the safest boundary: orientation would never suggest memory review. Rejected for Phase 3 because it weakens the intended handoff from re-entry/orientation to the existing review queue even when the source is already provenance-bearing and the threshold is high.

### 2. Emit intents on salience score alone

Rejected. Salience is an attentional overlay, not memory authority. Using it alone would turn ranking or attention pressure into hidden cognition accumulation.

### 3. Emit intents and create MemoryCandidate immediately

Rejected. Creating a candidate is a write-side memory transition, not a read-side orientation behavior. It would violate the orientation boundary and could make repeated reads accumulate candidate memory.

### 4. Emit a governance receipt for intent emission

Rejected. The intent is a handoff hint, not a durable semantic transition. A trace is required for observability; receipt semantics start when a later governed transition actually occurs.

### 5. UI decides when to emit MemoryCandidate intent

Rejected. The UI must render server-declared state and may initiate explicit user actions, but it must not classify candidate-worthiness or own authority over memory-review routing.

### 6. Agent or LLM freeform judgment threshold

Rejected unless mediated by explicit governed signals. Model judgment may help format a human-legible reason, but it cannot be the threshold or authority basis.

## Contract Impact

`companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` must specify that:

- `mutation_intents` are handoff hints only;
- `MemoryCandidate` intents are bounded and reference-only;
- intent emission does not create a candidate;
- orientation payloads carry no candidate content;
- the UI renders server-declared intents only and must not classify locally.

Concept contracts should clarify, where useful, that:

- orientation intent emission is a trace-not-receipt event;
- salience is one possible signal, not a gate;
- actual candidate creation and promotion remain review/governance paths outside orientation.

## Verification Requirements

- ADR is present at `docs/adr/ADR-0009-orientation-memory-candidate-intent.md`.
- ADR is indexed in `docs/adr/INDEX.md`.
- Workspace Orientation Contract includes the `MemoryCandidate` intent boundary.
- Boundary docs remain consistent with read-only orientation, trace-not-receipt semantics, and salience-as-signal-only semantics.
- `python3 scripts/docs_guard.py` passes.
- `git diff --check` passes.

## Follow-up Issue Impact

#1457 implements read-only pending MemoryCandidate awareness and bounded intent emission only under this ADR. It does not implement candidate creation, candidate acceptance, promotion, memory storage, push/ambient resurfacing (#1458), multi-agent reads (#1459), or changes to #1455 leave-point cursor semantics.

## References

- Issue #1456: orientation MemoryCandidate intent threshold + trace requirement
- Issue #1457: runtime implementation
- `docs/adr/ADR-0007-workspace-state-contract-scope-split.md`
- `docs/adr/ADR-0008-leave-point-cursor.md`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- `docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`
