State: FILED — parent feature issue [#3788](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3788) is the authoritative backlog/validation hub. It remains `agent:blocked` while ADR-0062/specification is unmerged and while child slices are outstanding.
Doc role: Specification companion (parent issue draft/pointer)
Authority: `README.md` owns task decomposition. The live GitHub parent owns backlog/validation state.

# Parent feature issue — BuilderOps independent control plane

## Context

BuilderOps must become a permanent API-first enabling system on Demerzel. Current state embeds its
unauthenticated routes in Product FastAPI and fragments operational authority across BuilderOps
SQLite, dispatcher SQLite/JSONL, and file-first run/receipt stores. ADR-0062 selects one independent
authenticated service and PostgreSQL authority while preserving GitHub/repo delivery authority.

## Scope

- deliver and validate BCP-01 through BCP-07 from `docs/BUILDEROPS_CONTROL_PLANE/`;
- act as the validation hub rather than an implementation pickup;
- reuse #3603 for Demerzel orchestration and #3690 for owner-doc enactment; and
- reconcile #3686/PR #3695 as migration evidence with a superseded SQLite target.

## Source Anchors

- `docs/adr/ADR-0010-builderops-vault-authority-boundary.md :: Decision`
- `docs/AGENT_ISSUE_DISPATCHER.md :: Current-State Honesty`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Environment matrix`

## SBS Impact

Builder System capability with Product/Builder boundary cleanup. It extends the Builder System
enabling-system deployment model and removes misplaced Product Runtime ownership; it does not add or
reshape a Product SBS subsystem.

## Constraints

- Parent is a validation hub and never receives `agent:ready`.
- No runtime child becomes ready before ADR-0062/specification merges.
- GitHub/repo delivery authority remains unchanged.
- No production direct-DB or local SQLite fallback is allowed.
- Product Runtime owns no BuilderOps lifecycle or trust material at closure.

## Acceptance Criteria

- [ ] All BCP-01 through BCP-06 implementation issues are merged and their receipts linked here.
  Verify: child-issue/PR ledger in this issue.
- [ ] Capability acceptance in `docs/BUILDEROPS_CONTROL_PLANE/README.md :: Capability acceptance criteria`
  is fully evidenced.
  Verify: BCP-06 cutover receipt and linked test/restore/merge receipts.
- [ ] BCP-07 updates current-state owner docs and closes superseded backlog truth.
  Verify: `docs/BUILDEROPS_CONTROL_PLANE/OWNER_DOC_ENACTMENT_AND_CLOSURE.md :: Acceptance Criteria`.

## Out of Scope

- replacing GitHub Issues/PRs/CI as delivery authority;
- making BuilderOps a Product Runtime subsystem;
- external multi-tenant BuilderOps; and
- requiring a separate source repository before the ADR-0062 source-extraction triggers fire.

## Suggested Validation

- keep a child/PR/receipt ledger on the parent;
- require the BCP-06 end-to-end cutover and restore-drill receipts before BCP-07; and
- close only through BCP-07's parent-closure handoff.

## Source Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/audits/BUILDEROPS_CONTROL_PLANE_2026-07-15.md`

## Implementation Tasks

| Task | GitHub work item | Initial state |
|---|---|---|
| BCP-01 | [#3792](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3792) | `agent:blocked` on ADR/spec acceptance |
| BCP-02 | [#3790](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3790) | `agent:blocked` on BCP-01 |
| BCP-03 | [#3789](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3789) | `agent:blocked` on BCP-01 |
| BCP-04 | [#3791](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3791) | `agent:blocked` on BCP-02 |
| BCP-05 | Existing #3603 / PR #3620 | blocked on BCP-02/04 contract adaptation |
| BCP-06 | [#3793](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3793) | `agent:blocked` on BCP-03/04/05 |
| BCP-07 | Existing #3690 | `agent:blocked` on BCP-06 |

Task specifications and dependency order are linked from
`docs/BUILDEROPS_CONTROL_PLANE/README.md :: Implementation tasks`.

## Verification Path

Each child runs the exact `Verify:` targets in its specification and posts a compact receipt here.
BCP-01 through BCP-05 must each be independently mergeable and verifiable; BCP-06 consumes their
receipts in the test cutover and authoritative cutover gate.

## Validation / Acceptance Path

After BCP-06, attach the Demerzel end-to-end API/executor/GitHub readback receipt, legacy-import
reconciliation, independent Product/BuilderOps lifecycle proof, and backup restore drill. Only then
may #3690/BCP-07 promote current-state owner docs and close this parent.
