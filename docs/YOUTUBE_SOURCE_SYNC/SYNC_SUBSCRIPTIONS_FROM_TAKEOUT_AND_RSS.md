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

## What This Task Does

1. **Adopt the operator's Takeout baseline verbatim first:** land the existing
   `app/knowledge_acquisition/youtube_onboarding.py` +
   `tests/knowledge_acquisition/test_youtube_onboarding.py` + the `youtube-onboard` CLI command
   byte-identical as this slice's first commit (they exist as uncommitted operator work-in-
   progress; the PR body credits that provenance), together with the two
   `docs/KNOWLEDGE_ACQUISITION/` State-line sentences that describe them. Then extend.
2. **Registry import:** `import_takeout_registry(takeout_root, *, registry, account_binding_id=None)`
   maps parsed Takeout subscriptions/playlists onto YSS-01 bindings
   (`subscription_feed` / playlist kinds), deduplicating against existing bindings; import is
   re-runnable (Takeout is snapshot-grade reconcile input, not a live feed).
3. **RSS incremental discovery** `app/knowledge_acquisition/channel_rss_discovery.py`:
   - fetches `https://www.youtube.com/feeds/videos.xml?channel_id=UC…` (stdlib XML parsing — no
     new dependency; hardened: no external entity resolution, bounded size);
   - per-channel durable cursor (newest-published-seen + recent entry ids) in the binding row;
   - request-before-cursor discipline identical to YSS-05 (INV-YSS-1/2), the ~15-entry window
     documented as the incremental reach (past-window gaps are YSS-08's job);
   - failure semantics per INV-YSS-4 (no cursor mutation, reason-coded, never empty-success).
4. **Policy modes enforced at the discovery seam:** `discover_only` (default — traced discovery,
   no requests, no vault notes), `candidate_metadata_only`, `acquire_transcript`,
   `acquire_if_filter_matches` per contract §Acquisition policy; the conservative default and its
   consequences are what the setup surfaces (YSS-10/11) display.
5. Emits the same event family as playlist discovery (`youtube.source.discovered`,
   `youtube.sync.completed`/`degraded`) with `collection_kind=subscription_feed`.

## Concretely

```
$ python -m app.cli youtube-onboard <takeout-root> --output registry.json --json   # unchanged baseline
$ python -m app.cli youtube-sources import-takeout <takeout-root> --json
{"imported": 214, "deduplicated": 3, "policy": "discover_only"}
# scheduler (YSS-06) then polls each channel's RSS at subscriptionsPollSeconds cadence
```

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
      default and provenance `takeout_import`; re-import is idempotent.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_takeout_import_idempotent_with_conservative_default`
- [ ] RSS discovery creates requests per policy through the production enqueue call site; the
      per-channel cursor advances only per INV-YSS-1.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_rss_incremental_cursor_and_request_before_cursor`
- [ ] `discover_only` records traced discoveries without requests; switching a binding to
      `acquire_transcript` acquires only *future* discoveries (policy_version bump, no
      retroactive flood).
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_policy_modes_and_version_bump_not_retroactive`
- [ ] Feed fetch failure mutates no cursor and reports reason-coded degradation, never empty
      success.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_feed_failure_never_empty_success`
- [ ] The XML parser refuses external entities/DTDs and oversized feeds.
      Verify: `tests/knowledge_acquisition/test_channel_rss_discovery.py::test_xml_hardening_no_external_entities_bounded_size`
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
