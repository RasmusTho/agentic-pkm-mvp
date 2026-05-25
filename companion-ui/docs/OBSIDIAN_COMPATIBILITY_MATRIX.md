---
name: Obsidian Compatibility Matrix
description: Source-of-truth matrix for Obsidian compatibility in Companion UI's note surface — phases, mutation risk, and explicit non-goals
doc_role: Compatibility specification
authority: SoT for Obsidian syntax compatibility decisions in Companion UI. Binding on all Companion UI renderer and editor implementation work.
owner: Companion UI / note surface
temporal_class: strategic
review_cadence: event-driven
last_reviewed: 2026-05-25
last_verified_against: |
  companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md,
  companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md,
  companion-ui/docs/UI_RUNTIME_BOUNDARIES.md,
  companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md,
  companion-ui/docs/CANVAS_SUGGESTION_FLOW.md,
  docs/COMPANION_UI_PRODUCT_SPEC.md,
  docs/ARCHITECTURE.md,
  docs/DESIGN_PRINCIPLES.md
---

# Obsidian Compatibility Matrix

## 1. Purpose and Scope

This document is the source-of-truth matrix for Obsidian compatibility in the Companion UI
note surface.

It defines:

- the compatibility target (Reading View-like, not Live Preview parity),
- the architectural posture governing how far Companion UI follows Obsidian conventions,
- a feature-by-feature matrix with phase, mutation risk, and test-fixture requirement,
- explicit non-goals and stop conditions.

This document is not an implementation spec. Implementation details live in
`companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md` and the bounded GitHub issues created
from this matrix.

---

## 2. Architectural Posture

**Obsidian remains the primary interaction surface for now.**

Companion UI is a cognitive prosthesis — a surface for reading, orienting, resuming, reviewing,
safely staging suggestions, inspecting provenance, and collaborating with agents around Markdown
notes. It is not an Obsidian replacement, not an Obsidian clone, and not a general-purpose
Markdown editor.

The note rendering surface in Companion UI must:

- reduce cognitive load by preserving Obsidian-familiar note semantics;
- render the note body consistently with how Obsidian presents it in Reading View;
- never become a hidden source of semantic authority over note content;
- never allow renderer or editor choices to bypass Panel, Canvas suggestion flow,
  GovernanceRouter, WriteGuard, receipts, or session-log provenance.

**Markdown files are the durable human source of truth.** DB/index/store projections are
rebuildable mirrors. The renderer is not semantic authority.

**Companion UI does not directly write vault files.** All mutations must route through the
governed runtime execution path (policy, WriteGuard, idempotency, deterministic note-writer,
receipt).

---

## 3. Compatibility Target

**Target: Obsidian Reading View-like behavior for a safe subset of Obsidian syntax.**

This means:

- The rendered output of a vault note in Companion UI should look and feel like Obsidian
  Reading View for supported constructs.
- Unsupported constructs render as diagnostics, placeholders, or source blocks — not silent
  failures.
- Plugin-dependent behavior is outside scope.
- Live Preview parity is explicitly out of scope.
- Full Obsidian clone is explicitly out of scope.

---

## 4. Explicit Non-Goals

The following are not targets for this workstream:

- Full Obsidian clone or visual pixel-parity.
- Obsidian Live Preview parity (rich WYSIWYG over raw Markdown).
- Plugin execution or plugin CSS compatibility.
- Dataview execution.
- Editable transclusion.
- Automatic link rename mutation.
- Task checkbox toggling until a governed write contract exists.
- Frontmatter editing until a governance route through Panel/governance exists.
- Custom CSS snippet compatibility.
- Cross-vault global search execution within the renderer.
- PDF viewer (unless already available as a safe viewer).
- Audio/video players (unless already available).
- Canvas diagram editing.

Companion UI does not claim to replace Obsidian. Both surfaces co-exist; Companion UI must
minimize friction for users who use Obsidian daily.

---

## 5. Compatibility Matrix

Legend:

- **Phase**: `Adopt now` | `Adopt soon` | `Spike` | `Diagnostic only` | `Inspiration only` | `Reject/defer`
- **Mutation risk**: `None (read-only)` | `Low (UI state only)` | `Governed (requires write contract)`
- **Fixture required**: `Yes` | `No`

