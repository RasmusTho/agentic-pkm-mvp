---
name: Vault Markdown Renderer Contract
description: Contract for read-only Companion UI rendering of vault Markdown using Obsidian-compatible semantics — parser, resolver, component, security, and governance boundaries
doc_role: Implementation contract
authority: SoT for Companion UI vault Markdown rendering. Binding on all renderer, parser, link resolver, asset resolver, and editor-adapter implementation work.
owner: Companion UI / note surface
temporal_class: strategic
review_cadence: event-driven
last_reviewed: 2026-05-25
last_verified_against: |
  companion-ui/docs/OBSIDIAN_COMPATIBILITY_MATRIX.md,
  companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md,
  companion-ui/docs/UI_RUNTIME_BOUNDARIES.md,
  companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md,
  companion-ui/docs/CANVAS_SUGGESTION_FLOW.md,
  docs/COMPANION_UI_PRODUCT_SPEC.md,
  docs/DESIGN_PRINCIPLES.md,
  docs/ARCHITECTURE.md
---

# Vault Markdown Renderer Contract

## 1. Purpose

Define the contract for read-only Companion UI rendering of vault Markdown using
Obsidian-compatible semantics.

This document governs:

- the document model produced by the parser,
- the responsibilities of the renderer, link resolver, and asset resolver,
- the security model for browser-side rendering,
- the governance boundary separating rendering from mutation,
- the test contract for fixture-driven verification,
- stop conditions for renderer and editor-adapter work.

This document does not implement any component. Implementation belongs to bounded GitHub
issues sourced from this contract and from
`companion-ui/docs/OBSIDIAN_COMPATIBILITY_MATRIX.md`.

---

## 2. Non-Goals

The following are explicitly outside this contract:

- Full Obsidian clone or visual pixel-parity.
- Obsidian Live Preview parity.
- Plugin execution or plugin CSS compatibility.
- Dataview execution.
- Any renderer-side vault file writes.
- Editor selection or rich-editor adoption.
- In-place editing, autosave, or task checkbox toggling.
- Frontmatter editing.
- Editable transclusion or automatic link rename mutation.
- Remote file loading outside the API boundary.
- Production UI styling or design-token application.

---

## 3. Architecture

The renderer sits between the runtime API and the browser note surface.

```
Runtime API
  └── GET /api/companion/workspace (artifact.raw_markdown)
        │
        ▼
  [parseVaultMarkdown]
        │  produces VaultMarkdownDocument
        ▼
  [VaultMarkdownRenderer]  ←── VaultLinkResolver (from API)
        │                  ←── VaultAssetResolver (from API)
        │
        ▼
  Browser note surface (read-only)
```

Key invariants:

- **Vault files are never accessed directly.** All content comes through the runtime API.
- **Vault paths are never exposed in the browser.** The renderer works with API-provided content
  and resolver responses.
- **The renderer is stateless with respect to vault state.** It does not cache, merge, or
  infer note content.
- **The renderer does not call write endpoints.** Rendering is a read-only operation.
- **Resolver calls are the only side effects allowed during render.**

---

## 4. Data Model

The following types define the conceptual data model. Implementations may use equivalent
representations in the target language (TypeScript, Python, etc.).

### VaultMarkdownDocument

```typescript
type VaultMarkdownDocument = {
  rawMarkdown: string
  frontmatter: string | null        // raw YAML frontmatter string or null
  bodyMarkdown: string              // markdown body after frontmatter extraction
  diagnostics: MarkdownDiagnostic[]
  headings: HeadingRef[]
  blockIds: BlockIdRef[]
  wikilinks: WikiLinkRef[]
  embeds: EmbedRef[]
  assetRefs: AssetRef[]
}
```

### MarkdownDiagnostic

```typescript
type MarkdownDiagnostic = {
  severity: "info" | "warning" | "error"
  code: string                      // stable diagnostic code for testing
  message: string
  sourceRange?: SourceRange         // optional: character range in rawMarkdown
}
```

### HeadingRef

```typescript
type HeadingRef = {
  level: 1 | 2 | 3 | 4 | 5 | 6
  text: string
  anchor: string                    // slug for in-page linking
  sourceRange?: SourceRange
}
```

### BlockIdRef

```typescript
type BlockIdRef = {
  blockId: string                   // the ^block-id string
  anchor: string                    // resolved anchor in rendered HTML
  sourceRange?: SourceRange
}
```

