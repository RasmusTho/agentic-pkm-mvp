# Temporal Provenance

## Purpose
Define provenance semantics that preserve trust and continuity across time, interruptions, and resurfacing.

## Provenance dimensions
- **Source lineage:** where a claim or suggestion originates.
- **Temporal lineage:** when and in what sequence context changed.
- **Interpretive lineage:** why an object was surfaced, staged, or deferred.
- **Evolution lineage:** how understanding or confidence changed across the life of a trajectory.

## Provenance requirements
- Resurfaced objects must include enough lineage for rapid trust evaluation.
- Interruption recovery must include the last meaningful transition context.
- Deferred proposals must preserve prior rationale, not only status.

## Temporal continuity rules
- Historical validity and current validity can diverge; provenance must keep both intelligible.
- Provenance should survive salience decay and thread dormancy.
- Provenance should remain inspectable without forcing deep navigation.
- Provenance should support epistemic evolution without pretending that later framing erases earlier states.

## Re-entry semantics
- Re-entry cues should state prior intent, unresolved tension, and recent lineage.
- Provenance should support quick answers to: "Why am I seeing this now?"
- Absence of provenance should reduce confidence, not simulate certainty.

## Related docs
- `TEMPORAL_COGNITION.md`
- `COGNITIVE_OBJECTS.md`
- `ATTENTION_MODEL.md`
- `EPISTEMIC_EVOLUTION.md`
- `COGNITIVE_FAILURE_MODES.md`
