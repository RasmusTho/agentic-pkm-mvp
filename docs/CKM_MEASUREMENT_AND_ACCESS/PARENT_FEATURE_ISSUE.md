State: FILED as GitHub validation-parent issue #3775 with children #3776-#3781. The five owner decisions are accepted; all children remain blocked pending task/Issue-contract reconciliation and strict revalidation. GitHub is the live validation surface; this file is the checked-in parent contract.

# CKM Measurement & Access — Parent Validation Hub

## Context

The accepted CKM MVP predecessor is #3138. The audit `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md` and consensus inquiries `inq_20260715T062832Z_e73546a2` and `inq_20260715T090347Z_61c6d5e4` define the post-MVP structured access, measurement, and observation boundary. The later inquiry exposed five owner decisions; on 2026-07-15 the owner accepted the single-operator local posture, bounded human-advisory metric use under TCD, sampled compatible history, never-reused lifecycle identity, and 365-day retention with explicit pruning. Q1a remains paused until every affected contract is reconciled and revalidated. This parent is a validation hub, never an implementation pickup issue.

## Scope

Validate Q1a/Q1b, Q2, M1, O1a, and O1b as defined in `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`. Hold child receipts, cross-task verification, observation evidence, owner-doc promotion, and closure truth.

## Source Anchors

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted architecture decisions`
- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Cross-task invariants / interaction safety`
- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Capability acceptance criteria`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md :: 7. Dependency-ordered advisory backlog`

## SBS Impact

- Primary subsystem: Builder System / CES boundary — BuilderOps CKM
- Secondary subsystem(s): OEF consumes descriptive observations; SFC/CES and Correctness Kernel boundaries are explicitly preserved
- Write class: derived analytical/projection/receipt state
- Authority impact: none; observation-to-action stays behind normal promotion/Issue/PR authority
- Persistence impact: rebuildable CKM query state plus durable non-authoritative observation receipts
- Derived/rebuildable impact: snapshot/query results are derived; observations are immutable evidence records bound to rebuildable snapshots
- Human knowledge impact: none
- Memory impact: none; no runtime/user memory
- Retrieval/context impact: structured builder query only
- Sync/deployment impact: none
- External boundary impact: CLI JSON only; no HTTP/federation
- New or changed contract: CKM Measurement & Access identity, policy-bound DTO, complete snapshot/query, metric, and observation contracts
- Owner-doc impact: will-update-in-PR through children and final parent acceptance
- Transition debt impact: reduces CKM access/measurement ambiguity; D11 preserved and D12 reduced through explicit Builder learning/observation destinations
- Fitness rule impact: strengthens I-MA1..I-MA13 and associated determinism/provenance rules

## Constraints

- Parent is never claimed.
- No child becomes Ready until its spec/Issue contract is reconciled to all five accepted owner decisions and strict readiness validation passes.
- Q1 is not accepted after schemas alone.
- Read paths are side-effect free and fail closed.
- No machine ranking, gating, automated prioritization, automation, drift, prediction, or federation. A fully explained aggregate may be one small human-advisory input under the accepted policy.
- M2/O2 remain observation-gated future work.
- V1 uses bounded complete capture and has no cursor/pagination contract; later continuation requires size evidence, retained immutable snapshots, and accepted retention semantics.

## Acceptance Criteria

- [x] All five pre-implementation owner decisions are accepted.
  Verify: `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted pre-implementation owner decisions`
- [ ] Every affected task and child Issue is reconciled and revalidated against those decisions before pickup.
  Verify: child reconciliation and strict readiness receipts
- [ ] Every repo-verifiable capability criterion in the specification README is satisfied.
  Verify: child delivery receipts plus ledger at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Capability acceptance criteria`
- [ ] Q1a and Q1b jointly prove the working public contract; schemas alone never satisfy Q1.
  Verify: Q1a/Q1b issue closure receipts and `tests/builderops/ckm/test_query_service.py`
- [ ] All child owner-doc and transition-debt outcomes, D11/D12, and learning candidates are resolved.
  Verify: successor-parent closure ledger
- [ ] M2 and O2 were not pre-authorized without the required accepted evidence.
  Verify: `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Observation-gated future work` and live GitHub child map
- [ ] Final supported truth is promoted once, after acceptance.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: State` plus post-merge owner-doc receipt

## Implementation Tasks

- Q1a #3776 — `ESTABLISH_PUBLIC_SNAPSHOT_CONTRACT.md`
- Q1b #3777 — `DELIVER_SINGLE_TRANSACTION_QUERY_SERVICE.md`
- Q2 #3778 — `OPTIMIZE_BOUNDED_QUERY_PLANS.md`
- M1 #3779 — `DEFINE_METRIC_REGISTRY_AND_OBSERVATIONS.md`
- O1a #3780 — `CAPTURE_QUERY_QUESTIONS.md`
- O1b #3781 — `COMPARE_COMPATIBLE_OBSERVATIONS.md`

## Verification Path

After contract/Issue reconciliation and strict readiness validation, each child executes its exact `Verify:` targets, `ruff check app tests`, current-SHA CI, and local review. Receipts accumulate on this parent after each merge.

## Validation / Acceptance Path

Re-read current `origin/main`, all children, PRs, claims, receipts, owner-doc outcomes, and observation evidence after every merge. Close only when the full ledger is green and future work has a separate governed destination.

## Out of Scope

- Direct implementation from this parent
- General bitemporality or arbitrary historical reconstruction
- M2/O2, prediction, automation, drift, and federation

## Suggested Validation

- Run every child `Suggested Validation` command.
- Verify all child Issues are closed without `agent:*` labels and their PR merges are reachable from current `origin/main`.
- Verify the parent receipt ledger, D11/D12 outcome, and post-merge owner-doc receipt.

## Source Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Applies learning (optional)

BuilderOps inquiry `inq_20260715T062832Z_e73546a2` corrected the audit's Q1 split, identity, state-revision, read-side-effect, cursor, temporal, metrics, and lifecycle assumptions. Later inquiry `inq_20260715T090347Z_61c6d5e4` further corrected access/retention, identity lifecycle, v1 pagination, completeness, aggregate-maturity, and longitudinal-history boundaries.
