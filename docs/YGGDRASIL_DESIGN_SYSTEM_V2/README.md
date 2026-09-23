State: Target-state capability specification, filed as parent #5626 with children #5627–#5631 (YDS-01 ready). Nothing in this document is shipped. Current binding
token truth remains `companion-ui/companion-app/colors_and_type.css` under `docs/DESIGN_PRINCIPLES.md
:: 11. Shared Visual Language` until a slice below is delivered and its owner doc is promoted.
Doc role: Capability specification directory README for the Yggdrasil Design System v2 refinement.
Owner: Yggdrasil visual language (DP-11)
Temporal class: target-state
Review cadence: event-driven (per delivered slice)
Last reviewed: 2026-09-22
Last verified against: origin/main 22a8928e8, `companion-ui/companion-app/colors_and_type.css`,
`app/web/static/colors_and_type.css`, `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Yggdrasil
design-system gate`, `.codex/skills/yggdrasil-design-handoff/SKILL.md`,
`docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Design-system conflicts`,
`tests/api/test_cockpit_api.py`, `RasmusTho/bifrost:Yggdrasil/Yggdrasil/DesignSystem/Theme.swift`

# Yggdrasil Design System v2

Refine the Yggdrasil Design System from a single dark token sheet, copied by hand into each
consumer, into one versioned, layered, platform-neutral system that every Yggdrasil surface draws
from: the Companion product UI, the Builder System UIs, and the Bifrost native clients.

Owner decisions recorded 2026-09-22:

