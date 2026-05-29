# Adaptive Workspace Layout — Design Handoff

Corrective UI/layout pass for the Companion UI / Vault Browser workspace. Supports parent issue **#1395** and child issues **#1396–#1401**.

## 1. Status and authority

This document is **design input**, not authority.

- It is **subordinate** to repo source-of-truth, runtime boundary docs, shipped behavior, and any governed Vault layout/orientation notes explicitly referenced by the implementation issue.
- It must not override Panel, Canvas, Vault Browser, or runtime authority contracts. If this document and a shipped contract disagree, the contract wins and this document should be amended.
- Companion UI remains a shell/host for cognitive work. It is not an authority surface.
- Companion UI never writes vault files directly. All mutation flows through governed runtime paths.
- Companion UI never reclassifies server/runtime-declared proposals, action modes, or guard states locally.
- Internal/test state may remain on stable `data-*` attributes even when removed from human-facing chrome.

Pixel values and dimensions in this handoff are recommended ranges, not dogma. If implementation deviates from the recommended layout ranges, the PR must explain the deviation and prove through browser UAT that note readability, single-left-panel behavior, and no-bottom-clipping are preserved.

## 2. Core workspace principle

The central note surface is the cognitive anchor.

1. The note body is primary. It is the largest, most legible, most stable region. Nothing may squeeze it below a usable reading size, and it must never clip at the bottom of the viewport.
2. Side panes are contextual support, not permanent competing workspaces. The left context panel and right companion rail exist to serve the current task. When they have nothing useful to show, they compact or collapse.
3. The default workspace shows only what helps the current task. Diagnostics, idle states, raw metadata, and runtime telemetry are not part of the default reading surface.

If an element does not help the user read, navigate, orient, or take a governed action right now, it should compact, collapse, or move to diagnostics.

## 3. Target desktop layout

Target structure:

```text
one adaptive left context/navigation panel
+
central note surface
+
optional/collapsible right companion rail
```

There is exactly one left panel and exactly one right rail. No third browser surface and no second left column.

### 3.1 Region width guidance

| Region | Min | Default | Max | Collapsed |
|---|---:|---:|---:|---|
| Left context panel | 240px | 288px | 360px | 0px content plus persistent reopen affordance |
| Central note surface | 600px usable | flexes to fill | n/a | never collapses |
| Right companion rail | 300px | 336px | 380px | 0px content plus compact posture chip |

The central surface always takes remaining space after side regions resolve.

### 3.2 Central note constraints

- Minimum usable width: 600px.
- Prose column should be bounded around 68–74ch and centered in the available central width.
- On a 720px-tall viewport, the body should show at least 8–10 lines below sticky chrome without scrolling.

### 3.3 Scroll ownership

The note-bottom clipping bug is a scroll-ownership failure. The corrected contract is:

- App shell: `height: 100dvh; overflow: hidden`.
- Page/body does not scroll.
- Central note surface owns the primary reading scroll.
- Central scroll container uses `min-height: 0` and bottom padding of at least 96px.
- Left browser list scrolls inside the left panel.
- Right rail scrolls inside the rail only when expanded content exceeds available height.
- Header is outside the scroll regions.

Acceptance target: at 1280x720 and 1440x900, a long note must allow the last heading and paragraph to be fully visible by scrolling the center region, with breathing room below.

### 3.4 Responsive summary

- At 1400px and wider: all three regions may be open.
- At 1100–1400px: prefer center plus the currently relevant side region; collapse the other.
- At 860–1100px: only one side region open at a time.
- Below 860px: side regions become overlay drawers/sheets; center remains available underneath.

## 4. Left context panel model

There is exactly one left context panel. It has four modes and only one mode is visible at a time:

- `browse`
- `outline`
- `context`
- `collapsed`

A small mode switcher or labeled tab set may sit at the top of the panel. Switching modes must not spawn a second panel, modal, or duplicate browser.

