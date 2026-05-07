# Event Model Summary

## Intent
Keep companion UI compatible with event-driven runtime evolution and future AgentState coordination.

## Event categories
- `ui.intent.*`: user interaction intents (open drawer, expand rail, accept/discard proposal).
- `ui.state.*`: non-durable runtime transitions for local rendering.
- `proposal.*`: staged suggestion lifecycle (`created`, `accepted`, `discarded`).
- `provenance.*`: citation/context linkage events.
- `persistence.*`: explicit durable writes through runtime contracts.

## Contract posture
- Use explicit event envelopes with stable names/versioning.
- Keep ephemeral UI state separate from persisted artifact events.
- Never infer hidden semantic state from visual state alone.

## AgentState compatibility
The UI event model should remain usable as input/output boundaries for future AgentState graphs without introducing app-specific semantic side channels.
