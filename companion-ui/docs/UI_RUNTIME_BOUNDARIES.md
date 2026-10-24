# UI Runtime Boundaries

## Separation of concerns
- Cognition: human intent, reasoning continuity, and proposal interpretation.
- UI runtime: transient rendering/session state.
- Persistence/runtime integration: explicit writes via backend contracts.

## Rules
- UI-local state is ephemeral by default.
- Durable state must be explicitly persisted and vault-compatible.
- Do not add hidden app databases for meaning-bearing artifacts.
- Do not implement production backend integration inside this workspace lane.

## Cognitive boundary constraints
- Document remains the cognitive anchor.
- Overlays preserve continuity and provenance visibility.
- AI remains contextual rather than dominant.
- No runtime contract should require chat-centric, dashboard-centric, or notification-centric interaction.
- No interface contract should depend on hidden semantic state for continuity recovery.

## Integration boundary (future-safe)
- Keep transport and event contracts explicit.
- Keep proposal workflows staged-first.
- Keep provenance visible at interaction time, not only in audit trails.
- Keep interruption and re-entry semantics explicit at the interface boundary.

## Single-origin API proxy (#2125)
- The existing Companion picker opts into a scoped handoff on `POST /api/companion/vault/select`.
  The API resolves the selected filesystem identity to exactly one registered binding after the
  compatibility rebind, authenticates the caller, and mints an opaque selection. A successful
  explicit selection replaces the browser's `companion_context_session` session cookie. It is
  HttpOnly, SameSite=Strict, and has no persistent expiry; it contains no path or principal data.
  On successful explicit `/vault/select` or `/vault/initialize` only, the gateway moves the returned
  `context_selection_id` into `Set-Cookie` and omits that credential field (including its nested
  initialization-context copy) from browser-facing JSON. All non-credential payload fields and
  upstream errors retain their runtime meaning. This is a route-specific transport handoff, not
  generic JSON rewriting. The gateway keeps no shared session state. On page navigation, fragments,
  and browser API reads,
  it forwards this opaque value as `X-Active-Context-Session` through a request-local HTTP adapter.
  Explicit `X-Active-Context-*` headers retain precedence, including blank carriers, and the API
  authenticates and resolves them. The gateway derives no principal or binding authority.
- Scoped runtime routes (`/api/search/scoped`, `/api/ask/scoped`, and
  `/api/companion/vault/notes/scoped`) enforce the opaque bearer. The consumed Companion read
  `/api/companion/vault/notes/scoped` is explicitly allowlisted in the single-origin gateway.
  Missing, stale, or stripped carriers return `reselection_required`; there is no carrier-free
  retry. Other Companion production reads forward the same session to their request-context
  dependency, including server-rendered page and fragment reads. A stale page session is checked
  before page-triggered work and renders the existing picker. Browser read failures visibly ask
  for reselection. The old cookie is retained: neither a sole authorized binding, a matching
  default, nor API restart can silently mint or choose a replacement. A new browser without stale
  explicit intent may independently use the ordinary default journey.
- Compatibility mutations use distinct same-origin routes (`/api/companion/capture/compatibility`
  and `/api/companion/note/save/compatibility`). Before an explicit capture or note edit, the browser
  reads the scoped notes route once and passes its opaque `X-Compatibility-Write-Precondition`
  response header to the compatibility mutation. A failed read or missing precondition stops the
  mutation. The gateway forwards the proof unchanged, and does not translate the session cookie
  on compatibility mutation or selector-bridge routes; explicitly supplied session headers remain
  intact and are refused by the pre-05C seal. Other writes keep that seal and WriteGuard.
- First-vault initialization uses the existing in-band confirmation gesture, obtains the
  authenticated single-use `/api/companion/vault/initialize/bootstrap` precondition, and executes
  initialization with that exact token. The successful server-owned scoped handoff sets the same
  session cookie, so the next read resolves the new binding. An explicit retry after a failed or
  lost handoff retains the exact token in page memory; it never automatically repeats an effect
  or remints a bootstrap token. Bootstrap tokens select no general write target.
