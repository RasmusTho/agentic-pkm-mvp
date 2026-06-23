---
name: Rail Ambient Until Active
description: Demote the right rail to a thin ambient strip when idle; expand only when it carries a suggestion, proposal, or receipt.
task_id: CUIDR-03
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 02 J2; 03 Visual hierarchy; 04 B1
parent_capability: Companion UI Deep-Review Remediation
prerequisites: []
depends_on: []
can_parallelize_with: [Calm Degraded Grammar and Enum Map, Overlay Modal Frame Spec, Edge Job and Reachability, Front Door and Copy Hygiene]
---

# Rail Ambient Until Active

## Purpose

Return the note column to its rightful place as the primary, widest, highest-contrast region on
screen by eliminating the permanently-reserved right-rail console. The rail earns its width only
when it has something the reader needs to act on.

## What This Task Does

Changes the render path for the right companion rail so it has exactly two visual states:

- **Ambient** — a thin strip (no sub-module stack, no idle header, no placeholder copy). Carries no
  interactive content beyond a minimal presence cue. Occupies the smallest defensible column width.
- **Active** — full rail width, rendered only when the payload contains at least one suggestion,
  proposal, or receipt.

The switch between states is governed by one content rule plus a small, closed set of
visibility-critical overrides:

```
rail_is_active iff
    len(suggestions) + len(proposals) + len(receipts) >= 1   # the content rule
    OR any visibility-critical override is set                # never hidden in the strip
```

**The content rule** is the primary contract: the rail earns its width when the payload carries at
least one suggestion, proposal, or receipt. Nothing about ordinary capability/availability state
(canvas idle/disabled, find unavailable, resurface degraded, a "thinking"/"blocked" suggestion
state with no staged card, an open-loops count) controls it — those stay ambient.

**The visibility-critical overrides** keep the rail expanded even with zero
suggestions/proposals/receipts, because collapsing them into the ambient strip would *hide a state
the user must see*. This exception set is closed and enumerated — it is not "anything non-idle":

- WriteGuard `blocked` — a write was refused; the reason must be visible.
- Canvas `recovery_needed` / conflict — an unsaved-edit recovery or conflict prompt.
- A Panel that carries a human-facing message — a `blocked` state, a `no-match` reason, or any
  first-class visible Panel failure mapped into `panel_render.message`. (A non-empty Panel message
  is the trigger; transient no-message states such as `running`/`idle` stay ambient.)
- An actionable `reorient_sections` payload with real items (an orientation step the user can act
  on); an empty-section reorient payload stays ambient.
- A `populated` `commitments_surface` — the user's active next/waiting/review responsibilities,
  shown read-only (delivered commitment-surfacing contract). The `empty`/`not-shown`/`degraded`
  commitment states are confident-zero or availability cues, not content, and stay ambient.
- A non-empty Find or Resurface candidate payload (`find_candidates` / `resurface_candidates`) —
  shipped read-side content the user can act on (a result to open, a why-now candidate). An *empty*
  candidate list (find unavailable / resurface degraded) stays ambient; the trigger is non-empty
  results, not the section's mere presence.

The overrides exist because the ambient strip *collapses the rail header and body to a thin
presence cue* — any state rendered only inside that body would otherwise become invisible. They do
not relax the content rule for ordinary idle states; they are the exhaustive list of states whose
visibility is safety/clarity-critical. (This set was made binding by the Codex review of the spec
PR; collapsing any of them is a regression — see `tests/companion_ui/test_right_rail_compaction.py`.)

This is a **presentation-only** change. Which proposals, suggestions, receipts, messages, and guard
states exist is still declared by the runtime payload. The rail renders what it receives; it never
reclassifies or invents content.

## Concretely

**Idle = thin ambient strip.**
The eight sub-module cards (Canvas · Log · Find · Reorient · Resurface · Commitments and any
others) do not render in the idle shell. "Companion · idle — no active proposals." does not render
as a header. The strip is visually present — the user can see there is a companion surface — but
claims none of the reading width. The note column expands to fill the reclaimed space.

**Active = expands when a suggestion, proposal, or receipt exists.**
The moment the runtime payload includes any suggestion, proposal, or receipt, the rail transitions
to full active width and renders the relevant content. This expansion is immediate and
data-driven — it tracks the payload, not a local toggle or a user gesture. On the next payload
where the count returns to zero, the rail collapses back to ambient.

There is no intermediate or "loading" expanded state. The rail is either ambient (nothing to act
on) or active (something to act on). A receipt arriving after a governed Apply triggers active just
as a new proposal does — the receipt is content, not a decoration.

## Why This Matters

The review's J2 verdict (Axis B: Friction) and the cross-cutting Visual hierarchy finding
(Axis B: Broken) both identify the same root cause: the idle rail permanently consuming roughly a
third of the shell while displaying only "Companion · idle — no active proposals." Three regions
compete — topbar, document, rail — and the document does not win. The review's highest-leverage
change for J2 is verbatim: "Collapse the idle right rail to a thin ambient strip until it has
something to say, so the note is unambiguously the primary surface."

