# Governed Vault Profile parent feature issue

State: Filed live validation hub #4944. It is `agent:blocked`, never direct pickup work, and does not claim runtime delivery.

## Context

Accepted YouTube Source Note v2 D4 requires a vault-wide governed profile owner contract before #4117 can consume an approved same-scope projection. This parent keeps the cross-capability acceptance evidence without turning the target-state specification into a shipped runtime claim.

## Scope

Validate the three serial implementation tasks that establish governed profile authority, durable state and receipt binding, confirmed ProfileAgent writes, and same-scope consumer projection/no-profile behavior.

## Source Anchors

- `docs/GOVERNED_VAULT_PROFILE/README.md :: Capability boundary`
- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: D4 — resolved direction 2026-07-25`

## SBS Impact

- Primary subsystem: MEM
- Secondary subsystem(s): GOV, HKA, WSP, CAO, RCA
- Write class: authority-bearing target-state runtime contract
- Persistence impact: future durable Profile Note, proposal state, versions, and receipts
- Derived/rebuildable impact: future consumer projection rebuildable from approved profile versions and receipts
- New or changed contract: governed vault-profile owner contract
- Owner-doc impact: follow-up promotion only after parent acceptance
- Transition debt impact: reduces the unowned D4 prerequisite for #4117
- Boundary risk: candidate data, inference, or unreceipted state must never become approved profile authority

## Constraints

- Keep one ProfileAgent-only approved-content writer and one vault-wide Profile Note.
- Do not claim target runtime behavior as shipped while this parent is open.
- Preserve direct owner-correction precedence and visible reconciliation.

## Acceptance Criteria

- [ ] GOVPROF-01 through GOVPROF-03 are delivered in dependency order with parent validation receipts.
  - Verify: `docs/GOVERNED_VAULT_PROFILE/README.md :: Capability acceptance`
- [ ] Parent acceptance records a current, end-to-end invariant proof for approved same-scope consumer admission and restart/partial-failure behavior.
  - Verify: doc writeback at `docs/GOVERNED_VAULT_PROFILE/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`
- [ ] Any current-state owner-doc claim is promoted only after the parent accepts the evidence.
  - Verify: doc writeback at `docs/GOVERNED_VAULT_PROFILE/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`

## Out of Scope

- Implementing ProfileAgent, vault persistence, Panel handling, WriteGuard integration, receipts, consumer projection, or #4117 in this parent/specification slice.

## Suggested Validation

- Re-read child issue contracts and parent validation receipts after each merged child.
- Run the child task `Verify:` targets on their exact PR heads.
- Run the final task's end-to-end acceptance proof before owner-doc promotion.

## Source Docs

- `docs/GOVERNED_VAULT_PROFILE/README.md`
- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md`

## Applies learning (optional)

Backlog reconciliation found #4117 correctly bounded as a consumer while its source-authorized profile producer/owner capability was unowned.

## Implementation Tasks

1. `DEFINE_PROFILE_AUTHORITY_AND_PERSISTENCE.md` — GOVPROF-01 / #4945.
2. `GOVERN_PROFILE_UPDATE_PROPOSALS_AND_CONFIRMED_WRITES.md` — GOVPROF-02 / #4946, blocked by GOVPROF-01 / #4945.
3. `PROJECT_APPROVED_PROFILE_TO_SAME_SCOPE_CONSUMERS.md` — GOVPROF-03 / #4947, blocked by GOVPROF-02 / #4946.

## Verification Path

Each child runs its exact task-level test(s). The final child additionally runs an integration-equivalent path proving consumer admission requires an approved, receipt-bound, same-scope version and returns explicit no-profile behavior otherwise.

## Validation / Acceptance Path

The parent remains open and blocked until all child PRs are merged and their exact-head receipts are posted here. The final child records the end-to-end partial-failure/restart proof, then invokes governed parent closure and owner-doc promotion review; no profile runtime claim is made merely by filing this specification.
