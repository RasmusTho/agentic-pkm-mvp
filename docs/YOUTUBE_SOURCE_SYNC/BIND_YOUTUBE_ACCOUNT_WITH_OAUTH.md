---
name: Bind YouTube Account with OAuth
description: Minimal-scope OAuth 2.0 account binding (device flow primary, loopback secondary), encrypted token store behind secret references, reconnect/disconnect, legible degradation.
task_id: YSS-02
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Secrets and private bindings"
parent_capability: YouTube Source Sync
prerequisites: [YSS-01]
depends_on: [ESTABLISH_SOURCE_REGISTRY_AND_SETTINGS.md]
can_parallelize_with: [ESTABLISH_DURABLE_ACQUISITION_REQUESTS.md]
---

# Bind YouTube Account with OAuth

## Purpose

Private playlists, the inbox UX, and Liked Videos require the user's consent via OAuth. This task
lands the single account-binding seam every authenticated surface uses — with secrets that never
touch the repo, vault, settings values, logs, events, or receipts.

## What This Task Does

1. New module `app/knowledge_acquisition/youtube_oauth.py` implementing, over the existing `httpx`
   dependency (no new packages, no Google SDK):
   - **Device authorization grant (primary):** `start_device_flow()` → `{verification_url,
     verification_url_complete, user_code, interval}`; `poll_device_flow()` until
     granted/denied/expired. Headless-friendly; the complete-URL variant means the user clicks a
     link or scans a QR — no typing required.
   - **Loopback installed-app flow (secondary):** authorization-code + PKCE against an exact
     `http://127.0.0.1:<ephemeral>` redirect for same-host setups. Start and completion both reject
     any other scheme/host, missing or invalid port, userinfo, query, or fragment. OAuth `state`
     validated; tokens never
     appear in URLs beyond the provider's own redirect params.
   - Scope: exactly `https://www.googleapis.com/auth/youtube.readonly`. Refresh, expiry-aware
     access-token provider `TokenProvider.get_access_token()` with single-flight refresh.
2. **Encrypted token store** `app/knowledge_acquisition/youtube_token_store.py`: AES-256-GCM
   (existing `cryptography` dependency, mirroring `app/heimdal/raw_store.py` key discipline), key
   from `YOUTUBE_TOKEN_STORE_KEY` (32 bytes; absent or valid-but-wrong key ⇒
   `TokenStoreKeyMissingError`, fail closed, never plaintext). An authenticated encrypted canary
   binds the key to the aggregate; legacy no-canary files authenticate every existing record before
   upgrade, so a wrong key cannot create a mixed-key store. Store file path is an app-local binding
   defaulting under the channel runtime dir; never inside a vault, never tracked.
3. **Account binding record** (non-secret) in the registry substrate: binding id, provider channel
   id, display label, connected/degraded state, scopes, obtained_at. Client credentials resolve
   from `YOUTUBE_OAUTH_CLIENT_ID`/`YOUTUBE_OAUTH_CLIENT_SECRET` env (host secret-provisioning
   boundary); their *values* are never persisted or printed.
