# Companion UI Current State — 2026-05-26

## Overview

The Companion UI exists today as a dev/staging browser application served by the Yggdrasil
host process. It is not a production UI. It is a real implementation that can be run locally
and evaluated against real vault notes. The design review is intended to guide how it should
look and behave before it becomes a credible daily-use surface.

**Baseline observed:** `origin/main` at commit `29f81427` or later.

**Runtime environment used for UAT:** dev

**Vault:** Niflheim (dev vault)

**UI URL pattern:**
```
http://10.42.42.10:8111/?note_path=<note-path>
```

**Tailscale URL (may be used for device access):**
```
http://100.113.104.116:8111/?note_path=<note-path>
```

## UI surfaces

### 1. Main note body

The note body is the primary cognitive surface. It renders the content of the vault note
currently selected. The implementation uses Python/Jinja2 to serve HTML with Tailwind CSS.

**Current state:**
- Basic Markdown rendering works: headings, paragraphs, lists, blockquotes, emphasis, inline
  code, horizontal rules, GFM tables, callouts.
- Visual design alignment is incomplete. The rendered typography does not match the intended
  design tokens (heading scale, paragraph rhythm, spacing).
- The note body is rendered in a column on the left side of the workspace, with a dark shell
  around it using Yggdrasil design tokens.
- There is no rich Markdown editor (CodeMirror or equivalent) integrated. The note body is
  rendered read-only from the runtime API.
- Body edit failure: note edits do not work. The Canvas body-edit session flow exists in the
  backend API but is not wired to the UI. Attempting to edit the body produces no visible
  effect.
- Mermaid diagrams fail to render.
- Internal wikilinks fail to resolve and navigate.
- Images: a missing image placeholder state has been observed, but real image rendering from
  the vault has not been confirmed because no real image asset fixture was available during UAT.

### 2. Left rail / outline

An outline panel is present on the **left** side of the workspace. It extracts headings from
the current note and allows the user to click a heading to scroll to it.

Note: some earlier documents in this package incorrectly referred to this as the "right rail".
The outline is the left rail. The Panel / governance rail is the right rail.

**Current state (observed in screenshots):**
- Outline renders and navigates. This passed UAT.
- The outline displays heading hierarchy with visible indentation for nested headings.
- The outline font and visual weight are relatively close to the note body — it does not
  clearly recede as a secondary surface.
- Visual integration with the note body shell needs design review: sizing, visual weight,
  relationship to the note body at different viewport sizes.

### 3. Panel / governance rail (right rail)

The Panel rail is on the **right** side of the workspace. It is intended to show artifact-local
proposals from the agent for the current note.

**Current state (observed in screenshots):**
- The Panel rail is not a silent placeholder. It actively shows system state:
  "No active Panel proposals", "Panel ready", "Suggestions are idle",
  "Find is unavailable because no backend candidate payload is available yet",
  "read-only".
- Each section of the Panel rail has a labeled state. This is more informative than a blank
  placeholder, but the visual weight and density of these state labels has not been
  designed for cognitive clarity.
- The governance boundary (Panel vs Canvas vs note body) is architecturally defined but not
  yet visually communicated to the user with sufficient clarity.

### 4. Metadata / note header area

A dense metadata band appears above the note title. It contains:
- Breadcrumb path (note file path)
- Artifact ID (a hash-like identifier)
- Content hash
- Properties (lifecycle_state, note_type, origin, context)
- Tags

**Current state (observed in screenshots):**
- The metadata band takes up significant vertical space before the note content begins.
- It uses small monospace text throughout — dense and technical.
- An environment banner ("DEV / NOT PRODUCTION") appears in the top-right.
- This metadata area is currently more prominent than it needs to be for the primary
  cognitive act of reading the note. It reads as infrastructure, not as orientation context.

### 4. Vault Browser

The Vault Browser is a navigation and orientation surface that lets the user browse vault
content. It includes an artifact inspector panel.

**Current state:**
- The Vault Browser exists and is functional at a basic level: it shows vault structure and
  allows navigation.
- It is a separate surface from the note workspace. Integration and visual consistency with the
  workspace shell are not fully established.
