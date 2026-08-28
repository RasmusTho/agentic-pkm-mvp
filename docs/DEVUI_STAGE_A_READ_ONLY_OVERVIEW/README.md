State: Accepted target-state breakdown with blocked validation parent #4741; ARO-01 is closed with
its withdrawal recorded, ARO-03 is delivered as the direct-loopback local route, and ARO-04–08
remain blocked. Recovery inputs #4833, #4834, #4838, and #4841 are closed, while #4835 remains
open/in progress and #4836 remains open/blocked; no final `M` or downstream runtime receipt exists.
Doc role: Capability specification and source-authorized task decomposition for the remaining read-only devUI Stage A Overview.
Authority: `docs/DEVUI.md` owns owner experience and Overview semantics; `docs/plans/DEVUI_IMPLEMENTATION.md` owns Stage A order. This directory owns only the bounded delivery contracts and validation path.
Owner: Builder System governance
Temporal class: Strategic target state with an explicit delivered-input ledger
Review cadence: Event-driven
Source of truth: Owner documents own intended behavior; source systems and receipts own facts; GitHub, Git, CI, and merged code own delivery truth.
Last reviewed: 2026-08-28
Last verified against: `origin/main` `0ccdb8613766a46fb3830227b2a1b3e45979e2d7`, live GitHub
state for #4742–#4749, #4768, #4786, #4791, #4833–#4836, #4838, and #4841, and merged PRs #4751,
#4771, #4772, #4789, #4792, #4842, and #4845.

# devUI Stage A Read-Only Overview

## Outcome

Complete the remaining read-only Overview path without reimplementing the delivered
`devui-overview-view.v1` composer or allowing a browser, label, terminal delivery state, or merged
PR to invent owner attention or trial readiness.

The capability remains deliberately blocked for its owner-question, readiness, navigation, and
visual steps. No current producer exposes the canonical source facts needed for **Needs you** or
**Ready to try**. #4834 delivers source-owned **Now** candidates from the trusted Cockpit `working`
payload only; the delivered local Focus route does not by itself authorize an Overview typed-
navigation destination, and no local SoI destination exists. Connected visual implementation waits
for stable #4834 **Now** fixtures plus the delivered #4768 Focus API fixtures, the open #4835
production repository/prerequisite work, the blocked #4836 connected shell, and accepted governed
Yggdrasil evidence: exact constrained reuse provenance, or the live handoff required for any novel,
mixed, or unknown delta.

#4841 supplies only the production loopback-published Companion transport for the existing two
read APIs. #4836 must consume its exact admission and header-stripping boundary; it provides no
page, asset, or visual destination.

## Current-to-target truth

| Surface | Current delivered fact | Remaining target |
| --- | --- | --- |
| `devui.composition.v1` | Per-request CKM/Cockpit envelope with independent provider state; #4834 reads its already-composed Cockpit `working` payload once | No current source owns an owner-question or readiness fact, so **Needs you** and **Ready to try** remain withdrawn and ARO-02 stays closed/superseded |
| `devui-overview-view.v1` | Pure composer in `app/builderops/devui_overview.py`, including hostile cross-field validation and typed root-reference preservation | **Excluded from this breakdown; do not duplicate or reopen** |
| Cockpit producer | #4834 maps only trusted, countable `working` items to source-ordered **Now** candidates with stable GitHub identity and separate Cockpit evidence | Owner-question facts remain separately source-owned or honestly withdrawn; `agent:needs-human`, delivery, and readiness are not admitted |
| Delivery evidence | Delivery, merge, closure, and terminal verification facts exist independently; #4833/#4842 supplies the exact-ref browser workflow, but its required pre-merge proof must run against the published #4836 candidate; #4835 is open/in progress and #4836 is open/blocked | Exact published #4836 candidate proof before merge, then final post-merge `main` commit `M` containing #4835/#4836, fresh #4748 exact-SHA proof at `M`, and deployment/owner receipts; a source-owned, receipt-backed `ready_to_try` fact, or an honest withdrawal |
| API | Local-only GET `/api/devui/composition`, delivered direct-loopback Overview/Focus reads, and #4841's production Companion exact two-GET transport; no devUI mutation or page route | Typed navigation only after actual local destinations are governed |
| Navigation | Composer validates typed root references | Resolvable local Focus and optional SoI destinations without joins |
| Visual shell | No accepted connected shell; #4836 remains open/blocked, while #4833/#4842 provides only the exact-ref proof workflow | Accepted constrained-reuse or live-handoff evidence, read-only shell, required #4836-candidate browser proof before merge, separate browser/accessibility proof at `M`, owner pilot |

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

#4834 is the delivered source adapter for source-owned **Now** items only. It admits one unique,
countable Cockpit `working` band only when the composed work contribution remains trusted, and it
changes none of the withdrawal conclusions for **Needs you** or **Ready to try**.

## Dependency order and readiness

