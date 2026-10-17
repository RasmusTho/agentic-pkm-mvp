# Design notes — CAL-03 revisit card

## Grammar used (all existing)
| Part | Yggdrasil source | Notes |
|---|---|---|
| Card | Cards & surfaces → surface panel: `--bg-surface`, 1px `--border`, `--radius-md`, no shadow | No glow at rest. |
| Eyebrow | `h5` grammar: UI sans, `--text-sm`, medium, `--tracking-wide`, uppercase, `--fg-2` | "Decision calibration · revisit" |
| Question | Display serif (`--font-display`, `--text-xl`, `--tracking-tight`) | Same use as session titles. The decision title is EB Garamond italic, the system's secondary display line. |
| Metadata | Mono `--text-xs`, `--fg-2`, `--tracking-wide` | Date, rung, short id. Never `--fg-3`. |
| Note | Inputs & forms → compose textarea: `--bg-raised`, `--border-strong`, `--radius-md` | Label "Note (optional)". Hint is `--fg-2`. |
| Answer picks | Buttons → secondary: `--bg-raised`, 1px `--border-strong`, `--control-height` | Four equal-weight buttons. None is primary, so no outcome is suggested. |
| Dismiss | Buttons → ghost: no border, `--fg-2` | In its own form, below a `--border` divider. |
| Status | Badges: mono uppercase on `-muted` with `-dim` border | Pending = default, Recording/Deferring = cyan, Recorded = vault, Deferred = default, Unavailable = amber, Not recorded/Blocked = destructive. |
| Chosen pick while submitting | Selection grammar: `--accent` border | Label kept, plus "· recording". |
| Failure | Destructive muted panel with `--destructive-dim` border | Pattern from the Companion kit's unreachable banner. Body text is `--fg-1`. |
| Focus | `data-focus="v2"`: 2px `--border-focus`, 2px offset, from the sheet | Not overridden anywhere. |
| Motion | `--duration-base` / `--ease` colour fades only | These become zero under reduced motion through the sheet. |

## How answer and dismiss differ
Five layers separate them, and none of them adds new authority affordance:
1. **Two forms, two routes.** Picks are `submit` buttons in the answer form. Dismiss is the only button in a separate form, so it can never send `outcome` or `note`.
2. **Button grammar.** Picks are outlined secondary buttons. Dismiss is a ghost button.
3. **Placement.** Picks sit in a fieldset with the legend "Did it hold?". Dismiss sits below a divider in the footer.
4. **Verb.** "Dismiss for now", with the visible description "Defers this revisit. Records no outcome." (`aria-describedby`).
5. **Consequence copy.** The picks' description reads "A pick records the outcome for this rung. It cannot be changed afterwards."

## Note placement
The note comes before the picks because a pick submits immediately. A note placed after the picks could never be sent. The note is not required, and its hint says so.

## Duplicate-action prevention
While submitting, every pick and the dismiss button get `aria-disabled="true"`, not `disabled`, so keyboard focus stays on the pressed control. The submit handler ignores events in either `submitting_*` state. The textarea becomes `readonly`. The chosen label stays visible.

## Not used, by rule
- No glow anywhere. No element is "the one live element" in the sense the effects rule means. See open question Q8.
- No icons. Text labels carry every meaning, so a Lucide glyph would add nothing.
- No `.fx-grid`, no v1 glow classes, no raw hex, no `rgba` literals in the prototype CSS.
- The resting glow on Buttons and Badges preview cards conflicts with "glow is a state" in README/SKILL. The sheet defines no button styles, so the README rule applies and the resting glow is dropped. See Q2.

## Responsive
- Picks: `repeat(auto-fit, minmax(min(100%, 8.5rem), 1fr))`. Four columns at desktop, 2×2 at around 360px, one column at 200% zoom on narrow viewports.
- The card is `max-width: 42rem`, `min-width: 0`, and long titles wrap (`overflow-wrap: anywhere`).
- Below 52rem, card padding drops from `--space-6` to `--space-4`.

## Print
CSS only, so it works with JavaScript off. Forms, dismiss, and live status are hidden, and "Outcome pending." is shown. Surfaces lose their backgrounds. Text uses `--fg-inverse` (the role for text on light grounds, here paper) and borders use `--border-strong`. No token values are restated. See Q11.

## JavaScript off
The pending card is server-rendered as two plain `<form method="post">` elements. A pick posts `outcome=<enum>` plus `note`, and dismiss posts nothing. The server responds post/redirect/get and re-renders the card from the new state. The prototype shows this markup in `<noscript>`.