### 5.1 CommonMark / Base Markdown

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Headings | `# H1` … `###### H6` | Render as heading elements with anchor IDs | Adopt now | None | Yes | Heading IDs needed for outline/link fragments |
| Paragraphs | Plain text blocks | Render as `<p>` | Adopt now | None | Yes | |
| Ordered lists | `1. item` | Render as `<ol>` | Adopt now | None | Yes | |
| Unordered lists | `- item` / `* item` | Render as `<ul>` | Adopt now | None | Yes | |
| Nested lists | Indented lists | Render nested | Adopt now | None | Yes | |
| Blockquotes | `> text` | Render as `<blockquote>` | Adopt now | None | Yes | Obsidian callouts override the bare blockquote for `[!type]` blocks |
| Horizontal rules | `---` / `***` | Render as `<hr>` | Adopt now | None | No | |
| Inline emphasis | `*em*` / `**strong**` / `***bold-em***` | Render appropriately | Adopt now | None | Yes | |
| Inline code | `` `code` `` | Render as `<code>` | Adopt now | None | Yes | |
| Fenced code blocks | ` ```lang\ncode\n``` ` | Render with language class; syntax-highlight where safe | Adopt now | None | Yes | See CodeBlockRenderer; Mermaid is a special fenced block case |
| Syntax highlighting | Language-tagged fenced blocks | Highlight via safe client-side library | Adopt now | None | Yes | Must not execute code |

### 5.2 GFM Extensions

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| GFM tables | `\| A \| B \|` | Render as table | Adopt now | None | Yes | remark-gfm |
| GFM task lists | `- [ ] item` / `- [x] item` | Render as visual checkbox; no toggle | Adopt now | Governed (toggling deferred) | Yes | Toggling is mutation; defer until governed write contract exists |
| Nonstandard task checkbox states | `- [/] item` / `- [-] item` etc. | Render as styled read-only checkbox | Adopt now | Governed | Yes | Visual representation only; do not normalize the symbol |
| GFM strikethrough | `~~text~~` | Render as `<s>` | Adopt now | None | Yes | |
| GFM autolinks | `https://...` | Render as external link | Adopt now | None | No | |
| GFM footnotes | `[^1]` | Render if remark-gfm supports it | Adopt soon | None | No | Low priority |

### 5.3 Standard Markdown Links and Images

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Ordinary Markdown links | `[text](url)` | Render as link; external URLs open externally | Adopt now | None | Yes | Internal relative paths route through link resolver |
| Ordinary Markdown images | `![alt](path)` | Render through VaultAssetResolver | Adopt now | None | Yes | Must not use file:// directly |

### 5.4 Obsidian Wikilinks

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Basic wikilink | `[[Note]]` | Parse and render as internal navigation link | Adopt now | None | Yes | |
| Wikilink with alias | `[[Note\|Alias]]` | Render Alias as display text | Adopt now | None | Yes | |
| Heading link | `[[Note#Heading]]` | Parse target + heading fragment | Adopt now | None | Yes | |
| Local heading link | `[[#Heading]]` | Scroll/focus within current document | Adopt now | None | Yes | |
| Nested heading link | `[[Note#H2#H3]]` if supported | Parse where possible; diagnostic otherwise | Adopt soon | None | No | Obsidian support is limited |
| Block link | `[[Note#^block-id]]` | Parse; render as link to anchor or diagnostic | Adopt now | None | Yes | Block ID anchors may not exist in rendered HTML |
| Local block link | `[[^local-block]]` | Same as block link scoped to current doc | Adopt now | None | Yes | |
| Wikilink with heading alias | `[[Note#Heading\|Alias]]` | Parse; render Alias | Adopt now | None | Yes | |
| Missing note link | Link to non-existent note | Render as visible missing-link diagnostic | Adopt now | None | Yes | Do not auto-create the note |
| Ambiguous note link | Link matches multiple notes | Render as ambiguous-link diagnostic | Adopt now | None | Yes | Do not resolve silently |
| Link rename mutation | Auto-update `[[Old]]` → `[[New]]` | Reject/defer | Reject/defer | Governed | No | Out of scope |

