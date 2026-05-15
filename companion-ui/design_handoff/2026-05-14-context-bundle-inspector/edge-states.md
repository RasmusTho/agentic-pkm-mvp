# Edge states — Context Bundle Inspector

This document is the edge-state checklist required by the Handoff Governance Pack §08.
The full per-state visual treatment lives in **`prototype.html` §06 (Edge states)**. This
document is the text checklist.

## Required edges

- **Empty** — designed (see `prototype.html` §06).
- **Loading** — designed; static dim states, no skeleton animation.
- **Degraded** — designed; partial function with explicit naming of what is degraded.
- **Blocked** — designed; refusal is named, recorded, and never silently retried.
- **Stale context** — designed; threshold and "why" rendered.
- **Missing provenance** — designed; surfaced rather than hidden.
- **Write-guard denial** — designed; denial reason visible; not retried.
- **Reduced motion** — designed; receipt pulse + banner LED respect `prefers-reduced-motion`.
- **Narrow / mobile layout** — designed; see `prototype.html` §06 (and §04 for the
  portrait-specific layout in the bundle inspector).

## Deferred-with-reason

None for this package. If a future revision defers any edge, it must be tracked here with a
reason and a follow-up issue link.

## Validation expectations

Per the implementation contract, every edge above must render correctly from a fixture and
must satisfy the per-edge acceptance criteria in `prototype.html` §06. Reduced-motion is
verified with the OS preference set; narrow layouts are verified at the documented
breakpoints (`< 900px` for the standard collapse; `< 560px` where applicable).
