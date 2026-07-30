---
name: Consolidate Meeting On End
description: Meeting finalization that materializes the consolidated transcript and final derived analysis create-once into the Sources zone, preserves user notes as their own artifact, and surfaces gaps as needs-attention.
task_id: CDLM-08
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-07]
depends_on: [ENFORCE_MEETING_BLOCK_OWNERSHIP.md]
can_parallelize_with: [RUN_LIVE_MEETING_ON_IPAD.md]
---

# Consolidate Meeting On End

State: Delivered by hub issue #4388 (2026-07-30). Finalization is implemented in
`app/heimdal/meeting_finalization.py`, triggered on session close (`POST
/api/heimdal/meeting/{session_id}/close`) and on post-close late-segment reconciliation through the
production admission path. It materializes the consolidated transcript, the final derived analysis
(draft standing, human-only promotion), and the verbatim user-notes artifact create-once into the
Sources zone through the governed write seam, registers its own block through the CDLM-07 guard as
the finalization writer, and commits the `heimdal.meeting.finalized` event before the durable
receipt that is the finalized acknowledgement (migration `d0f5b2c7e4a6`; receipt surfaced on the
projection read). The six acceptance criteria below are proven by
`tests/heimdal/test_meeting_finalization.py`. The vault root is settings-resolved via
`HEIMDAL_MEETING_VAULT_ROOT`; when unconfigured, finalization reports a named `skipped` outcome
rather than guessing a vault (the close remains ledger truth). KD-F9588AFBC165 (transcript-block
registration on the derivation-replay path) was absorbed here per its promotion trigger.

## Purpose

Turn a closed session's projections into durable artifacts with honest completeness — the step
where revisable projection state becomes create-once derived material, and where the separation
between the user's notes and machine output becomes permanent.

## What This Task Does

- **Trigger.** Runs on session close (CDLM-02) and re-runs on late-segment reconciliation after
  close. Idempotent per `(session_id, ledger completeness state)`: re-triggering with an unchanged
  ledger reuses the existing finalization, never duplicates artifacts.
- **Consolidated transcript.** The full ordered transcript materializes as one create-once
  Markdown note in the Sources zone (settings-resolved root per
  `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5, e.g. `Sources/Meetings/<session>/transcript`),
  with segment timing, confidence, explicit gap markers, and derivation provenance frontmatter.
  Sources-zone class rules apply: create-once; a post-reconciliation re-derivation creates a new
  note version by the zone's re-derivation rule, never a silent rewrite.
- **Final derived analysis.** The last analysis revision materializes as its own create-once note
  (summary, themes, decisions, open questions, action candidates under `generic-default@1`),
  frontmatter carrying template, revision, derived_from, and engine provenance. It is derived
  material at draft-zone standing — promotion to human-canonical knowledge remains a human act
  through the trust path; nothing here self-promotes.
- **User notes artifact.** The session's `user_note` blocks materialize verbatim (byte-identical
  content, original order, edit history reference) as their own note, distinctly provenanced as
  human-authored. Never merged into, appended to, or interleaved with the derived notes. The
  CDLM-07 guard runs at this call site too — finalization is a derived writer and cannot touch
  user content beyond copying it verbatim into the human-provenance artifact.
- **Completeness receipt.** Finalization emits a durable receipt
  `{session_id, complete | needs_attention, missing_seqs, artifact refs, finalized_at}` and the
  corresponding outbox event. `needs attention` (missing segments, failed derivations) is carried
  in the receipt, on the projection read, and in frontmatter on the materialized notes — a reader
  can never mistake a gapped transcript for a complete one (INV-CDLM-9).
- **Post-close reconciliation.** A late segment admitted after finalization re-derives and
  re-finalizes under the create-once re-derivation rule, superseding the receipt (old artifacts
  remain, marked superseded in the new receipt's lineage).

## Concretely

Close `mtg-42` with segment 2 missing → three notes materialize; transcript and receipt say
`needs_attention, missing:[2]`; late-admit 2 → re-finalization produces the complete versions
with lineage to the superseded ones; re-trigger close with nothing new → no new artifacts.

## Why This Matters

This is where the vertical's honesty becomes permanent record. A finalization that silently
rewrites, silently completes over gaps, or folds user notes into machine output would poison the
vault with exactly the ambiguity the block model exists to prevent — and unlike projection state,
vault artifacts are forever.

## Acceptance Criteria

- [ ] Finalization materializes the three artifacts with correct classes (create-once Sources
  material; derived analysis at draft standing; user notes with human provenance), through the
  governed write seam.
  - Verify: `tests/heimdal/test_meeting_finalization.py::test_three_artifacts_materialize_with_correct_classes`
- [ ] Re-triggering finalization with an unchanged ledger creates nothing new (idempotent), through
  the production trigger path.
  - Verify: `tests/heimdal/test_meeting_finalization.py::test_finalization_idempotent_per_ledger_state`
- [ ] A gapped close yields `needs_attention` with exact missing sequences in receipt, projection
  read, and note frontmatter.
  - Verify: `tests/heimdal/test_meeting_finalization.py::test_gapped_close_is_legible_everywhere`
- [ ] Late admission after close re-finalizes under the re-derivation rule with lineage to
  superseded artifacts; no silent rewrite of any existing note.
  - Verify: `tests/heimdal/test_meeting_finalization.py::test_post_close_reconciliation_supersedes_with_lineage`
- [ ] User-note content in the materialized artifact is byte-identical to the block registry
  content, and finalization writes pass the CDLM-07 guard at this production call site.
  - Verify: `tests/heimdal/test_meeting_finalization.py::test_user_notes_materialize_verbatim_via_guard`
- [ ] The finalization receipt and its outbox event commit before the close flow reports
  finalized (same ack-ordering family as CDLM-01).
  - Verify: `tests/heimdal/test_meeting_finalization.py::test_receipt_and_event_before_finalized_ack`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_asyncio.plugin -q tests/heimdal/test_meeting_finalization.py`
- `ruff check app tests`; CI `Unit tests (not pg)` green on the head SHA.

## Out of Scope

- Human promotion of derived analysis to canonical knowledge (the trust path owns it).
- Episode Resolution Engine registration of meeting sessions (sidecar fields already feed ADR-0051
  dimensions; ERE wiring is a later slice).
- Deleting or expiring raw segments (raw-store retention policy is owned elsewhere;
  `docs/HEIMDAL_LOCAL_ARCHIVE/README.md` governs cold-tier direction).
- Any UI (CDLM-09 renders the final view from these artifacts and the receipt).

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-5/6/9)
- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5 (Sources zone classes; create-once re-derivation)
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` (promotion stays human)
- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ENFORCE_MEETING_BLOCK_OWNERSHIP.md` (the guard this consumes)

## Related GitHub Issues

One hub issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/CONSOLIDATE_MEETING_ON_END").
TCD hint: Opus / high — vault-writing finalization with idempotency, lineage, and guard
composition; wrong behavior here is permanent.
