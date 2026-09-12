State: Accepted target-state gap/acceptance specification. In the 2026-09-12 repository snapshot,
FCA-01..04 are delivered; composed platform deployment and owner acceptance remain unproved.
Parent #5399 is the live validation hub; seven original children are filed. Two additional
contract-repair tasks below are specified but unfiled; live readiness is owned by GitHub.
Doc role: Specification directory
Authority: User-authorized research-to-backlog handoff `prom_20260907052807_ef79007c`, accepted receipt `receipt_20260907052822_aa95b743`; subordinate to DEVUI, ADR-0062 and the Builder System process map.
Owner: Builder System governance and owner-experience acceptance

# Builder Factory Acceptance

## Capability intent

Make Builder a usable standalone Product Owner platform on TARS VM `bob-1` (VM ID `102`, formerly
`vm102`), running guest/system `builder-system`, first for Yggdrasil and then an explicitly
addressed second consumer repository. The owner clarified that an LLM is welcome wherever it
improves overview and control, and determinism is secondary to that usable outcome. LLM-assisted
explanation, synthesis and bounded agent workflows are admitted design direction; exact
authorization, source/effect identity and truthful readback remain binding. Completing the entire
DDO portfolio is not a first-release gate.

This specification owns only the gaps and aggregate acceptance identified in the [audit](../audits/BUILDER_SYSTEM_VISION_DELIVERY_2026-09-07.md). Existing infrastructure, DevUI, action, delivery and design owners are reused. It adds no task store, source registry, graph authority, universal score or second workflow engine. Source extraction and multi-tenancy are out of scope.

## Implementation tasks and execution order

Serial pickup is the default. FCA-04 can run independently of the first two governance tasks if a separate issue/worktree owner is available; the flat review order remains the order below.

| Task | Scope | Prerequisites |
| --- | --- | --- |
| #5400 [FCA-01 — Reconcile executable Builder contracts](RECONCILE_EXECUTABLE_CONTRACTS.md) | Delivered by PR #5420; contract reconciliation only | Closed; runtime acceptance remains parent-owned |
| #5401 [FCA-02 — Define owner facts and bounded action handoff](DEFINE_OWNER_FACT_AND_ACTION_CONTRACT.md) | Delivered by PR #5424; source-backed contract only | Closed; remaining authority gaps use the bounded repair tasks below |
| #5402 [FCA-03 — Compose LLM-assisted owner overview](COMPOSE_LLM_ASSISTED_OWNER_OVERVIEW.md) | Delivered by PR #5413; source-linked proposal-only synthesis | Closed; runtime acceptance remains parent-owned |
| #5403 [FCA-04 — Isolate Builder package boot](ISOLATE_BUILDER_PACKAGE_BOOT.md) | Delivered by PR #5421; package/build independence | Closed; no live platform acceptance implied |
| #5404 [FCA-05 — Produce owner decision and trial facts](PRODUCE_OWNER_DECISION_AND_TRIAL_FACTS.md) | produce and project explicit owner decision and trial receipts | FCA-02, #4169 |
| #5405 [FCA-06 — Qualify a second consumer repository](QUALIFY_SECOND_CONSUMER_REPOSITORY.md) | qualify Builder against an explicitly addressed second repo | FCA-04, #3793, #5181 |
| #5406 [FCA-07 — Prepare composed owner acceptance](PREPARE_COMPOSED_OWNER_ACCEPTANCE.md) | prepare whole owner-platform acceptance over existing workflow proofs | FCA-03, FCA-05, FCA-06, #4749, #4697, #4982, #5181 |

FCA-02 is a contract-enrichment task, not authorization to invent a source store. FCA-05 cannot become ready until its exact producer/source/action contract exists. FCA-03 delivered independently using existing admitted sources; it emits interpretations/proposals rather than the missing canonical owner facts. If the contract changes their implementation boundaries, amend their specs and Issues before pickup. #4169's prerequisite means its admitted first action boundary after FCA-01 reconciliation; it does not silently require all DDO effects for a non-DDO workflow.

### Contract-repair tasks

These tasks repair remaining executable-contract gaps under the existing owner documents. They
specify the next work, not new admitted action/data/runtime authority. Existing closed children stay
closed. No later implementation dependency changes until the owning repair is delivered and the
affected live Issue is reconciled. Only these first tasks are published now; later implementation
breakdown follows their accepted results.

