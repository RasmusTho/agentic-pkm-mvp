State: Active blocked validation hub #4741; ARO-01 is closed with its withdrawal recorded, ARO-02
is closed/superseded, ARO-03/#4744 is closed and delivered, ARO-04/#4745 and ARO-06/#4747 are
closed as superseded by #4836, ARO-05/#4746 is closed after its accepted constrained-reuse receipt,
ARO-07/#4748 is closed after exact final-main proof, and ARO-08/#4749 remains blocked. Recovery
children #4834, #4836, #4838, and #4841 preserve the serial connected-shell path.
Doc role: Parent feature issue contract
Authority: The capability README owns stable scope and order. The live GitHub parent owns backlog and validation state after filing.
Owner: Builder System governance
Temporal class: Active validation contract
Review cadence: Event-driven
Source of truth: GitHub owns live child/receipt state; this document owns the acceptance path.
Last reviewed: 2026-08-30
Last verified against: `origin/main` `b1b71f205ff57da2df99a6747102066e5e74b350` and live GitHub
state for #4741–#4749, #4768, #4833, #4834, #4835, #4836, #4838, #4841, and #4857; the delivery
ledger below records the exact PR heads, merge commits, and proof receipt it cites.

# Parent feature issue — devUI Stage A Read-Only Overview

## Context

The pure `devui-overview-view.v1` composer, admitted direct-loopback Overview GET route, and Focus
API route are delivered. The current producer chain still lacks a selectable source-owned **Now**
subject; **Needs you** and **Ready to try** remain withdrawn. The connected shell is delivered by
#4836 after #4746 accepted its exact `yggdrasil-constrained-reuse.v1` binding, and its candidate was
verified by #4833/#4842 before merge. The separate #4748 receipt then authenticated the exact
five-node browser/accessibility proof at final post-merge `main` `M=c7c57300f2ec241778061078e7ad585454f0b880`.
The parent coordinates validation only; it is never ready work and claims no deployed or accepted
UI. #4841 supplies the narrow production Companion transport for the existing two read APIs only;
it supplies neither a page nor a visual destination.

## Scope

- Preserve the ARO-01 withdrawal and ARO-02 supersession; do not infer producer delivery from either.
- Preserve closed ARO-03 route evidence, then deliver the recovery-connected design, shell,
  exact-ref browser proof, and pilot strictly after their observable gates pass.
- Preserve producer-declared classification, withdrawals, evidence state, and root separation.
- Keep the delivered composer excluded and preserve the GET-only, local, read-only boundary.
- Maintain the child ledger and final receipts on this parent, including the production-pilot
  identity/evidence contract after #4748.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Cross-task invariants`
