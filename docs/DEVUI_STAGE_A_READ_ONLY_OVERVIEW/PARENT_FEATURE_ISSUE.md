State: Active blocked validation hub #4741; #4742 is closed with withdrawal, #4743 is superseded,
#4744 delivered the direct-loopback Overview route, and #4745–#4749 remain blocked pending their
own prerequisites.
Doc role: Parent feature issue contract
Authority: The capability README owns stable scope and order. The live GitHub parent owns backlog and validation state after filing.
Owner: Builder System governance
Temporal class: Active validation contract
Review cadence: Event-driven
Source of truth: GitHub owns live child/receipt state; this document owns the acceptance path.
Last reviewed: 2026-08-11

# Parent feature issue — devUI Stage A Read-Only Overview

## Context

The pure `devui-overview-view.v1` composer and the direct-loopback local GET route are delivered,
but the current producer chain lacks the canonical source facts required to populate **Needs you**
and **Ready to try**. The Overview still lacks real typed navigation destinations, a governed
design, a browser shell, accessibility proof, and an owner pilot. The parent coordinates validation
only; it is never ready work.

## Scope

- Preserve the accepted no-source resolution and explicit withdrawals until a separately governed
  source contract exists.
- Treat ARO-02 as superseded and the ARO-03 direct-loopback route as delivered.
- Deliver ARO-04 through ARO-08 strictly in dependency order after their observable gates pass.
- Preserve producer-declared classification, withdrawals, evidence state, and root separation.
- Keep the delivered composer excluded and preserve the GET-only, local, read-only boundary.
- Maintain the child ledger and final receipts on this parent.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Cross-task invariants`
- `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
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
- Sync/deployment impact: single-operator local devUI only
- External boundary impact: governed Yggdrasil design handoff only
- New or changed contract: producer serialization and local route/navigation bindings; no new composer contract
- Owner-doc impact: ARO-01 may amend the owning source contract; final acceptance may reconcile current-state truth
- Transition debt impact: removes label/delivery-state inference pressure and standalone-UI reconstruction
- Fitness rule impact: source-authority, no-inference, local-GET, dead-link, browser-state, and accessibility tests

## Constraints

- The delivered composer in `app/builderops/devui_overview.py` is excluded.
- ARO-01 is closed with the accepted withdrawal, ARO-02 is superseded, and ARO-03 is delivered with
  Issue closure pending this reconciliation. ARO-04 through ARO-08 remain `agent:blocked`.
- No downstream child becomes ready from this specification or its merge alone.
- Visual children wait for the governed Yggdrasil handoff; nonvisual children do not wait on design.
- No technical label/state, provider metadata, or terminal delivery fact substitutes for explicit
  canonical category or receipt-backed `ready_to_try` evidence.

## Acceptance Criteria

- [ ] Every child has a terminal receipt or explicit superseding/withdrawal disposition.
  - Verify: runtime receipt: devui-stage-a-read-only-child-ledger.v1
- [x] The source-authority decision and no-candidate composer proof reject all
      label/done/merge/closure inference.
  - Verify: `tests/builderops/test_devui_overview.py :: test_overview_without_producer_candidates_withdraws_owner_and_ready_classifications`
- [x] The local Overview route preserves exact contract identity, direct-loopback admission, and
      GET-only behavior without producer enrichment.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_reuses_local_admission_and_exact_contract`
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_preserves_no_source_withdrawals`
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_is_get_only`
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_uses_live_composition_and_delivered_composer`
- [ ] Typed destinations preserve contract identity, remain GET-only/local, and never fabricate an
      unavailable optional SoI route.
  - Verify: `tests/api/test_devui_api.py :: test_overview_focus_reference_resolves_without_identity_drift`
  - Verify: `tests/api/test_devui_api.py :: test_overview_soi_reference_fails_closed_without_destination`
