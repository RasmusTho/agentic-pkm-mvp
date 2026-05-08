# Cognitive Failure Modes

## Purpose
Name recurring cognitive breakdowns so architecture can prevent or recover from them without changing core interaction principles.

## Failure modes
- **Interruption amnesia:** user returns and cannot recover prior intent or decision boundary.
- **Posture thrash:** rapid posture switching without continuity preservation.
- **Trajectory fragmentation:** one line of thought splits into disconnected pieces without recoverable linkage.
- **Salience collapse:** relevant dormant threads never resurface until too late.
- **Resurfacing noise:** too many weakly relevant resurfacings drown true signals.
- **Provenance opacity:** user sees suggestions without enough lineage to trust or reject quickly.
- **Tension burial:** unresolved cognitive tension disappears from active context.
- **Decay without payload:** reconstruction cost rises because insufficient continuity cues were preserved.
- **Persistence ambiguity:** user cannot tell what is transient versus durable.
- **Chat gravity:** thread UI becomes primary, displacing document-centered cognition.

## Recovery principles
- Recover intent before content.
- Surface unresolved tension before new synthesis.
- Prefer provenance-rich resurfacing over generic recap.
- Keep transition and persistence semantics explicit.

## Prevention heuristics (conceptual)
- Treat interruption as a first-class transition, not an exception.
- Keep salience dynamic and revisable across time.
- Preserve anchor continuity during overlay dismiss/reopen cycles.
- Avoid introducing app-only semantic state that cannot be reconstructed.

## Related docs
- `TEMPORAL_COGNITION.md`
- `ATTENTION_MODEL.md`
- `CONTINUITY_AND_DECAY.md`
- `POSTURE_TRANSITIONS.md`
- `SALIENCE_AND_TENSION.md`
- `UI_RUNTIME_BOUNDARIES.md`
