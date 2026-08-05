State: Active blocked validation hub #4163. DDO-01 through DDO-04 are delivered; DDO-05 through DDO-07 and the deferred autonomous CI retry #4466 remain blocked. The 2026-08-05 architecture reconciliation makes scheduled bug delivery a strict-serial DDO profile rather than a separate state machine.
Doc role: Parent validation-hub contract
Authority: The capability README owns stable decomposition. The live GitHub parent owns backlog and validation state after filing.

# Parent feature issue — deterministic delivery orchestration

## Context

The delivered epic-runner baseline reduces some repeated work but still relies on a model coordinator
to reconstruct state, decide routine transitions, wait, and route results. The capability specified
in `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md` provides immediate fast-lane value and then
progressively replaces routine coordination with deterministic compilation, reduction,
reconciliation, and receipts.

## Scope

- Deliver DDO-01 through DDO-07 in dependency order.
- Keep the parent as the live validation and TCD evidence hub.
- Reuse #3229 and BuilderOps control-plane/outbox work rather than reopening or duplicating it.
- Integrate the separately governed review-severity and known-defect contracts.
- Promote owner docs only after the final acceptance task.
- Reconcile the seven observed scheduled bug runs into DDO-05 through DDO-07 and the existing
  #3603/#3604/#3793/#4217/#4466 dependencies without creating a duplicate bug-runner task.

## Source Anchors

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Capability boundary`
- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Capability acceptance`

## SBS Impact

- Primary subsystem: Builder System / CES boundary
- Secondary subsystem(s): none
- Write class: governance/docs/process plus BuilderOps operational state
- Authority impact: changes delivery initiation and coordination while preserving GitHub/repo delivery authority
- Persistence impact: repository contracts, BuilderOps plan/journal/receipt records, and GitHub delivery evidence
- Derived/rebuildable impact: CKM and epic-run views remain rebuildable projections
- Human knowledge impact: none
- Memory impact: no Product/Runtime or user-memory impact
- Retrieval/context impact: bounded worker context packs replace broad epic-history replay
- Sync/deployment impact: BuilderOps control-plane integration only; no Product deployment change
- External boundary impact: GitHub REST, CI, and bounded model-worker invocation
- New or changed contract: request/preview/approved-initiation chain, DeliveryPlan, reducer
  event/effect and lifecycle-control contracts, provider-neutral worker runtime, active-run
  projection, acceptance profile, and terminal receipt
- Owner-doc impact: follow-up final owner-doc promotion through DDO-07
- Transition debt impact: reduces D11 concentration in model coordination and D12 loss of TCD evidence
- Fitness rule impact: adds deterministic state-machine, idempotency, crash, and authority-boundary tests

## Constraints

- Parent is a validation hub and never receives `agent:ready`.
- DDO-05 through DDO-07 remain serially dependency-blocked until their live prerequisite and
  readiness reconciliation succeeds.
- GitHub, dispatcher leases, PR heads, CI, review, merge, and closure evidence remain authoritative.
- Do not create a new journal/outbox when the #3792 substrate satisfies the required conformance.
- Do not mutate the static CKM Direction B cockpit.
- Do not weaken any current-SHA CI, review, merge, or closure gate.

## Acceptance Criteria

- [ ] Every child has a terminal delivery receipt or an explicitly superseding owner decision.
  - Verify: child ledger on this Issue.
- [ ] Capability-level invariants and partial-failure paths are evidenced.
  - Verify: `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Capability acceptance`.
- [ ] Fast-lane and full-kernel TCD targets are evaluated without hiding quality regressions.
  - Verify: DDO-07 acceptance report and linked `DeliveryReceipt.v2` artifacts.
- [ ] CKM initiation and receipt projection preserve the non-authority boundary.
  - Verify: `tests/builderops/ckm/test_delivery_bridge.py`.
- [ ] One 4–8 Issue scheduled `type:bug` pilot is strictly serial, resumes before selection,
  survives concurrent ticks and detached-worktree bootstrap, and releases only after the complete
  terminal/owner-doc receipt chain.
  - Verify: `autonomous_bug_delivery_pilot.v1` linked here.
- [ ] Owner-doc truth is promoted only after capability acceptance.
  - Verify: final owner-doc PR and post-merge receipts linked here.

## Out of Scope

- Product/Runtime orchestration.
- A second BuilderOps control plane or outbox.
- A new hosted dashboard.
- Automatic issue prioritization from CKM maturity or gap scores.
- A prompt-local bug lifecycle state machine or universal serial gate over unrelated direct manual
  pickup.
- Weakening review, merge, or closure policy.

## Suggested Validation

- Resolve every child `Verify:` target on its closing PR.
- Maintain a child/PR/merge/TCD receipt ledger in the parent.
- Run DDO-07 fault injection and live pilot only after DDO-01 through DDO-06 deliver.
- Close the parent only after owner-doc promotion is resolved.

## Source Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/audits/AUTONOMOUS_BUG_DELIVERY_ARCHITECTURE_2026-08-05.md`

## Applies learning (optional)

- BuilderOps inquiry `inq_20260727T075022Z_55bcca22`
- BuilderOps AgentWorklog `awl_20260727085216_ab1a8cf3`
- BuilderOps PromotionIntent `prom_20260727085216_b24bc805`

## Implementation Tasks

| Task | Issue | Live lifecycle on 2026-08-05 | Dependency |
| --- | --- | --- | --- |
| DDO-01 — independent-Issue fast lane | #4164 | delivered/closed | #4161 |
| DDO-02 — carrier-neutral delivery contracts | #4165 | delivered/closed by PR #4176 | none |
| DDO-03 — immutable plan compiler | #4166 | delivered/closed by PR #4226 | #4165 |
| DDO-04 — deterministic reducer | #4167 | delivered by PR #4252; autonomous CI retry deferred to #4466 | delivered #4164 and #4166 |
| DDO-05 — BuilderOps reconciliation binding | #4168 | blocked; also unblocks #4466 | #3603/#3604 readiness and #3793 timing must be reconciled; reuses #3792 |
| DDO-06 — CKM initiation/receipt bridge | #4169 | blocked | #4165 and #4168 |
| DDO-07 — TCD/recovery acceptance | #4170 | blocked | #4164 through #4169 plus #3604 terminal integration, #4217 substantive evidence, and cutover proof |

Live lifecycle and receipt state is maintained on parent
[#4163](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4163).

## Verification Path

Each child resolves its own test/doc/receipt targets and posts a compact validation receipt here.

## Validation / Acceptance Path

DDO-07 evaluates the live pilot, crash recovery, TCD targets, quality non-regression, and owner-doc
promotion. The parent remains open until that evidence is complete.
