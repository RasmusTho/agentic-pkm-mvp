# Cognitive Objects

## Purpose
Define the meaning-bearing objects used across document, overlays, and temporal recovery.

## Canonical object types
- **Anchor document:** primary cognitive surface for durable thought.
- **Thread:** coherent trajectory of thought over time.
- **Proposal:** staged suggestion pending acceptance/rejection.
- **Provenance card:** compact lineage object describing source and rationale.
- **Tension marker:** explicit unresolved pressure in a thread.
- **Resurfacing cue:** contextual signal to re-open a dormant thread.

## Object-level invariants
- Every object must be inspectable in context.
- Objects shown in overlays must map to document-anchored semantics.
- Durable objects must remain vault-compatible.
- Object identity must not depend on hidden app state.

## Persistence posture
- Transient object views are allowed.
- Meaning-bearing object state must be explicitly persisted when durable.
- If transient cues disappear, durable trajectory meaning must still be recoverable.

## Cross-object relations
- Proposals belong to threads.
- Threads are anchored to documents.
- Tension markers can attach to proposals, threads, or anchor documents.
- Resurfacing cues should reference provenance and prior tension.

## Related docs
- `TEMPORAL_PROVENANCE.md`
- `TEMPORAL_COGNITION.md`
- `SALIENCE_AND_TENSION.md`
- `OVERLAY_GRAMMAR.md`
