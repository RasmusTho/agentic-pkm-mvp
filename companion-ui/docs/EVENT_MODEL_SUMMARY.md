# Event Model Summary

## Intent
Keep companion UI compatible with event-driven runtime evolution while preserving cognitive semantics.

## Event categories
- `ui.intent.*`: user interaction intents (open drawer, expand rail, accept/discard proposal).
- `ui.state.*`: non-durable runtime transitions for local rendering.
- `posture.*`: cognitive posture entry/exit and transition hints.
- `proposal.*`: staged suggestion lifecycle (`created`, `accepted`, `discarded`).
- `provenance.*`: citation/context linkage events.
- `resurface.*`: contextual resurfacing and re-entry cues.
- `persistence.*`: explicit durable writes through runtime contracts.

## Contract posture
- Use explicit event envelopes with stable names/versioning.
- Keep ephemeral UI state separate from persisted artifact events.
- Never infer hidden semantic state from visual state alone.
- Preserve continuity metadata for interruption/recovery flows.

## Boundary rule
This file defines conceptual event boundaries only. It does not define runtime implementation strategy.

## Related docs
- `TEMPORAL_COGNITION.md`
- `ATTENTION_MODEL.md`
- `POSTURE_TRANSITIONS.md`