### WikiLinkRef

```typescript
type WikiLinkRef = {
  raw: string                       // the full [[...]] text
  target: string                    // note target (may include extension)
  alias?: string                    // display text if alias present
  heading?: string                  // heading fragment if present
  blockId?: string                  // block ID fragment if present
  localOnly?: boolean               // true for [[#heading]] and [[^block-id]]
}
```

### EmbedRef

```typescript
type EmbedRef = {
  raw: string                       // the full ![[...]] text
  target: string                    // embed target
  kind: "image" | "note" | "pdf" | "audio" | "video" | "canvas" | "unknown"
  width?: number                    // parsed from |100 or |100x145
  height?: number                   // parsed from |100x145
  heading?: string                  // heading fragment for note embeds
  blockId?: string                  // block ID fragment for block embeds
}
```

### AssetRef

```typescript
type AssetRef = {
  raw: string                       // the original markdown image syntax
  target: string                    // image path or URL
  alt?: string
}
```

### LinkResolution

```typescript
type LinkResolution =
  | { kind: "resolved"; notePath: string; displayText: string; heading?: string; blockId?: string }
  | { kind: "missing"; displayText: string; reason: string }
  | { kind: "ambiguous"; displayText: string; candidates: string[] }
```

### AssetResolution

```typescript
type AssetResolution =
  | { kind: "allowed"; src: string; displayName: string; width?: number; height?: number }
  | { kind: "missing"; displayName: string; reason: string }
  | { kind: "blocked"; displayName: string; reason: string }
  | { kind: "unsupported"; displayName: string; reason: string }
```

---

## 5. Parser Responsibilities

`parseVaultMarkdown(rawMarkdown: string): VaultMarkdownDocument`

The parser:

- **Preserves** `rawMarkdown` without modification.
- **Extracts frontmatter** (YAML between opening and closing `---` delimiters) into
  `frontmatter`; sets it to `null` if absent.
- **Produces `bodyMarkdown`** as the portion of `rawMarkdown` after frontmatter extraction,
  without any semantic change to the text.
- **Extracts `headings`** with level, text, and anchor slug.
- **Extracts `blockIds`** — Obsidian block ID markers (`^block-id`) with their anchors.
- **Extracts `wikilinks`** — all `[[...]]` patterns including aliases, heading fragments,
  block ID fragments, and local-only variants.
- **Extracts `embeds`** — all `![[...]]` patterns with classification, size hints, and
  sub-target fragments.
- **Extracts `assetRefs`** — standard Markdown image syntax `![alt](path)`.
- **Extracts Obsidian comments** — `%% ... %%` patterns; these are suppressed in rendered
  output but may be available in source/inspect mode.
- **Emits `diagnostics`** for malformed frontmatter (parse error), unrecognized embed types,
  and syntax that falls into the Diagnostic-only phase.
