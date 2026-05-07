# Posture Transitions

## Purpose
Formalize how cognitive postures change while preserving continuity.

## Canonical postures
- **Orientation:** understand where attention should begin.
- **Exploration:** branch possibilities without commitment pressure.
- **Synthesis:** integrate multiple objects into coherent outputs.
- **Review:** evaluate decisions, proposals, and unresolved tension.
- **Recovery:** re-enter after interruption and restore trajectory.

## Transition semantics
- Transitions are explicit shifts in cognitive emphasis, not page-level locks.
- Any transition must preserve anchor document, provenance context, and unresolved tension.
- Recovery can enter from any posture and should restore prior trajectory before new branching.

## Minimal transition contract
- **From posture:** current emphasis context.
- **To posture:** new emphasis context.
- **Reason:** explicit trigger (intent, interruption, resurfacing, review need).
- **Carry-forward set:** objects that must survive the shift.

## Anti-patterns
- Hard mode walls that force context loss.
- Hidden transition side effects.
- Transitioning without preserving unresolved questions.

## Related docs
- `COGNITIVE_MODES.md`
- `ATTENTION_MODEL.md`
- `TEMPORAL_COGNITION.md`
- `COGNITIVE_FAILURE_MODES.md`
