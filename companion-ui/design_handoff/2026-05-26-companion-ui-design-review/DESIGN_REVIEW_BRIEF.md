# Design Review Brief — Companion UI

## Addressed to: Claude Design

This is the core brief for the Companion UI design review. Read `SYSTEM_CONTEXT.md` and
`COMPANION_UI_CURRENT_STATE.md` before reading this document.

---

## What we need from Claude Design

A **design review and design specification** — not implementation code, not implementation PRs.

We need Claude Design to evaluate the current UI against the system's cognitive prosthetic
purpose and produce prioritized, actionable design recommendations organized by type.

Claude Design should not attempt to fix Mermaid rendering, wikilink resolution, or body edit
failures — those are implementation problems with dedicated implementation tracks. Claude
Design's output will be consumed by Codex (see `CODEX_IMPLEMENTATION_BOUNDARY.md`) to produce
implementation changes from the design specification.

---

## Evaluation questions

Claude Design should evaluate the Companion UI against the following questions. Use the
screenshots in this package alongside the system context documents. Answer each question
concretely.

### Does the UI support the system's purpose?

The system's purpose is to function as a cognitive prosthesis for a single expert user.
- Does the current UI support sustained reading and sensemaking of long-form vault notes?
- Does it support orientation — knowing where you are, what is current, what the system has
  done?
- Does it feel like a tool the user can trust, or like something they must manage?
- Does it support resumption after interruption — coming back after hours or days and quickly
  recovering what you were thinking about?

### Where does it create unnecessary cognitive load?

- Are there UI elements that require the user to track system state that the UI should be
  tracking for them?
- Are there elements competing for attention that do not serve the current cognitive act?
- Is the visual hierarchy clear enough that the user does not need to consciously parse the
  page structure?
- Are there areas where information is present but not legible without effort?

### Where does it create friction?

- Are there places where a user would pause to figure out what to do next?
- Are there interaction patterns that work against the user's likely intent?
- Are there states (empty, loading, error, disabled) that are confusing or alarming rather
  than informative?
- Does the outline navigation add value or require extra effort to use?

### Is the visual hierarchy clear?

- Is the note body unmistakably the primary surface?
- Are the outline rail and Panel rail clearly secondary?
- Are headings within the note readable at a glance without requiring effort?
- Is the relationship between the note body, the outline, and the Panel rail clear?

### Is the note body calm and readable enough for long-form sensemaking?

- Does the typography support sustained reading? (Refer to `MARKDOWN_RENDERER_VISUAL_SCOPE.md`
  for detailed typography scope.)
- Is the line length appropriate?
- Is the vertical rhythm consistent?
- Is there enough visual breathing room between sections?
- Do callouts, tables, code blocks, and blockquotes integrate naturally with body text?

### Does the right rail help orientation without distracting?

- Does the outline appear at the right visual weight — present but not competing?
- Is the outline legible and navigable?
- Does it communicate the structure of the document without duplicating the document?
- What should happen to the outline on narrow viewports?

### Is Panel / governance separation understandable?

- Can a user understand at a glance that the Panel rail is a distinct surface from the note
  body?
- Are Panel proposals visually distinguishable from note content?
- Is the Panel placeholder state clear — that it exists but currently has no proposals?
- Does the Panel feel like it belongs in the workspace without dominating it?

### Are errors and disabled states understandable?

- What should missing wikilinks look like? (Currently they fail silently or render as text.)
- What should a failed Mermaid block look like? (Currently it fails without a useful signal.)
- What should a missing image look like? (Placeholder state observed but not designed.)
- What should unavailable body edit controls look like?
- Do these states communicate "I understand what happened and what to do next" rather than
  "something is broken"?

### Does the UI help resumption after interruption?

- If a user returns to the UI after a day away, what do they see?
- Is the last-viewed note still present?
- Does the UI communicate whether the system state is fresh or stale?
- Is there enough context to resume without reconstructing state from scratch?

### Does it support review and decision-making?

- When Panel proposals exist (they do not in the current UAT, but design should specify
  the state), does the layout support reading the proposal alongside the relevant note content?
- Can the user see both the note body and the Panel rail simultaneously without one
  overwhelming the other?

### Does it feel like a cognitive prosthetic rather than a generic Markdown viewer?

- Does the current UI have qualities that distinguish it from a bare Markdown preview tool?
- Are there places where the design could reinforce the sense that this is a companion — an
  entity that has been tracking work on behalf of the user — rather than a read-only renderer?
- Are there places where the current design works against this framing?

### What needs to change before it is a credible daily-use companion surface?

- If the user sat down to use this as their primary companion surface tomorrow, what would
  they encounter that would erode trust or cause them to disengage?
- What is the shortest path to a surface that could be used daily without friction?

---

## Output format requested

Organize Claude Design's output into the following sections:

### 1. Overall assessment

One paragraph: does the current UI fulfill the system's purpose? What is the most important
thing missing?

### 2. Prioritized recommendations

Organized into five categories:

**A. Quick visual fixes**
Changes achievable by CSS or design token adjustment without structural change. Examples:
typography scale, spacing, color contrast, line height.

**B. Structural layout changes**
Changes to how the workspace is organized — column widths, visual separation between surfaces,
responsive behavior, information hierarchy.

**C. Cognitive-load reductions**
Changes that remove or quieten elements that consume attention without providing value. Changes
that surface useful state without requiring the user to seek it out.

**D. Future / strategic changes**
Changes that require new functionality or are appropriate only after functional gaps (body edit,
Mermaid, wikilinks) are resolved.

**E. Things not to change**
Elements of the current design that are working and should be preserved.

### 3. Error and missing-state specifications

For each failing or ambiguous UAT result (Mermaid, wikilinks, images, body edit, task lists,
code blocks), specify:
- What the degraded/missing state should look like.
- What the successful state should look like.
- Any interaction affordances that should be present in each state.

### 4. Typography and reading experience

Detailed recommendations for the note body typography, including:
- Heading scale and weight.
- Body paragraph rhythm and line height.
- Code block and inline code treatment.
- Table visual style.
- Callout visual style.
- Interaction between Markdown elements and surrounding shell.

(See `MARKDOWN_RENDERER_VISUAL_SCOPE.md` for the full visual scope.)

### 5. Acceptance criteria and UAT checklist

A concrete list of acceptance criteria that Codex can implement against and the human can
verify in a follow-up UAT session. Each criterion should be specific enough to produce a
clear PASS or FAIL judgment.

### 6. What Codex should do and should not do

High-level guidance for Codex implementation, expressed as design specification rather than
code. Refer to `CODEX_IMPLEMENTATION_BOUNDARY.md` for the constraints Codex must observe.
