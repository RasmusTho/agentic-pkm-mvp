State: Accepted target-state breakdown with blocked validation parent #4741; ARO-01 is closed with
its withdrawal recorded, ARO-03 is delivered as the direct-loopback local route, and ARO-04–08
remain blocked; Focus-route prerequisite #4768 is delivered.
Doc role: Capability specification and source-authorized task decomposition for the remaining read-only devUI Stage A Overview.
Authority: `docs/DEVUI.md` owns owner experience and Overview semantics; `docs/plans/DEVUI_IMPLEMENTATION.md` owns Stage A order. This directory owns only the bounded delivery contracts and validation path.
Owner: Builder System governance
Temporal class: Strategic target state with an explicit delivered-input ledger
Review cadence: Event-driven
Source of truth: Owner documents own intended behavior; source systems and receipts own facts; GitHub, Git, CI, and merged code own delivery truth.
Last reviewed: 2026-08-12
Last verified against: `origin/main` `989a8d73d52b75c3a038ba1d3f93c78e03d98065`, live GitHub
state for #4742–#4749 and #4786, and merged PRs #4751, #4772, and #4789.

# devUI Stage A Read-Only Overview

## Outcome

Complete the remaining read-only Overview path without reimplementing the delivered
`devui-overview-view.v1` composer or allowing a browser, label, terminal delivery state, or merged
PR to invent owner attention or trial readiness.

The capability is deliberately blocked. No current producer exposes the canonical source facts
needed for **Needs you** or **Ready to try**, and no local Focus or SoI destination exists for typed
navigation. Visual implementation additionally waits for a governed Yggdrasil handoff.

## Current-to-target truth

| Surface | Current delivered fact | Remaining target |
| --- | --- | --- |
| `devui.composition.v1` | Per-request CKM/Cockpit envelope with independent provider state | No current source owns either Overview fact, so both zones remain withdrawn and ARO-02 remains blocked |
| `devui-overview-view.v1` | Pure composer in `app/builderops/devui_overview.py`, including hostile cross-field validation and typed root-reference preservation | **Excluded from this breakdown; do not duplicate or reopen** |
| Cockpit producer | `agent:needs-human` may place work in a Cockpit band, but no serialized canonical owner-authority category/governing-source fact reaches Overview | Exact source-owned owner-question facts, or an honest withdrawal |
| Delivery evidence | Delivery, merge, closure, and terminal verification facts exist independently | A source-owned, receipt-backed `ready_to_try` fact, or an honest withdrawal |
| API | Local-only GET `/api/devui/composition` and delivered direct-loopback GET `/api/devui/overview`; no devUI mutation route | Typed navigation only after actual local destinations are governed |
| Navigation | Composer validates typed root references | Resolvable local Focus and optional SoI destinations without joins |
| Visual shell | No Overview browser shell | Governed Yggdrasil design, read-only shell, browser/accessibility proof, owner pilot |

## Authority-resolution gate

ARO-01 was the only owner-decision child. Its accepted resolution recorded that no current source
owns either Overview fact, so neither zone may be enriched from current inputs. A future source
contract would have to name:

1. the canonical existing source and serialized field that owns one of
   `irreversible_external_effect`, `security_privacy_cost_commitment`,
   `production_release_operator_action`, or `contradictory_source_authority`;
2. the governing source reference, stable subject linkage, and evidence-state fields carried with
   that category;
3. the canonical receipt type and source that explicitly owns `ready_to_try`, including its
   subject linkage and freshness/availability rules; and
4. whether the current GitHub → Cockpit → `devui.composition.v1` producer chain can transport those
   exact facts without acquiring authority.

The recorded no-source resolution keeps the corresponding zones withdrawn and ARO-02 blocked or
superseded. `agent:needs-human`, `done`, a merge, Issue closure, availability, or a terminal
verification receipt is never itself the missing category or `ready_to_try` fact.

## Dependency order and readiness

