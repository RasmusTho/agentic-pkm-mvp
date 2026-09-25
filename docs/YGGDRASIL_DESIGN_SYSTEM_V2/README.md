State: Owner doc for the Yggdrasil Design System v2 (promoted by YDS-06, #5631, on 2026-09-25).
Slices S1–S6 and the Shell follow-ups (#5652, #5657, #5662) are delivered and recorded in
`:: Rollout`. Binding token truth is the generated `companion-ui/companion-app/colors_and_type.css`
(design-system `VERSION`, currently 2.2.0) under `docs/DESIGN_PRINCIPLES.md :: 11. Shared Visual
Language`; where this document and the generated sheet disagree, the sheet wins.
Doc role: Owner doc for the Yggdrasil Design System v2 (token source, themes, density, effects, rollout record).
Owner: Yggdrasil visual language (DP-11)
Temporal class: delivered capability contract (authored as target state; owner-doc promotion 2026-09-25)
Review cadence: event-driven (per token version or theme change)
Last reviewed: 2026-09-25
Last verified against: origin/main 9f6ad309f, `companion-ui/companion-app/colors_and_type.css`,
`app/web/static/colors_and_type.css`, `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Yggdrasil
design-system gate`, `.codex/skills/yggdrasil-design-handoff/SKILL.md`,
`docs/BUILDEROPS_COCKPIT/DESIGN_DECISIONS.md :: Design-system conflicts`,
`tests/api/test_cockpit_api.py`, `RasmusTho/bifrost:Yggdrasil/Yggdrasil/DesignSystem/Theme.swift`

# Yggdrasil Design System v2

Refine the Yggdrasil Design System from a single dark token sheet, copied by hand into each
consumer, into one versioned, layered, platform-neutral system that every Yggdrasil surface draws
from: the Companion product UI, the Builder System UIs, and the Bifrost native clients.

Owner decisions recorded 2026-09-22:

- **Themes:** *Yggdrasil Dark* (today's look) stays the default. *Yggdrasil Light "Shell"* was
  approved for trial on 2026-09-22 and **graduated on 2026-09-25** (see below). It is inspired by the Ghost in the Shell (2017) posters: porcelain work
  surfaces floating on a glitching neon city. Four earlier light directions were reviewed and
  rejected the same day because they felt generic, "90s", or "too My Little Pony": a plain cool
  light, a frost / Tron-grid / neon-signage trio, a prismatic rainbow-bridge look, and a muted porcelain Shell.
  The review page is kept at [`exploration/2026-09-22-shell-light-theme.html`](exploration/2026-09-22-shell-light-theme.html).
  The trial rule was that Shell graduates only after the owner uses it in the Companion (S3).
  **Graduated 2026-09-25:** after using Shell (frosted glass and night city, v2.2.0) the owner
  chose to keep it (#5626, #5631). Shell is a supported theme; Dark stays the default.
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
  tokens/themes/shell.json    # role -> primitive bindings (Yggdrasil Light "Shell")
  tokens/css-values.json      # CSS-native values DTCG cannot express (shadow stacks,
                              # gradients/materials, em letter-spacing, keyword easing)
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
| `companion-ui/companion-app/yggdrasil-tokens.css` and `app/web/static/yggdrasil-tokens.css` | Tokens only: the same tokens, themes, density, opt-in rules, and reduced motion, without v1 element defaults. For surfaces that own their base styles: the Companion workspace pages and the web Builder surfaces, both served at `/static/yggdrasil-tokens.css`. |
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
  Light is a per-user choice in the Companion and is not a surface default (graduated from trial
  on 2026-09-25; the default stays Dark).
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

### Yggdrasil Light "Shell"

The suit against the city. The surfaces people read and write on are calm porcelain. The frame
around them is a saturated neon city that the porcelain catches as rim light.

**Structure**

- **City backdrop** (the app frame, visible around and through panels): a lit night (#5662).
  A near-black base (`#150a2a` → `#06040c` → `#020104`) with small neon "sign" glows and corner
  fields in four palette colours (`--city-<n>-a..d`), vertical glitch streaks, and scanlines. The
  palette cycles over 10 minutes through three complementary sets: Neo-Tokyo (red `#ff1f4b` ↔
  cyan `#00e5ff`, magenta `#ff2aa0` ↔ blue `#2850ff`), Aurora (coral ↔ turquoise, violet ↔ amber),
  and Ice & Ember (ember ↔ ice cyan, indigo ↔ gold). The owner asked for more black and a slow
  cycle on 2026-09-24.
- **Porcelain sheet** (content surfaces): frosted glass. A translucent `#ffffff` → `#f1f2f5` →
  `#e4e6eb` gradient at 90 % → 85 % coverage (`--material-sheet`) with a backdrop frost
  (`--surface-panel-filter`: `blur(6px) saturate(1.5)`), so the city's glows show through. The
  owner chose frosted glass ("C · Glas") on 2026-09-24 (#5652). Coverage rose from 75 % with the
  night base (#5662), so the porcelain still reads as porcelain against black. A faint suit panel-seam
  line draws in one corner. Rim light: cyan from the left, red from the right.
- **Reading surface** (note body, source editor; `--surface-reading`): calm glitch. Porcelain at
  86 % coverage with faint static scanlines and two hairline chroma streaks (cyan, red). It is
  static: no animation. Dark keeps `var(--bg-base)`.
- **Dark glass chrome** (top bar, sidebar, anything sitting directly on the city):
  `rgba(10,8,24,0.74)` with white text.
- **Emblem:** the ᛉ rune inside a thin triangle (after the poster's triangle, and the valknut).
  Wordmark in light, very widely tracked capitals.

**Roles.** Every role has an *ink* tone for text and a *mark* tone for the markers next to it.
Neon colours are decorative only: never text.

| Role | Ink (text) | Mark | Worst-case ink contrast (sheet over any city colour) |
|---|---|---|---|
| `fg-1` | `#0f1014` | — | 8.83 |
| `fg-2` | `#3f424a` | — | 4.67 |
| `fg-3` | `#a0a4ad` | — | disabled/decorative only |
| `accent` | `#573e00` | `#e8b440` | 4.66 |
| `cyan` | `#004a53` | `#00d4e8` | 4.63 |
| `vault` | `#094d29` | `#16c95e` | 4.63 |
| `agent` | `#1a3999` | `#2f6bff` | 4.67 |
| `amber` | `#6a3400` | `#ff8a1a` | 4.63 |
| `destructive` | `#841021` | `#ff1f4b` | 4.69 |

The inks were darkened in #5652 because the sheet is translucent: the worst case is the 75 %
sheet over the darkest city violet `#1a0a2e`. On the solid porcelain `#e4e6eb` every ink measures
at least 7.99. `tests/design_system/test_yggdrasil_tokens.py::test_shell_text_holds_aa_over_translucent_sheet`
guards the composite.

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

**Motion (opt in with `class="fx-city"` on `<html>`):** three static palette layers cross-fade
over a 600 s cycle with opacity only, so the cycle runs on the compositor (measured main-thread
cost: about 0.3 ms/s, against about 67 ms/s for an animated colour variable). Every 29 s a horizontal tear (two neon hairlines and faint bands) crosses
the screen for about 150 ms, above everything but never taking input. Every 53 s the city lights
dip twice behind the glass. Combined, the flashes stay at or below three per second. Everything
stops under `prefers-reduced-motion`; in Dark the animation-name tokens are `none`. Content
surfaces never move.

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
| DevUI candidate (`companion_ui/workspace/devui_candidate/`) and served managed DevUI (`app/builderops/devui_managed.css`, hash-pinned in `devui_assets.py`) | this | Inline Yggdrasil Dark copy (41/44 identical; system fonts under a strict CSP) | compact | #5637 |
| CKM overview (`app/builderops/ckm/overview_html.py`) | this | Own inlined token copy | compact | S4 |
| Bifrost: Heimdal capture, Mimer knowledge (`Yggdrasil/DesignSystem/Theme.swift`) | `RasmusTho/bifrost` | iOS system colours | native (Dynamic Type) | S5 |
| Claude Design live system `f2b13410-…` | Claude Design | Reconciled to v2.0.0 on 2026-09-23 (token SHA-256 parity; DS-1 closed; DS-2 kept with reason); re-reconciled to v2.1.0 (#5652) and v2.2.0 (#5662, night city) on 2026-09-24 | — | S2 (delivered) |

### Bifrost

Bifrost stays native. It adopts Yggdrasil **colours, spacing, and radius** through the generated
`YggdrasilTokens.swift`. Bifrost ships Dark first, with `.preferredColorScheme(.dark)`. Shell
follows on iOS only after the web trial graduates. It graduated on 2026-09-25, and iOS Shell is
now a separate Bifrost decision outside v2 (city backdrop and rim light map to SwiftUI
gradients and shadows). Typography keeps iOS Dynamic Type sizes, mapped onto Yggdrasil
roles (`display` → New York serif as the closest native analogue to EB Garamond unless the font
is bundled; UI → SF Pro). Bifrost vendors the generated Swift file from a named hub commit and
records the token `VERSION` and commit SHA. A Bifrost CI check compares its vendored file against
that commit. No release or tag is required. The cross-repo contract lives under
the ecosystem authority Bifrost already declares (ADR-0050). This spec does not override it.

## Rollout

| Slice | Outcome | Depends on | Notes |
|---|---|---|---|
| **S1** Token source and generator | **Delivered (#5627).** `design-system/yggdrasil/` holds the DTCG source (primitives, semantic aliases, Dark and Shell themes, density; structured values and `{alias}` syntax, checked by `test_token_source_is_valid_dtcg`), `css-values.json` for CSS-native values DTCG cannot express (shadows, materials, em tracking, keyword easing), the contrast pairs, `VERSION` 2.0.0, and the stdlib `build.py` (`--check` for freshness). It generates both CSS copies, `dist/YggdrasilTokens.swift`, and `dist/tokens.json`. Every v1 token and rule is unchanged (checked against `tests/design_system/fixtures/colors_and_type.v1.css`). Shell, compact density, the v2 focus ring (`data-focus="v2"`), and `.fx-*` effects are opt-in only. JetBrains Mono now loads from Google Fonts. `prefers-reduced-motion` zeroes the duration tokens. `dist/tokens.json` resolves every alias to a concrete value. | — | The live Claude Design gate fails closed until S2 re-syncs the new sheet bytes. |
| **S2** Live system reconciliation | **Delivered (#5628).** The owner confirmed on 2026-09-25 that the live project no longer shows as Legacy (#5626). The owner-started `/design-sync` run (finalized plan: 11 named paths plus the recompile marker, no deletes) uploaded the generated `colors_and_type.css`, rewrote the live `README.md` and `SKILL.md` from the tokens (Dark and Shell, density, ink/mark tones, effects rule; closes DS-1), added three Shell cards plus density and focus/effects cards, corrected two drifted card labels, and replaced the stale Signboard stylesheet that had overridden the live `--accent` index with Signboard green. **Live-parity evidence:** the live `colors_and_type.css` read back on 2026-09-23 hashes to SHA-256 `99120ff9bb29dc0b497cd09802cc2e6ea87dcd9814a1afdf22690126fa837243` (17,439 bytes), equal to both repo copies; the gate records it with version 2.0.0. DS-2 keeps its limitation with a reason. Authored sources and the sync pin live in `design-system/yggdrasil/claude-design/` and `.design-sync/`. | S1 | Re-reconciled per token version (2.1.0 #5652, 2.2.0 #5662); the gate records the current hash. |
| **S3** Companion migration | **Delivered (#5629).** The workspace and orientation pages link the generated tokens-only sheet (served at `/static/yggdrasil-tokens.css`) and opt in to the v2 focus ring; 50 inlined token copies and 210 `var(--x, #hex)` fallbacks are gone, and the remaining free hex literals map to tokens except four justified exceptions (help-guide error page, two authority-state colours). 171 readable `fg-3` uses moved to `fg-2` across the Companion modules and pages. Theme is a `companion.displayPreferences.v1` preference (Dark canonical; Light "Shell" as a per-user choice in the settings drawer, applied before first paint), and under Light the workspace renders porcelain sheets with rim light on the city backdrop. Since the #5652 follow-up the orientation door applies the same stored theme and surface tokens (it previously stayed Dark). | S1 | **Trial gate closed:** the owner used Shell and chose to keep it on 2026-09-25 (#5626). |
| **S4** Builder UI migration | **Delivered (#5630).** Signboard and the legacy dashboard load the tokens-only sheet and drop their local palettes; the CKM overview embeds the generated tokens at render time (standalone file, no web-font `@import`); readable `fg-3` moved to `fg-2` in Signboard, dashboard, CKM, and Cockpit; every page opts in to compact density and the v2 focus ring. No hex literals remain outside print styles. The managed DevUI was split to #5637 (it already renders Yggdrasil Dark; its change needs a new constrained-reuse revision, browser proof, and VM102 receipts). | S1 | Ran in parallel with S3. The managed DevUI migration (#5637) was moved out of v2 scope by the owner on 2026-09-25 (option B): the DevUI already renders Dark with 41/44 identical tokens. |
| **S5** Bifrost adoption | **Delivered (`RasmusTho/bifrost#70`).** `YggTheme` is backed by the generated Swift tokens with a version pin and CI parity check. Bifrost ships Dark. | S1 | Bifrost stays pinned to 2.0.0 until it needs later tokens. |
| **S6** Governance promotion | **Delivered (#5631).** DP-11, `DESIGN_HANDOFF_GOVERNANCE.md`, and the `yggdrasil-design-handoff` skill point at the token source, `VERSION`, themes, and effects rule; the owner's Shell outcome (keep) is recorded; this document is the owner doc. | S1, S2 | Parent #5626 handed to `verification-and-closure`. |

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
5. **Shell stays opt-in.** Shell graduated on 2026-09-25 but no surface defaults to it; it is a
   per-user choice. Bifrost ships Dark only.

## Relationship to GitHub Issues

Parent #5626 was the validation hub. Its children were YDS-01–04 (#5627–#5630), YDS-05
(`RasmusTho/bifrost#70`) and YDS-06 (#5631), all delivered; each task file's `github_issue:`
frontmatter holds its number. #5637 (managed DevUI) left the v2 scope by owner decision. Later
changes to this system are ordinary issues that cite this owner doc.

## Out of scope

- Redesigning individual surfaces or components beyond token adoption.
- Renaming existing tokens (reserved for a later major version).
- Rewriting historical `design_handoff/*` packages. They keep their recorded token copies under
  the gate's adoption boundary.
- Bundling custom fonts into Bifrost (a Bifrost-local decision).
- Shell as a default for any surface, or on Bifrost (a separate Bifrost decision after graduation).
