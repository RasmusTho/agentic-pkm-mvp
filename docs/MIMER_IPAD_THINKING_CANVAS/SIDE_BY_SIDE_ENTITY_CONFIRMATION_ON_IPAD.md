---
name: Side-By-Side Entity Confirmation On iPad
description: JE on the iPad canvas — a pending entity mention beside its candidate entities' context, merge/reject recorded as reversible appended decisions with provenance.
task_id: MIPAD-03
source_anchor: docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md :: §2 Platform footprint
parent_capability: Mimer iPad Thinking Canvas
prerequisites: [MIPAD-02]
depends_on: [VAULT_BROWSE_COLUMNS_WITH_NOTE_INSPECTOR]
can_parallelize_with: [ANNOTATE_AND_PROMOTE_INTO_NOTES]
---

# Side-By-Side Entity Confirmation On iPad

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).
**Write gate applies:** blocked until hub #3129/#3131/#3132 and bifrost#4/#5 are all merged
(README :: Write gate).

## Purpose

The design-of-record calls side-by-side entity confirmation "the single biggest iPad win": the
score-banded candidate compare is cramped on a phone. B1's `EntityConfirmLensView` (A17) already
implements the JE mechanism end-to-end on iPhone — read `pending` from
`_heimdal/entities/review.md`, append to `decisions`, hub applies and clears. This task widens
that same mechanism into a comparison surface; it does not change the note contract.

## What This Task Does

- **Content column:** the pending review queue (from `EntityReviewNote.pending`), each entry
  showing surface form, confidence band, and candidate count — the existing lens data, richer
  layout.
- **Detail column (the JE win):** for the selected pending entry, show the mention's context on
  one side and, on the other, the candidate entities — for each `candidateEntityIDs` entry,
  resolve and render the candidate's entity note from the Mimer-owned register
  (`_heimdal/entities/…`, read-only; when a candidate note does not exist as a file, render the
  bare ID with an explicit "no note yet" state, never a crash or a hidden row).
- **Actions:** Merge (into a chosen candidate — selection required when more than one candidate,
  replacing B1's first-candidate default on this surface), Reject, and **Undo** (a compensating
  decision appended for the same `queue_entry_id`, per INV-B2-4). All three go through
  `fileStore.readModifyWrite(HeimdalPaths.entityReview)` + `EntityReviewNote.addDecision` — the
  identical seam B1 uses, now coordinated + provenance-tagged by bifrost#4/#5.
- The client never mutates `pending`, never edits or deletes prior `decisions` entries, and never
  writes the entity register notes themselves (Mimer-organ-owned, ADR-0049 §2).

## Concretely

iPad simulator with a fixture vault: `_heimdal/entities/review.md` containing one pending entry
with two candidates → detail shows mention left, two candidate cards right → tapping a candidate
then **Merge** appends `{queue_entry_id, action: merge, from, into, decided_at}` to `decisions`
(file diff shows exactly one appended array entry plus provenance update) → **Undo** appends the
compensating entry; `pending` is untouched by the client in both cases.

## Why This Matters

Entity merges are identity decisions over the knowledge base — a wrong or lost decision corrupts
the register the whole system resolves against. Reversible append-only decisions with provenance
are what make a fat-finger on a tablet recoverable instead of destructive. This satisfies #3024's
"reversible" acceptance at the decision layer; materializing register redirects from decisions
stays hub-side.

## Acceptance Criteria

- [ ] Selected pending entry renders mention and ALL candidates side by side, including the
  missing-candidate-note state. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/EntityCompareModelTests.swift::testCandidateResolutionIncludingMissingNotes`
  (new; view-model level with a fixture store).
- [ ] Merge with an explicitly selected candidate appends exactly one decision entry via
  `readModifyWrite`; `pending` and prior `decisions` are byte-identical after the write except the
  append. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/EntityDecisionWriteTests.swift::testMergeAppendsSingleDecisionWithoutTouchingHistory`
  (new; asserts through the store's public API on a temp vault).
- [ ] Undo appends a compensating decision for the same `queue_entry_id` and the UI reflects the
  entry as un-decided locally. `Verify:` bifrost
  `EntityDecisionWriteTests.swift::testUndoAppendsCompensatingDecision` (new).
- [ ] Decisions carry the provenance behavior from bifrost#5 (block present/updated on the write).
  `Verify:` bifrost `EntityDecisionWriteTests.swift::testDecisionWriteCarriesProvenance` (new;
  enforcement AC — asserts provenance is applied on the real `readModifyWrite` path used by the
  Merge action, not a helper in isolation).
- [ ] iPad journey test covers queue → compare → merge → undo. `Verify:` bifrost
  `Yggdrasil/YggdrasilUITests/MimerCanvasUITests.swift::testEntityCompareMergeUndoJourney` (new,
  iPad destination).

## How to Verify (Pre-Merge)

- bifrost CI green (both destinations) including the five named tests; `swiftlint --strict` clean.
- Pre-merge gate check recorded in the PR body: hub #3129/#3131/#3132 and bifrost#4/#5 all show
  `state: MERGED/CLOSED` (INV-B2-5).

## Out of Scope

- Applying decisions / clearing pending / writing register redirect notes (hub-side Mimer organ).
- Any change to the `_heimdal/entities/review.md` schema (owned by hub #3131's published schema).
- Drag-drop and annotation (MIPAD-04).

## Related Docs

- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §2 (entity register is Mimer-owned; merges are note edits)
- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5–§6, §8 (Bifrost family)
- `docs/MIMER_IPAD_THINKING_CANVAS/README.md` (INV-B2-2/-B2-4/-B2-5)
- bifrost: `Yggdrasil/Yggdrasil/Mimer/Lenses/EntityConfirmLensView.swift`, `Packages/YggdrasilCore/Sources/YggdrasilCore/HeimdalNotes.swift`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:blocked` — names its gate
list explicitly: MIPAD-02 issue + hub #3129/#3131/#3132 + bifrost#4/#5), linking hub #3024 and
this spec file. TCD hint: Sonnet / high effort — data-plus-UI slice whose write discipline must be
exactly right; escalate to Opus only if the review-note schema from #3131 lands materially
different from the shipped `HeimdalNotes` shapes.
