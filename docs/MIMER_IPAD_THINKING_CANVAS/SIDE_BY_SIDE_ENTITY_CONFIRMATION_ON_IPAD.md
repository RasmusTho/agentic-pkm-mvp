---
name: Side-By-Side Entity Confirmation On iPad
description: JE on the iPad canvas — a pending entity mention beside candidate context, with proposal-bound approval/reject/undo signals and Hub-owned merge execution.
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
implements the JE review surface end-to-end on iPhone — read `pending` from
`_heimdal/entities/review.md`, record a proposal-bound review signal, and let the Hub canonicalize,
apply, record, and clear it. This task widens that surface; it does not give the client
merge-execution authority.

## What This Task Does

- **Content column:** the pending review queue (from `EntityReviewNote.pending`), each entry
  showing surface form, confidence band, and candidate count — the existing lens data, richer
  layout.
- **Detail column (the JE win):** for the selected pending entry, show the mention's context on
  one side and, on the other, the candidate entities — for each `candidateEntityIDs` entry,
  resolve and render the candidate's entity note from the Mimer-owned register
  (`_heimdal/entities/…`, read-only; when a candidate note does not exist as a file, render the
  bare ID with an explicit "no note yet" state, never a crash or a hidden row).
- **Actions:** Approve the displayed merge proposal into a chosen candidate (selection required when
  more than one candidate), Reject, and **Undo** a still-unapplied approval. These are
  proposal-bound review signals through the coordinated/provenance-tagged review seam; the Hub,
  not the client signal, canonicalizes an approval into a merge operation.
- The client never mutates `pending`, never edits or deletes prior review history, never writes the
  entity register notes, and never owns merge execution (Mimer-organ-owned, ADR-0049 §2).
- **Delivered Hub-side transaction boundary (EROJ-01, #4350):** when the Hub folds an uncompensated
  approval, it canonicalizes it into one durable entity-review operation
  (`entity_review_operations`, deterministic over the exact decision mapping) **before** any
  register mutation; the operation's `heimdal.register.entity.merged` event commits atomically with
  its terminal journal state; and the `pending` entry is cleared only after a **fresh** database
  transaction observes both committed rows. A client record alone is never replayed as a merge
  command, and a changed decision mapping for a still-active operation fails closed with the entry
  left pending. Recovery across later target merges/splits is not claimed by this boundary
  (EROJ-02/EROJ-03).

## Undo boundary

Undo is reversible only at the append-only **decision layer before hub application**. The client
appends `action: undo` for the same `queue_entry_id`; while that entry is still in `pending`, the
hub folds the ordered decision history to an undecided state, performs no register mutation, keeps
the pending entry, and retains every `merge`/`reject`/`undo` history entry. A later merge or reject
may establish a new terminal intent.

Once the hub has applied an uncompensated merge or reject and cleared `pending`, a later undo is an
idempotent no-op. It does not reverse an already-materialized register merge, call
`EntityRegister.split`, or grant the Bifrost client register-write authority. The client must
refresh the hub-owned pending state rather than present a late undo as a successful register
reversal.

## Concretely

iPad simulator with a fixture vault: `_heimdal/entities/review.md` containing one pending proposal
with two candidates → detail shows mention left, two candidate cards right → tapping a candidate
then **Approve** records one proposal-bound approval with the selected candidate and provenance →
the Hub canonicalizes that approval into the sole merge operation and later publishes the durable
outcome → **Undo**, before Hub application, records a compensating undo for the same proposal.
`pending` is untouched by the client in every case; the Hub fold preserves a compensated proposal as
undecided.

## Why This Matters

Entity merges are identity decisions over the knowledge base — a wrong or lost decision corrupts
the register the whole system resolves against. Proposal-bound, reversible review signals make a
fat-finger on a tablet recoverable while keeping canonical execution and durable outcomes in the
Hub. This satisfies #3024's "reversible" acceptance at the review layer; materializing register
redirects stays Hub-side.

## Acceptance Criteria

- [ ] Selected pending entry renders mention and ALL candidates side by side, including the
  missing-candidate-note state. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/EntityCompareModelTests.swift::testCandidateResolutionIncludingMissingNotes`
  (new; view-model level with a fixture store).
- [ ] Approving an explicitly selected candidate records exactly one proposal-bound review signal;
  `pending` and prior history are byte-identical after the write except the append, and the signal
  is not presented as a merge command. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/EntityDecisionWriteTests.swift::testApprovalAppendsSingleProposalBoundSignalWithoutTouchingHistory`
  (new; asserts through the store's public API on a temp vault).
- [ ] Undo appends a compensating decision for the same `queue_entry_id` and the UI reflects the
  entry as un-decided locally. `Verify:` bifrost
  `EntityDecisionWriteTests.swift::testUndoAppendsCompensatingDecision` (new).
- [ ] Review signals carry the provenance behavior from bifrost#5 (block present/updated on the
  write). `Verify:` bifrost `EntityDecisionWriteTests.swift::testApprovalWriteCarriesProvenance`
  (new; enforcement AC — asserts provenance on the real approval path, not a helper in isolation).
- [ ] iPad journey test covers queue → compare → approve → undo and displays the Hub-owned durable
  outcome after refresh. `Verify:` bifrost
  `Yggdrasil/YggdrasilUITests/MimerCanvasUITests.swift::testEntityCompareApproveUndoAndHubOutcomeJourney` (new,
  iPad destination).

## How to Verify (Pre-Merge)

- bifrost CI green (both destinations) including the five named tests; `swiftlint --strict` clean.
- Pre-merge gate check recorded in the PR body: hub #3129/#3131/#3132 and bifrost#4/#5 all show
  `state: MERGED/CLOSED` (INV-B2-5).
- The Hub operation-journal parent #4349 is accepted through EROJ-01 → EROJ-03 and publishes the
  proposal/approval contract before this client implementation is resumed.

## Out of Scope

- Applying decisions / clearing pending / writing register redirect notes (hub-side Mimer organ).
- Any Hub operation-journal, proposal/approval schema, or register-execution implementation
  (owned by #4349's EROJ chain).
- Drag-drop and annotation (MIPAD-04).

## Related Docs

- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §2 (entity register is Mimer-owned; merges are note edits)
- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5–§6, §8 (Bifrost family)
- `docs/MIMER_IPAD_THINKING_CANVAS/README.md` (INV-B2-2/-B2-4/-B2-5)
- bifrost: `Yggdrasil/Yggdrasil/Mimer/Lenses/EntityConfirmLensView.swift`, `Packages/YggdrasilCore/Sources/YggdrasilCore/HeimdalNotes.swift`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:blocked` — names its gate
list explicitly: MIPAD-02 issue + hub #3129/#3131/#3132 + bifrost#4/#5 + accepted hub #4349 EROJ
chain), linking hub #3024 and
this spec file. TCD hint: Sonnet / high effort — data-plus-UI slice whose write discipline must be
exactly right; escalate to Opus only if the review-note schema from #3131 lands materially
different from the shipped `HeimdalNotes` shapes.
