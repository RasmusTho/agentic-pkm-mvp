# UI Runtime Boundaries

## Separation of concerns
- Cognition: human intent, reasoning continuity, and proposal interpretation.
- UI runtime: transient rendering/session state.
- Persistence/runtime integration: explicit writes via backend contracts.

## Rules
- UI-local state is ephemeral by default.
- Durable state must be explicitly persisted and vault-compatible.
- Do not add hidden app databases for meaning-bearing artifacts.
- Do not implement production backend integration inside this workspace lane.

## Cognitive boundary constraints
- Document remains the cognitive anchor.
- Overlays preserve continuity and provenance visibility.
- AI remains contextual rather than dominant.
- No runtime contract should require chat-centric, dashboard-centric, or notification-centric interaction.
- No interface contract should depend on hidden semantic state for continuity recovery.

## Integration boundary (future-safe)
- Keep transport and event contracts explicit.
- Keep proposal workflows staged-first.
- Keep provenance visible at interaction time, not only in audit trails.
- Keep interruption and re-entry semantics explicit at the interface boundary.

## Related docs
- `SYSTEM_OVERVIEW.md`
- `EVENT_MODEL_SUMMARY.md`
- `CONTINUITY_AND_DECAY.md`
- `TEMPORAL_PROVENANCE.md`
