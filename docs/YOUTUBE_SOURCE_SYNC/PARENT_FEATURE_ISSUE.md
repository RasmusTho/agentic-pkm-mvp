State: Mirrors live parent feature issue #3915 after the pragmatic V1 re-contract of 2026-07-21.
Doc role: Parent feature issue mirror
Authority: GitHub issue #3915 is the live validation hub; this file is a repo-local mirror only.

# Parent Feature Issue — YouTube Source Sync V1

Title: `feature: YouTube source sync V1 — OAuth Inbox playlist → review candidates`

## Outcome

One operator can connect one YouTube account, select exactly one ordinary owned playlist as the
Inbox, invoke one manual sync, inspect connected/degraded state plus last success and a sanitized
latest error, and receive review-required draft candidates for newly discovered videos. The route
never promotes external content directly into knowledge.

No automatic cadence is claimed because the shipped runtime has no ordinary reusable cadence hook
for this adapter. Scheduling, leases, multi-playlist product support, Liked Videos,
subscriptions/RSS/Takeout, backfill, analytics, broad CLI/UI, full-media storage, and generalized
recovery remain deferred.

## Active delivery set

| Work | Issue / PR | Result |
| --- | --- | --- |
| Registry/settings, OAuth, Data API, acquisition queue | #3916–#3919 | Delivered reusable foundations |
| OAuth safety floor | #3990 / PR #4030 | Delivered: token-first connection authority and transient revoke retry preservation |
| One-Inbox manual sync | #3920 / PR #4014 | Final V1 slice: request-before-cursor, sanitized status, review-required candidate proof |

The former YSS-06..11 issues and #3993 are deferred traceability records, not active V1 children or
pickup candidates. They require a fresh owner directive and bounded re-contract before work resumes.

## Acceptance criteria

- One account connects and selects one Inbox without exposing credentials.
  Verify: merged #3990 OAuth safety tests plus
  `tests/knowledge_acquisition/test_playlist_discovery.py::test_v1_selects_exactly_one_enabled_inbox`.
- A manual sync turns new Inbox items with available material into review-required draft
  candidates, never knowledge.
  Verify: `test_new_inbox_item_enqueues_once_at_production_call_site` and
  `test_inbox_sync_produces_review_required_candidate_never_knowledge` in
  `tests/knowledge_acquisition/test_playlist_discovery.py`.
- OAuth/API/network/persistence failures remain honest and secret-free.
  Verify: merged #3990 status/disconnect tests plus
  `test_failed_poll_never_reports_empty_success`, `test_enqueue_failure_blocks_cursor_prefix`, and
  `test_registry_persistence_failures_are_sanitized`.
- The minimal operator route exposes connection, last success, and latest sanitized error.
  Verify: `test_v1_status_reports_connection_last_success_and_sanitized_error` and
  `test_manual_inbox_sync_uses_production_poll_route`.

## Safety and authority

- OAuth credentials stay in the existing encrypted local token store and never enter repository,
  vault, log, event, receipt, exception, or status output.
- The token store is positive connection authority; the binding is configuration/status projection.
- Every acquisition outcome stays `authority.requires_review: true`, `review_state: draft`, and
  `triage_state: captured` until a separate human-governed promotion path acts.
- Official Google OAuth and YouTube Data API boundaries only; no cookies or scraping.

## Validation and closure

Child delivery receipts accumulate on live #3915. After PR #4014 passes exact-head CI and two clean
independent reviews, verification explicitly closes #3920, records its child receipt, validates the
four parent criteria above against #3990 and #3920 evidence, and closes #3915 through
`docs/development/PARENT_ISSUE_CLOSURE.md`. Deferred records stay untouched.

## Source anchors

- live GitHub parent #3915, owner directive 2026-07-21
- `docs/YOUTUBE_SOURCE_SYNC/README.md :: Outcome`
- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Shipped V1 product boundary`
- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Discovery`
