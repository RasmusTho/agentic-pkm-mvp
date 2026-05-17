# Handoff: Companion UI — Converse Surface

**Target location:** `<repo root>/companion-ui/`  
**Design fidelity:** Low-to-mid fidelity wireframes. Structure, layout, IA, and interaction patterns are specified precisely. Visual polish (exact shadows, animation curves, final copy) is left to implementation. Color tokens are specified; use them or the nearest equivalent in your stack.

---

## About the Design Files

The files bundled here (`Companion UI Wireframes.html`, `design-canvas.jsx`, `colors_and_type.css`) are **HTML design prototypes** — not production code. They exist to show intended structure, states, and interactions. Do not ship them directly.

Your task: implement the designs described in this README inside `companion-ui/` using whatever framework fits the existing codebase (React + Vite is the natural choice given the runtime is FastAPI + Python). The wireframe HTML is reference material; this README is the spec.

---

## Project context

The Companion UI is a **PWA client** for a personal agentic PKM system. The backing runtime is a FastAPI server, reachable on a personal network (Tailscale). The vault is a folder of markdown files, Obsidian-compatible. All persistent state lives as markdown in the vault; the UI is a client onto that, not the source of truth.

**v0 scope:** implement the **Converse surface only.** Other surfaces (Orient, Capture, Synthesize, Resurface) appear in navigation as disabled placeholders — do not implement them.

**User:** one senior software architect. Fluent with Obsidian, markdown, agent tooling. Design for this user; do not import onboarding or discoverability patterns intended for strangers.

---

## Design direction: Document-first (Direction C)

The chosen direction treats the **vault note as the primary object** on screen. The conversation with Hugin (the agent) lives in a collapsible margin rail. The document is always visible; everything else is an overlay or a strip alongside it.

### Core layout — landscape iPad (1194×834) / Mac desktop

```
┌─────────────────────────────────────────────┬──────────────┐
│  TOP BAR (38px)                             │              │
├─────────────────────────────────────────────┤              │
│                                             │  MARGIN RAIL │
│           DOCUMENT PANE                     │  (288px)     │
│           (fills remainder)                 │  or          │
│                                             │  32px strip  │
│                                             │              │
└─────────────────────────────────────────────┴──────────────┘
```

The margin rail has **three sizes** — collapsed strip, active panel, and portrait bottom sheet:

| State | Width / Height | Trigger |
|---|---|---|
| Collapsed strip | 32px right edge | Default / focus mode |
| Active panel | 288px right edge | Tap strip or drag |
| Portrait bottom sheet | Full width, ~240px peek | iPad portrait / iPhone |

---

## Screens and states

### State C.1 — Focus (rail collapsed)

The reading/writing state. Nothing competes with the document.

**Layout:**
- Top bar: 38px, `--bg-surface`, 1px border-bottom
- Document pane: fills entire width minus 32px strip
- Document inner width: max 640px, centered horizontally, 44px vertical padding
- Collapsed strip: 32px wide, full height, `--bg-surface`, 1px border-left

**Strip contents (top to bottom):**
- Hugin presence dot: 8×8px circle, `--agent` color at 70% opacity, 12px from top
- Unread count label: `font-mono`, 8px, `--fg-3`, `writing-mode: vertical-rl`, rotated text e.g. "3 new"
- Expand handle: 16×16px box, 1px border `--border`, borderRadius 2px, "‹" character, pinned to bottom, 10px margin

**Document:**
- Frontmatter block: `font-mono` 9px `--fg-3`, 1px border-bottom `--border`, `padding-bottom: 10px`, `margin-bottom: 28px`, single line summary of key fields
- Title: `font-display` 30px `--fg-1`, weight 400, `letter-spacing: -0.02em`, `line-height: 1.25`
- Headings H2: height placeholder 13px, width 38%, `rgba(220,232,240,0.25)` 
- Headings H3: height placeholder 10px, width 28%
- Body paragraphs: stacked lines at 8px height, 7px gap, last line 62% width, `--border-strong` color

**Color rule for this state:** only the vault status dot in the top bar carries colour (green = online). Everything else is foreground/border.

---

### State C.2 — Dialogue (rail active)

Rail expands to 288px. Document narrows to fill remaining width, inner column stays ~600px centered.

