---
name: Strategic — Cold-Start Cutoff and Rail/Palette Relationship
description: Owner-gated decisions on long-absence re-entry orientation and whether the rail and ⌘K palette present one coherent model or should eventually fold.
task_id: CUIDR-09
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 04 E1/E2
parent_capability: Companion UI Deep-Review Remediation
prerequisites: [CUIDR-03]
depends_on: [RAIL_AMBIENT_UNTIL_ACTIVE.md]
can_parallelize_with: []
---

# Strategic — Cold-Start Cutoff and Rail/Palette Relationship

## Purpose

Two strategic questions surface from the deep review that cannot be resolved by an implementer alone. Both affect the coherence of the interaction model at a level that leaks across multiple surfaces. This task frames each as an open owner decision, provides a recommended default, and defines the acceptance criteria that apply once the owner rules.

## What This Task Does

1. Frames the long-absence orientation problem (E1) — the cold_start cutoff routes the greatest re-entry need to the least orientation — and proposes options with consequences for the owner to decide.
2. Frames the rail-vs-palette relationship question (E2) — once the rail is calmed (CUIDR-03), whether two interception surfaces are still coherent or need to be collapsed — and proposes options with consequences.
3. Provides the acceptance criteria each decision must satisfy, so implementation can proceed immediately once the owner decides.

This task does **not** implement the chosen treatment. It is a holding spec for owner-gated decisions. Implementation follows in a child issue once the decisions are recorded.

## Open Decisions

### E1 — Long-absence re-entry orientation

> **Owner decision recorded 2026-06-23 (supersedes the options below).** The spec
> originally conflated two situations under `cold_start`; the owner split them and
> dropped the absence-age treatment. The decision, not the options, is the contract.

#### Problem

The `cold_start` entry state applies to both first-ever contact and any return after more than 14 days. The intent is correct: do not show a dashboard to someone who has been away for weeks. But the consequence is that the moment of greatest re-entry need — the long return — receives the least orientation, while a 1-day gap gets the full re-entry card. The REVIEW_RESPONSE (E2, J1) captures this directly:

> "Because cold_start claims everything >14 days, the moment of greatest re-entry need — weeks away — receives the least orientation, while a one-day gap gets the full card."

The existing test suite confirms this shape: the cold_start treatment renders no re-entry card and no orientation panels. This is correct for first contact. It may not be correct for a long return.

#### Decision (owner, 2026-06-23)

Two situations were conflated under `cold_start`; they are now separate:

1. **Returning user (vault already selected, away a while).** Offer a gentle _"resume the thread?"_ pickup affordance. **There is no "last here N days ago" count and no `absence_age_days` field** — absence duration is irrelevant to the surface and there is **no client-side math, threshold, or age rendering**. The resume line is gated solely on a **server-declared resumable thread being present** in the orientation payload — specifically the already-produced `orientation.recents_anchor` field on `WorkspaceOrientationResponse` (its presence ⇒ there is a recent thread to resume). When the runtime declares `recents_anchor`, the UI renders the calm line; when it does not, the UI renders nothing extra. The UI computes nothing — the server-authoritative boundary holds.

