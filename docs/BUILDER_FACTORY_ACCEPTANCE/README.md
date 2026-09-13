State: Accepted target-state gap/acceptance specification. In the 2026-09-12 repository snapshot,
FCA-01..04 are delivered; composed platform deployment and owner acceptance remain unproved.
Parent #5399 is the live validation hub; seven original children and contract-repair children
#5502/#5503 define the bounded admission/outcome contracts; ARO-09/#5504 defines managed runtime
and pilot sequencing under #4741. Runtime implementation and live readiness remain separately gated.
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
| #5404 [FCA-05 — Produce owner decision and trial facts](PRODUCE_OWNER_DECISION_AND_TRIAL_FACTS.md) | produce and project explicit owner decision and trial receipts | FCA-02, FCA-09 outcome authority, and the selected operation's implemented admission/readback seam |
| #5405 [FCA-06 — Qualify a second consumer repository](QUALIFY_SECOND_CONSUMER_REPOSITORY.md) | Pre-merge conformance harness, validator and second-consumer pilot procedure | FCA-04 and accepted FCA-08/ARO-09 contracts; implemented selected production admission/read/launch seams. Live #3793/#5181 qualification and the real second consumer are parent gates. |
| #5406 [FCA-07 — Prepare composed owner acceptance](PREPARE_COMPOSED_OWNER_ACCEPTANCE.md) | Pre-merge composed harness, validator and owner-pilot procedure | FCA-03, implemented FCA-05 outcome/readback and selected production read/action seams, applicable design contract. #5405 contributes its procedure where available; its live pilot, #4749/#5181 and owner acceptance are later parent gates. |

FCA-02 is a contract-enrichment task, not authorization to invent a source store. FCA-05 pickup requires its exact accepted producer/source/action contracts and the selected operation's external admission/readback prerequisites. Its four producers and outcome read transport remain its own implementation work; runtime activation additionally requires their delivery and source admission. FCA-03 delivered independently using existing admitted sources; it emits interpretations/proposals rather than the missing canonical owner facts. Amend affected specs and live Issues before pickup. The bounded admission contract below separates the first inquiry seam from #4169's DDO bridge; neither this contract nor an inquiry delivers FCA-05's outcome writer or an Issue-delivery operation.

### Contract-repair tasks

These tasks repair remaining executable-contract gaps under the existing owner documents. They
specify the next work, not new admitted action/data/runtime authority. Existing closed children stay
closed. No later implementation dependency changes until the owning repair is delivered and the
affected live Issue is reconciled. Only these first tasks are published now; later implementation
breakdown follows their accepted results.

| Task | Bounded outcome | Order |
| --- | --- | --- |
| #5502 [FCA-08 — Define bounded action admission](DEFINE_BOUNDED_ACTION_ADMISSION.md) | Contract defined below for the existing control plane and destination owners | Runtime admission, destination reservation/readback and activation remain separate work |
| #5503 [FCA-09 — Define owner outcome authority](DEFINE_OWNER_OUTCOME_AUTHORITY.md) | Separate candidate-bound trial/acceptance contract defined in the existing object/receipt owner | FCA-05 still owns producer/readback implementation; runtime admission and owner observations remain separate |
| #5504 [ARO-09 — Reconcile managed owner pilot](../DEVUI_STAGE_A_READ_ONLY_OVERVIEW/RECONCILE_MANAGED_OWNER_PILOT.md) | Managed runtime/source and pre-merge versus live evidence contract defined | Owned by Stage A / #4741; runtime, read-only pilot and full-platform acceptance remain separate. |

#### FCA-08 — Bounded action contract repair