**Rail structure:**
```
┌─────────────────────┐
│ ● Hugin   18 turns ›│  ← header 38px
├─────────────────────┤
│                     │
│  [conversation      │
│   thread]           │  ← flex-1, overflow-y scroll
│                     │
├─────────────────────┤
│  [composer]         │  ← 44px
└─────────────────────┘
```

**Rail header:** 9px padding, `--border` bottom, flex row: Hugin dot (7px circle, `--agent` 80% opacity) + "HUGIN" label (`font-mono` 10px `--fg-3` uppercase 0.1em tracking) + turn count (`font-mono` 9px `--fg-3` right-aligned) + collapse handle (14×14 box, "›")

**Message types in thread:**

*Human message:*
- Background: `--bg-raised`
- Border: 1px `--border`
- Border-radius: `3px 3px 1px 3px` (right-hand bubble)
- Padding: 7px 10px
- Align: `align-self: flex-end`, max-width 88%
- Content: text lines placeholder

*Agent message (Hugin):*
- Background: `rgba(74,158,255,0.06)` — tint only, no coloured border
- Border: 1px `--border`
- Border-radius: `1px 3px 3px 3px`
- Padding: 7px 10px
- Context label: `font-mono` 8px `--fg-3` uppercase, e.g. "re: Decision record", margin-bottom 5px
- Source line: below content, `font-mono` 8px `--fg-3`, `↳ Projects/Q2-arch.md`, separated by 1px `--border` top

*Thinking indicator:*
- "HUGIN" label + three dots, dot pulse animation (opacity 0.3→1→0.3, scale 0.85→1→0.85, staggered 0.2s)

**Composer:**
- Background: `--bg-raised`
- Border: 1px `--border-strong`
- Border-radius: 3px
- Padding: 6px 8px
- Input: flex-1, no border, background transparent, `font-ui` 13px
- Send button: right-aligned, `padding: 3px 9px`, border 1px `--cyan`, border-radius 2px, `font-ui` 10px `--cyan` color
- **Send is the only cyan element on screen**

**Document annotations while rail is active:**
- Agent-referenced passages: `border-left: 2px solid rgba(74,158,255,0.2)`, `padding-left: 10px`, `margin-left: -12px`
- Margin dot at right edge: 8×8px circle, `rgba(74,158,255,0.5)`, `position: absolute, right: -26px`
- Staged/uncommitted passages: `border-left: 2px solid rgba(240,144,48,0.35)`, `background: rgba(240,144,48,0.07)`, margin dot `rgba(240,144,48,0.7)`

---

### State C.3 — Suggestion moment

A proposed addition exists. Everything except the suggestion recedes.

**Document behaviour:**
- All document sections NOT involved in the suggestion: `opacity: 0.35`
- Proposed insertion block:
  - `border-left: 3px solid #f09030`
  - `background: rgba(240,144,48,0.07)`
  - `border-radius: 0 2px 2px 0`
  - `padding: 10px 12px`
  - Label: `font-mono` 8px `#f09030` uppercase "proposed addition"
  - Content: text placeholder lines
  - Margin dot: 10×10px circle, `#f09030` 80% opacity, `right: -28px top: 14px`

**Rail behaviour:**
- Prior conversation turns: `opacity: 0.3`
- Suggestion card: full opacity, same amber treatment as document block
  - `border-left: 3px solid #f09030`
  - `border: 1px solid rgba(240,144,48,0.3)`
  - `background: rgba(240,144,48,0.07)`
  - Label: `font-mono` 8px `#f09030` uppercase "Hugin · proposed addition"
  - Content placeholder
  - Diff hint: `font-mono` 8px `--fg-3`, e.g. "+3 lines after ## Current state"
  - **Apply to note** button: `padding: 4px 12px`, `border: 1px solid #f09030`, `border-radius: 2px`, `font-ui` 11px `#f09030`, `background: rgba(240,144,48,0.08)`
  - **Discard** button: `padding: 4px 10px`, `border: 1px solid --border`, `font-ui` 11px `--fg-3`

**Composer behaviour during staged state:**
- Composer opacity: 0.4
- Input disabled
- Below composer: `font-mono` 8px `--fg-3` centered text: "apply or discard to continue"

**Key principle:** the document block and the rail card are the same object shown twice. Same amber, same label, same action. The user should feel they are acting on one thing.

---

### State C.4 — Session drawer

Triggered by: tapping the session pill in the top bar (shows current session title + ▾).

