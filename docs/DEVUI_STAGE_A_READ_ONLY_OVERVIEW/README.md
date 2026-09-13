State: Accepted target-state breakdown with blocked validation parent #4741; ARO-01 is closed with
its withdrawal recorded, ARO-03 is delivered as the direct-loopback local route, ARO-05/#4746 and
ARO-06/#4836 are delivered, ARO-07/#4748 is delivered with exact final-main evidence, and ARO-04 is
superseded while ARO-08/#4749 remains blocked; Focus-route prerequisite #4768, source-owned Now producer #4834, and
production transport #4841 are delivered. ARO-09/#5504 defines the managed runtime/pilot contract;
the managed shell/source extension, deployment and owner pilot remain unproved.
Doc role: Capability specification and source-authorized task decomposition for the remaining read-only devUI Stage A Overview.
Authority: `docs/DEVUI.md` owns owner experience and Overview semantics; `docs/plans/DEVUI_IMPLEMENTATION.md` owns Stage A order. This directory owns only the bounded delivery contracts and validation path.
Owner: Builder System governance
Temporal class: Strategic target state with an explicit delivered-input ledger
Review cadence: Event-driven
Source of truth: Owner documents own intended behavior; source systems and receipts own facts; GitHub, Git, CI, and merged code own delivery truth.
Last reviewed: 2026-09-13
Last verified against: `origin/main` `9d9cacff7c1ee04dd73eeb3c67bd1a8b485edae8`, managed
listener/receipt producers, the dated #5181 component receipt and latest #4076 operator boundary.
Historical #4836/#4748 proof retains its exact source/transport scope.

# devUI Stage A Read-Only Overview

## Outcome

Complete the remaining read-only Overview path without reimplementing the delivered
`devui-overview-view.v1` composer or allowing a browser, label, terminal delivery state, or merged
PR to invent owner attention or trial readiness.

The capability remains deliberately blocked for its owner-question, readiness, and
production-validation steps. Merged #4836 supplies the bounded typed-navigation contract; no
separate navigation delivery slice remains. No current producer exposes the canonical source facts needed for
**Needs you** or **Ready to try**. #4834 delivers source-owned **Now** candidates from the trusted
Cockpit `working` payload only; the connected shell is delivered, but exact browser proof and
production acceptance remain separate authorities. ARO-07/#4748 is now proven at final post-merge
main `M=c7c57300f2ec241778061078e7ad585454f0b880`; ARO-08/#4749 still requires the independent VM-102
deployment, promotion, production observation, and owner-evidence gates.