Default mode policy:

- Opening a note via link/deep link: `outline`.
- Explicit Browse Vault action: `browse`.
- `context` and `collapsed`: user-initiated or auto-selected by state hierarchy, not cold-start default.

The panel remembers the last non-collapsed mode.

### 4.1 Browse mode

Purpose: choose and open notes/artifacts. This is the canonical Vault Browser.

Must show:

- folder/path hierarchy or grouped rows;
- scannable artifact titles as primary row text;
- compact kind/type cue where useful;
- active/selected note;
- search/filter input only if already in current scope.

Must not show:

- raw UUID as primary row text;
- `trust`, `origin`, `review_state`, `source_ref`, `content_hash`, or `zone` as inline row noise;
- multiple Vault Browser instances;
- graph, timeline, or saved views.

Selecting a row opens the note in the central pane and should switch the left panel to outline mode.

### 4.2 Outline mode

Purpose: navigate headings of the current note.

Must show:

- current note heading tree, usually H1–H3;
- current section highlighted as the user scrolls. If current implementation already supports this behavior, preserve it; otherwise implement only if covered by the relevant child issue;
- compact note-local context only.

Must not show:

- full Vault Browser at the same time;
- raw metadata/frontmatter dump;
- browser filters.

### 4.3 Context mode

Purpose: compact artifact/workspace context, not a second metadata column.

May show:

- note path;
- artifact identity status, not raw UUID by default;
- content hash or conflict status only when relevant;
- companion-note presence/missing state only when relevant.

When nothing is notable, use concise copy such as: `Nothing needs attention for this note.`

### 4.4 Collapsed mode

Purpose: maximize reading surface.

Must provide:

- persistent visible reopen affordance;
- memory of last mode;
- browse/outline-triggering actions that restore the panel into the correct mode.

## 5. Duplicate Vault Browser rules

The current workspace must be corrected so the Vault Browser is not visible in multiple competing places.

### 5.1 Do-not-render list

Normal desktop workspace must not show simultaneously:

- two left panels;
- Vault Browser in more than one surface;
- default browser modal when the left panel is available;
- browser list plus a second browser/outline rail competing with it;
- raw metadata rows as primary browser list content.

### 5.2 Canonical entrypoint behavior

There is one canonical browser: left panel in `browse` mode.

- Any Browse Vault action opens/focuses the left panel in `browse` mode.
- If the panel is collapsed, Browse Vault expands it into `browse` mode.
- Desktop Browse Vault does not open a modal.
- A quick-open palette may exist as a finder, but it is not the Vault Browser and must close on selection.
- Wikilink disambiguation may focus browse mode scoped to candidates, rather than opening a competing modal.

### 5.3 Modal/sheet fallback

A modal/sheet browser is allowed only as responsive fallback when viewport width is too narrow for a persistent left panel beside a usable center. It must not appear as the default desktop browsing UX.

Dev/operator chrome, such as `NOTE_PATH`, `LOAD`, or top-level harness controls, may exist behind an explicit diagnostics toggle, dev-only flag, or operator-only route. It must not render as default human workspace chrome.

## 6. Vault Browser density and scale

The browse list must stay legible at 40+ artifacts across nested directories.

### 6.1 Row layout

Rows should prioritize:

1. title/name;
2. compact folder/path context;
3. compact kind/type cue.

Rows must not use raw metadata as primary text.

Recommended row behavior:

- row height 32–40px;
- selected row has clear active marker;
- hover/focus is visible but restrained;
- list scrolls inside the left panel;
- long title uses ellipsis;
- long path uses middle truncation.

### 6.2 Grouping

- Group rows by folder where possible.
- Show folder path once per group header, not repeatedly as row noise.
- System/companion notes may be grouped, de-emphasized, or hidden behind a clear toggle.

### 6.3 Metadata visibility

Default inline:

- title;
- folder/group;
- compact kind cue;
- selected/active marker.