- `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
- `docs/DEVUI.md :: Owner-experience acceptance criteria`
- `docs/plans/DEVUI_IMPLEMENTATION.md :: Stage A — see: coherent read-only devUI`

## SBS Impact

- Primary subsystem: Builder System / devUI owner experience
- Secondary subsystem(s): BuilderOps Cockpit and delivery evidence producers; Product/Runtime SoI boundary by typed reference only
- Write class: target specification followed by bounded Builder System read/UI work
- Authority impact: one explicit source-authority decision; no devUI authority gained
- Persistence impact: none
- Derived/rebuildable impact: Overview remains per-request and rebuildable
- Human knowledge impact: none
- Memory impact: no Product/Runtime or user-memory impact
- Retrieval/context impact: no new retrieval or context store
- Sync/deployment impact: the future ARO-08 consumes an existing Demerzel production deployment
  receipt only (`pkm-prod`, `PKM_ENVIRONMENT=prod`, Midgård); it does not deploy or promote
- External boundary impact: none for independently reviewed exact shipped reuse; governed live
  Yggdrasil design handoff for novel, mixed, unknown, extension, or out-of-envelope work
- New or changed contract: source-owned Now serialization plus one connected Overview/Focus visual
  path; no new composer authority
- Owner-doc impact: ARO-01 may amend the owning source contract; final acceptance may reconcile current-state truth
- Transition debt impact: removes label/delivery-state inference pressure and standalone-UI reconstruction
- Fitness rule impact: source-authority, no-inference, local-GET, dead-link, browser-state, and accessibility tests

## Constraints

- The delivered composer in `app/builderops/devui_overview.py` is excluded.
- ARO-01 is closed with its withdrawal recorded; ARO-02 is closed/superseded; ARO-03/#4744 is
  closed and delivered; ARO-04/#4745 and ARO-06/#4747 are closed as superseded; ARO-05/#4746 and
  ARO-07/#4748 are closed after their separate accepted evidence gates; and ARO-08/#4749 remains
  blocked on its own serial pilot prerequisites.
- No downstream child becomes ready from this specification or its merge alone.
- Connected visual work waits for stable #4834 plus delivered #4768 and one accepted applicable
  receipt from #4746: either `yggdrasil-constrained-reuse.v1` or
  `yggdrasil-design-handoff.v1`. Exact shipped reuse does not run or claim the live system/token
  preflight; any novel, mixed, unknown, extension, or out-of-envelope delta must pass it.
- #4836 must consume #4841's `127.0.0.1:8113` host publish, local-Host/no-forwarded admission,
  exact two-GET/header-stripping contract, and direct-loopback-or-server-derived Companion API
  admission unchanged. Port `18000` remains direct diagnostics, never a browser page origin.
- No technical label/state, provider metadata, or terminal delivery fact substitutes for explicit
  canonical category or receipt-backed `ready_to_try` evidence.
- ARO-08 remains serially blocked after #4748 until the repaired source contract, Demerzel
  authentication/access, #4747 server-supplied Focus selectors, and receipt-sourced deployed
  URL/SHA are available. If the pilot uses a `pkm-test` supplement, its disposable-state
  classification is also required; the production-only path has no supplemental-state
  prerequisite. It never invents a URL or deployed SHA.

## Acceptance Criteria

- [ ] Every child has a terminal receipt or explicit superseding/withdrawal disposition.
  - Verify: runtime receipt: devui-stage-a-read-only-child-ledger.v1
- [ ] The source-authority decision and producer proof reject all label/done/merge/closure inference.
  - Verify: `tests/builderops/test_devui_composition.py :: test_overview_candidates_require_explicit_source_owned_facts`
- [ ] The local route and typed destinations preserve contract identity and remain GET-only/local.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_is_local_get_only_and_preserves_typed_destinations`
- [ ] The accepted applicable design evidence and browser suite cover the complete connected
      state/accessibility matrix without browser classification or persistence.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_overview_accessibility_and_layout_matrix`
- [ ] The owner pilot records exact SHA, source conditions, answers, reconstruction steps, and a
      pass/fail disposition for all three zones; it proves the receipt-sourced deployed SHA across
      CI/review/deploy receipt, `/version`, `/api/health.version`, and gateway marker. If a
      `pkm-test` supplement is used, it records the disposable-state Overview → server-supplied
      Focus → return Playwright journey with zero effects, errors, storage, or unauthorized writes
      and durable trace/screenshot/checksum/manifest evidence plus owner acknowledgement. If no
      supplement is used, the production-only evidence records the applicable final-M proof and
      that no test state was created. The pilot ledger may preserve candidate provenance when
      available, but readiness does not require a candidate-to-final cross-run binding.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [ ] Current-state owner docs change only after all capability receipts support the claim.
  - Verify: doc writeback at `docs/DEVUI.md :: Current state and target`

## Out of Scope

- Reimplementation or extension of the pure Overview composer.
- Focus/Conversation Port, SoI Evidence, delivery execution, or Builder System Control semantics.
- Any command, write endpoint, task/session store, provider-session inventory, or durable browser decision.
- Novel Product/Runtime behavior or cross-root joins.

## Suggested Validation

- Run every child's named tests and attach exact PR, merge SHA, and CI receipts here.
- Re-read live source authority, Issue labels, dependencies, and destination routes before promoting any child.
- Validate the design receipt before visual implementation, the browser matrix before the pilot, and
  the ARO-08 receipt-sourced production identity/disposable-state prerequisites before any owner
  journey.
- Close the parent only after the ledger and owner-doc truth are reconciled.

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/plans/DEVUI_IMPLEMENTATION.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`

## Applies learning (optional)

- The Phase 1 audit supplies advisory hostile-test boundaries only; its stale task list is not authority.

## Implementation Tasks

