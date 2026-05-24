# Source Manifest

## Source

- **Source design URL:** `https://api.anthropic.com/v1/design/h/ChRizWmVEC_PmOhoUUYc9g?open_file=Vault+Browser+Design+Handoff.html`
- **Local handoff input package:** `tmp/claude-design-vault-browser-handoff/` (in repo working tree at capture time; not committed).
- **Date captured:** 2026-05-24

## What the design URL returned

A gzipped tar archive containing the Claude Design project. Relevant items:

- `companion-ui/project/Vault Browser Design Handoff.html` — primary design
  document. This is the file converted to
  [`VAULT_BROWSER_DESIGN_HANDOFF.md`](VAULT_BROWSER_DESIGN_HANDOFF.md).
- `companion-ui/project/Vault Browser Design Handoff (standalone).html` —
  same content with inlined styles for offline viewing.
- `companion-ui/project/*.jsx`, `companion-ui/project/*.css` — design canvas
  components and shared tokens used to render the HTML. Not committed; these
  are design-tool internals, not implementation code.

Only the textual content of the primary HTML was converted. The interactive
SVG mockups and CSS-driven visualizations are described in prose in the
converted Markdown (see fidelity note in [`README.md`](README.md)).

## Files included from the input handoff package

The temporary handoff package that was sent to Claude Design contained:

- `tmp/claude-design-vault-browser-handoff/README.md`
- `tmp/claude-design-vault-browser-handoff/SOURCE_MANIFEST.md`
- `tmp/claude-design-vault-browser-handoff/DESIGN_TASK.md`
- Canonical SoT excerpts under `tmp/claude-design-vault-browser-handoff/docs/`:
  - `VAULT_BROWSER_CAPABILITY_CONTRACT.md`
  - `ARCHITECTURE.md`
  - `COMPONENTS.md`
  - `HUMAN-FLOWS.md`
  - `FRONTMATTER.md`
  - `EVENTS.md`
  - `AGENT_MEMORY_README.md`
  - `CONTEXTUALIZATION_LAYER_README.md`
- Companion UI excerpts under
  `tmp/claude-design-vault-browser-handoff/companion-ui/`:
  - `PANEL_COMPANION_UI_CONTRACT.md`
  - `MLP_INTERACTION_DESIGN_HANDOFF.md`
- Implementation extracts under
  `tmp/claude-design-vault-browser-handoff/implementation-extract/`:
  - `companion-route-extract.py.txt`
  - `vault-browser-api-tests.py.txt`
  - `vault-browser-ui-tests.py.txt`

None of these source-package excerpts are committed inside this design-handoff
folder — they are pointers to live repo SoT under `docs/`, `companion-ui/`,
`app/`, and `tests/`.

## Screenshots

The handoff package referenced one Companion UI UAT screenshot
(`Companion UI UAT.md` view) used to ground the §02 workspace shell critique.
No screenshots are committed in this design-handoff folder; the critique is
written so a reader can locate the equivalent state in the running app.

## Canonical SoT docs constraining this handoff

The handoff is non-authoritative and constrained by the following repo SoT
docs. If any design recommendation conflicts with these, the SoT wins:

- `docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`
- `docs/ARCHITECTURE.md`
- `docs/COMPONENTS.md`
- `docs/HUMAN-FLOWS.md`
- `docs/FRONTMATTER.md`
- `docs/EVENTS.md`
- `docs/AGENT_MEMORY/README.md`
- `docs/CONTEXTUALIZATION_LAYER/README.md`
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md`
- `companion-ui/docs/MLP_INTERACTION_DESIGN_HANDOFF.md`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md` (governance for this
  package)

## Related issues

- **#1259** — *this issue*: land the Claude Design handoff as a
  non-authoritative design artifact.
- **#1260** — workspace shell orientation alignment (downstream; informed by
  §02 critique).
- **#1261** — Vault Browser Foundation sequencing/planning issue.
- **#1253** — metadata read model (informed by §07, §09 Metadata tab, §15 data
  attributes).
- **#1254** — metadata filters and badges (informed by §07, §08, §10).
- **#1255** — artifact inspector (informed by §09).
- **#1256** — VaultAction display model (informed by §11).
- **#1257** — agent receipts and review posture (informed by §12).

## Conversion fidelity note

The Markdown conversion preserves all section headings, tables, prose, and
rules. SVG mockups in the source HTML are described in prose rather than
reproduced. See [`README.md`](README.md) §"Conversion fidelity" for details.

## Disposability

Per `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`, design handoff packages
are guidance and input only. This package is disposable in the sense that the
canonical reading of the design lives in the converted Markdown plus the
mapping file; the original HTML and project archive can be regenerated from the
source URL.