- VaultAction display model, agent receipts, and review posture in the inspector have been
  implemented (PR #1274, #1273, #1272, #1257).

## Markdown renderer status

The Markdown renderer is a Python/Jinja2 server-rendered implementation. It is not a rich
JavaScript Markdown renderer (no react-markdown, no remark/rehype pipeline, no CodeMirror).

| Feature | Status | Observed in screenshots |
|---|---|---|
| Headings | Renders | Yes — H1 through H4+ visible; hierarchy needs design work |
| Paragraphs | Renders | Yes |
| Lists (ordered, unordered) | Renders | Yes |
| Inline emphasis (bold, italic) | Renders | Yes (visible in table rows) |
| Inline code | Renders | Yes (visible in task list items) |
| Fenced code blocks | Renders | Not in captured screenshots — needs separate capture |
| Blockquotes | Renders | Not in captured screenshots |
| GFM tables | Renders | Yes — UAT result summary table and feature table visible |
| GFM task lists | Renders | Yes — checked and unchecked checkboxes visible in screenshot 06 |
| Callouts (`> [!type]`) | Renders | Yes — Note, Tip, Warning, Danger with color-coded styling visible |
| Mermaid diagrams | Fails | Not in captured screenshots — failure state not yet documented |
| Internal wikilinks | Fails | Not in captured screenshots — failure state not yet documented |
| Images | Ambiguous | Not in captured screenshots |
| Horizontal rules | Renders | Not in captured screenshots |
| Frontmatter / properties | Renders as metadata band | Yes — visible above note title as dense metadata block |

## Observed visual design problems

These are concrete observations from the screenshots, not inferences.

**Heading hierarchy is insufficiently differentiated.**
H2 and H3 headings are visually very similar in size and weight. A section heading like
"2. Outline and right rail navigation" (H2) and "2.1 First nested heading" (H3) appear
nearly the same visual size. The user must read the text to understand the level rather than
perceiving it at a glance.

**All headings are too large relative to body text.**
The heading sizes create a layout where headings dominate the reading surface. A long note
with many headings will feel fragmented rather than continuous. The H1 (note title) is
appropriate as a landmark; H2 through H4 need to step down more sharply.

**Metadata band is too prominent.**
The metadata area above the note title (breadcrumb, artifact ID, content hash, properties,
tags) occupies significant vertical space and uses dense monospace text. It reads as
infrastructure chrome, not as orientation context that serves the reader.

**Callouts render well — color and label system is functional.**
The callout rendering is one of the stronger visual elements: distinct background colors per
type (Note=blue, Tip=teal, Warning=yellow/orange, Danger=red), with a type label visible.
This is a visual pattern worth preserving and extending.

## Body edit / CodeMirror status

**Body edit does not work.** The Canvas body-edit flow exists in the backend API but is not
wired to the Companion UI browser surface. A CodeMirror or equivalent editor adapter has not
been adopted yet. Any interaction intended to edit the note body produces no visible effect.

This is the main functional blocker for deeper editor UAT. Design should treat the note body
as a read-only rendering surface for the purposes of this review, with the understanding that
edit capability is a near-future requirement.

## Known runtime / dev constraints

- The dev server runs on `http://10.42.42.10:8111` (LAN/Tailscale) or `http://127.0.0.1:8111`
  (local only). Port `8111` is the dev environment port.
- The runtime API runs on port `18001` (dev) and the Companion UI proxies through it.
- The Companion UI does not choose or configure the vault directly. It calls the runtime API;
  the runtime determines the vault bound to the environment.
- No auth or TLS is in place. The dev server is suitable for trusted-device local/LAN/Tailscale
  access only. Production hardening is deferred.
- Production UI framework decision (React, server-rendered HTML, or other) has not been made.
  The current implementation uses Python/Jinja2 with Tailwind CSS.

## Yggdrasil design reference

The file `logga v2.png` in this package is the Yggdrasil product logo. It shows a stylized
tree that is half organic (warm gold, natural forms, leaf detail) and half circuit board
(teal, geometric connectors, circuit-board endpoints), on a pure black background.

This logo is relevant design context for Claude Design:
- The color palette (gold/warm and teal/cyan on black) informs the existing design token
  direction.
- The organic + technical duality reflects the product's identity: human cognition supported
  by machine substrate.
- The logo is calm and precise — not playful, not corporate.

Design recommendations should remain compatible with this identity.

## What is shipped vs experimental/spike

| Component | State |
|---|---|
| Browser dev server (`serve_dev_page.py`) | Shipped — dev/staging only |
| Real-note workspace visual shell (first alignment pass) | Shipped — dev/staging only |
| Note body Markdown rendering | Shipped (partial) — read-only, not all features work |
| Right rail / outline | Shipped — works |
| Panel rail | Placeholder only — live proposals not wired |
| Canvas body-edit API | Shipped in backend — not wired to browser UI |
| Vault Browser (basic) | Shipped — functional |
| Vault Browser artifact inspector | Shipped — PR #1272–#1274 |
| Canvas Suggestion Flow models | Shipped in backend — browser integration pending |
| Production Companion UI | Not yet shipped |
| Auth / TLS / reverse proxy | Not yet shipped — deferred |
| Full editor adapter (CodeMirror, etc.) | Not yet shipped — spike phase |
| Mermaid rendering | Not working |
| Internal wikilink resolution | Not working |