- The browser only ever talks to the UI origin. The UI server proxies an
  **explicit allowlist** of consumed routes (not a `/api/companion/*` wildcard)
  through to the configured runtime API base (`COMPANION_API_BASE_URL`, default
  `http://127.0.0.1:18001`), so a remote device that can reach the UI origin
  never needs direct access to the runtime origin. The forwarded routes are the
  ones the served page actually calls — orientation, workspace
  (read/body/update), vault (notes/select/initialize/reload/settings),
  authenticated first-vault initialize/bootstrap and scoped notes, vault-related, capture, note save, TTS (status/plan/synthesize and the audio
  pattern), the canvas co-author pattern, and the operator status/health/settings/events
  routes — defined in `_GET_PROXY_PATHS`/`_POST_PROXY_PATHS` (plus a small set of
  `_GET_PROXY_PATTERNS`/`_POST_PROXY_PATTERNS` regexes). A route outside the
  allowlist (e.g. `GET /api/companion/vault-browser`) is **not** proxied. This
  removes the "wrong device" failure mode at the root; the UI
  disambiguation/fallback (#2124) remains as the graceful fallback when no
  proxy target is reachable.
- The proxy is **transport only**. It always forwards the runtime status code
  unchanged — a runtime `503` stays a `503` and renders as the #2123 "Vault
  unreachable" state. Error **bodies** are forwarded verbatim only when the
  runtime body parses to a JSON object (e.g. the canvas co-author `409`
  `{"status":"routed_to_panel", ...}` handoff body survives to the page); a
  non-JSON or non-object error body is wrapped in the diagnostic
  `runtime_api_error` shape (status preserved). The proxy never re-classifies,
  caches, or rewrites the status code. Apart from the two successful picker credential-to-cookie
  handoffs described above, it does not rewrite JSON-object bodies: the server declares, the UI
  renders.
- The runtime API target is configuration; it does not relax operator
  bind/exposure posture. Remote exposure of the UI origin remains an explicit
  operator choice, independent of this proxy path.
- Production devUI transport is a separate, stricter two-route allowlist (#4841): exact GET
  `/api/devui/overview` with no query and exact GET `/api/devui/focus` with one nonempty
  `subject` query. Unknown/child devUI paths, duplicate or extra query keys, wildcards, and
  POST/PUT/PATCH/DELETE are denied. The route is enabled only from an explicit all-loopback
  `COMPANION_UI_BIND_HOST` declaration and requires a loopback-local browser `Host` with no
  forwarded identity, including `Via`; it never treats the inside-container peer as loopback
  authority.
- For those two reads, the UI server creates a fresh request from only
  `COMPANION_API_BASE_URL`, the exact path, and the validated query. It copies no inbound `Host`,
  API key, authorization, forwarding, Via, client-IP, or proxy header, and returns the upstream
  status and JSON body unchanged. In the transport contract's compact wording, #4841 adds
  no page/static route. It itself adds no FastAPI page/static route, packaged
  page/asset, or browser fallback. The #4836 candidate adds only Companion-owned
  `/devui/overview`, `/devui/focus?subject=...`, and `/devui/assets/*` presentation routes behind
  the same gateway admission. It does not add a FastAPI presentation route or widen the exact two
API GETs. The complete delivered asset inventory is Git-tree-bound by its
`yggdrasil-constrained-reuse.v1` manifest; production deployment and owner acceptance remain
separate later gates.

## Control-action register

The UI is a **transport** of human intent. The same intent may arrive on any valid surface — UI,
CLI, a direct hand-edit of `settings/local.md`, or (later) MCP/API. The server-side governed seam
is the single classification and enforcement point; the UI never re-derives authority.

### Tier 1 — Vault binding (pre-init)

These actions happen before a vault is initialized and selected. They route through app-local / WSP
binding, not vault-scoped governance.

| Action | API route | Gov/EXE routing | Receipt |
|--------|-----------|-----------------|---------|
| Vault select | `POST /api/companion/vault/select` with explicit scoped handoff | WSP compatibility rebind + authenticated ephemeral selection | Scoped handoff (never logged) |
| Vault init | `POST /api/companion/vault/initialize` | WSP init (app-local) | None (init logged) |
| Vault reload | `POST /api/companion/vault/reload` | WSP refresh | None |

The UI is the human's only interaction surface at this stage (the vault does not yet exist).
No write guard applies to the binding itself.

### Tier 2 — Runtime gating (post-init, authority-bearing)

These writes reconfigure whether the watcher/indexing runtime runs. They are **authority-bearing**
in the proportional sense (#1881 tiers): reversible, local, no external boundary — so **no
approval loop** (consistent with a human being able to flip the same flag via a direct
settings-file hand-edit; the watcher routes the delta through the same gate before runtime
acceptance). The governed seam applies the WriteGuard health-gate and emits an actor-tagged receipt.

| Setting key | Effect | Authority class | Governed seam |
|-------------|--------|-----------------|---------------|
| `enableVaultWatcher` | Gates watcher startup (`registry.py:734`, `config.py:92`) | Authority-bearing | WriteGuard + `SettingsWriteReceipt` |
| `enableAutoIndexing` | Gates auto-indexing runtime | Authority-bearing | WriteGuard + `SettingsWriteReceipt` |
| `youtubeSync.enabled` | Master switch for the YouTube Source Sync capability (YSS-01, #3916) | Authority-bearing | WriteGuard + `SettingsWriteReceipt` |
| `youtubeSync.runnerEnabled` | Gates whether this machine runs the YouTube sync loop (the DB lease remains the hard guard) | Authority-bearing | WriteGuard + `SettingsWriteReceipt` |

**Governed seam** (`app/vault/settings_service.py :: SettingsService.update_setting`):
1. `RUNTIME_GATING_SETTINGS` classifies the key as authority-bearing.
2. `DEFAULT_WRITE_GUARD.assert_writes_allowed()` is called; raises `SettingsWriteError` if
   `state in WRITE_BLOCKED_STATES` (i.e. `safe_mode` or `unhealthy`).
3. The markdown write is applied to the setting's owning file (`settings/local.md` or
   `settings/youtube.md`).
4. A `SettingsWriteReceipt(key, value, surface, actor, timestamp, is_runtime_gating=True)` is
   emitted and logged at INFO level.

**Receipt covers the API door (only):**
- **API/UI origin** (`surface='api'`, `actor='human'`): receipt emitted immediately
  (sole production caller: `app/api/routes/companion.py:826`).
- **CLI origin** (`surface='cli'`): NOT yet wired. The `app.cli vault` group exposes `init`/`preflight`
  only; no command toggles runtime-gating settings through the seam. Addable when a consumer exists.
- **File-originated origin** (`surface='file'`): wired for the runtime-gating keys owned by
  `settings/local.md` and `settings/youtube.md`. The watcher calls the same governed seam; a
  blocked delta is not accepted as runtime state and an allowed delta emits the durable receipt.

**Valid origins of the same seam:** UI (via `POST /api/companion/vault/settings`, wired), watcher
file deltas (`surface='file'`, wired), CLI (existing `app.cli vault` commands — NOT yet wired, see
above), and future MCP/API surfaces.

### Tier 3 — External-boundary enable

TTS provider enable crosses an external boundary (EBF applies). Not re-decided here; governed by
`#2086` / `#1699`.

### Server-authoritative classification rule

The UI never re-derives authority from the server response. Classification lives server-side in
`RUNTIME_GATING_SETTINGS` (settings_service.py). If a key is promoted to runtime-gating in the
future, only the server-side constant and the governed seam need to change.

## Related docs
- `SYSTEM_OVERVIEW.md`
- `EVENT_MODEL_SUMMARY.md`
- `CONTINUITY_AND_DECAY.md`
- `TEMPORAL_PROVENANCE.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md :: Runtime control actions`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_RUNTIME_CONTROL_ACTION_BOUNDARY.md`