| Task | Bounded outcome | Order |
| --- | --- | --- |
| [FCA-08 — Define bounded action admission](DEFINE_BOUNDED_ACTION_ADMISSION.md) | Name the first action seam in the existing control plane while retaining DDO-specific ownership | First; before dependent action implementation |
| [FCA-09 — Define owner outcome authority](DEFINE_OWNER_OUTCOME_AUTHORITY.md) | Resolve trial/acceptance authority in the existing receipt/object owner without overloading ADR-0065 dispositions | Second; before FCA-05 producer implementation |
| [ARO-09 — Reconcile managed owner pilot](../DEVUI_STAGE_A_READ_ONLY_OVERVIEW/RECONCILE_MANAGED_OWNER_PILOT.md) | Reconcile runtime/source topology and pre-merge versus live evidence order | Third; owned by Stage A / #4741, not a new FCA child |

#### FCA-08 — Bounded action contract repair

Source work is [DEFINE_BOUNDED_ACTION_ADMISSION](DEFINE_BOUNDED_ACTION_ADMISSION.md). The repair must
name the admitted service, destination, operation, approval/readback and recovery responsibilities
using existing action owners. This paragraph grants no action admission and does not replace #4169.

#### FCA-09 — Owner outcome contract repair

Source work is [DEFINE_OWNER_OUTCOME_AUTHORITY](DEFINE_OWNER_OUTCOME_AUTHORITY.md). The repair must
resolve the distinction between temporal-intention dispositions and explicit candidate-bound owner
trial/acceptance in the object-model owner before FCA-05 writes those facts.

## Existing epics and validation hubs

| Existing owner | Retained scope | How this capability consumes it |
| --- | --- | --- |
| #5052 / #5056 | TARS/VM102 qualification and rebuildable activation | Exact platform and activation receipts; backup remains deferred |
| #3788 / #3793 / #3690 | API/PostgreSQL authority cutover, Product separation, enacted docs | Independent operational authority and no fallback; FCA-04 owns package boot only |
| #5181 | Complete Dev System component inventory and VM102 deployment | Full component, auth, source/image/epoch, health and rollback/rebuild evidence |
| #4741 / #4749 | Stage A read-only deployment and owner pilot | A usable first read surface and its owner observations |
| #4693 / #4695 / #4697 | Focus/Conversation design and first inquiry command | Contextual reasoning and actual first command, through existing action owner |
| #4982 | Unified owner experience and BSC design handoff | Follow-up execution slices for rich Focus, BSC and progressive disclosure; design alone does not satisfy implementation |
| #4163 / #4168 / #4169 / #4170 / #4466 | DDO effects, initiation, recovery/TCD and retry | Reuse where selected; deepen unattended delivery without blocking an admitted agent-led owner-control MVP |
| #3604 / #4897 / #4893 | Closure and post-effect recovery integration | Actual selected workflow's terminal truth and recovery; no second queue |
| #5177 | Model-aware execution routing | Optional controlled optimization; configured LLM use is permitted before this whole epic completes |

## Cross-Task Invariants / Interaction Safety

1. **Source before assertion:** LLM summaries can propose interpretations from bounded evidence, but only the owning source can assert a decision, deployment, trial or acceptance. Stale/contradictory sources remain visible; a failed model still leaves usable source navigation.
2. **Approval before effect:** one addressed subject/action/version crosses the existing authenticated action boundary. A new model response or changed preview never widens an existing approval.
3. **Unknown effect before retry:** if launch succeeds but response is lost, the destination's operation identity/readback must resolve it before another launch. Store a pending reconciliation state in the existing authority, not browser memory.
4. **Written fact before projection:** if a fact write commits but rendering fails, replay reads the existing receipt and regenerates the view. Render failure cannot undo acceptance or create duplicate asks.
5. **Version before inheritance:** an updated candidate, source or permission invalidates the affected preview/tryability/acceptance projection; old receipts remain history, never proof for the new candidate.
6. **Repository before defaults:** second-consumer paths must resolve their own manifest/policy/credential scope. An absent manifest refuses; hub defaults cannot fill the gap.
7. **Independent lifecycle:** Builder package boot and VM102 service lifecycle cannot require Product Runtime availability or the owner UI being open. Explicit external model dependencies remain declared; failure is visible and does not expand billing/authority.
8. **Per-workflow autonomy:** owner-platform acceptance does not grant universal unattended authority. A selected workflow carries its own stop/recovery and permission proof; deeper autonomy follows the process map's qualification/demotion contract.