#4841 supplies the historical Companion two-GET transport; #4836 adds its pages/assets. The
independent managed runtime is a different process at the same port and currently serves neither
those pages nor Focus. Its remaining extension is governed by
[Managed read journey admission](../BUILDEROPS_CONTROL_PLANE/README.md#managed-read-journey-admission).

## Complete Dev System placement boundary

Stage A is one read-only Dev UI projection component within the complete Builder System / Dev
System. Its target runtime home is TARS VM `bob-1` (VM ID `102`, formerly `vm102`), running
guest/system `builder-system`, but this capability specification
does not claim that Stage A, Dev UI, or the complete Dev System is resident or deployed there. The
complete topology, external dependencies, intentionally non-runtime components, and unresolved
gaps are owned by [`docs/BUILDEROPS_CONTROL_PLANE/README.md :: Complete Dev System VM-102 topology
contract`](../BUILDEROPS_CONTROL_PLANE/README.md).

Stage A cannot replace BuilderOps, GitHub/CI/review/merge/closure, Product Runtime, or TARS/Proxmox
authority. Its browser and owner-pilot evidence is valid only when bound to the complete-system
deployment receipts and exact deployed/final-main SHA `M`. A missing component or receipt withdraws the affected
claim; it is never treated as an empty, healthy, or deployed state.

## Current-to-target truth

| Surface | Current delivered fact | Remaining target |
| --- | --- | --- |
| `devui.composition.v1` | Per-request CKM/Cockpit envelope with independent provider state; #4834 reads its already-composed Cockpit `working` payload once | No current source owns an owner-question or readiness fact, so **Needs you** and **Ready to try** remain withdrawn and ARO-02 stays closed/superseded |
| `devui-overview-view.v1` | Pure composer in `app/builderops/devui_overview.py`, including hostile cross-field validation and typed root-reference preservation | **Excluded from this breakdown; do not duplicate or reopen** |
| Cockpit producer | #4834 maps only trusted, countable `working` items to source-ordered **Now** candidates with stable GitHub identity and separate Cockpit evidence | Owner-question facts remain separately source-owned or honestly withdrawn; `agent:needs-human`, delivery, and readiness are not admitted |
| Delivery evidence | Delivery, merge, closure, and terminal verification facts exist independently | A source-owned, receipt-backed `ready_to_try` fact, or an honest withdrawal |
| API | Local-only GET `/api/devui/composition`, delivered direct-loopback Overview/Focus reads, and #4841's production Companion exact two-GET transport; merged #4836 adds only the governed read-only Companion page/asset routes | Typed navigation only after actual local destinations are governed |
| Navigation | Composer validates typed root references; merged #4836 owns the bounded typed-navigation contract | No separate navigation delivery slice; remaining acceptance belongs to the owner-pilot and production gates |
| Visual shell | #4836 delivered the connected read-only shell and exact constrained-reuse manifest; #4748 has an authenticated exact-main receipt at `M`, but the shell is not production-deployed or owner-accepted | #4749 deployment identity, owner pilot, and separate owner-evidence acknowledgement |

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
| 4 | ARO-04 — Bind Typed Overview Navigation | Superseded #4745 | The delivered #4836 shell owns the bounded typed-navigation contract; no separate successor is admitted |
| 5 | ARO-05 — Validate Connected Overview and Focus Yggdrasil Evidence #4746 | Delivered and closed after exact constrained-reuse receipt | Merged stable #4834 source-owned Now fixtures plus delivered #4768 Focus API fixtures, with independently reviewed `yggdrasil-constrained-reuse.v1` receipt |
| 6 | ARO-06 — Render the Read-Only Overview Shell | Delivered by merged #4836 | Accepted ARO-05 design evidence and merged ARO-03/04 |
| 7 | ARO-07 — Prove Overview Browser and Accessibility States | Delivered and closed #4748 | Exact five-node #4833 artifact and `devui-stage-a-exact-sha-state-matrix.v1` receipt at final post-merge `main` `M` |
| 8 | ARO-08 — Run the Read-Only Owner Pilot | Separately gated #4749 | Merged ARO-09; delivered/admitted managed shell, Focus and required sources; fresh applicable #4748 proof for deployed `M`; exact VM102 qualification/deploy/health and operator/promotion receipts; observed URL/source/image/config agreement. Disposable-state classification is conditional on a `pkm-test` supplement. Separate owner evidence acknowledgement is pilot output. |

No task is `agent:ready` at filing. The parent is a blocked validation hub and never becomes a
pickup issue. #4748 is a completed proof receipt, while #4749 remains blocked on external runtime
authority and genuine acknowledgements.

### ARO-09 — Managed runtime and pilot contract repair

[RECONCILE_MANAGED_OWNER_PILOT](RECONCILE_MANAGED_OWNER_PILOT.md) / #5504 defines the
[managed origin, source and producer contract](../BUILDEROPS_CONTROL_PLANE/README.md#managed-read-journey-admission)
and the [ordered implementation/live-evidence stages](../plans/DEVUI_IMPLEMENTATION.md#dependency-graph).
It repairs ARO-08 without deploying it. Current startup needs readable local configuration; missing
typed receipts withdraw readiness at read time. The older #5181 stopped-process observation does
not redefine that code behavior. Complete topology, external SoI/model evidence and #4076's actual
Heimdal/Platform operation remain separately owned gaps.

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
- **ARO-INV-8 — exact managed transport.** The independent runtime consumes the finite
  [managed read contract](../BUILDEROPS_CONTROL_PLANE/README.md#managed-read-journey-admission),
  including its direct-loopback/no-forwarded-identity boundary. Historical #4841 Companion
  admission and #4836 provenance do not install that managed extension or authorize Product access.
- **ARO-INV-9 — contracts, implementation and live proof differ.** ARO-09 defines the contract;
  missing shell/source producers remain implementation work, then #5181 supplies operational
  evidence and #4749 supplies a zero-effect pilot. Missing evidence withdraws claims. Effectful
  first-repository acceptance remains separate and cannot widen this pilot.

## Capability acceptance

- [ ] Every child has a terminal delivery receipt or explicit superseding/withdrawal disposition.
- [ ] The accepted source contract proves that Needs-you and Ready-to-try facts are source-owned,
      serialized, linked, fresh enough, and never inferred.
- [ ] The local Overview endpoint is GET-only, local-admission constrained, projection-only, and
      preserves the delivered composer contract.
- [ ] The managed shell uses the independently admitted origin, finite GET/assets/Focus allowlist
      and exact candidate identity. It never borrows Product/Companion authority, forwards identity
      or credentials, adds a wildcard/write route, or infers loopback from a Docker peer.
- [ ] Every typed navigation reference resolves to an actual admitted local destination or remains
      explicitly unavailable/unsupported; no dead or synthetic link is rendered.
- [ ] The governed design evidence and shell cover desktop, narrow, 200% zoom, keyboard, screen-reader,
      print, JavaScript-off, many-at-once, complete-empty, partial, stale, missing, refused, and
      unlinked states without browser reclassification.
- [ ] The owner pilot answers Now, Needs you, and Ready to try without a false decision, readiness,
      durable acceptance, or dependency on opening standalone subsystem UIs. It runs only on the
      receipt-sourced Bob-1/VM-ID-102 Dev System deployment (`builder-system`) and its governed external read
      dependencies; Product Runtime projects, vaults, and lifecycle are not VM-102 deployment evidence,
      proves source/image/config equality across CI/review/deploy/health evidence, managed `/version`,
      served shell/assets and applicable exact-main browser proof, and always records the deployed Overview → server-supplied Focus → return
      journey with zero effects/errors/storage/unauthorized writes and durable evidence. If a
      `pkm-test` supplement is used, it additionally records the disposable-state matrix; the
      production-only path does not create test state.

## Relationship to GitHub issues

Parent [#4741](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4741) is the blocked validation
hub. ARO-01 is [#4742](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4742), closed with its
withdrawal recorded by PR #4751; ARO-02 / [#4743](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4743)
is superseded by that no-source decision, and ARO-03 / [#4744](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4744)
is delivered as the no-candidate local projection route; its contract and route-test selection were
reconciled by merged PR #4789. ARO-04 /
[#4745](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4745) is closed as superseded, and
[#4748](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4748) is closed after its authenticated
exact-main proof, while ARO-08 /
[#4749](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4749) remains `agent:blocked`. ARO-08
is a future executable production pilot only: its actual URL/SHA must be sourced later from #4748
and deployment receipts, and it must not imply that deployment or owner validation happened.
The separate
[Focus-route prerequisite #4768](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4768) is
delivered by PR #4771. Connected handoff #4746 is closed after accepting the exact constrained-reuse
receipt for merged #4836; #4748's authenticated exact-main proof is recorded separately at final
post-merge `main`.
GitHub owns backlog state; this directory owns the stable breakdown and validation path.

Production transport prerequisite [#4841](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4841)
is consumed only by the source-authorized connected shell
[#4836](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4836) and does not itself deliver that shell.
The merged #4836 subtree is
`companion-ui/companion-app/companion_ui/workspace/devui_candidate`; its manifest binds the complete
Git inventory, exact shipped Cockpit/token source objects, and closed transformations. Its
Companion-owned page/assets repeat #4841 admission, preserve the exact two API GET allowlist, and
carry no-store/CSP/no-egress/effect-free browser constraints. This ledger records candidate scope
only as delivered repository scope; #4748's exact-main receipt is the proof authority at final
post-merge `main`, and #4749 remains the deployment/owner-pilot authority.

## Delivery evidence

The browser-evidence sequence is serial: the exact-ref #4836 candidate artifact was produced before
merge; #4748 then ran at final `main` `M` and posted the authenticated
`devui-stage-a-exact-sha-state-matrix.v1` receipt. Its artifact is self-describing only for that
run and makes no production claim. `M` must be the current `main` promotion ref used by the
receipt-sourced deployment; the historical #4748 run at `c7c57300f2ec241778061078e7ad585454f0b880`
is not reusable after `main` advances. If ARO-08 later becomes executable, its
`devui-stage-a-read-only-owner-pilot.v1` ledger is the sole binding authority for the exact-M
browser evidence plus production evidence. It records each tested SHA and separate recomputable
`evidence_artifact_sha256` inventories: the browser inventory contains the authenticated #4748
wrapper, its source `manifest.json` emitted and uploaded by `.github/workflows/browser-runtime.yml`,
and browser bundle; the production inventory contains deployment/health/identity receipts, the
deployed Playwright journey's trace, screenshots, checksums, and journey manifest, any used
disposable-state receipt, and, only when a `pkm-test` supplement is used, that supplement's trace,
screenshots, checksums, and manifest. Each digest uses RFC 8785 JSON Canonicalization Scheme (JCS), encoded
as UTF-8 without a BOM and without a trailing newline or other bytes; non-finite numbers and
non-string path/hash values are invalid. The pilot entry's own rendered inventory manifest is
excluded from its inventory. Owner-walkthrough output and acknowledgement are authenticated ledger
fields but are explicitly excluded from the production digest. Missing or mismatched artifacts fail
closed. #4836 and #4748 repository/proof delivery are complete; deployment and
owner validation have not run.

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
