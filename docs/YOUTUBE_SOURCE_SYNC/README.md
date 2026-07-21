State: Pragmatic YouTube Source Sync V1. Delivered foundations provide the registry, OAuth, Data API client, acquisition queue, and one manual Inbox sync route. The owner directive of 2026-07-21 limits the product outcome to one OAuth account, exactly one Inbox playlist, manual sync, minimal sanitized status, and review-required candidates. Scheduling, multi-source expansion, subscriptions/RSS/Takeout, backfill, analytics, broad CLI/UI, and full-media work remain deferred.
Doc role: Capability specification directory
Authority: Owns the YouTube source-sync capability design — account binding, source registry, continuous discovery, durable acquisition requests, scheduling, and the setup/status surfaces. Subordinate to `docs/KNOWLEDGE_ACQUISITION/README.md` (platform boundary), `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md` (plugin interface), `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` (stages), `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` (triage), `docs/EVENTS.md` (event envelope/outbox), and `docs/SECURITY.md` (secret baseline). It revises `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md` §Discovery by owner directive (see §Decision record).
Owner: Architecture / knowledge acquisition
Temporal class: strategic
Review cadence: event-driven (task merge, YouTube API surface change)
Last reviewed: 2026-07-16

# YouTube Source Sync

## Outcome

The user connects one YouTube account, selects exactly one owned playlist as the **Inbox**, saves
videos there using YouTube's ordinary UI, and explicitly runs the manual Inbox sync route. New
items flow idempotently through the existing Knowledge Acquisition pipeline:

```
YouTube playlist discovery
  → durable AcquisitionRequest
  → acquire_youtube (existing entrypoint, app/knowledge_acquisition/acquire.py)
  → immutable raw evidence → normalize → extract
  → review-required youtube_source_note candidate
```

**The playlist is only a user-friendly intent surface — never knowledge authority.** Discovery
creates a durable request; KAP produces a review-required candidate; only Mimer's governed human
review/promotion can raise anything to higher knowledge standing.

No automatic cadence is claimed by V1. Owned/public/unlisted/Liked multi-playlist sync,
subscriptions, RSS, Takeout, backfill, analytics, and full-media acquisition are not V1 outcomes.

## Decision record (owner directives 2026-07-16 and 2026-07-21)

`docs/KNOWLEDGE_ACQUISITION/RESEARCH_2026-07.md` §4 and `YOUTUBE_SOURCE_SPEC.md` §Discovery
originally decided **"No Data API"** (Takeout + RSS + yt-dlp only, zero OAuth coupling). The owner
directive of 2026-07-16 revises that decision for playlist-shaped sources:

| Question | Previous posture (2026-07 memo) | Ruling now in force |
| --- | --- | --- |
| Inbox / owned / private playlists, Liked Videos | not reachable (API rejected) | **YouTube Data API v3 with OAuth 2.0, minimal scope `youtube.readonly`** — the save-to-playlist ≤3-minute inbox UX and private-playlist reads are unreachable any other sanctioned way |
| Subscriptions | Takeout bootstrap + per-channel RSS + rare yt-dlp `--flat-playlist` backfill | **unchanged (conforms)** |
| Watch Later / Watch History | optional cookie-based degradable capability | **removed entirely** — both are unsupported by the official Data API; the standard flow MUST NOT attempt cookies, scraping, or browser sessions |
| Auth posture | none (logged-out) | logged-out for fetch/backfill (unchanged); OAuth read-only **only** for the playlist/liked discovery API surface, fully degradable |

Rationale: the research memo itself conceded the API's unique value is near-real-time private-list
sync; the owner now wants exactly that value, at minimal scope, with cookies banned outright
(stricter than the memo). The revision is recorded in `YOUTUBE_SOURCE_SPEC.md` §Discovery in the
same change that lands this directory. SBS posture: this **extends** the EBF Acquisition-source
class (`docs/INTEGRATION_FABRIC_CONTRACT.md` class 11) with an authenticated discovery surface —
no reshape; plugin authority limits are unchanged.