## Acceptance Criteria

The following full platform criteria are retained unchanged. The first-repository milestone below
is an intermediate owner-value checkpoint and cannot close #5399.

- [ ] Current executable contracts agree with VM102/A4 and the owner priority of useful LLM-assisted overview/control. Verify: runtime receipt: builder_factory_contract_reconciliation.v1
- [ ] The owner can understand ongoing work and a proposed next step, inspect its sources, approve a bounded action and see the actual result, including degraded/model-unavailable states. Verify: runtime receipt: builder_owner_platform_pilot.v1
- [ ] VM102 runtime identity, component coverage, independent authority, package boot, auth, health and rebuild posture are evidenced without Product or implicit operator-client dependence. Verify: runtime receipt: builder_factory_vm102_acceptance.v1
- [ ] A separately authorized second consumer completes the selected bounded workflow under its own repo/policy and produces real readback, with no hub policy/credential borrowing. Verify: runtime receipt: builder_second_consumer_pilot.v1
- [ ] Exact candidate trial/acceptance or rejection is explicitly recorded by the owner, and no fixture or model judgment supplies that human fact. Verify: runtime receipt: builder_owner_platform_acceptance.v1

### First-repository milestone

M2 narrows the first observed journey to one owner, this repository, one named feature/Issue and
one existing Builder workflow. It reuses the parent-owned `builder_owner_platform_pilot.v1` and
`builder_owner_platform_acceptance.v1` evidence surfaces with an explicit first-repository scope:

- source-linked intent, acceptance criteria and relevant architecture requirements are inspectable;
- scoped agent reasoning remains distinguishable from source facts;
- one exact permitted action reaches the selected workflow and has real result/readback evidence;
- changed requirements/evidence and interrupted or ambiguous execution retain their actual limits;
- the owner tries the exact delivered candidate and explicitly accepts or rejects it against the
  applicable requirements, including what could not be tried.

Supervised operation is acceptable within the selected workflow's authority; manual handoffs remain
visible in the pilot evidence. An inquiry alone cannot satisfy this milestone. Stage A's read-only
pilot is a separate predecessor, not permission for delivery effects. The milestone adds no receipt
schema, writer or inferred owner fact; [FCA-08](DEFINE_BOUNDED_ACTION_ADMISSION.md),
[FCA-09](DEFINE_OWNER_OUTCOME_AUTHORITY.md) and the existing action/data owners govern those repairs.
Full VM102 inventory, independent authority, second-consumer qualification and all full-platform
owner acceptance obligations above remain required before #5399 can close.

## Verification and validation

Pre-merge proof is task-local: document contracts, production call-site tests, package smoke and composed scenario tests. Behavioral targets are named commitments, including new tests, not claims that those tests already exist. Each child must remain independently mergeable. Live deployment, second-consumer effects and owner observation are **parent-validation** authority; no closing implementation child relies on an unprovable future live receipt.

Parent acceptance records the exact VM102 source/image/config/epoch, component inventory, selected consumer/workflow, issued permission and operation identities, provider availability, source/result/tryability receipts, actual owner observations, residual limits and next permitted autonomy mode. Existing receipt schemas are reused. The `builder_*_pilot/acceptance.v1` names here identify bounded acceptance artifacts, not a new database or service.

Before a live pilot, name its permitted repo/branch/actions and operator authority. This planning pass does not authorize host, secret, deploy, merge or user-acceptance effects. Existing operator gates remain; a blocked live operation does not justify blocking independent repository implementation.

## Relationship to GitHub issues

The parent is a gap/acceptance hub; it never acquires the lifecycle of existing epics. Child Issues reference exactly this parent; external issue links above are dependencies. Source publication is a prerequisite for pickup. Readiness is reevaluated from current evidence and strict validation, not inferred from this table. Parent closure requires all required child contracts and the finite acceptance receipts, followed by the normal owner-doc writeback on each owning surface.

## BuilderOps handoff

Worklog `awl_20260907052625_c9f45898`; learning `lrn_20260907052626_7ac5964f`; accepted PromotionIntent `prom_20260907052807_ef79007c`; acceptance receipt `receipt_20260907052822_aa95b743`. The self-contained audit and GitHub bodies carry the relevant evidence; no executing agent needs this host-local store. Owner steering on LLM use and useful control is preserved in Capability intent above.
