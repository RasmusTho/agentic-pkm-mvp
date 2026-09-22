State: Target-state capability specification. Nothing in this document is shipped. Current binding
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

- **Themes:** keep *Yggdrasil Dark* (today's look) as the default and add *Yggdrasil Light*.
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
| Dark-only | No light palette exists; surfaces needing one hardcode their own. |
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
  tokens/themes/dark.json     # role -> primitive bindings, default
  tokens/themes/light.json
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
3. **Themes:** bind every role for Dark and Light.
4. **Density:** comfortable or compact.
5. **Effects:** glow, grid background, and neon borders. Opt-in only.

**Compatibility:** every token name in today's sheet (`--bg-base`, `--fg-1`, `--accent`,
`--vault-glow`, `--space-4`, `--text-base`, and the rest) keeps its name and Dark value in v2.
Existing consumers change nothing to stay correct. Renames, if any, are a later major version.

### Theme and density selection (web)

- Theme: `data-theme="dark" | "light"` on the root element. With no attribute, the surface's
  declared default applies (Dark for all current surfaces). Surfaces may follow
  `prefers-color-scheme` only when they opt in with `data-theme="system"`.
- Density: `data-density="comfortable" | "compact"`, with comfortable as the default.
- Both are pure token swaps. No component CSS may branch on theme or density.

### Yggdrasil Light (proposed values)

Contrast ratios below were computed against WCAG 2.x relative luminance for this spec. S1 turns
them into a CI check.

| Role | Dark (unchanged) | Light | Light contrast on `bg-base` / `bg-raised` |
|---|---|---|---|
| `bg-base` | `#070b12` | `#eef2f6` | — |
| `bg-surface` | `#0c1220` | `#f7f9fb` | — |
| `bg-raised` | `#111a2e` | `#ffffff` | — |
| `bg-overlay` | `#162038` | `#e4eaf1` | — |
| `fg-1` | `#dce8f0` | `#0d1726` | 15.99 / 17.98 |
| `fg-2` | `#7a9ab8` | `#4a6280` | 5.57 / 6.27 |
| `fg-3` | `#3d5570` | `#7d90a6` | 2.91 / 3.28 (disabled/decorative only) |
| `accent` | `#d4a843` | `#8a6512` | 4.72 / 5.32 |
| `cyan` | `#00d4e8` | `#00707c` | 5.17 / 5.82 |
| `vault` | `#39e87d` | `#137a46` | 4.79 / 5.38 |
| `agent` | `#4a9eff` | `#1f5fbf` | 5.41 / 6.09 |
| `amber` | `#f09030` | `#9a4f08` | 5.34 / 6.01 |
| `destructive` | `#ff3d3d` | `#c02626` | 5.26 / 5.92 |

In both themes `fg-3` is below 4.5:1 (Dark: 2.56 on `bg-base`), so v2 documents it as
disabled/decorative only. It must never carry readable content. Light-theme `-dim` and `-muted`
tints, borders, and shadows are derived in S1 and ship under the same contrast check.

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
- Focus ring: a 2px solid `--border-focus` outline in both themes, with no glow by default.
- Move `.glow-*`, `.text-glow-*`, `.grid-bg`, `.border-cyan`, and `.border-gold` into an opt-in
  effects layer (`[data-effects="on"]` or explicit `.fx-*` classes), documented as state-only.
- Honour `prefers-reduced-motion` by zeroing `--duration-*`.

## Consumers

| Surface | Repo | Today | Default density | Migration slice |
|---|---|---|---|---|
| Companion workspace dev page and drawers (`companion_ui/workspace/*`) | this | Inlined token subset plus about 260 hex literals across modules | comfortable | S3 |
| Canvas suggestion flow, panel visual shell, converse layout (`companion-ui/companion-app/*.html`) | this | Binding sheet | comfortable | S3 (verify only) |
| BuilderOps Cockpit (`app/web/static/cockpit.*`) | this | Binding sheet (byte-parity copy) | compact | S4 (verify only) |
| Signboard (`app/web/static/signboard.*`) | this | Own palette | compact | S4 |
| Legacy web dashboard (`app/web/static/index.html`) | this | Partial | compact | S4 |
| DevUI candidate (`companion_ui/workspace/devui_candidate/`) | this | Partial | compact | S4 |
| Bifrost: Heimdal capture, Mimer knowledge (`Yggdrasil/DesignSystem/Theme.swift`) | `RasmusTho/bifrost` | iOS system colours | native (Dynamic Type) | S5 |
| Claude Design live system `f2b13410-…` | Claude Design | Legacy; README drift (DS-1); no exports (DS-2) | — | S2 |

### Bifrost

Bifrost stays native. It adopts Yggdrasil **colours, spacing, and radius** through the generated
`YggdrasilTokens.swift`. Colours become asset-catalog-style dynamic `Color`s that resolve Dark and
Light from the system appearance. Typography keeps iOS Dynamic Type sizes, mapped onto Yggdrasil
roles (`display` → New York serif as the closest native analogue to EB Garamond unless the font
is bundled; UI → SF Pro). Bifrost vendors a pinned token version and records it. A Bifrost CI check
compares its vendored file against the tagged release here. The cross-repo contract lives under
the ecosystem authority Bifrost already declares (ADR-0050). This spec does not override it.

## Rollout

| Slice | Outcome | Depends on | Notes |
|---|---|---|---|
| **S1** Token source and generator | DTCG source, stdlib generator, regenerated binding sheet with byte-compatible Dark semantics, Light theme, density profiles, effects layer, contrast and freshness CI | — | Enabling change. Existing consumers render identically in Dark/comfortable. |
| **S2** Live system reconciliation | Claude Design system republished from S1 output, no longer Legacy; README matches tokens (closes DS-1); component previews promoted to exports (DS-2); gate records new SHA-256 | S1 | **Owner-assisted:** needs a working Claude Design login. Until S2 lands, the byte-parity gate fails closed and new design generation waits. |
| **S3** Companion migration | Workspace modules use tokens only; inlined subset replaced by the served sheet; Light theme selectable | S1 | Hex-literal ceiling test per module. |
| **S4** Builder UI migration | Signboard, legacy dashboard, and DevUI candidate on tokens with compact density; Cockpit verified | S1 | Can run in parallel with S3. |
| **S5** Bifrost adoption | `YggTheme` backed by generated Swift tokens; version pin and parity check | S1 | Filed in `RasmusTho/bifrost`. |
| **S6** Governance promotion | DP-11, `DESIGN_HANDOFF_GOVERNANCE.md`, and `yggdrasil-design-handoff` skill point at the token source, version, and effects rule; this doc becomes the owner doc | S1, S2 | Via `post-merge-owner-doc`. |

Sequencing risk: S1 changes the bytes of the binding sheet, so the live gate fails closed until S2
lands. Schedule S1 and S2 back to back. Otherwise S1 must be held while design generation is
active.

## Out of scope

- Redesigning individual surfaces or components beyond token adoption.
- Renaming existing tokens (reserved for a later major version).
- Rewriting historical `design_handoff/*` packages. They keep their recorded token copies under
  the gate's adoption boundary.
- Bundling custom fonts into Bifrost (a Bifrost-local decision).