4. **Degradation + lifecycle:** revoked/expired/invalid_grant map to `auth_revoked`/`auth_expired`,
   while rotated-refresh recovery maps to `auth_refresh_pending`, `auth_refresh_conflict`, or
   `auth_refresh_durability`, on both the binding and dependent sources (INV-YSS-4). Before each
   device-token poll, connect proves encryption-key and locked atomic-store readiness. POSIX store
   writes sync the staged file before atomic replacement and confirm the complete parent-directory
   chain through the filesystem root afterward, including first-use nested directories;
   Windows uses write-through replacement. Visible readback after a failed barrier is not accepted
   as crash-durable until a fresh barrier succeeds. A returned grant is
   immediately encrypted under an opaque pending-journal id before the fallible identity probe or
   binding work. Exact encrypted-record readback treats a lost write acknowledgement as durable
   success, so a landed pending journal or canonical reconnect token is never revoked as though its
   write failed. Identity/journal failure is provider-compensated when revocation is authoritative;
   otherwise the pending authority remains encrypted and locally retryable. For a pending-only
   first connect, canonical token durability precedes binding-row creation and the `connected`
   claim. If an older canonical predecessor already exists, its row is recovered before a distinct
   later grant may replace it, so failed row recovery preserves both authorities. Pending cleanup
   begins only after the matching binding row is visible. A deterministic first-connect candidate
   without that row retains its per-attempt retry journal, and a later consent gets a distinct
   journal instead of overwriting the earlier grant. Retry uses encrypted display metadata to re-attempt the same deterministic binding
   create without minting another grant; a delayed exact row converges and a different same-channel
   winner remains a non-destructive conflict. Later cleanup may leave only a redundant encrypted
   copy on crash. Promotion and cleanup stay within pending/channel/binding lifecycle authority. The
   pending ciphertext records its exact target, predecessor refresh authority, and
   next generation before canonical write. Retry cleans only the same refresh authority, promotes
   only over that unchanged predecessor, and preserves a same-channel token mismatch as
   `pending_conflict` without deletion or provider revocation; channel identity alone is not grant
   identity.
   Google's [documented refresh response](https://developers.google.com/identity/protocols/oauth2/web-server#offline)
   renews the access token and retains the stored refresh credential. Defense in depth still treats
   an unexpected different `refresh_token` as rotation: preflight precedes `/token`, the response is
   journaled encrypted before canonical promotion, and a write failure recovers on the next access
   only over the proven predecessor generation. Before provider compensation, the encrypted
   journal is durably marked non-promotable; authoritative revocation advances that marker to
   compensated before best-effort cleanup, so crash residue can never restore revoked authority.
   Pending/conflicting refresh authority durably
   degrades the account binding and every dependent source, without cursor mutation, and blocks
   reconnect/disconnect provider actions until safely resolved. Failure classification and the
   matching binding/source degradation remain inside the same per-binding lifecycle lock, so a
   stale actor cannot overwrite another service instance's completed recovery. A reconnect never cleans its
   pending journal merely because canonical ciphertext is visible: the binding row must also be
   durably `connected` before cleanup.
   Connect, reconnect, refresh, and disconnect are
   serialized per binding across service instances and runtime processes sharing the channel token
   store. The app-local lock filename is a digest of the binding id and the private lock file
   contains no account identifier or secret. A portable store-wide lock serializes aggregate-file
   mutations across distinct bindings on POSIX and Windows, while concurrent first connects
   re-resolve provider identity under shared authority. First-connect binding ids are deterministic
   per provider channel. A create exception rolls forward when the row is visible; negative read
   snapshots preserve the encrypted credential because a delayed commit may still appear, and retry
   converges on the same candidate id. `disconnect()` revokes at `oauth2.googleapis.com/revoke`
   before local teardown. Only Google's documented HTTP 400 `invalid_token` outcome (already expired
   or revoked) permits teardown with `revoked=false`; `invalid_request`, intermediary/unknown 4xx,
   redirects, transport failures, and every other unproven outcome preserve the encrypted token and
   dependent-source state for retry/reconciliation. Every credential-bearing OAuth POST disables
   redirect following at the request site. Teardown deletes the token record, disables dependent
   sources with `auth_disconnected`, and deletes no acquired artifacts. `reconnect()` re-runs consent
   onto the same binding when the provider channel id matches.
5. Redaction: all exception/log/serialization paths sanitize provider responses (status + an
   allowlisted OAuth error enum only); no token, code, or client secret in any emitted string.

## Concretely

