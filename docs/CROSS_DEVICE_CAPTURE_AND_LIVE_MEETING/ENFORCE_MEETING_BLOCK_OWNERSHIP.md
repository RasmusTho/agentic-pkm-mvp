---
name: Enforce Meeting Block Ownership
description: Meeting block model with stable id, owner, type, and provenance; user_note writable only through the user's editor seam; derived writers confined to derived_projection; ambiguity fails closed.
task_id: CDLM-07
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4387"
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-06]
depends_on: [PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS.md]
can_parallelize_with: []
---

# Enforce Meeting Block Ownership

State: Delivered by hub issue #4387 (2026-07-30). The block model, the shared fail-closed
ownership guard, and the durable block registry are implemented in `app/heimdal/meeting_blocks.py`
(`apply_block_write` is the one seam); the user-note endpoint
`POST /api/heimdal/meeting/{session_id}/user-note` is in `app/api/routes/heimdal_meeting.py` with
CDLM-01 ack ordering and the `heimdal.meeting.user_note.written` event (`docs/EVENTS.md`); the
CDLM-06 derivation and analysis writers register their transcript/analysis blocks through the same
guard; refusals and the page-block composition surface on the projection read. The six acceptance
criteria below are proven by `tests/heimdal/test_meeting_block_ownership.py`. Tables ship in
migration `c9e4a1b6d3f5`, whose pg trigger additionally rejects any user_note content change that
does not carry user-editor provenance — defense in depth under the guard. Editor identity remains
structural (client-contract F2 owns cryptographic identity later), stated honestly.

## Purpose

Make "the AI can never touch your notes" a mechanical property of the hub, not a UI promise. The
meeting page is a governed composition of blocks with different owners; this task builds the block
model and the guard that keeps ownership boundaries closed (INV-CDLM-6).

## What This Task Does

- **Block model.** Every meeting-page block carries `{block_id (stable, minted at creation, never
  reused), owner ∈ {user, system}, type ∈ {user_note, derived_projection, transcript_segment},
  provenance (editor identity or engine+template+revision), created_at, revised_at}`. The block
  registry is durable session state.
- **The ownership guard, at one seam.** All block mutations — user edits, analysis revisions,
  reconciliation, template re-render, finalization — pass through one shared block-write guard:
  - a `user_note` block is writable only by the user's editor identity through the user-note
    endpoint below; every other writer is refused;
  - a derived writer may create/revise/retire only `derived_projection` blocks it owns by
    provenance; it may never move, renumber, merge, or reorder blocks it does not own;
  - `transcript_segment` blocks are created by the CDLM-06 derivation and revised only by it;
  - a write naming an unknown `block_id`, an unknown owner/type, or a target whose recorded
    ownership conflicts with the writer **fails closed**: the write is refused, existing content
    is untouched, and a legible refusal (who attempted, what target, why refused) is recorded and
    surfaced as needs-attention.
- **User-note write endpoint.** `POST /api/heimdal/meeting/{session_id}/user-note` accepts
  `{note_block_id (client-minted UUID), revision (client-monotonic), text, editor_identity}`;
  idempotent by `(note_block_id, revision)` with CDLM-01's ack ordering (durable write + committed
  event before 2xx) so the client can retain-until-ack and resend safely. Revisions of a user note
  supersede content but preserve the block's identity, position, and edit history.
- **Survival guarantees, tested where they bite:** analysis re-derivation over any segment set,
  template re-render, late-segment reconciliation, and finalization each run against a page
  containing user notes — and each provably leaves every `user_note` block byte-identical, in
  place, with provenance intact.

## Concretely

Write a user note into `mtg-42`; force analysis revision N+1, a template re-render, and a late
segment reconcile → the note's bytes, id, and position are unchanged; attempt a derived write
targeting the note's `block_id` → refused, recorded, surfaced; re-post the same note revision →
idempotent replay, one stored revision.

## Why This Matters

The meeting page mixes machine text with the user's own thinking in one visual space. One derived
writer with a wrong target id is enough to destroy human-authored content invisibly — the exact
class of loss the artifact taxonomy calls Human Knowledge Artifacts and protects with human-first
write guards. Fail-closed here is what makes the CDLM-09 UI labels true rather than decorative.

## Acceptance Criteria

- [ ] A derived writer (analysis, reconciliation, template re-render, finalization) attempting to
  write any `user_note` block is refused through the production guard call site, with content
  untouched and a recorded, surfaceable refusal.
  - Verify: `tests/heimdal/test_meeting_block_ownership.py::test_derived_writers_cannot_touch_user_notes`
    (enforcement: exercises each production writer path against a user_note target).
- [ ] Unknown or conflicting ownership (unknown block id, mismatched owner/type, provenance
  conflict) fails the write closed and preserves existing content.
  - Verify: `tests/heimdal/test_meeting_block_ownership.py::test_ambiguous_ownership_fails_closed`
- [ ] The user-note endpoint is idempotent by `(note_block_id, revision)` and acknowledges only
  after durable write + committed event.
  - Verify: `tests/heimdal/test_meeting_block_ownership.py::test_user_note_write_idempotent_and_durable`
- [ ] Analysis revision, template re-render, and late-segment reconciliation each leave every
  user_note block byte-identical, in place, with provenance intact.
  - Verify: `tests/heimdal/test_meeting_block_ownership.py::test_user_notes_survive_all_derived_passes`
- [ ] Derived writers cannot move, merge, reorder, or renumber blocks outside their provenance
  even within `derived_projection` types.
  - Verify: `tests/heimdal/test_meeting_block_ownership.py::test_derived_writers_confined_to_own_provenance`
- [ ] Only the user's editor identity passes the guard for user_note writes; a forged
  `editor_identity` from a derived context is refused at the production seam.
  - Verify: `tests/heimdal/test_meeting_block_ownership.py::test_editor_identity_required_for_user_notes`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_asyncio.plugin -q tests/heimdal/test_meeting_block_ownership.py`
  — all six ACs, including every production-writer enforcement path.
- `ruff check app tests`; migrations + producers + preflight in the same PR.
- CI: `Unit tests (not pg)` green on the head SHA.

## Out of Scope

- The iPad editor and labels (CDLM-09). Finalization materialization (CDLM-08 — it consumes the
  guard; its own ACs prove the survival at finalize time).
- Cross-session or vault-wide block models (this is meeting-session state; vault note classes
  remain governed by ADR-0055's table).
- Collaborative multi-user editing (single-operator system; one user editor identity).
- Client-contract F2 auth keys (editor identity rides the existing provenance conventions until
  F2 lands; the guard's identity check is structural, not cryptographic, in this slice — stated
  honestly).

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-6; partial-failure matrix rows
  on template switch and concurrent user writes)
- `docs/development/AGENT_OPERATING_PROTOCOL.md` (artifact classes: Human Knowledge vs Machine
  Mirror vs Bridge/Assembly — the meeting page is a governed composition)
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md` (governed-write chain this endpoint mirrors)

## Related GitHub Issues

One hub issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ENFORCE_MEETING_BLOCK_OWNERSHIP").
TCD hint: Opus / high–xhigh — authority-boundary enforcement with fail-closed semantics across
every production writer; the protected-finding class if it regresses.