### 5.5 Obsidian Embeds

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Image embed | `![[image.png]]` | Render through VaultAssetResolver | Adopt now | None | Yes | |
| Image embed with width | `![[image.png\|100]]` | Parse width; apply to rendered image | Adopt now | None | Yes | |
| Image embed with width×height | `![[image.png\|100x145]]` | Parse both dimensions | Adopt now | None | Yes | |
| Note embed | `![[Some Note]]` | Diagnostic placeholder (render-only later) | Diagnostic only → Adopt soon | None | Yes | Full transclusion is complex; start with placeholder |
| Heading embed | `![[Note#Heading]]` | Diagnostic placeholder initially | Diagnostic only | None | Yes | |
| Block embed | `![[Note#^block-id]]` | Diagnostic placeholder initially | Diagnostic only | None | Yes | |
| PDF embed | `![[document.pdf]]` | Diagnostic placeholder unless safe viewer exists | Diagnostic only | None | Yes | |
| PDF embed with page | `![[document.pdf#page=3]]` | Parse page hint; show in placeholder | Diagnostic only | None | No | |
| Audio embed | `![[audio.mp3]]` | Diagnostic placeholder | Diagnostic only | None | No | |
| Video embed | `![[video.mp4]]` | Diagnostic placeholder | Diagnostic only | None | No | |
| Canvas embed | `![[diagram.canvas]]` | Diagnostic placeholder | Diagnostic only | None | Yes | |
| List embed | `![[Note^list-block]]` | Diagnostic placeholder | Diagnostic only | None | No | |
| Search embed | `![[query/...]]` | Diagnostic placeholder; do not execute query | Diagnostic only | None | No | Search execution is out of scope |
| Editable transclusion | In-place editing of embedded note | Reject/defer | Reject/defer | Governed | No | Cross-note mutation; out of scope |

### 5.6 Obsidian Callouts

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Basic callout | `> [!note]` | Render with type styling | Adopt now | None | Yes | |
| Callout with custom title | `> [!warning] My Title` | Render title text | Adopt now | None | Yes | |
| Foldable callout (collapsed) | `> [!tip]-` | Render collapsed; expand on click | Adopt now | Low (UI state) | Yes | Fold state is UI-local; no mutation |
| Foldable callout (expanded) | `> [!tip]+` | Render expanded by default | Adopt now | Low (UI state) | Yes | |
| Nested callouts | Callout inside callout | Render nested | Adopt now | None | Yes | |
| Callout with title only (no body) | `> [!note] Title only` | Render as title-only callout | Adopt now | None | Yes | |
| Unsupported/custom callout type | `> [!custom]` | Default to note-like visual treatment | Adopt now | None | Yes | Do not error |
| Markdown inside callout | `> [!note]\n> **bold** [[link]]` | Render nested Markdown/wikilinks | Adopt now | None | Yes | |
| Wikilinks/embeds inside callout | `> [!tip]\n> ![[img.png]]` | Render via same resolver pipeline | Adopt now | None | Yes | |

### 5.7 Properties / Frontmatter

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| YAML frontmatter | `---\ntitle: X\n---` | Render in read-only properties surface | Adopt now | None | Yes | Do not render as body text |
| Tags property | `tags: [foo, bar]` | Render as read-only tag chips | Adopt now | None | Yes | |
| Aliases property | `aliases: [Alt Name]` | Render as read-only values | Adopt now | None | Yes | |
| Malformed frontmatter | Invalid YAML | Show diagnostic, render body anyway | Adopt now | None | Yes | |
| Frontmatter editing | UI-side edit of properties | Reject/defer | Reject/defer | Governed | No | Requires governance route through Panel/governance |

### 5.8 Comments

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Obsidian comments | `%% comment %%` | Hidden in Reading View; available in source/inspect mode | Adopt soon | None | Yes | Comments must be parsed and stripped from rendered output |

### 5.9 Diagrams

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Mermaid fenced blocks | ` ```mermaid\n...\n``` ` | Render via controlled Mermaid component | Adopt now | None | Yes | Render-only; no interactive editing |
| MathJax / LaTeX | `$$...$$` / `$...$` | Render if safe schema can be defined | Adopt soon | None | No | Safety schema must be explicit before adoption |

### 5.10 HTML

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Inline HTML | `<span style="...">` | Sanitized or disabled via rehype-sanitize | Adopt now | None | Yes | Raw HTML must be sanitized; script execution forbidden |
| Unsafe HTML / script tags | `<script>...` | Strip/sanitize; never execute | Adopt now | None | Yes | |
| Remote images via HTML | `<img src="https://...">` | Block by default or require explicit policy | Adopt now | None | Yes | Remote image policy must be explicit and test-covered |

### 5.11 Plugins and Extended Syntax

| Feature | Syntax example | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|---|
| Dataview blocks | ` ```dataview\nTABLE...\n``` ` | Diagnostic placeholder; never execute | Diagnostic only | None | Yes | Do not execute Dataview queries |
| Other plugin code blocks | ` ```plugin-name\n...\n``` ` | Diagnostic placeholder | Diagnostic only | None | No | |
| Full plugin runtime | Any Obsidian plugin behavior | Reject/defer | Reject/defer | N/A | No | Out of scope |

### 5.12 Navigation and Orientation Affordances