**Behaviour:** a drawer slides in from the left as a full-height overlay. It does not navigate away from the document — the document stays visible behind it.

**Scrim:** `background: rgba(7,11,18,0.55)`, `backdrop-filter: blur(2px)`, covers full viewport behind drawer. Tapping scrim dismisses without switching session.

**Drawer:** 340px wide, full height, `--bg-surface`, `border-right: 1px --border`, `box-shadow: 4px 0 32px rgba(0,0,0,0.5)`

**Drawer header:** `padding: 12px 14px`
- "SESSIONS" label: `font-mono` 9px `--fg-3` uppercase
- New session button: icon box + "New" label, `border: 1px --border`, `border-radius: 2px`
- Close ✕: 16×16 box

**Search bar:** `padding: 8px 12px`, `border-bottom: 1px --border`
- Input: `--bg-raised`, `border: 1px --border`, `border-radius: 2px`, `padding: 5px 10px`

**Session list items:**
- Padding: 8px 10px, `border-radius: 2px`, `margin-bottom: 2px`
- Active session: `background: rgba(212,168,67,0.05)`, `border: 1px solid rgba(212,168,67,0.25)`
- Active title: `font-ui` 12px `--accent` weight 500
- Inactive title: `font-ui` 12px `--fg-2` weight 400
- Path: `font-mono` 9px `--fg-3`
- Age + turn count: `font-mono` 9px `--fg-3`, right-aligned

**Drawer footer:** vault status dot + "Vault online · N sessions", `font-mono` 9px `--fg-3`

---

### State C.5 — Portrait (iPad portrait 834×1194 / iPhone)

**Top bar:** same 38px bar. Nav labels drop — show icon boxes only (no text labels). Session pill truncates to fit. Vault dot only (no path text).

**Document:** fills full 834px width. Inner column ~560px centered. Bottom padding ~160px to clear the sheet.

**Conversation rail → bottom sheet:**
- Collapsed: a `~240px` sheet docked to the bottom edge
- Drag handle: 36×3px pill, `--border-strong`, centered, 10px from top of sheet
- Header: same Hugin dot + label + turn count as landscape
- Peek area: shows latest agent message + composer
- Drag up: expands to full-height sheet covering most of screen
- Drag down: collapses to 32px strip at bottom (equivalent to landscape collapsed state)
- On iPhone: this is the only rail presentation — no side panel

---

### State C.6 — Source peek

**Trigger:** tap any margin dot (blue or amber circle at right edge of annotated passage).

**Peek card:** a floating card anchored to the dot position. Not a modal; not a new pane.
- Width: 288px
- Position: `position: absolute`, `right: -310px` (to the right of the document column), vertically centred on the dot
- Background: `--bg-raised`
- Border: 1px `--border-strong`
- Border-radius: 3px
- Box-shadow: `0 4px 24px rgba(0,0,0,0.5), 0 1px 4px rgba(0,0,0,0.3)`

**Peek card contents:**
- Header: source file path (`font-mono` 9px `--fg-3`) + ✕ close button, separated by 1px `--border` bottom
- Section heading: `font-mono` 8px `--fg-3` uppercase
- Referenced passage: `background: rgba(74,158,255,0.07)`, `border-left: 2px solid rgba(74,158,255,0.3)`, `padding: 5px 7px` — this is the exact span the agent cited
- Context lines: dimmed placeholder lines above/below
- Footer: "N of M references" count + ← → navigation between refs + "open full note" link

**Dismiss:** tap ✕ or anywhere outside the card. No modal backdrop needed.

**Note on positioning:** on iPad portrait or narrow viewports, the peek card should shift to appear above or below the dot (not off-screen right). On iPhone, use a bottom sheet for the peek.

---

## Component inventory

| Component | Description |
|---|---|
| `TopBar` | 38px app shell bar: logo glyph, surface nav tabs, session pill, vault dot |
| `DocumentPane` | Scrollable document area, centered column, renders markdown |
| `MarginRail` | Right-side panel: collapsed strip (32px) ↔ active panel (288px) |
| `BottomSheet` | Portrait-mode rail, draggable, three snap points |
| `ConversationThread` | Scrollable message list inside the rail |
| `HumanMessage` | Right-aligned bubble, `--bg-raised` |
| `AgentMessage` | Left-aligned, faint blue tint, context label + source footnote |
| `ThinkingIndicator` | Three-dot pulse animation |
| `Composer` | Textarea + Send button (only cyan element in dialogue state) |
| `SuggestionCard` | Amber card in thread, mirrors document insertion block |
| `DocumentInsertionBlock` | Amber annotated region in the document |
| `MarginDot` | 8–10px circle at right edge of annotated passage, tappable |
| `SourcePeekCard` | Floating card anchored to a margin dot |
| `SessionDrawer` | Left overlay: session list, search, new session |
| `SessionListItem` | Single row: title, path, age, turn count |

