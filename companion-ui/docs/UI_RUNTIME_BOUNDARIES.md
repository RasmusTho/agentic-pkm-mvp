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

## Related docs
- `SYSTEM_OVERVIEW.md`
- `EVENT_MODEL_SUMMARY.md`
- `CONTINUITY_AND_DECAY.md`
- `TEMPORAL_PROVENANCE.md`
