# Governed Vault Profile parent feature issue

State: Accepted and closed validation hub #4944 (2026-09-29). It was a validation hub, never direct pickup work; current-state claims are limited to the delivered GOVPROF-01 through GOVPROF-03 evidence below.

## Context

Accepted YouTube Source Note v2 D4 required a vault-wide governed profile owner contract before #4117 could consume an approved same-scope projection. That prerequisite was delivered and accepted under this parent on 2026-09-29; the separate #4117 renderer remains downstream work.

## Scope

Validate the three serial implementation tasks that establish governed profile authority, durable state and receipt binding, confirmed ProfileAgent writes, and same-scope consumer projection/no-profile behavior.

## Source Anchors

- `docs/GOVERNED_VAULT_PROFILE/README.md :: Capability boundary`
- `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: D4 — resolved direction 2026-07-25`

## SBS Impact

- Primary subsystem: MEM
- Secondary subsystem(s): GOV, HKA, WSP, CAO, RCA
- Write class: authority-bearing runtime contract, delivered through GOVPROF-01–03
- Persistence impact: durable Profile Note, proposal state, versions, and receipts
- Derived/rebuildable impact: consumer projection rebuildable from approved profile versions and receipts
- New or changed contract: governed vault-profile owner contract
- Owner-doc impact: promoted after parent acceptance through the parent-acceptance docs PR
- Transition debt impact: delivered the D4 profile prerequisite and enables separate consumer task #4117
- Boundary risk: candidate data, inference, or unreceipted state must never become approved profile authority

## Constraints

- Keep one ProfileAgent-only approved-content writer and one vault-wide Profile Note.
- Do not promote current-state claims before parent evidence acceptance; after acceptance, limit them to the exact GOVPROF-01 through GOVPROF-03 proof.
- Preserve direct owner-correction precedence and visible reconciliation.

## Acceptance Criteria

- [x] GOVPROF-01 through GOVPROF-03 are delivered in dependency order with parent validation receipts.
  - Verify: `docs/GOVERNED_VAULT_PROFILE/README.md :: Capability acceptance`
- [x] Parent acceptance records a current, end-to-end invariant proof for approved same-scope consumer admission and restart/partial-failure behavior.
  - Verify: doc writeback at `docs/GOVERNED_VAULT_PROFILE/PARENT_FEATURE_ISSUE.md :: Validation / Acceptance Path`
- [x] Current-state owner-doc claims were promoted only after parent acceptance.
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

Backlog reconciliation originally found #4117 correctly bounded as a consumer while its source-authorized profile producer/owner capability was unowned; GOVPROF-01–03 delivered that prerequisite.

## Implementation Tasks

1. `DEFINE_PROFILE_AUTHORITY_AND_PERSISTENCE.md` — delivered GOVPROF-01 / #4945 by PR #5731.
2. `GOVERN_PROFILE_UPDATE_PROPOSALS_AND_CONFIRMED_WRITES.md` — delivered GOVPROF-02 / #4946 by PR #5733 after GOVPROF-01.
3. `PROJECT_APPROVED_PROFILE_TO_SAME_SCOPE_CONSUMERS.md` — delivered GOVPROF-03 / #4947 by PR #5735 after GOVPROF-02.

## Verification Path

Each child runs its exact task-level test(s). The final child additionally runs an integration-equivalent path proving consumer admission requires an approved, receipt-bound, same-scope version and returns explicit no-profile behavior otherwise.

## Validation / Acceptance Path

Parent acceptance was recorded on 2026-09-29 after all three children were merged in dependency order and their exact-head validation receipts were posted:

- GOVPROF-01 / #4945 — PR #5731; head `761284d3f92680f7d16deb186ff128d2baf81cf7`, merge `68b024f62dfd20688ec065c7e6edcb282c4461b4`; [parent receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4944#issuecomment-5882484583).
- GOVPROF-02 / #4946 — PR #5733; head `f8e46f837cb40a5e0872d0661eb55f6fad609160`, merge `6bc4d45947523ecd241603c9654956c16a80df6d`; [parent receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4944#issuecomment-5888930860).
- GOVPROF-03 / #4947 — PR #5735; head `eac8cd261ee21ab1c2c135fd217568c8682a0c55`, merge `1bc1f5a1e55559eadfdf0bad71d1656e1a8b8de7`; [parent receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4944#issuecomment-5890059740).

The combined proof composes exact-head Verify coverage: ProfileAgent-only authority and receipt-bound versions; direct-owner precedence through restart and partial-write failure; proposal, confirmation, write, and truthful receipt-failure behavior; and rebuildable consumer admission requiring a live approved-body digest and explicit matching scope, with no-profile results for invalid or unavailable states. The read-only consumer adapter does not implement the separate #4117 four-part YouTube renderer. This is a cross-slice evidence matrix, not a claim that one test executes all three slices in a single process. Parent acceptance is recorded at [#4944](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4944#issuecomment-5890141625).

Owner-doc promotion followed that acceptance and is carried by this parent-acceptance docs PR. The final-child handoff is the #4947 receipt above; the parent closure receipt records the delivered children, their PRs and receipts, repo-verifiable acceptance, and downstream follow-up in #4117.
