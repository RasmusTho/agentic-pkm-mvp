# Cognitive Trajectories

## Purpose
Define trajectories as the canonical temporal unit of cognition in the companion UI.

## Metaphor boundary
- `Trajectory` is architectural semantics, not decorative language.
- It means a continuity-bearing line of thought that can be resumed, cooled, resurfaced, fragmented, or converged over time.

## Core rule
- Sessions are interaction slices.
- Trajectories are the longer-lived semantic unit.
- A posture shift may happen within one trajectory.
- A trajectory may span multiple sessions, overlays, and interruptions.

## Canonical trajectory states
- **Active trajectory:** currently focal and being worked directly.
- **Warm trajectory:** not focal now, but re-entry cost remains low.
- **Dormant trajectory:** inactive but still semantically unresolved and resurfacing-eligible.
- **Cold trajectory:** inactive long enough that reconstruction cost is high.
- **Interrupted trajectory:** paused by external break before semantic closure.
- **Decaying trajectory:** continuity signals are weakening and re-entry cost is rising.
- **Fragmented trajectory:** continuity exists only in partial, weakly linked pieces.
- **Converging trajectory:** multiple partial lines of thought are moving toward one synthesis.

## Transition rules
- Active trajectories can cool into warm or dormant states.
- Dormant trajectories can resurface into warm or active states.
- Interrupted trajectories should preserve enough continuity payload to avoid fragmentation.
- Converging trajectories should preserve provenance from each contributing line.

## Architectural consequences
- Document remains the anchor for durable trajectory meaning.
- Resurfacing should target trajectories, not just isolated snippets.
- Continuity support should preserve unresolved synthesis, not only last-visible text.

## Related docs
- `TEMPORAL_COGNITION.md`
- `CONTINUITY_AND_DECAY.md`
- `ATTENTION_MODEL.md`
- `EPISTEMIC_EVOLUTION.md`