```
$ python -m app.cli youtube-auth connect --device --json
{"verification_url_complete": "https://www.google.com/device?user_code=XXXX-XXXX", "user_code": "XXXX-XXXX", ...}
# user approves in any browser; poll completes:
{"status": "connected", "account": {"binding_id": "…", "channel_title": "…"}}   # no tokens in output
$ python -m app.cli youtube-auth status --json
{"status": "connected", "scopes": ["…/youtube.readonly"], "token_store": "encrypted", "reason_code": null}
```

## Why This Matters

A leaked refresh token is a standing credential to the user's account; a plaintext fallback or a
token in a log line is the one defect class this feature must never ship. Equally: revoked consent
must read as a clear degraded state, not as "all playlists are suddenly empty" (which would poison
cursors and mass-noop the queue).

## Acceptance Criteria

- [ ] Device flow completes against a stubbed provider and persists only through the encrypted
      store; the token file is unreadable without the key and carries no plaintext token bytes.
      Verify: `tests/knowledge_acquisition/test_youtube_oauth.py::test_device_flow_persists_encrypted_only`
- [ ] Loopback flow validates `state` and PKCE verifier; a tampered state is refused.
      Verify: `tests/knowledge_acquisition/test_youtube_oauth.py::test_loopback_flow_rejects_tampered_state`
- [ ] Missing `YOUTUBE_TOKEN_STORE_KEY` with an existing binding fails closed as
      `auth_key_missing` — no plaintext read/write path exists.
      Verify: `tests/knowledge_acquisition/test_youtube_oauth.py::test_missing_store_key_fails_closed`
- [ ] Revoked consent (provider `invalid_grant`) yields `auth_revoked` on binding and dependent
      sources, mutates no cursor, and never reports an empty-success poll.
      Verify: `tests/knowledge_acquisition/test_youtube_oauth.py::test_revoked_auth_degrades_without_cursor_mutation`
- [ ] No secret value appears in logs, exceptions, events, receipts, or `--json` output across
      connect/status/refresh/failure paths (scans captured output for planted sentinel secrets).
      Verify: `tests/knowledge_acquisition/test_youtube_oauth.py::test_no_secret_in_logs_events_receipts_or_json`
- [ ] Disconnect revokes, removes the token record, disables dependent sources with
      `auth_disconnected`, and leaves acquired artifacts/raw records untouched.
      Verify: `tests/knowledge_acquisition/test_youtube_oauth.py::test_disconnect_revokes_without_deleting_artifacts`
- [ ] Scope requested is exactly `youtube.readonly` (enforcement asserted at the request-building
      production call site).
      Verify: `tests/knowledge_acquisition/test_youtube_oauth.py::test_minimal_scope_requested_at_call_site`

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_youtube_oauth.py`
- `pytest -q -m "not pg"` (secret handling is hot-path; run the full default suite)
- `ruff check app tests && mypy app`

## Out of Scope

Data API resource calls (YSS-03), UI surfaces (YSS-11), CLI beyond the two commands shown
(YSS-10 owns the full CLI family), any secret-manager integration beyond the documented env/
Keychain-bootstrap boundary.

## Restart / Durability Posture

Bindings and encrypted tokens survive restart on disk (app-local, per channel). A restart with a
missing key, wrong key, or unauthenticatable encrypted aggregate degrades to `auth_key_missing` —
visible, fail-closed, recoverable by re-provisioning the correct key; consent is not silently
re-requested. In-flight device-flow sessions do not survive
restart; the user simply restarts the connect step (the UI/CLI says so).

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Secrets and private bindings / Egress posture / Reason codes`
- `docs/LOCAL_SECRET_PROVISIONING/README.md` (host secret boundary)
- `docs/SECURITY.md`, `docs/adr/ADR-0046-inv-ef1-public-private-seam.md`
- `docs/YOUTUBE_SOURCE_SYNC/OPERATOR_RUNBOOK.md :: Create the OAuth client`

## Related GitHub Issues

One issue. TCD hint: Opus / high — auth + external API + secret handling is exactly the
escalation class in `AGENTS.md :: Total Cost of Development`; defect blast radius is a standing
account credential.
