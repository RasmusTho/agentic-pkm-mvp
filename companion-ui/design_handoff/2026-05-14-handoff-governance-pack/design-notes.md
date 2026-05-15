# Design notes — Design Handoff Governance Pack

## Visual language

This package follows the shared Yggdrasil design system (`colors_and_type.css`) used across the
2026-05 companion-ui handoffs:

- **Dark, cool blue-black background** (`--bg-base`) with a subtle Tron grid.
- **Cool blue-white text** (`--fg-1`); secondary copy in `--fg-2`; mono captions in `--fg-3`.
- **Norse gold** (`--accent`) for governance and provenance accents.
- **Electric cyan** (`--cyan`) for trigger / link / receipt-pending cues.
- **Vault green** (`--vault`) for healthy, applied, reviewed.
- **Amber** (`--amber`) for staged, stale, inferred, or attention-needed.
- **Destructive red** (`--destructive`) for refusal, denial, conflict, and dead-letter.

Type: **EB Garamond** for display, **Space Grotesk** for UI, **JetBrains Mono** for evidence
captions, ids, scores, and timestamps. Mono is the load-bearing voice of "this is evidence,
not summary."

## Surface posture

How a Claude Design exploration becomes a governed implementation input — without becoming architecture authority on the way.

The surface is intentionally **calm**:

- No alarm noise. Red is reserved for actual refusals.
- No coloured tiles without evidence. Every mono caption is rooted in a runtime value.
- Animation is restrained: receipt-pill pulse and the banner LED only. Both respect
  `prefers-reduced-motion`.
- No emoji. Status uses short words ("Running", "Backlogged", "Stale") rather than icons.

## Component vocabulary

The shared spec chrome (`spec_chrome.css`) carries:

- `.callout` (cyan, amber, accent, destructive, vault variants) for invariants and notes.
- `.chip` for tag-style metadata.
- `.receipt` (queued, applied, pending, failed) for receipt pills.
- `.btn` (primary, governance, vault, danger, ghost) for actions.
- `.gallery` and `.gallery-card` for state galleries.
- `table.spec` for evidence tables with mono headers.

Each prototype adds local components on top — see `prototype.html` for inline styles.

See `prototype.html` §02 for the flow diagram, §03 for the maturity checklist, §04 for the review console prototype, §05–§07 for the README / implementation-contract / authority-boundaries templates.

## Why the layout is the way it is

- **TOC sidebar.** Specs are scanned, not read. The TOC is sticky so scanning stays cheap.
- **Mono section numbers and metadata.** Visual contract: mono text means "this is a value
  the runtime emits", not a designer's invented label.
- **Section heads in EB Garamond.** Display serif at section boundaries marks the
  transitions in attention; UI sans inside the section keeps reading dense.
- **No hover-only affordances.** Every action is visible at rest; hover only adds an accent.

## Copy conventions

- Headlines: short verbs or adjectives.
- Captions: mono, in `--fg-3`.
- Action labels: uppercase, letter-spacing wide, never punctuated.
- Status copy: second-person plain language. Never imperative-without-object ("Restart").

## Out of scope for this package

- Brand redesign.
- New colour tokens (none added).
- New type pairings.
- Animation grammar beyond the existing receipt-pulse pattern.
