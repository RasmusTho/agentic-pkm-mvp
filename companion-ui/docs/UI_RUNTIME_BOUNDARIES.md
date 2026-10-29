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
  The API freezes the selected canonical filesystem identity before the compatibility rebind,
  selects that exact root, revalidates its physical identity, and matches exactly one registered
  binding before minting an authenticated opaque selection. Retargeting a filesystem alias while
  rebind waits cannot redirect the handoff to a different binding. A successful
  explicit selection replaces the browser's `companion_context_session` session cookie. It is
  HttpOnly, SameSite=Strict, and has no persistent expiry; it contains no path or principal data.
  On successful explicit `/vault/select` or `/vault/initialize` only, the gateway moves the returned
  `context_selection_id` into `Set-Cookie` and omits that credential field (including its nested
  initialization-context copy) from browser-facing JSON, including partial successful responses
  that lost the top-level field. It also returns `X-Companion-Scoped-Handoff`, a non-authority digest
  of the transported bearer bytes. All non-credential payload fields, statuses, and upstream errors
  retain their runtime meaning. This is a route-specific transport handoff, not generic JSON rewriting. The gateway keeps no shared session state. On page navigation, fragments,
  and browser API reads, it forwards this opaque value as `X-Active-Context-Session` through a request-local HTTP adapter.
  Before select or initialize, the browser writes the nonsecret session cookie
  `companion_context_intent=pending` and pauses content requests. A successful handoff records its
  expected transport digest in that cookie and must pass one strict scoped read before the client
  accepts it or clears its retained bootstrap token. On later requests, a pending, missing, or
  mismatched bearer becomes a blank explicit selection header, so an old valid A cookie cannot
  substitute for a lost B handoff. Browser storage failure is a visible refusal before selection.
  This intent marker and digest grant no authority; the API still authenticates and resolves the
  actual opaque bearer. Explicit `X-Active-Context-*` headers retain precedence, including blank
  carriers. The gateway derives no principal or binding authority.
- Scoped runtime routes (`/api/search/scoped`, `/api/ask/scoped`, and
  `/api/companion/vault/notes/scoped`) enforce the opaque bearer. The consumed Companion read
  `/api/companion/vault/notes/scoped` and authenticated
  `GET /api/companion/active-context/selection` inspection are explicitly allowlisted in the gateway.
  Missing, stale, or stripped carriers return `reselection_required`; there is no carrier-free
  retry. Other Companion production reads forward the same session to their request-context
  dependency, including server-rendered page and fragment reads. A stale page session is checked
  before page-triggered work and renders the existing picker. Browser content-read failures visibly
  ask for reselection and stop subsequent content requests until explicit picker success. The old
  cookie is retained: neither a sole authorized binding, a matching
  default, nor API restart can silently mint or choose a replacement. A new browser without stale
  explicit intent may independently use the ordinary default journey.
- The allowlisted `/api/operator/ask` alias targets `/api/ask/scoped` whenever an explicit
  session or override carrier is present, including a blank one. A carrier-free request retains
  `/api/ask`. Both paths preserve real client authentication and the presented carriers; there is
  no retry on the legacy twin after a scoped refusal.
- Scoped page capture sends its opaque context bearer and the rendered document's selected
  `target_binding_id` to `/api/companion/capture/scoped`. Session liveness is checked first; the
  retained rendered target is never replaced from a newer cookie. The runtime requires selected
  membership, exact-context GOV authority and the shared binding effect window. A stale document
  therefore cannot write to a newly selected binding.
- Carrier-free capture and note edits retain distinct same-origin compatibility routes (`/api/companion/capture/compatibility`
  and `/api/companion/note/save/compatibility`). Before these compatibility writes, the browser
  uses the opaque `X-Compatibility-Write-Precondition` captured with that rendered document.
  For scoped pages, both note and orientation/capture producers obtain it through the existing scoped notes
  read with the same request-local adapter that loads the page, and capture its response header
  before later projection reads overwrite transport headers. It remains in document-local script
  state. A scoped page note save validates session liveness through the authenticated strict selection
  inspection, then sends the retained proof unchanged. It never refreshes proof from a mutable
  current cookie or automatically retries a rejected write. Missing or expired proof blocks the
  mutation and preserves the draft; recovery requires explicit reload/reselection.
  For a carrier-free configured page, the actual `/workspace` or `/orientation` API producer
  supplies the same existing proof after principal admission, while holding manager selection and
  compatibility ingress through content serialization. The first document response owns the proof,
  including a missing proof; later telemetry cannot substitute one. No scoped selection is minted.
  Real client IP and API-key context are forwarded even without cookies, including direct document
  API and compatibility-write paths. Proof readiness reads only existing qualified registry state
  after authentication; a missing registry or recovery artifact is never initialized or repaired
  by that probe. An unselected bridge retains its read projection without a write proof.
  An unauthenticated projection receives no write proof. These
  pages check liveness through the legacy notes read while retaining their original document proof;
  newly shared stale intent still refuses, and missing proof never falls back to a legacy write.
  If another tab selects B while an A document stays open, A's proof cannot authorize a B mutation: the existing
  compatibility ingress and binding/revision guard either finish an already-admitted A write on A
  or reject it after B commits. The gateway forwards the proof unchanged, and does not translate the session cookie
  on compatibility mutation or selector-bridge routes. The exact authenticated folder-discovery
  route `/api/companion/vault/browse` also omits cookie-derived selection: it lists picker folders,
  never vault content or a selected context. Its existing API authentication and filesystem
  containment checks still apply. Discovery remains available after stale-session refusal and can
  browse siblings of a live selected vault; only an explicit picker selection changes the retained
  session. Explicitly supplied session headers remain intact and are validated/refused by the
  applicable scoped-read dependency or pre-05C seal. Other writes keep that seal and WriteGuard.
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
  authenticated first-vault initialize/bootstrap and scoped notes, vault-related, capture, note save,
  TTS (status/plan/synthesize and the audio pattern), the canvas co-author pattern, and the operator status/health/settings/events
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

## Companion shared operations consumer (#5339)

The shell's Operations workspace uses the public same-origin operations client. Its action belongs to the active note header and the System Map index; the shared header guidance remains UI-local. Entry surfaces leave it closed, and the observer runs only while the human has opened the Operations view. Closing the view stops observation without cancelling native work. Its finite gateway
additions are `GET /api/operations/capabilities`, `GET /api/operations/receipts/{request_id}`,
`POST /api/operations`, `POST /api/operations/preconditions`, and the existing finite batch
preview/inspect/execute/cancel routes. Real client IP, API key and opaque selection carriers retain
the existing request-local forwarding path on every admitted operation route; no wildcard or
client-selected runtime origin is introduced.

The runtime capability inventory determines availability. Current qualified update/move/rename
batches use one server-frozen digest confirmation; preconditions observe native versions and never
execute or reserve effects. The UI owns selection and display only. It submits no raw policy,
delegation, store, source path or receipt authority, and never implements a per-item effect loop.
Source effect, durable receipt, conflict, refusal and derived convergence remain separate server
fields. Retained batch cancellation preserves completed receipts; verify/resume is available only
for runtime-declared pending/recoverable state under its original admission and uncancelled scope.
A lost effect response triggers receipt inspection, never automatic effect retry. URL references
carry only non-authority request/batch identities and digests so reload rehydrates durable state;
unavailable readback is explicitly unknown. This consumer is not capability-level GUI/MCP parity
acceptance; parent #5329 and the owner-doc promotion gate remain open.

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
