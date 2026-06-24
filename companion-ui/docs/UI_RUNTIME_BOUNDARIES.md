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
- The browser only ever talks to the UI origin. The UI server proxies an
  **explicit allowlist** of consumed routes (not a `/api/companion/*` wildcard)
  through to the configured runtime API base (`COMPANION_API_BASE_URL`, default
  `http://127.0.0.1:18001`), so a remote device that can reach the UI origin
  never needs direct access to the runtime origin. The forwarded routes are the
  ones the served page actually calls — orientation, workspace
  (read/body/update), vault (notes/select/initialize/reload/settings),
  vault-related, capture, note save, TTS (status/plan/synthesize and the audio
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
  caches, or rewrites the status code, and does not rewrite JSON-object bodies:
  the server declares, the UI renders.
- The runtime API target is configuration; it does not relax operator
  bind/exposure posture. Remote exposure of the UI origin remains an explicit
  operator choice, independent of this proxy path.

## Control-action register

The UI is a **transport** of human intent. The same intent may arrive on any valid surface — UI,
CLI, a direct hand-edit of `settings/local.md`, or (later) MCP/API. The server-side governed seam
is the single classification and enforcement point; the UI never re-derives authority.

### Tier 1 — Vault binding (pre-init)

These actions happen before a vault is initialized and selected. They route through app-local / WSP
binding, not vault-scoped governance.

| Action | API route | Gov/EXE routing | Receipt |
|--------|-----------|-----------------|---------|
| Vault select | `POST /api/companion/vault/select` | WSP binding (app-local) | None (binding logged) |
| Vault init | `POST /api/companion/vault/initialize` | WSP init (app-local) | None (init logged) |
| Vault reload | `POST /api/companion/vault/reload` | WSP refresh | None |

The UI is the human's only interaction surface at this stage (the vault does not yet exist).
No write guard applies to the binding itself.

### Tier 2 — Runtime gating (post-init, authority-bearing)

These writes reconfigure whether the watcher/indexing runtime runs. They are **authority-bearing**
in the proportional sense (#1881 tiers): reversible, local, no external boundary — so **no
approval loop** (consistent with a human being able to flip the same flag via a direct
`settings/local.md` hand-edit with no gate). The governed seam applies the WriteGuard
health-gate and emits an actor-tagged receipt.

| Setting key | Effect | Authority class | Governed seam |
|-------------|--------|-----------------|---------------|
| `enableVaultWatcher` | Gates watcher startup (`registry.py:734`, `config.py:92`) | Authority-bearing | WriteGuard + `SettingsWriteReceipt` |
| `enableAutoIndexing` | Gates auto-indexing runtime | Authority-bearing | WriteGuard + `SettingsWriteReceipt` |

**Governed seam** (`app/vault/settings_service.py :: SettingsService.update_setting`):
1. `RUNTIME_GATING_SETTINGS` classifies the key as authority-bearing.
2. `DEFAULT_WRITE_GUARD.assert_writes_allowed()` is called; raises `SettingsWriteError` if
   `state in WRITE_BLOCKED_STATES` (i.e. `safe_mode` or `unhealthy`).
3. The markdown write is applied to `settings/local.md`.
4. A `SettingsWriteReceipt(key, value, surface, actor, timestamp, is_runtime_gating=True)` is
   emitted and logged at INFO level.

**Receipt covers the API/CLI door (only):**
- **API/UI/CLI origin** (`surface='api'` or `'cli'`, `actor='human'`): receipt emitted immediately
  (sole production caller: `app/api/routes/companion.py:826`).
- **File-originated origin** (`surface='file'`): NOT yet wired. The watcher does NOT call the
  governed seam on a `settings/local.md` delta, so a human hand-editing that file produces no
  receipt. Closing this door is tracked by #2512.

**Valid origins of the same seam:** UI (via `POST /api/companion/vault/settings`), CLI (existing
`app.cli vault` commands), and future MCP/API surfaces. No new surfaces are added here.

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
