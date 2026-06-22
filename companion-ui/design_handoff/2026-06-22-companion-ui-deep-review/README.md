# Companion UI — Deep Design Review Package (2026-06-22)

## What this is

A self-contained handoff for **Claude Design** to perform a **deep design review** of the
Companion UI (the Yggdrasil / Agentic PKM front door). "Deep" means the review evaluates
**whether the workflows work intuitively and whether functions have been implemented well** —
not whether individual screens look good in isolation.

This package supersedes the per-screen, aesthetics-first framing of
`../2026-05-26-companion-ui-design-review/`. It is addressed to a design-review AI that cannot
run the app or read the repo, so everything it needs is in this folder.

## Why a new package (what changed since 2026-05-26)

- The **System Entry Point** shipped: a unified shell with an entry-state machine
  (`boot / cold_start / orienting / shell_active / no_vault`), a single overlay host, and a
  system map. The earlier package predates all of this.
- The UI "almost works again" but has known graphical and functional defects — some already
  found and documented here (see `OBSERVED_ISSUES.md`), some still latent.
- The owner wants the review organised around **end-to-end journeys** and a **two-axis rubric
  (workflow intuitiveness × implementation quality)**, not a screen-by-screen aesthetics pass.

## How to read this package (in order)

1. **`SYSTEM_CONTEXT.md`** — what Yggdrasil is, who the single user is, and the design
   philosophy the UI is meant to serve (anti-dashboard, calm, server-authoritative, governed).
2. **`SURFACE_INVENTORY.md`** — every captured surface: what it is, what triggers it, which
   journey it serves, the spec doc that governs it, and any pre-noted observation.
3. **`WORKFLOWS_TO_EVALUATE.md`** — the **core of the review**: the user journeys to walk,
   each with its screenshots and the specific questions to answer.
4. **`OBSERVED_ISSUES.md`** — defects already found during capture, with evidence. Start past
   these; don't just re-report them.
5. **`REVIEW_BRIEF.md`** — the brief: the two-axis rubric, what's in/out of scope, and the
   exact deliverable format we want back.

## What we want back

Design feedback **and** a design specification — not code, not PRs. Specifically:

- A per-journey verdict on **two axes**: *Is the workflow intuitive?* and *Is the function
  implemented well?* (rubric in `REVIEW_BRIEF.md`).
- Prioritised, actionable recommendations grouped by type (quick visual fix · structural
  layout · cognitive-load reduction · workflow/interaction redesign · strategic · do-not-change).
- Acceptance criteria / UAT checklist per recommendation, stated as design spec.

The output is consumed downstream by the implementer (Codex) through the governed handoff chain
(`../../docs/DESIGN_HANDOFF_GOVERNANCE.md`). Design should produce specification, not fixes.

## Screenshot set

26 captures in `img/`, all from the **real `render_index_html` renderer** using the project's
own state fixtures (the same fixtures the `test_entry_state_gallery.py` regression net asserts),
so every pixel is what the dev/prod gateway emits. Index and meaning in `SURFACE_INVENTORY.md`.

- `entry_*` — entry / orientation states (first contact, re-entry mist ladder, degraded, stale,
  no-vault, vault picker).
- `shell_*` — the active document shell and its states (suggestions, Panel proposals, governed
  receipt, blocked).
- `overlay_*` — every shipped drawer / modal / overlay opened (command palette, capture, memory
  review, settings, vault browser, receipts history, system map, guidance layer).
- `narrow_*` — narrow / portrait responsive captures.
- `evidence_topbar_*` — supporting evidence for `OBSERVED_ISSUES.md` #1.

### Methodology and its limits (read before judging dynamics)

These are **static, server-rendered captures with no live runtime connected**. That makes them
faithful for *layout, hierarchy, typography, state composition, and copy*, but they **do not
exercise**: live data fetches (some overlays show their degraded/empty fallback — e.g. memory
review reads "Review queue unavailable"), animations and motion, focus management, scroll
behaviour, or the body-edit / Canvas round-trip. Where a judgement depends on live behaviour,
say so and flag it for separate live UAT rather than inferring it from a still.

The overlays were opened through the page's own `window.overlayHost.mount()` API because the
topbar launch icons are clipped off-screen at the capture width — itself a finding
(`OBSERVED_ISSUES.md` #1).

## Reproducing the screenshots

From the repo root (`agentic-pkm-mvp`), with the project venv:

```bash
.venv/bin/python companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/_tools/generate.py
.venv/bin/python companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/_tools/screenshot.py
```

`generate.py` renders every state to `screens/*.html` (pure render, no runtime). `screenshot.py`
drives Chromium (Playwright) over those files and writes `img/*.png`. Both reuse the fixtures in
`tests/companion_ui/test_entry_state_gallery.py`, so the package stays in lock-step with the
shipped renderer.

## Governance

This is a Crossing-A design input: guidance only, not architecture authority or runtime truth.
It must pass the governed chain in `../../docs/DESIGN_HANDOFF_GOVERNANCE.md` before any
recommendation becomes implementation work. It does not override any owner doc in `docs/**`.
