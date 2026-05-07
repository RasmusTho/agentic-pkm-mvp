# Salience and Tension

## Purpose
Define how attentional relevance and unresolved cognitive pressure evolve over time while keeping salience and tension distinct from notification urgency or simple priority schemes.

## Boundary note
- This document defines the top-level relationship between salience and tension.
- `TENSION_PATTERNS.md` owns the deeper taxonomy of unresolved pressure.
- `RESURFACING_HEURISTICS.md` owns when salience and tension should trigger contextual return.

## Salience semantics
- Salience is the evolving relevance of a cognitive object to current or near-future thinking.
- Salience is temporal, contextual, and revisable.
- Salience is not equivalent to static priority.
- Salience may vary by gradient, not only by binary relevance.

## Tension semantics
- Cognitive tension is unresolved pressure in a thread.
- Typical tension forms: unanswered question, contradiction, deferred decision, incomplete synthesis.
- Tension should remain visible until explicitly resolved, reframed, or retired.
- Dormant pressure is unresolved tension that is not focal now but still capable of future resurfacing.

## Evolution model
- Objects can rise in salience via new context, interruption return, or downstream dependency.
- Objects can decay in salience when resolved, superseded, or contextually displaced.
- Decay should not erase provenance or historical significance.

## Resurfacing relationship
- Resurfacing should target unresolved tension and meaningful salience shifts.
- Low-provenance resurfacing should be treated as weak guidance.
- Salience promotion should preserve trajectory continuity, not reset context.
- Tension without continuity context should not be amplified into interruption-heavy interaction.

## Design constraints
- Do not collapse salience into rigid score-only logic.
- Do not hide tension in app-local state.
- Do not use AI-generated urgency without traceable context.

## Related docs
- `ATTENTION_MODEL.md`
- `TEMPORAL_COGNITION.md`
- `COGNITIVE_TRAJECTORIES.md`
- `TENSION_PATTERNS.md`
- `RESURFACING_HEURISTICS.md`
- `COGNITIVE_OBJECTS.md`
- `TEMPORAL_PROVENANCE.md`
