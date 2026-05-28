# Screenshot Plan

This document lists all screenshots that should be added to this package before sending
it to Claude Design. Screenshots must be captured from the live Companion UI running against
the dev vault (Niflheim) with the UAT note (`Companion_UI_Markdown_Feature_UAT.md`) loaded.

**Layout clarification:** The outline is the LEFT rail. The Panel / governance is the RIGHT
rail. Screenshot names have been updated to reflect this.

---

## Checklist — current status

- [x] `01_full_workspace_top.png` — **PRESENT** (full workspace, all three columns visible)
- [ ] `02_note_body_typography.png` — **MISSING** — `02_note_body_uat_table.png` shows the UAT result table but not a close-up of body typography with headings + paragraphs + inline code
- [x] `03_outline_left_rail_heading_hierarchy.png` — **PRESENT** (heading hierarchy with nested levels visible in both note body and left outline rail)
- [ ] `04_panel_governance_separation.png` — **MISSING** — partial view in `01_full_workspace_top.png` but no dedicated close-up of Panel right rail
- [x] `05_callouts.png` — **PRESENT** (Note, Tip, Warning, Danger callouts with color coding)
- [x] `06_task_lists_and_tables.png` — **PRESENT** (task list checkboxes + beginning of tables section)
- [ ] `07_mermaid_failure.png` — **MISSING**
- [ ] `08_links_images_failure.png` — **MISSING**
- [ ] `09_body_edit_failure.png` — **MISSING**
- [ ] `10_vault_browser_if_relevant.png` — **MISSING**
- [ ] `11_mobile_or_narrow_view_if_available.png` — **MISSING**

Additional file present:
- [x] `logga v2.png` — Yggdrasil product logo (gold/organic + teal/circuit on black). Design reference.
- [x] `02_note_body_uat_table.png` — UAT result summary table visible. Not a typography close-up but useful context.

**Minimum required before sending to Claude Design:** screenshots 01, 04, 07, 08, and 09 together cover the most critical evaluation areas. Screenshots 02 and a dedicated Panel close-up (04) are the highest-priority missing items.

---

## Screenshot specifications

### `01_full_workspace_top.png` ✓ PRESENT

**What is shown:**
- Full three-column workspace: left outline rail, center note body, right Panel rail.
- Note title "Companion UI Markdown Feature UAT" as H1.
- Dense metadata band above the title (breadcrumb, artifact ID, content hash, properties).
- "DEV / NOT PRODUCTION" badge top right.
- Environment/system status bar across the top.
- A green Important callout visible in the note body.
- The UAT result summary table beginning below the callout.
- Right Panel rail showing: "No active Panel proposals", "Panel ready", "Suggestions are idle",
  "Find is unavailable...", "read-only".

**What Claude Design should evaluate:**
- Overall layout and proportions of the workspace.
- Visual hierarchy between surfaces (note body vs. left outline vs. right Panel).
- Shell chrome weight — the metadata band and status bar take significant space before content.
- Whether the note body feels like the primary surface despite the chrome.
- First impressions of the full workspace at rest.
- Whether the Panel rail state labels communicate clearly without requiring interpretation.

---

### `02_note_body_uat_table.png` ✓ PRESENT (partial coverage)

**What is shown:**
- The UAT result summary table: a GFM table with Feature / Expected / Result columns.
- Rows: Outline/right rail, Callouts, Tables, Task lists, Code blocks, Mermaid, Images,
  Internal links, Body edit.
- Table renders with visible column structure and row borders.
- Body paragraphs visible above the table.

**What Claude Design should evaluate:**
- Table header/data row visual distinction.
- Table cell padding and legibility.
- How table text size relates to body paragraph text.
- Whether the table feels integrated or intrusive.

### `02_note_body_typography.png` ✗ MISSING — still needed

**What to capture:**
- A close-up of the note body showing at least two heading levels (H1 or H2 and H3)
  alongside body paragraphs, a list, and inline code within a sentence.

**What Claude Design should evaluate:**
- Typographic scale between heading levels and body text.
- Paragraph rhythm and line height.
- Vertical spacing between heading, body, and list elements.
- Whether the typography feels calm and readable for long-form sensemaking.

---

### `03_outline_left_rail_heading_hierarchy.png` ✓ PRESENT

**What is shown:**
- Section "2. Outline and right rail navigation" (H2) with nested headings:
  "2.1 First nested heading" (H3), "2.1.1 Third-level heading" (H4),
  "2.2 Second nested heading" (H3), "2.2.1 Another third-level..." (H4).
- The left outline rail shows the same heading structure with indentation.
- H2 and H3 headings in the note body are visually very similar in size.

**What Claude Design should evaluate:**
- Visual weight of the left outline rail relative to the note body.
- Legibility of outline heading entries and indentation.
- Whether the outline feels secondary without being invisible.
- **Critical:** The heading hierarchy problem — H2 and H3 are barely distinguishable. The H2
  "2. Outline and right rail navigation" and H3 "2.1 First nested heading" appear at nearly
  the same visual size. Design must specify a more differentiated heading scale.
- Whether heading numbering (2., 2.1, 2.1.1) is part of the note content or should be
  stripped/de-emphasized in the reading view.

---

### `04_panel_governance_separation.png`

**What to show:**
- The Panel / governance rail alongside the note body.
- If the Panel rail is in placeholder state, capture that state clearly.
- Include the boundary between the note body and the Panel rail.

**What Claude Design should evaluate:**
- Is the Panel rail visually distinguishable from the note body?
- Is the placeholder state informative or confusing?
- Does the Panel feel like a companion surface, not a notification panel?
- Is the visual boundary between Panel and note body clear?