- [ ] The governed handoff and browser suite cover the complete state/accessibility matrix without
      browser classification or persistence.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_overview_accessibility_and_layout_matrix`
- [ ] The owner pilot records exact SHA, source conditions, answers, reconstruction steps, and a
      pass/fail disposition for all three zones.
  - Verify: runtime receipt: devui-stage-a-read-only-owner-pilot.v1
- [x] Current-state owner docs record the accepted withdrawals and delivered ARO-03 route without
      claiming typed navigation, design, shell, accessibility proof, or pilot delivery.
  - Verify: doc writeback at `docs/DEVUI.md :: Current state and target`
- [ ] Final current-state owner-doc acceptance follows only after all remaining capability receipts
      support the complete claim.
  - Verify: doc writeback at `docs/DEVUI.md :: Current state and target`

## Out of Scope

- Reimplementation or extension of the pure Overview composer.
- Focus/Conversation Port, SoI Evidence, delivery execution, or Builder System Control semantics.
- Any command, write endpoint, task/session store, provider-session inventory, or durable browser decision.
- Novel Product/Runtime behavior or cross-root joins.

## Suggested Validation

- Run every child's named tests and attach exact PR, merge SHA, and CI receipts here.
- Re-read live source authority, Issue labels, dependencies, and destination routes before promoting any child.
- Validate the design receipt before visual implementation and the browser matrix before the pilot.
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
| ARO-01 — Authorize Overview Source Facts | [#4742](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4742) | Closed #4742; withdrawal recorded by PR #4751 | No current source owns either Overview fact |
| ARO-02 — Enrich Overview Producer Facts | [#4743](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4743) | Superseded #4743 | The accepted no-source decision leaves no producer facts to enrich; a future source contract requires a new governed slice |
| ARO-03 — Expose Local Overview GET Route | [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744) | Delivered #4744; PR #4772 | The direct-loopback route rebuilds the production composition and calls the delivered composer without candidates |
| ARO-04 — Bind Typed Overview Navigation | [#4745](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4745) | `agent:blocked` | Revalidate its own typed-navigation contract against delivered #4744 and [#4768](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4768); absent optional SoI remains unsupported |
| ARO-05 — Validate Overview Yggdrasil Design | [#4746](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4746) | `agent:blocked` | stable #4744/#4745 fixtures plus design preflight |
| ARO-06 — Render Read-Only Overview Shell | [#4747](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4747) | `agent:blocked` | #4744/#4745 merged and #4746 accepted |
| ARO-07 — Prove Browser and Accessibility | [#4748](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4748) | `agent:blocked` | exact merged #4747 SHA |
| ARO-08 — Run Read-Only Owner Pilot | [#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) | `agent:blocked` | #4748 receipt and stable local fixtures |

<!-- builderops:epic-delivery-ledger v1 epic=#4741 -->
Ledger authority: coordination evidence only; live GitHub Issues/PRs/CI win.

| Child | Issue | PR | SHA | CI | Blocker | Next |
| --- | --- | --- | --- | --- | --- | --- |
| #4742 ARO-01 | closed / withdrawal | #4751 merged | head `d8c90761cbf9d32cf10c9471b6092466b91fad5c`<br>merge `bf2f034279c394c03529323a1a1509c756e5a0b3` | verified | no current source owns either Overview fact | preserve withdrawal until a separate source contract exists |
| #4743 ARO-02 | closed / superseded | none | none | superseded | accepted no-source decision | create a new governed slice only after a source contract exists |
| #4744 ARO-03 | delivered / closure pending | #4772 merged; #4774 blocked; #4776 recovery in progress | head `7b1f83d4a0b6bdd75071959c41146c70012a29d2`<br>merge `24371d8bf3289dad631c2986f44865794897f32c` | #4772 verified | current-state delivery-ledger reconciliation | verify and merge #4776, then supersede #4774 and close #4744 |
| #4745 ARO-04 | open / blocked | none | none | not started | #4744 + real destinations | revalidate after destination routes exist |
| #4746 ARO-05 | open / blocked | none | none | not started | stable fixtures + design preflight | run governed handoff when inputs exist |
| #4747 ARO-06 | open / blocked | none | none | not started | #4744/#4745/#4746 | revalidate after accepted handoff |
| #4748 ARO-07 | open / blocked | none | none | not started | #4747 | validate exact merged shell SHA |
| #4749 ARO-08 | open / blocked | none | none | not started | #4748 | run owner pilot after browser receipt |
<!-- /builderops:epic-delivery-ledger -->

## Verification Path

Each child resolves every named Verify target on its PR and posts a compact exact-SHA receipt to
the parent. ARO-01 records the accepted no-source withdrawal, ARO-02 is superseded, and ARO-03 is a
delivered input. Each remaining task rereads its direct dependency before any readiness transition.

## Validation / Acceptance Path

The parent remains open and `agent:blocked`. Accepted withdrawals and the delivered ARO-03 route are
stable inputs; typed destinations, design, shell, browser proof, and owner-pilot evidence remain
undelivered and must be validated in sequence. The parent never receives `agent:ready` and performs
no implementation itself.