---

## Interaction patterns

### Rail expand/collapse
- Collapsed → active: tap strip or drag from right edge. Animate width 32px → 288px, `ease-out 200ms`.
- Active → collapsed: tap collapse handle "›" or drag. Same animation reversed.
- Rail and document animate simultaneously; document column narrows as rail expands.

### Session switching
1. Tap session pill in top bar → session drawer slides in from left (`translateX(-340px → 0`, `ease-out 220ms`)
2. Tap session in list → drawer slides out, document transitions to new session's note
3. Tap scrim → drawer slides out, no session change
4. Keyboard: Escape closes drawer

### Suggestion flow
1. Agent produces suggestion → `SuggestionCard` appears in thread at full opacity; prior messages dim to 0.3
2. Simultaneously: `DocumentInsertionBlock` appears at correct location in document; surrounding sections dim to 0.35
3. Composer disables, hint text "apply or discard to continue" appears
4. **Apply:** POST to runtime `SUGGEST` endpoint → on success, document re-renders with insertion applied, amber regions clear, composer re-enables
5. **Discard:** suggestion card + document insertion block both clear, full opacity restored, composer re-enables
6. The amber treatment on the card and document block must be visually identical — same colour, same label — they are the same object

### Source peek
1. Tap margin dot → peek card appears anchored to dot, animated `opacity 0 → 1, translateY(4px → 0), 150ms ease-out`
2. Multiple dots can be on screen; tapping a second dot closes the first, opens the new one
3. ← → in footer navigates between references within the same cited passage
4. "open full note" → opens the referenced note in a new session or document view (TBD; for v0, could be a no-op or link to Obsidian URI)
5. Tap ✕ or outside card → card closes, `opacity 1 → 0, 100ms`

### Portrait bottom sheet snap points
- **Snap 0 (collapsed):** 32px strip, drag handle barely visible. Sheet has `box-shadow: 0 -4px 20px rgba(0,0,0,0.3)`.
- **Snap 1 (peek):** ~240px — drag handle + header + one agent message + composer visible.
- **Snap 2 (full):** ~80% of viewport height — full thread + composer. Document visible above as a sliver.
- Drag velocity determines which snap point to settle on. Use spring physics or `ease-out`.

---

## Runtime API integration

The UI is a client of the existing FastAPI runtime. All vault I/O goes through it.

| Action | API call |
|---|---|
| Load session thread | `GET /sessions/{id}/messages` |
| Send message | `POST /sessions/{id}/messages` |
| Load document | `GET /vault/notes/{path}` |
| Apply suggestion | `POST /sessions/{id}/suggestions/{suggestion_id}/apply` |
| Discard suggestion | `DELETE /sessions/{id}/suggestions/{suggestion_id}` |
| List sessions | `GET /sessions` |
| Create session | `POST /sessions` with `{ title, vault_path }` |
| Vault status | `GET /health` or websocket event |

Endpoints are illustrative — match to your actual runtime schema. The contract is: the UI proposes (SUGGEST), the runtime owns vault writes (APPLY). No direct vault file I/O from the client.

**Vault unreachable state:**
- Show a non-blocking banner at top of document pane: `--destructive` colour dot + `font-mono` message "Vault unreachable. Sessions are read-only."
- Disable composer Send, Apply buttons
- Do not interrupt the user's reading or discard any composed text

---

## Design tokens

These come from `colors_and_type.css` in the bundled reference files. Implement them as CSS custom properties, Tailwind config keys, or your equivalent.

### Backgrounds
```
--bg-base:     #070b12   /* page root */
--bg-surface:  #0c1220   /* panels, top bar, rail */
--bg-raised:   #111a2e   /* cards, inputs */
--bg-overlay:  #162038   /* hover states */
```

### Foreground
```
--fg-1:  #dce8f0   /* primary text */
--fg-2:  #7a9ab8   /* secondary */
--fg-3:  #3d5570   /* tertiary / disabled */
```

