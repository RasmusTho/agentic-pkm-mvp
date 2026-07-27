## Change Lane
- [ ] Docs authoring lane
- [ ] Governance lane

Final-Review-Rounds: 1

Docs authoring applies only to docs-only changes in approved docs-authoring surfaces. It must not be used for code, runtime behavior, contracts, shipped reality, or implementation writeback.
Governance lane applies to bounded repository-governance changes such as repo-local skills, PR/issue policy, and lightweight enforcement for docs/governance workflows. It may include repo-meta governance scripts and focused tests, but it must not be used for product/runtime implementation.

<!-- Issue-backed only: replace this comment with exactly one line like `Governing-Issue: #123`. -->

## Linked Issue
<!-- Issue-backed only: add one closing-keyword line for every fully delivered issue. -->

Both lines are required for a single-issue PR and identify the same issue. For an approved multi-issue PR, keep exactly one governing identity, reference the governing parent when it remains open, and use closing keywords only for fully delivered issues.
Leave both fields blank only when no governing issue exists, including issue-free docs-authoring or governance-lane PRs.

## SBS Impact
Classify Product/Runtime System, Builder System, or boundary work per `docs/architecture/SBS_OPERATING_MODEL.md` §3, then fill SBS impact per §4; use "none"/"unaffected" explicitly rather than leaving a field blank.
- Primary subsystem:
- Secondary subsystem(s):
- Write class:
- Authority impact:
- Persistence impact:
- Derived/rebuildable impact:
- Human knowledge impact:
- Memory impact:
- Retrieval/context impact:
- Sync/deployment impact:
- External boundary impact:
- New or changed contract:
- Owner-doc impact:
- Transition debt impact:
- Fitness rule impact:
- Boundary risk:

## Owner-Doc Writeback
Resolve to exactly one (`docs/architecture/SBS_OPERATING_MODEL.md` §9). A comment or "to update later" note is not an acceptable resolution.
- [ ] No owner-doc change implied.
- [ ] Owner-doc updated in this PR.
- [ ] Owner-doc follow-up issue created and linked.

## Summary
-
-

## BuilderOps Routing
- Records/projections/receipts: <ids or "none">
- Reason: <why no BuilderOps material was created, or what was routed>

## Notes
- State any residual risks, follow-ups, or assumptions.
- Escalate to the repo-wide non-PG suite only through `scripts/run_with_host_lease.py --resource pytest-not-pg ...`; see `docs/development/DEV_WORKFLOW.md :: Validation baseline`.
