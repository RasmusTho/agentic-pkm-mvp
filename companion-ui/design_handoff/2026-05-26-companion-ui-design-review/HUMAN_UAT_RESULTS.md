# Human UAT Results — Companion UI Markdown Feature UAT

## Test context

| Field | Value |
|---|---|
| Environment | dev |
| Vault | Niflheim |
| UAT note | `Companion_UI_Markdown_Feature_UAT.md` |
| UI URL | `http://10.42.42.10:8111/?note_path=Companion_UI_Markdown_Feature_UAT.md` |
| Tailscale URL | `http://100.113.104.116:8111/?note_path=Companion_UI_Markdown_Feature_UAT.md` |
| Baseline | `origin/main` at `29f81427` or later |
| Tracking issue | #1332 (not visible to Claude Design — all relevant content is summarized here) |

The UAT note `Companion_UI_Markdown_Feature_UAT.md` contains examples of all Markdown
features under test. It was loaded through the runtime API and observed in the browser.

---

## Result matrix

| Feature area | Result | Notes |
|---|---|---|
| Typography / design handoff alignment | **FAIL** | Rendered typography does not match intended design tokens. Heading scale, paragraph rhythm, and spacing need correction. |
| Basic Markdown rendering | **PASS** | Headings, paragraphs, ordered and unordered lists, blockquotes, emphasis, inline code, horizontal rules all render. |
| Callouts (`> [!type]`) | **PASS** | Callout blocks render with type styling. |
| GFM Tables | **PASS** | Tables render with visible structure. |
| Outline / right rail navigation | **PASS** | Headings appear in the outline rail; clicking navigates to the heading. Panel separation is maintained. |
| Panel / governance separation | **PASS** | The Panel rail is visually distinct from the note body. Panel and Canvas surfaces remain separate. |
| GFM Task lists | **PASS (functional) / FAIL (design)** | Checkboxes render with visually distinct checked and unchecked states. Inline code within task items is visible. Read-only behavior is correct. Visual alignment and sizing need design review. |
| Fenced code blocks | **AMBIGUOUS** | Code blocks were not captured in the available screenshots. Functional rendering is assumed from earlier observations but visual alignment (font, spacing, contrast, language label) is unconfirmed. A dedicated screenshot is still needed. |
| Mermaid diagrams | **FAIL** | Mermaid fenced blocks do not render. The block appears as raw text or produces an error. |
| Images | **AMBIGUOUS** | A missing-image placeholder state was observed. A real vault image asset was not available during UAT, so real image rendering remains unconfirmed. |
| Internal / wiki links | **FAIL** | Wikilinks (`[[Note Name]]`) do not resolve and do not navigate. Rendered as raw text or as a non-functional link. |
| Body edit (note mutation) | **FAIL** | No body edit functionality is wired to the browser UI. Attempting to edit the note body produces no visible effect. The Canvas body-edit API exists in the backend but is not connected. |

---

## Observations from screenshots

Screenshots `01_full_workspace_top.png`, `02_note_body_uat_table.png`,
`03_outline_left_rail_heading_hierarchy.png`, `05_callouts.png`, and
`06_task_lists_and_tables.png` are now included in this package.

**Layout clarification:** The outline is the LEFT rail. The Panel / governance is the RIGHT
rail. Some earlier drafts of this document referred to the "right rail" for the outline —
this was incorrect. The outline is left; Panel is right.

**Concrete visual problems observed:**

1. **Heading hierarchy is insufficiently differentiated.** H2 and H3 headings are nearly
   the same visual size. "2. Outline and right rail navigation" (H2) and "2.1 First nested
   heading" (H3) are indistinguishable at a glance.

2. **All headings are too large relative to body text.** The heading scale creates a
   fragmented reading experience. H2 through H4 need to step down more sharply from H1.

3. **Metadata band is too prominent.** The dense metadata block above the note title
   (breadcrumb, artifact ID, content hash, properties, tags) occupies significant space
   and reads as infrastructure, not orientation context.

4. **Callouts are a visual success.** Color-coded by type (Note=blue, Tip=teal,
   Warning=yellow/orange, Danger=red) with visible type labels. This is the strongest
   visual element in the current UI and should be preserved.

5. **Task list checkboxes render correctly.** Checked and unchecked states are visually
   distinct. Inline code within task items renders correctly.

