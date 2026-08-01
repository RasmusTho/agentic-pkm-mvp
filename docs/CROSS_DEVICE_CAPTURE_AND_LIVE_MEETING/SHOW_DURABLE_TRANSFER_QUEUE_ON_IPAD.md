---
name: Show Durable Transfer Queue On iPad
description: iPad transfer-queue surface rendering the five truthful item states from durable local state plus hub answers, surviving relaunch and reconnect.
task_id: CDLM-05
github_issue: "https://github.com/RasmusTho/bifrost/issues/59"
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: [CDLM-03]
depends_on: [RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT.md]
can_parallelize_with: [CAPTURE_PHOTOS_DOCUMENTS_AND_VIDEO.md, PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS.md]
---

# Show Durable Transfer Queue On iPad

State: Delivered by Bifrost issue #59 / PR #63 on 2026-07-30 (merge commit
`e29ea38021fe37f41913627c0b46e45a212c5ac2`).

## Purpose

Make the durability contract visible. The owner must be able to look at the iPad and know, for
every capture: is it still only here, is it moving, has the hub durably accepted it, is the hub
processing it, is it done — or does it need me.

## What This Task Does

- **Queue surface** in the iPad app (regular-width layout per the B2 shell conventions) listing
  outbox items and recently completed items with exactly the five states:
  `pending locally → transferring → backend durably received → processing → complete`, plus the
  terminal-adjacent `needs attention`.
- **State derivation, not state invention (INV-CDLM-4):** the first three states derive from the
  CDLM-03 outbox store (an item shows `backend durably received` only when its receipt is
  persisted); `processing`/`complete`/`needs attention` derive from hub status answers
  (`GET /api/heimdal/capture/receipts` extended by CDLM-01's processing-status fields, and the
  CDLM-02 conflict/gap surface for session items). Unreachable hub renders last-known hub-derived
  states with a visible staleness marker — never optimistic advancement.
- **Needs-attention items are actionable:** each carries its reason (refused admission with named
  error, sequence conflict, aged-out delivery failure per JD's threshold, processing failure) and
  the safe actions (retry — always idempotent; reveal item; discard-with-confirmation only for
  items whose original still exists locally and only by explicit user action).
- **Relaunch/reconnect truth:** the surface renders identically from a cold launch (disk + one
  hub query) as from a warm session; a reconnect refreshes hub-derived states without ever
  regressing a receipt-backed `backend durably received`.
- **JD composition:** queue depth and oldest-pending age remain on the HCAP-05 health panel; this
  surface is the item-level truth. One store feeds both — no second bookkeeping.

## Concretely

Simulator walk: with the hub stopped, capture three items → all `pending locally`; start the hub →
they advance to `backend durably received`, then `processing`/`complete` as the hub answers;
force-quit anywhere → relaunch shows the same states from disk; break the network mid-meeting
session with a missing segment → the affected session item shows `needs attention` naming the
missing sequence numbers.

## Why This Matters

A durable queue nobody can see still loses trust: the owner's #4369 experience was not "data
loss" at first — it was *unknowability*. The five visible states are the product surface of
INV-CDLM-1/2/4/9; if the display can fabricate or silently skip states, the contract behind it is
unverifiable in daily use.

## Acceptance Criteria

- [ ] Every state transition rendered is backed by the required evidence (persisted receipt for
  `backend durably received`; hub answer for `processing`/`complete`), asserted at the view-model
  seam that is the production render path.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferQueueSurfaceTests.swift::testStatesRenderOnlyFromEvidence`
- [ ] Cold launch renders the queue from disk plus one receipts query, identical to the pre-kill
  state for local evidence and with staleness marking for hub-derived states.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferQueueSurfaceTests.swift::testColdLaunchRendersFromDurableEvidence`
- [ ] Reconnect refresh never regresses a receipt-backed state and never advances without new
  evidence.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferQueueSurfaceTests.swift::testReconnectRefreshIsMonotoneOverEvidence`
- [ ] Each needs-attention item names its reason and offers only safe actions; retry routes
  through the idempotent resend path; discard requires explicit confirmation and an existing local
  original.
  - Verify: bifrost `Yggdrasil/YggdrasilTests/TransferQueueSurfaceTests.swift::testNeedsAttentionIsActionableAndSafe`
- [ ] The queue journey runs as an XCUITest on the iPad destination: capture offline → observe
  `pending locally` → hub up → observe advancement to `complete`.
  - Verify: bifrost `Yggdrasil/YggdrasilUITests/TransferQueueJourneyTests.swift::testOfflineToCompleteJourney`

## How to Verify (Pre-Merge)

- bifrost CI: `TransferQueueSurfaceTests` + the iPad-destination UI journey.
- `swiftlint --strict` clean.

## Out of Scope

- The meeting surface (CDLM-09) — session items appear here as items; the meeting page is its own
  surface.
- Hub-side processing semantics (CDLM-01/02/06 own what `processing` means per kind).
- iPhone queue layout parity (functional on iPhone via the shared view-model; polish is not a
  gate).
- Notifications/badging (future bounded slice).

## Restart / Durability Posture

The surface owns no durable state; it renders CDLM-03's durable outbox plus hub answers. What
survives restart is exactly what INV-CDLM-2/4 guarantee: items, originals, receipts, and their
states. What does not survive is unfetched hub-side progress — after relaunch, `processing`/
`complete` may display as stale until the first refresh answers. The user consequence is honest
staleness, never invented progress and never a lost item.

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-4/9)
- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT.md` (the store this renders)
- `docs/HEIMDAL_CAPTURE_CLIENT/DEVICE_HEALTH_PANEL_WITH_GAP_LOG.md` (JD aggregate panel this composes with)
- `docs/MIMER_IPAD_THINKING_CANVAS/README.md` (iPad shell/layout conventions)

## Related GitHub Issues

One bifrost issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/SHOW_DURABLE_TRANSFER_QUEUE_ON_IPAD").
TCD hint: Sonnet / high — the render-only-from-evidence discipline and monotone-refresh rules are
where a cheap implementation would quietly lie.