| Task | Issue | Initial label | Dependency / exact next trigger |
| --- | --- | --- | --- |
| ARO-01 — Authorize Overview Source Facts | [#4742](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4742) | closed; withdrawal recorded by PR #4751 | No current source owns either Overview fact |
| ARO-02 — Enrich Overview Producer Facts | [#4743](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4743) | closed / superseded | The ARO-01 no-source withdrawal leaves no producer facts to enrich; a future source contract requires a new governed slice |
| ARO-03 — Expose Local Overview GET Route | [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744) | closed / delivered | PR #4772 proves the admitted direct-loopback route → live composition → delivered no-candidate composer |
| ARO-04 — Bind Typed Overview Navigation | [#4745](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4745) | closed / superseded | Delivered through the canonical connected shell #4836 / PR #5157; no separate successor is required |
| ARO-05 — Validate Connected Overview and Focus Yggdrasil Evidence | [#4746](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4746) | closed / accepted constrained reuse | Accepted exact `yggdrasil-constrained-reuse.v1` evidence for the merged #4836 candidate |
| ARO-06 — Render Read-Only Overview Shell | [#4747](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4747) | closed / superseded | Delivered through the canonical connected shell #4836 / PR #5157; no separate successor is required |
| ARO-07 — Prove Browser and Accessibility | [#4748](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4748) | closed / exact-main proof | Authenticated #4833 exact five-node receipt at final post-merge `main` `M=c7c57300f2ec241778061078e7ad585454f0b880` |
| ARO-08 — Run Read-Only Owner Pilot | [#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) | `agent:blocked` | serially after #4748 and #4857: boolean-only #4835 prerequisite, Demerzel prod access, acknowledged promotion plan, receipt-sourced deployed URL/SHA, and conditional disposable-state classification |

<!-- builderops:epic-delivery-ledger v1 epic=#4741 -->
Ledger authority: coordination evidence only; live GitHub Issues/PRs/CI win.

| Child | Issue | PR | SHA | CI | Blocker | Next |
| --- | --- | --- | --- | --- | --- | --- |
| #4742 ARO-01 | closed / withdrawal recorded | #4751 | head `d8c90761cbf9d32cf10c9471b6092466b91fad5c`; merge `bf2f034279c394c03529323a1a1509c756e5a0b3` | merged receipt | no current source owns either Overview fact | preserve explicit withdrawals |
| #4743 ARO-02 | closed / superseded | #4751 withdrawal evidence | head `d8c90761cbf9d32cf10c9471b6092466b91fad5c`; merge `bf2f034279c394c03529323a1a1509c756e5a0b3` | no producer delivery | no current source facts to enrich | create a new governed slice only after a source contract exists |
| #4744 ARO-03 | closed / delivered | #4772; supporting #4789 and #4792 | #4772 head `7b1f83d4a0b6bdd75071959c41146c70012a29d2`; merge `24371d8bf3289dad631c2986f44865794897f32c`. #4789 head `c5f4fab08d58b5efb8d52a457bfa9eaf555824bd`; merge `989a8d73d52b75c3a038ba1d3f93c78e03d98065`. #4792 head `031dbfaa2d6d474bf02e5d778ffb252f0879ae97`; merge `a7f945cb591f24c4f5d85d048187f92a8ed91211` | route delivered; contract/CI-selection and `Via`-admission recoveries merged | none | preserve receipt in parent acceptance |
| #4745 ARO-04 | closed / superseded | #5157 | candidate head `47e56110adbdae30548cd313a66b4e2d26311f7e`; merge `b79d8778b8d49233bad22335d393efa12712e040` | merged receipt | typed-navigation behavior delivered in the canonical connected shell | preserve the closed predecessor as superseded history |
| #4746 ARO-05 | closed / accepted constrained reuse | #5157 / #4746 receipt | candidate head `47e56110adbdae30548cd313a66b4e2d26311f7e`; merge `b79d8778b8d49233bad22335d393efa12712e040` | accepted `yggdrasil-constrained-reuse.v1` receipt | design/provenance gate complete | preserve the accepted receipt; #4748 remains a separate final-main proof |
| #4747 ARO-06 | closed / superseded | #5157 | candidate head `47e56110adbdae30548cd313a66b4e2d26311f7e`; merge `b79d8778b8d49233bad22335d393efa12712e040` | merged shell receipt | shell delivered in the canonical connected path | preserve the closed predecessor as superseded history |
| #4748 ARO-07 | closed / exact-main proof | #4833 receipt; closure comment on #4748 | final `M=c7c57300f2ec241778061078e7ad585454f0b880`; #4833 run `33304261671` | authenticated exact five-node `devui-stage-a-exact-sha-state-matrix.v1` receipt | browser/accessibility proof complete; no deployment claim | preserve proof-only boundary; #4749 owns production pilot |
| #4749 ARO-08 | open / blocked | none | no pilot run | awaiting #4857, boolean-only #4835 prerequisite, deployment identity, promotion acknowledgement, and owner evidence | run production-only or conditionally supplemented pilot only after every applicable receipt; POST-PASS current-state writeback is separate |
<!-- /builderops:epic-delivery-ledger -->

## Verification Path

Each child or governed recovery replacement resolves every named Verify target on its PR and posts
a compact exact-SHA receipt to the parent. Before #4746 readiness, re-read merged #4834, delivered
#4768, and the accepted #4838 receipt authority; validate its one actual receipt without inferring
the other route. #4833 verified the published #4836 candidate at its exact ref before merge, and
#4748 subsequently verified the merged final-main SHA. ARO-08 additionally takes its deployed
URL/SHA only from shell/browser/deployment receipts and records
every required identity/effect proof in the structured owner-pilot ledger.
Before #4836 pickup, re-read merged #4841 and bind its current transport regression evidence;
#4833 verifies the published #4836 candidate at its exact ref before merge.

## Validation / Acceptance Path

The parent remains open and `agent:blocked` while source facts, producer output, route, connected
design evidence, shell, exact-ref browser proof, deployment identity, and owner-pilot evidence are
validated together. The parent never receives `agent:ready` and performs no implementation itself.
An accepted constrained-reuse receipt does not claim live MCP selection, project creation, or token
parity; a live receipt must be genuine. Only a PASS pilot may begin a separate `docs/DEVUI.md`
current-state writeback; no current-state claim is made by this target-state contract.
