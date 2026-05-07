# Temporal Cognition

## Purpose
Define how cognition is preserved across time in a document-first, interruption-prone workflow.

## Temporal cognition model
- Cognition unfolds as a trajectory, not isolated sessions.
- Each trajectory moves through active, latent, and resurfaced phases.
- Time changes meaning: relevance, urgency, and interpretation evolve.

## Core concepts
- **Active thread:** currently attended trajectory.
- **Dormant thread:** latent trajectory that is unresolved but not currently focal.
- **Re-entry window:** period where minimal cues can recover full context.
- **Cognitive decay:** loss of context fidelity over time when cues are weak.
- **Continuity residue:** preserved traces (anchors, provenance, tension markers) that support recovery.

## Temporal invariants
- Document remains the cognitive anchor across all temporal phases.
- Overlays preserve continuity and must not fork hidden semantic state.
- Resurfacing must carry provenance and continuity residue.
- AI may assist recovery but must not replace human continuity judgment.

## Re-entry ergonomics
- Re-entry should begin with prior intent, current tension, and last meaningful transition.
- Recovery cues should be compact, contextual, and dismissible.
- Recovery should avoid full synthetic summaries unless explicitly requested.

## Trajectory continuity rules
- Preserve unresolved questions across interruptions.
- Preserve decision boundary state (proposed vs accepted vs deferred).
- Preserve why the thread mattered, not only what text existed.

## Related docs
- `ATTENTION_MODEL.md`
- `POSTURE_TRANSITIONS.md`
- `SALIENCE_AND_TENSION.md`
- `TEMPORAL_PROVENANCE.md`
- `COGNITIVE_FAILURE_MODES.md`
