# Runtime Proof / Health Dashboard

**Date:** 2026-05-14
**Status:** Design handoff · v1 · ready for review at crossing B
**Authority:** Visual guidance only — mirror of runtime state
**Owner-docs:** STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md (invariant), runtime-proof receipt contract (when normalized)
**Crossing target:** B

## What this is

Compact operator surface for proving whether the local-first runtime is actually working — watcher, worker, outbox, vault, write-guard, last proof receipt.

The dashboard answers nine questions the local operator must be able to answer:

1. Is the system running?
2. Is the watcher healthy?
3. Is the worker healthy?
4. Are there stuck or poison outbox messages?
5. Is the vault scope correct?
6. Is indexing moving?
7. Are writes allowed or blocked?
8. What was the last successful proof receipt?
9. What should I do next?

See `prototype.html` §03 for the dashboard prototype, §04 for the section design, §05 for the 9-state gallery.

## Influence

- **May influence:** card layout, copy, LED palette, sparkline placement, next-action vocabulary, narrow-layout collapse order.
- **May not decide:** the snapshot schema, posture algorithm (UI never derives `overall.posture`), receipt shape, polling interval, what counts as healthy.

## Files

- `prototype.html` — full 10-section spec, dashboard mock, 9-state gallery.
- `design-notes.md`, `state-gallery.md`, `implementation-contracts.md`, `authority-boundaries.md`, `edge-states.md`, `open-questions.md`.

## Related

- Stabilization work this surface depends on landing first: watcher OOM repair, worker poison-message handling, startup sequencing, runtime-proof receipts.
- `STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md` — the invariant the dashboard honors (mirror, never control plane).

## Authority &amp; disclaimers

- **This design is visual guidance.** It is not architecture authority. Architecture authority lives in repo owner-docs.
- **Runtime truth lives downstream.** It is not asserted in this package. Runtime truth comes from shipped code, tests, status docs, and validation receipts.
- **This package proposes; it does not promote.** Promotion happens at crossing B (the maturity bar in the governance pack §03).
- **The gated-execution invariant is honored throughout.** No interaction surface in this design mutates durable state outside the governed pipeline.
