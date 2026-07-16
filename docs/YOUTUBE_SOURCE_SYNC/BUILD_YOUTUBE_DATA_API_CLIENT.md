---
name: Build YouTube Data API Client
description: Bounded read-only Data API v3 client over httpx — playlists/playlistItems/channels, pagination, ETag conditional requests, quota accounting, host allowlist.
task_id: YSS-03
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Egress posture"
parent_capability: YouTube Source Sync
prerequisites: [YSS-02]
depends_on: [BIND_YOUTUBE_ACCOUNT_WITH_OAUTH.md]
can_parallelize_with: [SYNC_SUBSCRIPTIONS_FROM_TAKEOUT_AND_RSS.md]
---

# Build YouTube Data API Client

## Purpose

One bounded, allowlisted, quota-accounted client is the only code that speaks the Data API. Every
discovery adapter consumes it; no other module builds Google URLs or parses Google JSON.

## What This Task Does

1. New module `app/knowledge_acquisition/youtube_api_client.py` over `httpx` (no new deps),
   constructor-injected with a `TokenProvider` (YSS-02 interface; stubbable so this slice tests
   without OAuth):
   - `list_my_playlists()` → owned playlists (id, title, itemCount) with pagination.
   - `list_playlist_items(playlist_id, *, etag=None, page_token=None)` → items
     (`playlist_item_id`, `video_id`, `position`, `published_at`, `title`), `next_page_token`,
     `etag`, or a `NotModified` marker on HTTP 304 via `If-None-Match`.
   - `get_my_channel()` → channel id/title (binding display + Liked Videos ref `LL`).
   - `maxResults=50`, minimal `part`/`fields` selections per call.
2. Guardrails: absolute host allowlist (`www.googleapis.com` only; redirects off-list refused);
   item-ref shape validation before URL construction (video ids, `PL*/UU*/LL*/UC*`); request
   timeout; bounded response size; bounded pages per invocation with an explicit
   `pagination_truncated` marker (never silent).
3. Error taxonomy mapped to contract reason codes: 401/`invalid_grant` → auth codes (delegated to
   the token provider), 403 quota family → `quota_exhausted`, 404/private → `source_gone`,
   5xx/timeout → `api_unavailable`, transport → `network_error`. Structured
   `YouTubeApiError(reason_code, status, detail)` — detail never echoes request auth headers or
   response bodies verbatim.
4. Durable per-UTC-day quota accounting (contract §Quota accounting): one counter row in the
   channel DB (memory fallback), incremented per call, exposed as
   `quota_status() -> {spent_today, budget, exhausted}`.

## Concretely

```python
client = YouTubeApiClient(token_provider=stub, quota=quota_store)
page = client.list_playlist_items("PL<fixture>")
assert page.items[0].video_id and page.etag
assert client.list_playlist_items("PL<fixture>", etag=page.etag).not_modified  # 304 path
```

Fixtures are recorded-shape JSON documents (no live egress, no personal identifiers).

## Why This Matters

An unbounded or unallowlisted HTTP layer is the SSRF/runaway-quota surface of this feature; a
mis-mapped 403 would read as "playlist is empty" and corrupt downstream decisions. The client is
where those failure classes are killed once.

## Acceptance Criteria

- [ ] Pagination walks multi-page fixtures completely and reports the page-cap truncation marker
      when the bound is hit.
      Verify: `tests/knowledge_acquisition/test_youtube_api_client.py::test_pagination_and_bounded_page_cap`
- [ ] `If-None-Match` sends the ETag and a 304 maps to `NotModified` (no item parsing).
      Verify: `tests/knowledge_acquisition/test_youtube_api_client.py::test_etag_not_modified_roundtrip`
- [ ] Non-allowlisted hosts and malformed collection/item refs are refused before any request.
      Verify: `tests/knowledge_acquisition/test_youtube_api_client.py::test_host_allowlist_and_ref_validation`
- [ ] Error mapping: quota 403 → `quota_exhausted`; 404/private → `source_gone`; 5xx →
      `api_unavailable`; auth failures surface through the token provider path — each with
      secret-free detail.
      Verify: `tests/knowledge_acquisition/test_youtube_api_client.py::test_error_taxonomy_mapping_secret_free`
- [ ] Quota accounting increments per call, persists across client instances, and flips
      `exhausted` on the quota error family.
      Verify: `tests/knowledge_acquisition/test_youtube_api_client.py::test_quota_accounting_durable_and_exhaustion`

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_youtube_api_client.py`
- `ruff check app tests && mypy app`

## Out of Scope

Discovery/cursor logic (YSS-05), scheduling (YSS-06), OAuth flows themselves (YSS-02), any write
scope or mutation API, RSS/Takeout (YSS-07).

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Egress posture / Quota accounting / Reason codes`

## Related GitHub Issues

One issue. TCD hint: Sonnet / high — bounded external-API client with fixture-verifiable behavior;
the error-taxonomy mapping is the risk center.