| Order | Task | Initial label | Exact executable trigger |
| --- | --- | --- | --- |
| 1 | ARO-01 — Authorize Overview Source Facts | Closed #4742; withdrawal recorded by PR #4751 | No current source owns either Overview fact |
| 2 | ARO-02 — Enrich Overview Producer Facts | Superseded #4743 | The accepted no-source decision leaves no producer facts to enrich; a future source contract requires a new governed slice |
| 3 | ARO-03 — Expose the Local Overview GET Route | Delivered #4744 and #4834 recovery | The route rebuilds the production composition once, derives only trusted Cockpit `working` inputs, and calls the delivered composer |
| 4 | ARO-04 — Bind Typed Overview Navigation | `agent:blocked` | ARO-03 plus delivered #4768 local Focus route and an optional local SoI destination |
| 5 | ARO-05 — Validate Connected Overview and Focus Yggdrasil Evidence #4746 | `agent:blocked` | Merged stable #4834 source-owned Now fixtures plus delivered #4768 Focus API fixtures, then either an independently reviewed `yggdrasil-constrained-reuse.v1` exact-reuse receipt or a passing live Yggdrasil Design Handoff Receipt for novel, mixed, or unknown scope |
| 6 | ARO-06 — Render the Read-Only Overview Shell | `agent:blocked` | Accepted ARO-05 design evidence and merged ARO-03/04; connected recovery #4836 remains open/blocked |
| 7 | ARO-07 — Prove Overview Browser and Accessibility States | `agent:blocked` | Publish the #4836 candidate, dispatch exact-ref #4833/#4842 against that candidate before merge, then prove final `M` containing #4835/#4836 |
| 8 | ARO-08 — Run the Read-Only Owner Pilot | `agent:blocked` | Fresh #4748-at-`M` receipt, repaired pilot contract, #4835 boolean prerequisite receipt, Demerzel prod access, #4747 selectors, receipt-sourced deployed URL/SHA, separate promotion/owner acknowledgements, and disposable-state classification |

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
- **ARO-INV-7 — visual authority stays bounded.** Design guidance cannot change source semantics.
  Exact shipped-pattern reuse requires an independently reviewed content-addressed
  `yggdrasil-constrained-reuse.v1` receipt with zero novel language; novel, mixed, unknown, or
  out-of-envelope work still requires the live Yggdrasil preflight and handoff receipt.
- **ARO-INV-8 — production transport stays narrower than presentation.** #4836 must consume #4841's
  `127.0.0.1:8113` loopback publish, local-Host/no-forwarded gateway admission, exact Overview/Focus
  GET allowlist, stripped upstream request, and direct-loopback-or-server-derived API rule unchanged.
  Port `18000` remains direct diagnostics and is not a browser page origin.

## Capability acceptance

- [ ] Every child has a terminal delivery receipt or explicit superseding/withdrawal disposition.
- [ ] The accepted source contract proves that Needs-you and Ready-to-try facts are source-owned,
      serialized, linked, fresh enough, and never inferred.
- [ ] The local Overview endpoint is GET-only, local-admission constrained, projection-only, and
      preserves the delivered composer contract.
- [ ] The production shell uses #4841's exact read-only Companion transport at `127.0.0.1:8113`;
      it never treats port `18000` as a browser page, forwards identity or credentials, adds a
      wildcard/write route, or infers loopback from the Docker peer.
- [ ] Every typed navigation reference resolves to an actual admitted local destination or remains
      explicitly unavailable/unsupported; no dead or synthetic link is rendered.
- [ ] The governed design evidence and shell cover desktop, narrow, 200% zoom, keyboard, screen-reader,
      print, JavaScript-off, many-at-once, complete-empty, partial, stale, missing, refused, and
      unlinked states without browser reclassification.
- [ ] The owner pilot answers Now, Needs you, and Ready to try without a false decision, readiness,
      durable acceptance, or dependency on opening standalone subsystem UIs. It runs only on the
      receipt-sourced Demerzel production deployment (`pkm-prod`, `PKM_ENVIRONMENT=prod`, Midgård),
      proves the deployed SHA across CI/review/deploy receipt, `/version`, `/api/health.version`,
      and gateway marker, and records the disposable-state Overview → server-supplied Focus →
      return journey with zero effects/errors/storage/unauthorized writes and durable evidence.
- [ ] The final pilot ledger binds #4835's value-free boolean prerequisite receipt, allows `pkm-test`
      only after disposable classification, and keeps promotion-plan acknowledgement separate from
      the later owner evidence acknowledgement.

## Relationship to GitHub issues

Parent [#4741](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4741) is the blocked validation
hub. ARO-01 is [#4742](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4742), closed with its
withdrawal recorded by PR #4751; ARO-02 / [#4743](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4743)
is superseded by that no-source decision, and ARO-03 / [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744)
is delivered as the no-candidate local projection route; its contract and route-test selection were
reconciled by merged PR #4789. ARO-04 through ARO-08 remain
[#4745](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4745) through
[#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) (`agent:blocked`). Recovery Issue
[#4833](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4833) is closed through merged PR #4842
and supplies the exact-ref browser workflow, not a proof receipt. Before #4836 merges, that workflow
must produce the separately authenticated published-candidate proof; #4748 then produces its distinct
later proof at final `M`. #4834, #4838, and #4841 are closed; #4835 remains open/in progress and #4836
remains open/blocked. ARO-08 is a future executable production pilot only: its actual URL/SHA must be
sourced later from the candidate proof, final `M`, #4748, and deployment receipts, and it must not
imply that deployment or owner validation happened.
The separate
[Focus-route prerequisite #4768](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4768) is
delivered by PR #4771. Connected handoff #4746 remains blocked until the delivered source-owned Now
producer #4834 is merged stable and one applicable governed receipt passes independent review. This governance change
does not accept #4746 or produce its receipt. GitHub owns backlog state; this directory owns the
stable breakdown and validation path.

Production transport prerequisite [#4841](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4841)
is consumed only by the source-authorized connected shell
[#4836](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4836) and does not itself deliver that shell.

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
