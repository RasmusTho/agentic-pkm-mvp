# Vault Browser · Design Handoff

> **Non-authoritative design guidance.** Converted from the Claude Design handoff
> `Vault Browser Design Handoff.html` (2026-05-24). Constrained by SoT docs listed
> in [`SOURCE_MANIFEST.md`](SOURCE_MANIFEST.md). Conversion is faithful but not
> byte-exact: visual mockups in the source HTML are described in prose rather than
> reproduced as SVG/CSS. The original HTML is preserved in this package's source
> manifest reference for designers who need pixel-level detail.

---

**Crumb:** Vault Browser Foundation · Design Handoff · 2026-05-24

## The browser is the orientation layer over the vault — not a file picker, not a graph, not an automation surface.

Interaction-design handoff for the Vault Browser capability contract (Companion UI).
Scoped to the slices feeding #1253–#1257 and the slice grid that follows them.
Includes a critique of the current shipped Companion workspace shell, because the
Vault Browser opens into that shell and inherits its problems if they are not
fixed first.

**Refs**

- `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`
- `docs/HUMAN-FLOWS.md`

**Baseline:** Vault Browser MLP v0 (read-only enumeration).
**Scope:** MLP / near-term #1253–#1257 / future capability map.

---

## 01 · Executive summary

The Vault Browser is the long-lived navigation and orientation surface over the
vault. It must answer eight questions for the user at a glance — where am I,
what is this, why does it matter, where did it come from, what state is it in,
can I trust it, what has the system done around it, and what is safe to do
next. It is not a redesign of the workspace. It is the layer that loads things
into the workspace and prepares the user to act there.

### The shape of the work

- **MLP v0 stays as-is.** Read-only Markdown enumeration with deterministic
  filters. The contract floor in §6 of the capability contract is non-negotiable.
- **#1253–#1257 deliver the foundation.** Normalized metadata read model →
  metadata filters/badges → inspector → action display model → receipts. The
  five issues map onto five concepts in this doc.
- **The browser holds nine concepts, never collapsed.** Artifact, View, Query,
  Relation, Activity, Health, Action, Proposal, Receipt. The visual language
  must keep them distinct under uncertainty.
- **Action class is the load-bearing safety primitive.** Read-only, UI-only,
  bounded system write, governance write, agent proposal, blocked — six modes,
  six visual treatments, server-declared. The browser never reclassifies.
- **Degradation is a first-class state.** Vault identity unavailable,
  frontmatter invalid, relation index down, receipt source down, WriteGuard
  blocked — each rendered explicitly. Silent degradation is a contract
  violation.

### What this doc avoids

- Backend architecture, event schemas, endpoint shapes — out of scope.
- A graph-first navigation model — the contract forbids it and so does this doc.
- An inbox metaphor — the browser is a projection, not a queue, not a
  notification feed.
- Anything that would let an agent proposal touch a note without a governed
  action and a receipt.

---

## 02 · Critique of the current Companion workspace shell

The shipped UI (screenshot, 2026-05-24, `Companion UI UAT.md`) is the surface
the Vault Browser opens into. Several things are wrong on it that the browser
will inherit if we don't fix them. This is the load-bearing list — the rest of
this doc assumes these are corrected.

**C1 · frontmatter.** Frontmatter is rendered as note body. The block from
`uuid:` through `- companion-ui` appears verbatim above the heading. That's the
canonical metadata of the artifact being treated as prose. The user has to
mentally split body from metadata every time they open a note, and the artifact
identity row at top duplicates only some of it. *Fix:* Parse frontmatter at the
workspace boundary. Render the body without it; surface metadata in the
artifact strip + inspector. Never render frontmatter twice.

**C2 · safety strips.** Three stacked status rows compete. Browser chrome
warns `DEV / NOT PRODUCTION`. Then the
runtime/vault/channel/WriteGuard/Canvas/Update-flow/Guard row. Then a third row
with `WORKSPACE UPDATE / UPDATE REASON / GOVERNANCE VIA UPDATE / TRACE`. All
three are roughly the same visual weight, and the most important fact
(`GUARD degraded`) sits at the end of the second row with the same styling as
everything else. *Fix:* Collapse to one safety strip with a clear posture
(`online / degraded / blocked / unavailable`) on the left and identity/trace on
the right. Trace and reason move into the inspector. Posture state changes the
strip's background tone, not just a label.

**C3 · disabled affordances.** Disabled buttons are rendered enabled.
`START`, `CLOSE`, `APPLY BODY EDIT`, `UNDO` all have the same border/background
as live affordances; they are only distinguishable by reading the reason text
below. The addendum's §B rule already says: remove the button entirely in
read-only — do not just disable it. The current shell ignores that. *Fix:*
When `workspace_update.available = false`, do not render the composer or its
action buttons. Render an explicit absence card with the reason. This is the
same rule the Vault Browser will apply to every blocked action mode.

**C4 · state vocabulary leaks.** Internal labels reach the user.
`user not present`, `E I`, `composer enabled · thinking`, `SUGGESTION · idle`,
`FIND · unavailable` all read like backend state strings, not human copy. Each
violates the copy table already shipped in the MLP handoff (§11). The user
shouldn't be parsing finite-state-machine labels to know whether the system is
alive. *Fix:* All user-facing strings come from the copy table in the MLP
handoff. Internal state stays in `data-*` attributes for tests, not in visible
text.

**C5 · artifact identity row.** The artifact identity strip is correct in
shape but visually buried. `PATH · ARTIFACT · HASH` is exactly the right three
pills, but they're rendered at the same scale as a paragraph of body copy. This
row is supposed to be the user's permanent answer to "what is this and can I
trust the identity" — and right now it loses to the giant `Companion UI UAT`
serif title and the frontmatter block below it. *Fix:* Pull the identity strip
into the safety/identity bar at the top, just under the safety posture. Title
becomes the orienting display moment in the inspector and content area;
identity is permanent chrome.

