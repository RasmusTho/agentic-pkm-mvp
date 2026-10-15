---
name: Sync Subscriptions from Takeout and RSS
description: Adopt the Takeout onboarding baseline into the registry, add per-channel RSS/Atom incremental discovery with durable cursors, and conservative per-mode acquisition policies.
task_id: YSS-07
source_anchor: "docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Cursor discipline"
parent_capability: YouTube Source Sync
prerequisites: [YSS-01, YSS-04]
depends_on: [ESTABLISH_SOURCE_REGISTRY_AND_SETTINGS.md, ESTABLISH_DURABLE_ACQUISITION_REQUESTS.md]
can_parallelize_with: [BUILD_YOUTUBE_DATA_API_CLIENT.md]
---

# Sync Subscriptions from Takeout and RSS

## Purpose

Subscriptions follow the 2026-07 research decision unchanged: Takeout bootstraps the list,
per-channel RSS feeds discover incrementally with zero auth and zero quota, and rare backfill
(YSS-08) repairs gaps. This task turns the existing metadata-only Takeout bootstrap into live,
policy-governed subscription discovery.

## Producer prerequisite

Issue #5722 delivered the bounded metadata-only acquisition producer. Issue #3922 continues only
YSS-07: Takeout registry import, RSS discovery, cursor management, and the four declared policy
modes. YSS-06 scheduling and YSS-08 backfill remain separate deferred work; this continuation
does not expand the one-Inbox user-facing V1 route.

## What This Task Does

1. **Adopt the operator's Takeout baseline verbatim first:** take the recoverable baseline from
   commit `fe037d7cc29574847bd1089af46f4b3bfafaee0b` and land the existing
   `app/knowledge_acquisition/youtube_onboarding.py` +
   `tests/knowledge_acquisition/test_youtube_onboarding.py` + the `youtube-onboard` CLI command
   byte-identical as this slice's first commit (the PR body credits that provenance), together
   with the two `docs/KNOWLEDGE_ACQUISITION/` State-line sentences that describe them. Then extend.
2. **Registry import:** `import_takeout_registry(takeout_root, *, registry, account_binding_id=None)`
   maps parsed Takeout subscriptions/playlists onto YSS-01 bindings
   (`subscription_feed` / playlist kinds), deduplicating against existing bindings; re-import
   preserves existing cursor/policy/state and does not delete rows absent from the new snapshot.
   Playlist account-binding requirements are checked before the first write.