### Borders
```
--border:        #152030   /* default */
--border-strong: #1e3050   /* emphasis */
```

### Semantic accent colours
```
--accent:      #d4a843   /* Norse gold — active session highlight */
--cyan:        #00d4e8   /* Send button, primary action only */
--vault:       #39e87d   /* vault-connected dot */
--agent:       #4a9eff   /* Hugin presence dot (used sparingly, mostly as tint) */
--amber:       #f09030   /* staged/suggested state */
--destructive: #ff3d3d   /* vault unreachable, errors */
```

### Typography
```
--font-display: 'EB Garamond', Georgia, serif      /* document title */
--font-ui:      'Space Grotesk', system-ui, sans   /* UI labels, buttons */
--font-mono:    'JetBrains Mono', monospace         /* metadata, paths, code */
```

**Font loading:**
- EB Garamond + Space Grotesk: Google Fonts
- JetBrains Mono: `https://fonts.bunny.net/css?family=jetbrains-mono:400,500`

### Spacing and radius
```
border-radius default: 2–4px (sharp, not pill-shaped)
border-radius modal/card: 3–4px
no border-radius > 6px in the UI
```

---

## Colour discipline

**The most important design constraint:** at any given moment, only the single most actionable element on screen carries a saturated colour. Everything else is monochrome (`--fg-*`, `--border-*`, `--bg-*`).

| Moment | Coloured element |
|---|---|
| Focus (reading) | Vault dot only |
| Dialogue | Vault dot + Send button (cyan) |
| Suggestion | Vault dot + Apply button + amber tints |
| Vault unreachable | Destructive banner dot |

Never use glow effects, drop shadows, or `text-shadow` on primary UI elements. The neon/Tron references in the design system exist — use them with restraint, only where they communicate state (e.g. vault dot glow when connected).

---

## What not to build in v0

- Any surface other than Converse (Orient, Capture, Triage, Resurface, Synthesize) — show as disabled nav tabs
- Direct vault file writes from the UI — all writes go through the runtime
- Multi-agent UI
- Onboarding, tooltips, empty-state coaching for a new user
- Light mode
- Any modal dialog except possibly the "New session" form (and even that could be inline)

---

## Files in this bundle

| File | Purpose |
|---|---|
| `README.md` | This document — the implementation spec |
| `Companion UI Wireframes.html` | Interactive wireframe canvas — 9 screen states |
| `design-canvas.jsx` | Canvas component used by wireframes (reference only) |
| `colors_and_type.css` | Full design token stylesheet |

Open `Companion UI Wireframes.html` in a browser and navigate the canvas. Scroll right for the C deep-dive states (C.1–C.6). Double-click any artboard to fullscreen it.

---

## Governance status

**Crossing:** A (pre-governance)

This package was archived before the design handoff governance chain was established in [`companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`](../../../companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md). It is explicitly exempt from retroactive maturity-checklist completion. The maturity checklist (Crossing B) and the associated required files (`implementation-contracts.md`, `authority-boundaries.md`, `open-questions.md`) do not apply to this package retroactively. The package remains a valid exploration archive.

Future work: a Crossing B review may be initiated as a separate task if this package is nominated for promotion to a normalized spec.

---

## Prompt to paste into Claude Code

Paste this at the start of your Claude Code session:

```
I'm implementing a new PWA surface at companion-ui/ in this repo. 

The design is fully specified in companion-ui/design_handoff/README.md — please read that first before writing any code.

Also open companion-ui/design_handoff/Companion UI Wireframes.html in a browser so you can see the 9 wireframe states.

Start by:
1. Reading README.md in full
2. Scaffolding the companion-ui/ directory with a React + Vite PWA setup (or adapt to whatever the repo already uses)
3. Implementing the TopBar, DocumentPane, and MarginRail (collapsed state) first — get the shell right before adding interaction
4. Then implement State C.2 (Dialogue) end-to-end: real API calls to the FastAPI runtime, real message rendering, working composer
5. Then the suggestion flow (C.3): SuggestionCard + DocumentInsertionBlock + Apply/Discard wired to the API

Work screen-state by screen-state. Ask me when the API schema is ambiguous.

The runtime base URL is configurable — default to http://localhost:8000 for local dev. I'll tell you the Tailscale address for device testing.
```
