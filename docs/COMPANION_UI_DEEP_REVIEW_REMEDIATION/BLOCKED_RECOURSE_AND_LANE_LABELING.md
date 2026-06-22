---
name: Blocked Recourse and Lane Labeling
description: Give Blocked proposals a plain-language reason and explicit recourse; label the two agent lanes (recorded vs not-recorded) in words, not colour alone.
task_id: CUIDR-08
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 02 J5 + J6; 04 A3/C2
parent_capability: Companion UI Deep-Review Remediation
prerequisites: [CUIDR-01]
depends_on: [CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP.md]
can_parallelize_with: [Mist Ladder Subtractive, Governed Receipt First Class]
---

# Blocked Recourse and Lane Labeling

## Purpose

Close two legibility gaps that leave the user at a dead end or forced to infer critical
distinctions from colour and button count alone:

1. **A3 — Blocked recourse.** A WriteGuard-held proposal (S5) already presents as held rather than
   red — the calm treatment is correct. But it states the rule name ("blocked by WriteGuard") with no
   plain-language reason and no next step: the user cannot tell *why* the hold fired or *what would
   unblock it*. The current fallback collapses to "staged proposal unavailable" — a dead end, not a
   guided hold.
2. **C2 — Lane labeling.** The two agent lanes differ on the single most trust-critical dimension in
   the system — whether an action is recorded — yet that distinction is stated nowhere in words. The
   body-edit lane (S2: amber inline SUGGESTED block + rail card, Apply/Discard, no Defer) and the
   governed lane (S3: blue rail card MOVE NOTE TO PROJECTS/, Apply/Discard/Defer) differ in colour
   and button count; a first-time user must infer the recording distinction from those signals alone.
   "Defer" carries no stated consequence.

## What This Task Does

### A3 — Blocked proposal: reason and recourse

Extends the blocked-state render path to surface two fields from the runtime's block payload:

