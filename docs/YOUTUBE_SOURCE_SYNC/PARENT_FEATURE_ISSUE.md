State: Filed — mirrors live parent feature issue #3915 (open validation hub, `agent:blocked` while children #3916–#3926 are outstanding; filed 2026-07-17).
Doc role: Parent feature issue mirror
Authority: None of its own — GitHub issue #3915 is the live validation hub; this file mirrors it for repo-local readers.

# Parent Feature Issue — YouTube Source Sync

Title: `feature: YouTube source sync — OAuth inbox playlist, continuous discovery, subscriptions (KAP Phase 4)`

Labels: `type:task`, `prio:high`, `agent:blocked` (validation hub while children are open).

## Context

Knowledge Acquisition Platform Phase 4 (`docs/KNOWLEDGE_ACQUISITION/README.md :: Phasing`) —
continuous discovery — instantiated for YouTube per the owner directive of 2026-07-16 recorded in
`docs/YOUTUBE_SOURCE_SYNC/README.md :: Decision record`. The specification directory
`docs/YOUTUBE_SOURCE_SYNC/` is the source of truth; this issue is the live validation hub.

## Scope

The capability outcome in `docs/YOUTUBE_SOURCE_SYNC/README.md :: Outcome` — not one PR. Children
deliver bounded slices; this issue collects validation receipts and the final live-acceptance run.

## Source Anchors

- `docs/YOUTUBE_SOURCE_SYNC/README.md :: Outcome`
- `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md` (all sections)
- `docs/KNOWLEDGE_ACQUISITION/README.md :: Phasing` (Phase 4 row)
- `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Discovery`

## SBS Impact

- Primary subsystem: EBF (acquisition-source discovery adapters; class 11 extension — authenticated read-only discovery surface)
- Secondary subsystem(s): PDM (registry/queue/state tables via migrations), DRI (rebuildable sync state), OEF (health/receipts/counters), CAO/HKA/SIP/GOV unchanged (existing governed candidate writeback only)
- Write class: mechanical durable (machine-side tables + governed candidate notes through the existing KA-05 seam)
- Authority impact: none — candidates stay review-required; no promotion path touched
- Persistence impact: new rebuildable-class tables (source registry, acquisition requests, sync state) via forward-only Alembic migrations
- Derived/rebuildable impact: all sync state re-derivable from source + queue; raw/derived KA artifacts unchanged
- Human knowledge impact: none directly; more review-required candidates enter triage at `captured`
- Memory impact: none
- Retrieval/context impact: none (indexing remains #2314's boundary)
- Sync/deployment impact: watcher-hosted sub-tick (no new service); per-channel isolation via existing DB/vault separation
- External boundary impact: adds OAuth (device/loopback) + YouTube Data API v3 + channel RSS to the declared egress posture; cookies remain banned
- New or changed contract: `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md` (new); `YOUTUBE_SOURCE_SPEC.md :: Discovery` revised by owner directive
- Owner-doc impact: will-update-in-children (KA README/spec State lines per slice; ARCHITECTURE/STATUS only after live acceptance)
- Transition debt impact: no effect
- Fitness rule impact: strengthens (new enforcement tests at production call sites for lease, gates, and posture markers)
- Boundary risk: OAuth secret handling and provider egress — mitigated by INV-YSS-4/5 and the secret-provisioning boundary

## Constraints

- Everything in `docs/YOUTUBE_SOURCE_SYNC/README.md :: Cross-Task Invariants / Interaction Safety` (INV-YSS-1..9).
- KAP ends at `candidate`; no auto-promotion; posture markers unconditional.
- No Heimdal observation-log writes; no new event substrate; no cookies for any YouTube surface.
- No new runtime dependencies; no personal identifiers in code/fixtures/docs.

## Acceptance Criteria

The capability acceptance criteria in `docs/YOUTUBE_SOURCE_SYNC/README.md :: Capability
acceptance criteria` (each with its Verify target), plus the completed
`OPERATOR_RUNBOOK.md :: Live acceptance` checklist recorded as a receipt on this issue.

## Implementation Tasks

`docs/YOUTUBE_SOURCE_SYNC/README.md :: Implementation tasks and execution order` — eleven bounded
task files, YSS-01..YSS-11, filed as child issues in dependency order.

## Verification Path

Per-child test suites named in each task file; full `not pg` suite on hot-path slices; `ruff` +
`mypy` per the validation baseline; child PRs post receipts here.

## Validation / Acceptance Path

Child receipts accumulate here → live acceptance on the operator runtime host (test channel)
(`OPERATOR_RUNBOOK.md :: Live acceptance`) → owner-doc promotion (ARCHITECTURE/STATUS) only after
that run passes. Items not live-verifiable while the runtime host is offline remain unchecked here and
block only the *shipped-operator-verified* claim, not child merges.

## Out of Scope

Full-media archival engine (separate `agent:needs-human` issue — ToS/rights review), Watch
Later/Watch History, other source instances, embedding/indexing (#2314).

## Suggested Validation

- `pytest -q tests/knowledge_acquisition -m "not pg"` plus each child's named suites
- `python -m app.cli youtube-sync doctor --json` on the test channel after promotion

## Source Docs

- `docs/YOUTUBE_SOURCE_SYNC/` (this directory)
- `docs/KNOWLEDGE_ACQUISITION/README.md`, `YOUTUBE_SOURCE_SPEC.md`, `SOURCE_PLUGIN_CONTRACT.md`, `REFINEMENT_PIPELINE_CONTRACT.md`
