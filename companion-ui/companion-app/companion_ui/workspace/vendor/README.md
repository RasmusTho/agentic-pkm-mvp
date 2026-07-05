# Vendored browser modules (self-hosted, no runtime CDN)

The Companion workspace page (`serve_dev_page.render_index_html`, used by both the
dev and production launch profiles) previously loaded its source-editor front-end
dependency from the public `esm.sh` CDN at runtime via a top-level
`<script type="module">` static import. A static module import gates
`DOMContentLoaded` on its resolution, so when esm.sh was slow or unreachable the
whole page hung — an availability + supply-chain dependency baked into the product
runtime (and the direct cause of the `companion-ui-browser-runtime` CI false-fail
on 2026-07-04, #2884).

These bundles are the self-hosted replacement. They are served from the local API
as static assets (`/static/vendor/...`) so the product has **no runtime CDN
dependency** for the editor.

## Files

| File | Exports | Source packages (pinned) |
|---|---|---|
| `codemirror-6.0.1.mjs` | `EditorView`, `basicSetup`, `markdown`, `markdownLanguage`, `oneDark` | `codemirror@6.0.1`, `@codemirror/lang-markdown@6.2.5`, `@codemirror/theme-one-dark@6.1.2` (transitively `@codemirror/state@6.7.0`, `@codemirror/view@6.43.5`, `@codemirror/language@6.12.4`, `@codemirror/commands@6.10.4`, `@lezer/markdown@1.6.4`) |

`codemirror-6.0.1.mjs` sha256: `fa1ed1dab6c60c9dab67d65e5123b0c4fd24cc3c87dae762b042c3dbacc436d8`

## Regenerating (reproducible, no repo build system required)

This repository has no frontend build pipeline. The bundle is produced out-of-band
with `esbuild` and committed. To regenerate byte-for-byte-equivalent output:

```sh
mkdir cm-vendor && cd cm-vendor
printf '{ "name": "cm-vendor-build", "private": true, "type": "module" }\n' > package.json
npm install --no-audit --no-fund \
  codemirror@6.0.1 @codemirror/lang-markdown@6.2.5 @codemirror/theme-one-dark@6.1.2

cat > entry-codemirror.mjs <<'ENTRY'
export { EditorView, basicSetup } from 'codemirror';
export { markdown, markdownLanguage } from '@codemirror/lang-markdown';
export { oneDark } from '@codemirror/theme-one-dark';
ENTRY

npx esbuild@0.24.0 entry-codemirror.mjs --bundle --format=esm --minify \
  --target=es2020 --outfile=codemirror-6.0.1.mjs
```

Then copy `codemirror-6.0.1.mjs` here. The entry file re-exports exactly the five
symbols the page imports; keep it in sync with the import site in
`serve_dev_page.py` if the editor's dependency surface changes.

## Not vendored: mermaid

`mermaid@10.9.1` is still loaded from `esm.sh` at runtime, but it is a **dynamic**
import inside a `try/catch` that already degrades to the raw diagram source on
failure (`serve_dev_page._mermaid_render_script`), so a CDN outage is non-fatal —
one diagram falls back to source, the page and editor keep working. A naive
esbuild bundle of mermaid is ~3.5 MB and statically inlines mermaid's lazy
diagram-type loaders, which risks breaking diagram-type registration in ways that
need per-diagram browser verification.

**Decision (#2897): accepted — mermaid stays CDN-loaded; the product assumes
internet access.** It is not self-hosted (the ~3.5 MB bundle + registration risk
outweigh removing a non-fatal dependency). Revisit only if fully-offline
operation becomes a requirement. This dependency is recorded in
`docs/DEPENDENCIES.md` (Browser runtime dependencies).