---

### `05_callouts.png` ✓ PRESENT

**What is shown:**
- Section "5.2 Obsidian-style callouts" with four callout types rendered:
  - **Note** — blue background, "Note" label
  - **Tip** — blue/teal background, "Tip" label
  - **Warning** — yellow/orange background, "Warning" label
  - **Danger** — red background, "Danger" label
- Each callout has a distinct background color and a type label.

**What Claude Design should evaluate:**
- The color palette and whether it is consistent with the Yggdrasil design language
  (see `logga v2.png` — gold/teal/black).
- Whether the callout backgrounds are calm or alarming.
- Whether the type labels are sufficient or if icons would add clarity.
- Callout body text size and padding.
- The visual boundary between callout and surrounding body text.
- Whether foldable callout interaction would need a different visual treatment.

### `05_tables_callouts.png` ✗ MISSING — combine with existing or capture separately

The table rendering is partially captured in `02_note_body_uat_table.png`. A screenshot
showing a feature table (Feature / Input syntax / Expected rendering) alongside a callout
would be useful additional context.

---

### `06_task_lists_and_tables.png` ✓ PRESENT

**What is shown:**
- Task list section with four items:
  - Unchecked task (empty checkbox)
  - Checked task (filled/checked checkbox)
  - Task with bold text
  - Task with inline code
- The task list is followed by the beginning of section "4. Tables" and a feature table
  (Feature / Input syntax / Expected rendering / Bold row visible).

**What Claude Design should evaluate:**
- Checkbox size, alignment, and visual distinction between checked and unchecked states.
- Whether inline code within a task item renders correctly relative to the task text.
- Whether the read-only nature of the task checkboxes needs a visual cue (currently they
  appear interactive but cannot be toggled — a governance constraint, not a design choice).
- Table visual style: header vs data row distinction, cell padding, border treatment.
- Whether the task list and table sections feel integrated with the surrounding content.

### `06_code_blocks_task_lists.png` ✗ MISSING — code block still needs capture

A dedicated screenshot of a fenced code block (with a language tag) is still needed. The
task list portion is covered by `06_task_lists_and_tables.png`.

---

### `07_mermaid_failure.png`

**What to show:**
- A fenced Mermaid block from the UAT note in its current failed/unrendered state.
- Show whatever the UI currently displays — raw text, empty space, or an error message.

**What Claude Design should evaluate:**
- Is the current failure state acceptable? (It is not — this is a design problem to solve.)
- What should the degraded state look like?
- Should there be a labeled placeholder, an error icon, a fallback message?
- How should the failure communicate that a diagram was intended here?

---

### `08_links_images_failure.png`

**What to show:**
- A wikilink (`[[Note Name]]`) from the UAT note in its current non-functional state.
- The missing image placeholder state that was observed during UAT.
- Both in the same screenshot if layout allows.

**What Claude Design should evaluate:**
- What does a failed/unresolved wikilink look like currently?
- Is the current state informative or silent?
- What should a resolved wikilink look like?
- What should an unresolved wikilink look like?
- What should the missing image placeholder look like?
- What should a successfully loaded image look like?

---

### `09_body_edit_failure.png`

**What to show:**
- The note body in its current read-only state.
- If there is any edit affordance visible (edit button, click-to-edit hint), include it.
- If the edit attempt was made and produced no visible effect, capture the state after the
  attempt.

**What Claude Design should evaluate:**
- Is it clear to the user that the note body is currently read-only?
- If edit affordances exist but do not work, how should they be styled to communicate
  their unavailable state?
- What should the transition from read-only to editable look like when body edit becomes
  available?
- Should the UI communicate "body edit is coming" or should it be silent about absent
  functionality?

---

### `10_vault_browser_if_relevant.png`

**What to show:**
- The Vault Browser surface if it is accessible from the current UI and relevant to the
  design review.
- Capture at a comfortable reading size showing the vault structure and any artifact
  inspector content.

**What Claude Design should evaluate:**
- Does the Vault Browser share visual language with the workspace shell?
- Is the transition between Vault Browser and note workspace legible?
- Does the artifact inspector integrate coherently?
- Any obvious visual inconsistencies between the two surfaces.

---

### `11_mobile_or_narrow_view_if_available.png`

**What to show:**
- The Companion UI at a narrow viewport width (mobile simulation or physical device).
- Load the same UAT note.
- Capture the full page from the top.

**What Claude Design should evaluate:**
- Does the layout adapt to narrow viewports?
- What happens to the right rail (outline) at narrow width?
- What happens to the Panel rail at narrow width?
- Is the note body still readable and primary?
- Are there any breakage states or visual collisions?
- If no mobile/narrow view is available, note this explicitly.

---

## Screenshot capture instructions

1. Start the runtime for the dev environment:
   ```
   PKM_ENVIRONMENT=dev scripts/start_full_system.sh
   ```
2. Start the Companion UI dev server:
   ```
   cd companion-ui/companion-app
   COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=0.0.0.0 PORT=8111 \
     python -m companion_ui.workspace.serve_dev_page
   ```
3. Open the UAT note:
   ```
   http://10.42.42.10:8111/?note_path=Companion_UI_Markdown_Feature_UAT.md
   ```
4. Capture each screenshot at 1280px+ width for desktop views.
5. For `11_mobile_or_narrow_view_if_available.png`, resize browser to ~375px or use a device.
6. Save screenshots as PNG files in this folder, named exactly as listed above.
