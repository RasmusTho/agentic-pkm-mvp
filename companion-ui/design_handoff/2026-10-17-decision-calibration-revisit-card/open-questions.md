# Open questions — triaged

Categories (governance only):
- **resolve-before-promotion**: must be closed before Crossing-B promotion.
- **resolve-in-normalized-spec**: owner of `docs/DECISION_CALIBRATION/SURFACE_REVISIT_REVIEW_CARD.md` confirms; the design applies a conservative default meanwhile.
- **defer-to-implementation-issue**: tracked as follow-up work (design system or implementation); it does not affect this card's contract.

**No resolve-before-promotion item remains after these fixes.** The former mechanical gate (verify token hash and egress) is closed by the receipt in `README.md`.

| Q | Category | Topic |
|---|---|---|
| Q1 | defer-to-implementation-issue | Token sheet `@import` vs no-egress |
| Q2 | defer-to-implementation-issue | Preview cards conflict with README rules |
| Q3 | defer-to-implementation-issue | Button radius inconsistency |
| Q4 | resolve-in-normalized-spec | Duplicate submit with JavaScript off |
| Q5 | resolve-in-normalized-spec | Answered label source |
| Q6 | resolve-in-normalized-spec | Degraded projection with fields present |
| Q7 | resolve-in-normalized-spec | Blocked vs failed distinction |
| Q8 | defer-to-implementation-issue | Glow while submitting |
| Q9 | resolve-in-normalized-spec | What follows answered/dismissed |
| Q10 | resolve-in-normalized-spec | Note placement above picks |
| Q11 | defer-to-implementation-issue | Print roles (proposed extension) |
| Q12 | defer-to-implementation-issue | Coarse-pointer control height (proposed extension) |
| Q13 | defer-to-implementation-issue | Fonts-free sheet build (proposed extension) |

### Conflicts found (sheet wins)
**Q1 · Token sheet @import vs no-egress. defer-to-implementation-issue.** The binding sheet `@import`s Google Fonts, and the brief forbids egress. Applied: the prototype links `tokens/colors_and_type.no-egress.css`, which is identical except that this one line is replaced by a 3-line local-font comment (verified, see README). Fonts fall back to the sheet's own local stacks. Follow-up for the design-system maintainer: emit a fonts-free variant from `build.py`.

**Q2 · Preview cards vs README rules. defer-to-implementation-issue.** The Buttons, Badges, and Inputs previews use resting glows, raw `rgba()`, readable `--fg-3` labels and hints, and an accent focus border with `outline:none`. README/SKILL ("glow is a state", no readable `--fg-3`) and the sheet's `[data-focus="v2"]` rule win. The prototype drops resting glow, uses `--fg-2`, and keeps the sheet focus ring. No visual was stopped, because the sheet itself does not conflict. Follow-up: refresh the previews.

**Q3 · Button radius inconsistency. defer-to-implementation-issue.** The Buttons preview uses `--radius-md` and the Focus preview uses `--radius-sm`. The prototype follows Buttons (`--radius-md`). Follow-up: the design system states one canonical button radius.

### Behaviour (conservative defaults applied)
**Q4 · Duplicate submit with JavaScript off. resolve-in-normalized-spec.** The card prevents duplicates only with JavaScript. The design assumes the CAL-01 route is idempotent per `decision_id` + rung, or rejects a second answer. That is runtime truth, not design.

**Q5 · Answered label source. resolve-in-normalized-spec.** "Outcome recorded: {label}" renders from the route's 2xx response. If CAL-01 does not echo `outcome`, render "Outcome recorded." without the label. That is never inferred from the click.

**Q6 · Degraded projection with fields present. resolve-in-normalized-spec.** Default: when `degraded: true`, show no answer or dismiss controls even if title and date are present. This does not widen the contract.

**Q7 · Blocked vs failed distinction. resolve-in-normalized-spec.** The card shows "blocked" only when the server returns a distinguishable guard response. Otherwise it shows the generic "not recorded" / "not deferred". The status codes 409 and 503 in the mock are illustrative only. This applies to both intents (gallery 07 and 09).

**Q8 · Glow while submitting. defer-to-implementation-issue.** No glow is used. `.fx-glow-cyan` on the in-flight pick would be allowed as "the one active element", but the calm review-prompt brief argues against it. Revisit only if implementation review asks for it.

**Q9 · What follows answered or dismissed. resolve-in-normalized-spec.** The card re-reads and renders whatever the server returns: the next revisit, `absent`, or `degraded`. The mock returns `absent`.

**Q10 · Note placement above picks. resolve-in-normalized-spec.** This is required because picks submit immediately. Confirm the spec does not require a two-step choose-then-confirm. Adding one would widen the contract, so it is not proposed.

### Proposed extensions (not used in the prototype)
**Q11 · Print roles. defer-to-implementation-issue.** The system has no print tokens. The prototype maps print text to `--fg-inverse` and borders to `--border-strong`, which are existing roles reinterpreted for paper. Proposal: generator-emitted `@media print` role overrides.

**Q12 · Coarse-pointer control height. defer-to-implementation-issue.** `--control-height` is 36px at comfortable density. That passes WCAG 2.5.8 (24px) but sits below the 44px touch guideline. Proposal: a `pointer: coarse` density override in the sheet. The prototype stays at `--control-height`.

**Q13 · Fonts-free sheet build. defer-to-implementation-issue.** See Q1.
