# Yggdrasil Design System

Version 2.2.1. Token sheet: `colors_and_type.css`, generated from the repo token source
`design-system/yggdrasil/` in `RasmusTho/agentic-pkm-mvp`. The repo sheet
`companion-ui/companion-app/colors_and_type.css` is the binding authority. This project's copy must
match it byte for byte. If this README and the sheet ever disagree, the sheet wins.

## What This Is

Yggdrasil is a local-first, vault-backed AI second brain for a single power user. It sits atop an
Obsidian-compatible markdown vault and adds an agentic assistance layer: capture, triage, retrieval,
synthesis, and bounded automation. All artifacts stay portable, inspectable, and Obsidian-readable.

The system is named after the Norse world-tree. Its modules carry Norse names that reflect their
roles (see the glossary). The design language inherits that vocabulary: rooted, long-lived,
expert-grade, unhurried.

## Sources

- **Codebase:** `RasmusTho/agentic-pkm-mvp`. Shipped surfaces are server-rendered HTML and CSS: the
  Companion workspace (`companion-ui/`), the BuilderOps Cockpit, Signboard, and the legacy dashboard
  (`app/web/static/`).
- **Token source:** `design-system/yggdrasil/` (DTCG JSON plus a deterministic generator). Never edit
  `colors_and_type.css` by hand.
- **Native clients:** Bifrost (`RasmusTho/bifrost`, SwiftUI) consumes the same tokens as generated
  Swift. It ships Dark only.
- **No Figma.**

## Products / Surfaces

| Surface | Description | Density |
|---------|-------------|---------|
| **Companion UI** | Workspace for Converse, Orient, Capture: the assisted-thinking shell | comfortable |
| **Builder System UIs** | BuilderOps Cockpit, Signboard, CKM overview, DevUI: operator dashboards | compact |
| **Bifrost** | Native iOS clients (Heimdal capture, Mimer knowledge) | native Dynamic Type |
| **Obsidian vault** | Primary human writing and reading surface | n/a |

Platforms: iPhone, iPad, Mac. Desktop is primary. Everything runs over a personal network
(Tailscale), not a cloud product.

## Module Glossary (Norse names)

| Name | Role |
|------|------|
| **Mimer** | Knowledge surface: vault, ingestion, indexing, vault-facing agent behavior |
| **Hugin** | Agent and reasoning layer |
| **Munin** | Planned media and raw-memory module |
| **Ratatosk** | Ingest and pipeline boundary (routing, normalization) |
| **Brokkr** | Planned execution and deliverable workshop |
| **Tyr** | Planned formal-records boundary (receipts, contracts) |
| **Heimdall** | Infrastructure and observability |

## User Profile

Single user: senior software architect. Daily Obsidian user. Thinks at system level. Not a
consumer. Fluent with markdown, agent tooling, and vault-native workflows. No onboarding flows, no
engagement mechanics.

---

## CONTENT FUNDAMENTALS

### Voice and Tone

- **Terse.** No filler. The user reads dense technical prose all day.
- **Declarative, not conversational.** Agent contributions read like a careful colleague. No
  exclamation points. No "Great question!"
- **Precise.** "Artifact", "surface", "vault", "receipt", "contract", "authority" keep their
  technical sense.
- **No emoji.** Never.
- **Sentence case** for all UI labels and headings. Proper nouns and module names keep capitals.
- **Imperative verbs for actions:** "Capture", "Synthesize", "Orient".
- **Provenance is surfaced, not hidden.** Agent contributions are labelled, suggestions are
  labelled as suggestions, and sources are cited.
- **No growth loops.** No streaks, no "keep going" prompts.

### Example Copy Patterns

| Context | Example |
|---------|---------|
| Empty state | "No open sessions." |
| Agent suggestion | "Suggested: restructure this section into three sub-claims." |
| Vault sync | "Vault unreachable." |
| Commit action | "Apply" / "Discard" |
| Error | "Session log could not be written. Runtime unreachable." |
| Provenance | "Source: Inbox/2026-04-22-meeting.md · indexed 2d ago" |

---

## VISUAL FOUNDATIONS

### Setup

Link the sheet, then choose theme and density on the root element. Components never branch on
theme or density: both are pure token swaps.

```html
<html data-theme="dark" data-density="comfortable" data-focus="v2">
  <link rel="stylesheet" href="colors_and_type.css">
```

| Attribute | Values | Default |
|-----------|--------|---------|
| `data-theme` | `dark`, `light` (Shell), `system` (Shell under `prefers-color-scheme: light`, else Dark) | missing means `dark` |
| `data-density` | `comfortable`, `compact` | missing means `comfortable` |
| `data-focus` | `v2` opts in to the 2px solid focus ring | missing keeps the v1 glow ring |

Yggdrasil Dark is the default for every surface. Shell is a per-user choice. Never make Shell
the default of a design unless the brief asks for it.

### Themes

**Yggdrasil Dark (default).** Cold, near-black blue backgrounds with a cool blue-white text scale.
Norse gold is the primary accent. Electric cyan is the signal colour. Vault green, agent blue,
amber, and red carry domain meaning. The only material is a faint cyan grid, available through
`.fx-grid`.

