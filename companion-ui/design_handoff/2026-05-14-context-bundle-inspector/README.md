# Context Bundle Inspector

**Date:** 2026-05-14
**Status:** Design handoff · v1 · ready for review at crossing B
**Authority:** Visual guidance only — bundle schema not owned here
**Owner-docs:** docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/
**Crossing target:** B

## What this is

Inspector surface for the bundle bridge object — included artifacts, excluded artifacts, authority flags, receipts. Desktop + portrait. The bundle is the bridge object between retrieval, orientation, resurfacing, and write proposals; the inspector exposes it for human review.

Nine designed states:

1. Retrieval bundle (answering a question)
2. Orientation bundle (where was I)
3. Resurfacing bundle with "why now"
4. Write-proposal bundle (authority flags differ)
5. Stale bundle warning
6. Excluded source visible because exclusion affects interpretation
7. Degraded bundle (provenance incomplete)
8. Empty (no sufficient context)
9. Blocked (context exists but cannot support write proposal)

See `prototype.html` §02 for the field model, §03 for the inspector prototype, §04 for the portrait layout, §05 for the 9-state gallery.

## Influence

- **May influence:** field grouping, authority-chip wording, staleness presentation, exclusion-visibility default, narrow layout, dominant-role colour cues.
- **May not decide:** the bundle schema, the authority-flag set, expiry policy, the retrieval ranking, the apply / writeback flow.

## Files

- `prototype.html` — 10-section spec, inspector mock, portrait layout, 9-state gallery.
- Sibling markdown docs per the handoff governance pack's folder shape.

## Related

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` — the bundle contract this inspector renders.
- The Memory Candidate Review queue (sibling) — bundles may include memory items; promotion lives there, never here.
- The Canvas Suggestion Flow handoff — context bundles attach to canvas proposals.

## Authority &amp; disclaimers

- **This design is visual guidance.** It is not architecture authority. Architecture authority lives in repo owner-docs.
- **Runtime truth lives downstream.** It is not asserted in this package. Runtime truth comes from shipped code, tests, status docs, and validation receipts.
- **This package proposes; it does not promote.** Promotion happens at crossing B (the maturity bar in the governance pack §03).
- **The gated-execution invariant is honored throughout.** No interaction surface in this design mutates durable state outside the governed pipeline.
