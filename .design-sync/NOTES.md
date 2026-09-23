# design-sync notes: Yggdrasil Design System

- **Shape is hand-authored, not converter-built.** The live project holds a token sheet, preview
  cards with `@dsCard` markers, README/SKILL prose, and UI kits. There is no React component
  library in this repo (shipped surfaces are server-rendered HTML/CSS; the only `.jsx` files are
  archived `companion-ui/design_handoff/*` explorations). Do not run the storybook/package
  converter against it. Sync with a targeted plan over the paths in `config.json :: fileMap`.
- **Never write `_ds_bundle.js` or `_ds_manifest.json`.** The app compiles both from the UI kit
  sources and the `@dsCard` markers. Write `_ds_needs_recompile` after content writes instead.
- **No `_ds_sync.json` anchor.** The anchor recipe needs converter facts this layout lacks, so
  every re-sync re-verifies. Parity proof is the SHA-256 readback of `colors_and_type.css` against
  the repo binding sheet (the DP-11 gate).
- **Token sheet is generated.** Upload `companion-ui/companion-app/colors_and_type.css` bytes as
  they are; value changes go through `design-system/yggdrasil/` and `build.py`.
- **Global CSS.** The app lists `ui_kits/builderops-cockpit/existing-surfaces/signboard.css` as a
  global stylesheet. Before 2026-09-23 that copy defined its own palette, so the live token index
  resolved `--accent` to Signboard green `#a8d5a2`. It is now synced from
  `app/web/static/signboard.css`, which defines no custom properties. If the app ever injects
  global CSS into designs, that file's element rules (`body`, `h1`, `input`) would leak; removing it
  from the project is an owner call.
- **Previews render against the real sheet.** Verify new cards with Playwright at their `@dsCard`
  viewport (no overflow, no clipping) before upload. Shell cards need `data-theme="light"` on
  `<html>` because the theme selector is `:root[data-theme="light"]`.