| Order | Task | Initial label | Exact executable trigger |
| --- | --- | --- | --- |
| 1 | ARO-01 — Authorize Overview Source Facts | Closed #4742; withdrawal recorded by PR #4751 | No current source owns either Overview fact |
| 2 | ARO-02 — Enrich Overview Producer Facts | Superseded #4743 | The accepted no-source decision leaves no producer facts to enrich; a future source contract requires a new governed slice |
| 3 | ARO-03 — Expose the Local Overview GET Route | Delivered #4744 | The route rebuilds the production composition and calls the delivered composer without candidates |
| 4 | ARO-04 — Bind Typed Overview Navigation | `agent:blocked` | ARO-03 plus delivered #4768 local Focus route and an optional local SoI destination |
| 5 | ARO-05 — Validate the Overview Yggdrasil Design | `agent:blocked` | Stable ARO-03/04 fixtures plus passing governed design-system preflight |
| 6 | ARO-06 — Render the Read-Only Overview Shell | `agent:blocked` | Accepted ARO-05 handoff and merged ARO-03/04 |
| 7 | ARO-07 — Prove Overview Browser and Accessibility States | `agent:blocked` | ARO-06 merged at an exact testable SHA |
| 8 | ARO-08 — Run the Read-Only Owner Pilot | `agent:blocked` | ARO-07 receipt and stable local source fixtures |

No task is `agent:ready` at filing. The parent is a blocked validation hub and never becomes a
pickup issue.

## Cross-Task Invariants / Interaction Safety

- **ARO-INV-1 — composer exclusion.** No child changes or recreates Overview zone semantics owned
  by `app/builderops/devui_overview.py` unless a separately filed defect proves that delivered
  contract wrong.
- **ARO-INV-2 — producers declare.** Only explicit source-owned facts enter candidates; labels,
  provider prose, technical blocks, timestamps, terminal states, and textual similarity do not.
- **ARO-INV-3 — UI renders.** The route and browser preserve server classifications, evidence
  axes, withdrawals, limitations, and typed references byte-for-meaning; they never reclassify.
- **ARO-INV-4 — roots do not join.** Overview, Focus, Product/Runtime SoI Evidence, delivery, and
  Builder System Control remain separately owned roots connected only by typed references.
- **ARO-INV-5 — read only.** No POST/PUT/PATCH/DELETE endpoint, command, credential, browser store,
  durable selection, task store, cache, graph, or fallback write enters Stage A.
- **ARO-INV-6 — degraded is not empty.** Unavailable, refused, unsupported, stale, unread, missing,
  unlinked, and not measured never become healthy, zero, or measured empty.
- **ARO-INV-7 — visual authority stays bounded.** Design guidance cannot change source semantics;
  the Yggdrasil preflight and acceptance receipt are required before shell implementation.

## Capability acceptance

- [ ] Every child has a terminal delivery receipt or explicit superseding/withdrawal disposition.
- [ ] The accepted source contract proves that Needs-you and Ready-to-try facts are source-owned,
      serialized, linked, fresh enough, and never inferred.
- [ ] The local Overview endpoint is GET-only, local-admission constrained, projection-only, and
      preserves the delivered composer contract.
- [ ] Every typed navigation reference resolves to an actual admitted local destination or remains
      explicitly unavailable/unsupported; no dead or synthetic link is rendered.
- [ ] The governed handoff and shell cover desktop, narrow, 200% zoom, keyboard, screen-reader,
      print, JavaScript-off, many-at-once, complete-empty, partial, stale, missing, refused, and
      unlinked states without browser reclassification.
- [ ] The owner pilot answers Now, Needs you, and Ready to try without a false decision, readiness,
      durable acceptance, or dependency on opening standalone subsystem UIs.

## Relationship to GitHub issues

Parent [#4741](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4741) is the blocked validation
hub. ARO-01 is [#4742](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4742), closed with its
withdrawal recorded by PR #4751; ARO-02 / [#4743](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4743)
is superseded by that no-source decision, and ARO-03 / [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744)
is delivered as the no-candidate local projection route; its contract and route-test selection were
reconciled by merged PR #4789. ARO-04 through ARO-08 remain
[#4745](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4745) through
[#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) (`agent:blocked`). The separate
[Focus-route prerequisite #4768](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4768) is
delivered by PR #4771; ARO-04 still needs its own typed-navigation contract before it marks a
Focus destination available. GitHub owns
backlog state; this directory owns the stable breakdown and validation path.

## Governing and supporting sources

- `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
- `docs/plans/DEVUI_IMPLEMENTATION.md :: Stage A — see: coherent read-only devUI`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/DESIGN_PRINCIPLES.md :: Shared Visual Language`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
- `app/builderops/devui_overview.py`
- `app/builderops/devui_composition.py`
- `app/builderops/cockpit_registry.py`
- `app/api/routes/devui.py`
- `docs/audits/BUILDER_SYSTEM_DEVUI_EXECUTION_ARCHITECTURE_2026-08-09.md :: Phase 1` (advisory test-boundary input only)
