State: Normative shared contract for the YouTube Source Sync capability (target-state until child issues deliver it; each section names its consuming tasks).
Doc role: Capability contract
Authority: Owns the source-registry shape, AcquisitionRequest contract, cursor discipline, sync event topics/payloads, settings keys and scopes, reason-code taxonomy, quota accounting, and the media-retention policy for this capability. Subordinate to `docs/EVENTS.md` (envelope/idempotency), `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md` (plugin interface), `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md` (settings scopes), and `docs/SECURITY.md` (secret baseline).

# Source Sync Contract

Task files in this directory reference these sections instead of restating them. Field names are
normative; storage column names may differ only where a store port requires it, never in meaning.

## Source registry (YSS-01; read by YSS-03..11)

One durable row per followed collection, per account binding, in the channel database (Alembic
migration + memory fallback for `not_pg` tests — the PDM store discipline, no private persistence
mechanism).

| Field | Meaning |
| --- | --- |
| `binding_id` | stable UUID primary key — **the** source identity; never the title |
| `account_binding_id` | UUID of the OAuth account binding (nullable: RSS/public sources need none) |
| `collection_kind` | `inbox_playlist` \| `owned_playlist` \| `liked_videos` \| `public_playlist` \| `subscription_feed` |
| `collection_ref` | source-native stable id: playlist ID (`PL…`, `LL` for Liked) or channel ID (`UC…`). Never a title |
| `title` | human-visible display title, refreshed opportunistically from the source; display-only |
| `enabled` | bool; disabled sources keep rows, cursors, and history |
| `discovery_mode` | `api_poll` \| `rss_poll` \| `backfill_only` |
| `poll_interval_seconds` | positive int; per-source override of the kind default |
| `priority` | `high` (inbox) \| `normal` |
| `cursor` | opaque JSON per adapter (see §Cursor discipline); mutated only by its adapter |
| `last_attempt_at` / `last_success_at` | timestamps of the last poll attempt / last successful poll |
| `last_error` | JSON `{reason_code, detail, at}` or null; cleared on success |
| `acquisition_policy` | JSON: `{mode, extractor_ids, captions, media}` — see §Acquisition policy |
| `provenance` | JSON: how the binding was created — `{origin: user_pick \| takeout_import \| manual_add, at, detail}` |
| `created_at` / `updated_at` | timestamps |

Integrity rules (enforced in the service layer so the memory backend behaves identically, plus DB
constraints where expressible):

- unique `(collection_kind, collection_ref, account_binding_id)` — no duplicate bindings;
- **exactly one enabled `inbox_playlist` per `account_binding_id`** — "Change inbox" is an atomic
  swap, never a second inbox;
- `poll_interval_seconds` validated to `[60, 604800]`; the inbox default (180) and other defaults
  come from settings (§Settings), overridable per source;
- unsupported special lists are rejected at registration with `reason_code=source_unsupported`:
  Watch Later (`WL`) and Watch History (`HL`) by ID, with a legible explanation that the official
  Data API does not expose them — never a cookie/scraping fallback;
- environment isolation comes from DB-per-channel plus per-channel token stores (INV-YSS-7);
  registry rows carry no environment column.

## Acquisition policy (YSS-01; consumed by YSS-04/05/07/08)

`acquisition_policy.mode`, in increasing acquisition depth:

| Mode | Effect on a discovered item |
| --- | --- |
| `discover_only` | record discovery (registry/events only); no request, no vault note |
| `candidate_metadata_only` | durable request; pipeline runs metadata-only candidate (no transcript fetch) |
| `acquire_transcript` | durable request; full existing pipeline (metadata + captions/ASR + extractors + candidate) |
| `acquire_if_filter_matches` | as `acquire_transcript` when the declared filter (language/duration/channel allowlist) matches; otherwise a traced `discover_only` rejection |

Defaults: playlist-shaped sources (`inbox_playlist`, `owned_playlist`, `liked_videos`,
`public_playlist`) default to `acquire_transcript`; `subscription_feed` defaults to
`discover_only` (conservative — shown and changeable in setup). `policy_version` is an integer
stamped into requests; a policy change bumps it, which changes request identity for *future*
discoveries only (no retroactive re-acquisition without explicit backfill).