**Yggdrasil Light "Shell".** The suit against the city. People read and write on calm
porcelain sheets. The frame around them is a saturated neon city that the porcelain catches as rim
light.

- **City backdrop** (app frame): `var(--surface-page)`. A lit night: a near-black base with small
  neon sign glows and corner fields in four palette colours, glitch streaks, and scanlines. With
  `class="fx-city"` on `<html>` the palette cycles over 10 minutes (Neo-Tokyo, Aurora, Ice & Ember).
- **Porcelain sheet** (content): `var(--surface-panel)` and `var(--surface-main)`, frosted glass.
  A translucent white to `#e4e6eb` gradient (85 % coverage) with `backdrop-filter:
  var(--surface-panel-filter)`, so the city and its glitch streaks show through. Rim light is
  `var(--surface-panel-shadow)`: cyan from the left, red from the right.
- **Reading surface** (note body, editors): `var(--surface-reading)`. Calm glitch: denser porcelain
  with faint static scanlines and two hairline chroma streaks. It never animates.
- **Dark glass chrome** (top bar, anything directly on the city): `var(--material-glass)` with
  `var(--material-on-glass)` text.
- **Emblem:** the ᛉ rune inside a thin triangle. Wordmark in light, widely tracked capitals.
- **Motion (`.fx-city`):** a brief horizontal tear every 29 s and a city power dip every 53 s,
  never more than three flashes per second. Content never moves. Everything stops under
  `prefers-reduced-motion`.

Shell's material belongs to the theme. Dark surfaces must not borrow it.

### Colour roles

Use roles, never raw hex. Every role keeps its name in both themes.

- **Surfaces:** `--bg-base`, `--bg-surface`, `--bg-raised`, `--bg-overlay`, `--bg-modal`
- **Text:** `--fg-1` (primary), `--fg-2` (secondary), `--fg-inverse`
- **Disabled and decorative only:** `--fg-3`. It fails contrast in both themes. Never put readable
  text in `--fg-3`; use `--fg-2`.
- **Borders:** `--border`, `--border-strong`, `--border-focus`
- **Brand:** `--accent` (Norse gold), `--cyan` (signal)
- **Domain meaning:** `--vault` (vault-connected, committed), `--agent` (agent-contributed),
  `--amber` (staged, uncommitted), `--destructive`
- **Status aliases:** `--status-success`, `--status-warning`, `--status-danger`, `--status-info`
  alias vault, amber, destructive, and agent. Do not invent a fourth colour language.
- **Tints:** each brand and domain role has `-dim` and `-muted` variants. Use `-muted` as a
  background tint behind its role.

**Ink and mark.** Every brand and domain role has an ink tone for text (`--vault`) and a mark tone
for the square marker or edge beside it (`--vault-mark`). In Dark both are the same colour. In
Shell the ink is a deep readable tone and the mark is the neon. Neon is decorative only and never
text.

| Role | Dark | Shell ink | Shell mark |
|------|------|-----------|------------|
| accent | `#d4a843` | `#573e00` | `#e8b440` |
| cyan | `#00d4e8` | `#004a53` | `#00d4e8` |
| vault | `#39e87d` | `#094d29` | `#16c95e` |
| agent | `#4a9eff` | `#1a3999` | `#2f6bff` |
| amber | `#f09030` | `#6a3400` | `#ff8a1a` |
| destructive | `#ff3d3d` | `#841021` | `#ff1f4b` |

Surface tokens for layout: `--surface-page`, `--surface-panel`, `--surface-main`,
`--surface-panel-border`, `--surface-panel-shadow`, `--surface-panel-radius`,
`--surface-frame-gap`, `--surface-title-shadow`, `--surface-panel-filter` (apply as
`backdrop-filter` on panels), and `--surface-reading` (reading surfaces such as a note body).
Build app frames from these and the same markup renders Dark or Shell.

### Typography

- **Display serif, EB Garamond** (`--font-display`): wordmark, session titles, `h1`/`h2`. In Shell,
  large display headings become light, widely tracked capitals with `text-shadow:
  var(--surface-title-shadow)`. EB Garamond italic stays for secondary display lines.
- **UI sans, Space Grotesk** (`--font-ui`): all interface chrome, labels, body copy, `h3` to `h6`.
- **Monospace, JetBrains Mono** (`--font-mono`): code, frontmatter, vault paths, metadata,
  timestamps, status labels.

All three load from Google Fonts through the sheet's `@import`. Scale: `--text-xs` (11px) through
`--text-4xl` (60px). Body is `--text-base` (15px comfortable, 13px compact). Tracking tokens:
`--tracking-tight`, `--tracking-normal`, `--tracking-wide`, `--tracking-wider`.

### Density

| Token | Comfortable | Compact |
|-------|-------------|---------|
| `--text-base` | 15px | 13px |
| `--text-sm` | 13px | 12px |
| `--space-3` / `--space-4` / `--space-6` | 12 / 16 / 24px | 8 / 12 / 16px |
| `--control-height` | 36px | 28px |
| `--row-height` | 40px | 28px |

