# State gallery — Context Bundle Inspector

The full visual gallery lives in **`prototype.html` §05**. This document is a text mirror
intended for quick scanning in code review and for issue acceptance criteria.

Every state is described as a (name, when, designed behavior) triple. The prototype is the
authority on the visual; this document is the authority on the state list.

See `prototype.html` §02 for the field model, §03 for the inspector prototype, §04 for the portrait layout, §05 for the 9-state gallery.

## State list

See the gallery cards in `prototype.html` §05 for the canonical visuals. Each state in the
gallery includes:

- A bar with the state name and a state-kind chip.
- A title-row LED in the appropriate colour (vault / amber / destructive / dim / gold).
- A one-paragraph narrative describing the state.
- A meta line of mono captions naming the values that distinguish the state.
- Where relevant, a next-action strip with the suggested operator action.

## Transition table (illustrative)

Detailed transitions for the UI state machine are owned by `implementation-contracts.md`;
this gallery is descriptive, not normative. Implementation must enumerate the full set
declared in the contract document.

## Edge cases the gallery covers

- **Empty** — the surface explains why there is nothing and what produces content.
- **Loading** — inert, distinguishable from empty.
- **Degraded** — partial function with explicit naming of what is degraded.
- **Blocked** — refusal is named, recorded, and never silently retried.
- **Stale** — staleness is shown with a "why" and an explicit threshold.
- **Missing provenance** — surfaced, not hidden; never silently authoritative.

For the full edge-state checklist see `edge-states.md`.