- **Does not mutate** source text.
- **Does not resolve** links or assets (that is the resolver's job).
- **Does not render** anything (that is the renderer's job).

---

## 6. Renderer Responsibilities

`VaultMarkdownRenderer` takes a `VaultMarkdownDocument` and produces browser-safe rendered
output (HTML via React or equivalent).

### Required sub-renderers

| Component | Responsibility |
|---|---|
| `PropertiesRenderer` | Render frontmatter as read-only structured metadata surface |
| `InternalLinkRenderer` | Render wikilinks using `VaultLinkResolver`; display resolved/missing/ambiguous states |
| `ObsidianEmbedRenderer` | Render embeds using `VaultAssetResolver`; dispatch by `kind` |
| `VaultImageRenderer` | Render image embeds and standard Markdown images via `VaultAssetResolver` |
| `ObsidianCalloutRenderer` | Detect and render `> [!type]` callouts; local fold state; nested callouts |
| `MermaidBlockRenderer` | Render fenced `mermaid` blocks via controlled Mermaid component with error boundary |
| `CodeBlockRenderer` | Render fenced code blocks with syntax highlighting; must not execute code |
| `UnsupportedBlockDiagnostic` | Render a visible diagnostic for Dataview, plugin blocks, and unsupported constructs |

### Future sub-renderers (do not implement now)

| Component | Purpose |
|---|---|
| `NoteOutline` | Read-only outline from `headings` |
| `LinkPreview` | Hover/focus preview popover for internal links |

### Renderer invariants

- The renderer does not call write endpoints.
- The renderer does not read vault files directly.
- A resolved internal link emits `<a class="vault-wikilink" data-link-state="resolved" href="?note_path=…">`.
  A heading fragment is emitted as the slugified heading anchor (`#some-heading`,
  matching the rendered `<h_ id>`) so the link scrolls to the heading; a block-id
  fragment keeps the literal `#^block-id` form. Resolution requires the
  `VaultLinkResolver` to be seeded with the active-vault link index; with an empty
  index every link stays diagnostic. The workspace seeds that index from the
  read-only `GET /api/companion/vault-link-index` endpoint (#1431) — a complete
  note-path listing the resolver expands into lookup keys; the UI never reads the
  vault filesystem, and a failed/absent fetch degrades to the empty (diagnostic)
  index.
- The renderer does not emit navigation events as mutations.
- The renderer does not store resolved content in durable state.
- Clicking an internal link is a navigation event, not a mutation.
- Expanding or folding a callout is local UI state, not a mutation.
- Rendering frontmatter/properties is read-only.
- Toggling task checkboxes is out of scope until a governed write contract exists.
- Unsupported constructs render as `UnsupportedBlockDiagnostic`, not as silent gaps.

---

## 7. Resolver Responsibilities

### VaultLinkResolver

```typescript
interface VaultLinkResolver {
  resolve(params: {
    notePath: string       // path of the note being rendered
    rawTarget: string      // wikilink target string
    heading?: string
    blockId?: string
    alias?: string
  }): LinkResolution
}
```

The resolver:

- Returns `resolved`, `missing`, or `ambiguous` — never throws or returns undefined.
- Does not create missing notes.
- Does not rename or update links.
- Does not cache results across note loads (caching is an implementation concern, not a contract).

The `resolved` variant provides the `notePath` needed for navigation intent emission.
Navigation intent must be emitted by the renderer, not executed as a mutation.

### VaultAssetResolver

```typescript
interface VaultAssetResolver {
  resolve(params: {
    notePath: string
    rawTarget: string
    kind: "markdown-image" | "obsidian-embed"
  }): AssetResolution
}
```

The resolver:

- Returns `allowed`, `missing`, `blocked`, or `unsupported` — never throws.
- Does not read vault files directly.
- Does not expose vault filesystem paths to the browser.
- `blocked` is used when the asset policy forbids the request (e.g., unsupported embed type
  in the current phase, or remote image blocked by policy).
- `unsupported` is used for embed kinds in the Diagnostic-only phase.

---

## 8. Security Model

### Hard rules

1. **No direct local file access.** The renderer and resolvers must not use
   `file://`, `fs.readFileSync`, or equivalent to read vault content.
2. **No vault path exposure.** Vault filesystem paths must never appear in browser-side
   HTML, scripts, or network requests.
3. **All local assets through VaultAssetResolver.** Local images and embeds must be
   resolved through the resolver, which proxies through the runtime API.
4. **All internal navigation through VaultLinkResolver.** Internal links must not be
   resolved directly to vault paths in the browser.
5. **Raw HTML sanitized or disabled.** rehype-sanitize (or equivalent) must be applied
   after all plugin transformations. Sanitization schema must be explicit and tested.
6. **Script execution forbidden.** `<script>` tags, `javascript:` URLs, and inline
   event handlers must be stripped by sanitization.
7. **Mermaid render-only with error boundary.** The **server** renderer never executes
   Mermaid and makes no network/file calls: it emits a stable, source-preserving placeholder
   (`pre.vault-mermaid > code.language-mermaid`) for well-formed source and degrades clearly
   invalid source to the #1340 failed-embed partial. SVG rendering is delegated to a
   **sandboxed client runtime on the workspace dev page** (`securityLevel: 'strict'`,
   `suppressErrorRendering: true`); the Mermaid bundle is imported only when at least one
   placeholder is present. A Mermaid render failure must be caught and rewritten to the same
   `[data-testid="failed-embed"][data-kind="mermaid"]` partial — no parallel error visual,
   no leaked Mermaid error graphic — never propagating as a crash (#1344).
8. **Dataview and plugin code must not execute.** Fenced blocks with plugin names render as
   `UnsupportedBlockDiagnostic` or `CodeBlockRenderer` without execution.
9. **Remote image policy must be explicit and test-covered.** The default policy must block
   remote images or require explicit opt-in. The policy must be enforced by `VaultAssetResolver`
   or the sanitization layer, not left to browser default.
10. **Renderer must not call write endpoints.** No `POST`, `PUT`, `PATCH`, or `DELETE` calls
    may originate from renderer code.

### Recommended library stack

For React-based implementation:

- `react-markdown` — rendering base (CommonMark + custom component hooks)
- `remark-gfm` — GFM tables, task lists, strikethrough, autolinks, footnotes
- `rehype-sanitize` — strict post-transform HTML sanitization with project schema
- Custom components for wikilinks, callouts, Mermaid, embeds, properties, diagnostics

The sanitization schema must explicitly allow only the tags and attributes required by the
renderer. It must not use the default permissive schema without review.

---

## 9. Governance Boundary

The following table summarizes what the renderer may and may not do:

| Action | Allowed | Notes |
|---|---|---|
| Display note content | Yes | Read-only |
| Display frontmatter/properties | Yes | Read-only surface |
| Display resolved wikilinks | Yes | Link text and styling |
| Display missing/ambiguous link diagnostics | Yes | Required |
| Emit navigation intent on link click | Yes | Navigation only; not mutation |
| Expand/collapse callout | Yes | Local UI state only |
| Display outline | Yes (phase 2) | Scroll/focus; not mutation |
| Display hover preview | Yes (phase 2) | Read-only rendering |
| Display read-only backlinks | Yes (phase 2) | From API; not renderer-computed |
| Toggle task checkboxes | No | Requires governed write contract |
| Edit frontmatter/properties | No | Requires governance route |
| Create missing notes from links | No | Mutation; out of scope |
| Rename/update links | No | Mutation; out of scope |
| Edit embedded notes | No | Cross-note mutation; out of scope |
| Apply AI suggestions via renderer | No | Must use Canvas body-edit lane or governance queue |
| Execute Dataview queries | No | Out of scope |
| Execute plugin code | No | Out of scope |
| Write vault files directly | No | API boundary rule |
| Autosave rendered state | No | Renderer is stateless |

**AI suggestions applied through the renderer are not allowed.** Suggestion application must
route through the Canvas body-edit lane or the governance queue lane, not through in-place
renderer editing.

---

## 10. Test Contract

All renderer, parser, resolver, and sub-component implementations must be covered by
fixture-based tests.

### Fixture location

Fixtures live under:

```
companion-ui/companion-app/tests/fixtures/obsidian-renderer/
```

If no fixture convention exists at implementation time, create the directory at this path
and document the choice in the implementing issue.

### Required fixture files

| File | Covers |
|---|---|
| `basic.md` | CommonMark headings, paragraphs, lists, blockquotes, emphasis, code |
| `frontmatter-properties.md` | YAML frontmatter, tags, aliases, malformed YAML |
| `wikilinks.md` | All wikilink variants: basic, alias, heading, block, local, missing, ambiguous |
| `embeds-images.md` | Image embeds, size hints, standard images, unsupported embed types |
| `callouts.md` | Basic, custom title, foldable +/−, nested, title-only, unsupported type |
| `mermaid.md` | Valid Mermaid, invalid Mermaid, Mermaid inside callout |
| `comments-and-html.md` | Obsidian comments `%% %%`, safe inline HTML, unsafe HTML/script |
| `missing-links-assets.md` | Missing note links, missing images, ambiguous links, blocked assets |
| `full-smoke.md` | All feature categories combined in a realistic note |

### Fixture content requirements

Every fixture file must include at minimum:

- YAML frontmatter with at least `title`, `tags`, and `aliases`.
- A representative sample of the constructs in its category.
- At least one unsafe, missing, or unsupported case where applicable.
- No executable code, no real vault paths, no real user data.

The `full-smoke.md` fixture must include all of:

- Frontmatter with tags and aliases.
- H1–H3 headings.
- GFM table.
- GFM task list (standard and nonstandard states).
- Wikilinks: basic, alias, heading, block, local heading, local block, missing.
- Image embed: basic, width hint, width×height hint.
- Callout: basic, custom title, foldable, nested.
- Fenced Mermaid block.
- Fenced code block with language.
- Obsidian comment `%% hidden %%`.
- Unsafe HTML `<script>` tag.
- Dataview fenced block.

### Test coverage targets

- Parser: every WikiLinkRef variant, every EmbedRef variant, frontmatter extraction,
  comment extraction, block ID extraction, diagnostics for malformed input.
- Link resolver: resolved, missing, ambiguous paths.
- Asset resolver: allowed, missing, blocked, unsupported paths.
- Renderer: every fixture file passes without crash; unsafe HTML is stripped; diagnostics
  appear for unsupported constructs; write endpoints are not called.
- Security: script tags stripped, `file://` URLs blocked, remote images follow policy.

---

## 11. Stop Conditions

- If renderer implementation would call a write endpoint: **stop**.
- If resolver implementation would read vault files directly: **stop**.
- If sanitization schema would allow `<script>` or `javascript:` : **stop**.
- The server Mermaid path emits a source placeholder + diagnostics only; client-side SVG
  rendering runs in a sandboxed runtime (`securityLevel: 'strict'`) on the workspace dev page,
  loaded only when a placeholder is present (#1344). If a future surface cannot load that
  sandboxed runtime, it **falls back to the placeholder/diagnostic** rather than executing
  Mermaid unsafely.
- If any editor adapter (CodeMirror, Milkdown, MDXEditor) cannot guarantee no autosave or
  direct vault write: **reject the adapter**.
- If a rich editor cannot prove Obsidian-flavored Markdown round-trip in fixture tests:
  **defer the editor until round-trip is proven**.
- If frontmatter editing is requested before a governance route exists: **stop and create a
  governed issue**.
- If task checkbox toggling is requested before a governed write contract exists: **stop**.

---

## 12. Future Editor-Adapter Boundary

When a rich editor (CodeMirror, Milkdown, MDXEditor, or equivalent) is considered:

### Required pre-conditions before adoption

1. Obsidian-flavored Markdown round-trip passes all fixture tests without silent mutation.
2. Frontmatter preservation proven in fixture tests.
3. Wikilink, embed, callout, Obsidian comment, and Mermaid block preservation proven.
4. MDX/JSX disabled or safely sandboxed if using MDXEditor.
5. No autosave or direct vault write without explicit user action.
6. Write interception is compatible with Panel/Canvas/GovernanceRouter/WriteGuard contracts.

### NoteEditorAdapter conceptual interface

Any editor adoption must implement or conform to a `NoteEditorAdapter` contract:

```typescript
interface NoteEditorAdapter {
  getMarkdown(): string               // current editor Markdown content
  setMarkdown(markdown: string): void // set content programmatically
  getSelection(): SelectionRange | null
  applyBodyPatch(patch: BodyPatch): void  // governed patch from Canvas/Panel
  focusBlock?(blockId: string): void  // optional; focus a specific block
}
```

Rules for any editor adapter:

- `getMarkdown()` must return raw Markdown without mutation.
- `setMarkdown()` must accept Obsidian-flavored Markdown without normalizing it.
- `applyBodyPatch()` must be the only write path; it must route through the governance
  pipeline, not bypass it.
- No autosave or background write behavior is permitted.
- The adapter must not expose vault paths in its internal state or API surface.

### Spike posture

Editor adoption follows a spike → fixture roundtrip → governed wire-up sequence.
No editor adapter may be promoted to production until the spike produces a
documented recommendation (adopt, defer, or reject) and the round-trip fixture test passes.

---

## 13. Relationship to Other Docs

| Document | Relationship |
|---|---|
| `companion-ui/docs/OBSIDIAN_COMPATIBILITY_MATRIX.md` | Feature-by-feature phase assignments; upstream of this contract |
| `companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md` | Hosting, vault-boundary, and API-only access rules |
| `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` | Cognitive boundary constraints |
| `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md` | Panel write-back boundary; governs suggestion application path |
| `companion-ui/docs/CANVAS_SUGGESTION_FLOW.md` | Canvas body-edit lane; the governed path for AI suggestion application |
| `docs/COMPANION_UI_PRODUCT_SPEC.md` | Product mode model; Companion UI non-goals |
| `docs/DESIGN_PRINCIPLES.md` | Explicit mutation authority and boundary-first design |
| `docs/FRONTMATTER.md` | Frontmatter rules and write contract |
| `docs/ARCHITECTURE.md` | Current runtime architecture |