**C6 · rail noise.** Right rail is a status dump. Six sub-sections (Canvas /
Log / Panel / Suggestion / E I / Find) stacked vertically with idle/unavailable
in five of them. A user opening this note sees a wall of "nothing is happening"
rather than "you are oriented; here is what is safe to do." This is exactly
the pattern the addendum cuts (Find, Resurface in v1). *Fix:* Hide cards that
have no content rather than rendering "idle"/"unavailable" stubs. The rail
should show: identity, safety posture, one Reorient card, the active
Canvas/Panel slot if it has content, plus an outcome card if any. Empty rail =
single line "Note loaded · no active session." Do not invent chrome to fill
the column.

**C7 · this is a debug surface.** Nothing here is wrong as a UAT verification
screen. The trace ID, channel name, workspace update reason, the verbatim
frontmatter — all useful for a developer running UAT against a Niflheim dev
runtime. The problem is calling this a Companion UI. It is currently shaped
for the runtime engineer, not for the human-first cognitive prosthetic user
described in `HUMAN-FLOWS.md §0`. *Fix:* Keep this view available as a
dev/diagnostic mode (toggle), but do not ship it as the default Companion UI.
The default opens with the Vault Browser, not a raw artifact identity dump.

**How this connects to the browser.** Every item above will reappear in the
Vault Browser if not addressed. The browser opens notes into this workspace,
so its trust contract bottoms out here. C1–C5 in particular block the inspector
design from being legible: there's no point surfacing frontmatter health,
trust, and review state in the inspector if the workspace then re-renders
frontmatter as body.

---

## 03 · Design principles

Eight principles, distilled from `VAULT_BROWSER_CAPABILITY_CONTRACT.md §2` and
the human-flow contract. The visual language follows from these; they are not
negotiable.

| Principle | What it means in this UI | Failure mode if violated |
|---|---|---|
| Preserve human agency. | The browser surfaces, ranks, and explains; it never auto-applies. Every governed action is named, deliberate, and produces a receipt. | Hidden authority — the user can no longer reconstruct what the system did. |
| Reduce orientation cost. | The eight orientation questions are answered without opening every artifact. Health, trust, review state, origin visible on the row. | The browser becomes a file picker; the user re-derives context every visit. |
| Cognitive distance via zones. | `active / semi_active / peripheral` as a stable overlay — never as a folder, never as maturity. | Zones drift into folder semantics; the cognitive distance signal is lost. |
| Separate read, suggest, write. | Six action modes, six visual treatments. Browsing, proposing, committing never collapse into one click. | Agent proposal ends up indistinguishable from a confirmed write; trust collapses. |
| Vault-driven, not DB-driven. | Frontmatter and Markdown are the source of truth surfaced in the UI. Store/DB read is for orientation; never described as authoritative. | The browser becomes a DB explorer; the vault no longer reflects what the user sees. |
| Expose uncertainty. | Unreviewed, generated, derived, low-trust content does not look like confirmed material. Trust and review posture are first-class signals on the row. | Generated text looks like asserted truth; the user can't tell what to rely on. |
| Avoid hidden automation. | Navigating to a note does not trigger any governed write. The browser may emit traces; it does not emit mutation. | Opening becomes acting; the user cannot move through the vault without risk. |
| Degrade legibly. | Every degraded state has a visible posture, a reason, and a safe next step. No silent failure paths. | "Empty" and "broken" become indistinguishable; the user can't tell when to trust the answer. |

---

## 04 · Information architecture

Five primary areas. Three are always visible (Safety / Identity strip,
View+Query bar, Result list). Two are progressive disclosure (Filter panel,
Inspector). The inspector itself is tabbed; only the first tab is open by
default. Nothing else is allowed to float chrome over the working area.

| Area | Visibility | Job | Authority class |
|---|---|---|---|
| Safety / Identity strip | Always | Posture (`online / degraded / blocked / unavailable`). Active vault + channel. Trace. | read |
| View + Query bar | Always | Switch among named views. Text/path/title query (deterministic). Result count. | ui-only |
| Result list | Always | Artifact rows. Title, path, kind, zone, review state, trust, health, action indicator. | read |
| Filter panel (left) | Collapsible | Metadata filters: kind, zone, review state, trust, origin, source ref, health. Receipts later. | ui-only |
| Inspector (right) | Opens on selection | Tabbed surface for one artifact. Preview · Metadata · Health · Provenance · Links · Activity · Receipts · Actions. | read + bounded + gov |

### Always-visible vs. progressive disclosure

- **Always:** safety posture, active vault/channel, query, view switcher,
  result list, current selection.
- **On selection:** inspector opens with Preview tab; metadata, health,
  provenance, links, activity, receipts, actions remain one click each.
- **On request:** filter panel expands. Saved views (future) live in the
  filter panel header.
- **Never floated:** no toasts. Outcome cards live in the rail. The browser
  does not chase the user's focus with notifications.

---

## 05 · Main layout

Three columns under one safety/identity strip. Filter rail on the left
(220px), artifact list in the center (fluid), inspector on the right (360px).
The list and inspector are the two surfaces the user lives in; the filter rail
is the one they configure once per session.

**Mockup summary — Vault Browser · Artifacts view · selected note desktop · 1280px:**

- *Safety/identity strip:* `online · vault: vault/dev · writeguard ok · channel: local-dev · trace 9ef0…1f49`.
- *View + query bar:* `files · artifacts · review · timeline · source · agent · graph · resurface | › uat (text/path/title) | 12 of 247`.
- *Filter rail (left):* groups for **zones** (active 5 / semi_active 42 / peripheral 200), **kind** (human_note 189 / companion_note 52 / attachment 6), **review state** (inbox 23 / needs_review 12 / reviewed 198 / archived 14), **trust** (assert 156 / suggest 68 / apply 23), **health** (valid 220 / missing_fields 15 / broken_links 9 / stale 3).
- *Result list (center):* filter chip dock `FILTERS · zone: active × · review_state: needs_review × · + kind + trust + origin + health`, then rows including:
  - `Companion UI UAT` — `active` `needs_review` — `Companion UI UAT.md · uuid 1111…1111` — `human_note · origin: manual · trust: internal · created 2026-05-23`.
  - `Q2 architecture review · synthesis` (selected) — `active` `needs_review` `3 proposals` — `Synthesize/2026-05-19-q2-architecture.md · uuid 4c8f…9a21` — `human_note · origin: derived · trust: suggest · missing: source_ref`.
  - `Inbox · 2026-05-22 meeting` — `semi_active` `inbox` — `Inbox/2026-05-22-meeting.md · uuid 7d2a…b144`.
  - `Yggdrasil capability contract — vault browser` — `active` `reviewed` — `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md · uuid b912…04ee` — `trust: assert · updated 2026-05-24`.
  - `Companion note · q2-architecture` — `semi_active` `companion` — `.system/companion/4c8f-9a21.md · companion_of 4c8f…9a21`.