Behind details/inspector/progressive disclosure:

- UUID/artifact ID;
- content hash;
- trust;
- origin;
- source_ref;
- review_state;
- zone;
- full absolute path;
- indexed timestamp.

Graph-first browsing is out of scope.

## 7. Central note surface

The center is the anchor.

- The note surface remains visually dominant.
- Body prose uses comfortable reading measure and does not run edge-to-edge on wide screens.
- Side panes collapse before shrinking center below 600px usable.
- Central pane owns the primary note scroll.
- No nested double-scroll unless explicitly defined and tested.

### 7.1 Metadata chrome

- Frontmatter/YAML must never render as body prose.
- Metadata lives in bounded breadcrumb/properties chrome above the body.
- Metadata chrome should be collapsed by default behind a `properties` disclosure.
- If current implementation already provides this disclosure, preserve and consolidate it; otherwise implement it only under the relevant child issue.
- Path, artifact ID/UUID, content hash, and vault/channel identity must be findable there, but must not dominate or precede prose.

### 7.2 Markdown rendering guidance

- Headings: clear hierarchy and generous rhythm.
- Callouts: bounded blocks, not ordinary blockquotes.
- Mermaid: graceful bounded fallback if rendering is unavailable or invalid.
- Code blocks: internal horizontal scroll, never widening the column.
- Links/wikilinks: distinguish resolved vs unresolved calmly.
- Images/embeds: bounded to reading measure, with labeled placeholder if unavailable.

## 8. Right companion rail

The right rail must earn its space. It should not be a permanent debug/status dump.

### 8.1 Default state

Default is compact: one posture chip in the header or narrow icon strip. It expands only when useful.

### 8.2 Expand for actionable or safety-critical states

Rail may expand for:

- active Panel proposal;
- Panel receipt;
- block reason;
- WriteGuard block affecting an attempted action;
- active Canvas edit session;
- Canvas recovery/conflict;
- actionable Reorient step;
- important runtime unavailable/degraded state affecting safe operation.

### 8.3 Compact/collapse for non-actionable states

Rail compacts/collapses when only these states exist:

- no proposals;
- no candidates;
- Canvas disabled with no current action;
- Find unavailable with no candidate payload;
- Resurface degraded/no candidate;
- Suggestions idle;
- generic session persistence status.

### 8.4 Single posture/absence treatment

Replace multiple inactive cards with one compact posture line, for example:

`Companion · idle — no active proposals. Details`

Details may reveal per-capability state, but default view should not stack inactive cards. Critical safety state must not be hidden.

## 9. State hierarchy

When space is contested, visible space follows this priority:

1. active user task / note body;
2. critical safety/block/recovery state;
3. active proposal/edit/receipt;
4. current navigation/orientation need;
5. passive context;
6. diagnostics/details;
7. idle/unavailable/no-candidate/no-proposal states.

Lower-priority states must not shrink or push away higher-priority states. In particular, priority 5–7 must not shrink the note body.

## 10. Responsive behavior

- Normal desktop: all three regions may be open if center remains usable.
- Narrow desktop: center plus the currently relevant side region; collapse the other.
- Tablet/narrow: one side region at a time.
- Very narrow: overlay drawers/sheets.

Remote-client constraints:

- no client-side dependency on `127.0.0.1` or `localhost`;
- collapse panes instead of clipping note;
- keep state legible at smaller browser sizes.

Collapse-before-shrink rule:

1. collapse non-active side region;
2. collapse second side region;
3. only then reduce center toward its 600px floor;
4. below that, use drawer mode.

## 11. Human-facing copy rules

Internal runtime/test labels must not leak into the default human UI. They may remain in `data-*` attributes.

Do not show in default UI unless inside diagnostics/dev chrome:

- `user not present`;
- `composer enabled`;
- `thinking`;
- `SUGGESTION idle`;
- `FIND unavailable`;
- `Session persistence: in_memory`;
- raw trust/zone/review/kind labels;
- bare UUIDs;
- `DEV / NOT PRODUCTION` banner;
- `SERVER-SIDE RUNTIME same-origin bridge`.