- **Reason** — a plain-language sentence explaining why the hold fired (e.g. "Writes are
  temporarily held while the system is in safe mode."). The reason is humanised via the enum map
  (CUIDR-01) when the `block_reason.gate` field is a runtime enum; otherwise the `block_reason.message`
  field is rendered as-is. If neither is present, the calm fallback grammar applies: "Proposal held —
  details unavailable. Nothing was mutated."
- **Recourse** — a plain-language next step (e.g. "Writes resume automatically once safe mode
  clears. No action is needed now."). The recourse text is sourced from the runtime's
  `block_reason.recourse` field when present; otherwise a per-gate canonical fallback string is used.

The existing calm, non-red treatment (held state pill, no alarm) is preserved. The buttons do not
re-appear; the held state remains non-actionable. What changes is that the user is told *why* and
*what comes next* rather than encountering a mute dead end.

The "staged proposal unavailable" fallback that fires when `writeguard_blocked=True` but
`available=False` must also carry a reason + recourse rather than collapsing silently.

### C2 — Agent lane labeling

Adds a mandatory, prominently-positioned label line to every agent card — both the inline rail card
and the ⌘K palette row — stating in plain English whether applying the action is recorded:

- **Body-edit lane** label: `Apply · not recorded (no receipt)`
- **Governed lane** label: `Apply → vault change → receipt`

The recorded/not-recorded line is the most prominent text on the card — above the proposal
description, not below it. The lane type is sourced from the runtime payload's `lane` or `governed`
field; the UI never infers the lane from colour, button count, or proposal content.

**Defer consequence.** Every card that carries a Defer button appends a one-line consequence
immediately below or adjacent to the Defer button: e.g. "Deferred proposals return the next time
this note is active." The text is a fixed rendering string (not server-supplied); its purpose is
to prevent "Defer" from being a mystery action.

## Concretely

**Body-edit card (S2 lane):**

```
┌─ APPLY · NOT RECORDED (NO RECEIPT) ────────────────────────────┐
│ <proposal description>                                          │
│ [Apply]  [Discard]                                              │
└─────────────────────────────────────────────────────────────────┘
```

The lane-label line is the visual headline — larger weight or accent than the description line. No
receipt is generated; the label makes that explicit before the user acts.

**Governed card (S3 lane):**

```
┌─ APPLY → VAULT CHANGE → RECEIPT ───────────────────────────────┐
│ <proposal description>                                          │
│ [Apply]  [Discard]  [Defer ↓]                                   │
│          Deferred proposals return the next time                │
│          this note is active.                                   │
└─────────────────────────────────────────────────────────────────┘
```

The lane-label line is the visual headline. Apply triggers a vault write and produces a durable
receipt; the label states that before the user acts.

**Blocked card (S5, calm treatment):**

```
┌─ HELD — no action possible ────────────────────────────────────┐
│ <proposal description>                                          │
│                                                                 │
│  Why: Writes are temporarily held while the system              │
│       is in safe mode.                                          │
│  What unblocks this: Writes resume automatically once           │
│       safe mode clears. No action is needed now.                │
│                                                                 │
│  (no Apply / Discard / Defer buttons)                           │
└─────────────────────────────────────────────────────────────────┘
```

No red state, no alarm. The calm pill / held-state treatment is preserved. The reason and recourse
lines are rendered below the description, clearly separated. If `block_reason` is absent from the
payload, the fallback renders: "Proposal held — details unavailable. Nothing was mutated."

## Why This Matters

The review identifies the body-edit vs governed asymmetry as a *deliberate and correct* design
decision — one that must be made legible, not flattened. The recording distinction is the central
trust claim of the system ("you can always tell whether your vault changed and whether there's a
record"), and that claim is currently buried in colour coding. Naming it removes the inferential
burden entirely.

For blocked proposals: the current dead end ("staged proposal unavailable") is categorically worse
than a short, calm explanation. The user cannot act on a blocked proposal regardless of how much
information is presented, but they can decide whether to wait, contact an operator, or continue
working on unblocked notes — only if they are told what is happening.

## Acceptance Criteria

**A3 (static): Blocked proposal — reason and recourse present.**
A Blocked proposal renders, in the calm (non-red) treatment, both a plain-language reason and an
explicit next step / recourse. No proposal collapses to "unavailable" or "held" with no
explanation.
Verify: render the WriteGuard-held fixture via `render_index_html` (static capture);
assert `data-testid="palette-blocked-reason"` and `data-testid="palette-blocked-recourse"` are
present and non-empty; assert no `data-testid="palette-proposal-unavailable"` element renders
without adjacent reason + recourse text.
New test: `tests/companion_ui/test_blocked_proposal_recourse.py` —
`test_blocked_proposal_shows_reason_and_recourse`.

**C2 (static): Agent cards label the recording distinction in words; Defer states its consequence.**
Each agent card (body-edit and governed) states in words whether applying it is recorded (receipt)
or not. The recorded/not-recorded line is the most prominent text on the card. Defer states its
consequence.
Verify: render S2 / S3 / O1 fixtures via `render_index_html` (static capture);
assert body-edit cards contain `data-testid="lane-label"` with text matching `not recorded`;
assert governed cards contain `data-testid="lane-label"` with text matching `receipt`;
assert any card carrying a Defer button also carries `data-testid="defer-consequence"` with
non-empty text.
New test: `tests/companion_ui/test_lane_label_and_defer_consequence.py` —
`test_body_edit_lane_label_not_recorded`,
`test_governed_lane_label_receipt`,
`test_defer_consequence_present`.

## How to Verify (Pre-Merge)

1. **Static — Blocked fixture.** Render the WriteGuard-held proposal fixture. Confirm the calm
   held-state pill is present; confirm reason + recourse text is rendered below the description;
   confirm no Apply/Discard/Defer buttons appear; confirm no raw enum token or rule identifier is
   visible in the user-facing copy.
2. **Static — Lane labels.** Render the S2 (body-edit) and S3 (governed) panel-rail fixtures and the
   O1 ⌘K palette fixture. Confirm the lane-label line appears as the most prominent text on each
   card. Confirm body-edit reads "not recorded (no receipt)" and governed reads "vault change →
   receipt". Confirm the Defer button on governed cards has an adjacent consequence line.
3. **Static — Palette blocked.** Render the `_blocked_html` path in `panel_palette.py` with a
   fixture that supplies `block_reason.gate` and `block_reason.recourse`. Assert the humanised
   reason and recourse appear at `data-testid="palette-blocked-reason"` and
   `data-testid="palette-blocked-recourse"`.
4. **Constraint check.** Grep the changed render functions for any branch that derives lane type from
   colour, button count, or proposal content rather than the runtime's `lane` / `governed` field.
   Zero matches expected.
5. **Regression.** Run `tests/companion_ui/test_panel_palette.py`,
   `tests/companion_ui/test_panel_proposal_row.py`, and
   `tests/companion_ui/test_governance_queue_browser.py`. All existing tests must pass.

## Out of Scope

- Whether a proposal is blocked, which rule blocked it, or whether a lane is governed are all
  server-authoritative facts. This task renders humanised copy **from** those runtime-declared
  fields. It must not add any client-side logic that decides whether something is blocked or which
  lane it belongs to.
- Changing the button set, the action affordances, or the confirm/reject pipeline for either lane.
  That is the domain of the governed-lane interaction spec, not presentation labeling.
- Changing the visual styling of the calm held-state (pill colour, border, typography) beyond adding
  the reason + recourse text block. The non-red treatment is deliberate and must be preserved.
- Defer behaviour (what the runtime does with a deferred proposal). This task only adds the
  consequence label to the presentation.
- Promoted receipt (CUIDR-07 / GOVERNED_RECEIPT_FIRST_CLASS). That task handles post-apply state;
  this task handles pre-apply lane labeling and blocked pre-apply state.

## Restart / Durability Posture

**Body-edit suggestions** are in-memory for the lifetime of the active Canvas session. They are not
persisted across process restarts. If the API process restarts while a suggestion is staged, the
suggestion is gone when the page reloads. The user experiences: the rail returns to its ambient
state, the suggestion card is absent, and no error is surfaced. This is the intended behaviour —
the suggestion was never written to the vault, so nothing is lost. The lane label "Apply · not
recorded (no receipt)" already states the ephemeral nature of the action before the user acts;
the post-restart empty rail is consistent with that statement.

**Staged / blocked governed proposals** have lifecycle managed by the server's proposal store. A
blocked proposal remains in the server's staging area across restarts (the block is on writes, not
on the proposal record itself); when the process restarts, the blocked proposal is re-declared in
the next payload and rendered with the same reason + recourse. If the proposal store is in-memory
(non-pg mode), a process restart drops all staged proposals. The user experiences: the rail returns
to ambient, the blocked card is absent. This is the honest consequence of the in-memory posture and
must not be papered over with a misleading "no proposals" state.

If a staged (non-blocked) governed proposal disappears after restart in non-pg mode, the same
posture applies: the rail shows ambient, no error. The "Apply → vault change → receipt" label
correctly implies the action was not yet taken — nothing was mutated, nothing is owed.

## Related Docs

- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt` — J5/J6
  verdicts and recs A3/C2 (the authoritative design input for this task)
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP.md` (CUIDR-01) —
  the enum map and degraded-copy grammar this task depends on for humanising `block_reason.gate`
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/RAIL_AMBIENT_UNTIL_ACTIVE.md` (CUIDR-03) — the rail
  active-state contract that hosts the lane-labelled cards and the blocked card
- `companion-ui/companion-app/companion_ui/workspace/panel_palette.py` — `_blocked_html` (current
  blocked render path, to be extended) and `palette_row_model` (row model, to gain `lane` field)
- `companion-ui/companion-app/companion_ui/panel/proposal_row.py` — `ProposalRow` model (to gain
  `lane` / `governed` field) and `ProposalReceipt`
- `app/write_guard.py` and `app/health_contract.py` — WriteGuard runtime; `write_guard_reason`
  field in health payload (the upstream block signal)
- `tests/companion_ui/test_panel_palette.py` — existing palette tests (must not regress)
- `tests/companion_ui/test_panel_proposal_row.py` — existing proposal row tests (must not regress)
- `tests/companion_ui/test_governance_queue_browser.py` — existing governance queue tests

## Related GitHub Issues

Maps to child issue [Companion UI Deep-Review] blocked-recourse-and-lane-labeling; Wave 2;
`agent:blocked` until CUIDR-01 (CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP) merges.