- *Inspector (right):* artifact title `Q2 architecture review · synthesis`, pill row `active · needs_review · trust: suggest · origin: derived · health: missing source_ref`, tab bar `preview | metadata | health | provenance | links | activity | receipts`, actions section listing one row per action mode (`read · Open in workspace`; `bounded · Mark indexed · emits receipt`; `gov · Set review_state · reviewed · requires confirmation`; `proposal · 3 agent proposals · review · never auto-applied`; `blocked · Promote to canon · trust: suggest · governance write`), plus a "recent receipts" card (`receipt · ok · Indexed by ingest pipeline · trace 9ef0…1f49 · receipt 8c12…ab02 · 2d ago`).

### Layout rules

- **Selection is permanent until changed.** The inspector reflects the
  selected row; clicking the same row a second time does not close it. Close is
  explicit (Esc / X).
- **The result list scrolls independently of the inspector.** The inspector
  scrolls within itself; the user can scan a long list without losing the
  inspector context.
- **Safety strip is sticky; nothing else floats.** The strip stays pinned at
  the top across scroll. Filter chips and inspector tabs do not stick — they
  remain inside their column.
- **One density.** Row padding is 11px. Inspector field padding is the same.
  No "compact mode" toggle — density is fixed.

---

## 06 · Browsing modes

Eight named views. They are **projections**, not modes of the user — switching
views does not change the underlying authority class. Filters and query persist
across compatible views (e.g. text query carries from Files into Artifacts; an
artifact-only filter does not).

