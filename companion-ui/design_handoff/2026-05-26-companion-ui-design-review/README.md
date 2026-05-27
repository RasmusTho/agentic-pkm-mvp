# Companion UI Design Review Package — 2026-05-26

## What this is

This is a self-contained design review package for the Companion UI surface of the Yggdrasil
Agentic PKM system. It is addressed to Claude Design.

It covers the whole Companion UI as a cognitive prosthetic surface — not only Markdown rendering.
It includes UAT findings, a design brief, a Markdown renderer visual scope document, a screenshot
plan, a prompt ready to paste into a Claude Design session, and a Codex implementation boundary
document.

## Who this is for

**Claude Design** — a design-review AI that will produce design feedback and design
specification, not implementation code.

Claude Design should not expect to access GitHub issues, repo history, or the running application.
Everything Claude Design needs to understand the system is included in this package.

## What Claude Design should produce

Design feedback and a design specification — not code, not implementation PRs.

Specifically:
- Prioritized design recommendations organized by change type (quick visual fix, structural
  layout change, cognitive-load reduction, future/strategic change, things not to change).
- Acceptance criteria and a UAT checklist for validating design changes.
- Codex-ready implementation guidance stated as design specification, not as code.

## How to use this package

1. Read `SYSTEM_CONTEXT.md` first. It explains what Yggdrasil is and why the Companion UI exists.
2. Read `COMPANION_UI_CURRENT_STATE.md`. It describes the current UI surfaces, their status, and
   known constraints.
3. Read `HUMAN_UAT_RESULTS.md`. It contains the full UAT result matrix from the most recent
   manual test run and its interpretation.
4. Read `DESIGN_REVIEW_BRIEF.md`. This is the core brief that frames what Claude Design should
   evaluate.
5. Read `MARKDOWN_RENDERER_VISUAL_SCOPE.md` for the narrower typography and rendering scope that
   is a subset of the broader design review.
6. Read `SCREENSHOT_PLAN.md`. It lists all screenshots the human should add to this package
   before sending it to Claude Design. Check which screenshots are present in this folder.
7. Use `CLAUDE_DESIGN_PROMPT.md` as the prompt to paste into a Claude Design session, with this
   package attached.
8. Read `CODEX_IMPLEMENTATION_BOUNDARY.md` to understand how Codex will later consume Claude
   Design's output.

## How to use the screenshots

Screenshots are named sequentially and documented in `SCREENSHOT_PLAN.md`. Each screenshot
entry explains what it should show and what Claude Design should evaluate in it.

If a screenshot listed in `SCREENSHOT_PLAN.md` is not present in this folder, it has not yet
been captured by the human. Claude Design should note which screenshots are missing and how
their absence limits the review.

## Location note

Design handoffs for this project live in `companion-ui/design_handoff/`. This package follows
that convention. The task brief requested `docs/design_handoffs/` but that directory does not
exist in the repo. All prior design handoffs use `companion-ui/design_handoff/`, so this package
follows the established convention.

## Package contents

| File | Purpose |
|---|---|
| `README.md` | This file — package overview and usage guide |
| `SYSTEM_CONTEXT.md` | Yggdrasil purpose, framing, and cognitive prosthesis definition |
| `COMPANION_UI_CURRENT_STATE.md` | Current UI surfaces, status, and known constraints |
| `HUMAN_UAT_RESULTS.md` | Full UAT result matrix with interpretation |
| `DESIGN_REVIEW_BRIEF.md` | Core design review brief for Claude Design |
| `MARKDOWN_RENDERER_VISUAL_SCOPE.md` | Narrower Markdown renderer and typography scope |
| `SCREENSHOT_PLAN.md` | Screenshot checklist with evaluation guidance |
| `CLAUDE_DESIGN_PROMPT.md` | Ready-to-paste prompt for a Claude Design session |
| `CODEX_IMPLEMENTATION_BOUNDARY.md` | Constraints for Codex when implementing design changes |

## Screenshots status (2026-05-26)

Five screenshots are now present:

| File | What it shows |
|---|---|
| `01_full_workspace_top.png` | Full three-column workspace — outline left, note body center, Panel right |
| `02_note_body_uat_table.png` | UAT result summary table; body paragraph context |
| `03_outline_left_rail_heading_hierarchy.png` | Heading hierarchy in note body and left outline rail |
| `05_callouts.png` | Note / Tip / Warning / Danger callouts with color coding |
| `06_task_lists_and_tables.png` | Task list checkboxes (checked/unchecked) and feature table |
| `logga v2.png` | Yggdrasil product logo — gold/organic + teal/circuit on black |

Still missing: close-up body typography (02), Panel right rail close-up (04), code block (06),
Mermaid failure (07), wikilink/image failure (08), body edit state (09), Vault Browser (10),
mobile view (11). See `SCREENSHOT_PLAN.md` for full details.

The package is usable for Claude Design with the current screenshots, but the missing
screenshots limit review of error states, code blocks, and the Panel rail in detail.