| Feature | Companion UI target | Phase | Mutation risk | Fixture required | Notes |
|---|---|---|---|---|---|
| Note outline (heading navigation) | Read-only heading outline panel | Adopt soon | None | No | Must not mutate document |
| Hover/page preview | Read-only popover for internal links | Adopt soon | None | No | Bounded read-only rendering only; no unbounded recursion |
| Read-only backlinks | List of inbound links to current note | Adopt soon | None | No | Read from API; no in-renderer link scanning |
| Local graph | Visual graph of note relations | Inspiration only | None | No | Complex; deferred |
| Command palette | UI command dispatch | Inspiration only | N/A | No | Complex; deferred |
| Plugin compatibility | CSS/behavior from Obsidian plugins | Reject/defer | N/A | No | Out of scope |

---

## 6. Mutation / Governance Boundary

The following affordances are **read-only in Companion UI**:

- Note content rendering.
- Properties/frontmatter display.
- Wikilink/embed display.
- Callout expand/collapse (local UI state only).
- Outline navigation (scroll/focus; no rename).
- Hover preview (read rendering only).
- Backlinks display (read from API).

The following affordances **require a governed write contract** before they may be implemented:

- Task checkbox toggling.
- Frontmatter/property editing.
- Note creation from missing links.
- Automatic link rename/update.
- Inline note embed editing (transclusion editing).
- AI suggestion application (must route through Canvas body-edit lane or governance queue).

**No renderer implementation may bypass Panel, Canvas suggestion flow, GovernanceRouter,
WriteGuard, receipts, or session-log provenance.**

Editor adoption must not introduce write paths that are not governed by the existing contracts.
Milkdown, MDXEditor, CodeMirror, or any other rich editor must be adopted only after proving:

1. Obsidian-flavored Markdown round-trip preservation without silent mutation.
2. Frontmatter preservation.
3. Wikilink, embed, callout, comment, and Mermaid block preservation.
4. Write interception compatible with existing governance pipeline.

---

## 7. Phasing

### Phase 1 — Adopt now

Core note reading surface: basic Markdown, GFM, wikilinks, internal links, image embeds,
image sizing, callouts, Mermaid render-only, properties/frontmatter split, unsafe HTML
sanitization, unsupported syntax diagnostics.

Implementation target: VaultMarkdownRenderer wired to main note area. Parser, link resolver,
asset resolver, and sanitization boundaries in place. Fixture suite covers all Adopt-now rows.

### Phase 2 — Adopt soon

Note outline, hover/link preview, read-only backlinks, read-only properties panel, MathJax
(if safe schema defined), comments hidden in reading view but available in inspect/source mode.

### Phase 3 — Spike

Source-mode editor adapter (CodeMirror); rich editor spike (Milkdown, MDXEditor) against
Obsidian compatibility fixtures.

### Phase 4 — Diagnostic only → later adoption

Note embeds (full transclusion), heading/block embeds, PDF/audio/video/canvas/search embeds.
Upgrade from diagnostic to adopted when a safe implementation path is confirmed and governed.

### Phase 5 — Reject/defer

Plugin runtime, Dataview execution, editable transclusion, automatic link rename mutation,
frontmatter editing without governance route, full Live Preview parity, full Obsidian clone.

---

## 8. Stop Conditions

- If a renderer or editor choice would allow bypassing Panel, Canvas suggestion flow,
  GovernanceRouter, WriteGuard, receipts, or session-log provenance: **stop, do not proceed**.
- If a renderer or editor choice requires changing stored Markdown semantics: **stop**.
- If a feature marked Adopt now requires arbitrary file-system access from the browser:
  **stop and split the asset-resolution boundary into a separate governed issue**.
- If plugin-execution behavior is required for a feature: **stop and mark Reject/defer**.
- If a rich editor (Milkdown, MDXEditor) cannot preserve Obsidian-flavored Markdown in a
  round-trip test: **reject or defer the editor choice until the round-trip is proven**.
- If MathJax safety schema cannot be defined without allowing script execution: **stay at
  Diagnostic only until the schema is defined**.

---

## 9. Source Anchors and Related Docs

- `companion-ui/docs/VAULT_MARKDOWN_RENDERER_CONTRACT.md` — renderer contract and component boundaries
- `companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md` — hosting and vault-boundary rules
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — cognitive boundary constraints
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md` — Panel write-back boundary
- `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` — Canvas suggestion flow governance
- `docs/COMPANION_UI_PRODUCT_SPEC.md` — product mode model and non-goals
- `docs/DESIGN_PRINCIPLES.md` — boundary-first design and explicit mutation authority
- `docs/ARCHITECTURE.md` — current runtime architecture
- `docs/FRONTMATTER.md` — frontmatter rules and ownership
