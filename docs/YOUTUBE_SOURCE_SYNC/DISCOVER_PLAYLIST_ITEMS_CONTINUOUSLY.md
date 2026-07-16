---
name: Discover Playlist Items Continuously
description: One generic playlist discovery adapter for inbox/owned/liked/public/private playlists — playlist-item vs video identity, cross-list dedup with provenance, request-before-cursor discipline, unsupported-list refusal.
task_id: YSS-05
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Cursor discipline"
parent_capability: YouTube Source Sync
prerequisites: [YSS-01, YSS-03, YSS-04]
depends_on: [ESTABLISH_SOURCE_REGISTRY_AND_SETTINGS.md, BUILD_YOUTUBE_DATA_API_CLIENT.md, ESTABLISH_DURABLE_ACQUISITION_REQUESTS.md]
can_parallelize_with: []
---

# Discover Playlist Items Continuously

## Purpose

One adapter serves every playlist-shaped source — the inbox, other owned playlists, Liked Videos,
and explicitly added public/unlisted playlists. Differences live in registry policy (priority,
interval, mode), never in duplicated code paths.

## What This Task Does

1. New module `app/knowledge_acquisition/playlist_discovery.py` exposing
   `poll_source(binding, *, api_client, requests, registry) -> SourcePollResult`:
   - pages `playlistItems.list` newest-first with the YSS-03 client (ETag first; `304` →
     successful no-change poll);
   - separates **playlist-item identity** (`playlist_item_id`, provenance) from **video identity**
     (`item_ref`, request identity): removal/re-add or presence in N lists never mints a second
     request (INV-YSS-2 via YSS-04 `enqueue`);
   - applies the source's acquisition policy (`discover_only` → traced disposition without a
     request; filter mode per contract);
   - advances the cursor frontier only past items with durable requests or traced dispositions
     (INV-YSS-1), stopping at the known frontier or the bounded page cap (cap overflow → marked
     for backfill, never silently skipped);
   - on any API/auth/network failure: no cursor mutation, no known-set mutation, `last_error`
     with the mapped reason code, and no `youtube.sync.completed` emission (INV-YSS-4) — a failed
     poll is never an empty success.
2. Liked Videos resolve through the same adapter via the account's `LL` playlist ref; private
   playlists work iff the OAuth binding grants access, else `source_gone` degradation with legible
   copy.
3. Registration-time and poll-time refusal of Watch Later (`WL`) / Watch History (`HL`) with
   `source_unsupported` (defense in depth on top of YSS-01's registry rule).
4. Emits `youtube.source.discovered` per newly disposed item and `youtube.sync.completed` /
   `youtube.sync.degraded` per run, keys per contract.

## Concretely

```python
res = poll_source(inbox_binding, api_client=client, requests=q, registry=reg)
assert res.discovered == 2 and res.enqueued == 2 and res.not_modified is False
res2 = poll_source(inbox_binding, ...)          # unchanged playlist, ETag hit
assert res2.not_modified and res2.enqueued == 0  # cursor untouched, last_success updated
```

## Why This Matters

This is where "save to playlist on your phone" becomes a durable intent. A cursor that advances
past an unrequested item loses a video forever; a poll that treats auth failure as emptiness
poisons the frontier; item-vs-video identity confusion duplicates candidates.

## Acceptance Criteria

- [ ] A new playlist item creates exactly one AcquisitionRequest with the correct trigger
      (binding, playlist_item_id) — asserted through the production `poll_source` → `enqueue`
      call site.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_new_item_creates_exactly_one_request_at_call_site`
- [ ] The same video in two synced playlists dedups to one request with both triggers.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_cross_list_dedup_preserves_both_triggers`
- [ ] Pagination walks past page one to find unknown items behind known ones; the page cap marks
      backfill-needed instead of silently truncating.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_pagination_to_frontier_and_capped_overflow_marked`
- [ ] ETag 304 is a successful no-change poll: `last_success_at` updates, cursor and known-set do
      not.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_not_modified_poll_success_without_mutation`
- [ ] A failing poll (auth/API/network) mutates neither cursor nor known-set, records the mapped
      reason code, and emits `youtube.sync.degraded` — never `youtube.sync.completed`.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_failed_poll_never_reports_empty_success`
- [ ] Request persistence failure blocks cursor advance past that item (INV-YSS-1 partial-failure
      seam).
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_enqueue_failure_blocks_cursor_prefix`
- [ ] Liked Videos syncs through this adapter (no special-cased code path) and requires auth.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_liked_videos_via_generic_adapter_requires_auth`
- [ ] Watch Later / Watch History are refused as unsupported with legible copy at both
      registration and poll time.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_watch_later_and_history_refused_unsupported`
- [ ] `discover_only` policy records traced dispositions without creating requests.
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_discover_only_traces_without_requests`

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_playlist_discovery.py`
- `pytest -q -m "not pg"` (cursor/queue interplay is hot-path; full default suite)
- `ruff check app tests && mypy app`

## Out of Scope

Scheduling/cadence/lease (YSS-06), subscriptions/RSS (YSS-07), backfill enumeration (YSS-08),
fetch/refinement (existing KA pipeline, untouched).

## Restart / Durability Posture

Cursors and dispositions are registry-row state in the channel DB. A crash mid-poll re-enumerates
from the durable frontier on the next poll; request idempotency absorbs the overlap. Nothing about
a poll run lives only in memory.

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Cursor discipline / Event topics / Reason codes`
- `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md :: Operations (discover)`

## Related GitHub Issues

One issue. TCD hint: Opus / high — the cursor/dedup/partial-failure discipline is the
invariant-dense heart of the capability; two prior contracts (YSS-03/04) constrain it tightly.