6. **Panel rail shows informative state, not a blank placeholder.** The right rail actively
   shows: "No active Panel proposals", "Panel ready", "Suggestions are idle", "Find is
   unavailable...", "read-only". The visual weight and density of these labels is not yet
   designed for cognitive clarity, but the functional state is communicative.

---

## Interpretation

### What the UAT results mean overall

**Markdown rendering is not completely broken.** The renderer delivers basic reading capability.
A user can load a note and read it. The fundamental note-loading pipeline works.

**Basic renderer capability exists and should be preserved.** Passing features — callouts, tables,
task lists, outline navigation, Panel state display — should not be regressed by design changes.

**Visual design alignment is not acceptable.** The heading hierarchy, metadata prominence, and
overall typography do not match the intended cognitive prosthetic purpose. This is the primary
design problem to solve.

**Body edit is the main blocker for deeper editor UAT.** Until body edit is wired up in the
browser, all tests that depend on mutation (task checkbox toggling as a write, in-place edit,
Canvas body-edit flows) cannot be completed. Design should treat the note body as a read-only
surface for this review and specify what edit affordances should look like when available.

**Mermaid and internal links are separate functional problems, not design problems.** They are
implementation failures that need their own bounded implementation work. Design can note where
they appear and what the degraded/missing state should look like, but fixing them is not a
design task.

**The outline (left rail) can be accepted as a functional foundation.** Design review should
focus on its visual weight, font size, and spatial relationship to the note body.

**Task lists render — the issue is design alignment, not functional failure.** The checkboxes
work. Design should specify the correct visual treatment.

**Code blocks still need a dedicated screenshot.** Functional rendering is assumed but not
confirmed visually. A screenshot of the code block section of the UAT note is still needed.

**Images need a real asset fixture.** The missing-image placeholder state is observable, but
real image rendering cannot be confirmed until a vault image asset is included in the UAT note.
Design should specify what both the successful and missing states should look like.

---

## Functional blockers vs design problems

| Problem | Category |
|---|---|
| Typography misalignment | Design problem — can be fixed by CSS/design tokens |
| Body edit not wired | Functional/implementation blocker — not a design problem |
| Mermaid fails | Functional/implementation blocker — design should specify the error/missing state |
| Internal wikilinks fail | Functional/implementation blocker — design should specify the missing/unresolved state |
| Task list retest needed | Test coverage gap — design should specify correct rendering |
| Code block retest needed | Test coverage gap — design should specify correct rendering |
| Image asset missing | Test fixture gap — design should specify both states |

---

## 2026-05-30 retest — task lists & code blocks (#1348)

Retested against `origin/main` after #1410 (Markdown list rendering) merged. Observed via local static render of the UAT note sections driven in a real browser at 1280×900 (the live runtime had not yet been redeployed with #1410).

### Task list retest — **PASS**

The renderer now produces correctly nested lists and unambiguous task states:

- Unchecked tasks render an empty checkbox with `data-task-state=" "`.
- Checked tasks render a filled accent checkbox with a check tick **and** an Obsidian-style completed treatment (`text-decoration: line-through`, muted color) keyed on `data-task-state="x"`.
- Bold and inline code inside task items render (`<strong>`, `<code>`).
- Nested ordered/unordered list items now indent under their parent (nested `<ol>` restarts numbering at 1 instead of continuing 4/5).

Evidence: `getComputedStyle` on the checked item reported `text-decoration-line: line-through` with `checkbox.checked === true`; the nested ordered list rendered as a nested `<ol>` inside the parent `<li>`. Covered by `tests/companion_ui/test_markdown_renderer_lists.py`. Supersedes the earlier "Task list retest needed" gap.

### Code block retest — **PASS (functional)**

Fenced code blocks render as `<pre class="vault-code-block" data-language="…"><code class="language-…">`, both with a language hint (python/json/ts observed in the live note) and without one (plain block). Monospace, contained horizontal scroll, visible language attribute. Supersedes the earlier "Fenced code blocks AMBIGUOUS" row.

### Syntax highlighting decision

**Not required for current acceptance.** Code blocks are a faithful, readable monospace surface with a language label; token-level syntax highlighting is a reading-comfort enhancement, not a correctness requirement for the cognitive-workspace MLP. No follow-up issue filed; revisit only if a future spec mandates highlighted code.
