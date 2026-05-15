# Memory Candidate Review Queue

**Date:** 2026-05-14
**Status:** Design handoff · v1 · ready for review at crossing B
**Authority:** Review surface · state mutates through governed pipeline
**Owner-docs:** docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md
**Crossing target:** B

## What this is

Review queue for proposed agent memories. Accept / edit / reject / defer / promote / keep-operational. Unreviewed memory is not semantic authority. Eight actions cover the lifecycle: accept, edit, promote-to-note, keep-operational, set-expiry, defer, reject, delete.

Ten designed states:

1. Single candidate card
2. Batch review queue
3. Strong source-backed candidate
4. Inferred low-confidence candidate
5. Candidate conflicting with existing memory
6. Candidate that should expire
7. Candidate rejected with reason
8. Candidate revised by the user
9. Candidate promoted to durable Markdown
10. Candidate kept as operational memory only

See `prototype.html` §02 for the memory classes, §03 for the queue prototype, §04 for the action vocabulary, §05 for the 10-state gallery.

## Influence

- **May influence:** queue layout, action bar, copy, default action by confidence band, batch-mode safety rails, conflict-resolution UI.
- **May not decide:** the memory class set, the authority-flag set on memory records, recall behavior, auto-archive policy, promotion target paths.

## Files

- `prototype.html` — 10-section spec, queue mock, 10-state gallery.
- Sibling markdown docs.

## Related

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` — the contract this queue serves as the review surface for.
- The Context Bundle Inspector (sibling) — bundles may reference memory items; promotion to durable knowledge happens here, not there.

## Authority &amp; disclaimers

- **This design is visual guidance.** It is not architecture authority. Architecture authority lives in repo owner-docs.
- **Runtime truth lives downstream.** It is not asserted in this package. Runtime truth comes from shipped code, tests, status docs, and validation receipts.
- **This package proposes; it does not promote.** Promotion happens at crossing B (the maturity bar in the governance pack §03).
- **The gated-execution invariant is honored throughout.** No interaction surface in this design mutates durable state outside the governed pipeline.
