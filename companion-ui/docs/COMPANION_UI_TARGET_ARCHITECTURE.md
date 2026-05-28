---
name: Companion UI Target Architecture
description: Defines the long-term target architecture for Companion UI as a local-first web application served by the Yggdrasil host
doc_role: Target-state architecture definition
authority: Owner doc for Companion UI product architecture decisions. Binding on Companion UI implementation, hosting, access model, and vault-boundary decisions.
owner: Companion UI / product architecture
temporal_class: strategic
review_cadence: event-driven
last_reviewed: 2026-05-18
last_verified_against: |
  companion-ui/docs/REAL_NOTE_WORKSPACE_DEV_PAGE.md,
  companion-ui/docs/UI_RUNTIME_BOUNDARIES.md,
  companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md,
  companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md,
  docs/COMPANION_UI_PRODUCT_SPEC.md,
  docs/ENVIRONMENTS.md,
  docs/ROADMAP.md,
  docs/STATUS.md
governing_issue: "#1102"
---

# Companion UI Target Architecture

## Purpose

Define the long-term target architecture for Companion UI as a product before further UI
implementation. This document is the owner doc for Companion UI hosting, access model, and
vault-boundary decisions.

## Current-state guardrail

This document defines target-state architecture and records decisions before they are implemented.
It does not claim that all described capability is currently shipped.

