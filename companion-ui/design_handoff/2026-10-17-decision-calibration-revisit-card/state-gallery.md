# State gallery

The server declares each state and the card renders it. The static renders are in `prototype.html` under "State gallery". There are **13 renders**: 11 state renders covering all 8 design-side enum values (including 4 `write_failed` variants), plus 2 narrow-width renders. The live harness drives the same render function.

| # | `data-state` | Variant attrs | Badge | Controls | Visible copy (key lines) | SR announcement (live harness) |
|---|---|---|---|---|---|---|
| 01 | `pending` | — | Pending (default) | Note, 4 picks, Dismiss for now | Question · "Decided 2026-06-23 · 14-day rung · decision 8f2e…" | — |
| 02 | `submitting_answer` | `aria-busy` | Recording (cyan) | All `aria-disabled`; chosen pick keeps label + accent border + "· recording"; note readonly | "Recording Partly held. Other picks are unavailable until the server responds." | polite: "Recording outcome: Partly held." |
| 03 | `answered` | `data-outcome` | Recorded (vault) | None | "Outcome recorded: Partly held." · "This rung is closed. It cannot be edited or re-answered." | polite; focus → question heading |
| 04 | `submitting_dismiss` | `aria-busy` | Deferring (cyan) | All `aria-disabled`; button reads "Deferring…" | "Deferring this revisit. No outcome will be recorded." | polite |
| 05 | `dismissed` | — | Deferred (default) | None | "Revisit deferred. No outcome recorded." | polite; focus → question heading |
| 06 | `write_failed` | `data-intent=answer` `data-failure=failed` | Not recorded | Re-enabled; note preserved | "Answer not recorded. The write failed." · "Nothing durable happened. The revisit is still pending." | assertive; focus stays on the pressed pick |
| 07 | `write_failed` | `data-intent=answer` `data-failure=blocked` | Blocked | Re-enabled | "Answer blocked by the write guard." · same second line | assertive |
| 08 | `write_failed` | `data-intent=dismiss` `data-failure=failed` | Not deferred | Re-enabled | "Dismissal not recorded." · same second line | assertive; focus stays on Dismiss |
| 09 | `write_failed` | `data-intent=dismiss` `data-failure=blocked` | Blocked | Re-enabled | "Dismissal blocked." · same second line | assertive; focus stays on Dismiss |
| 10 | `degraded` | `data-degraded=true` | Unavailable (amber) | None | "Calibration revisits unavailable." · "Revisit state could not be read. Pending revisits are unknown, not zero." | — |
| 11 | `absent` | — | — | None | "No revisit due." (quiet: smaller padding, `--fg-2`, no badge) | polite after re-read |
| 12 | `pending` @ 360px | — | — | — | Picks wrap to 2×2 | — |
| 13 | `submitting_answer` @ 360px | — | — | — | Chosen "Did not hold" keeps its label | — |

The variants in 06–09 are attributes on the failure panel (`.cal-alert[data-intent][data-failure]`). They are not separate enum values. Degraded (10) and absent (11) share no wording.

## Verification table

**Authored acceptance assertions** are what the design requires. Independent execution evidence goes in the last two columns. The designer has **not** run browser or assistive-technology checks for this table, so every evidence cell is blank and waits for the independent reviewer.

| # | Check | How to run | Acceptance assertion (authored) | Result | Evidence / reviewer |
|---|---|---|---|---|---|
| V1 | Desktop | Harness → Width: Desktop, ≥1280px window | Card ≤42rem; 4 picks in one row; dismiss below divider, visibly ghost | | |
| V2 | Narrow 360 | Harness → Narrow 360; gallery 12–13; or a 360px viewport | Picks 2×2; no horizontal scroll; long title wraps; badge wraps under eyebrow | | |
| V3 | 200% zoom | Browser zoom 200% on a 1280px window | Layout remains usable and may reflow as space requires; no clipped or overlapping text; no horizontal page scroll; WCAG 1.4.10 reflow. | | |
| V4 | Keyboard order + focus | Tab from page top into the live card | Order: Note → Held → Partly held → Did not hold → Not sure yet → Dismiss for now. 2px `--border-focus` ring on each. Enter/Space activates. During submit, activation is ignored and focus is kept. After answered/dismissed, focus is on the heading with a visible ring. After failure, focus is on the pressed control. | | |
| V5 | Screen-reader names | VoiceOver + Safari and NVDA + Firefox | Buttons are announced as "Held", "Partly held", "Did not hold", "Not sure yet" inside group "Did it hold?", with description "A pick records the outcome…". "Dismiss for now" is outside the group, with description "Defers this revisit. Records no outcome." No two controls share a name. | | |
| V6 | Optional note | AT + inspect | Label "Note (optional)"; no `required`/`aria-required`; hint "Not required. Sent only with an outcome." Picks submit with an empty note; `note` is omitted from the body (see mock log). | | |
| V7 | Print | Print preview of `prototype.html` | No buttons, textarea, or harness. Ink is `--fg-inverse` on paper with `--border-strong` rules. Pending cards read "Outcome pending." Cards do not split across pages. | | |
| V8 | JavaScript off | Disable JS, reload | `<noscript>` card renders with two native forms: answer → `/decision` with `outcome`+`note`; dismiss → `/dismiss` with no fields. | | |
| V9 | Reduced motion | OS reduce-motion on | All transitions are 0ms through the sheet; nothing animates. | | |
| V10 | Degraded vs absent | Harness → Degraded, then None; gallery 10–11 | Degraded: amber "Unavailable", "unknown, not zero", no controls. Absent: quiet "No revisit due.", no badge. No shared wording. | | |
| V11 | Blocked / write failure | Harness → Next write result: Write failed, then Blocked; try both an answer and a dismiss; gallery 06–09 | Card stays present; alert says "Nothing durable happened. The revisit is still pending."; controls re-enabled; note preserved; announced assertively; never shows Recorded or Deferred | | |
| V12 | No egress | Open DevTools / CDP Network on `prototype.html` | 0 cross-origin requests; only same-origin `prototype.html` + `tokens/colors_and_type.no-egress.css` | Observed: 0 cross-origin, same-origin localhost only | Browser CDP receipt (see README) |
