State: FILED — the parent feature issue is live as #3320 (Backlog, agent:blocked validation hub). GitHub is the authoritative backlog/validation surface; this file is the archived draft + local pointer. Children were filed agent:blocked: #3321 (CAL-01, dependency-free head — flips to agent:ready when this spec PR merges to main), #3323 (CAL-02, blocked until CAL-01/#3321 merges), #3324 (CAL-03, blocked until CAL-01/#3321 and CAL-02/#3323 merge), #3322 (CAL-04, blocked until CAL-01/#3321 merges).
Doc role: Parent feature issue draft (feature-breakdown lane)
Temporal class: operational
Review cadence: event-driven (issue lifecycle)
Source of truth: GitHub issue #3320; this file is the archived draft + local pointer
Last reviewed: 2026-07-07

# [Decision Calibration] parent: revisit decisions, stamp outcomes, aggregate a calibration profile

Title on GitHub (once filed): `[Decision Calibration] parent: revisit past decisions, stamp outcomes, aggregate a calibration profile`

## Context

The decision-receipt architecture (`docs/DECISION_RECEIPT_LOG/`, feature #2969) delivered a
vault-canonical, WriteGuard-gated, Postgres-projected append-only log — but for GOV governance
verdicts (`review`/`evaluate`/`classification`), not for the owner's own decisions. The owner's actual
decision journal is the `decision_record` Human Knowledge Artifact
(`docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md :: decision_record`), and it is currently
write-only: nothing revisits it, stamps an outcome, or aggregates a calibration profile. This capability
closes that loop, extending the receipt-log **architecture pattern** (not its table) over the owner's
own decisions. See `docs/DECISION_CALIBRATION/README.md :: Grounding` for the disambiguation this
breakdown had to make explicitly — **flagged for owner confirmation, not yet ratified as a standing
decision** the way the ideation capture itself was ratified.

This parent is the **live validation hub** once filed: children post validation receipts here; it is
`agent:blocked` (not a pickup issue) while children are outstanding.

## Scope

The capability outcome — not one PR: a separate append-only outcome-receipt model referencing the
original decision (CAL-01); a time-based revisit scheduler with a provisional interval ladder,
settings-governed posture, at most one pending revisit per decision (CAL-02); a companion UI card that
answers through the governed write path or defers on dismiss (CAL-03); a rebuildable, human-readable
calibration profile aggregated over outcome receipts, hazard-safe against the known
Postgres-only-row-loss failure mode (CAL-04).

## Source Anchors

- `docs/DECISION_CALIBRATION/README.md` (spec: tasks, grounding, cross-task invariants, capability ACs)
- `docs/research/yggdrasil-closed-loops-ideation.md :: 2. Decision calibration`
- `docs/DECISION_RECEIPT_LOG/README.md`; `docs/adr/ADR-0019-governed-writes-decision-token-authority-receipt.md`
- `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md :: decision_record`

## SBS Impact

- Primary subsystem: GOV (outcome stamping is a new receipt/accountability record)
- Secondary subsystem(s): HKA (`decision_record` artifacts being revisited), PDM (JSONL-append +
  Postgres-projection persistence mechanics), DRI (calibration profile as a rebuildable rollup), HIX
  (companion UI revisit card)
- Write class: mixed — mechanical durable via guarded seam (outcome receipts, dismissal ledger);
  derived-rebuildable (calibration profile / `decision_outcomes` projection)
- Authority impact: none beyond existing contracts; an outcome stamp is a human judgment recorded
  through a governed write, not a new authority class
- Persistence impact: new vault receipt-log family (`receipts/decision_outcomes/`,
  `receipts/decision_revisit_dismissals/`), two new rebuildable Postgres tables, one generated markdown
  vault surface (`calibration/calibration-profile.md`)
- Derived/rebuildable impact: both projections rebuild from vault-canonical receipts; the calibration
  profile additionally requires a pre-rebuild completeness check (INV-CAL-F)
- Human knowledge impact: revisits quote the owner's own `decision_record` notes back to him; no new
  HKA artifact class is introduced
- Memory impact: none — this capability does not touch MEM
- Retrieval/context impact: none in v1; a future capability could feed calibration signals into
  retrieval, out of scope here
- Sync/deployment impact: two Alembic migrations (`decision_outcomes`, dismissal ledger projection if
  DB-backed); no watcher change
- External boundary impact: none
- New or changed contract: outcome-receipt schema (CAL-01); revisit-ladder settings key (CAL-02);
  companion route additions (CAL-03)
- Owner-doc impact: none until acceptance; then a `docs/DECISION_RECEIPT_LOG/README.md` cross-link and
  a `docs/COGNITIVE_PROSTHESIS_CHARTER.md` §2 (Reflect) reference
- Transition debt impact: reduces (fills the "receipt log is write-only" gap the ideation capture names)
- Fitness rule impact: follow-up — a future fitness probe could assert outcome-receipt immutability the
  way `observation_episode_binding_survives` does for ERE; not proposed as a blocking gate in v1

## Constraints

Original `decision_record` notes and any GOV judgment receipt stay immutable — no code path in this
capability may edit either. Outcome vocabulary is exactly `held` / `partly_held` / `did_not_hold` /
`unknown_yet` plus an optional free-text note; no additional vocabulary values without a spec update.
WriteGuard asserted at every new write seam (outcome receipt append, dismissal ledger append). No
episode-closure trigger in v1 (Episode Resolution Engine dependency, named future work). No automated
outcome inference — human-stamped only.

## Acceptance Criteria

The capability-level ACs in `docs/DECISION_CALIBRATION/README.md :: Capability acceptance criteria`,
each with its `Verify:` target there — including append-only immutability, at-most-one-pending-revisit,
governed-write answer path, dismiss-without-outcome, hazard-safe rebuild refusal, projection-outage
survival, and the readable calibration-profile writeback.

## Implementation Tasks

`docs/DECISION_CALIBRATION/` — CAL-01..CAL-04 per the README execution order: 1 → (2 ‖ 4) → 3.

## Verification Path

Per-task `Verify:` targets (each task file couples ACs to `How to Verify (Pre-Merge)`); the WriteGuard
call-site assertions run in the ordinary `not pg` suite; the projection-rebuild and hazard-refusal tests
are `pg`-marked and run against a real Postgres instance.

## Validation / Acceptance Path

After each child merges: a validation receipt comment here (test run links, and for CAL-03, a real
screenshot/UAT of the card per the companion UI local UAT pattern). After CAL-03 merges: an end-to-end
walk — seed a `decision_record` note with a past `decided_on` date, run the scheduler, answer the
resulting card through the companion UI, confirm the outcome receipt and calibration profile update.
Acceptance → owner-doc cross-links (no owner doc currently claims this capability as shipped, so no
promotion PR is strictly required, but the DECISION_RECEIPT_LOG README should note the extension) and
parent closure.

## Out of Scope

Episode-closure-triggered revisits (dependent on Episode Resolution Engine); automated outcome
inference; briefing delivery (`docs/DAILY_BRIEFING/`, future seam); editing/re-scoring original decision
receipts or `decision_record` notes; adding a `confidence` field to the `decision_record` template.

## Suggested Validation

`pytest -q -m "not pg"` per child; `pytest -q -m pg tests/jobs/test_calibration_projection_rebuild.py
tests/integration/test_calibration_rebuild_from_log_only.py` on a real Postgres instance; companion UI
local UAT for CAL-03 (`render_index_html` static render); receipts to this issue once filed.

## Source Docs

`docs/DECISION_CALIBRATION/README.md`; `docs/research/yggdrasil-closed-loops-ideation.md`;
`docs/DECISION_RECEIPT_LOG/README.md`; `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md`.
