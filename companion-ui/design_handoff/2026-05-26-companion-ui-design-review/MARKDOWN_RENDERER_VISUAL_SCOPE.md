# Markdown Renderer Visual Scope

This document covers the narrower design scope for the Markdown renderer and typography
surface within the Companion UI note body. It is a subset of the broader design review
defined in `DESIGN_REVIEW_BRIEF.md`.

The renderer currently uses Python/Jinja2 server-side rendering with Tailwind CSS. It does
not use a JavaScript Markdown pipeline (no react-markdown, no remark/rehype). Design
recommendations should assume that CSS-based styling is the primary implementation path,
and should not require a renderer rewrite.

---

## Typography scale

**What to evaluate:**

- Is there a clear typographic scale between H1, H2, H3, H4, and body text?
- Do headings communicate hierarchy without requiring the user to count the `#` symbols?
- Is the H1 (note title) visually distinguished as the entry point of the note?
- Is H2 clearly subordinate to H1 and superior to H3?
- Do deeper heading levels (H4–H6) remain readable without being mistaken for body text?

**What to specify:**

- Font size ratios across heading levels relative to body text.
- Font weight per heading level.
- Top and bottom margin for each heading level.
- Whether headings should be visually marked (e.g. a subtle left accent or color shift) or
  rely on size and weight alone.

---

## Heading hierarchy

**What to evaluate:**

- Does the heading hierarchy help the user scan the note structure at a glance?
- Is there enough visual distance between heading levels?
- Are heading anchors (used by the outline rail) visually accessible without cluttering the
  reading experience?

**What to specify:**

- Visual treatment of heading anchors (hidden by default? visible on hover? always visible?).
- Whether section dividers or spacing should reinforce heading boundaries.

---

## Paragraph rhythm

**What to evaluate:**

- Is the line height comfortable for sustained reading?
- Is paragraph spacing consistent and generous enough to prevent text blocks from merging?
- Is line length controlled to a readable measure (recommended: 60–80 characters for body)?
- Does the paragraph spacing feel different from heading spacing?

**What to specify:**

- Line height for body text.
- Paragraph margin (space between consecutive paragraphs).
- Maximum line length for the note body column.

---

## Links

**What to evaluate:**

- Are external links visually distinguishable from body text?
- Are internal wikilinks (currently non-functional) styled to indicate they are links, even
  in their current non-functional state?
- Is the link color accessible (contrast ratio)?
- Is visited/hover/focus state specified?

**What to specify:**

- Link color, underline treatment, and hover state.
- Visual difference between external links and wikilinks (if any).
- Style for wikilinks that fail to resolve (missing/unresolved link state).

---

## Inline code

**What to evaluate:**

- Is inline code legible against the body text background?
- Is the font size appropriate relative to body text?
- Does the background / border treatment clearly mark it as code without being distracting?

**What to specify:**

- Font family, size, background, and border for inline code.
- Whether inline code should have horizontal padding.

---

## Code blocks

**What to evaluate:**

- Is the code block visually separated from surrounding body text?
- Is the font size readable?
- Is there a language label?
- Is the contrast adequate?
- Does the code block feel like a stable reading surface, not a piece of chrome?

**What to specify:**

- Background, border, and border-radius for code blocks.
- Font family and size.
- Padding (internal and external).
- Language label style and placement.
- Whether line numbers are needed (probably not for this use case).

---

## Blockquotes

**What to evaluate:**

- Are blockquotes visually distinct from body paragraphs?
- Is the left-border treatment consistent with the overall design language?
- Does the blockquote style interfere with callout rendering?

**What to specify:**

- Left border color and width.
- Text color and font style inside blockquotes.
- Whether nested blockquotes maintain visual clarity.

---

## Callouts

**What to evaluate:**

- Do callout types (note, warning, tip, info, etc.) have visually distinguishable treatments?
- Is the callout icon (if present) consistent and unambiguous?
- Does the callout background/border integrate with the note body without being alarming?
- Are foldable callouts (collapsed/expanded) clearly interactive?

**What to specify:**

- Background and border color per callout type (at minimum: note, warning, tip, info,
  question, danger, success).
- Icon or type marker treatment.
- Header vs body layout within a callout.
- Fold indicator style and placement.

---

## Tables

**What to evaluate:**

- Are table headers visually distinct from data rows?
- Is the table readable at a glance without requiring the user to trace rows horizontally?
- Does the table style integrate with the surrounding text without dominating it?
- Does the table behave reasonably on narrow viewports?

**What to specify:**

- Header background and border.
- Row striping or border treatment.
- Cell padding.
- Whether tables should scroll horizontally on narrow viewports or wrap.

---

## Task lists

**What to evaluate:**

- Do task checkboxes render at a size and position that matches the list text?
- Are checked and unchecked states visually clear without requiring color alone?
- Are non-standard task states (`[/]`, `[-]`, `[>]`) styled distinctly, or should they fall
  back to the unchecked visual?
- Are task lists read-only in the current UI? Is this clear to the user?

**What to specify:**

- Checkbox size and alignment with list text.
- Style for `[ ]` (unchecked), `[x]` (checked), and any supported non-standard states.
- Visual indication that task checkboxes are currently non-interactive (read-only rendering).

---

## Horizontal rules

**What to evaluate:**

- Are horizontal rules visible and purposeful without being heavy or distracting?
- Do they provide a meaningful section break or just noise?

**What to specify:**

- Color, thickness, and margin for horizontal rules.
- Whether they should match or contrast with the background.

---

## Missing / unsupported block containment

Some block types fail to render (Mermaid, wikilinks) or are not yet supported (complex
embeds, Dataview). These should not produce silent failures or raw text output.

**What to evaluate:**

- Is there a consistent treatment for blocks that fail to render?
- Does the user understand that a specific feature is not working, rather than assuming the
  note has no content in that block?
- Is the failure state calm and informative, not alarming?

**What to specify:**

- Visual style for unsupported or failed block placeholders.
- Text/label convention for failed blocks (e.g., "Mermaid diagram — not available in this
  view" vs. raw fallback text).
- Whether failed blocks should have a border, background, or icon to distinguish them from
  intentional content.

---

## Relation to right rail and Panel

The note body typography must be evaluated in the context of the full workspace layout:

- **Right rail (outline):** The outline text style must be lighter and smaller than the note
  body to maintain visual hierarchy. The outline should never compete with the note headings
  for weight.
- **Panel / governance rail:** Panel content must be visually distinct from the note body.
  Panel proposals are machine-generated and must not look like note content. Their typography
  should signal a different semantic category.
- **Shell chrome:** The workspace shell (header, environment markers, dark background) must
  not bleed into the note body's reading surface. The note body should feel as if it is a
  clean reading canvas, not a panel inside a dashboard.
