State: Pragmatic V1 operator contract. A narrow dev-only Inbox CLI is delivered; no broad CLI or Companion UI is delivered by V1.
Doc role: Operator runbook
Authority: Owns the currently delivered manual route for one YouTube account and one Inbox.

# YouTube Source Sync V1 — Operator Runbook

## Boundary

V1 provides core application routes, not a broad command family:

- connect/status/disconnect: `YouTubeAccountBinder` in
  `app/knowledge_acquisition/youtube_oauth.py`;
- select one Inbox, sync once, inspect status: `YouTubeInboxSyncV1` in
  `app/knowledge_acquisition/playlist_discovery.py`.

There is no automatic scheduler, next-sync promise, UI setup wizard, multi-playlist
configuration, Takeout/RSS import, backfill command, analytics view, or full-media route.

## Dev command

Provision `YOUTUBE_OAUTH_CLIENT_ID`, `YOUTUBE_OAUTH_CLIENT_SECRET`, and
`YOUTUBE_TOKEN_STORE_KEY` through the local host-secret boundary, then select the explicit dev
environment. Do not place credential values in arguments, shell history, logs, or receipts. The
supported entrypoint refuses any environment other than `dev` before it constructs an OAuth or
YouTube API client:

```bash
PKM_ENVIRONMENT=dev python -m app.cli youtube-inbox-dev connect
PKM_ENVIRONMENT=dev python -m app.cli youtube-inbox-dev select \
  --account-binding-id <binding-id> --playlist-id <owned-playlist-id>
PKM_ENVIRONMENT=dev python -m app.cli youtube-inbox-dev sync \
  --account-binding-id <binding-id>
PKM_ENVIRONMENT=dev python -m app.cli youtube-inbox-dev status \
  --account-binding-id <binding-id>
```

`connect` prints the provider's device-consent URL and user code, waits for approval, and returns
the non-secret binding id. `select` resolves the stable id against playlists owned by that OAuth
account and refuses a different second Inbox. `sync` performs exactly one synchronous V1 poll;
`status` emits only the sanitized account and Inbox views. This route uses OAuth with the minimal
`youtube.readonly` scope for both consent and YouTube Data API access. It has no public API-key
authentication surface and exposes no scheduler, backfill, or multi-playlist operations.

## One-time local OAuth setup

Use a user-owned Google Cloud OAuth client with the YouTube Data API v3 enabled and the minimal
`youtube.readonly` scope. Provision client identifiers and `YOUTUBE_TOKEN_STORE_KEY` through the
local secret boundary. Values never belong in tracked config, vault content, logs, events, or
receipts. Start and complete device consent only through
`PKM_ENVIRONMENT=dev python -m app.cli youtube-inbox-dev connect`, which composes the shared
`YouTubeAccountBinder` writer boundary and retains the returned non-secret binding id. The binder
owns channel-wide writer admission, one-account enforcement, and restart reconciliation; the CLI
does not implement a second lock or credential state machine. Calling binder methods directly is
an internal application route, not a supported operator invocation.

## Manual Inbox route

The calling application constructs one `YouTubeInboxSyncV1` instance pinned to the connected
`account_binding_id`, existing `SourceRegistry`, `AcquisitionRequests`, YouTube API client, and
OAuth status callback. The manual sequence is:

1. `select_inbox(playlist_ref=<stable playlist id>, title=<display title>)`
2. `sync_now()`
3. `status()`

`select_inbox` is idempotent for the same playlist and rejects a different second Inbox. It does
not expose owned/public/Liked multi-source configuration. `sync_now` calls the production
`poll_source` path exactly once. `status` returns only:

```json
{
  "status": "connected | degraded",
  "last_success_at": "timestamp or null",
  "latest_error": {"reason_code": "...", "detail": "sanitized copy", "at": "..."}
}
```

No token, provider body, or credential-bearing field is forwarded. A successful poll clears the
latest error. A failed poll preserves the prior cursor and last success and records a sanitized
reason. The manual sync receipt contains only status, discovery/enqueue/dedup counts,
`not_modified`, and optional reason code.

## Candidate outcome

New Inbox videos enter the existing durable acquisition queue. When available material drains
successfully, the result is a `youtube_source_note` candidate with:

- `authority.requires_review: true`
- `review_state: draft`
- `triage_state: captured`

The Inbox route never calls knowledge promotion. Human review remains the only path to higher
knowledge standing.

## Troubleshooting

| Reason | Meaning / action |
| --- | --- |
| `auth_missing` | connect the one OAuth account |
| `auth_key_missing` | restore the local token-store key; reconnect if the old key is unavailable |
| `auth_expired` / `auth_revoked` / `auth_disconnected` | reconnect; Inbox cursor and acquired artifacts remain |
| `inbox_missing` | select the one Inbox before `sync_now()` |
| `quota_exhausted` | wait for quota reset, then run manual sync again |
| `api_unavailable` / `network_error` | retry manual sync after provider/network recovery |
| `source_gone` | select an accessible owned playlist as Inbox |
| `policy_unsupported` | V1 requires the delivered `acquire_transcript` Inbox policy |

## Repository verification

The seven exact tests in
`tests/knowledge_acquisition/test_playlist_discovery.py` prove Inbox selection, production poll,
request-before-cursor, honest failure/status, manual routing, and review-required candidate output.
All network egress is stubbed. No real account, playlist id, or token is stored in fixtures.
