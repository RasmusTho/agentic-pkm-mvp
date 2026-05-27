# Claude Design Prompt

This file contains the complete prompt to paste into a Claude Design session. Attach this
entire package folder (or its contents) to the session before using this prompt.

---

## Prompt (paste this)

---

You are reviewing the Companion UI of Yggdrasil, a local-first personal cognitive prosthesis
built by a single person for their own daily use. You cannot access the GitHub repository,
issue tracker, or the live running application. Use only the documents and screenshots
included in this package.

**Your role:** Claude Design — produce design feedback and design specification. Do not write
code. Do not write implementation PRs. Your output will be consumed by Codex (an AI coding
agent) to produce implementation changes from your specification.

---

## Package contents

Before you begin, confirm which files and screenshots are present in the package you received.
If any screenshots from `SCREENSHOT_PLAN.md` are missing, note explicitly which ones are
missing and how their absence limits your review.

---

## Reading order

Read these documents before responding:

1. `SYSTEM_CONTEXT.md` — what the system is and why the UI exists
2. `COMPANION_UI_CURRENT_STATE.md` — current UI surfaces, status, and constraints
3. `HUMAN_UAT_RESULTS.md` — what passed, failed, and is ambiguous in testing
4. `DESIGN_REVIEW_BRIEF.md` — the core evaluation questions
5. `MARKDOWN_RENDERER_VISUAL_SCOPE.md` — the narrower typography and rendering scope
6. `CODEX_IMPLEMENTATION_BOUNDARY.md` — what Codex can and cannot do when implementing
   your specification

Then study the screenshots.

---

## What to evaluate

The Companion UI's entire surface as a cognitive prosthetic — not only Markdown rendering.

Key dimensions:
- Cognitive load: where does the UI require working memory that should be handled by the system?
- Friction: where does the UI slow down or interrupt the user's thinking?
- Orientation: does the user always know where they are, what is current, what the system did?
- Resumption after interruption: can the user come back after a day away and quickly recover?
- Note reading: is the note body calm and readable for long-form sensemaking?
- Visual hierarchy: is the note body unmistakably primary?
- Outline / right rail: does it help orientation without distracting?
- Panel / governance separation: is it visually and conceptually distinct from the note body?
- Error and disabled states: do they communicate clearly, or are they alarming and opaque?
- Does it feel like a cognitive prosthetic — a companion that has been tracking work — or a
  generic Markdown preview tool?

---

## Constraints you must respect

1. **Single-user, expert user.** No onboarding, no engagement mechanics, no growth patterns.
   The user is a senior software architect who is fluent in Obsidian and Markdown.

2. **Note body is always primary.** Nothing else in the layout should compete with it.

3. **Panel and Canvas are different surfaces with different semantics.** Do not collapse them.

4. **The vault (Markdown files on disk) is the source of truth.** The UI renders and augments;
   it does not replace or become authoritative.

5. **Do not specify changes that bypass governance boundaries.** Design may not suggest that
   the UI write to the vault directly, or that Panel proposals auto-execute, or that Canvas
   edits bypass the runtime governance pipeline. These are hard architectural constraints.
   See `CODEX_IMPLEMENTATION_BOUNDARY.md` for what Codex can implement.

6. **Implementation is Python/Jinja2 with Tailwind CSS.** CSS-based recommendations are
   preferred. Major UI framework migrations are outside scope. Prefer design-token changes and
   CSS adjustments. Do not require a full rewrite.

7. **Mermaid failures, wikilink failures, and body edit failures are implementation problems,
   not design problems.** Design should specify what the degraded/missing states should look
   like, but should not attempt to fix the underlying implementation failures.

---

## Output format

Structure your response as follows:

### 1. Package inventory

List which documents you received. List which screenshots are present and which are missing.

### 2. Overall assessment

One paragraph: does the current UI fulfill its purpose as a cognitive prosthetic? What is the
most critical gap?

### 3. Prioritized recommendations

Five categories:

**A. Quick visual fixes**
CSS/token-level changes achievable without structural changes. Be specific: name the element,
describe the change, explain why it reduces cognitive load or improves readability.

**B. Structural layout changes**
Changes to workspace organization, column widths, surface separation, or responsive behavior.
Each recommendation must include why it serves the cognitive prosthetic purpose.

**C. Cognitive-load reductions**
Identify elements that consume attention without providing value. Recommend removal, quieting,
or progressive disclosure. Be specific.

**D. Future / strategic changes**
Changes that require new functionality or should follow functional gap closure (body edit,
Mermaid, wikilinks). These are design targets, not current implementation scope.

**E. Things not to change**
Elements of the current design that are working well and should be preserved. This is as
important as the recommendations for change.

### 4. Error and missing-state specifications

For each failing or ambiguous UAT result, specify:
- Current state (what the UI shows now).
- Required state: what the UI must show when the feature fails or is unavailable.
- Optional: what the UI should show when the feature is available and working.
- Any interaction affordances.

Cover: Mermaid failure, wikilink failure, image failure/success, body edit unavailability,
task list rendering, code block rendering.

### 5. Typography and reading experience

Concrete specifications for the note body typography, organized by element (see
`MARKDOWN_RENDERER_VISUAL_SCOPE.md`). Be precise: heading levels, line heights, margins,
font weights, color values if critical to contrast. These should be implementable as CSS or
Tailwind token overrides by Codex without ambiguity.

### 6. Acceptance criteria and UAT checklist

A concrete list of acceptance criteria for the design changes you recommend. Each criterion
must be specific enough to produce a clear PASS or FAIL judgment in a human UAT session.

Group criteria by:
- Typography and reading (quick visual fixes)
- Layout and surface separation (structural changes)
- Error and missing states
- Outline and Panel

### 7. Codex implementation guidance

High-level design specification — not code — organized so Codex can translate it into
implementation tasks. Reference `CODEX_IMPLEMENTATION_BOUNDARY.md` for the constraints
Codex must observe. Flag any recommendation that Codex cannot implement within those
constraints and explain what a human decision would be needed for.

---

End of prompt.

---

## Notes for the human before sending

1. Confirm that screenshots are present in this folder and attached to the Claude Design session.
2. If screenshots are missing, consider capturing them before sending (see `SCREENSHOT_PLAN.md`).
3. Claude Design works best when it can see the actual UI rather than relying entirely on
   written descriptions. At minimum, screenshots 01, 02, 03, and 04 are essential.
4. The full package (all Markdown files) should be attached, not just the prompt.