## AcquisitionRequest (YSS-04; produced by YSS-05/07/08, drained by YSS-06)

Source-independent durable work item. **Identity:** `request_id = uuid5(namespace,
"{source_kind}:{item_ref}:{policy_version}")` — the idempotency rule *one request per
(source_kind, item_ref, policy_version)*.

| Field | Meaning |
| --- | --- |
| `request_id` | deterministic UUID primary key (above) |
| `source_kind` | `youtube_url` (existing vocabulary; new sources bring their own) |
| `item_ref` | source-native stable item id (11-char YouTube video id) |
| `source_ref` | canonical URL for the item |
| `status` | `pending` \| `in_progress` \| `completed` \| `dead_lettered` (retryable failure stays `pending` with `next_attempt_at` in the future) |
| `priority` | `high` \| `normal` — inherited from the discovering source; drain order `(priority, requested_at)` |
| `requested_at` / `completed_at` | timestamps |
| `attempts` | int; incremented per drain attempt |
| `next_attempt_at` | timestamp gate for retry backoff (see §Retry and backoff) |
| `last_failure` | JSON `{reason_code, error, at}` or null — error text is exception-class + safe message, never tokens |
| `discovery_triggers` | JSON array, append-only: `{binding_id, collection_kind, playlist_item_id?, discovered_at, trigger: poll \| backfill \| manual}` — full multi-source provenance |
| `policy_snapshot` | JSON copy of the effective acquisition policy at enqueue + `policy_version` |
| `trace_id` | correlation id propagated into `acquire_youtube` and stage events |
| `content_identity` / `artifact_path` | filled on completion from the `AcquisitionReceipt` |

State rules:

- Insert is idempotent (`ON CONFLICT (request_id)` → append the new trigger to
  `discovery_triggers`, update nothing else). Playlist-item identity is provenance
  (`playlist_item_id` in the trigger), never request identity — the same video in N lists is one
  request (INV-YSS-2).
- `completed` requires the KA terminal outcome: `AcquisitionReceipt.ok` with candidate written or
  traced dedup no-op (INV-YSS-3). A WriteGuard block (`blocked=True`) or transient failure resets
  to `pending` with `reason_code` + backoff; it never dead-letters and never completes.
- `dead_lettered` is explicit, item-scoped, and reserved for terminal per-item outcomes (KA stage
  dead-letter surfaced, or attempts exhausted); it emits `acquisition.failed` with
  `terminal: true` and is listable/retryable by operator command.
- Restart recovery: rows stuck `in_progress` past a stale threshold are reset to `pending` (the
  drain re-run converges through KA idempotency).

## Cursor discipline (YSS-05/07; guarded by YSS-06)

Cursors are opaque per-adapter JSON in the registry row, durable in the channel DB, and advanced
only under INV-YSS-1 (*request-before-cursor*):

- **API playlist adapter (YSS-05):** cursor records the frontier of playlist items already
  disposed (durable request or traced rejection). A poll pages `playlistItems.list`
  (`maxResults=50`, `If-None-Match` ETag) newest-first until it reaches only-known items or the
  bounded page cap; unknown items get requests *before* the cursor frontier moves. An ETag `304`
  is a successful no-change poll (updates `last_success_at`, nothing else). A poll that fails
  (auth/API/network) mutates neither cursor nor known-set and records `last_error` (INV-YSS-4).
- **RSS channel adapter (YSS-07):** cursor is newest-published-seen per feed plus recent entry ids;
  the ~15-entry RSS window bounds incremental reach — anything past the window is backfill's job.
- **Backfill (YSS-08):** does not use the incremental cursor; it enumerates via yt-dlp
  `--flat-playlist` (logged-out) or full API pagination, diffs against existing
  requests/dispositions, and enqueues only the gap. It never rewinds an incremental cursor.

## Event topics (YSS-04/05/06; schemas registered per KERNEL-08)

All on the canonical DB outbox via `write_outbox_event` with `derive_idempotency_key` — never the
Heimdal observation log, never embedding payloads. Versioned schemas under
`schemas/events/<topic>.v1.schema.json`; envelope `source` is `knowledge_acquisition.source_sync`.
These are lineage/receipt events (not dispatched commands); registration gives write-time
validation, and any future consumer follows the KA-07 route pattern.

