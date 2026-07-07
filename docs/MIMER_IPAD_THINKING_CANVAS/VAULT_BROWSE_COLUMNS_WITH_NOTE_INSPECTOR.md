---
name: Vault Browse Columns With Note Inspector
description: Fill the iPad canvas columns — source list drives an item list, item selection renders the note with a metadata inspector; hardware-keyboard navigation. Read-only.
task_id: MIPAD-02
source_anchor: docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md :: §2 Platform footprint
parent_capability: Mimer iPad Thinking Canvas
prerequisites: [MIPAD-01]
depends_on: [ADAPTIVE_THREE_COLUMN_SHELL_ON_IPAD]
can_parallelize_with: []
---

# Vault Browse Columns With Note Inspector

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).

## Purpose

"Source/list · item · inspector — the review feed and its context at once." MIPAD-01 built the
skeleton; this task makes the canvas useful for reading and thinking: pick a source (lens or vault
folder) → see its items → read the selected note with its metadata visible. Strictly read-only.

## What This Task Does

- **Content column:** for the Notes-browser source, list folders/`.md` files via the existing
  `VaultFileStore.listEntries(in:)` (the `NoteBrowserView` mechanism, re-hosted as a column); for
  lens sources, the lens's existing list (pending entities, interest entries, attention items)
  becomes the column content.
- **Detail column:** selected note renders with the existing `MarkdownRendererView`, plus an
  **inspector panel** (trailing pane or toggleable overlay) showing the note's frontmatter
  metadata: `uuid`, zone/origin fields if present, `agent_provenance` block if present, file
  modification date. Parsing uses `YggdrasilCore.FrontmatterDocument` — no new parser.
- **Hardware keyboard:** arrow/`Tab` moves between columns and list items; `⌘F` (where a list is
  filterable) focuses a local filter field; `⌘I` toggles the inspector. Use SwiftUI
  `.keyboardShortcut`/focus APIs — no private API.
- Vault listing stays filesystem-based by contract: the client API surface has no
  folder-listing/recent/backlinks endpoint (`docs/contracts/MIMER_CLIENT_CONTRACT.md` §4), and no
  hidden client-side index may be built to compensate (§3 invariant 3) — directory enumeration on
  demand, computed transiently.

## Concretely

On an iPad Pro simulator: sidebar "Notes" → content column lists the vault root; selecting a
folder pushes its entries; selecting `Projects/foo.md` renders it in the detail column; `⌘I`
reveals `uuid: …`, `modified: …`. Selecting sidebar "Entities" shows the pending review queue as
the content column (read-only here; actions come in MIPAD-03).

## Why This Matters

This is the daily "thinking surface" the iPad exists for. It also establishes the
selection/navigation model MIPAD-03/04 attach their actions to — if selection state is wrong here,
the write-bearing slices inherit the confusion.

## Acceptance Criteria

- [ ] Folder → item → note flow works in the three columns; note body renders identically to the
  iPhone renderer. `Verify:` bifrost
  `Yggdrasil/YggdrasilUITests/MimerCanvasUITests.swift::testBrowseFolderToNoteAcrossColumns` (new,
  iPad destination).
- [ ] Inspector shows frontmatter metadata (uuid, provenance when present) for the selected note;
  a note with no uuid still renders with the inspector stating the absence (uuid is lineage
  metadata, never a render gate). `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/NoteInspectorModelTests.swift::testInspectorFieldsFromFrontmatterAndMissingUuid`
  (new; unit-level on the inspector's view model).
- [ ] Keyboard navigation: column focus traversal and `⌘I` inspector toggle work. `Verify:`
  bifrost `MimerCanvasUITests.swift::testKeyboardColumnTraversalAndInspectorToggle` (new).
- [ ] No write call sites added: the slice introduces no call to `VaultFileStore.write` /
  `readModifyWrite`. `Verify:` PR review checklist item + `git grep` in the PR diff shows no new
  write/readModifyWrite call sites (recorded in the PR body).

## How to Verify (Pre-Merge)

- bifrost CI green on both simulator destinations; `swiftlint --strict` clean.
- The no-new-writes check is a diff-level assertion stated in the PR body (INV-B2-5).

## Out of Scope

- Merge/reject actions on the entity queue (MIPAD-03).
- Editing, annotation, drag-drop (MIPAD-04); the detail column may reuse the existing
  `NoteDetailView` editor only if it is presented read-only here.
- Recent-notes/backlinks surfaces (would need either client-side scanning or a new hub endpoint —
  a named contract follow-on, not B2 scope).

## Related Docs

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §3 (invariant 3), §4 (no listing endpoint — FS is the read surface)
- `docs/MIMER_IPAD_THINKING_CANVAS/README.md` (INV-B2-1/-B2-3)
- bifrost: `Yggdrasil/Yggdrasil/Mimer/Lenses/NoteBrowserView.swift`, `Yggdrasil/Yggdrasil/Markdown/{MarkdownRendererView,NoteDetailView}.swift`, `Packages/YggdrasilCore/Sources/YggdrasilCore/FrontmatterDocument.swift`

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`; `agent:blocked` on the MIPAD-01
issue, flips to `agent:ready` when it merges — still write-free, outside the B2 write gate),
linking hub #3024 and this spec file. TCD hint: Sonnet / medium effort — composition of existing
components; the only care point is selection-state modeling across columns.
