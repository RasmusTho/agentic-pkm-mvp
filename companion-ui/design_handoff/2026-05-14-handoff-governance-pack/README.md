# Design Handoff Governance Pack

**Date:** 2026-05-14
**Status:** Design handoff · v1 · ready for review at crossing B (handoff → normalized spec)
**Authority:** Process pattern only — not runtime, not architecture
**Owner-docs:** docs/INTERACTION_SURFACES_AND_AUTHORITY/
**Crossing target:** B

## What this is

A meta-handoff. How a Claude Design exploration becomes a governed implementation input — without becoming architecture authority on the way. Defines the chain:

```
design exploration → handoff package → normalized spec → GitHub issue → PR → validation receipt
```

Five artifacts inside the package:

- **Governance flow diagram** with crossing-by-crossing evidence requirements.
- **Maturity checklist** that decides when an exploration is allowed to become a normalized spec.
- **Review console prototype** — a target-shape operator surface for walking packages through the chain.
- **Three templates**: README, implementation-contract notes, authority-boundaries.
- **State, edge-case, and influence inventories** every design must answer before promotion.

See `prototype.html` §02 for the flow diagram, §03 for the maturity checklist, §04 for the review console prototype, §05–§07 for the README / implementation-contract / authority-boundaries templates.

## Influence

- **May influence:** the folder shape for every handoff in `companion-ui/design_handoff/`; the maturity bar at crossing B; the wording of README / implementation-contract / authority-boundaries templates.
- **May not decide:** which docs are owner-docs; which contracts are authority; the gated-execution invariant; how a validation receipt is produced.

## Files

- `prototype.html` — full 12-section spec + interactive review-console mock.
- `design-notes.md` — visual guidance and rationale.
- `state-gallery.md` — every UI state in the prototype, with descriptions.
- `implementation-contracts.md` — what implementation reads from this package.
- `authority-boundaries.md` — what this design may / may not influence.
- `edge-states.md` — empty / loading / degraded / blocked / stale / missing-provenance / write-guard / reduced-motion / narrow.
- `open-questions.md` — unresolved, with proposed owners.

## Related

- `docs/INTERACTION_SURFACES_AND_AUTHORITY/` — the existing authority-boundary docs that this pack governs the contribution process for.
- `companion-ui/design_handoff/README.md` — the handoff-folder index.
- The four sibling 2026-05-14 packages, which are themselves the first packages produced under this pack's folder shape.

## Authority &amp; disclaimers

- **This design is visual guidance.** It is not architecture authority. Architecture authority lives in repo owner-docs.
- **Runtime truth lives downstream.** It is not asserted in this package. Runtime truth comes from shipped code, tests, status docs, and validation receipts.
- **This package proposes; it does not promote.** Promotion happens at crossing B (the maturity bar in the governance pack §03).
- **The gated-execution invariant is honored throughout.** No interaction surface in this design mutates durable state outside the governed pipeline.
