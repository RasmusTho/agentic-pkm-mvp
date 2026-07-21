---
name: Sync One YouTube Inbox Playlist
description: Manual V1 discovery for one OAuth account and one enabled Inbox playlist.
task_id: YSS-05
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Cursor discipline"
parent_capability: YouTube Source Sync
prerequisites: [YSS-01, YSS-03, YSS-04]
depends_on: [ESTABLISH_SOURCE_REGISTRY_AND_SETTINGS.md, BUILD_YOUTUBE_DATA_API_CLIENT.md, ESTABLISH_DURABLE_ACQUISITION_REQUESTS.md]
can_parallelize_with: []
---

# Sync One YouTube Inbox Playlist

## Purpose

YouTube Source Sync V1 exposes one product route: connect one OAuth account,
select exactly one enabled `inbox_playlist`, run one manual sync, and inspect a
minimal connected/degraded status. The playlist is an intent surface, never
knowledge authority.

## Delivered behavior

- `app/knowledge_acquisition/playlist_discovery.py::poll_source` accepts only an
  enabled Inbox binding and calls the existing YouTube Data API client.
- Playlist-item identity remains trigger provenance; video identity remains the
  idempotent `AcquisitionRequest` identity.
- Every new item is durably enqueued before the cursor covers it. A persistence
  failure leaves the prior cursor and known set intact.
- API, auth, network, and persistence failures record and return a sanitized
  degradation rather than success, and never expose provider response text.
- Success, including ETag no-change, updates `last_success_at` and clears the
  previous error.
- `YouTubeInboxSyncV1` is the explicit manual operator route for Inbox selection,
  `sync_now`, and minimal status. It rejects a second Inbox instead of exposing
  generic multi-playlist configuration.
- The existing acquisition drain writes a `youtube_source_note` candidate with
  `authority.requires_review: true`, `review_state: draft`, and `triage_state:
  captured`. No automatic promotion call exists in this route.

## Acceptance criteria

- Exactly one Inbox is selectable; a second is rejected.
  Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_v1_selects_exactly_one_enabled_inbox`
- One new Inbox video creates one durable request with playlist-item trigger.
  Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_new_inbox_item_enqueues_once_at_production_call_site`
- Request persistence failure blocks cursor publication.
  Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_enqueue_failure_blocks_cursor_prefix`
- Failed polls preserve cursor truth and never report success.
  Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_failed_poll_never_reports_empty_success`
- Minimal status reports connection, last success, and sanitized latest error.
  Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_v1_status_reports_connection_last_success_and_sanitized_error`
- Manual sync uses the production `poll_source` call path.
  Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_manual_inbox_sync_uses_production_poll_route`
- Acquired material ends as review-required draft candidate, never promoted knowledge.
  Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_inbox_sync_produces_review_required_candidate_never_knowledge`

## Explicitly deferred

No scheduler or cadence is added. Owned/public/unlisted/Liked multi-playlist
product sync, subscriptions, RSS, Takeout, backfill, filters, analytics, broad
CLI/UI families, full-media storage, advanced receipt recovery, leases, CAS,
journals, and automatic knowledge promotion remain outside V1.

## Verification

- `pytest -q tests/knowledge_acquisition/test_playlist_discovery.py tests/knowledge_acquisition/test_source_registry.py tests/knowledge_acquisition/test_acquisition_requests.py tests/knowledge_acquisition/test_candidate_writeback.py`
- `ruff check app tests`
- `mypy app`
- `git diff --check`