Size controls with `--control-height` and list rows with `--row-height`. Companion surfaces are
comfortable. Builder dashboards are compact.

### Spacing, radii, shadows, motion

- **Spacing:** `--space-1` to `--space-16` on a 4px base (4, 8, 12, 16, 20, 24, 32, 40, 48, 64).
- **Radii:** `--radius-sm` 2px (inputs, inline), `--radius-md` 4px (cards, panels), `--radius-lg`
  6px, `--radius-xl` 10px (modals, drawers), `--radius-full` for pills only.
- **Shadows:** `--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-float` (popovers, modals),
  `--shadow-inset` (pressed). Cards carry no shadow by default.
- **Motion:** `--duration-fast` 100ms, `--duration-base` 150ms, `--duration-slow` 250ms, easing
  `--ease`. Purposeful fades only. All durations are zero under `prefers-reduced-motion`.
- **Layers:** `--z-base` to `--z-toast`.

### Focus

New work opts in with `data-focus="v2"`: a 2px solid `--border-focus` outline, 2px offset, no glow.
The v1 global rule (1px cyan outline plus glow) stays for surfaces that have not migrated. Focus is
never hidden.

### Effects rule: glow is a state, not a style

Glow and grid are opt-in and mark state only: the active item, the live connection, the agent
currently working. Use the `.fx-*` classes:

| Class | Use |
|-------|-----|
| `.fx-glow-cyan` | the one active or live element |
| `.fx-glow-vault` | a vault connection that just confirmed |
| `.fx-glow-agent` | the agent currently working |
| `.fx-grid` | the theme backdrop on an app frame |
| `.fx-chroma` | Shell display headings (cyan/red split) |

Never glow resting content, whole panels, or body text. The v1 classes `.glow-*`, `.text-glow-*`,
`.grid-bg`, `.border-cyan`, and `.border-gold` still exist for unmigrated surfaces. Do not use them
in new designs.

### Component grammar

| Element | Dark | Shell |
|---------|------|-------|
| Status | Mono uppercase badge on the role's `-muted` tint with a `-dim` border | Small square marker in `--<role>-mark` beside an uppercase tracked mono label in the role ink. No pills. |
| Primary button | Outline in `--accent` or `--cyan` | Solid graphite (`--fg-1`) with `--fg-inverse` text and a `var(--material-chroma-split)` edge |
| Secondary button | 1px `--border-strong` outline | 1px graphite outline |
| Input | `--bg-raised` field, `--border-strong` border | Underline only. Focus is a cyan underline with a red offset. |
| Agent voice | `--agent-muted` panel with a 2px `--agent` left edge | Blue/violet scanline band with an agent-blue edge |
| Staged | `--amber-muted` bar with an `--amber-dim` top border | Amber edge with a warm fade |
| Selection | `--accent` border | Red and cyan double edge |
| Cards and panels | 1px `--border`, `--radius-md`, no shadow | Porcelain sheet, `--surface-panel-shadow` rim light |

Hover lightens the background one step (`--bg-surface` to `--bg-raised`). Press darkens slightly
and adds `--shadow-inset`. Destructive hover uses `--destructive-muted`.

### Imagery, blur, transparency

- No photography, no stock imagery, no grain. The vault is the content.
- Blur (`backdrop-filter`) only for floating overlays, Shell's dark glass chrome, and Shell's
  frosted sheets through `--surface-panel-filter`.
- Transparency layers surfaces. It is never decoration.

---

## ICONOGRAPHY

**Icon system: Lucide.** Stroke 1.5, `currentColor`, 16px for chrome, 20px for prominent actions.
Never filled icons, never emoji. Pair icons with a text label unless the toolbar convention is
established.

| Concept | Lucide name |
|---------|-------------|
| Capture | `circle-dot` |
| Orient | `compass` |
| Converse | `message-square` |
| Synthesize | `layers` |
| Resurface | `refresh-cw` |
| Triage | `filter` |
| Vault | `archive` |
| Agent | `cpu` |
| Note | `file-text` |
| Session | `scroll` |
| Source | `link` |
| Receipt | `receipt` |
| Settings | `settings` |
| Search | `search` |

---

## Components and limits

This system exports tokens and preview cards, not a component library. Shipped Yggdrasil surfaces
are server-rendered HTML and CSS, so there is no React component source to export. Build every
component from the roles, surface tokens, and grammar above. The preview cards and
`ui_kits/companion-ui/` show the grammar in use. They are references, not importable components.

## File Index

| Path | Contents |
|------|----------|
| `README.md` | This file |
| `SKILL.md` | Agent skill entrypoint |
| `colors_and_type.css` | Generated token sheet: both themes, density, opt-in focus and effects |
| `preview/` | Preview cards for the Design System tab. `shell-*` cards show the Shell theme; `density.html` and `effects-focus.html` apply to both. |
| `ui_kits/companion-ui/` | Companion UI kit (Dark) |
| `ui_kits/builderops-cockpit/` | Builder design references and existing surfaces |