The 2026-07-21 directive supersedes the broad delivery plan with the pragmatic V1 boundary above.
The wider data shapes remain future-facing compatibility vocabulary, not shipped product claims.

## Capability boundary

In scope:

- One minimal-scope OAuth account with encrypted local token authority and fail-closed status.
- Exactly one enabled Inbox playlist selected through `YouTubeInboxSyncV1.select_inbox`.
- One explicit `sync_now` call through the production Inbox poll path.
- Durable request-before-cursor discovery and minimal sanitized status.
- Existing acquisition drain into review-required draft `youtube_source_note` candidates.
- Existing versioned acquisition events on the canonical DB outbox.

Out of scope (owned elsewhere or explicitly deferred):

- Everything downstream of `candidate` (triage, promotion) — `INGESTION_AND_TRIAGE_POLICY.md`.
- Fetch/refinement mechanics — already shipped (KA-01..07); this capability only *feeds* them.
- Automatic scheduling/cadence, leases, pause/resume, and restart reconciliation.
- Owned/public/unlisted/Liked multi-playlist product sync; subscriptions, RSS, Takeout, backfill,
  analytics, broad CLI/UI families, and filter-policy expansion.
- Full media (video/audio file) archival — policy fields ship OFF by default; the archival engine
  is a separate follow-up issue gated on an explicit owner rights/ToS review (see
  `SOURCE_SYNC_CONTRACT.md` §Media retention policy).
