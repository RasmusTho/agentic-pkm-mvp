# CAL-03 — Decision calibration revisit card · design handoff

Visual and interaction guidance only. It does not change owner docs, runtime contracts, shipped components, or production authority.

## Surface
- Product: Yggdrasil Companion UI, workspace view. One bounded card.
- Issue `#3324`, task `CAL-03`. Bounding authority: `docs/DECISION_CALIBRATION/SURFACE_REVISIT_REVIEW_CARD.md` and issue `#3324`. This package does not widen either.
- Input: read-only `WorkspaceStateResponse.calibration_revisit` (`decision_id`, `title`, `decided_on`, `rung_days`, `degraded`).
- Question: "You decided {title} on {decided_on} — did it hold?"
- Answer: `POST /companion/calibration/revisits/{decision_id}/decision` `{outcome, note?}` → existing CAL-01 append path, WriteGuard at route call site.
- Dismiss: `POST /companion/calibration/revisits/{decision_id}/dismiss` → CAL-02 dismissal ledger only. Never an outcome receipt.

## Authority state
Design guidance. Not normalized spec, not runtime truth. See `authority-boundaries.md`.

## Project / output identity
- Project URL: https://claude.ai/design/p/e07ff019-f51e-40ab-89f3-438bf5ea95cc
- Project ID: `e07ff019-f51e-40ab-89f3-438bf5ea95cc`
- Current title: `CAL-03 Decision calibration card`
- This is a new project, separate from the canonical design-system project (`f2b13410-af14-4875-8029-445352123f57`), which was not modified.
- Version: `cal-03-revisit-card / v2` (review-findings revision), 2026-10-17.
- Files: `README.md`, `prototype.html`, `design-notes.md`, `state-gallery.md`, `implementation-contracts.md`, `authority-boundaries.md`, `open-questions.md`, `tokens/colors_and_type.css`, `tokens/colors_and_type.no-egress.css`, `verify.html`.

## Live design-system receipt
- Name: `Yggdrasil Design System`, v2.2.1
- ID: `f2b13410-af14-4875-8029-445352123f57`
- Selection: selected at project creation from the live Yggdrasil Design System
- Binding token source: repo `companion-ui/companion-app/colors_and_type.css`
- Read: `README.md`, `SKILL.md`, `colors_and_type.css`, `ui_kits/companion-ui/index.html`, `preview/components-buttons.html`, `preview/components-cards.html`, `preview/components-inputs.html`, `preview/effects-focus.html`, `preview/components-badges.html`.
- Not loaded: `_ds_bundle.js`. The DS README states there is no importable component library, and the bundle requires CDN React, which would break no-egress.

## Token parity and egress — verification receipt
| Item | Result |
|---|---|
| `tokens/colors_and_type.css` (archived exact copy) | SHA-256 `edbc81c77209b5274b26b5e827191f95595f20d6bc5a97a17f7dd8751a774ba2`, matched repo `origin/main` exactly |
| `tokens/colors_and_type.no-egress.css` (linked by the prototype) | Differs from the exact copy only by replacing the single Google Fonts `@import` line with the 3-line local-font comment. All tokens, selectors, and values are identical. |
| Egress | Browser CDP observed only same-origin localhost resources, with **0 cross-origin requests** |

Font stacks resolve locally (`'EB Garamond', Georgia, serif` / `'Space Grotesk', system-ui, sans-serif` / `'JetBrains Mono', …, monospace`), so the token-role structure stays intact.

**Re-running locally:** serve the package folder over http and open `verify.html`. It hashes the archived exact copy `tokens/colors_and_type.css` against the declared SHA-256, and diffs the no-egress copy to confirm the only change is the `@import` → 3-line comment swap. It also lists the prototype's loaded resources with a cross-origin count (Resource Timing; CDP remains the authoritative egress evidence). Exported packages do not include the `_ds/` bound path, and the verifier reports it as "not present in this package (not required)" rather than failing.

## Prototype
`prototype.html` has an interactive card on a mocked server, plus **13 static renders**: 11 state renders covering all 8 design-side enum values, with 4 `write_failed` variants (answer/dismiss × failed/blocked), and 2 narrow 360px renders. See `state-gallery.md`.

## Verification — signoff table
Two kinds of evidence are kept apart:
- **Authored acceptance assertions** state what the design requires. The designer wrote them and has **not** executed browser or AT checks against them.
- **Independent execution evidence** comes from the reviewer who runs the checks. Only V12 has execution evidence so far (the CDP egress receipt above).

| # | Check | Authored assertion (summary) | Independent result |
|---|---|---|---|
| V1 | Desktop | 4 picks in one row; card ≤42rem; dismiss visibly ghost below divider | pending reviewer |
| V2 | Narrow 360 | Picks 2×2; no horizontal scroll; title wraps | pending reviewer |
| V3 | 200% zoom | Reflow without clipping or overlap (WCAG 1.4.10) | pending reviewer |
| V4 | Keyboard order + focus | Note → 4 picks → Dismiss; v2 ring visible; focus kept during submit and failure; heading focus after resolve | pending reviewer |
| V5 | Screen-reader names | Four distinct outcome names in group "Did it hold?"; "Dismiss for now" outside the group with its deferral description | pending reviewer |
| V6 | Optional note | "Note (optional)", not required; empty note omitted from body | pending reviewer |
| V7 | Print | No controls; `--fg-inverse` ink; "Outcome pending." | pending reviewer |
| V8 | JavaScript off | `<noscript>` card with two native forms on separate routes | pending reviewer |
| V9 | Reduced motion | All durations 0 through the sheet | pending reviewer |
| V10 | Degraded vs absent | Distinct copy and treatment; degraded never implies zero | pending reviewer |
| V11 | Blocked / write failure | Card stays; "Nothing durable happened"; both intents, both kinds | pending reviewer |
| V12 | No egress | 0 cross-origin requests | **Observed: CDP, same-origin localhost only, 0 cross-origin** |

The full how-to-run steps and the evidence columns are in `state-gallery.md` → Verification table.

## Crossing state
**Crossing-B eligible for independent review.** No resolve-before-promotion item remains (`open-questions.md`). The token-parity and egress checks are closed by the receipt above and no longer depend on the earlier verifier mechanism.

Promotion still requires the **external reviewer's receipt**: independent execution of V1–V11, recorded in `state-gallery.md`. This package does not self-certify those checks.
