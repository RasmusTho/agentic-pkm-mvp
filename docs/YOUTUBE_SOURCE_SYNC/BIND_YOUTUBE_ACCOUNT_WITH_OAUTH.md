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
   - **Loopback installed-app flow (secondary):** authorization-code + PKCE against a
     `127.0.0.1:<ephemeral>` redirect for same-host setups. OAuth `state` validated; tokens never
     appear in URLs beyond the provider's own redirect params.
   - Scope: exactly `https://www.googleapis.com/auth/youtube.readonly`. Refresh, expiry-aware
     access-token provider `TokenProvider.get_access_token()` with single-flight refresh.
2. **Encrypted token store** `app/knowledge_acquisition/youtube_token_store.py`: AES-256-GCM
   (existing `cryptography` dependency, mirroring `app/heimdal/raw_store.py` key discipline), key
   from `YOUTUBE_TOKEN_STORE_KEY` (32 bytes; absent key ⇒ `TokenStoreKeyMissingError`, fail
   closed, never plaintext). Store file path is an app-local binding defaulting under the channel
   runtime dir; never inside a vault, never tracked.
3. **Account binding record** (non-secret) in the registry substrate: binding id, provider channel
   id, display label, connected/degraded state, scopes, obtained_at. Client credentials resolve
   from `YOUTUBE_OAUTH_CLIENT_ID`/`YOUTUBE_OAUTH_CLIENT_SECRET` env (host secret-provisioning
   boundary); their *values* are never persisted or printed.
4. **Degradation + lifecycle:** revoked/expired/invalid_grant map to `auth_revoked`/`auth_expired`
   reason codes on the binding and dependent sources (INV-YSS-4). `disconnect()` revokes at
   `oauth2.googleapis.com/revoke`; a transport/408/429/5xx failure returns a sanitized retryable
   `api_unavailable` degraded result and retains encrypted token authority without changing sources
   or acquired artifacts. Success or permanent provider rejection deletes the token record and disables
   dependent sources with `auth_disconnected`. `reconnect()` re-runs consent onto the
   same binding when the provider channel id matches.
5. Redaction: all exception/log/serialization paths sanitize provider responses (status + error
   class only); no token, code, or client secret in any emitted string.

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
- [ ] Transient provider revoke failure retains encrypted retry authority and leaves source
      cursors and acquired artifacts untouched; permanent provider rejection keeps local teardown.
      Verify: `tests/knowledge_acquisition/test_youtube_oauth.py::test_disconnect_preserves_token_when_provider_revoke_fails` and `tests/knowledge_acquisition/test_youtube_oauth.py::test_disconnect_permanent_provider_error_keeps_existing_local_teardown`
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

Bindings and encrypted tokens survive restart on disk. The encrypted token file and the shared
connect/reconnect admission lock live in a private `knowledge_acquisition/` directory under the
canonical channel runtime-artifact root, independent of process CWD or linked worktree. The writer
refuses path escape, symlink traversal, non-sticky shared writable runtime directories,
non-current-user-owned/non-`0700` private directories, and non-current-user-owned/non-`0600` state
files before credential or admission effects. The shipped sticky `1777` channel scratch mount is a
container/bootstrap boundary only; credential and admission state stays in its private child.

V1 admits one connect or reconnect transition at a time across processes and permits at most one
durable YouTube account binding. Admission happens before provider egress and remains held through
token and binding persistence. Tokens remain the first durable write, but only a matching durable
account-binding row makes one positive authority: status, refresh, and reconnect fail closed on an
unbound or identity-mismatched token. A failed or indeterminate binding write leaves its token
non-authoritative; the next admitted start performs one bounded reconciliation pass that deletes
only token ids proven unbound by durable binding truth and preserves every valid bound credential.

A restart with a missing key degrades to `auth_key_missing` — visible, fail-closed, recoverable by
re-provisioning the key; consent is not silently re-requested. In-flight device-flow sessions do not
survive restart; after process-held admission is released, the user restarts the connect step (the
UI/CLI says so).

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Secrets and private bindings / Egress posture / Reason codes`
- `docs/LOCAL_SECRET_PROVISIONING/README.md` (host secret boundary)
- `docs/SECURITY.md`, `docs/adr/ADR-0046-inv-ef1-public-private-seam.md`
- `docs/YOUTUBE_SOURCE_SYNC/OPERATOR_RUNBOOK.md :: Create the OAuth client`

## Related GitHub Issues

One issue. TCD hint: Opus / high — auth + external API + secret handling is exactly the
escalation class in `AGENTS.md :: Total Cost of Development`; defect blast radius is a standing
account credential.