2. **First contact is NOT a calm-minimal `cold_start` greeting — it is the `no_vault` state.** With no vault selected the entry surface is the **vault picker**: a gentle choice between (a) initiate a new vault and (b) browse to an existing vault. Only after a vault is selected does the system bootstrap the vault-dependent subsystems. This is the `no_vault` entry state, owned by the vault picker (**E11 / #2448**, already merged) — distinct from the returning-user resume line, and it must not be folded into a cold_start calm line. See `FRONT_DOOR_AND_COPY_HYGIENE.md` and #2448.

**Server-authoritative boundary unchanged:** the UI renders runtime-declared entry/vault/session state; it computes nothing. No `absence_age_days`, no day rendering, no new runtime age field.

#### Superseded options (historical)

The original framing offered: **Option A** — a "Last here N days ago — resume the thread?" line gated on a runtime `absence_age_days`; **Option B** — keep cold_start identical for all durations. The owner adopted a *modified Option A*: keep the gentle resume affordance but **drop the day-count and `absence_age_days` entirely**, gate it on a server-declared resumable thread (the already-produced `orientation.recents_anchor` field) instead, and split first-contact out to the `no_vault` vault picker. Both original options are retained here only for provenance.

---

### E2 — Rail-vs-palette relationship

#### Problem

After the rail is calmed (CUIDR-03), two surfaces still act as proposal-presentation layers: the right rail and the ⌘K command palette. The REVIEW_RESPONSE (J5, E2) notes:

> "The duplication with the rail is acceptable once the rail is calmed; today both exist and the rail is the noisier path, so it reads as a fork to learn rather than a shortcut."

The existing tests confirm both surfaces exist and are deliberately distinct: `tests/companion_ui/test_panel_command_palette.py` describes the palette as "a presentation of Panel, not new authority" and verifies it renders the same server-declared proposal set as the rail. `tests/companion_ui/test_right_rail_compaction.py` verifies the rail collapses when idle. Once CUIDR-03 ships, the rail will be ambient; the question is whether the two surfaces still form one coherent model or remain a fork.

#### Options

**Option A — Keep both surfaces; confirm their roles explicitly (recommended default)**
The ⌘K palette is the fast path: keyboard-first, full-screen, dismiss-when-done. The right rail is the ambient path: always-present when active, peripheral when idle. They share the same proposal set (server-declared). Document the model explicitly in the shell spec and reflect it in the surface labels and keyboard affordances. Revisit folding only if the two surfaces still feel like a fork after the rail is calm.

**Option B — Fold the palette into the rail (or the rail into the palette)**
Remove one surface. Route all proposal interaction through a single host. Simpler model, fewer surfaces to maintain. Risk: the keyboard-fast-path and the ambient-peripheral-path serve different interaction modes; collapsing them may degrade one or both.

**Option C — Keep both but gate the palette behind a feature flag until the rail is calm**
No change today; defer the coherence question until CUIDR-03 ships and the model can be evaluated in context.

#### Consequence

| | Option A | Option B | Option C |
|---|---|---|---|
| Interaction model clarity | Two roles, one model; explicit | One surface, one model; simpler | Deferred; no clarity now |
| Keyboard affordance | ⌘K preserved as fast path | Must be rebuilt in single surface | Preserved unchanged |
| Implementation cost | Documentation + label changes only | Significant refactor | None |
| Risk | None if rail calm lands first | Degrades one interaction mode | Defers but does not close the question |

#### Recommended default

Option A. Keep both surfaces; confirm their roles in words. Palette = fast path. Rail = ambient. The only action required now is documenting the model and ensuring the shell reflects it. Revisit folding only after CUIDR-03 ships and both surfaces can be evaluated together.

---

## Concretely

E1 (owner decision applied):
- Render a single calm _"resume the thread?"_ line on the returning-user entry surface, gated **only** on a server-declared resumable thread being present in the orientation payload (the already-produced `orientation.recents_anchor` field). No `absence_age_days`, no "N days ago" count, no client-side threshold or age math, no new runtime field — this slice adds the UI consumer and gates on the field the runtime already produces. When the field is absent, no line renders. The line carries the existing `entry.resume` intent and routes to the server-declared resume target (`recents_anchor.note_path`). The prominent E1 line **supersedes** the quieter "Open your most recent note" recents-anchor link — both derive from `recents_anchor`, so exactly one calm resume affordance renders.
- First contact / no vault is the `no_vault` vault picker (E11 / #2448), not a cold_start branch — no cold_start first-contact resume line and no dashboard.
- Tests in `tests/companion_ui/test_reentry_orientation_treatment.py`: returning fixture **with** a resumable session → the calm resume line renders and no orientation panels / governance tiles / re-entry card appear; returning fixture **without** a resumable session → no resume line.

E2 (owner decision = Option A, applied):
- Name the two roles explicitly in the shell: the ⌘K palette is the keyboard-first **fast path**; the right rail is the **ambient** path. Both present the same server-declared proposal set; neither invents authority. No structural change — the palette stays a presentation of the rail (`data-presentation-of="panel-rail"`) and the rail keeps its safety-critical expansion behaviour.
- Concretely: the rail aside and the palette root each carry an explicit `data-surface-role` (`ambient` / `fast-path`) plus a visible role label. Test: `tests/companion_ui/test_panel_command_palette.py::test_rail_palette_single_model`.
- E2 was sequenced after #2446 (rail calmed), which is merged.

## Why This Matters

Both questions are about coherence of the interaction model, not surface polish. Getting them wrong compounds across sessions: a returner who finds no anchor after 21 days loses trust in the system's awareness of them. A user who cannot tell whether the rail and palette are the same thing or different things cannot develop a reliable mental model. Both failures are invisible in a single session and accumulate over time.

## Acceptance Criteria

**The owner decided both questions on 2026-06-23. The criteria below reflect the recorded decision.**

**E1-AC1 (resume affordance, gated on a resumable thread):** A returning user (vault selected) whose orientation payload declares a resumable thread (`recents_anchor`) renders a single calm "resume the thread?" line, with no dashboard, no orientation panels, no governance tiles, and no re-entry card. The prominent line supersedes the quieter recents-anchor link (both derive from the same field).
- Verify: render the returning-user fixture **with** a server-declared `recents_anchor`. Assert the calm resume line renders and carries the `entry.resume` intent, and that the quieter `cold-start-recents-anchor` link does not also render. Assert no `data-region="orientation-panel"`, no governance tiles (`data-testid="workspace-orientation-governance"`), and no `data-region="reentry-card"` render.
- New test: `tests/companion_ui/test_reentry_orientation_treatment.py::test_returning_with_resumable_anchor_renders_resume_line`

**E1-AC2 (server-authoritative gate, no age math):** The resume line renders **only** when the runtime declares a resumable thread (`recents_anchor`). The UI computes nothing — no absence-age, no threshold, no day-count, no `absence_age_days` field. With no `recents_anchor` declared, no resume line renders.
- Verify: render the same returning-user fixture **without** a `recents_anchor`. Assert no resume line renders.
- New test: `tests/companion_ui/test_reentry_orientation_treatment.py::test_returning_without_resumable_anchor_renders_no_resume_line`

**E1-AC3 (first contact is no_vault):** First contact is the `no_vault` vault picker (#2448), not a cold_start calm-greeting branch. No first-contact resume line and no dashboard are introduced by this task.

**E2-AC1 (one model, explicit roles):** The rail and ⌘K palette present ONE coherent model with explicit roles: the palette is labeled the **fast path** and the rail the **ambient** path; no proposal datum is invented by either surface beyond what the server declares. No structural refactor.
- Verify (static): inspect `test_panel_command_palette.py::test_palette_renders_same_proposals_as_rail` — it must continue to pass. Inspect shell render for explicit role labels on both surfaces.
- Verify (live): confirm that ⌘K opens the palette and dismisses cleanly, and that the rail does not duplicate the palette's affordances in an active proposal state.

## How to Verify (Pre-Merge)

1. **Static — E1:** Render the returning-user fixture with and without a server-declared `recents_anchor`. Assert the calm resume line appears only in the presence case and that no dashboard / orientation panels / re-entry card appear in either.
2. **Static — E2:** Run `test_panel_command_palette.py` and `test_right_rail_compaction.py` in full. Confirm both pass without behavioral change. Inspect the rendered shell for explicit role labels (rail=ambient, palette=fast-path).
3. **Live — E1:** Simulate a returning login with a `recents_anchor` in the test environment and confirm the calm line renders and Resume routes correctly.
4. **Live — E2:** Open ⌘K, confirm it shows the same proposals as the rail. Dismiss. Confirm rail returns to ambient posture.

## Out of Scope

- Client-side computation of any absence age, cutoff, or threshold — server-authoritative, always. No `absence_age_days`, no day-count rendering.
- First-contact / no-vault rendering — owned by the `no_vault` vault picker (#2448), not this task.
- Any dashboard or orientation panel for long returns — the anti-dashboard posture is non-negotiable.
- Merging the governed and body-edit agent lanes — that is CUIDR-05 (C2).
- Rail compaction layout — that is CUIDR-03 (B1).
- Palette structural refactor if Option B is chosen — that requires a separate scoped issue.

## Related Docs

- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/RAIL_AMBIENT_UNTIL_ACTIVE.md` — prerequisite; this task's E2 question is only meaningful after the rail is calm
- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt` — sections J1, J4, J5, 04 E1/E2
- `tests/companion_ui/test_entry_state_gallery.py` — cold_start and mist-rung fixture coverage
- `tests/companion_ui/test_reentry_orientation_treatment.py` — orientation treatment assertions; new tests land here
- `tests/companion_ui/test_panel_command_palette.py` — palette presentation contract
- `tests/companion_ui/test_right_rail_compaction.py` — rail idle/active posture contract

## Related GitHub Issues

Maps to child issue #2453 [Companion UI Deep-Review] strategic-coldstart-and-rail-palette. Both owner decisions are now recorded (2026-06-23) and applied: E1 = resume line gated on a server-declared resumable session (no absence-age math; first contact = the `no_vault` vault picker, #2448); E2 = Option A explicit role labels (rail=ambient, palette=fast-path), no refactor.