- **Themes:** *Yggdrasil Dark* (today's look) stays the default. *Yggdrasil Light "Shell"* is
  approved **for trial**. It is inspired by the Ghost in the Shell (2017) posters: porcelain work
  surfaces floating on a glitching neon city. Four earlier light directions were reviewed and
  rejected the same day because they felt generic, "90s", or "too My Little Pony": a plain cool
  light, a frost / Tron-grid / neon-signage trio, a prismatic rainbow-bridge look, and a muted porcelain Shell.
  The review page is kept at [`exploration/2026-09-22-shell-light-theme.html`](exploration/2026-09-22-shell-light-theme.html).
  Shell graduates from trial only after the owner uses it in the Companion (S3).
- **App feel:** one shared core (colour, type, meaning) with per-surface **density profiles**;
  glow and grid effects become opt-in and state-only.
- **Scope:** Companion UI, all Builder System UIs, and Bifrost (separate repo, same system).

## Why v2

Observed on `origin/main` 22a8928e8 and `RasmusTho/bifrost` `main`:

| Problem | Evidence |
|---|---|
| The live Claude Design system is marked **Legacy** | Owner report, 2026-09-22. The gate in `DESIGN_HANDOFF_GOVERNANCE.md` still resolves it by ID `f2b13410-af14-4875-8029-445352123f57`. |
| Live README contradicts the token sheet | `BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: DS-1` (background warmth, radii, focus ring, UI typeface, glow). |
| No exported components, only previews | `BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: DS-2`. |
| Token sheet is copied, not consumed | Byte-identical copies in `companion-ui/companion-app/`, `app/web/static/` (CI-enforced by `tests/api/test_cockpit_api.py`), and every `companion-ui/design_handoff/*/` package. |
| Surfaces drift off the palette | Some surfaces hardcode off-palette colours (for example `#fecaca`, `#f87171`, `#e5e7eb` in `signboard.css` and `index.html`) instead of Yggdrasil tokens. v2 brings them back to the system. |
| Surfaces bypass the tokens | Hex literals at time of writing: `serve_dev_page.py` 143 (with an inlined token subset), `settings_drawer.py` 27, `system_map_overlay.py` 24, `memory_review_drawer.py` 24, `receipts_history.py` 16, `app/web/static/signboard.css` 19, `devui_candidate/devui.css` 18, `app/web/static/index.html` 17. |
| Internal inconsistencies | Heading comment says "DM Sans" while `--font-ui` is Space Grotesk; JetBrains Mono loads from `fonts.bunny.net`, outside the Google Fonts host most sandboxes (including Claude artifacts) admit. |
| Glow is a default, not a signal | `.glow-*`, `.text-glow-*`, `.border-cyan`, and the `:focus-visible` glow ship as general utilities, while the converse handoff says glow is only for state. |
| Bifrost is outside the system | `YggTheme` uses iOS system colours (`systemBackground`, `accentColor`, `.orange`, `.green`), not Yggdrasil values. It cannot consume CSS. |

## Architecture

### One source, generated outputs

The canonical source becomes a platform-neutral token file in
[W3C Design Tokens (DTCG)](https://design-tokens.github.io/community-group/format/) JSON:

```
design-system/yggdrasil/
  tokens/primitives.json      # raw ramps, type scale, spacing, radius, motion
  tokens/semantic.json        # roles that reference primitives
  tokens/themes/dark.json     # role -> primitive bindings (Yggdrasil Dark, default)
  tokens/themes/shell.json    # role -> primitive bindings (Yggdrasil Light "Shell", trial)
  tokens/materials/*.json     # per-theme backdrop, glass, surface finish, light, motion
  tokens/density/comfortable.json
  tokens/density/compact.json
  VERSION                     # semver of the system
  build.py                    # deterministic generator (stdlib only)
```

The generator emits:

| Output | Consumer |
|---|---|
| `companion-ui/companion-app/colors_and_type.css` | Stays the binding path named by DP-11 and the handoff gate, so governance links survive. Becomes a generated artifact with a `generated-from` header and version. |
| `app/web/static/colors_and_type.css` | Builder UIs. Existing byte-parity test keeps working. |
| `design-system/yggdrasil/dist/YggdrasilTokens.swift` | Bifrost, vendored by version (see Bifrost below). |
| `design-system/yggdrasil/dist/tokens.json` (flattened) | Claude Design upload and any future consumer. |

CI proves every generated file is fresh (regenerate, then diff). Hand edits to outputs fail CI.

### Layers

1. **Primitives:** colour ramps, type scale, spacing, radius, motion, z-index. Never referenced
   directly by surfaces.
2. **Semantic roles:** what surfaces use.
   - Surface and text: `bg-base`, `bg-surface`, `bg-raised`, `bg-overlay`, `bg-modal`, `fg-1..3`,
     `fg-inverse`, `border`, `border-strong`, `border-focus`.
   - Brand accents: `accent` (Norse gold), `cyan` (signal).
   - Domain meaning: `vault` (vault-connected / committed), `agent` (agent-contributed),
     `amber` (staged / uncommitted), `destructive`. Each has `-dim` and `-muted`.
   - Status: `success`, `warning`, `danger`, `info`, which alias the domain roles, so builder
     dashboards do not invent a fourth colour language.
3. **Theme:** binds every role for Dark and for Shell.
4. **Density:** comfortable or compact.
5. **Material:** what gives a theme its identity beyond colour: backdrop, glass, surface
   finish, rim light, chromatic split, and ambient motion. Dark's material is today's faint cyan
   grid. Shell's is described below.
6. **Effects:** Dark's glow utilities, grid background, and neon borders. Opt-in and state-only.

**Compatibility:** every token name in today's sheet (`--bg-base`, `--fg-1`, `--accent`,
`--vault-glow`, `--space-4`, `--text-base`, and the rest) keeps its name and Dark value in v2.
Existing consumers change nothing to stay correct. Renames, if any, are a later major version.

### Theme and density selection (web)

- Theme: `data-theme="dark" | "light" | "system"` on the root element. This is the whole
  grammar. A missing attribute means `dark`. `system` resolves to Shell under
  `prefers-color-scheme: light` and to Dark otherwise. Any other value is invalid and falls back
  to `dark`.
  During the trial, Light is a per-user choice in the Companion and is not a surface default.
- Density: `data-density="comfortable" | "compact"`, with comfortable as the default.
- Both are pure token and material swaps. No component CSS may branch on theme or density.

### Yggdrasil Dark contrast

Contrast measured on `bg-base` `#070b12` (WCAG 2.x relative luminance): `fg-1` 15.81, `fg-2` 6.70,
`accent` 8.90, `cyan` 10.87, `vault` 12.21, `agent` 7.16, `amber` 8.20, `destructive` 5.62, all
at least 4.5:1. `fg-3` is 2.56, so v2 documents it as disabled/decorative only: it must never
carry readable content. S1 adds a CI contrast check over role/surface pairs for both themes.

A token-level check cannot prove how a token is used, and today readable text does use `fg-3`
(for example the "Vault online" status in `canvas_suggestion_flow.html` and a link in
`converse_layout.html`). `var(--fg-3)` appears in about 17 consumer files across Companion,
Cockpit, DevUI, and CKM. The rule therefore lands as a migration, not a declaration. S3 and S4
move readable `fg-3` uses to `fg-2` and add a usage-level check: every `var(--fg-3)` in a
consumer must sit on an allowlisted disabled, placeholder, or decorative selector.

### Yggdrasil Light "Shell" (trial)

The suit against the city. The surfaces people read and write on are calm porcelain. The frame
around them is a saturated neon city that the porcelain catches as rim light.

**Structure**

- **City backdrop** (the app frame, visible around panels): radial fields of red `#ff1f4b`,
  cyan `#00e5ff`, magenta `#ff2aa0`, and electric blue `#2850ff` over violet `#6a2bff` →
  `#1a0a2e`. On top sit vertical glitch streaks (1–2px lines in cyan, white, and red at
  irregular periods) and faint horizontal scanlines.
- **Porcelain sheet** (content surfaces): a `#ffffff` → `#f1f2f5` → `#e4e6eb` gradient with a
  faint suit panel-seam line drawing in one corner. Rim light: cyan from the left, red from the
  right.
- **Dark glass chrome** (top bar, sidebar, anything sitting directly on the city):
  `rgba(10,8,24,0.74)` with white text.
- **Emblem:** the ᛉ rune inside a thin triangle (after the poster's triangle, and the valknut).
  Wordmark in light, very widely tracked capitals.

**Roles.** Every role has an *ink* tone for text and a *mark* tone for the markers next to it.
Neon colours are decorative only: never text.

| Role | Ink (text) | Mark | Ink contrast on darkest porcelain `#e4e6eb` |
|---|---|---|---|
| `fg-1` | `#0f1014` | — | ≥ 15 |
| `fg-2` | `#50545e` | — | 5.48 (lowest) |
| `fg-3` | `#a0a4ad` | — | disabled/decorative only |
| `accent` | `#6b4d00` | `#e8b440` | ≥ 5.48 |
| `cyan` | `#006470` | `#00d4e8` | ≥ 5.48 |
| `vault` | `#0b6334` | `#16c95e` | ≥ 5.48 |
| `agent` | `#1f45b8` | `#2f6bff` | ≥ 5.48 |
| `amber` | `#8a4300` | `#ff8a1a` | ≥ 5.48 |
| `destructive` | `#b3162c` | `#ff1f4b` | ≥ 5.48 |

On dark glass, white text measures at least 8.94:1 and 80 % white at least 6.44:1. Both were
measured over the brightest point the city can put behind the glass (a white glitch streak).

**Component grammar**

- Status: small square markers in the mark tone, with uppercase tracked mono labels in the ink
  tone. No pills.
- Primary button: solid graphite with a cyan/red chromatic split on its edges. Secondary
  buttons: 1px graphite outline.
- Display headings: light, tracked capitals with a subtle cyan/red split. EB Garamond italic is
  kept for secondary display lines.
- Agent voice: a blue/violet scanline band with an agent-blue edge.
- Staged: an amber edge with a warm fade.
- Inputs: underline only. Focus is a cyan underline with a red offset.
- Selection: a red and cyan double edge.

**Motion:** the city's streak layer jumps a few pixels briefly every 7s (a "glitch tick"). It is
disabled under `prefers-reduced-motion`. Content surfaces never move.

**Scope boundary:** Shell's material (city, rim light, chromatic split, glitch) belongs to the
theme. It is not an effects utility that Dark surfaces may borrow.

### Density profiles

| Token | Comfortable (today) | Compact |
|---|---|---|
| `--text-base` | 15px | 13px |
| `--text-sm` | 13px | 12px |
| `--space-3` / `--space-4` / `--space-6` | 12 / 16 / 24px | 8 / 12 / 16px |
| `--control-height` (new) | 36px | 28px |
| `--row-height` (new) | 40px | 28px |

Other type steps and spacing are unchanged between profiles.

### Fixes folded into v2

- Correct the "DM Sans" comment. Space Grotesk stays the UI face.
- Load JetBrains Mono from Google Fonts, dropping `fonts.bunny.net`.
- Dark focus ring: a 2px solid `--border-focus` (cyan) outline, with no glow by default. This is
  a visible change, so S1 does not apply it globally. The sheet keeps today's global
  `:focus-visible` rule and glow utility classes. The new ring and the effects layer ship as
  opt-in, and each surface switches during its S3/S4 migration.
- Move `.glow-*`, `.text-glow-*`, `.grid-bg`, `.border-cyan`, and `.border-gold` into an opt-in
  effects layer (`[data-effects="on"]` or explicit `.fx-*` classes), documented as state-only.
- Honour `prefers-reduced-motion` by zeroing `--duration-*`.

## Consumers

| Surface | Repo | Today | Default density | Migration slice |
|---|---|---|---|---|
| Companion workspace dev page and drawers (`companion_ui/workspace/*`) | this | Inlined token subset plus about 260 hex literals across modules | comfortable | S3 |
| Canvas suggestion flow, panel visual shell, converse layout (`companion-ui/companion-app/*.html`) | this | Binding sheet; readable `fg-3` uses | comfortable | S3 |
| BuilderOps Cockpit (`app/web/static/cockpit.*`) | this | Binding sheet (byte-parity copy); `fg-3` uses | compact | S4 |
| Signboard (`app/web/static/signboard.*`) | this | Own palette | compact | S4 |
| Legacy web dashboard (`app/web/static/index.html`) | this | Partial | compact | S4 |
| DevUI candidate (`companion_ui/workspace/devui_candidate/`) and served managed DevUI (`app/builderops/devui_managed.css`, hash-pinned in `devui_assets.py`) | this | Partial, inlined dark tokens | compact | S4 |
| CKM overview (`app/builderops/ckm/overview_html.py`) | this | Own inlined token copy | compact | S4 |
| Bifrost: Heimdal capture, Mimer knowledge (`Yggdrasil/DesignSystem/Theme.swift`) | `RasmusTho/bifrost` | iOS system colours | native (Dynamic Type) | S5 |
| Claude Design live system `f2b13410-…` | Claude Design | Legacy; README drift (DS-1); no exports (DS-2) | — | S2 |

### Bifrost

Bifrost stays native. It adopts Yggdrasil **colours, spacing, and radius** through the generated
`YggdrasilTokens.swift`. Bifrost ships Dark first, with `.preferredColorScheme(.dark)`. Shell
follows on iOS only after the web trial graduates (city backdrop and rim light map to SwiftUI
gradients and shadows). Typography keeps iOS Dynamic Type sizes, mapped onto Yggdrasil
roles (`display` → New York serif as the closest native analogue to EB Garamond unless the font
is bundled; UI → SF Pro). Bifrost vendors the generated Swift file from a named hub commit and
records the token `VERSION` and commit SHA. A Bifrost CI check compares its vendored file against
that commit. No release or tag is required. The cross-repo contract lives under
the ecosystem authority Bifrost already declares (ADR-0050). This spec does not override it.

## Rollout

| Slice | Outcome | Depends on | Notes |
|---|---|---|---|
| **S1** Token source and generator | **Delivered (#5627).** `design-system/yggdrasil/` holds the DTCG source (primitives, semantic aliases, Dark and Shell themes, materials, density, contrast pairs), `VERSION` 2.0.0, and the stdlib `build.py` (`--check` for freshness). It generates both CSS copies, `dist/YggdrasilTokens.swift`, and `dist/tokens.json`. Every v1 token and rule is unchanged (checked against `tests/design_system/fixtures/colors_and_type.v1.css`). Shell, compact density, the v2 focus ring (`data-focus="v2"`), and `.fx-*` effects are opt-in only. JetBrains Mono now loads from Google Fonts. | — | The live Claude Design gate fails closed until S2 re-syncs the new sheet bytes. |
| **S2** Live system reconciliation | Claude Design system republished from S1 output (Dark and Shell), no longer Legacy; README matches tokens (closes DS-1); component previews promoted to exports (DS-2); gate records new SHA-256 | S1 | **Owner-assisted:** needs a working Claude Design login. Until S2 lands, the byte-parity gate fails closed and new design generation waits. |
| **S3** Companion migration | Workspace modules, renderer modules, and the canvas/converse/panel pages use tokens only; inlined subset replaced by the served sheet; off-palette colours removed; readable `fg-3` moved to `fg-2`; opt in to the new focus ring; per-user Light (Shell) toggle for the trial | S1 | Hex-literal ceiling test per module. **Trial gate:** the owner uses Shell in the Companion and then decides whether it graduates, needs changes, or is dropped. |
| **S4** Builder UI migration | Cockpit, Signboard, legacy dashboard, CKM overview (`app/builderops/ckm/overview_html.py`), the DevUI candidate, and the **served managed DevUI stylesheet** `app/builderops/devui_managed.css` on tokens with compact density. Includes updating `ASSET_SHA256` in `app/builderops/devui_assets.py` and its provenance tests. Readable `fg-3` moved to `fg-2`; opt in to the new focus ring. | S1 | Can run in parallel with S3. |
| **S5** Bifrost adoption | `YggTheme` backed by generated Swift tokens; version pin and parity check | S1 | Filed in `RasmusTho/bifrost`. |
| **S6** Governance promotion | DP-11, `DESIGN_HANDOFF_GOVERNANCE.md`, and `yggdrasil-design-handoff` skill point at the token source, version, and effects rule; this doc becomes the owner doc | S1, S2 | Via `post-merge-owner-doc`. |

Sequencing risk: S1 changes the bytes of the binding sheet, so the live gate fails closed until S2
lands. Schedule S1 and S2 back to back. Otherwise S1 must be held while design generation is
active.

## Implementation Tasks

| Task | Slice | Issue |
|---|---|---|
| [Establish the Token Source and Generator](ESTABLISH_TOKEN_SOURCE_AND_GENERATOR.md) | S1 · YDS-01 | #5627 |
| [Reconcile the Live Design System](RECONCILE_LIVE_DESIGN_SYSTEM.md) | S2 · YDS-02 | #5628 |
| [Migrate the Companion Surfaces](MIGRATE_COMPANION_SURFACES.md) | S3 · YDS-03 | #5629 |
| [Migrate the Builder Surfaces](MIGRATE_BUILDER_SURFACES.md) | S4 · YDS-04 | #5630 |
| [Adopt the Tokens in Bifrost](ADOPT_TOKENS_IN_BIFROST.md) | S5 · YDS-05 | filed in `RasmusTho/bifrost` after YDS-01 |
| [Promote the Design System Governance](PROMOTE_DESIGN_SYSTEM_GOVERNANCE.md) | S6 · YDS-06 | #5631 |

The parent validation hub is #5626, described in [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md).

## Cross-Task Invariants / Interaction Safety

These invariants hold across the tasks, which all read or write the same token outputs.

1. **Live parity window.** The binding sheet's bytes equal the live Claude Design sheet, except
   between the YDS-01 merge and the YDS-02 reconciliation. In that window the gate fails closed
   and no design generation runs. *Partial failure:* if YDS-02 cannot run after YDS-01 merges (for
   example, the Claude Design login fails), the window stays closed. Recovery is to finish YDS-02,
   not to hand-edit the live sheet or relax the gate. YDS-01 therefore merges only when YDS-02 can
   run right after.
2. **Generated outputs only.** Consumers read generated outputs, and nobody hand-edits them.
   YDS-01's freshness test fails any drift, so later tasks change values only through the source.
3. **Dark compatibility.** No task changes a Dark token name or value. YDS-03 and YDS-04 can land in
   either order, because a surface that is not yet migrated still renders correctly from the
   unchanged sheet.
4. **Pinned asset hashes move together.** A change to `app/builderops/devui_managed.css` and its
   `ASSET_SHA256` entry ship in the same YDS-04 change. A stylesheet change without the hash
   update fails the DevUI provenance tests.
5. **Shell stays opt-in.** No surface defaults to Shell before YDS-06 records the owner's trial
   decision. Bifrost ships Dark only until then.

## Relationship to GitHub Issues

The parent feature issue is the live validation hub. Child Issues are filed from the task files
above: YDS-01 as ready, and the others as blocked on their prerequisites. YDS-05 is filed in the
Bifrost repository once a token version exists to pin. Issue numbers are written back into each
task file's `github_issue:` frontmatter and into the table above when filed.

## Out of scope

- Redesigning individual surfaces or components beyond token adoption.
- Renaming existing tokens (reserved for a later major version).
- Rewriting historical `design_handoff/*` packages. They keep their recorded token copies under
  the gate's adoption boundary.
- Bundling custom fonts into Bifrost (a Bifrost-local decision).
- Shell as a default for any surface, or on Bifrost, before the trial graduates.