3. **RSS incremental discovery** `app/knowledge_acquisition/channel_rss_discovery.py`:
   - fetches the fixed
     `https://www.youtube.com/feeds/videos.xml?channel_id=UC…` URL (stdlib XML parsing — no new
     dependency; redirects, non-UTF-8 input, DTDs/entities, and oversized feeds are refused);
   - per-channel durable cursor (newest-published-seen + recent entry ids) in the binding row;
   - request-before-cursor discipline identical to YSS-05 (INV-YSS-1/2), the ~15-entry window
     documented as the incremental reach (past-window gaps are YSS-08's job);
   - failure semantics per INV-YSS-4 (no cursor mutation, reason-coded, never empty-success).
4. **Policy modes enforced at the discovery seam:** `discover_only` (default — traced discovery,
   no requests, no vault notes), `candidate_metadata_only`, `acquire_transcript`, and
   `acquire_if_filter_matches`. Filters are non-empty, validated, ANDed criteria: lowercase valid
   ISO 639-1 primary language codes, optional finite nonnegative inclusive duration bounds, and
   exact `UC` channel IDs. Channel-only filtering performs no metadata egress; language/duration
   checks use the existing metadata-only yt-dlp path. Missing required metadata degrades with
   `filter_metadata_unavailable` and does not advance the cursor. Effective policy changes bump the
   registry-owned version once; no-op changes do not bump it, and changes apply only to future
   discoveries. An existing request with the same deterministic identity but a different policy
   snapshot fails closed with `policy_conflict`.
5. Emits `youtube.source.discovered` and the YSS-07-only per-source
   `youtube.sync.completed`/`degraded` receipts with `collection_kind=subscription_feed`. Cursor
   publication and completion receipt share a canonical DB transaction. This does not add a
   scheduler, global receipt, or product setup surface.

## Concretely

The byte-identical `youtube-onboard` command remains a metadata-only export bootstrap. Registry
adoption is through `import_takeout_registry`; subscription polling is exposed by the YSS-07
module for a future scheduler or operator surface. This task adds no `youtube-sources` CLI command
and makes no scheduling-cadence claim.

## Why This Matters

Subscriptions are the volume path (hundreds of channels). A default that auto-acquires everything
floods the vault with review-required notes; a cursor that trusts the RSS window silently loses
videos; a parser that resolves external entities is an SSRF hole. Policy, window honesty, and
hardened parsing are the slice.

## Acceptance Criteria

- [ ] The adopted Takeout baseline lands byte-identical (module, test, CLI command) and its tests
      still pass unmodified.
      Verify: `tests/knowledge_acquisition/test_youtube_onboarding.py::test_parse_takeout_deduplicates_subscriptions_and_playlists`
- [ ] Takeout import creates deduplicated `subscription_feed` bindings with `discover_only`
      default and provenance `takeout_import`; re-import preserves existing state and is idempotent.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_takeout_import_idempotent_with_conservative_default`
- [ ] RSS discovery creates requests per policy through the production enqueue call site; the
      per-channel cursor advances only per INV-YSS-1.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_rss_incremental_cursor_and_request_before_cursor`
- [ ] `discover_only` records traced discoveries without requests; effective policy changes bump
      `policy_version` once, no-op changes do not bump it, and only future discoveries are affected.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_policy_modes_and_version_bump_not_retroactive`
      Verify: `tests/knowledge_acquisition/test_source_registry.py::test_policy_update_versioning_and_filter_validation`
- [ ] All four modes have production discovery-call-site coverage: metadata-only reaches its
      delivered candidate producer without transcript fetch; valid ANDed language/duration/channel
      filters enqueue effective transcript requests only on match; missing filter metadata degrades
      without cursor advance; nonmatches trace discovery only; unsupported requests fail loudly.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_all_four_modes_use_truthful_production_drain`
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_filter_metadata_failure_no_cursor`
- [ ] A shared request identity with an incompatible effective policy fails closed in either
      arrival order and under concurrent enqueue; the existing snapshot is preserved and the new
      discovery cursor does not advance.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_incompatible_shared_request_policies_degrade_in_both_arrival_orders`
      Verify: `tests/knowledge_acquisition/test_acquisition_requests.py::test_memory_backend_passes_shared_contract`
      Verify: `tests/knowledge_acquisition/test_playlist_discovery.py::test_shared_request_policy_conflict_is_sanitized_and_traced_for_inbox`
- [ ] Feed fetch failure mutates no cursor and reports reason-coded degradation, never empty
      success.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_feed_failure_never_empty_success`
- [ ] The XML parser refuses external entities/DTDs and oversized feeds.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_xml_hardening_no_external_entities_bounded_size`
- [ ] Per-source sync receipts validate against registered schemas, use outbox idempotency, and
      never report false completion after a failed run.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_sync_events_match_registered_schema_and_failure_never_completes`
- [ ] A completion receipt write failure and unavailable named-database transaction never advance
      the cursor or report a successful sync.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_completion_receipt_write_failure_never_advances_cursor`
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_named_database_without_receipt_transaction_fails_before_cursor_advance`
- [ ] YSS-07 policy, filter, cursor, and event contracts are concrete in the owner spec; current
      state records this bounded continuation without claiming scheduling, backfill, or a wider
      V1 user-facing outcome.
      Verify: doc writeback at `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Acquisition policy`
      Verify: doc writeback at `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Event topics`
      Verify: doc writeback at `docs/YOUTUBE_SOURCE_SYNC/README.md :: Decision record`
      Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Discovery`
- [ ] Docs State lines for the adopted baseline land with the code in the same PR.
      Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/README.md :: State` and `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md :: State`

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_youtube_onboarding.py tests/knowledge_acquisition/test_channel_rss_discovery.py`
- `pytest -q -m "not pg"`
- `ruff check app tests && mypy app`

## Out of Scope

Backfill/gap repair and its preview gate (YSS-08), scheduling cadence (YSS-06 — this slice's
functions are invoked by it), OAuth (subscriptions need none), Data API subscription enumeration
(Takeout + RSS is the ruled mechanism; the API path for subscriptions stays not-used).

## Restart / Durability Posture

Bindings and RSS cursors are durable registry rows. Takeout import state is re-derivable from the
export itself. The RSS window limitation is durable-honest: items missed while offline longer than
the window are *known* to need backfill (surfaced by YSS-09), never silently assumed synced.

## Related Docs

- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Acquisition policy / Cursor discipline / Egress posture`
- `docs/KNOWLEDGE_ACQUISITION/RESEARCH_2026-07.md :: 4. Subscription discovery`
- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Discovery`

## Related GitHub Issues

One issue. TCD hint: Sonnet / high — parsers, import mapping, and policy plumbing over
already-fixed contracts; XML hardening and window honesty are the review focus.
