---
name: Annotate And Promote Into Notes
description: Pencil/keyboard annotation on a canvas item and drag-drop promotion of an item/snippet into a vault note — both landing as governed markdown appends with provenance.
task_id: MIPAD-04
source_anchor: docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md :: §2 Platform footprint
parent_capability: Mimer iPad Thinking Canvas
prerequisites: [MIPAD-02]
depends_on: [VAULT_BROWSE_COLUMNS_WITH_NOTE_INSPECTOR]
can_parallelize_with: [SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD]
---

# Annotate And Promote Into Notes

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).
**Write gate applies:** blocked until hub #3129/#3131/#3132 and bifrost#4/#5 are all merged
(README :: Write gate).

## Purpose

The design-of-record commits two interaction promises for the iPad canvas: "Pencil + keyboard:
annotate an ingested item, correct an attribution, drag a snippet into a note" and "drag-drop into
the vault: promote/curate an episode straight into a note." Both are, at the storage layer, the
same thing: **a markdown append to a vault note through the coordinated write seam.** This task
ships that seam usage once and both gestures on top of it.

## What This Task Does

- **Annotation:** with a note (or canvas item) selected, an annotation affordance opens a text
  field — Apple Pencil writes into it via system **Scribble** (standard text input; no ink
  storage), hardware keyboard types into it. Commit appends a markdown block to the target note:
  a blockquote or `> [!note]`-style callout containing the annotation text and an attribution
  line. Markdown-first: ink never persists as drawing data; if Scribble is unavailable the field
  is still a plain text field.
- **Drag-drop promotion:** a content-column item (note row, entity entry, attention item) is
  draggable (`.draggable`/`NSItemProvider` with a plain-text + markdown-link representation);
  dropping it onto a note in the browse column (or onto the open detail note) appends a promotion
  block — a markdown link to the source (`[[relative/path]]` style used by the vault) plus any
  dragged snippet text.
- **One write shape:** both gestures call a single new `appendBlock(to:block:)` helper on the
  canvas layer that delegates to `VaultFileStore.readModifyWrite` (post-bifrost#4/#5: coordinated,
  stale-verified, provenance-tagged). Append-only with respect to existing content — the mutation
  closure may only add a suffix block, never reorder or rewrite prior content.
- **Failure surfacing (INV-B2-3):** if the write fails (contention, permission, gate), the
  annotation/drop content stays visible in the UI with an explicit error and a retry/copy
  affordance — never silently dropped, never queued to a hidden store.

## Concretely

iPad simulator, fixture vault: select `Projects/foo.md`, tap annotate, Scribble "check the June
numbers", commit → `foo.md` gains

```markdown
> [!note] Annotation (bifrost-ios, 2026-07-07T14:12:00Z)
> check the June numbers
```

Drag the entity entry "Acme AB" from the content column onto `Projects/foo.md` → the note gains a
promotion block linking the source item. Both diffs are pure suffix appends; frontmatter gains or
updates the provenance block from bifrost#5's mechanism.

## Why This Matters

These are the interactions that make the iPad a *thinking* canvas instead of a reader. They are
also the first B2 surfaces that write to arbitrary human notes (not just `_heimdal/**` control
notes) — the write class ADR-0055 protects hardest. Appends through the coordinated seam with
contention surfaced are what keep "the app is a lens" true (W3: prefer append over rewrite;
human-note edits only on explicit human direction — a gesture on the human's own iPad IS that
direction, and the append shape keeps the blast radius one block).

## Acceptance Criteria

- [ ] Annotation commit appends exactly one markdown block to the target note; prior content is
  byte-identical. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/CanvasAppendWriteTests.swift::testAnnotationAppendsSingleBlockPreservingContent`
  (new; through the store's public API on a temp vault).
- [ ] Drop of a dragged item appends a promotion block containing a resolvable vault-relative
  link. `Verify:` bifrost
  `CanvasAppendWriteTests.swift::testDropAppendsPromotionBlockWithRelativeLink` (new).
- [ ] Both gestures route through the same append helper on the coordinated `readModifyWrite`
  seam — no plain `write(_:to:)` whole-file call and no new write primitive. `Verify:` bifrost
  `CanvasAppendWriteTests.swift::testGesturesShareCoordinatedAppendSeam` (new; enforcement AC —
  asserts the production gesture handlers invoke the helper, and the helper invokes
  `readModifyWrite`, not `write`).
- [ ] A failed write keeps the content visible with an error + retry/copy; nothing is persisted
  client-side. `Verify:` bifrost
  `CanvasAppendWriteTests.swift::testFailedWriteSurfacesErrorAndRetainsText` (new; injected
  failing store).
- [ ] iPad journey test covers annotate-and-see-it-rendered plus drag-promote. `Verify:` bifrost
  `Yggdrasil/YggdrasilUITests/MimerCanvasUITests.swift::testAnnotateAndDragPromoteJourney` (new,
  iPad destination).

## How to Verify (Pre-Merge)

- bifrost CI green (both destinations) including the five named tests; `swiftlint --strict` clean.
- Pre-merge gate check recorded in the PR body: hub #3129/#3131/#3132 and bifrost#4/#5 merged
  (INV-B2-5).

## Out of Scope

- Ink/drawing persistence, PencilKit canvases, handwriting-to-sketch features (Scribble text only).
- "Correct an attribution" as a distinct structured flow — v1 treats it as an annotation on the
  item; a structured attribution-correction contract would be hub work first.
- Episode-object semantics for "promote an episode" (ADR-0051/ERE lane) — here "episode" means
  the item being promoted; the append block is a plain link+snippet, not an Episode entity.
- Any write outside the selected/target note (no batch operations).

## Restart / Durability Posture

In-progress annotation text and drag state are in-memory only; backgrounding or killing the app
mid-composition loses uncommitted text (standard iOS text-field expectations — acceptable), but a
*failed committed write* keeps its text visible for copy/retry while the app lives. Nothing about
committed content depends on app state: once the append lands in the vault file it is durable and
Obsidian-visible.

## Related Docs

- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §5 (provenance), §6 W2/W3/W4 (append discipline)
- `docs/MIMER_IPAD_THINKING_CANVAS/README.md` (INV-B2-2/-B2-3/-B2-5)
- bifrost: `Yggdrasil/Yggdrasil/Vault/VaultFileStore.swift` (post-bifrost#4/#5 seam)

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:blocked` — gate list: MIPAD-02
issue + hub #3129/#3131/#3132 + bifrost#4/#5), linking hub #3024 and this spec file. May split into
two issues (annotation; drag-drop) if the drag infrastructure proves heavy — the shared append
helper lands with whichever goes first. TCD hint: Sonnet / high effort — standard SwiftUI
drag/drop + text input, but the write-discipline enforcement tests must be honest.