This task is also structural for the capability: the governed-receipt promotion (CUIDR-07) and the
lane-labelled proposal cards (CUIDR-08) both render into the rail's active state. They cannot ship
until this contract exists.

## Acceptance Criteria

**B1** — In the idle shell the right rail occupies a thin ambient strip (no permanently-reserved
empty third), and expands only when carrying a suggestion, proposal, or receipt; the note column is
the widest, highest-contrast region on screen.

- Verify: render the idle-shell fixture at 1280 px and 1440 px; inspect that the rail column width
  is ambient (thin strip) and the note column is the widest column. Render the same fixture with
  `panel_proposal_count >= 1` (or a non-empty `suggestions` or `receipts` field); confirm the rail
  expands to full active width.
  `tests/companion_ui/test_right_rail_compaction.py` — extend or add
  `test_idle_shell_rail_is_ambient_strip` and `test_active_payload_expands_rail`.

**Rail-active-contract AC** — An explicit, closed rule governs expand/collapse: the rail is active
if and only if the payload carries at least one suggestion, proposal, or receipt, **or** one of the
enumerated visibility-critical overrides is set (WriteGuard blocked, canvas recovery/conflict, a
Panel carrying a human-facing message, an actionable reorient with items, populated commitments, a
non-empty Find/Resurface candidate payload).
There is no state where
content — or a visibility-critical reason — exists but the rail renders ambient, and no ordinary
idle/capability state forces the rail active.

- Verify: parametrize over (suggestion present, proposal present, receipt present, all absent) and
  assert the rail's rendered state matches the content rule; separately assert each override keeps
  the rail active with no suggestion/proposal/receipt, and that non-content states
  (`thinking`/`blocked` suggestion with no card, open-loops count, idle Panel) stay ambient.
  `tests/companion_ui/test_right_rail_compaction.py` — `test_rail_active_contract_parametrized`,
  `test_safety_critical_states_stay_active_without_content`,
  `test_panel_blocked_state_keeps_rail_active`, `test_panel_no_match_state_keeps_rail_active`,
  `test_open_loops_cta_hidden_in_ambient_strip`.

## How to Verify (Pre-Merge)

1. **Static — idle shell at 1280/1440.**
   Render `render_index_html` with the default idle fields (zero proposals, zero suggestions, zero
   receipts). Assert the rail column carries the ambient CSS class / narrow width token and does not
   contain any of the idle sub-module card labels (Canvas, Log, Find, Reorient, Resurface,
   Commitments). Assert the note column is wider than the rail column.

2. **Static — active-payload expansion.**
   Render `render_index_html` with `panel_proposal_count=1` (or equivalent for suggestions/
   receipts). Assert the rail column carries the active CSS class / full width token.

3. **Static — receipt triggers active.**
   Render `render_index_html` with a non-empty receipt field and zero proposals/suggestions. Assert
   rail is active (receipt alone is sufficient; the rail must never be ambient when a receipt
   exists).

4. **Static — zero-content returns to ambient.**
   After asserting active for a non-empty payload, render the same fixture with all payload counts
   at zero and confirm the rail returns to ambient. No intermediate expanded state persists.

All four are static SSR assertions executable against `render_index_html` with no live runtime.
Live UAT (rail expansion visible during a session with an arriving proposal) is a post-merge
validation step, not a merge gate.

Key test files:
- `tests/companion_ui/test_right_rail_compaction.py` — extend with the new ACs above
- `tests/companion_ui/test_panel_rail_browser.py` — confirm no existing assertion depends on the
  idle rail being at full width (update if needed; a test asserting the old always-expanded
  behaviour is wrong after this task)

## Out of Scope

- Which proposals, suggestions, or receipts appear in the active rail — that is runtime payload;
  this task changes only the render width and sub-module visibility.
- The visual design of the active rail's content — governed-receipt card layout belongs to
  CUIDR-07; lane-labelled proposal cards to CUIDR-08.
- The ⌘K palette (O1) — its relationship to the rail is a Wave-3 owner decision (CUIDR-09,
  recommendation E2); do not alter the palette as part of this task.
- Sub-module removal from the codebase — collapse them visually in the idle state; their render
  paths may stay alive for the active state.
- Any telemetry or operator copy on the top edge — that is CUIDR-04 (Edge Job and Reachability).

## Related Docs

- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt` — B1,
  J2 highest-leverage change, 03 Visual hierarchy finding.
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/README.md` — capability overview, cross-task
  invariants (§ "The rail is the single host"), execution order (step 3).
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — shell layout contract; the note column as the primary
  surface.

## Related GitHub Issues

Maps to child issue [Companion UI Deep-Review] rail-ambient-until-active; Wave 1; agent:ready.
