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

## Resolution (owner decisions recorded 2026-06-23, #2453)

- **E2 — Option A, DELIVERED.** Keep both surfaces with explicit roles: the ⌘K palette is the keyboard-first **fast path** (`data-surface-role="fast-path"`); the right rail is the **ambient** path (`data-surface-role="ambient"`). Same server-declared proposal set; the palette stays a presentation of the rail (`data-presentation-of="panel-rail"`); no structural refactor. The role model is documented in the canonical shell spec (`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` — Surface composition palette row + the `data-surface-role` data-attribute entry). Shipped in this slice (#2453); see `tests/companion_ui/test_panel_command_palette.py::test_rail_palette_single_model`.
- **E1 — RESOLVED: keep the existing recency anchor (no durable continuity signal).** A true "resume the thread?" affordance is **architecturally impossible on the long-absence cold surface by design**: the only continuity pointer (`orientation.leave_point`) is TTL-capped at **7 days** (`app/orientation/leave_point_cursor.py` `MAX_TTL`; ADR-0008 scopes it as bounded operational trace, *not* restart-surviving continuity), while `cold_start` requires a **>14-day** gap — so a present leave_point never coincides with `cold_start`. `recents_anchor` is a Find/recency projection, not a continuity claim, and must not drive `entry.resume`. The owner (2026-06-23) **accepted the existing `recents.open` "Open your most recent note" link as E1's calm long-return anchor** — no durable continuity signal, no ADR-0008 amendment, no dashboard; the system keeps its deliberate forget-fast posture. The deep-review E1/J1 finding is addressed by this existing honest anchor. (The follow-up issue #2472, which had proposed commissioning a durable signal, is closed by this decision.) The original E1 framing below (absence-age / `absence_age_days` / a new resume affordance) is superseded and retained only for provenance.

## Open Decisions

### E1 — Long-absence re-entry orientation

> **⛔ ARCHIVED — PROVENANCE ONLY. DO NOT IMPLEMENT.** This E1 sub-section (Problem → Options → Consequence → Recommended default → the `## Concretely` E1 bullet → E1-AC1/E1-AC2 below) describes the original absence-age / `absence_age_days` / `long_absence_calm_line` proposal, which the owner **rejected** on 2026-06-23. See **§Resolution** above: E1 is resolved as the existing `recents.open` "Open your most recent note" anchor — no `absence_age_days`, no resume-line branch, no new test. A docs-to-issue/governance run must **not** pick up any task text in this sub-section. Retained only to record what was considered.

#### Problem

The `cold_start` entry state applies to both first-ever contact and any return after more than 14 days. The intent is correct: do not show a dashboard to someone who has been away for weeks. But the consequence is that the moment of greatest re-entry need — the 21-day return — receives the least orientation of any gap, while a 1-day gap gets the full re-entry card. The REVIEW_RESPONSE (E2, J1) captures this directly:

> "Because cold_start claims everything >14 days, the moment of greatest re-entry need — weeks away — receives the least orientation, while a one-day gap gets the full card."

The existing test suite confirms this shape: `test_entry_state_gallery.py` lines 481–505 exercise `cold_start` fixtures; the cold_start treatment renders no re-entry card and no orientation panels. This is correct for first contact. It may not be correct for a 21-day return.

#### Options

**Option A — Add one calm orientation line for long returns (recommended default)**
When the runtime declares `entry_state=cold_start` with an `absence_age` above the cold_start threshold (e.g. >14 days), render a single calm line in the entry surface: _"Last here N days ago — resume the thread?"_ with a Resume affordance. No panels. No card. No dashboard. The runtime declares both the rung and the age; the UI renders the line only when the runtime provides an age value. This is a presentation-only addition: the UI does not compute the cutoff or classify the gap client-side.

**Option B — Keep the current cold_start treatment identical for all durations**
First contact and a 21-day return remain visually identical. Accept the orientation gap as a deliberate trade-off in favour of the anti-dashboard posture. The review finding is acknowledged but not acted on.

#### Consequence

| | Option A | Option B |
|---|---|---|
| Re-entry orientation | Long returner gets one calm anchor | Long returner and first-timer are identical |
| Anti-dashboard posture | Preserved — one line, no tiles, no panels | Fully preserved |
| Server authority | Preserved — UI renders runtime-declared age and rung | Preserved |
| Implementation cost | One new rendering branch + one new fixture + one new test | No change |
| Risk | Adds a branch that could drift from the mist ladder if not tested | None |

#### Recommended default

Option A. One calm "last here N days ago — resume the thread?" line for long returns, with no dashboard introduction. The constraint is non-negotiable: the absence-age classification stays server-authoritative. The UI renders the runtime-declared age; it does not compute the cutoff.

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

**E1 — ⛔ SUPERSEDED (provenance only; see §Resolution). Do NOT implement the bullet below.** E1 is resolved as the existing `recents.open` anchor; there is no `long_absence_calm_line`, no `absence_age_days`, and no new test.
- ~~If Option A: add a `long_absence_calm_line` rendering branch. The runtime must supply `absence_age_days` on a `cold_start` response. The UI renders "Last here {N} days ago — resume the thread?" only when `absence_age_days` is present. No client-side threshold computation. New test: `test_cold_start_long_absence_renders_calm_resume_line` in `tests/companion_ui/test_reentry_orientation_treatment.py`.~~
- ~~If Option B: no implementation change; close the E1 branch as won't-fix-by-design.~~

Once the owner decides on E2:
- If Option A: update the shell spec to name the two roles explicitly; audit the rail and palette labels to ensure they reflect the model; no structural change.
- If Option B: scoped refactor; requires a separate implementation issue.
- If Option C: no action now; re-open after CUIDR-03.

## Why This Matters

Both questions are about coherence of the interaction model, not surface polish. Getting them wrong compounds across sessions: a returner who finds no anchor after 21 days loses trust in the system's awareness of them. A user who cannot tell whether the rail and palette are the same thing or different things cannot develop a reliable mental model. Both failures are invisible in a single session and accumulate over time.

## Acceptance Criteria

**This task is owner-gated. The criteria below are conditional on the owner's decisions.**

**E1-AC1 / E1-AC2 — ⛔ SUPERSEDED (provenance only; see §Resolution). Not acceptance criteria for any open work.** E1 is resolved as the existing `recents.open` anchor; the absence-age criteria below are retained only to record what was originally proposed and rejected. No agent should treat them as executable.

~~**E1-AC1 (conditional on decision):** Once the owner picks the long-absence treatment, a long return (> the cold_start cutoff, runtime-declared `absence_age_days` present) renders the chosen calm orientation without introducing a dashboard. Under the recommended default (Option A), a single "last here N days ago — resume the thread?" line appears and no orientation panels, governance tiles, or re-entry card are shown.~~
- ~~Verify: render the long-absence `cold_start` fixture with `absence_age_days` set. Assert `data-entry-state="cold_start"` and the calm resume line are present. Assert no `data-region="orientation-panel"`, no governance tiles, and no re-entry card render.~~
- ~~New test: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_long_absence_renders_calm_resume_line`~~

~~**E1-AC2:** The cutoff and absence-age classification remain server-authoritative. The UI does not compute whether a gap crosses the cold_start threshold. The test suite must assert that the calm line renders only when the runtime supplies `absence_age_days`, not when it is absent.~~
- ~~Verify: render the same `cold_start` fixture without `absence_age_days`. Assert no calm resume line renders.~~
- ~~New test: `tests/companion_ui/test_reentry_orientation_treatment.py::test_cold_start_without_age_renders_no_resume_line`~~

**E2-AC1 (conditional on decision):** Once the owner decides, the rail and ⌘K palette present ONE coherent model. Under the recommended default (Option A), the palette is documented and labeled as the fast path and the rail as the ambient path; no proposal datum is invented by either surface beyond what the server declares.
- Verify (static): inspect `test_panel_command_palette.py::test_palette_renders_same_proposals_as_rail` — it must continue to pass. Inspect shell render for explicit role labels on both surfaces.
- Verify (live): confirm that ⌘K opens the palette and dismisses cleanly, and that the rail does not duplicate the palette's affordances in an active proposal state.

## How to Verify (Pre-Merge)

1. ~~**Static — E1 (Option A):** Render `cold_start` fixtures with and without `absence_age_days`…~~ **⛔ SUPERSEDED (provenance only; see §Resolution).** E1 is resolved as the existing `recents.open` anchor — there is no `absence_age_days` / calm-line branch to verify. The relevant invariant is simply that the long-absence `cold_start` surface renders **no** `entry.resume` continuity affordance (covered by `test_entry_state_gallery.py` / `test_reentry_orientation_treatment.py`).
2. **Static — E2 (Option A):** Run `test_panel_command_palette.py` and `test_right_rail_compaction.py` in full. Confirm both pass without modification. Inspect rendered shell for explicit role labels (`data-surface-role` on palette + rail).
3. ~~**Live — E1:** Simulate a long-absence login…~~ **⛔ SUPERSEDED (provenance only; see §Resolution).** No E1 resume affordance to exercise.
4. **Live — E2:** Open ⌘K, confirm it shows the same proposals as the rail. Dismiss. Confirm rail returns to ambient posture.

## Out of Scope

- Client-side computation of the cold_start threshold or absence age — server-authoritative, always.
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

Maps to child issue #2453 [Companion UI Deep-Review] strategic-coldstart-and-rail-palette; Wave 3. Both owner decisions are **resolved** (2026-06-23, see §Resolution): E1 = keep the existing `recents.open` anchor (no durable continuity signal; #2472 closed not-planned); E2 = Option A explicit role labels (delivered). No open owner decision remains.
