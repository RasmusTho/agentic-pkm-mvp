# Implementation contract — Context Bundle Inspector

**Status:** Contract for UI integration · target-state
**Mutates:** nothing on its own
**Depends on:** docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/, the gated-execution invariant.

## Position in the chain

This document is the part of the package that implementation reads. It is the only document
that promises anything to code. Everything else in the package (README, design-notes,
state-gallery, edge-states, authority-boundaries, open-questions) is guidance.

## State enum

The implementation must enumerate exactly the states described in **`prototype.html` §03 + §05**. Adding
or removing a state without amending this document means the design no longer covers it.

## Allowed transitions

See **`prototype.html` §03 + §05** for the per-state transition table. Implementation must
reject any transition not enumerated there.

## Data attributes

Stable attributes the design relies on for testids and behavioral selectors are listed in
**`prototype.html` §07 (Implementation contract)** of this package. Required attributes are
flagged in the prototype's code block. Adding new attributes is permitted; renaming is not.

## Intents

The full `data-intent` vocabulary is in **`prototype.html` §07**. Each intent declares:

- the surface that emits it,
- the effect (UI-local / read-only / governed / navigation),
- whether it routes through the governance pipeline.

Implementation must not emit intents not declared here. Adding a new intent requires an
amendment to this document.

## Server contract surface

Endpoints / events / classifiers the UI consumes are bound to existing or proposed runtime
contracts. The UI never re-classifies; the server's declared class wins.

Specific contract references:

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/`

## Validation expectations

A passing validation receipt for this package would render the full state gallery against
fixture inputs, verify every declared transition, and confirm:

- no UI-derived posture / class / authority,
- denied / blocked states emit the right receipts,
- reduced-motion preference is respected,
- narrow / portrait layout preserves all critical affordances.

The exact fixture set is owned by the implementation issue, not this document.

## What this contract does not say

Explicit list of things implementation is free to choose:

- framework (React, vanilla, web components — design works for any),
- style technique (CSS, styled-components, CSS modules),
- animation library (none needed; the design uses CSS),
- persistence cache shape,
- network transport.
