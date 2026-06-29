State: Point-in-time UX audit + correction record for the Companion UI (2026-06-27). Non-canonical review artifact — the authoritative product target is `docs/COMPANION_UI_PRODUCT_SPEC.md`; this records findings and the fixes applied in one pass.

# Companion UI — Evidence-Based UX Audit & Correction Pass

**Date:** 2026-06-27
**Scope:** The Companion UI (the human-facing workspace), which is **server-rendered HTML/CSS/JS emitted by Python** — not a JS framework. The audit covered navigation/reachability, the right panel & scroll behaviour, markdown rendering, the system map's developer-information exposure, accessibility, and empty/loading/error/long-content robustness.
**Method:** Read-only multi-agent traversal of the rendering code with file:line evidence (one auditor per dimension), cross-checked by direct reproduction (markdown tables) and one Playwright probe (right-rail scroll). Fixes were then applied surgically and re-verified against the test suite.

> **Key architectural fact:** `serve_production_page.py` imports `render_index_html` from `serve_dev_page.py`, so **the same renderer + CSS ship to dev and prod**. Every rendering defect below was a production defect, and every fix below ships to both — consistent with the "one product, identical features" principle.

---

## 1. Executive summary

### Top 5 UX risks (as found)
1. **Markdown tables silently collapse to raw text** for very common real-world syntax (1–2 dash separators, aligned columns, single-column, escaped pipes). A non-developer pasting an ordinary table saw `| A | B | | -- | -- |` garbage. *(P1)*
2. **The right "suggestions" rail could not scroll** — with several staged proposals the lower cards and their confirm/decline controls were clipped off-screen and unreachable. *(P1)*
3. **The System Map — a 1-click, default-view human surface — read like an internal engineering document:** it leaked a literal Python function name, JS API calls, raw intent tokens, a runtime trace id, and architecture jargon. *(P1)*
4. **The System Map is the *only* door to Settings, History/Receipts, Memory, and Search (⌘K).** Settings has no direct affordance anywhere; the map is a mandatory 2-click toll for routine surfaces. *(P1)*
5. **Overlays are invisible to the browser:** none are deep-linkable and none push history, so pressing browser **Back** to dismiss a modal throws the user off the page, and no surface can be bookmarked/shared. *(P1)* — **Fixed (NAV-3):** overlays now push history (Back closes the topmost overlay) and are deep-linkable via `?overlay=<id>`.

