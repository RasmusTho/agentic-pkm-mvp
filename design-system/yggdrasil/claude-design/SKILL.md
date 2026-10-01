---
name: yggdrasil-design
description: Use this skill to design interfaces for Yggdrasil, a local-first AI second brain. It holds the v2 token sheet (Yggdrasil Dark default, Yggdrasil Light "Shell", comfortable and compact density), content rules, and preview cards for the Companion UI, Builder System UIs, and Bifrost.
user-invocable: true
---

Read `README.md` first, then `colors_and_type.css`. The sheet is generated and binding: use its
tokens exactly, and never restate or edit its values.

Rules that are easy to miss:

- Link `colors_and_type.css` and set theme and density on the root element: `data-theme="dark"`
  (default) or `"light"` for Shell, and `data-density="comfortable"` or `"compact"`. Add
  `data-focus="v2"` to new work. Components never branch on theme or density.
- Dark is the default. Use Shell only when the brief asks for the light theme.
- Colour through roles (`--fg-1`, `--accent`, `--vault`, `--agent`, `--amber`, `--destructive`),
  never raw hex. Readable text never uses `--fg-3`.
- Put text in the role ink (`--vault`) and markers in the mark tone (`--vault-mark`). Neon is never
  text.
- Glow is a state, not a style. Use `.fx-*` classes only on the active, live, or working element.
  Do not use the v1 `.glow-*`, `.grid-bg`, or `.border-cyan` classes in new designs.
- Build frames from the `--surface-*` tokens so one layout renders in both themes.
- Use Builder dashboards at compact density and Companion surfaces at comfortable density.
- There is no importable component library. Compose components from tokens and follow the grammar
  table in `README.md`. The `preview/` cards and `ui_kits/` are references.

For visual artifacts (mocks, throwaway prototypes), produce static HTML that links the sheet. For
production code, copy the rules, not the values. If the user invokes this skill with no other
guidance, ask what they want to build and which surface it belongs to, then act as an expert
designer.