Current shipped state is tracked in section [Current Shipped State](#current-shipped-state) below
and in `docs/STATUS.md`. Do not interpret future-state sections as present-tense claims.

---

## 1. Primary Target: Local-First Web Application

**Companion UI is a browser-accessible, local-first web application.**

- Companion UI is served by the Yggdrasil host process.
- It is accessed from trusted devices over localhost, LAN, or Tailscale.
- There is no separate native macOS, Windows, or iPadOS app now. Native apps are an optional
  future wrapper, not the current primary architecture.
- The browser is the primary delivery surface.

This decision establishes the product architecture before any browser server is shipped. It must
remain the reference point for all hosting, access, and packaging decisions until explicitly
superseded by a later owner-doc update.

---

## 2. Runtime Boundary: API Is the Only Vault Access Path

**The runtime API is the only access path for notes and vault content.**

Rules that apply unconditionally to Companion UI:

- Companion UI must not read vault files directly.
- Companion UI must not write vault files directly. All writes route through the governed runtime
  execution path (policy, WriteGuard, idempotency, deterministic note-writer, receipt).
- Companion UI must not know or choose which vault is active.
- Companion UI must not configure, hardcode, or select named vaults (Midgård, Nifelheim,
  Bifröst, or any other).
- Companion UI must not expose vault filesystem paths to the browser or to browser-side logic.

The runtime owns environment selection, vault binding, write authority, and receipt production.
Companion UI is a consumer of the runtime API.

See also:

- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` — cognitive boundary constraints and integration rules.
- `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md :: Write-Back Boundary` — Panel write-back rules.

---

## 3. Environment-Bound Vault Model

The vault that Companion UI reads is bound by the runtime environment, not by the UI.

Companion UI configures or receives an API base URL (e.g., `COMPANION_API_BASE_URL`). The runtime
environment determines which vault is bound to that URL. The UI is not aware of the vault name.

Mapping examples (vault names are binding examples only, not UI configuration values):

| Configured `COMPANION_API_BASE_URL` | Runtime env | Bound vault (example) |
|--------------------------------------|-------------|----------------------|
| `http://localhost:18001`             | `dev`       | Nifelheim            |
| `http://localhost:18002`             | `test`      | Bifröst              |
| `http://localhost:18000`             | `prod`      | Midgård              |

These vault names are illustrative. The UI must not special-case, hardcode, or select them.

For environment and port details, see `docs/ENVIRONMENTS.md`.

---

## 4. Access Model

**Default: localhost only.**

| Bind target | When to use | Notes |
|---|---|---|
| `127.0.0.1` (localhost) | Default | Local-only; safe starting point |
| LAN IP / `0.0.0.0` | Intentional LAN access | Explicit operator choice; not the default |
| Tailscale IP / `0.0.0.0` | Intentional Tailnet access | Explicit operator choice; not the default |
| Public internet | Not supported now | Requires future auth/TLS/reverse-proxy hardening |

Rules:

- The dev server must bind to `127.0.0.1` by default.
- LAN or Tailscale binding must be an explicit operator choice (e.g., `HOST=0.0.0.0`).
- Companion UI must never be exposed to the public internet without auth/TLS/reverse-proxy hardening.
  That hardening is deferred; it is not part of the dev server scope.
- Work-computer access is deferred unless already safely reachable through the operator's approved
  Tailscale/network setup.

The detailed localhost/LAN/Tailscale/token/CSRF posture is defined in
`companion-ui/docs/LOCAL_ACCESS_MODEL.md`.

---

## 5. Current Shipped State

As of 2026-05-26 (after PR #1101, PR #1108, PR #1119, the Obsidian renderer/editor epic #1293–#1306, and the CodeMirror source editor #1329):

| Component | State |
|---|---|
| Live workspace HTTP client | Shipped — `companion_ui/workspace/workspace_http_client.py` (#1071 / PR #1101) |
| Real-note workspace dev page model | Shipped — `companion_ui/workspace/real_note_workspace_dev_page.py` (#1072 / PR #1101) |
| Browser dev server | Shipped — `companion_ui/workspace/serve_dev_page.py` (#1103 / PR #1108) |
| Real-note workspace visual shell (first alignment pass) | Shipped — Yggdrasil tokens, note body primary, companion rail placeholder (#1119). Dev/staging only. |
| Obsidian-compatible Markdown parser and resolvers | Shipped — `companion_ui/renderer/` parser, link resolver, and asset resolver provide read-only parsing/resolution boundaries (#1296, #1297, #1298). |
| Vault Markdown renderer core | Shipped — Python server-side read-only renderer wired into the Python-served note body (#1299). Unsafe HTML stripped/escaped; wikilinks/assets route through resolver boundaries. |
| Obsidian callout renderer | Shipped — `companion_ui/renderer/callout_renderer.py`; type styling, fold state, nested Markdown (#1300 / PR #1313). |
| Mermaid safe renderer | Shipped — `companion_ui/renderer/mermaid_renderer.py`; source preserved, no JS execution, no external network (#1301 / PR #1315). |
| Properties/frontmatter renderer | Shipped — `companion_ui/renderer/properties_renderer.py`; read-only YAML display, tag chips, aliases, malformed diagnostics (#1302 / PR #1314). |
| Note outline navigation | Shipped — `companion_ui/renderer/note_outline.py`; heading navigation, desktop side panel, no rename (#1303 / PR #1316). |
| Link preview | Shipped — `companion_ui/renderer/link_preview.py`; bounded hover preview, read-only, no write path (#1304 / PR #1325). |
| CodeMirror 6 source editor (body-edit panel) | Shipped for dev surface — `serve_dev_page.py` body-edit panel replaces the plain textarea with a CodeMirror 6 editor loaded via ESM CDN (`esm.sh`), pre-populated with raw Markdown. Write path unchanged (`POST /api/companion/workspace/body`). No autosave. No production bundling yet (#1329). |
| CodeMirror 6 adapter spike | Spike only — `companion_ui/spikes/codemirror_adapter.py`; adapter contract proven, raw-text round-trip across all Obsidian fixtures (#1305 / PR #1326). Decision: defer full production adoption until npm/browser frontend module exists. |
| Milkdown / MDXEditor rich-editor spikes | Spike only — test-only adapters in `tests/companion_ui/rich_editor_spike_adapters.py` (#1306 / PR #1327). Decision: defer both until real browser runtime round-trip is proven. |
| Canvas Core models and session API | Shipped — `companion_ui/canvas_core/`, `app/api/routes/canvas.py` behind `CANVAS_ENABLED` |
| Canvas Suggestion Flow models | Shipped — `companion_ui/canvas_suggestion_flow/` (browser integration pending) |
| Panel models and confirmation service | Shipped — `companion_ui/panel/`, `app/panel/confirmation.py`, `POST /api/panel/confirm` |
| Canvas governance pipeline (stub replaced) | Shipped — `app/panel/canvas_pipeline.py`, wired into `app/api/routes/canvas.py` |
| Panel correction path | Shipped — `app/panel/confirmation.py` (correction.enabled=true now supported) |
| Product modes | Shipped in dev/staging shell — Find, Reorient, Resurface, and Act render against runtime-owned workspace/Panel state |
| Production Companion UI | **Not yet shipped** — production hardening remains pending |
| Auth / TLS / reverse proxy for Companion UI | **Not yet shipped** — deferred until workspace state endpoint ships |
| PWA packaging | **Not yet shipped** |
| Native app wrapper (Tauri, Electron, etc.) | **Not yet shipped** |

---

## 6. Next Implementation Slice

The immediate next slices are defined in `docs/ROADMAP.md` under "Companion UI integration
roadmap (2026-05-19)". The ordering reflects the integration-first posture: existing Canvas Core,
Panel, and Suggestion Flow model foundations are shipped and must not be reimplemented.

Summary of next work:
1. Docs: define post-dev-server implementation roadmap
2. Complete remaining workspace shell gaps (stable selectors, error state, dev marker)
3. Docs: define workspace state read-side API contract (aggregate endpoint for browser)
4. Runtime: expose workspace state endpoint
5. Docs: define local auth/trusted-device access model (gate: after #4 merges)
6. Bind browser shell to workspace state endpoint
7. Docs: decide editor integration for shipped Canvas API (gate: after #3)
8. Canvas/Panel/Suggestion Flow browser integration (wire existing models, not rebuild)
9. Production hardening and packaging follow-ups after the dev/staging product modes

All future Companion UI implementation must be preceded by a bounded GitHub issue.
Docs-first where contracts are undecided. Agents must rescope to integration if they discover
an already-shipped model.

For operational detail on the shipped dev server, see
`companion-ui/docs/REAL_NOTE_WORKSPACE_DEV_PAGE.md`.

The next browser integration contracts are:

- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` — read-side workspace aggregate for artifact,
  Canvas, Panel, suggestion, and guard state.
- `companion-ui/docs/CANVAS_BROWSER_EDITOR_DECISION.md` — interim Canvas browser editor primitive
  and full-body edit delivery decision.
- `companion-ui/docs/PANEL_STATE_DISCOVERY_DELTA.md` — Panel browser discovery gap analysis.

---

## 7. Long-Term Options

These are the evaluated medium- and long-term directions. None are committed as shipped work.

### PWA (Progressive Web App) — likely medium-term path

A PWA is the most natural evolution of the local-first web app architecture:

- No separate native distribution required.
- Installable from the browser on macOS, iPadOS, Windows, and other platforms.
- Offline and caching behaviors available via service worker when needed.
- Compatible with localhost-first and Tailscale access model.

PWA is the preferred medium-term packaging path. No PWA implementation is shipped yet.

### Desktop wrapper (Tauri, Electron) — possible later, packaging only

A desktop wrapper such as Tauri or Electron may be evaluated later, but only as a packaging layer
over the same web application:

- The web application remains the primary artifact. The wrapper adds OS-level chrome only.
- No wrapper is shipped now.
- If evaluated, prefer Tauri for its smaller binary footprint and Rust-based system integration.
- A desktop wrapper does not change the vault-boundary rules: even inside a desktop wrapper,
  Companion UI must not read vault files directly.

### Native apps (iPadOS, macOS, Windows) — not the current target

Separate native apps for iPadOS, macOS, or Windows are not the current target architecture.

- They are a future option only if PWA capabilities prove insufficient for a specific use case.
- They would require separate codebases, separate distribution, and separate maintenance overhead.
- This decision must be revisited explicitly in a future owner-doc update if native apps are
  reconsidered. Do not treat "native apps are an option" as permission to start building them.

### Obsidian plugin integration — integration surface only

If Obsidian plugin integration is considered later, it is an integration surface for specific
Obsidian-resident interactions (e.g., in-vault Panel rendering), not the primary Companion UI
architecture.

- The standalone web application remains the primary architecture even if an Obsidian plugin
  integration is added alongside it.
- Plugin integration does not change the vault-boundary rules.
- Plugin integration is deferred and is not yet designed or specified.

---

## 8. Non-Goals and Anti-Patterns

The following must not happen under this architecture:

| Anti-pattern | Why it violates this architecture |
|---|---|
| Building separate native apps now | Native apps are not the current target; build the web app first |
| Companion UI reading vault files directly | The runtime API is the only vault access path |
| Companion UI writing vault files directly | Writes must route through the governed runtime execution path |
| Companion UI selecting or hardcoding named vaults | Vault binding is owned by the runtime, not the UI |
| Exposing the dev server to the public internet | No auth/TLS/reverse-proxy exists; exposure would be insecure |
| Conflating the browser dev server with production UI | They are categorically different; do not ship the dev server as production |
| Mixing vault paths into browser-side logic | Vault paths must never reach the browser |
| Using real vaults as automated test fixtures | Tests must use fake clients, fixtures, or `tmp_path` |

---

## 9. Relationship to Other Docs

| Document | Relationship |
|---|---|
| `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md` | Cognitive boundary and integration boundary rules; upstream of this doc |
| `companion-ui/docs/REAL_NOTE_WORKSPACE_DEV_PAGE.md` | Operational detail for the dev page: ports, env vars, UAT steps |
| `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` | Read-side aggregate contract for browser workspace state |
| `companion-ui/docs/LOCAL_ACCESS_MODEL.md` | Localhost, LAN, Tailscale, token, and CSRF access posture |
| `companion-ui/docs/CANVAS_BROWSER_EDITOR_DECISION.md` | Canvas browser editor primitive and edit delivery decision |
| `companion-ui/docs/PANEL_STATE_DISCOVERY_DELTA.md` | Panel discovery delta against the workspace aggregate |
| `companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md` | Panel surface contract; vault write-back boundary rules |
| `companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md` | Canvas surface contract; in-session authority model |
| `docs/COMPANION_UI_PRODUCT_SPEC.md` | Product mode model (Find/Reorient/Resurface/Act); upstream authority |
| `docs/ENVIRONMENTS.md` | Environment model, vault scoping, API port conventions |
| `docs/STATUS.md` | Current shipped state across the runtime |
| `docs/ROADMAP.md` | Strategic sequencing and forward-looking delivery framing |

---

## 10. Roadmap and Status Note

`docs/ROADMAP.md` and `docs/STATUS.md` are not updated in this PR. Issue #1098 (or the next
roadmap/status refresh cycle) should incorporate this target architecture decision into the
roadmap/status framing for Companion UI.

---

## Acceptance Criteria (Issue #1102)

- [x] A Companion UI target architecture doc exists at
  `companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md`.
  Verify: doc writeback at `companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md`
- [x] The doc clearly states that the primary target is a local-first web app.
  Verify: section 1 above.
- [x] The doc clearly states that native apps are optional future wrappers, not the current primary
  architecture.
  Verify: sections 1 and 7 above.
- [x] The doc states Companion UI accesses notes only through the runtime API.
  Verify: section 2 above.
- [x] The doc states Companion UI does not choose or hardcode named vaults.
  Verify: sections 2 and 3 above.
- [x] The doc identifies the minimal browser dev server as the next implementation slice.
  Verify: section 6 above.
- [x] The doc is linked from the companion-ui/docs README.
  Verify: `companion-ui/docs/README.md` updated.