### Top 5 recommended fixes
1. Fix the GFM table parser (dash count, alignment, escaped pipes, single column) + wrap wide tables for horizontal scroll. — **DONE**
2. Give the right rail body `min-height:0; overflow-y:auto`. — **DONE**
3. Rewrite the System Map copy into human language; gate the trace id behind the existing `?diagnostics=1` mode; humanise the mode chips. — **DONE**
4. Add a direct **Settings** launcher so the map is the *complete index*, not the *only door*. — **DONE (NAV-1)**; History + Search promoted to direct launchers — **DONE (NAV-2 / NAV-4, #2610)**.
5. Make overlays participate in browser history (pushState on mount, popstate → dismiss) and deep-linkable via `?overlay=`. — **DONE (NAV-3):** NAV-3a #2639 (history) + NAV-3b #2640 (route swap) + NAV-3c #2641 (deep-link) + NAV-3d #2644 (already-stacked-route history alignment).

### Fixed in this pass
- **Markdown tables (MD-1…MD-5):** separator now accepts GFM 1+ dash & single-column tables; per-column alignment (`:--`,`--:`,`:--:`) is applied; escaped/awkward pipes no longer drop the row; wide tables are wrapped in a horizontal-scroll container. + new tests. **MD-7** (span-aware splitting for pipes inside inline code / aliased wikilinks) landed independently on main via **#2596**; this PR builds on that splitter and keeps its regression tests.
- **Right-rail scroll (SC-1):** `.rail-placeholder-body` now owns the scroll (`min-height:0; overflow-y:auto`). Playwright-verified.
- **Portrait-sheet scroll (SC-2):** defensive `overflow-y:auto` on the narrow-mode bottom sheet.
- **System Map dev-leak (MAP-1…MAP-6):** all 19 node copies rewritten to plain language; `_render_resurface_mode` / `overlayHost.mount` / `*.open` tokens removed from visible copy; trace id gated behind diagnostics; the dev token `local-ui` is no longer shown on the mode chip and the four product-mode labels are title-cased (they are intentional product vocabulary, so they were not reworded further — MAP-6 is Partial); intro + parked notes + center copy humanised. The existing C4 "no internal refs" contract test was **extended** to also forbid source symbols/intent tokens.
- **Long-content robustness (ST-4, ST-5):** `.note-title` and proposal cards now wrap long unbroken tokens.
- **Accessibility (A11Y-1, A11Y-2, A11Y-3):** vault-action and filter-chip controls are now keyboard-operable (`role=button`, `tabindex`, Enter/Space) with visible `:focus-visible`; Help & Memory drawers now toggle `inert` when closed (no off-screen focus trap), matching the Settings-drawer precedent.
- **NAV-1 — direct Settings launcher:** added a labelled Settings control to the composed bottom bar (reuses `settings.open` + the host occupant); the System Map node is retained. This **knowingly reverses the #2447 "settings off the chrome" choice for settings only** (at the owner's request); the `test_settings_drawer` contract was updated to encode the new state.
- **NAV-2 / NAV-4 — direct launchers (#2610):** History/Receipts, Memory, and Search (⌘K) promoted to direct launchers so routine surfaces no longer cost the map's 2-click toll; the map remains the complete index.
- **NAV-3 — overlay browser-history + deep-link:** overlays now participate in browser history and are deep-linkable. Delivered as a cluster — **NAV-3a #2639** (mount pushes one history entry; browser Back closes the topmost overlay via `popstate`; Esc/scrim dismissal preserved), **NAV-3b #2640** (System Map route is an atomic `overlayHost.replace` swap at constant history depth), **NAV-3c #2641** (`?overlay=<id>` auto-mounts a declared+shipped overlay on load on both the note and orientation shells; unknown/unshipped/empty → calm no-op; boot script emitted after every occupant registration so nothing — Settings included — mounts before its occupant; the `vault` deep-link honours the browse-surface duality via `vaultBrowser.focus()` rather than a raw modal mount), and **NAV-3d #2644** (routes to already-open overlay destinations reuse the destination's existing history entry; immediate-below routes close in one Back press, deeper stacks leave the correct lower overlay open). The shipped contract is documented in `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Overlay browser-history + deep-link contract`.
- **ST-1 — Operator drawer retry:** `loaded` is now set only on fetch success (with an in-flight guard), so a transient gateway failure no longer pins the error state; the banner is calm copy, the raw error kept in `data-error` for operators.
- **ST-2 — ⌘K palette actions:** the POST now disables the button in-flight (no double-submit) and reflects success/error via `data-action-state`.
- **ST-3 — ⌘K palette filter:** a "No proposals match your filter." state shows when a filter excludes every row, instead of a blank list.

### What remains (recommended, not yet implemented)
- **NAV-3d (#2644):** fixed — history alignment for an already-stacked route destination now reuses the destination's existing history entry.
- **MAP-7 (mode chip) / MAP-8 (operator node):** further softening is possible; the operator node could be diagnostics-gated.
- **A11Y-4 / A11Y-5:** move initial focus into overlays on open + restore on close; arrow-key roving for the left-panel tablist.

---

## 2. UI inventory

### Entry / page surfaces
| Surface | File | Notes |
|---|---|---|
| Dev server / page renderer | `serve_dev_page.py` (`render_index_html`) | The whole shell, all CSS, all overlays. 13k LOC. |
| Production profile | `serve_production_page.py` | Imports `render_index_html` — same UI, prod defaults. |
| Workspace shell composition | `real_note_workspace_shell.py`, `real_note_workspace_dev_page.py` | 3-pane layout. |

### Entry states (one shell, several states)
`no_vault` (vault picker · first contact) · `cold_start` (greeting; verbs Find/Jot/Map) · warm re-entry card · `shell_active` (working view) · `calm_degraded` error/unavailable states (`calm_degraded.py`).

### Panels / drawers / overlays
Right **agent rail** (proposals) · **note-body** reading pane · left **vault browser / outline / context** panel · **command palette** ⌘K (`panel_palette.py`) · **capture** modal (`capture_modal.py`) · **memory review** drawer (`memory_review_drawer.py`) · **settings** drawer (`settings_drawer.py`) · **vault settings** panel (`vault_settings_panel.py`) · **receipts/history** (`receipts_history.py`) · **operator** drawer (diagnostics) · **help** drawer · **system map** overlay (`system_map_overlay.py`) · shared **overlay host** with focus-trap + Esc (`overlay_host.py`).

### Markdown / content states
Renderer `renderer/vault_markdown_renderer.py` (+ `vault_markdown_parser.py` for Obsidian metadata). Features: headings, emphasis, code, lists, tasks, blockquotes, links/wikilinks, images/embeds, callouts, mermaid, tables, diagnostics for malformed input.

### Map states
Closed (default) · open via Map button (1 click) or entry-screen affordance · nodes: routable (button) vs inert (article) · center "home" node · parked-surfaces note · optional diagnostics meta row.

---

## 3. Findings

Severity: **P0** blocks core use · **P1** major usability failure · **P2** frequent friction · **P3** polish.
Status: **Fixed** (this pass) · **Documented** (recommended; not changed).

> **Note on line numbers:** `file:line` references describe the code **as found during the audit (pre-fix)**. The fixes shifted line numbers within the four changed files by ~20–40 lines; refs into unedited files remain exact.

| ID | Area | Sev | Finding | Evidence | User impact | Recommended fix | Status |
|----|------|-----|---------|----------|-------------|-----------------|--------|
| MD-1 | Markdown / tables | P1 | Separator regex required `-{3,}` per column; `\| - \|`, `\| -- \|` collapse to a paragraph | `vault_markdown_renderer.py:46` (`_TABLE_SEPARATOR_RE`) | Ordinary tables render as raw pipe text | Relax to `:?-+:?` (GFM = 1+ dash) | **Fixed** |
| MD-2 | Markdown / tables | P2 | Single-column tables rejected (regex required 2+ cols) | `vault_markdown_renderer.py:46` (`(?:…)+`) | `\| Name \|` table → paragraph | `+`→`*` on column group; column-count guard in `_is_table_start` | **Fixed** |
| MD-3 | Markdown / tables | P1 | Per-column alignment (`:--`,`--:`,`:--:`) never applied | `_render_table` `:387-395`; CSS `serve_dev_page.py` th/td `text-align:left` | Right/center columns render left | Parse separator → `_table_alignments`; emit `style="text-align:…"` | **Fixed** |
| MD-4 | Markdown / tables | P2 | Escaped pipe `\|` split as a delimiter → table drops the row / shows `\|` | `_split_table_row` `:398-400` raw `split("\|")` | Cells with a literal pipe break the table | Split on unescaped pipes `(?<!\\)\|`, unescape `\|`→`\|` | **Fixed** |
| MD-5 | Markdown / tables + CSS | P1 | Wide tables had no horizontal scroll; crushed into the 68ch column / widened layout | `_render_table` emitted bare `<table>`; only `<pre>` had `overflow-x` | Wide tables unreadable / break layout | Wrap in `.vault-table-scroll{overflow-x:auto}`; table `min-width:100%` | **Fixed** |
| MD-6 | Markdown / hr | P3 | A document starting with bare `---` emits a spurious "unterminated frontmatter" diagnostic before the `<hr>` | `vault_markdown_parser.py:78-95` | Confusing diagnostic on a valid thematic break | Only treat leading `---` as frontmatter when a closing `---` exists | **Documented** |
| MD-7 | Markdown / tables | P2 | A literal pipe inside inline code (`` `a\|b` ``) or an aliased wikilink (`[[Note\|Alias]]`) in a table cell was split as a delimiter → the row mis-counts and the table collapses to a mangled paragraph (aliased wikilinks in tables are common in real vaults) | `_split_table_row` split on every unescaped `\|` with no span awareness | Tables with code/wikilinks break | Span-aware `_split_table_row` (skips `` `…` `` code spans + `[[…]]` wikilinks) | **Fixed on main via #2596** (independent); this PR builds on it |
| SC-1 | Right panel / agent-rail | P1 | Rail body cannot scroll; lower proposal cards + their controls clipped | `.agent-rail` `overflow:hidden` `:10449`; `.rail-placeholder-body` `flex:1` no overflow `:10488` | Cannot reach/act on lower proposals | Add `min-height:0; overflow-y:auto` to `.rail-placeholder-body` | **Fixed** |
| SC-2 | Narrow / portrait-sheet | P2 | Height-capped bottom sheet had no `overflow-y` → tall content clipped | `.portrait-sheet` snaps `:11290-11298`, base rule no overflow | Narrow-screen sheet content unreachable | Add `overflow-y:auto` to `.portrait-sheet` | **Fixed** |
| SC-3 | Settings badge layering | P3 | `position:fixed` local-only badge floats over scrolled drawer content | `settings_drawer.py:507-514` (z-index 955 vs drawer 960) | Minor overlap of a small chip | Render badge inside drawer flow | **Documented** |
| MAP-1 | System map / center | P1 | Runtime **trace id** rendered as `<code>` in the default human view | `system_map_overlay.py` center-meta (`trace_id` span) | Users see a meaningless correlation id | Gate behind `?diagnostics=1` (#1418 pattern) | **Fixed** |
| MAP-2 | System map / resurface node | P1 | Visible copy contained a literal Python function name `_render_resurface_mode` and `overlayHost.mount` | `system_map_overlay.py` resurface_rail `reached` | Reads as leaked source / broken text | Rewrite to plain language | **Fixed** |
| MAP-3 | System map / node reach text | P1 | `reached`/`returns` carried raw intent tokens (`cmd.open`, `memory.open`, `vaultBrowser.focus()`) | all routable nodes' `reached` | Cryptic impl tokens in human copy | Rewrite copy; keep keyboard hints (⌘K) | **Fixed** |
| MAP-4 | System map / status notes | P2 | Architecture jargon: "Projection", "governed handoff", "queue_review", "canonical hash" | nodes' `status_note` | Confusing, unprofessional | Rewrite as plain "Ready — …" copy | **Fixed** |
| MAP-5 | System map / parked + intro + center | P2/P3 | Spec citation "(spec §Parked, Q15–Q16)", "renders and routes / re-classifies", "latency ladder" | parked note, intro note, `MAP_CENTER_SUB` | Internal-document tone | Humanise all three | **Fixed** |
| MAP-6 | System map / mode chip | P2 | Raw enum chips ("find reorient resurface act" / "local-ui") shown to users | `_node_html` mode span | Reads as internal status codes | Hide the dev token `local-ui`; title-case the four product-mode labels (intentional product vocabulary); keep `data-mode` machine | **Partial** — `local-ui` hidden + chips title-cased; deeper rewording of the product-mode words deferred |
| MAP-7 | System map / contract | P2 | The "no internal refs" contract only caught issue/SEP numbers, not source symbols | `test_system_map_overlay.py` C4 | Future copy can re-leak symbols | Extend contract to forbid `_fn(`, `x.y(`, `*.open/focus/mount` | **Fixed** |
| MAP-8 | System map / operator node | P2 | "Operator diagnostics" node advertised to all users in the default view | `system_map_overlay.py` operator node | Non-tech user offered a diagnostics surface | Renamed to "System status"; humanised. Consider diagnostics-gating the node | **Fixed** (rename) / **Documented** (gating) |
| NAV-1 | Reachability / Settings | P1 | Settings had **no direct affordance**; reachable only via the map (2 clicks, 19-node grid) | `overlay_host.py:127` (`SHIPPED_TOPBAR_SURFACES=("capture",)`); map route only | Users can't find "preferences" | Added a direct Settings launcher to the bottom bar (reuses `settings.open` + host occupant); map node retained. Knowingly reverses #2447 for settings; contract test updated. | **Fixed** |
| NAV-2 | Reachability / map-as-hub | P1 | Map is a mandatory 2-click toll for History/Memory/Governance (Settings now direct via NAV-1) | bottom-bar = Map+Settings+Help `:8327-8336` | Routine surfaces cost double clicks | Promote History + Memory to direct launchers | **Fixed** (#2610) |
| NAV-3 | Overlays / browser history | P1 | No overlay is deep-linkable; mount/dismiss never touch URL/history → browser Back leaves the page | `overlay_host.py:359-370`; `do_GET` has no `?overlay` | Back doesn't close modals; no bookmarking | pushState on mount + popstate→dismiss; honour `?overlay=` | **Fixed** — NAV-3a #2639 (history) + NAV-3b #2640 (route swap) + NAV-3c #2641 (`?overlay=` deep-link) + NAV-3d #2644 (already-stacked-route history alignment) |
| NAV-4 | Search / palette launcher | P2 | ⌘K palette (the search/fast path) has no visible launcher | `overlay_host.py:406`; not in topbar/bottom-bar | Mouse-only users can't find search | Add a search pill (⌘K hint) emitting `cmd.open` | **Fixed** (#2610) |
| NAV-5 | Ambiguous "settings" controls | P2 | Icon-only "V" (Vault settings) collides with the hidden Local-UI "Settings" | `serve_dev_page.py:590` | Two different "settings", one a bare letter | Label distinctly (Vault config vs Preferences) | **Documented** |
| NAV-6 | Vault chip affordance | P3 | Vault chip is both identity and the only Browse launcher; looks like a label | `serve_dev_page.py:584` | No labelled "Browse" affordance | Add a Browse verb / folder glyph | **Documented** |
| A11Y-1 | Vault-browser action strip | P1 | "Copy path / Find related / Queue for review" were `<div onclick>` — no role/tabindex/keydown/focus | `serve_dev_page.py` `_action()` builder | Keyboard/SR users can't fire 3 of 4 note actions | Add `role=button`+`tabindex`+Enter/Space (this.click) + `:focus-visible` | **Fixed** |
| A11Y-2 | Filter chips | P2 | Filter chips were `<span onclick>` — keyboard-unreachable, no focus | `serve_dev_page.py` filter-chip builder | Keyboard/SR users can't filter Browse | Same keyboard treatment + `aria-pressed` + `:focus-visible` | **Fixed** |
| A11Y-3 | Help & Memory drawers | P2 | Closed drawers translate off-screen but kept controls in the tab order (no `inert`) | help `:8423`; `memory_review_drawer.py` setOpen | Phantom focus stops on hidden controls | Toggle `inert` on open/close (Settings-drawer precedent) | **Fixed** |
| A11Y-4 | Overlay host focus | P3 | mount() doesn't move focus into the overlay; dismiss() doesn't restore trigger focus | `overlay_host.py:348-370` | SR users not announced into dialog | Focus first focusable on mount; restore on dismiss | **Documented** |
| A11Y-5 | Left-panel tablist | P3 | ARIA tabs lack arrow-key roving (tabs are real buttons, so usable) | `serve_dev_page.py:982-1000` | Minor ARIA contract gap | Add Arrow Left/Right + roving tabindex | **Documented** |
| ST-1 | Operator drawer | P1 | `loaded=true` set *before* fetch → a transient failure pins the error state forever (reopen never retries); raw `String(err)` shown | `serve_dev_page.py:8178-8196` | Diagnostics drawer can get permanently stuck | Set `loaded` only on success (+ in-flight guard); calm copy; raw error in `data-error` | **Fixed** |
| ST-2 | ⌘K palette actions | P1 | `postPanelAction` POST has no `.then/.catch`; no loading/receipt/error, no in-flight disable (double-submit) | `panel_palette.py:584-599` | Silent action; no feedback; double submits | Disable in-flight (`aria-disabled`); reflect result via `data-action-state` | **Fixed** |
| ST-3 | ⌘K palette filter | P2 | Filtering to zero matches blanks the palette — no "no matches" empty state | `panel_palette.py:555-562` | Looks broken when filter excludes all | Added a `palette-filter-empty` "no matches" row toggled by `applyFilter` | **Fixed** |
| ST-4 | Note title | P2 | `.note-title` had no wrap → long unbroken title overflows header | `serve_dev_page.py:9473-9480` | Header overflow on slug/URL/path titles | `overflow-wrap:anywhere; word-break:break-word` | **Fixed** |
| ST-5 | Rail proposal cards | P2 | `.act-proposal*` had no CSS → no wrap in the 280px rail | `serve_dev_page.py:4497-4502`; no `.act-proposal` CSS | Long tokens overflow the rail | Add word-break rules for proposal cards | **Fixed** |
| ST-6 | Loading states | P3 | Only the operator drawer shows a loading state | `panel_palette.py`, `serve_dev_page.py:8147` | Future fetch actions lack in-flight cue | Add `aria-busy`/spinner to fetch handlers | **Documented** |

---

## 4. Click-budget map

Standard: primary actions 1–2 clicks · secondary 2–3 · rare/admin deeper but clearly labelled.

| Destination / action | Current path | Current clicks | Target | Problem | Recommendation |
|---|---|---|---|---|---|
| Home / vault root | Wordmark → `/` | 1 | 1 | — | none |
| Entry verbs (Find/Jot/Map) | Entry screen | 0 | 0 | — | none (bright spot) |
| Vault browser | Vault chip → `vaultBrowser.focus()` | 1 | 1 | Chip looks like a label (NAV-6) | add Browse cue |
| Open a note | `?note_path=` link / recents | 1–2 | 1–2 | only deep-linkable destination | none |
| Right panel / proposals | Ambient rail | 0–1 | 0–1 | — | none |
| **Command palette / search** | ⌘K *or* Map→palette | 2 (mouse) | 1 | ~~no visible launcher (NAV-4)~~ **Fixed (#2610)** | done — direct launcher shipped |
| **Settings** | Map → scroll grid → node | 2 | 1 | **zero direct affordance (NAV-1)** | add Settings launcher |
| **Memory review** | Map → node | 2 | 1 | ~~map-only (NAV-2)~~ **Fixed (#2610)** | done — direct launcher shipped |
| **Receipts / history** | Map → node | 2 | 1 | ~~map-only (NAV-2)~~ **Fixed (#2610)** | done — direct launcher shipped |
| Governance counts | Map → node → receipts | 2 | 2 | via receipts | OK if receipts gets a launcher |
| System map | Bottom-bar Map | 1 | 1 | — | none |
| Capture / create | Button / ⌘N | 1 | 1 | — | none |
| Operator / diagnostics | Map → node | 2 | 2 | by design (rare) | OK (consider gating) |
| **Back / close overlay** | Esc / scrim / **browser Back** | — | — | ~~browser Back fails (NAV-3)~~ **Fixed (#2639/#2640/#2641)** | done — Back closes the topmost overlay; `?overlay=` deep-links |

---

## 5. Markdown rendering matrix

| Feature | Works? | Evidence | Fix |
|---|---|---|---|
| Headings h1–h6 | ✅ | `_HEADING_RE`, `_render_heading` | — |
| Paragraphs / bold / italic / strikethrough | ✅ | `_render_text_segment` | — |
| Inline code / fenced code | ✅ | `_render_inline`, `_render_fenced_code`; `<pre>` has `overflow-x` | — |
| Ordered / unordered / nested lists | ✅ | `_build_list_html` (indent-aware) | — |
| Task lists / checkboxes | ✅ | `_TASK_RE` | — |
| Blockquotes | ✅ | `_render_blockquote` | — |
| Links / wikilinks | ✅ | `_render_wikilink` (resolved/missing/ambiguous) | — |
| Images / embeds | ✅ | `_render_asset` (alt text never empty) | — |
| Horizontal rules | ⚠️ leading `---` | `_is_thematic_break` ok; leading `---` triggers a frontmatter diagnostic (MD-6) | **Documented** |
| Table — 3-dash multi-col | ✅ | baseline | — |
| Table — 1–2 dash separators | ✅ **(fixed)** | was `<p>`; now `<table>` | **MD-1 Fixed** |
| Table — single column | ✅ **(fixed)** | was `<p>`; now `<table>` | **MD-2 Fixed** |
| Table — alignment `:--`/`--:`/`:--:` | ✅ **(fixed)** | now emits `style="text-align:…"` | **MD-3 Fixed** |
| Table — escaped pipe `\|` | ✅ **(fixed)** | now one cell, unescaped to `\|` | **MD-4 Fixed** |
| Table — pipe in inline code / aliased wikilink in a cell | ✅ **(fixed)** | span-aware split keeps `` `a\|b` `` & `[[Note\|Alias]]` in one cell | **MD-7 — via #2596** (this PR builds on it) |
| Wide table (horizontal overflow) | ✅ **(fixed)** | wrapped in `.vault-table-scroll` | **MD-5 Fixed** |
| Long table (many rows) | ✅ | scrolls via note-body | — |
| Table inside a scrollable panel | ✅ **(fixed)** | covered by MD-5 wrapper | **MD-5 Fixed** |
| Code block inside panel | ✅ | `<pre>` `overflow-x:auto` | — |
| Markdown mixed with app metadata (`%%…%%`, `<!--ai:-->`) | ✅ | stripped from human view | — |

---

## 6. Right-panel scroll matrix

| Scenario | Works? | Evidence | Fix |
|---|---|---|---|
| Note-body reading pane, long markdown | ✅ | `.note-body` `min-height:0; overflow-y:auto` | — |
| **Right agent-rail, many proposals** | ✅ **(fixed)** | was `overflow:hidden` parent + non-shrinking body; Playwright: bottom 5461px below viewport → now scrollable | **SC-1 Fixed** |
| Settings drawer scrolls | ✅ | `top:0;bottom:0;overflow-y:auto` | — |
| Memory review drawer scrolls | ✅ | max-height + inner `overflow-y:auto` | — |
| Receipts / capture / system-map / vault-settings | ✅ | max-height + inner scroll child | — |
| Vault browser list scrolls | ✅ | inner `overflow-y:auto` | — |
| **Narrow-mode portrait sheet** | ✅ **(fixed)** | height-capped snaps had no `overflow-y` | **SC-2 Fixed** |
| Sticky header covering content | ✅ | headers `flex-shrink:0`, body owns scroll | — |
| Close/navigate when scrolled deep | ✅ | overlay close is fixed/host-owned, not in scroll flow | — |
| Settings local-only badge layering | ⚠️ | `position:fixed` floats over scrolled drawer (SC-3) | **Documented** |

---

## 7. Map information-leak audit

The map is a **default human-view surface** (1 click), so all visible copy is user-facing.

| Surface | Internal info exposed? | Evidence | Fix |
|---|---|---|---|
| Center node — trace id | ✅ runtime correlation id in `<code>` | center-meta `trace_id` span | **Fixed** — gated behind `?diagnostics=1` (kept in DOM for operators) |
| Resurface node — reach text | ✅ Python fn `_render_resurface_mode` + `overlayHost.mount` | resurface_rail `reached` | **Fixed** — rewritten to plain copy |
| Routable nodes — reach text | ✅ intent tokens `cmd.open`/`memory.open`/`vaultBrowser.focus()` | nodes' `reached` | **Fixed** — rewritten (kept ⌘K hints) |
| Nodes — status notes | ✅ "Projection"/"governed handoff"/"queue_review"/"canonical hash" | `status_note` | **Fixed** — "Ready — …" plain copy |
| Mode chip | ✅ raw enums / `local-ui` | `_node_html` mode span | **Fixed** — humanised; `local-ui` hidden; `data-mode` kept machine |
| Parked note | ✅ "(spec §Parked, Q15–Q16)" | parked note | **Fixed** — humanised |
| Intro note / center sub | ⚠️ "renders/routes/re-classifies", "latency ladder" | intro note, `MAP_CENTER_SUB` | **Fixed** — humanised |
| Operator node | ⚠️ "Operator diagnostics … not a daily-use surface" | operator node | **Fixed** (→ "System status") / consider gating |
| `data-*` attributes (status/authority/surface-id/intent) | ❌ DOM-only, not rendered text | node attrs | No change — machine hooks, kept for tests/routing |

**Contract hardening:** the existing C4 test (`test_system_map_no_issue_refs`) — which forbade `#1234`/`SEP-05` in node copy — was extended to also reject source symbols and intent tokens (`_fn(`, `x.y(`, `*.open/focus/mount/dismiss/peek`), so this class of leak can't silently return.

---

## 8. Remaining risks & next actions

**Recommended product decisions (not changed unilaterally — the map-as-hub was deliberate in #2447):**
1. **NAV-1/2/4 — direct launchers.** ✅ **Delivered.** Bottom-bar **Settings** (gear) launcher (NAV-1) plus **History** and **Search** (⌘K) promoted to direct launchers (NAV-2/NAV-4, #2610). The map remains the complete index. This serves the core principle "reach every important function in the minimum practical clicks without hidden knowledge."
2. **NAV-3 — browser history + deep links for overlays.** ✅ **Delivered.** `history.pushState` on mount with a `popstate` listener dismissing the topmost overlay (NAV-3a #2639), an atomic `overlayHost.replace` swap for the System Map route (NAV-3b #2640), `?overlay=<id>` deep-linking honoured server-side in `handle_get` (NAV-3c #2641), and already-stacked route targets reusing their existing history entry (NAV-3d #2644). Back now closes modals and surfaces are shareable. The shipped contract is in `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Overlay browser-history + deep-link contract`.

**Behavioural JS fixes worth a live-runtime pass:**
3. **ST-1** Operator drawer: set `loaded` only on fetch success; render a calm, retryable error.
4. **ST-2/ST-3** ⌘K palette: handle POST success/error, disable in-flight, add a "no matches" empty state.

**Low-risk polish:**
5. **A11Y-4/A11Y-5** focus-into-overlay on open + restore on close; arrow-key roving for the left-panel tabs.
6. **MD-6** suppress the spurious frontmatter diagnostic for a lone leading `---`.
7. **MAP-8** optionally diagnostics-gate the operator node itself.

---

## Appendix — files changed in this pass
This branch (`chore/companion-ui-ux-audit`) is based on **`origin/main`** — the original audit was performed on the stale `fix/2527` branch (39 commits behind main), so every change was rebased onto current shipping code and re-verified.
- `companion-ui/companion-app/companion_ui/renderer/vault_markdown_renderer.py` — table parser/renderer (MD-1…MD-5; built on #2596's MD-7 span-aware splitter).
- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py` — table-scroll CSS, right-rail scroll, portrait-sheet scroll, note/proposal word-break, vault-action & filter-chip keyboard + focus, Help-drawer `inert`, **NAV-1 Settings launcher**, **ST-1 operator-drawer retry**.
- `companion-ui/companion-app/companion_ui/workspace/system_map_overlay.py` — human copy, trace-id gate, mode-chip humanisation.
- `companion-ui/companion-app/companion_ui/workspace/panel_palette.py` — **ST-2** in-flight/result handling, **ST-3** filter empty-state.
- `companion-ui/companion-app/companion_ui/workspace/memory_review_drawer.py` — `inert` on close.
- Tests: `test_vault_markdown_renderer.py` (5 complementary table tests on top of #2596's span tests), `test_system_map_overlay.py` (extended C4 contract + copy), `test_reentry_orientation_treatment.py` (scoped cold-start assertion), `test_settings_drawer.py` (NAV-1 contract update), `test_topbar_edge_job.py` (NAV-1 test), `test_panel_palette.py` (ST-2/ST-3 tests), `test_operator_overlay_render.py` (ST-1 test).

**Verification (run from the worktree, base = origin/main):**
- `tests/companion_ui` — **1785 passed, 5 skipped, 0 failed** (on the branch rebased onto current `main`, including #2596).
- `ruff check` clean on all changed files; markdown table fixes reproduced before/after (incl. inline-code & aliased-wikilink cells); map copy machine-checked free of source symbols/intent tokens; no new `mypy` errors (pre-existing baseline only).
- ST-1/ST-2/ST-3 are JS behavioural fixes verified by render/string tests + reasoning; a live-runtime smoke is still recommended before relying on them in production.
