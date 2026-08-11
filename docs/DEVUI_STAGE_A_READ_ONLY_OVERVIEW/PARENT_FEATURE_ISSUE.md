State: Active blocked validation hub #4741; children #4742–#4749 are filed and no implementation delivery is claimed.
Doc role: Parent feature issue contract
Authority: The capability README owns stable scope and order. The live GitHub parent owns backlog and validation state after filing.
Owner: Builder System governance
Temporal class: Active validation contract
Review cadence: Event-driven
Source of truth: GitHub owns live child/receipt state; this document owns the acceptance path.
Last reviewed: 2026-08-12
Last verified against: `origin/main` `989a8d73d52b75c3a038ba1d3f93c78e03d98065` and live GitHub
Issue/PR state; the delivery ledger below records the exact PR heads and merge commits it cites.

# Parent feature issue — devUI Stage A Read-Only Overview

## Context

The pure `devui-overview-view.v1` composer is delivered, but the current producer chain lacks the
canonical source facts required to populate **Needs you** and **Ready to try**. The Overview also
lacks a local GET route, real typed navigation destinations, a governed design, a browser shell,
accessibility proof, and an owner pilot. The parent coordinates validation only; it is never ready
work.

## Scope

- Resolve the exact source authority and serialization boundary before producer code.
- Deliver ARO-02 through ARO-08 strictly in dependency order after their observable gates pass.
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
- ARO-01 is `agent:needs-human`; all other children are `agent:blocked` at filing.
- No downstream child becomes ready from this specification or its merge alone.
- Visual children wait for the governed Yggdrasil handoff; nonvisual children do not wait on design.
- No technical label/state, provider metadata, or terminal delivery fact substitutes for explicit
  canonical category or receipt-backed `ready_to_try` evidence.

## Acceptance Criteria

- [ ] Every child has a terminal receipt or explicit superseding/withdrawal disposition.
  - Verify: runtime receipt: devui-stage-a-read-only-child-ledger.v1
- [ ] The source-authority decision and producer proof reject all label/done/merge/closure inference.
  - Verify: `tests/builderops/test_devui_composition.py :: test_overview_candidates_require_explicit_source_owned_facts`
- [ ] The local route and typed destinations preserve contract identity and remain GET-only/local.
  - Verify: `tests/api/test_devui_api.py :: test_overview_route_is_local_get_only_and_preserves_typed_destinations`
- [ ] The governed handoff and browser suite cover the complete state/accessibility matrix without
      browser classification or persistence.
  - Verify: `tests/companion_ui/test_devui_overview_journeys.py :: test_overview_accessibility_and_layout_matrix`
- [ ] The owner pilot records exact SHA, source conditions, answers, reconstruction steps, and a
      pass/fail disposition for all three zones.
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
| ARO-01 — Authorize Overview Source Facts | [#4742](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4742) | `agent:needs-human` | Owner accepts the exact source/serialization contract |
| ARO-02 — Enrich Overview Producer Facts | [#4743](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4743) | `agent:blocked` | accepted #4742 transportable through bounded current producer chain |
| ARO-03 — Expose Local Overview GET Route | [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744) | delivered | PR #4772 proves the admitted direct-loopback route → live composition → delivered no-candidate composer |
| ARO-04 — Bind Typed Overview Navigation | [#4745](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4745) | `agent:blocked` | #4744 plus delivered [#4768](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4768) local Focus route and optional SoI destination |
| ARO-05 — Validate Overview Yggdrasil Design | [#4746](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4746) | `agent:blocked` | stable #4743/#4744/#4745 fixtures plus design preflight |
| ARO-06 — Render Read-Only Overview Shell | [#4747](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4747) | `agent:blocked` | #4744/#4745 merged and #4746 accepted |
| ARO-07 — Prove Browser and Accessibility | [#4748](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4748) | `agent:blocked` | exact merged #4747 SHA |
| ARO-08 — Run Read-Only Owner Pilot | [#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) | `agent:blocked` | #4748 receipt and stable local fixtures |

<!-- builderops:epic-delivery-ledger v1 epic=#4741 -->
Ledger authority: coordination evidence only; live GitHub Issues/PRs/CI win.

| Child | Issue | PR | SHA | CI | Blocker | Next |
| --- | --- | --- | --- | --- | --- | --- |
| #4742 ARO-01 | closed / withdrawal recorded | #4751 | head `d8c90761cbf9d32cf10c9471b6092466b91fad5c`; merge `bf2f034279c394c03529323a1a1509c756e5a0b3` | merged receipt | no current source owns either Overview fact | preserve explicit withdrawals |
| #4743 ARO-02 | open / blocked | none | none | not started | #4742 | revalidate after accepted source contract |
| #4744 ARO-03 | open / blocked | #4772; supporting #4789 | #4772 head `7b1f83d4a0b6bdd75071959c41146c70012a29d2`; merge `24371d8bf3289dad631c2986f44865794897f32c`. #4789 head `c5f4fab08d58b5efb8d52a457bfa9eaf555824bd`; merge `989a8d73d52b75c3a038ba1d3f93c78e03d98065` | route delivered; contract/CI-selection recovery merged | parent validation remains open | later verification-and-closure for #4744 |
| #4745 ARO-04 | open / blocked | none | none | not started | #4744 + real destinations | revalidate after destination routes exist |
| #4746 ARO-05 | open / blocked | none | none | not started | stable fixtures + design preflight | run governed handoff when inputs exist |
| #4747 ARO-06 | open / blocked | none | none | not started | #4744/#4745/#4746 | revalidate after accepted handoff |
| #4748 ARO-07 | open / blocked | none | none | not started | #4747 | validate exact merged shell SHA |
| #4749 ARO-08 | open / blocked | none | none | not started | #4748 | run owner pilot after browser receipt |
<!-- /builderops:epic-delivery-ledger -->

## Verification Path

Each child resolves every named Verify target on its PR and posts a compact exact-SHA receipt to
the parent. ARO-01 records the accepted source contract; each downstream task rereads its direct
dependency before any readiness transition.

## Validation / Acceptance Path

The parent remains open and `agent:blocked` while source facts, producer output, route, typed
destinations, design, shell, browser proof, and owner-pilot evidence are validated together. The
parent never receives `agent:ready` and performs no implementation itself.