The [task contract](DEFINE_BOUNDED_ACTION_ADMISSION.md) is realized by
[Bounded action admission](#bounded-action-admission) and the finite interaction table below.
This is a target contract under existing owners, not runtime implementation or activation.
#4169 retains DDO-specific request/compiler/reducer/CKM ownership.

#### FCA-09 — Owner outcome contract repair

The [task contract](DEFINE_OWNER_OUTCOME_AUTHORITY.md) is realized by the object-model owner's
[separate candidate-bound outcome contract](../builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md#candidate-bound-owner-outcome-contract-fca-09).
It defines authenticated owner confirmation, finite trial/decision payloads, exact candidate/profile
binding and atomic replay/correction/readback. ADR-0065 dispositions are separate. This is accepted
target-contract direction, not an implemented writer or owner outcome. FCA-05 and its retained P1
remain subject to the actual producer/source/admission proof; live Issue maintenance follows merge.

### Implementation and live-evidence order

The [dependency graph](../plans/DEVUI_IMPLEMENTATION.md#dependency-graph) is the single sequencing
owner. FCA-06/07 own reusable harnesses, validators and procedures; they do not wait for the live
evidence those procedures will later collect. Their actual external production seams must exist
before the child can test them. #4697 owns the first inquiry seam; it does not deliver a separately
approved Issue workflow or FCA-05's outcome writer. #4169/#4170 apply only when DDO is selected.
Removing #5181/#4749 live scheduling edges removes no #5399 acceptance obligation: complete-system
identity/authority, real second-consumer effects, and explicit owner trial/acceptance remain required.

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

## Bounded action admission

This section defines the target contract repaired by #5502. It admits a finite implementation
direction, not a live command. The existing authenticated BuilderOps control-plane service owns
admission; the selected workflow's existing destination owns execution and execution evidence.
No new action service, queue, DevUI store, credential route or Product/Runtime authority is added.
Live use still requires the service's authority/deployment gates and the selected destination's
implemented support. The complete DDO portfolio is required only for operations that use DDO.

### Service and destination responsibilities

| Responsibility | Existing owner / concrete producer | Present capability and remaining support |
| --- | --- | --- |
| Authenticate, authorize and persist one exact approval/handoff | `app/builderops/control_plane/service.py`, its `Credential`/repository/authority-epoch guards, and the existing transaction/record/receipt/outbox owner | Existing service primitives are reused. The finite approval admission and handoff binding below still need implementation; a UI preview or loopback read route supplies no owner identity. |
| Store an inquiry authority record | `POST /v1/inquiries` → `commit_inquiry` → `store.commit_record`; client `BuilderOpsControlPlaneClient.create_inquiry` | Accepts a caller-supplied `inquiry_id` and record idempotency key. It stores a `ModelInquiry` record; it does not invoke the sanctioned launcher or reserve an operation key against a future inquiry. Its commit receipt proves that record write only. |
| Launch the first inquiry | [Start Model Inquiry](../../.codex/skills/start-model-inquiry/SKILL.md), through the fixed `Tailscale_macmini` host alias and sanctioned `$HOME/.local/bin/yggdrasil-model-inquiry` launcher on the bound host | The existing skill owns route proof, lock, staging, single invocation and cleanup. Neither the service adapter nor DevUI may reproduce those internals. Destination operation-key reservation and authenticated status lookup are missing from this launch contract. |
| Produce inquiry execution/readback evidence | The configured launcher's existing artifact-first Model Inquiry service/runner: `ModelInquiryService.start`, `trace`, `commit_run_terminal_receipt`, `write_human_readable_report`, and `ModelInquiryRunner._finalize_terminal` | Existing inquiry artifacts and terminal JSON are reusable evidence for their inquiry. They do not yet establish a durable approval/operation-key-to-inquiry lookup. An inquiry start artifact records artifact creation; a terminal artifact records the workflow outcome, not an externally requested process stop. |
| Execute one separately approved Issue workflow | Existing `issue-to-code` → `publish-pr` → `verification-and-closure` workflow owners; when DDO is selected, #4169's request/compiler/initiation bridge plus reducer and BuilderOps outbox/effect adapters | This is a separately gated extension, unavailable through inquiry approval. Its exact workflow entrypoint/version, effects, producer/readback contract and implementation must be accepted before command admission. Existing merge/executor and deployment fences remain binding. |
| Render preview, progress and result | DevUI's separately authenticated action region, including #4697's bounded inquiry adapter | A derived projection of the above sources. Browser state, model text, a generated fixture and an HTTP acknowledgement never supply admission, launch, terminality or owner acceptance. |

### Immutable approval manifest and operation permissions

The existing admission owner persists one immutable approval manifest plus its content hash in its
existing record/receipt authority. This is a required payload contract, not a new record service or
ledger. The authenticated approval receipt binds the following complete fields:

| Field group | Exact required binding |
| --- | --- |
| Approval and principal | `approval_id`, `approval_manifest_hash`, authenticated `owner_principal`, repository-scoped authority/permission reference and version, approval receipt reference and `approved_at`; no credential or bearer-token material is retained. |
| Addressed subject | Canonical `repository` (`owner/repo`), `subject_kind`, exact `issue_number` when Issue-addressed, and exact question bytes/hash for an inquiry. A pre-ticket question explicitly carries `issue_number: null`; it cannot inherit a default repository or Issue. |
| Mutable source authority | Bounded source references with immutable revision/content hashes, exact Issue-body and acceptance-criteria hashes when an Issue exists, canonical proposal and context-pack hashes. Pre-ticket Issue/AC fields are explicitly not applicable, never inferred from another Issue. |
| Operation and destination | `operation_type`, stable `operation_key`, destination identity, exact workflow contract/version/hash and its declared entrypoint. The same approval binds exactly one key and one operation; a changed key cannot reuse that approval. |
| Effects and execution policy | Closed `permitted_effects` and explicit non-effects; exact policy, configuration and resolved capability/profile references with hashes/versions. A changed resolved target/profile invalidates approval; UI/model text cannot select a substitute. |
| Validity and revocation | Absolute `expires_at`, current permission/revocation authority reference and version, and the expected authority epoch. Admission and the destination's final pre-launch check consult current revocation/permission state. Unavailable or contradictory authority refuses launch; an old revocation snapshot is not proof of continuing permission. |

An authenticated readback binds `approval_id`, manifest hash, repository/subject, operation type/key,
workflow version and destination to the source-owned observation. It names the admission receipt,
destination reservation/launch-attempt receipt when present, `inquiry_id` or the selected workflow's
run identity when known, observed operation state, receipt references/hashes, observation time and
source revision/epoch, refusal/uncertainty reason, and stop support/status. Missing evidence remains
explicitly absent. A current readback must not reuse another subject's or candidate's receipt.

| Operation | Permitted effects | Separate gates and forbidden inheritance |
| --- | --- | --- |
| `start_model_inquiry` — first target operation | One exact question to the sanctioned inquiry workflow; its bounded model calls and BuilderOps inquiry artifacts/readiness/report under its existing contract | No code/worktree edit, Issue/PR creation or mutation, commit/push, merge/closure, deploy, Product/vault write, or owner acceptance. Inquiry readiness is not promotion approval. Promotion remains a separate governed path. |
| One approved Issue workflow — extension only | Only the effects individually named in a fresh Issue-bound manifest and admitted by that selected existing workflow | Inquiry permission cannot start `issue-to-code`. A delivery approval must explicitly name allowed repository/worktree, code, publication and closure effects as applicable and satisfy each owning skill/executor gate. Deployment requires its separate operator/promotion authority; it is never implied by delivery permission. |

### Destination reservation, reconciliation and stop

Before the first launch attempt, the existing destination must durably reserve the full
repository/destination/workflow/operation/key binding to the exact manifest hash and one inquiry/run
identity. It must enforce uniqueness across competing requests and prevent both a same-key changed
manifest and a same-approval new-key replay. The fixed launcher lock serializes its staging path;
it does not supply this durable deduplication. The existing artifact owner must add reservation and
lookup support; the control plane must not invent a parallel inquiry artifact store.

Persist the reservation before invocation and record the launch attempt before crossing the
launcher boundary. A crash between those writes and actual launch is indeterminate until the
destination proves what happened. After a timeout, duplicate submit, refresh or restart, query the
same destination binding first and project the existing reservation, active inquiry or terminal
receipt. An empty list, unavailable lookup or elapsed timeout is not proof that launch did not occur.
No automatic second launch, new key, lock deletion or staged-question cleanup resolves ambiguity.
Any continued launch from a reservation needs authoritative evidence that no attempt occurred plus
fresh pre-launch permission/source/expiry checks; otherwise preserve reconciliation-needed state.

The current sanctioned inquiry skill has **no supported stop command or stop acknowledgement**.
Report `stop_support: unsupported`; Hold before invocation makes no call. Do not add a kill, cancel,
lock-release or cleanup operation. If a later selected workflow explicitly supports stop, record its
request and destination acknowledgement separately from observed termination. A supported request
can be refused, late or still pending; acknowledgement alone never proves termination or rollback.
For DDO, typed lifecycle commands and their lawful outcomes remain in #4169's reducer/effect owners.

## Cross-Task Invariants / Interaction Safety

1. **Source before assertion:** LLM summaries can propose interpretations from bounded evidence, but only the owning source can assert a decision, deployment, trial or acceptance. Stale/contradictory sources remain visible; a failed model still leaves usable source navigation.
2. **Approval before effect:** one addressed subject/action/version crosses the existing authenticated action boundary. A new model response or changed preview never widens an existing approval.
3. **Unknown effect before retry:** if launch succeeds but response is lost, the destination's operation identity/readback must resolve it before another launch. Store a pending reconciliation state in the existing authority, not browser memory.
4. **Written fact before projection:** if a fact write commits but rendering fails, replay reads the existing receipt and regenerates the view. Render failure cannot undo acceptance or create duplicate asks.
5. **Version before inheritance:** an updated candidate, source or permission invalidates the affected preview/tryability/acceptance projection; old receipts remain history, never proof for the new candidate.
6. **Repository before defaults:** second-consumer paths must resolve their own manifest/policy/credential scope. An absent manifest refuses; hub defaults cannot fill the gap.
7. **Independent lifecycle:** Builder package boot and VM102 service lifecycle cannot require Product Runtime availability or the owner UI being open. Explicit external model dependencies remain declared; failure is visible and does not expand billing/authority.
8. **Per-workflow autonomy:** owner-platform acceptance does not grant universal unattended authority. A selected workflow carries its own stop/recovery and permission proof; deeper autonomy follows the process map's qualification/demotion contract.

The following finite table is the required admission/recovery behavior, not a claim that its missing
runtime support is delivered. Operation states are `previewed`, `held`, `reserved`,
`launch_unknown`, `active`, `terminal`, `invalidated` and `refused`. Stop status is a separate
observation and cannot rewrite the operation outcome. The service owns admission/invalidation facts;
the destination owns reservation, attempt, execution and terminal facts; DevUI only projects them.

| Initial state and event | Legal next state / effect | Required source evidence |
| --- | --- | --- |
| `previewed`; owner chooses Hold | `held`; no reservation or invocation | The exact proposal/hold observation; absence of a Start is not an execution receipt. |
| `previewed`; exact Start, fresh permission/source/expiry and supported destination | `reserved`, then one launch attempt; `active` only when the destination observes execution | Immutable approval receipt, unique destination reservation and attempt identity, then execution observation. Record persistence alone cannot supply `active`. |
| Any pre-launch state; approval expired | `invalidated`; no launch | Current time against `expires_at` and an expiry refusal/invalidation receipt. A new preview/approval is required. |
| Any pre-launch state; permission revoked or epoch/profile/policy changed | `invalidated`; no launch | Current permission/revocation/epoch or configuration evidence plus refusal reason. Stale or unavailable authority yields `refused`, never cached permission. |
| Any pre-launch state; question, repository, Issue body/AC, source, pack or workflow changes | `invalidated`; no launch | Expected versus current hashes/versions; a fresh exact preview and approval. Issue A's approval cannot execute Issue B or another operation. |
| `reserved` or `active`; response lost, malformed or nonzero after launch may have begun | `launch_unknown`; no retry or cleanup | Preserved reservation/attempt, exact key and transport outcome; destination lookup returns active/terminal evidence or remains unknown. |
| `reserved`, `launch_unknown`, `active` or `terminal`; same-key duplicate or caller/service restart | Existing state, or advance only to the destination-observed `active`/`terminal`; no second launch | Authenticated key-to-manifest-to-inquiry/run readback and receipt hashes. A changed manifest/key binding is `refused` as a conflict; it does not replace the original operation. |
| `reserved`; destination proves no launch attempt occurred | Remain `reserved`; first launch may proceed only after fresh pre-launch checks | Durable negative attempt evidence from the destination, not missing UI/API data. If this proof is unavailable, use `launch_unknown` and reconcile. |
| `active` or `launch_unknown`; source changes, expiry or revocation after a possible effect | Preserve observed execution/uncertainty; withdraw further permission and stale projections | Invalidation and current destination readback. Do not erase effects, imply rollback, or relaunch under a new approval while the old operation is unresolved. |
| `active` or `launch_unknown`; valid inquiry terminal response/readback | `terminal`; render the actual outcome and limitations | Exit-zero launcher response whose entire stdout is one JSON object with non-empty `inquiry_id`, `final_state`, `terminal_receipt_id`, `human_readable_report`, matched to the bound destination artifacts. Lost-response recovery must obtain authenticated equivalent source evidence; current skill ambiguity rules remain until that lookup is implemented. |
| Any attempted inquiry; stop requested | Operation state unchanged; stop status `unsupported` | The current workflow's stop-support declaration; no invented request/acknowledgement or termination receipt. |
| A separately admitted workflow with stop support; stop requested, then acknowledged | Preserve operation state; stop status `requested`, then `acknowledged` only on destination evidence | Separately authorized exact run/key-bound request and acknowledgement receipts. A refused or unavailable stop remains explicitly so. |
| Supported stop; destination later observes termination | `terminal` only as the workflow's terminal contract allows; stop status `termination_observed` | Source-owned termination observation and terminal outcome, including partial effects. Request, acknowledgement, process absence, and rollback are not interchangeable proof. |
| `terminal`; receipt rendering fails | `terminal`; regenerate the derived view without launch or mutation | Re-read the same terminal receipt/report; rendering failure does not remove execution evidence or create owner acceptance. |

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