| Topic | Emitted when | Payload (beyond envelope) | Idempotency key basis |
| --- | --- | --- | --- |
| `youtube.source.discovered` | a not-previously-disposed item is seen in a source | `binding_id, collection_kind, collection_ref, item_ref, playlist_item_id?, trigger` | `(topic, binding_id, item_ref)` — re-discovery of the same item in the same source dedups |
| `acquisition.requested` | a request row is first created | `request_id, source_kind, item_ref, policy_version, priority, trigger_count` | `(topic, request_id, policy_version)` |
| `acquisition.started` | a drain attempt begins | `request_id, attempt` | `(topic, request_id, attempt)` — each attempt is a distinct event |
| `acquisition.completed` | a request reaches `completed` | `request_id, attempt, content_identity, artifact_path?, dedup_noop` | `(topic, request_id, attempt)` |
| `acquisition.failed` | an attempt fails (retryable or terminal) | `request_id, attempt, reason_code, terminal, next_attempt_at?` | `(topic, request_id, attempt)` |
| `youtube.sync.completed` | a per-source poll run ends successfully (incl. 304 no-change) | `binding_id, run_id, discovered, enqueued, deduped, not_modified, duration_ms, quota_units_spent` | `(topic, binding_id, run_id)` |
| `youtube.sync.degraded` | a poll run ends degraded, or global degradation starts/changes | `binding_id?, run_id, reason_code, detail` | `(topic, binding_id or "global", run_id)` |

Receipt sufficiency: request rows + these events must answer — why a candidate exists (triggers),
which source discovered it and when, whether it was deduplicated, which step failed, whether the
cursor advanced, when the next retry is due, and which account/environment ran the job — all
without exposing a secret (INV-YSS-5). YSS-09 ships the typed read-only projection over this
substrate (the `settings_receipts`/`promotion_receipts` pattern).

## Reason codes (all surfaces: `last_error`, events, health, UI, CLI)

