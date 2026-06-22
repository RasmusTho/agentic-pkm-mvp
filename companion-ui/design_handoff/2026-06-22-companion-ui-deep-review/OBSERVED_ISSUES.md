# Observed Issues (found during capture)

Defects already found while building this package, with evidence. **Start past these** — don't
spend the review re-reporting them. Where useful, treat each as a symptom and ask what the
*design* should be, not just how to patch the bug.

Confidence is stated per item. "Confirmed (static)" = visible and reproducible in the captures.
"Candidate" = looks wrong in the static capture but may depend on live behaviour — flag for live
UAT.

---

## #1 — Topbar overflows and clips its own controls; it is not responsive · **Confirmed (static)**

The unified topbar does not adapt to width. Instead of wrapping, collapsing into a "more" menu,
or prioritising, it simply **clips** — and what gets clipped includes the surface-launch icons
that open the overlays.

Evidence:
- `evidence_topbar_1280.png` (1280px): the right icon cluster is **truncated** — `?`, `ⓘ`, `/`,
  and "BROWSE VAULT" are cut off / sit behind the right Panel rail. Only ~6 of the surface icons
  survive.
- `evidence_topbar_1920.png` (1920px): the *same* markup fits cleanly with every icon and label
  visible. So this is non-responsive overflow, not missing content.
- `shell_01_active_anchor.png` (1440px): "BROWS…" is clipped at the right edge.

**Why it's functional, not cosmetic:** these icons are the primary way to open the command
palette, capture, memory review, settings, vault browser, receipts, and system map. At common
laptop widths (≤~1440) several of those entry points are **unreachable by pointer**. (During
capture, Playwright clicks on the launch icons failed as "element not visible" for exactly this
reason; the overlays could only be opened through the page's JS API.) Keyboard shortcuts cover
⌘K / ⌘N only — the rest have no fallback.

**Design question, not just a fix:** the topbar is being asked to carry app identity, vault
status, connection/recovery state, time, *and* seven surface launchers, *and* coexist with a
right rail that overlaps it. That's likely too much for one row. The review should propose what
the top edge is actually *for* and where the overflow goes.

---

## #2 — Right Panel rail overlaps / collides with the topbar's right cluster · **Confirmed (static)**

The Panel/agent rail's header (`PANEL · Panel proposal ready` / `No active Panel proposal`) is
drawn over the top-right of the topbar rather than beginning *below* a shared top band. In
`evidence_topbar_1280.png` and `shell_01_active_anchor.png` the Panel box sits on top of the
topbar icons; the two regions claim the same pixels. This is a layout/z-order composition bug
where two top-anchored regions aren't reconciled into one grid. It compounds #1 (the rail eats
the space the icons need).

---

## #3 — Narrow layout: top status string overflows off-screen · **Confirmed (static)**

At 430px (`narrow_shell_01_active_anchor.png`) the identity/status string
`Yggdrasil · vault/dev · vault ok · N RECOVERY · ok Online · as…` runs straight off the right
edge with no wrap, truncation affordance, or horizontal scroll. The same root cause as #1
(non-responsive top band) but on the small end. Status the user can't read is status that isn't
doing its job.

---

## #4 — Narrow layout: bottom-edge collision between hint bar, sheet triggers, and floating pills · **Confirmed (static)**

At 430px the bottom region stacks three things that fight for the same corner
(`narrow_shell_01_active_anchor.png`):
- the "Edit note body · Opt-in · keeps the reading su[rface]…" hint bar (right-clipped),
- the bottom-sheet triggers (`≡ Outline`, `Panel`),
- the floating `⚠ Operator` and `? Help` pills.

They overlap rather than compose. The hint text is clipped, and the floating pills sit over the
sheet triggers. The bottom edge needs a single reconciled layout (a real bottom bar / sheet
grammar) instead of independently-positioned fixed elements.

---

## #5 — Memory review opens to a degraded/empty state with no live data · **Methodology caveat, verify live**

`overlay_03_memory_review.png` shows "Pending candidates — Review queue unavailable — the
runtime could not be reached. Nothing was decided." This is the *correct* fallback for the
static-capture setup (no runtime), and the empty-state copy is good. But it means the **populated**
memory-review experience (candidate cards, accept/reject/revise/defer, the governed decision
boundary) is **not exercised in this package**. Judge the structure and copy here; flag the
populated flow for live UAT before signing off J6.

---

## Candidates worth a hard look (lower confidence, judge from the captures)

- **Topbar information altitude:** "N RECOVERY", "ok Online", "vault ok", "as of 21:08", the
  amber `⚠ Operator` pill — several of these read as operator/diagnostic telemetry on what is
  supposed to be an anti-dashboard surface. Does this belong on the front edge, or behind the
  System Map?
- **Right-rail emptiness:** in `shell_01_active_anchor.png` the Panel rail is mostly blank
  ("Companion · idle — no active proposals") yet occupies a full third of the width. Is a large
  permanently-reserved empty rail the right default for a reading-first surface?
- **Two competing "act" surfaces:** the rail proposals (`shell_03`) and the command palette
  (`overlay_01`) present the same governed proposals two ways. Intended redundancy, or a fork the
  user must learn?
- **Icon legibility:** the topbar surface launchers are terse single glyphs (`V`, `◈`, `≡`, `⚙`)
  with no labels until very wide. For an intermittent user, are they self-explanatory?
