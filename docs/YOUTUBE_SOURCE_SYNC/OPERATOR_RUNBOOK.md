State: Operator runbook (target-state until the child issues deliver the commands it references; the Live acceptance section is the capability's pending operator evidence — every unchecked item is by definition not yet live-verified).
Doc role: Operator runbook
Authority: Owns the operator path for YouTube source sync: OAuth client creation, first setup, troubleshooting, and live acceptance. Command truth is the delivered CLI (`OPERATE_SYNC_FROM_CLI.md`); this document never overrides contract semantics in `SOURCE_SYNC_CONTRACT.md`.

# YouTube Source Sync — Operator Runbook

## One-time: create the OAuth client (user-owned Google Cloud project)

Single-user posture: the OAuth client belongs to the owner's own Google account. No service
account (YouTube's API does not serve user-private data to service accounts), no shared client.

1. In Google Cloud Console: create (or reuse) a project → enable **YouTube Data API v3**.
2. OAuth consent screen: External, add only the owner account as test user (Testing status is
   fine and avoids verification; refresh tokens issued in Testing expire after 7 days **only**
   for some client types — use **TVs and Limited Input devices** client type, whose tokens do not
   carry that restriction, or publish the app to Production for a long-lived refresh token).
3. Create credentials → OAuth client ID → **TVs and Limited Input devices** (device flow;
   loopback dev flows may use a separate Desktop client).
4. Provision the two identifiers on the host through the local secret-provisioning boundary
   (`docs/LOCAL_SECRET_PROVISIONING/`): Keychain entries resolved into the channel process
   environment as `YOUTUBE_OAUTH_CLIENT_ID` / `YOUTUBE_OAUTH_CLIENT_SECRET`. Never write values
   into tracked config, compose files, the vault, or BuilderOps records.
5. Generate a 32-byte token-store key into the same boundary, exposed as
   `YOUTUBE_TOKEN_STORE_KEY`. Same non-rotation caution as other store keys: rotating it orphans
   the stored token (recovery = reconnect, not data loss).

## First setup (Companion UI — recommended)

Settings → YouTube: **Connect** → approve on any device via the shown link → **pick the inbox
playlist** (create e.g. "Mimer Inbox" in YouTube first if you have none — the name is a
suggestion; the binding is by playlist ID) → choose other playlists / Liked Videos → note that
Watch Later and Watch History cannot be connected (official API limitation) → optionally import
subscriptions from a Google Takeout export → review the **preview** (source count, discovered
items, estimated work; "new items only" is the default — historical backfill needs its own armed
confirmation) → confirm. The status card then shows last sync, next sync, queue, quota, and
per-source state; **Save → your inbox playlist** on any device now flows in within ~3 minutes.

CLI equivalent: `youtube-auth connect --device` → `youtube-sources list` / `configure --set-inbox`
/ `add-playlist` / `import-takeout` → `youtube-sync backfill --plan` (+ `--execute
--confirm-plan`) → `youtube-sync status`.

## Routine operations

| Need | Action |
| --- | --- |
| Force a poll now | UI **Sync now** / `youtube-sync run --once` (lease-guarded, safe) |
| Stop temporarily | UI **Pause** / `youtube-sync pause [--source <id>]` |
| Change inbox | UI **Change inbox** / `youtube-sources configure <id> --set-inbox` (atomic swap) |
| Re-consent after revoke | UI **Reconnect** / `youtube-auth connect` (same binding, cursors intact) |
| Stop for good | UI **Disconnect** / `youtube-auth disconnect` — revokes + deletes token, keeps every acquired note/record |
| Audit one item | `youtube-sync why <video_id> --json` |
| Weekly drift | automatic reconcile; large gaps surface as a pending preview to confirm |

## Troubleshooting (doctor-first)

`python -m app.cli youtube-sync doctor --json` (or `health --json` → `checks.youtube_sync`).
Reason codes and their remedies:

| Reason code | Meaning | Remedy |
| --- | --- | --- |
| `auth_missing` | no account connected | run setup / `youtube-auth connect` |
| `auth_key_missing` | token store key absent (fail-closed) | re-provision `YOUTUBE_TOKEN_STORE_KEY` via the secret boundary; nothing was written in plaintext |
| `auth_expired` / `auth_revoked` | consent lapsed or withdrawn | **Reconnect**; cursors and queue are untouched |
| `quota_exhausted` | Data API daily quota spent | wait for the UTC reset (automatic backoff); check for a runaway interval override |
| `api_unavailable` / `network_error` | provider/network outage | automatic backoff; `Sync now` for a manual safe retry |
| `source_gone` | playlist deleted or made inaccessible | remove or re-scope the binding |
| `source_unsupported` | Watch Later / Watch History | not connectable; save to the inbox playlist instead |
| `writeguard_blocked` | runtime health blocks vault writes | heal runtime health; requests retry automatically |
| `pipeline_dead_letter` | item failed a KA stage terminally | inspect via `youtube-sync why`; item-scoped, siblings unaffected |
| `paused_global` / `paused_source` | operator pause | resume when ready |
| `runner_offline` | no scheduler tick within the staleness window | confirm the watcher service is running (`docker compose ps` for the channel); UI shows offline, never "up to date" |

## Live acceptance (pending — requires the Mac mini; run on the test channel first)

Execute after all child slices are merged and promoted to the test channel. Every item below is
**unchecked until an operator runs it live**; fixture-based CI cannot discharge these.

1. [ ] Connect YouTube via OAuth (device flow) in dev/test; confirm no secret appears in
       `docker compose logs`, events, or receipts during the flow.
2. [ ] Pick an own **private** playlist as inbox.
3. [ ] Add a test video from the YouTube mobile app (*Save → inbox*).
4. [ ] Confirm discovery within ~3 minutes (`youtube-sync status` shows the request; event
       `youtube.source.discovered` present).
5. [ ] Confirm the durable AcquisitionRequest row (`youtube-sync why <video_id>`).
6. [ ] Confirm raw → normalized → extracted → candidate completion (stage events + note in
       `Sources/`).
7. [ ] Confirm the candidate carries `requires_review: true`, `review_state: draft`,
       `triage_state: captured`, and full provenance including the discovery trigger.
8. [ ] Add the same video to a second synced playlist; verify single request/candidate with both
       triggers (`deduplicated: true`).
9. [ ] Stop the runtime; add a video; restart; verify reconciliation discovers it with no
       duplicate candidate.
10. [ ] Revoke consent in Google security settings; verify legible `auth_revoked` degradation
        (UI + doctor) with no cursor corruption; Reconnect restores sync.
11. [ ] Sweep logs, events, receipts, and notes for token material one final time (planted-
        sentinel + pattern scan).

Record the run as a validation receipt on the parent feature issue. Only after this section is
fully checked may owner docs (`ARCHITECTURE.md`/`STATUS.md`) claim the capability as shipped
operator-verified.