`auth_missing` (no binding), `auth_key_missing` (token store key absent or unable to authenticate
the encrypted aggregate — fail-closed),
`auth_expired`, `auth_revoked`, `auth_disconnected` (operator action),
`auth_refresh_pending` (rotated encrypted authority awaits canonical promotion),
`auth_refresh_conflict` (canonical no longer matches the journal's predecessor generation),
`auth_refresh_durability` (rotation could not be durably journaled or authoritatively compensated),
`quota_exhausted`,
`api_unavailable` (5xx/timeout), `network_error`, `source_gone` (404/private-without-access),
`source_unsupported` (Watch Later / Watch History), `writeguard_blocked`, `pipeline_dead_letter`,
`policy_unsupported` (queued acquisition mode/depth has no delivered production path),
`paused_global`, `paused_source`, `runner_offline` (staleness derived, not self-reported),
`media_policy_disabled`. UI copy maps these through the Companion UI's single degraded-copy module;
unknown codes fail closed to the generic degraded message.

## Settings model (YSS-01; surfaces in YSS-10/11)

Via the existing `SettingsService` registry — no parallel settings format. Vault-shared file:
`<vault>/settings/youtube.md`. Everything below is a **product default: visible, overridable**.

| Key | Scope | Default | Notes |
| --- | --- | --- | --- |
| `youtubeSync.enabled` | vault-shared | `false` | master switch; flipped by completing setup |
| `youtubeSync.inboxPollSeconds` | vault-shared | `180` | validated `[60, 3600]` |
| `youtubeSync.playlistPollSeconds` | vault-shared | `3600` | validated `[300, 86400]` |
| `youtubeSync.subscriptionsPollSeconds` | vault-shared | `21600` | 6 h; validated `[3600, 86400]` |
| `youtubeSync.reconcileIntervalDays` | vault-shared | `7` | weekly gap repair |
| `youtubeSync.maxConcurrentAcquisitions` | vault-shared | `2` | bounded fan-out |
| `youtubeSync.subscriptionDefaultPolicy` | vault-shared | `discover_only` | conservative; shown in setup |
| `youtubeSync.captionsEnabled` | vault-shared | `true` | transcript acquisition on |
| `youtubeSync.mediaDownloadEnabled` | vault-shared | `false` | §Media retention policy |
| `youtubeSync.runnerEnabled` | vault-local | `false` | which machine runs the sync loop; DB lease remains the hard guard |

Not settings (runtime-operational state in the channel DB, per §Registry/§Request): cursors,
leases, heartbeats, last-sync, retry state, dead letters, schedule state. Not settings values
(app-local/private bindings only): account binding metadata, OAuth client env-var *names*, token
store *path*, local Takeout import path. Candidate posture (`requires_review: true`,
`review_state: draft`) is **not configurable** (INV-YSS-8).

`youtubeSync.enabled` and `youtubeSync.runnerEnabled` join `RUNTIME_GATING_SETTINGS` (writes gated
by WriteGuard + durable settings receipt). Each runtime-gating key is accepted only from its
registered owner file (`youtube.md` for the shared master switch, `local.md` for the machine-local
runner switch); a cross-file override is ignored with a `SettingsValidationError` and no success
receipt. Runtime consumers use `SettingsService.resolve_accepted_runtime_gating`, which derives
accepted state for the two issue-authorized YouTube gates from identity-bound durable
governed-write receipts in serialized durable append order, deduplicated by validated operation
identity, and fails closed to the registered default;
raw `SettingsService.resolve` remains the operator/provenance view and is not a runtime-gating
authority accessor. Deleting an owner file is a governed reset to its registered default; a failed
or deferred reset remains pending for retry, and deletion of the vault-local owner retains its
accepted identity only while the surviving vault owner still proves the same vault. A git-synced
arrival replays through the same local gate with `surface='sync'` and `actor='sync'`, never as a
local human receipt. The watcher identifies that production provenance only when the exact observed
bytes match the clean tracked Git snapshot and remain unchanged through durable acceptance; watcher
state advances only that accepted digest, so a later generation remains pending rather than being
marked seen. Durable receipts carry the registered owner filename, never the vault path.
Modified/untracked, raced, receipt-failed, or non-Git observations remain local or deferred rather
than receiving stale sync attribution.
Validation errors degrade to defaults with a
`SettingsValidationError`, never silently apply. Effective values, scope, and source file are
shown by the capability doctor
(`youtube-sync doctor`) via `EffectiveSetting` provenance.

## Secrets and private bindings (YSS-02)

Per `docs/SECURITY.md`, ADR-0046 (zero secrets in the public tree), the private-bindings posture
(ADR-0044 D2), and `docs/LOCAL_SECRET_PROVISIONING/` (host secret boundary):

- OAuth client credentials resolve from environment (`YOUTUBE_OAUTH_CLIENT_ID` /
  `YOUTUBE_OAUTH_CLIENT_SECRET`), provisioned per host through the local secret-provisioning
  boundary (Keychain → process env). Settings/receipts may name the env vars, never their values.
- Tokens (refresh/access) live in an encrypted-at-rest token store file (AES-256-GCM via the
  existing `cryptography` dependency, mirroring `app/heimdal/raw_store.py`): path is an app-local
  binding (default under the channel runtime dir; never the vault, never the repo), key from
  `YOUTUBE_TOKEN_STORE_KEY` (32 bytes, same provisioning boundary). An authenticated encrypted
  canary binds that configured key to the whole aggregate; a legacy aggregate without the canary is
  admitted only after every existing record authenticates under the key. A missing or valid-but-
  wrong key with an existing binding ⇒ `auth_key_missing` degraded state before any grant poll or
  aggregate mutation — never a plaintext fallback or mixed-key file (fail closed).
- Redaction: all sync surfaces route through redaction-aware serialization; field names carry
  `token`/`secret`/`credential` tokens so existing key-name redactors match. Exception text from
  the OAuth/HTTP layer is sanitized (status + an allowlisted OAuth error enum, never arbitrary
  provider strings or response bodies that may echo tokens).
- Before polling the device-token endpoint, connect resolves the encryption key and proves the
  aggregate store's locked atomic write/read path without writing secret probe material. Each POSIX
  write syncs the staged file before atomic replacement and confirms the complete parent-directory
  chain through the filesystem root, including fresh first-use nested directories. Windows uses a
  write-through replacement. A visible record after a failed barrier is
  not crash-durable authority until a fresh barrier succeeds. Once
  the provider returns a grant, connect immediately journals it encrypted under an opaque digest
  id; no identity probe or binding mutation occurs first. Exact encrypted-record readback treats a
  lost write acknowledgement as durable success, so a landed pending journal or canonical
  reconnect token is never revoked as though its write failed. If the journal or identity probe
  fails without such durable authority, an authoritative provider revocation compensates and
  removes the journal. An unproven revoke preserves or retries the encrypted pending journal, whose
  compensation is explicitly retryable. Pending-only first-connect recovery makes the canonical
  token durable before it creates a binding row whose default state claims `connected`. When an
  older canonical predecessor exists, recovery first recreates its matching row before a distinct
  later pending grant can replace it, so a failed row create leaves both authorities intact. After
  the canonical binding token is durable **and the matching binding row is visible**,
  pending-journal cleanup is safe and best-effort: a crash can
  retain a redundant encrypted copy but cannot remove revocation authority. A deterministic
  first-connect candidate without that row is not canonical authority: its per-attempt journal
  remains retryable, and a later consent retains a distinct journal rather than overwriting the
  candidate grant. The encrypted journal carries the display metadata needed to retry the same
  deterministic binding create without polling for another grant; delayed exact rows converge,
  while a different same-channel winner remains a non-destructive conflict. Promotion and cleanup
  remain inside the pending → channel → binding lifecycle-lock order. Before canonical write, the
  encrypted pending record gains its
  exact target, predecessor refresh authority, and next authority generation. Retry removes it only
  when canonical has the same refresh authority, or promotes it only while canonical still exactly
  matches that predecessor generation. Same-channel identity alone is never canonical proof: a
  token mismatch against a newer/different generation preserves both records as `pending_conflict`
  and performs no provider revocation.
- Connect persists the encrypted token before claiming a binding is connected. Connect,
  reconnect, refresh, and disconnect serialize each binding's credential lifecycle across service
  instances and runtime processes sharing the channel token store. The app-local lock filename is
  a digest of the binding id and its private lock file contains no account identifier or secret.
  A portable store-wide lock additionally serializes aggregate token-file mutations across
  distinct bindings (POSIX and Windows), and concurrent first connects re-resolve provider identity
  under shared authority before creating a binding. First-connect binding ids are deterministic per
  provider channel. If binding creation returns an exception after its database commit, visible
  binding/channel readback rolls forward to the committed connected row; negative read snapshots
  never compensate the encrypted credential because a delayed commit may still appear. Retry then
  converges through the same candidate id without minting another credential identity.
- Google's [refresh contract](https://developers.google.com/identity/protocols/oauth2/web-server#offline)
  documents a successful refresh as returning a new access token while the securely stored refresh
  token remains the long-lived credential. The implementation nevertheless treats any unexpected,
  non-empty different `refresh_token` in that response as a rotation: it proves store readiness
  before `/token`, durably journals the returned authority with its exact predecessor/generation,
  and only then promotes canonical state. A canonical-write failure leaves
  `auth_refresh_pending`; the next access promotes without another provider request only if the
  predecessor is unchanged. A newer/different canonical generation yields
  `auth_refresh_conflict` and preserves both encrypted authorities. Status never reports either
  state as connected. If local journaling cannot be confirmed, a durable encrypted compensation
  marker makes the rotated authority non-promotable before provider revocation; authoritative
  compensation advances that marker and persists `auth_revoked` binding/source truth before
  cleanup. Retained crash residue reports revoked and can only be cleaned or re-compensated, never
  promoted; reconnect requires new consent. Pending, conflict, and durability failures stamp the same registered reason
  code on the binding and dependent sources while the per-binding lifecycle lock is still held, and reconnect/disconnect must resolve the journal or
  fail closed before polling/revoking.
- Loopback redirect admission runs on the raw string before URI parsing can normalize it: the URI
  must be `http`, use exact host `127.0.0.1` with an explicit valid port, contain no ASCII controls,
  and contain neither a query/fragment delimiter nor query/fragment content. Creation and code
  exchange both apply the same validation.
- Disconnect durably sets `auth_disconnected` before calling the provider. A queued or stale token
  consumer cannot consume retained ciphertext or replace that terminal operator state with
  `auth_missing` or another transient reason. Before confirmed teardown, dependent sources remain
  enabled but degraded for retry; cursors and acquired artifacts remain unchanged. After confirmed
  teardown they are disabled with the same reason.
- Disconnect then revokes at the provider (`oauth2.googleapis.com/revoke`). Only Google's
  documented HTTP 400 `invalid_token` outcome — meaning already expired or revoked — permits local
  teardown with `revoked=false`. `invalid_request`, intermediary/unknown 4xx responses, redirects,
  transport failures, and every other unproven outcome preserve the encrypted token solely as
  revocation-retry authority while terminal local state blocks consumption. Credential-bearing
  OAuth requests set redirect following off at the
  request site, independent of injected-client defaults. Teardown deletes the token record and
  disables dependent sources with `auth_disconnected` — acquired artifacts, raw records, and
  receipts are never deleted.

## Egress posture (YSS-02/03/07/08)

Declared hosts, all TLS, allowlisted at the client layer (SSRF guard — refuse any other host or a
redirect off-list): `www.googleapis.com` (Data API), `accounts.google.com` +
`oauth2.googleapis.com` (OAuth device/token/revoke), `www.youtube.com` (RSS feeds + yt-dlp),
`googlevideo.com` (existing fetch path, unchanged). Item refs are validated as 11-char video ids /
`PL*`/`UU*`/`LL*` playlist ids / `UC*` channel ids before any URL is built. Bounded pagination
(page cap per poll), bounded response size, request timeouts, and politeness sleeps on yt-dlp
paths (existing constants) apply everywhere.

## Quota accounting (YSS-03/06/09)

Data API reads cost 1 unit per call against the project's 10,000/day default. The client counts
units per UTC day (durable counter in the channel DB), surfaces
`quota: {spent_today, budget, exhausted}` in status/doctor, and treats a 403
`quotaExceeded`/`rateLimitExceeded` as `quota_exhausted` degradation with backoff to the next UTC
window — never as source emptiness. ETag `304`s still spend quota (documented Google behavior);
their value is payload/processing reduction. Expected steady-state spend (inbox @180 s + 10
playlists @1 h + subscriptions on RSS) is well under 1,000 units/day; the accounting exists to
make misconfiguration visible, not to micro-optimize.

## Retry and backoff (YSS-04/06)

Exponential backoff with jitter per failing unit (source poll or request attempt): base 60 s,
factor 4, cap 6 h, reason-coded. `quota_exhausted` backs off to the next quota window. Manual
"Sync now" performs one immediate safe attempt regardless of backoff (lease-guarded, never
parallel to a running poll of the same source) — it resets no counters on failure. Attempts
exhaust into `dead_lettered` only for per-item terminal outcomes (default max 8 attempts);
source-level degradation never dead-letters items that were never attempted.

## Media retention policy (fields YSS-01; enforcement YSS-04/06; engine deferred)

Acquisition depth (metadata + captions/transcript + candidate) is the default and only shipped
behavior. Full media (video/audio file) archival is a distinct policy that ships **disabled**:

- `youtubeSync.mediaDownloadEnabled=false` default; per-source `acquisition_policy.media` object
  (`{enabled, max_quality, format, storage_binding, min_free_gb, retention_days, checksum: true}`)
  validated but refused at enforcement (`media_policy_disabled`) while the engine is undelivered.
- The archival engine is a separate follow-up issue, `agent:needs-human`-gated on an explicit
  owner review of YouTube ToS and the product's rights/retention posture. The Data API grants no
  general media-download right for third-party videos; nothing in this capability claims it does.
- Storage location must be a configured private binding (no hardcoded path); disk quota + minimum
  free space + retention + checksum/content-identity + cleanup receipts are engine requirements
  recorded here so the policy fields ship complete.