| View | Scope | What it shows | Used for |
|---|---|---|---|
| Files (mlp) | vault tree | File/folder enumeration. Path, title, size. No metadata. Equivalent to MLP v0. | Locating a known file. Verifying a path. Fallback when metadata is degraded. |
| Artifacts (#1253–#1255) | typed artifacts | Artifact rows with kind, zone, review_state, trust, origin, source_ref, health. | Default browsing surface. Orientation, scan, "what state is this in". |
| Review queue (#1254–#1255) | review_state ∈ {inbox, needs_review} | Artifacts requiring human review. Sorted by age, then by trust. | Daily / weekly review. Clearing the inbox without losing posture. |
| Timeline (#1257) | activity stream | Chronological activity. Created / edited / reviewed / indexed / agent_proposed / agent_blocked / archived. | Reorientation after interruption. "What happened while I was away." |
| Source / Evidence (defer) | artifacts with source_ref | Source artifacts and citations grouped by referent. Provenance-first. | Tracing a claim back to its source. Citation hygiene. |
| Agent activity (#1257) | receipts + proposals | System/agent-driven activity. Receipts (governed actions) and proposals (suggestions). | "What has the system done." Trust audit. Reviewing pending proposals. |
| Graph (future) | relations | Relation-driven view: `links_to`, `cites`, `derives_from`, `supersedes`, `duplicates`. Always optional. | Investigating relation structure. Never the default landing. |
| Resurfacing (future) | candidates | Forgotten / dormant material proposed for re-attention. Read-only until persistence ships. | Re-engaging stalled projects. Long-term project resurrection. |

### Default view selection

- **First load:** Artifacts view if `read_model_available = true`; otherwise
  Files.
- **Returning user:** last view used, scoped to current vault.
- **Degraded:** Files view, with a visible posture explaining why metadata is
  not available.

**On graph view.** Graph is a future capability and intentionally not the
default. The contract (§8) forbids it as primary navigation. When it ships, it
lives behind the same view switcher — never as a landing surface, never as a
global filter overlay, never as a "what does my vault look like" decoration.

---

## 07 · Metadata filter UX

Filters are **deterministic, observable, and explicit**. Each active filter is
a chip with `key:value`; clicking the `×` removes it. No ranking — order is
sort-by-path or sort-by-updated, both stable. If a future slice introduces
ranking, every signal must be surfaced on the row.

**Filter chip dock — selected state persists across views where compatible:**
`FILTERS · zone: active × · review_state: needs_review × · kind: human_note × · trust: suggest × · origin: derived × · health: missing_fields × · + source_ref + receipt + created + updated · clear all`.

### Filter dimensions and behavior

| Dimension | Slice | Behavior | Notes |
|---|---|---|---|
| kind | #1254 | Multi-select. Default: all kinds. | `human_note · companion_note · attachment · system_surface` |
| zone | #1254 | Multi-select. Default: `active + semi_active`. | Cognitive distance overlay; not folder, not maturity. |
| review_state | #1254 | Multi-select. Default: all except `archived`. | `inbox · needs_review · reviewed · archived` |
| trust | #1254 | Multi-select. Pairs with origin. | `assert · suggest · apply` (per TRUST_SEMANTICS_CONTRACT) |
| origin | #1254 | Multi-select. | `manual · imported · generated · derived · system` |
| source_ref | #1254 | Boolean (has/has not) + path prefix. | Surfaces source-anchored vs unanchored material. |
| health | #1254 | Multi-select. Default: all. | `valid · missing_fields · broken_links · stale · trust_conflict · blocked_write` |
| receipt | defer (#1257) | Boolean (has receipts / no receipts) + status. | Use for agent activity view; later for "what did the system touch". |
| created / updated | defer | Range; today / 7d / 30d / custom. | Pairs with timeline view. |

### What is forbidden

- **No opaque ranking.** If a future slice adds semantic ranking, the
  contributing signals (recency, similarity, agent score) must show on the row.
  A position is not a fact; the reasons for the position are.
- **No "smart" filters that mean different things in different views.** A
  filter chip means exactly one thing; it carries cleanly across views or it
  doesn't carry at all.
- **No filter that triggers writes.** Adding/removing a chip is `ui-only`.

---

## 08 · Artifact list / card design

Each row answers
`title · path · kind · zone · review_state · trust · health · provenance · receipt/action indicator`.
Title is the orienting line; everything else is mono-typed metadata. The row
is dense by intent — this user reads many at once.

**Row variants (same template, different state, row · selectable):**

- *human · reviewed · healthy:* `Yggdrasil capability contract — vault browser` · `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md · uuid b912…04ee` · `active · reviewed · human_note · trust: assert · updated 2026-05-24`.
- *derived · needs_review · missing fields:* `Q2 architecture review · synthesis` · `Synthesize/2026-05-19-q2-architecture.md · uuid 4c8f…9a21` · `active · needs_review · origin: derived · trust: suggest · missing: source_ref`.
- *inbox · unparseable frontmatter:* `2026-05-22 meeting (untitled)` · `Inbox/2026-05-22-meeting.md · uuid unresolved` · `semi_active · inbox · human_note · health: invalid_frontmatter · created 2026-05-22`.
- *agent activity · pending proposals:* `Notes/2026-04-22 meeting` · `Notes/2026-04-22-meeting.md · uuid e72a…40c1` · `semi_active · reviewed · 3 proposals · trust: assert · last receipt 2d ago`.
- *imported · low trust · stale:* `Annual-plan-2024 [import]` · `Imports/2024/annual-plan-2024.md · uuid a4f1…1c08` · `peripheral · archived · origin: imported · trust: suggest · health: stale`.
- *system surface · companion:* `Companion · q2-architecture` · `.system/companion/4c8f-9a21.md · companion_of 4c8f…9a21` · `semi_active · companion · companion_note · origin: system · indexed 2d ago`.

### Row rules

- **Title** in UI sans, 13.5px medium. Single line, ellipsis if it overflows.
  This is the orienting word.
- **Path + uuid** in mono, 10.5px dim. One line, ellipsis. `uuid` is shortened
  to `first4…last4`; full uuid available in inspector.
- **Metadata pills wrap onto a second row.** Order is stable:
  `zone → review_state → kind → origin → trust → health → activity indicator`.
  Never reorder by row.
- **Health is the only pill that turns red.** Destructive tone is reserved for
  `invalid_frontmatter` and `broken_write_state`. Amber is for `missing_fields`
  / `stale`.
- **Selection** is a 2px inset accent on the left edge, plus a slight
  background lift. No glow, no animation.

---

## 09 · Artifact inspector

The inspector is the right-rail surface where the user answers the deeper
orientation questions — provenance, health, links, activity, what the system
has done, what is safe to do. Eight tabs, one open by default (Preview). Each
tab is independently degradable.

| Tab | Slice | Contents |
|---|---|---|
| Preview | mlp | Rendered body (frontmatter stripped). Read-only. Opens into workspace via the Actions tab. |
| Metadata | #1253 | Normalized read-model: `uuid, kind, zone, review_state, trust, origin, source_ref, created, updated`, plus any policy-selected state fields. Each field shows source (`frontmatter / system / inferred`). |
| Health | #1253 | `frontmatter_valid · missing_required_fields · broken_links · stale_summary · stale_index · unreviewed_generated_content · trust_conflict · blocked_write_state`. Per signal: what, why, next step. |
| Provenance | #1253 | `origin · identity_source · identity_state · source_ref chain · companion linkage · imported-from / derived-from path`. |
| Links | defer | Typed relations: `links_to · cites · derives_from · companion_of · belongs_to_project · supersedes · duplicates · contradicts · mentions`. Inferred relations marked as such; never equal to human-confirmed. |
| Activity | #1257 | Time-ordered: `created, edited, reviewed, indexed, agent_proposed, agent_blocked, archived, resurfaced`. Each entry: actor, timestamp, `trace_id` when present. |
| Receipts | #1257 | Governed action records on this artifact. `receipt_id · action_id · trace_id · requested_by · approved_by · status · timestamp`. |
| Actions | #1256 | Server-declared VaultActions. Each labeled with its mode. Blocked actions render with reason; agent proposals render evidence-disclosed; governance writes require confirmation. |

**Per-tab sample bodies:**

- *Metadata:* `uuid 4c8f-9a21-…-2d11 · kind human_note · zone active · review_state needs_review · trust suggest · origin derived · source_ref — missing — · created 2026-05-19T09:14:02Z · updated 2026-05-23T18:22:41Z`. Each field carries a source attribution (`frontmatter / system / inferred`) shown on focus.
- *Provenance:* `origin: derived · identity_src: frontmatter.uuid · identity_state: resolved · derived_from: Notes/2026-04-22.md, Notes/2026-05-04.md · companion_of: — none —`. Note: `source_ref missing. This artifact derives from two notes but does not declare a canonical source. Open the Actions tab to set source_ref via governance write.`
- *Activity:* `2d ago 05-22 14:08 — indexer indexed body, 4 new spans · trace 9ef0…1f49`; `2d ago 05-22 14:08 — panel agent proposed metadata fix · 3 proposals · trace 9ef0…1f49 · pending`; `5d ago 05-19 09:14 — user created from synthesis session · session log Synthesize/2026-05-19.md`.
- *Receipts:* `receipt · ok · bounded_system_write — Indexed by ingest pipeline · 4 spans added · receipt 8c12…ab02 · trace 9ef0…1f49 · requested by indexer · 2d ago`; `receipt · blocked · governance_write — Promote to canon (request) · blocked: trust=suggest · receipt 4d99…02a1 · 3h ago`. Footer: `2 receipts · receipt source: available`.

### Inspector rules

- **One artifact per inspector instance.** Multi-select reduces the inspector
  to a count + bulk-action surface (future). MLP does not multi-select.
- **Tabs do not auto-switch.** Selecting another artifact keeps the user on
  the current tab. If that tab is unavailable for the new artifact, fall back
  to Preview, never silently to a different data tab.
- **Receipt source unavailability is not "no receipts."** Tab badge
  differentiates "0 receipts" from "receipt source unavailable" (destructive
  tone, explicit reason).
- **Actions tab is never empty.** At minimum it shows `read · Open in
  workspace` + `Copy path`. If the rest are blocked, they render with reasons.

---

## 10 · Provenance, trust, and review posture

Three orthogonal axes, three distinct visual languages. **Origin** describes
where it came from, **review state** describes where it is in human attention,
**trust** describes how much weight it carries. They are not collapsed.

### Origin · provenance

| Value | Pill | What it means |
|---|---|---|
| manual | `origin: manual` | Human-authored in the vault. The standard. |
| imported | `origin: imported` | Brought in from an external source. Carries source attribution; never silently becomes manual. |
| generated | `origin: generated` | Produced by an agent. Unreviewed generated content is amber until a human reviews. |
| derived | `origin: derived` | Synthesized from one or more vault artifacts. Provenance tab lists the source chain. |
| system | `origin: system` | System-written (e.g. companion notes). Bounded and inspectable. |

### Review state

| Value | Pill | What it means |
|---|---|---|
| inbox | `inbox` | Captured, not yet clarified. |
| needs_review | `needs_review` | Awaiting human review. This is the only `review_state` that uses amber. |
| reviewed | `reviewed` | Human-reviewed. Confirmed posture. |
| archived | `archived` | Set aside; preserved but de-emphasized. |

### Trust

| Value | Pill | What it means |
|---|---|---|
| assert | `trust: assert` | Confirmed claim. Standard for reviewed human-authored material. |
| suggest | `trust: suggest` | Suggestion; not asserted. Common for generated and derived material before review. |
| apply | `trust: apply` | Operational instruction; intended to be acted on under policy. |
| unknown | `trust: unknown` | Trust tier cannot be determined from the available metadata. Not the same as no trust. |

**Orthogonality.** A row can be `reviewed + suggest` (human-reviewed but still
framed as suggestion), or `needs_review + assert` (asserted by author, not yet
reviewed by a second pair of eyes), or `archived + apply` (historical
operational instruction). The three pills must stay distinct so these
combinations remain legible.

---

## 11 · VaultAction display model

Six modes. Six visual treatments. Each action arriving in the inspector carries
a server-declared mode; the browser never reclassifies. The user must
understand, before clicking, what kind of action they are about to take.

| Mode | Pill | What it does | Confirmation / receipt |
|---|---|---|---|
| read_only | `read` | No state change anywhere. Open, peek, copy path, view source. | No confirmation. No receipt. |
| ui_only | `ui-only` | Local Companion UI state only. Toggle filter, expand row, change view. | No confirmation. No receipt. |
| bounded_system_write | `bounded` | Governed system-side state change. Mark indexed, queue for review, refresh embeddings. | Single-click. Always produces a receipt in the rail. |
| governance_write | `gov` | Change crossing an authority boundary. Set review_state, change trust, promote relation. | Requires explicit confirmation. Routed through governed execution. Receipt mandatory. |
| agent_proposal | `proposal` | Surfaces an agent suggestion. Evidence disclosed at confirmation time. Never auto-applied. | User confirms / corrects / rejects. Confirmed proposal enters governed execution path. |
| blocked | `blocked` | Currently unavailable. Always carries a reason. WriteGuard, capability, policy, same-turn, or expired. | Cannot be clicked. Reason links to the docs/runtime explanation, not to a workaround. |

### Visual rules

- **Mode pill is leading-edge.** The pill appears on the left of every action
  row. The user reads mode → label → reason in that order.
- **Bounded vs governance are different colors.** Vault green vs amber. Same
  shape would collapse the distinction; same color would too.
- **Agent proposals are always blue, never green.** Even when "almost
  confirmed." Confirmed proposals become receipts, not green pills.
- **Blocked is destructive-tone only when an attempt was refused.** When the
  action is simply not available for this artifact, render `ui-only`-style
  "unavailable" with a neutral reason, not destructive.
- **No mode pill is ever inferred locally.** If the runtime hasn't declared a
  mode, the action does not render.

**Hard rule.** The browser never collapses `bounded_system_write` and
`governance_write` into one click. The addendum's §B distinction
(writeguard-blocked vs same-turn-blocked) extends here: the recovery path
differs by mode, and the visual treatment must let the user see that before
they act.

---

## 12 · Receipts and review posture

Receipts are **read-only records of governed action**. They are surfaced; they
are not authored by the browser. The receipt card and the proposal card share
template space but live in different rail slots — proposals before, receipts
after.

### Receipt state machine

| State | Pill | Meaning | What's visible |
|---|---|---|---|
| no receipts | `0 receipts` | No governed action has been recorded against this artifact. | Empty receipts tab with neutral reason. |
| source unavailable | `source down` | Receipt source is unreachable. Not the same as "0 receipts." | Destructive-tone strip with reason + retry link. |
| queued | `queued` | Action submitted, not yet executed. | Receipt placeholder with `action_id + trace_id`. |
| applied / ok | `ok` | Action executed successfully. | Receipt card with `receipt_id, trace_id, outcome, timestamp`. |
| blocked | `blocked` | Action blocked at execution (WriteGuard, policy, capability, same-turn). | Destructive-tone receipt with named gate + safe next step. |
| rejected | `rejected` | Proposal rejected by the user. | Neutral-tone receipt; logged for trace, not for action. |
| failed | `failed` | Execution error. | Destructive-tone with error reason + `trace_id` for support. |

### Identifier visibility

- **`trace_id` visible whenever a receipt exists.** Mono, shortened to
  `first4…last4`, full value on hover/focus.
- **`receipt_id` visible on every recorded receipt.** Same shortening rule.
- **`action_id` visible when the action is server-declared** (e.g. queued
  state); useful for correlating across receipts.
- **Identifiers never become primary UI.** They sit in the receipt's metadata
  line, mono, dim. Title and outcome are the reading order.

**Receipts in the rail vs. in the inspector.** A receipt produced by the
user's action in this session renders in the rail (persistent, until dismissed
or navigation). The Receipts tab of the inspector renders the full historical
list for the artifact. The two surfaces are consistent — the rail card is one
entry of the tab — but the rail is the live trail of "what I just did," the
tab is "what has ever happened here."

---

## 13 · Empty, error, degraded, blocked states

Every state in this section must be visually distinct from "everything is
fine." The contract is explicit: silent degradation is a contract violation.

**Sampled degraded states:**

- *vault identity unavailable:* `No active vault.` · `Companion UI could not resolve a vault identity. The browser is read-only until identity recovers.` · actions: `retry · open settings`.
- *no matches:* `No artifacts match these filters.` · `247 artifacts in vault. Try removing trust: suggest or health: missing_fields.` · actions: `clear filters · save view`.
- *read model degraded:* `Metadata read model unavailable.` · `Falling back to Files view. Path and title still work; kind, zone, trust, review_state are not shown.` · actions: `retry · stay in files view`.
- *writeguard blocked:* `Writes are currently blocked.` · `All bounded and governance actions render disabled with their reason. Browsing remains active.` · actions: `inspect policy · retry when released`.
- *relation index unavailable:* `Links tab degraded for this artifact.` · `Other tabs are unaffected. The Links tab shows an explicit empty reason rather than an empty list.` · actions: `retry · continue`.
- *receipt source unavailable:* `Receipts tab degraded.` · `Receipts are not shown rather than rendered as empty. The browser does not fabricate receipts.` · actions: `retry · continue`.

### State semantics

| State | What renders | What must not happen |
|---|---|---|
| vault identity unavailable | Safety strip turns destructive-tone. Result list replaced with identity-recovery card. Inspector hidden. | Empty list (would imply "no notes"). |
| artifact metadata invalid | Row still rendered. Health pill is destructive: `invalid_frontmatter`. Inspector Metadata tab shows the parse failure. | Hide the row. Hiding launders the failure. |
| frontmatter missing/invalid | Same as above. Health: `invalid_frontmatter` or `missing_required_fields`. Origin and uuid show as `unresolved`. | Silent default values. |
| WriteGuard blocked / safe_mode / degraded / unhealthy | Safety strip carries the posture. Affected actions render blocked with the gate name. | Actions rendered enabled. Toast notification. |
| receipt source unavailable | Receipts tab badge: destructive-tone `source down`. Rail receipts hidden. | Empty list. Fabricated receipts. |
| relation index unavailable | Links tab badge: `degraded`. Other tabs unaffected. | Empty links list (would imply "no links"). |
| no matches | List body replaced with neutral empty state. Filter chips remain visible so the user can clear them. | Same treatment as "no notes" or "identity unavailable." |
| API error | Safety strip turns destructive-tone. Last successful result remains visible with a `stale` badge. Retry action surfaced. | Blank screen. Loss of last known state. |

---

## 14 · Responsive behavior

Three layouts. Desktop is primary (single user, senior architect, Mac mini /
large laptop). iPad/half-window is a real secondary. Mobile is for read-only
reorientation, never for governance action.

**Layout breakpoints — desktop / laptop-narrow / mobile-readonly:**

- *desktop · ≥1200px · three-column:* `online safety/identity | filters | list | inspector`.
- *laptop-narrow · 900–1199px · collapsible filter:* `online safety/identity | filters (icon-rail) | list | inspector`.
- *tablet portrait · 700–899px · list + inspector sheet:* `online safety strip | view switch · query · filters drawer | artifact list (fluid) | inspector slides up as half-sheet on selection`.
- *mobile · ≤699px · read-only reorientation:* `online | query · view (artifacts / review / timeline) | artifact list · row→sheet | governance actions hidden — read-only on mobile`.

### Responsive rules

- **≥1200px:** three columns. Filters expanded by default.
- **900–1199px:** three columns, filters collapsed to a 44px icon rail. Chips
  still visible above the list.
- **700–899px (tablet portrait):** filters move into a drawer behind the view
  switcher. Inspector opens as a half-sheet from the bottom on selection.
- **≤699px (mobile):** single column. Inspector is a full-sheet. **Governance
  writes are hidden;** only `read_only`, `ui_only`, and `bounded_system_write`
  are exposed. The user can scan and orient but cannot promote, set review
  state, or change trust from mobile.
- **Two snap points only on the bottom sheet:** peek (header + 1 row of
  context) and half (header + all tabs). No full snap — the addendum's §A
  already rules this out.

---

## 15 · Test IDs / data attributes

Stable selectors for contract tests. Names are namespaced under
`vault-browser-`. State is exposed via `data-*` attributes, not via visible
text — this is the rule that closes the C4 vocabulary leak from the critique.

| Selector | `data-*` state | Asserts |
|---|---|---|
| `[data-testid="vault-browser-root"]` | `data-posture, data-channel` | Browser mounted; current posture and channel readable from a single root. |
| `[data-testid="vault-browser-safety"]` | `data-posture ∈ {online, degraded, blocked, unavailable}` | Safety posture is server-declared and visible. Contract test for §13. |
| `[data-testid="vault-browser-identity"]` | `data-identity-available, data-vault, data-channel` | Identity unavailable distinguishes from empty. Contract test for §13. |
| `[data-testid="vault-browser-view-switch"]` | `data-active-view` | Active named view. One of the eight defined in §6. |
| `[data-testid="vault-browser-query"]` | `data-query` | Active text/path/title query. |
| `[data-testid="vault-browser-filter-chip"]` | `data-key, data-value, data-active` | Active filters; addable + removable. Read-model contract for §7. |
| `[data-testid="vault-browser-row"]` | `data-uuid, data-kind, data-zone, data-review-state, data-trust, data-origin, data-health, data-selected` | One row per artifact. Every metadata axis exposed for assertion. |
| `[data-testid="vault-browser-row-action-indicator"]` | `data-mode, data-proposal-count` | Action indicator (proposals pending, blocked, etc.). |
| `[data-testid="vault-browser-inspector"]` | `data-artifact-uuid, data-open-tab` | Inspector mounted, current artifact and tab. |
| `[data-testid="vault-browser-inspector-tab"]` | `data-tab, data-available` | One per tab. Available vs degraded. |
| `[data-testid="vault-browser-action"]` | `data-mode, data-blocked-reason` | Action mode is server-declared; UI must not invent. |
| `[data-testid="vault-browser-receipt"]` | `data-receipt-id, data-trace-id, data-status` | Receipt entries. |
| `[data-testid="vault-browser-receipt-source"]` | `data-source-available` | Receipt source available vs down. Contract test for §12. |
| `[data-testid="vault-browser-empty"]` | `data-reason ∈ {no-matches, no-notes, identity-unavailable, api-error, read-model-degraded}` | Empty reason discriminated. Contract test for §13. |
| `[data-testid="vault-browser-degraded"]` | `data-scope, data-reason` | Per-scope degraded state (read model, relations, receipts, identity). |

**Why state lives in `data-*` not text.** Contract tests (current shipped path:
`tests/api/test_companion_vault_browser_api.py`, future UI side) can assert
state without depending on user-facing copy. The copy can be rewritten by the
team without breaking the test; the state can be reshaped by the runtime
without breaking the user-facing copy. The two move independently.

---

## 16 · MLP vs future capability

Four columns: **shipped MLP v0**, **near-term #1253–#1257**, **later**, and
**explicit non-goals**. The cut column is as load-bearing as the others — it
is the list of things the browser does not become.

| Capability | MLP v0 | Near-term | Later | Non-goal |
|---|---|---|---|---|
| Read-only Markdown enumeration | shipped | — | — | — |
| Active vault/channel identity | shipped | — | — | — |
| Deterministic text/path/title query | shipped | — | — | — |
| Hidden/system folder exclusion | shipped | — | — | — |
| Empty / error / identity-unavailable states | shipped | — | — | — |
| Normalized artifact metadata read model | — | #1253 | — | — |
| Metadata filters and badges (kind/zone/state/trust/origin/health) | — | #1254 | — | — |
| Artifact inspector panel | — | #1255 | — | — |
| VaultAction display model | — | #1256 | — | — |
| Agent receipts and review posture in inspector | — | #1257 | — | — |
| Review queue view | — | post-#1255 | — | — |
| Timeline / activity view | — | post-#1257 | — | — |
| Agent activity / receipt explorer | — | post-#1257 | — | — |
| Saved views | — | — | later | — |
| Source / evidence view | — | — | later | — |
| Relation / typed links surface | — | — | later | — |
| Resurfacing candidates view (read-only) | — | — | later | — |
| Duplicate / contradiction detection surfaces | — | — | later | — |
| Long-term project resurrection workflow | — | — | later | — |
| Bulk operations with guardrails | — | — | later | — |
| Graph as optional view | — | — | later | — |
| Graph as primary navigation | — | — | — | forbidden |
| Opaque semantic ranking | — | — | — | forbidden |
| Browser-initiated AI mutation of note body | — | — | — | forbidden |
| Local action reclassification | — | — | — | forbidden |
| Inbox / cross-note notification metaphor | — | — | — | forbidden |
| DB-first browser (store as authority) | — | — | — | forbidden |
| Auto-apply of agent proposals | — | — | — | forbidden |
| Toast notifications | — | — | — | forbidden |

---

## 17 · Future feature map

These are not roadmap items. They are capability slots the browser already has
space for — when they ship, they slot into existing views, tabs, or rail cards
without needing a new layer of chrome.

| Future capability | Lives in | Design note |
|---|---|---|
| Saved views | Filter rail header dropdown | A named filter+view tuple. No "smart" saved views; deterministic only. |
| Timeline browsing | Timeline view | Same row template, time-grouped. Filter chips still apply. |
| Graph browsing | Graph view (optional) | Never the landing. The rows-and-inspector view remains canonical; graph is a relation-visualization alternative. |
| Semantic neighborhoods | Inspector · Links tab | "Semantically near" group rendered with explicit similarity signal. Not an autonomous ranking. |
| Review campaigns | Review queue view + filter chip `campaign:` | Long-running review sweeps as a saved view with a campaign tag. |
| Resurfacing candidates | Resurfacing view (read-only first) | No urgency semantics. Same row template, "why now" disclosure. |
| Duplicate detection | Inspector · Links tab (`duplicates`) + filter chip `has_duplicates` | Proposed merges enter the proposal/receipt loop. Never auto-applied. |
| Contradiction candidates | Inspector · Links tab (`contradicts`) + agent activity view | Surface contradictions as proposals with two-side evidence. |
| Source / evidence browser | Source view | Pivot the row template onto `source_ref` instead of artifact path. |
| Long-term project resurrection | Resurfacing view + Project filter | Resurfaces dormant projects with a bounded context bundle. |
| Agent activity explorer | Agent activity view | Receipts + proposals stream, filterable by agent / action / outcome / time. |
| Bulk operations with guardrails | Inspector with multi-select state | Every bulk op is itself a server-declared VaultAction with a mode. Bounded and governance bulk are different shapes. |

---

## 18 · Design risks and tradeoffs

Where this design can go wrong. Each item is a failure pattern the team should
treat as a smoke alarm.

| Risk | How it shows up | Counter-measure |
|---|---|---|
| Too much metadata | Every row carries 8+ pills; the user scans pills, not titles. The orientation cost increases. | Row caps at 5 pills. The 6th wraps to the inspector. Pills must earn their place by being filterable. |
| Too much graph | Graph view drifts into landing surface; users measure their vault by edges; relations become identity. | Graph remains an optional view. Hard-coded: not the default, no "graph as decoration." Contract §8 enforced in code. |
| Hidden authority | The browser starts emitting "harmless" writes when navigating. Receipts accumulate without user-initiated actions. | Every receipt must trace to a server-declared VaultAction that the user invoked. Navigation traces are not receipts. |
| Action ambiguity | Bounded and governance writes look alike; the user clicks one expecting the other. | Different colors, different verbs, mandatory confirmation on governance. Contract test on the visual treatment matrix. |
| False trust | Generated content with no review reads like asserted truth in the list. The amber signal is too subtle. | `origin: generated` + `trust: suggest` + `unreviewed_generated_content` all surface on the row, not just inspector. |
| UI clutter | Every degraded state gets its own card; the user gets 4 banners before seeing the list. | Stack rule: only one degraded card per scope. The strip carries the headline; tabs carry per-scope detail. |
| Over-automation | Saved views become "smart" inboxes; resurfacing acquires urgency semantics; agent activity starts to "summarize." | Resurfacing read-only first. Saved views deterministic. Activity = chronology + actor; no narrative layer. |
| Weak degraded states | Receipts down looks like "no receipts." Relations down looks like "no relations." The user can't tell the difference. | Mandatory test: every degraded scope has a destructive-tone explicit reason in `data-reason`. |
| Inspector becomes its own app | Tabs proliferate (Source, Embeddings, Audit, Notes-on-this-note). The user can't find Preview. | Eight tabs is the cap. New surfaces become rows in existing tabs, not new tabs. |
| The list becomes the Companion UI | Workspace shell is forgotten; users start editing inside inspector preview; provenance breaks. | Preview is read-only. Editing always opens workspace (Canvas / Panel surfaces). The browser is navigation, not authoring. |

---

## 19 · Recommended implementation slices after #1253–#1257

Issue-sized, testable, ordered. Each slice extends the projection contract;
none weakens the MLP v0 boundary or the non-goals.

| # | Slice | Depends on | What ships | Verdict |
|---|---|---|---|---|
| A | Workspace shell parity for browser-opened notes | — | Resolves C1–C5 from §02 critique. Frontmatter parsed at workspace boundary; one safety strip; disabled affordances removed (not just disabled); vocabulary leaks replaced with copy-table copy; identity strip pinned. **Blocks all later slices.** | must |
| B | Vault Browser shell + Files view migration | A | Three-column shell. Files view reuses MLP v0 enumeration. Safety strip, view switcher, query, filter rail skeleton, inspector skeleton (Preview tab only). No metadata yet. | must |
| C | Artifacts view backed by read model | B + #1253 | Artifacts view renders the row template from §08. Metadata pills (kind, zone, review_state, trust, origin, health) wired from #1253 read model. Filter chips active for the five primary dimensions. | must |
| D | Inspector tabs: Metadata + Health + Provenance | C + #1255 | Three data tabs from §09. Each renders the per-tab samples shown in the mockup. Field source attribution (`frontmatter / system / inferred`) visible on focus. | must |
| E | Action mode rendering on the inspector | D + #1256 | Actions tab renders server-declared VaultActions with the six-mode visual treatment from §11. Blocked reasons render explicit. No local reclassification. | must |
| F | Receipt strip + Receipts tab | E + #1257 | Rail receipt card for the current session. Receipts inspector tab with the full historical list. Source-down state distinct from empty. | must |
| G | Review queue view | C + #1254 | Named view scoped to `review_state ∈ {inbox, needs_review}`. Default sort: age ascending then trust. Filter chips persist. | near |
| H | Activity tab + Timeline view | F | Activity tab renders the per-artifact timeline from §09. Timeline view renders the cross-vault chronology projection. Both read from #1257 read model. | near |
| I | Agent activity view | F + H | Receipts + proposals stream. Filterable by agent, action, outcome, time. The "what has the system done" landing for an audit posture. | near |
| J | Degraded-state contract pass | B–F | Every degraded scope from §13 has a destructive-tone explicit reason and a `data-reason` assertion. Contract test sweep. | near |
| K | Responsive: tablet + laptop-narrow | F | Collapsible filter rail at 900–1199px. Inspector half-sheet at 700–899px. Governance writes still available on tablet. | defer |
| L | Responsive: mobile read-only | K | Single-column mobile shell. Governance writes hidden; only `read_only/ui_only/bounded_system_write` exposed. Read-only reorientation surface. | defer |
| M | Saved views (deterministic) | G + I | Named filter+view tuples. No "smart" saved views. Listed in the filter rail header. | later |
| N | Links tab + relations projection | D + relation index runtime | Links inspector tab. Typed relations from §09 table. Inferred vs human-confirmed kept visually distinct. | later |
| O | Resurfacing view (read-only) | I | Resurfacing candidates as a named view. Read-only first. "Why now" disclosure. No urgency semantics; no dismiss/snooze/pin until persistence ships. | later |
| P | Graph view (optional) | N | Graph as one named view. Hard-coded: not landing, not default, not decoration. Filter chips still apply. | later |

### What each slice produces

- **Issue-sized.** Each slice fits a single PR with focused tests.
- **Testable.** Each slice declares its `data-*` attribute additions and the
  contract tests that ship with it.
- **Composable.** Later slices only extend the visible projection; none of
  them require revisiting the MLP v0 invariants or the non-goal list in §16.
- **Reversible.** Each slice's surface is removable without breaking the layer
  below it. Removing Graph (P) leaves N intact; removing N leaves D intact;
  removing D leaves C intact; and so on down to MLP v0.

---

## 20 · Closing notes

The Vault Browser is the user's continuous instrument over the vault, used for
many years. It carries a steep design constraint: the load is on **not lying
about authority**, not on visual richness. The mockups in this doc are
intentionally sober. Every pill, every state, every tab earns its place by
answering one of the eight orientation questions or by enforcing one of the
action-class boundaries.

If a future slice tempts the team to add ranking without surfaced signals, an
inbox metaphor, a graph landing, or a one-click governance action — refer back
to `VAULT_BROWSER_CAPABILITY_CONTRACT.md §8` and the non-goal column of §16.
The browser stays narrow on purpose. Its narrowness is what lets it last.