Preferred copy patterns:

| State | Default copy |
|---|---|
| No active proposal | `Companion · idle — no active proposals.` |
| Canvas disabled | `Editing is off right now. You can read and navigate; the runtime has Canvas disabled.` |
| Find unavailable | `Nothing to find yet — no candidates from the runtime.` |
| Resurface no candidates/degraded | `Nothing to resurface right now.` |
| WriteGuard blocked | `This change was blocked: <reason>. Nothing was written to the vault.` |
| Runtime unavailable | `Runtime unreachable. Reading works from the vault; actions are paused.` |
| Browsing unavailable | `Vault index unavailable — showing read-only filesystem fallback.` |
| Read-only note | `Read-only — editing is not permitted for this note.` |

Rule: never show an internal state name as the whole message. State what it means for the user and what they can safely do next.

## 12. Test and UAT checklist

Implementation PRs for #1397–#1401 must satisfy relevant items below.

Layout and structure:

- one left context panel visible at a time;
- no duplicate Vault Browser surfaces;
- no second left column or competing outline/browser rail.

Central note:

- note body is visible and not bottom-clipped on a long note, such as the Markdown Feature UAT note or an equivalent fixture, at 1280x720 and 1440x900;
- last heading/paragraph reachable with at least 96px breathing room below;
- note body remains primary;
- frontmatter/YAML does not render as body prose;
- only named regions scroll; page/body does not.

Browser density:

- 40+ files across nested directories render cleanly;
- browser list scrolls inside the left panel;
- no raw metadata in row text;
- human vs companion/system notes distinguishable.

Right rail:

- compact when only non-actionable states exist;
- expanded when critical/actionable state exists;
- permanent red disabled card does not appear as default state.

Copy and leakage:

- no internal/test labels in default UI.

Responsive and remote:

- collapse-before-shrink verified at 1100px and 860px;
- remote-client UAT from laptop browser;
- no dependency on client-local `127.0.0.1`/`localhost`.

Evidence:

- before/after screenshots;
- at least three note selections with timings.

## 13. Implementation notes for child issues

Implementation PRs should cite the relevant sections of this handoff in their PR body:

- #1397: §§3, 7, 10, 12
- #1398: §5
- #1399: §4
- #1400: §6
- #1401: §§8, 9, 11

### #1397 — Single adaptive workspace layout contract

Establish the one-shell, three-region structure from §3: `height:100dvh; overflow:hidden`, sticky header, three flex/grid regions, `min-height:0` on scroll containers, and at least 96px center bottom padding. Codify region widths, collapse order, and scroll ownership.

### #1398 — Remove duplicate Vault Browser surfaces

Apply §5. Funnel every Browse Vault entrypoint into the left panel `browse` mode. Keep modal only as narrow responsive fallback. Move dev harness controls to dev/operator chrome.

### #1399 — Adaptive left context panel modes

Implement one panel with four modes from §4. Only one mode visible at a time. Selecting a browser row opens in center and switches to outline.

### #1400 — Vault Browser density and 40+ artifacts

Apply §6. Single-line rows, folder grouping, compact kind cue, in-panel scroll, truncation, and metadata behind disclosure.

### #1401 — Right rail compaction

Apply §§8–9 and §11. Default compact posture chip; expand only for actionable/safety-critical states; never hide critical safety state.

## Non-goals

Do not propose or implement:

- full Obsidian replacement;
- graph-first browser;
- saved views;
- timeline/activity browser;
- relation graph;
- new metadata model;
- new editor replacement;
- new runtime authority semantics;
- new write paths;
- hidden automation;
- direct UI vault writes;
- client-side reclassification of proposals or guard states.

This document supports #1395 and remains subordinate to repo source-of-truth and runtime contracts.