- Watch Later / Watch History in any form. No cookies, no scraping, no browser sessions.
- Other source instances (podcast RSS etc.) — they later reuse the registry/request contracts.
- Embedding/indexing of acquired content (epic #2314).

## Architecture fit

- **Constituent:** Mimer (ADR-0044 Decision 2 — KAP is an in-constituent acquisition capability).
  This is not Heimdal work: nothing here writes the Heimdal observation log, and no new
  constituent is created. Yggdrasil is the ecosystem, not an implementing system.
- **SBS (conform, no reshape):** EBF primary (discovery/fetch adapters, declared egress posture,
  auth degradation); PDM (registry/queue tables behind the existing store/migration discipline —
  no private persistence mechanism); DRI (all sync state is rebuildable/derived; never the only
  copy of meaning); OEF (health, receipts, counters); HKA/SIP/GOV touched only through the
  existing governed candidate writeback (unchanged). Forbidden-dependency rule holds: no YouTube
  concept leaks into HKA/SIP/GOV vocabularies; artifacts keep `source_kind: youtube_url`.
- **Events:** canonical DB outbox only (`app/services/outbox.py::write_outbox_event` +
  `derive_idempotency_key`), KERNEL-08 registered schemas. JSONL stays audit-only. The Heimdal
  observation log is never written.
- **Reuse over new infrastructure:** V1 reuses the existing acquisition queue, shared
  outbox/idempotency helpers, and durable cursor discipline; WriteGuard remains the only
  vault-write gate. No runner, scheduler, lease, parallel outbox, or receipt substrate is
  introduced.

## Normative shared contract

Data shapes, event topics/payloads, settings keys and scopes, reason codes, cursor-advance
discipline, quota accounting, and the media-retention policy live in one normative file:
[`SOURCE_SYNC_CONTRACT.md`](SOURCE_SYNC_CONTRACT.md). Task files reference it instead of restating
it. The operator path (GCP/OAuth setup, first sync, troubleshooting, live acceptance) lives in
[`OPERATOR_RUNBOOK.md`](OPERATOR_RUNBOOK.md).

## Implementation tasks and execution order

| Order | Task | ID | Prerequisites | Outcome |
| --- | --- | --- | --- | --- |
| 1 | [Establish source registry and settings](ESTABLISH_SOURCE_REGISTRY_AND_SETTINGS.md) | YSS-01 | — | **Delivered repository-verifiably** (#3916 / PR #3931): durable per-account source registry + settings model + validation; live capability acceptance remains pending |
| 2a | [Bind YouTube account with OAuth](BIND_YOUTUBE_ACCOUNT_WITH_OAUTH.md) | YSS-02 | YSS-01 | **Delivered V1 foundation:** encrypted local token authority, connect/status/disconnect degradation |
| 2b | [Establish durable acquisition requests](ESTABLISH_DURABLE_ACQUISITION_REQUESTS.md) | YSS-04 | YSS-01 | **Delivered V1 foundation:** source-agnostic request queue + review-required acquisition drain |
| 3a | [Build YouTube Data API client](BUILD_YOUTUBE_DATA_API_CLIENT.md) | YSS-03 | YSS-02 (token provider interface only — stubbable) | **Delivered V1 foundation:** bounded read-only API client, ETag, quota accounting, host allowlist |
| 3b | [Sync subscriptions from Takeout and RSS](SYNC_SUBSCRIPTIONS_FROM_TAKEOUT_AND_RSS.md) | YSS-07 | YSS-01, YSS-04 | Takeout adoption (operator WIP baseline), channel-RSS incremental discovery, policy modes |
| 4 | [Sync one YouTube Inbox playlist](DISCOVER_PLAYLIST_ITEMS_CONTINUOUSLY.md) | YSS-05 | YSS-01, YSS-03, YSS-04 | **V1:** exactly one Inbox, manual production poll, sanitized status, review-required candidate |
| 5 | [Schedule and operate continuous sync](SCHEDULE_AND_OPERATE_CONTINUOUS_SYNC.md) | YSS-06 | YSS-04, YSS-05 | per-source scheduling, single-run lease, pause, offline/restart reconciliation, backoff, safe shutdown |
| 6a | [Repair gaps with previewed backfill](REPAIR_GAPS_WITH_PREVIEWED_BACKFILL.md) | YSS-08 | YSS-05, YSS-07 | weekly reconcile + historical backfill with preview receipt and explicit confirmation gate |
| 6b | [Surface sync health, status, and receipts](SURFACE_SYNC_HEALTH_STATUS_AND_RECEIPTS.md) | YSS-09 | YSS-02, YSS-04, YSS-06 | doctor/health checks, degraded-reason taxonomy, receipt projection answering the audit questions |
| 6c | [Operate sync from the CLI](OPERATE_SYNC_FROM_CLI.md) | YSS-10 | YSS-02, YSS-06 | scriptable `--json` commands: auth connect/status/disconnect, sources list/configure, sync run/status/pause, doctor |
| 7 | [Set up YouTube sync in Companion UI](SET_UP_YOUTUBE_SYNC_IN_COMPANION_UI.md) | YSS-11 | YSS-02, YSS-05, YSS-06, YSS-09 | guided setup flow + status card (cold/connected/degraded/paused/offline), preview-before-backfill, Sync now/Pause/Reconnect/Change inbox/Disconnect |

Parallel lanes after YSS-01: {YSS-02, YSS-04} → {YSS-03, YSS-07} → YSS-05 → YSS-06 → {YSS-08,
YSS-09, YSS-10} → YSS-11. The final child (YSS-11) includes the parent-closure handoff.

## Cross-Task Invariants / Interaction Safety

Invariants that hold *across* tasks, with their partial-failure seams:

- **INV-YSS-1 — request-before-cursor.** A source cursor never advances past an item that does not
  yet have a durable `AcquisitionRequest` row (or an explicit durable disposition such as a policy
  rejection trace). Seam: discovery crashes after enumerating but before persisting requests → on
  restart the unadvanced cursor re-enumerates; request idempotency (INV-YSS-2) makes the re-run
  converge. Cursor persistence and request persistence may not be reordered.
- **INV-YSS-2 — one request per (source_kind, item_ref, policy version).** The same video saved in
  N playlists yields exactly one request whose `discovery_triggers` records all N bindings.
  Duplicate discovery appends a trigger; it never creates a parallel request or re-runs completed
  work. Seam: two sources discover the same video in the same tick — the deterministic request id
  makes the second insert converge to trigger-append.
- **INV-YSS-3 — a request is terminal only when candidate materialization is terminal.** `completed`
  requires the KA pipeline's terminal candidate outcome (note written, or traced dedup no-op).
  WriteGuard-blocked, extraction dead-letter without disposition, network and auth failures leave
  the request retryable with a reason code; dead-lettering is explicit and item-scoped. Seam: crash
  between `acquire_youtube` success and request status update → restart re-runs the item; KA
  idempotency (dedup triple, first-write-wins note) makes the re-run a traced no-op, after which
  the request completes. Restart may repeat work; it never duplicates candidates (KA-01..06
  guarantees, relied on, not reimplemented).
- **INV-YSS-4 — auth is degradable, never silently absent.** Missing/revoked/expired OAuth, or a
  missing token-store key, disables exactly the authenticated capabilities with a per-source
  `reason_code`; logged-out capabilities (RSS, backfill, explicit URLs) continue. No cursor is
  mutated by an auth failure; no empty poll result caused by auth/API failure is ever recorded as
  a successful sync. Disconnect stops future polling but deletes no acquired Mimer artifacts.
- **INV-YSS-5 — secrets never leave the private boundary.** OAuth client identifiers, refresh/access
  tokens, and token-store key material never appear in the repo, vault files, settings values,
  candidate notes, events, receipts, logs, or exception text. Settings and receipts may carry only
  non-secret references (binding ids, env-var *names*, file *paths*). Enforced by redaction-aware
  serializers plus tests on every emitting surface.
- **INV-YSS-6 — single writer per source (target state, deferred to YSS-06).** A future runner
  excludes overlapping runs with a durable single-run lease. V1 has only an explicit synchronous
  manual call and does not claim lease or concurrent-run reconciliation.
- **INV-YSS-7 — channel isolation.** dev/test/prod never share OAuth state, registry rows, cursors,
  or queues: DB-per-channel isolates the tables; token stores are per-channel app-local paths.
  Environment selection never bypasses these boundaries (`docs/ENVIRONMENTS.md`).
- **INV-YSS-8 — posture markers unconditional.** Every candidate written via this capability
  carries `authority.requires_review: true` + `review_state: draft` and enters triage at
  `captured` — inherited from KA-05 and never overridable by any sync policy or setting.
- **INV-YSS-9 — playlist title is display-only.** Source identity is playlist/channel ID + account
  binding; renaming a playlist in YouTube changes nothing. No personal playlist/channel/account
  identifier is hardcoded in product code, fixtures, or docs.

## Capability acceptance criteria

- [x] Exactly one Inbox is selected for the connected account.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_v1_selects_exactly_one_enabled_inbox`.
- [x] A new Inbox item creates one durable request before cursor publication.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_new_inbox_item_enqueues_once_at_production_call_site` and `tests/knowledge_acquisition/test_playlist_discovery.py::test_enqueue_failure_blocks_cursor_prefix`.
- [x] Failure and success status remain honest and sanitized.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_failed_poll_never_reports_empty_success` and `tests/knowledge_acquisition/test_playlist_discovery.py::test_v1_status_reports_connection_last_success_and_sanitized_error`.
- [x] Manual sync uses the production poll route.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_manual_inbox_sync_uses_production_poll_route`.
- [x] The queue/drain outcome is review-required draft candidate material, never promoted knowledge.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_inbox_sync_produces_review_required_candidate_never_knowledge`.

## Verification path

The V1 acceptance tests stub all network egress at the existing client/plugin boundaries and run
through the production registry, queue, poll, drain, and candidate call sites. `ruff check app
tests`, `mypy app`, and the focused subsystem suite are the publication baseline.

## Validation / Acceptance path

The parent feature issue is the V1 validation hub. Repository acceptance names the exact manual
routes and tests; no scheduler, rich UI, or real-account operator drill is implied by this V1.

## Relationship to GitHub issues

Parent #3915 is the pragmatic V1 validation hub. Issue #3990 supplies the final OAuth safety floor
and #3920 supplies the one-Inbox manual sync route. Deferred children and follow-ups remain
separate backlog contracts; this V1 does not claim or close them.
