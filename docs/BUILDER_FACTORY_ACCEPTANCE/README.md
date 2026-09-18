State: Accepted target-state gap/acceptance specification. FCA-01..05 have repository implementations;
composed platform deployment and owner acceptance remain unproved.
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
| #5404 [FCA-05 — Produce owner decision and trial facts](PRODUCE_OWNER_DECISION_AND_TRIAL_FACTS.md) | Implemented authenticated four-fact producers, atomic outcome correction/replay and Overview/Focus readback | Repository transaction/API proofs only; live source admission, human grant and owner observations remain parent gates |
| #5405 [FCA-06 — Qualify a second consumer repository](QUALIFY_SECOND_CONSUMER_REPOSITORY.md) | Implemented production-composed conformance harness, read-only validator and incomplete second-consumer pilot procedure | Finite hub/Bifrost/third-repository proof; live #3793/#5181 qualification, concrete host candidate/transport/bootstrap, authenticated M2 UI, consumer preparation and operation recovery remain parent gates. |
| #5406 [FCA-07 — Prepare composed owner acceptance](PREPARE_COMPOSED_OWNER_ACCEPTANCE.md) | Implemented pre-merge composed harness, read-only receipt validator and explicit incomplete operator plan | Consumes FCA-03, FCA-05 and protected hub Issue-delivery/readback seams. #5405 live second consumer, #4749/#5181 and explicit owner acceptance remain incomplete parent gates; fixture success cannot pass them. |

FCA-02 is a contract-enrichment task, not authorization to invent a source store. FCA-05 pickup requires its exact accepted producer/source/action contracts and the selected operation's external admission/readback prerequisites. FCA-05 implements the four producers and outcome read transport; runtime activation still requires source admission. FCA-03 delivered independently using existing admitted sources; it emits interpretations/proposals rather than canonical owner facts. Amend affected specs and live Issues before pickup. The bounded admission contract below separates the first inquiry seam from #4169's DDO bridge; neither this contract nor an inquiry supplies an owner outcome or an Issue-delivery operation.

### Contract-repair tasks

These tasks repair remaining executable-contract gaps under the existing owner documents. They
specify the next work, not new admitted action/data/runtime authority. Existing closed children stay
closed. No later implementation dependency changes until the owning repair is delivered and the
affected live Issue is reconciled. Only these first tasks are published now; later implementation
breakdown follows their accepted results.

| Task | Bounded outcome | Order |
| --- | --- | --- |
| #5502 [FCA-08 — Define bounded action admission](DEFINE_BOUNDED_ACTION_ADMISSION.md) | Contract defined below for the existing control plane and destination owners | Runtime admission, destination reservation/readback and activation remain separate work |
| #5503 [FCA-09 — Define owner outcome authority](DEFINE_OWNER_OUTCOME_AUTHORITY.md) | Separate candidate-bound trial/acceptance contract defined in the existing object/receipt owner | FCA-05 implements producer/readback; runtime admission and owner observations remain separate |
| #5504 [ARO-09 — Reconcile managed owner pilot](../DEVUI_STAGE_A_READ_ONLY_OVERVIEW/RECONCILE_MANAGED_OWNER_PILOT.md) | Managed runtime/source and pre-merge versus live evidence contract defined | Owned by Stage A / #4741; runtime, read-only pilot and full-platform acceptance remain separate. |
| #5531 [First approved Issue-delivery operation](#first-approved-issue-delivery-operation) | Finite M2 operation contract defined under FCA-08 | The implementation slices below, destination activation and actual owner evidence remain separate. |

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
contract direction. FCA-05 now implements its existing-service writer and production-path proof;
the retained P1 requires that fixing merge and original-thread readback at closure. Runtime source
admission and real human outcomes remain separate; live Issue maintenance follows merge.

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
implemented support. For the first inquiry, FCP-04 implements the
[finite skill facade and host protocol](../BUILDEROPS_MODEL_INQUIRY/README.md#approved-inquiry-operation-interface),
including authenticated control verbs, reserved identity propagation and one runtime cleanup
implementation. This repo-local implementation contract is not permission to inspect/change the
live host wrapper, credentials or deployment. The complete DDO portfolio is required only for
operations that use DDO.

### Service and destination responsibilities

| Responsibility | Existing owner / concrete producer | Present capability and remaining support |
| --- | --- | --- |
| Authenticate, authorize and persist one exact approval/handoff | `app/builderops/control_plane/service.py`, its `Credential`/repository/authority-epoch guards, and the existing transaction/record/receipt/outbox owner | FCP-04 implements immutable `ModelInquiryApproval`, exact preview/Start/Hold and authenticated destination authority queries in this service. A UI preview or loopback read route supplies no owner identity. Other operation types remain separately gated. |
| Store an inquiry authority record | `POST /v1/inquiries` → `commit_inquiry` → `store.commit_record`; client `BuilderOpsControlPlaneClient.create_inquiry` | Accepts a caller-supplied `inquiry_id` and record idempotency key. It stores a `ModelInquiry` record; it does not invoke the sanctioned launcher or reserve an operation key against a future inquiry. Its commit receipt proves that record write only. |
| Launch the first inquiry | [Start Model Inquiry](../../.codex/skills/start-model-inquiry/SKILL.md), through the fixed `Tailscale_macmini` host alias and sanctioned `$HOME/.local/bin/yggdrasil-model-inquiry` launcher on the bound host | The existing skill owns route proof, lock, staging, single invocation and cleanup. Neither the service adapter nor DevUI may reproduce those internals. FCP-04 supplies the concrete facade/protocol, reservation, authenticated readback and reserved-ID propagation. Runtime Start requires the operator-owned wrapper to advertise that exact protocol and current scoped permissions; manual-only wrappers refuse. |
| Produce inquiry execution/readback evidence | The configured launcher's existing artifact-first Model Inquiry service/runner: `ModelInquiryService.start`, `trace`, `commit_run_terminal_receipt`, `write_human_readable_report`, and `ModelInquiryRunner._finalize_terminal` | FCP-04 adds immutable approval/key-to-inquiry reservation, pre-invocation attempt and atomic entry in these existing artifacts, plus exact authenticated terminal/readback evidence. An inquiry start artifact records artifact creation; a terminal artifact records the workflow outcome, not an externally requested process stop. |
| Execute one separately approved Issue workflow | Existing `CodexIssueSessionLauncher` and `issue-to-code` → `publish-pr` → `verification-and-closure` owners | The [first Issue operation](#first-approved-issue-delivery-operation) defines the finite extension. FCA-ID-A admission, FCA-ID-B destination reservation/attempt/entry and protected effects, and #5552/FCA-ID-C independent repository readback have repository support. Live activation/deployment, one real delivery, candidate trial and owner outcome remain unimplemented. Inquiry approval grants none of its effects. Existing merge/executor and deployment fences remain binding. |
| Render preview, progress and result | DevUI's separately authenticated action region, including #4697's bounded inquiry adapter | A derived projection of the above sources. Browser state, model text, a generated fixture and an HTTP acknowledgement never supply admission, launch, terminality or owner acceptance. |

### Immutable approval manifest and operation permissions

The existing admission owner persists one immutable approval manifest plus its content hash in its
existing record/receipt authority. This is a required payload contract, not a new record service or
ledger. The authenticated approval receipt binds the following complete fields:

| Field group | Exact required binding |
| --- | --- |
| Approval and principal | `approval_id`, `approval_manifest_hash`, authenticated `owner_principal`, repository-scoped authority/permission reference and version, approval receipt reference and `approved_at`; only non-secret credential identity/rotation/scope metadata and a `permission_version` may be retained, never a bearer verifier or fingerprint. |
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

<!-- anchor: FCA-ID-01 -->
### First approved Issue-delivery operation

Stable source anchor: **FCA-ID-01**. Target contract `fca-issue-delivery.v1`, operation type
`deliver_ready_issue`. This is the first separately approved Issue operation for
[M2](#first-repository-milestone), defined by #5531. FCA-ID-A delivers the repository-only
authenticated preview/Hold/Start approval and durable receipt; destination execution and
independent readback are not implemented or activated by this document. It delivers exactly one bounded, open, strictly valid `agent:ready` Issue in
`RasmusTho/agentic-pkm-mvp` through one fresh Codex Issue session at one explicitly admitted
execution destination. It selects no sibling or parent delivery. A required parent evidence write
is a separately bound effect below. Project Status is not a pickup gate.

**Current availability and selected reuse.** The legacy
`app/builderops/cli.py::dispatch_sessions` command first authenticates the committed FCA-ID-A
approval and exact durable operation readback before any destination, isolation-profile or executor
preparation. A terminal, active or ambiguous existing operation is returned for reconciliation with
no new child preparation; only a not-started or reservation-only operation requires the explicit
#5559 isolation profile and host-installed #5558 protected-executor composition. It has no
caller-selected executor factory or environment selector. The fresh path routes through the FCA-ID-B
destination adapter before any child entry and remains fail-closed without that complete host
composition. Bootstrap pins the stable isolation-profile hash and host dependencies. After all
validated live probes but before the isolated child enters, the host builds and freezes its own
isolation receipt, executes the typed Issue claim, and requires its applied/readback-confirmed
receipt. Worker-returned JSON cannot supply or replace this per-launch evidence. Only after the
worker returns may the host consider separately typed publication, merge, closure, or
parent-evidence effects, bound to that same receipt. The dormant
`LinuxSystemdCodexIssueSessionLauncher`, content-only worker, and protected host executor are
#5558's repository prerequisite; FCA-ID-B now integrates them with the durable operation fences.
Historically, the legacy command
loaded a frozen plan and constructed
`app/builderops/epic_dispatch.py::CodexIssueSessionLauncher`; `dispatch_issue_sessions` calls its
`launch` method. The launcher invokes `codex exec --json --sandbox workspace-write`, resolves
the configured execution target and loads `.codex/agents/slice-implementer.toml` instructions. The
rebuildable BuilderOps image packages that adapter and `docs/settings/models/providers.yaml`, and
the image smoke check instantiates the launcher preflight against those packaged paths.
Those instructions require the worker to self-claim and perform `issue-to-code`, `publish-pr`,
`verification-and-closure`, owner-doc reconciliation and closeout. This is a full delivery worker,
not an edit-only worker. Agent reasoning and bounded execution remain permitted under DP-02C;
neither deterministic orchestration nor full DDO is a universal M2 prerequisite.

The #5551 admitted adapter must restore that call chain only with a frozen plan containing exactly one selected
Issue/context pack, no canary/fallback route and an independently retained `expected_plan_hash`.
`dispatch_issue_sessions` still accepts broader plans for non-delivery callers; the adapter enforces
this narrower operation and rejects canary/fallback routing. The CLI obtains its authenticated
BuilderOps client from host configuration, while the durable reservation/attempt/entry/terminal
receipts are committed through the dedicated operation route. Local `epic_run_state.py` JSON remains
coordination evidence only. The worker cannot replace the approval, protected executor or owning
effect-gate checks with prompt text.

**Exact approval.** Extend the [FCA-08 manifest](#immutable-approval-manifest-and-operation-permissions)
within its existing owner. Before Start, it must bind all of these values without defaults:

- `repository`, numeric Issue identity, node identity, immutable canonical Issue URL/scope and
  `agent:ready` label binding, caller-bound Issue body/AC hashes, one
  immutable 40-character Git commit source revision, proposal/context-pack hash, and a complete
  one-Issue frozen dispatch plan with its independently retained `expected_plan_hash`. The plan
  contains the planner's bound scope or `epic_issue_number`, run-state observation, validation
  ledger, publication/closure expectations, exactly one selected Codex Issue/context pack, and a
  launcher-compatible run identity. Its destination branch/worktree/run ID and resolved
  model/reasoning are the same values the launcher will execute; it has no canary/fallback route.
  Admission reuses the planner/launcher frozen-plan preflight rather than trusting a source label.
  FCA-ID-A seals these source/profile identity hashes immutably; it does not independently re-read GitHub or
  recompute source/profile truth before Start;
- parent evidence destination: explicit `none`, or one exact parent repository/number/node,
  source-authenticated relationship to the selected Issue, current parent contract hash/version,
  and permission for PR-specific receipt comments and this child's generated-ledger writeback.
  If the selected workflow requires parent writeback, an absent binding refuses launch; it cannot
  infer a parent later. Preview and Start both enforce the authenticated owner's repository scope
  for this destination. This evidence destination grants no parent delivery, contract or acceptance
  change, closure, or sibling mutation;
- operation type/version, `approval_id`, one `operation_key`, owner principal, and an explicit
  owner-profile principal equal to the authenticated owner, plus approval receipt, expiry and
  current repository/operation grant, revocation version and authority epoch;
- one destination identity: authenticated executor principal, host/system identity, channel,
  canonical repository checkout, dedicated worktree/branch, target base ref and observed base SHA,
  plus one proposed run identity allocated without effects for the preview. Start approves that
  exact identity, cross-checked against the full Issue contract and frozen dispatch plan; the
  worktree cannot equal the checkout or filesystem root, and the branch cannot equal the base ref.
  Admission resolves existing filesystem symlink parents before this overlap check; FCA-ID-B must
  re-resolve the checkout/worktree identities immediately before any effect because the filesystem
  may change after approval. Only after approval commits may the destination durably reserve it. A Codex
  session ID is attached only when observed;
- exact entrypoint `app/builderops/epic_dispatch.py::dispatch_issue_sessions` with
  `CodexIssueSessionLauncher.launch`, workflow contract `fca-issue-delivery.v1`, immutable source
  commit and a content-hashed artifact manifest for the CLI/launcher, role adapter and selected
  owning skills/shared gates. `workflow_hash` is SHA-256 of that manifest's canonical JSON (sorted
  keys, compact separators, UTF-8); every artifact entry binds path and SHA-256 of its exact bytes.
  The source commit pins their repository dependencies. A live request must contain resolved
  hashes, never a moving `main`, an example revision or a version label alone;
- the closed execution profile: provider-census hash, configuration digest, provider-neutral
  `general_delivery` selection intent, resolved capability/model/reasoning/carrier,
  top-level profile hash equal to the canonical closed profile content,
  verification-profile hash equal to the canonical criterion-hash map, and required criterion hashes. The
  context hash is top-level and equals the canonical selected context pack; Git source references
  equal the single immutable source revision, and the explicit non-effect list equals the complete
  closed set. This first operation is qualified only for `RasmusTho/agentic-pkm-mvp`; expanding
  credential repository configuration does not expand this operation. This operation's resolved carrier is
  Codex and must agree with the frozen dispatch context. Unknown or incomplete profile fields
  refuse admission; an unavailable target withdraws launch.

The target destination may be bob-1 only after its separately authorized runtime qualification and
activation. This source contract chooses no live host, credential or deployment. Workflow/profile,
base, source or Issue contract drift requires revalidation and a new exact approval before another
effect; it never silently changes the immutable manifest. The operation's own expected label,
branch and PR transitions are evidence of this workflow, not an Issue-body/AC change.

| Closed permitted effect | Owning boundary and limit |
| --- | --- |
| Repository/worktree preparation and edits | `issue-to-code` and `publish-pr`: one registered isolated worktree/branch, Issue-scoped code/tests/owner docs and required validation. No shared-root edits, unrelated path mutation or history rewrite. |
| Issue claim and active lifecycle | The protected host Issue-delivery adapter, under `issue-to-code`, constructs the exact mandatory claim and requires durable applied/readback proof before content-worker entry. The content worker cannot claim, and this admitted path has no dispatcher or label-only claim fallback. Lease/label evidence is not owner approval. |
| Publication | `publish-pr`: bounded commits, non-force push and one exact linked PR; record/read back the PR identity. Repairs remain within the approved Issue and current publication gates. |
| Review and merge | `verification-and-closure`: current-head AC/CI/review proof and the selected light/full route. Full-path neutralization, fixed merge message, authenticated closing set and any required `host_fenced_executor` remain binding; approval does not supply an executor credential or waive a gate. |
| Closure and delivery reconciliation | `verification-and-closure`, `post-merge-owner-doc` and `klart`: close only this authenticated delivered Issue, remove its active labels, reconcile its lease/worktree and post PR-specific evidence on it. On the exact approved open parent evidence destination, permit only those receipt comments and this child's generated-ledger writeback, preserving the parent contract and other child entries. Re-read parent identity, open state, relationship and contract at this write boundary; drift withdraws the effect and requires reconciliation, never target substitution. Parent closure, unrelated Issue mutation and new backlog extraction are excluded. |

All five effect groups must be explicitly approved for this first operation. A partial grant refuses
the full-chain launcher; it does not reinterpret it as inquiry or edit-only. Model calls and a
required bounded read-only reviewer are confined to the approved profile and owning skill budget.
Deployment, release/stable movement, credential provisioning/rotation, host setup, destructive
database/vault operations, other repository/Issue effects beyond the exact parent evidence grant,
owner confirmation and universal unattended
execution are explicit non-effects. A newly required effect pauses at its owning gate; consent to
this operation cannot widen the selected Issue or convert a technical receipt into owner acceptance.

<!-- anchor: FCA-ID-02 -->
### Issue-delivery admission and readback

Stable source anchor: **FCA-ID-02**. These are responsibilities of existing owners. FCA-ID-A
implements the authenticated Issue approval/readback seam below; #5551 supplies the FCA-ID-B
destination adapter, and this #5552 candidate supplies FCA-ID-C repository readback. Live
activation, deployment, the first real delivery, candidate trial and owner outcome remain separate.
No second service, queue, store or authority registry is needed.

| Boundary | Existing owner and required adapter responsibility |
| --- | --- |
| Preview, Hold, immutable Start approval and invalidation | `app/builderops/control_plane/service.py::create_app`, `CredentialRegistry` and the existing record/receipt API. FCA-ID-A adds a finite Issue-command subtype with an explicit repository-scoped owner approval grant and separate destination execute/read grants; generic record write or inquiry scopes cannot satisfy them. Match the authenticated human owner to the addressed profile. Hold produces no reservation or invocation. Persist exact approval through `PostgresBuilderOpsStore.commit_record` and its transaction receipt before dispatch. The store's central idempotency guard reserves this subtype's `issue-delivery:` prefix across generic records, task transitions, authority objects and lease operations; only the exact admitted IssueDeliveryApproval writer may use it. Concurrent identical Starts converge on the first durable approval: a losing commit re-reads and returns the winner's receipt as a replay, while changed manifests remain conflicts. |
| Durable reservation and attempt | The destination adapter surrounding `CodexIssueSessionLauncher`, writing through the same authenticated service and PostgreSQL transaction/receipt/outbox owner in `control_plane/store.py`. It uses existing `BuilderOpsReceipt` record envelopes with destination-owned reservation/attempt payloads, not local run-state as authority. The #5551 candidate's finite guarded operation binds the full repository/destination/workflow/type/key and approval identity to one manifest/run, rejecting competing or changed bindings. An unresolved operation for the same physical checkout/worktree/branch, including one admitted for another Issue, prevents another launch; a verified terminal record or an expired exact approval with no attempt is the only reusable boundary. |
| Attempt and actual entry | Persist reservation, then a unique attempt receipt before calling the existing launcher; the destination durably observes that same attempt's actual process entry/session binding separately. Every lifecycle write, including entry and terminal, requires the destination's `issue_delivery:execute` grant; `issue_delivery:read` only reads. Once an attempt exists, entry/terminal retain their immutable approval and predecessor bindings without rechecking mutable expiry, revocation, source or filesystem facts. Existing outbox intent/claim/reconcile remains the delivery mechanism where needed; an outbox retry performs exact lookup before dispatch and cannot create a second attempt. The bounded stream path forwards `thread.started` incrementally for crash-safe entry evidence. |
| Continuing effects | The authenticated service supplies fresh permission/revocation/epoch, expiry and source/profile readback to the host-owned pre-entry claim and each post-worker publication/merge/closure boundary. Implement the manifest/run linkage at those real gates, not only in worker instructions. Local files and skills retain their present ownership; no new workflow engine drives them. If a gate cannot enforce the binding, this operation stays unavailable. |
| Independent result reconciliation | Extend the existing authenticated control-plane readback with a bounded Issue source adapter. Reuse GitHub REST evidence acquisition from `cockpit_github_plane.py::default_github_reader` and the applicable read methods of `verification_github.py::GitHubProtectedRepositoryAuthority`; neither the overview summary nor a worker-supplied receipt suffices. Persist source references/hashes, observation time, epoch, exact identities and missing/contradictory evidence through the existing receipt owner. Read credentials remain separately scoped; reads confer no merge authority. |
| Owner projection and outcome | Existing DevUI Overview/Focus/action projection renders that readback and source links. Existing FCA-05 producer/service and the [FCA-09 outcome owner](../builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md#candidate-bound-owner-outcome-contract-fca-09) retain exact candidate/profile/trial/acceptance authority. The loopback GET listener, worker text, dispatcher and browser supply no approval or owner fact. |

The addressed Issue must also reach the existing BuilderOps-owned task envelope consumed by
`devui_sources.py::_task`. Its admitted payload needs the native `TaskRecord` Issue identity
(`repo`, `task_id`, `issue_number`, `title`), source/version references and matching service-owned
repository/state/version/lease envelope. The bounded adapter must use the existing authenticated
`/v1/tasks/transition`/task lifecycle API and `PostgresBuilderOpsStore.commit_transition`, then
re-read that envelope through the existing task GET path; current source/body hashes remain bound
to the approved Issue. Generic CLI tasks, verification documents and a legacy local dispatcher
claim do not supply this projection. FCA-ID-C owns this exact one-Issue producer/read-path proof;
enabling a source overlay alone cannot populate Overview. This is an extension of the existing
task owner, not a second task store or general import engine.

Authenticated readback carries the complete FCA-08 approval/key/manifest/workflow/destination/run
binding, the independently observed Codex session when available, reservation/attempt/entry
receipt refs, state and stop support. It also carries these finite source-owned evidence groups:

| Projection claim | Required independent source evidence |
| --- | --- |
| Claimed or locally changed | Fresh GitHub Issue identity/state/labels and contract hashes; destination registry/lease ownership, branch/worktree and Git HEAD/diff observations. A lease proves coordination only; an edit proves neither publication nor delivery. |
| PR published | Exact repository and PR number/node, head repository/ref/SHA, base ref/SHA, current body and governing/closing identities from GitHub; matching destination commit. Missing, multiple or conflicting PRs remain unresolved. |
| Verified on a candidate | Check-run/status identities and latest conclusions on that exact head, required-check configuration digest, and the selected workflow's authenticated current-head review evidence and disposition of actionable findings. A green summary or model's AC verdict cannot replace the governing `Verify:` evidence. Later head/body/Issue/check-policy drift supersedes affected evidence under the existing closure contract. |
| Merged and closed | GitHub merge timestamp/commit, target-base reachability and exact Issue state/closure attribution; the selected closure path's source-authenticated reconciliation evidence, including full-path restored-body/phase receipts when applicable. Require the PR-specific owner-doc receipt and final active-label/lease/worktree reconciliation. An open PR, process exit or `final_state` message never proves this outcome. |
| Ready for owner trial | The candidate owner's exact source commit, deployed image/config/environment/readiness refs, acceptance profile and per-criterion results/limits, joined to the operation and delivered merge. FCA-05 currently admits only its specified VM102 `devui_projection` source/profile chain. Another artifact/candidate owner needs a separately accepted source contract; a GitHub merge cannot manufacture a qualifying candidate. |

The worker's `subagent_handoff_receipt` is a pointer to evidence and a diagnostic proposal. Signing
or transporting it authentically proves authorship, not its delivery claims. Reconciliation reads
the bounded sources independently, including when the worker reports failure, handoff or success.
`terminal` records the observed operation outcome, including failed/partial delivery; `delivered`
is projected only when the applicable repository evidence agrees. Missing source groups withdraw
their claims without deleting intact historical evidence. Owner trial and acceptance remain separate
FCA-09 writes by the authenticated human against the exact candidate/profile; Start, technical
success and document publication record no human consent to the result.

<!-- anchor: FCA-ID-03 -->
### Issue-delivery interruption and reconciliation

Stable source anchor: **FCA-ID-03**. Reuse FCA-08 operation states; stop status remains separate.
The table binds the service admission owner, destination adapter and source readers above. There
is no assumption that GitHub/worktree effects roll back atomically with a service transaction.

| Event / observed state | Lawful next action | Required evidence and unsupported behavior |
| --- | --- | --- |
| Hold before invocation | `held`; perform no claim, reservation or launch | Exact Hold/preview binding. Absence of Start is not a terminal execution receipt. |
| Approval committed; crash or replay before reservation | Preserve the immutable approval and pre-reservation state; after fresh checks, perform only the first reservation of its proposed run ID | Complete service approval receipt and authoritative absence of reservation/attempt/entry under the destination guard. Unavailable or contradictory lookup stays unresolved; do not allocate a new run ID or re-confirm/mutate the original approval. |
| Same-key replay, refresh, competing submit or service restart | Return the existing reservation/active/terminal observation; reconcile before any effect | Unique key + approval + manifest + run readback from the destination-owned service records. No second session, attempt or synthetic success. |
| Same key with changed manifest, or new key reusing approval | `refused`; preserve original operation | Atomic key and approval binding conflict. No overwrite, key rotation or approval reuse; a genuinely new operation needs fresh approval and a resolved predecessor. |
| Permission revoked/expired, epoch changed, or authority unavailable before launch | `invalidated` or `refused`; no invocation | Fresh service grant/epoch/time readback against the immutable approval. Cached permission and inquiry consent are insufficient. |
| Issue closed/claimed by another worker, changed body/AC/source/base, or changed workflow/profile | Before effect, invalidate/refuse and obtain a new exact preview/approval; after a possible effect, preserve observed state and withdraw further permission | Fresh Issue/claim/branch and content/profile hashes, plus source-owned prior effect readback. Do not treat the operation's own expected claim as foreign drift, rebase under old approval, substitute a model or continue closure against a changed contract. |
| Crash after reservation but before any attempt | Keep `reserved`; only the first attempt may proceed after fresh checks | Transactionally complete destination reservation and authoritative negative attempt/entry evidence under the same guard. An empty API result, missing local file or timeout is not negative proof. |
| Crash after attempt but before confirmed entry, or after entry with lost response | `launch_unknown`; reconcile the same binding and inspect existing effects | Durable attempt and entry/session observations plus GitHub/worktree readback. An attempt without entry proof remains ambiguous; no retry, new session, new key or cleanup to hide uncertainty. |
| Worker ends or disappears, with missing/contradictory source readback | Preserve uncertainty or the proved partial/terminal outcome; repair source access/readback first | Exact destination observation plus independent PR/head/CI/review/merge/closure evidence. Exit zero, nonzero exit, process absence and worker text do not decide delivery or authorize a rerun. |
| Revocation/expiry/source drift after launch, including queued later effects | Preserve completed effects; refuse subsequent effects at their owning gates and reconcile | Current service invalidation and destination/source receipts. No retroactive cancellation, automatic rollback or replacement launch while unresolved; readback remains available under its own read grant. |
| Owner client disconnects or render fails | Continue only already admitted effects whose fresh gates still pass; rebuild the view by authenticated readback | Service/destination receipts survive the client. Disconnect is neither Hold, revocation, stop nor failure; reconnect never starts another worker. |
| Stop requested after an attempt | Report `stop_support: unsupported`; retain observed operation state | The selected `CodexIssueSessionLauncher` has no stop/control API, process handle contract or stop acknowledgement. Do not invent kill/cancel/lock deletion, termination proof or rollback. Revoking future effect permission is separate from stopping an in-flight process. |
| Exact merge exists but closure/reconciliation is incomplete | Read and finish only the missing steps through `verification-and-closure`, with current authorization | Authenticated exact-head merge/closure state and, on the full path, the existing continuous authority/phase ledger. Do not launch a replacement delivery worker or repeat merge. An expired/revoked grant requires the owning recovery/approval route, not implied permission. |
| All required source readback agrees | Record the actual `terminal` outcome, project repository delivery when proved, and leave owner outcome separate | Original approval/run plus all applicable source groups above. A trial still requires its own ready candidate and explicit FCA-09 confirmation. |

<!-- anchor: FCA-ID-04 -->
### Issue-delivery implementation slices

Stable source anchor: **FCA-ID-04**. The smallest bounded sequence is three serial repository
slices. FCA-ID-A is delivered by #5550 as repository-only admission support, FCA-ID-B is delivered
by #5551 as repository-only destination support, and this #5552 candidate delivers FCA-ID-C
repository readback through the existing task, source-reader and DevUI owners. Each Issue binds its
exact production surface and inline `Verify:` targets. These repository proofs do not claim live
activation, deployment, candidate trial or owner acceptance.

The credential-isolation and protected-effect prerequisites for FCA-ID-B now have repository
support through a dormant Linux/systemd adapter around the existing Codex Issue-session launcher
and the host-only `IssueDeliveryHostExecutor`. A pinned host profile binds
the exact distinct executor/worker principals (including an empty worker supplementary-group set),
content/mode/ownership executable identities, a clean-worktree identity and its exact linked
per-worktree/common Git administration directories, a private worker-owned `0700` model-login
directory, fixed isolation properties, and direct-command hash.
Immediately before entry, the
fork/drop-GID/drop-UID probes must return only typed proof that the executor-owned GitHub effect
credential is unreadable, every regular worktree/model-state file and directory is effectively
editable by the worker through POSIX permissions/ACLs, and the linked Git control file,
per-worktree index/`HEAD`, common refs, and objects remain non-writable. The unit grants only
worktree-content and model-state write apertures; the nested Git control file plus both Git
directories are explicit read-only paths, and their identities, typed metadata denial, and
executable facts are revalidated and receipt-bound without persisting their paths. Same-user,
uneditable worktree, writable Git metadata, readable/missing/aliased credential, primary checkout,
drifted, shell-mediated, and unsupported-host cases refuse with no legacy fallback. This
worker boundary is not same-user environment cleanup: the worker has a distinct UID/GID, no
supplementary groups, no repository effect identity, and no write path to linked-worktree or common
Git metadata. The owner/release path supplies the pre-created exact checkout/worktree/branch/base
destination; the host then freezes and verifies its origin and Git directory identities before
child construction. The freeze step performs no mkdir, branch, or worktree mutation. The protected
executor uses an explicit host-configured live-binding reader for current source/profile facts, and
the systemd boundary receives PATH from the approved worker profile rather than the coordinator's
ambient shell;
missing live binding is a hard refusal, never an echo of immutable approval. The host owns the mandatory
pre-entry Issue claim; a content-only worker may propose only a strict typed
publication/merge/closure/parent-evidence request. Worker diagnostics cannot carry host
effect receipts or references. The host executor then re-reads the
exact approval, destination, source/profile/target and protected credential manifest immediately
before the effect, resolves the opaque repository-scoped credential only after those gates, and
persists the effect intent through the existing authenticated BuilderOps PostgreSQL
task/transaction/outbox owner. One approval/run and semantic effect target owns one stable slot;
changed mutable request content cannot allocate a parallel operation while that slot is unresolved.
After credential resolution the executor revalidates the exact worker, fencing token,
intent/claim LSNs, receipt, expiry, task and effect against the database clock, then atomically and
idempotently consumes that exact fence into durable `unknown` before transport. Only the matching
commit receipt permits the call, so recovery between eligibility and dispatch cannot authorize a
stale process. Authoritative source readback uses the separate Issue-delivery read grant. Entry and
terminal observations retain their immutable approval/predecessor/hash bindings even after Issue
closure, source/profile drift, or execute-grant expiry; those current-fact checks apply only to
reservation and attempt effects. A recovered attempt receives a distinct readback-only fence and is never `effect_eligible`; positive
readback may settle a committed dispatch, while negative or ambiguous readback remains `unknown`
and cannot reopen retry because an admitted transport may still complete. Only the explicit
pre-transport refusal path may reconcile `not_applied` back to pending. Terminal observations retain
only a bounded list of exact host outbox references (operation, request and effect-slot hashes),
built from actual executor receipts and revalidated against the admitted
approval/run/repository/Issue binding; they make no separate applied-outcome claim. Typed receipts
bind hash identities while excluding raw credentials and local paths.

FCA-ID-B now integrates destination reservation, attempt and observed entry into the production
dispatch chain and rechecks the approved authority at owning effect gates through the protected
executor seam. #5552/FCA-ID-C adds a version-bound native task admission/readback, independently
parses exact Issue/PR/head/check/review/merge/closure state, ignores worker outcome claims, and joins
only the exact current FCA-09 candidate/profile binding into Overview and the pure Focus adapter
when a bounded caller supplies that addressed delivery projection. The standalone managed Focus
route keeps the M1 selected-Issue boundary and does not rescan the BuilderOps task root. Bob
activation/profile and credential provisioning, deployment, the first real delivery, candidate
trial, and owner outcome remain pending.
No bob principal, credential, profile, ACL, service, or deployment is created or activated here.
The future host-profile producer owns recursive worktree content permission; local
stage/commit/ref/object mutation and publication remain protected host-executor effects, without a
Git/common/worktree-parent aperture for the worker.

The same three slices cover parent evidence without another operation: A must prove exact or
explicitly absent parent admission and reject missing/foreign targets when writeback is required;
B must prove bounded receipt/child-ledger effects, preservation of the parent contract and other
child entries, and withdrawal for a closed, changed or substituted parent; C must independently
read back the approved target and permitted evidence. No parent effect is inferred from a child
merge or from a worker's proposed target.

Stable implementation-slice anchors:

- `FCA-ID-A`
- `FCA-ID-B`
- `FCA-ID-C`

| Order / stable source anchor | Bounded change and production callers | Resolvable verification obligation |
| --- | --- | --- |
| 1 — **FCA-ID-A** — delivered by #5550 | Existing `service.py::create_app` and record/receipt API, `CredentialRegistry`, existing client and `PostgresBuilderOpsStore.commit_record`: exact one-Issue preview/Hold/approval/read grant and immutable manifest, generic-write bypass refusal, caller-bound source/profile identity hashes and manifest-drift refusal. No launcher invocation or independent GitHub/source re-read. | `tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_production_admission` calls the real service/credential/store path and covers owner vs inquiry/generic grants, exact hashes, Hold, replay, revocation/expiry and immutable approval. `::test_issue_approval_transaction_recovery` proves committed approval/readback versus pre-commit rollback. |
| 2 — **FCA-ID-B**, delivered by #5551 after A | #5551 restores an authenticated destination adapter at `cli.py::dispatch_sessions` → `epic_dispatch.py::dispatch_issue_sessions` → `CodexIssueSessionLauncher.launch`, backed by the same service transaction/receipt/outbox owner; binds unique reservation/attempt/entry and current authority into the protected effect-gate seam. Live activation, deployment, independent readback and owner outcome remain separate. | `tests/builderops/test_issue_delivery_operation.py::test_production_dispatch_reservation_and_crash_matrix` enters the adapter and exercises crashes before/after attempt and lost entry response. `::test_delivery_effect_boundaries_recheck_authority` reaches the owning gates, refuses changed/revoked authority before the next effect and proves no second launch. `::test_selected_launcher_reports_stop_unsupported` covers truthful stop. Substitute only external effect transports; a stubbed gate verdict is insufficient. External GitHub transports and FCA-ID-C readback remain separate. |
| 3 — **FCA-ID-C**, delivered by #5552 after B | Existing authenticated task lifecycle API and `devui_sources.py::_task` admit/read the one Issue-bearing task envelope; service readback, bounded GitHub REST source reads and DevUI projection compose exact Issue/PR/head/CI/review/merge/closure evidence with the admitted candidate/profile source. Missing, generic, stale or contradictory bindings withdraw the projection. FCA-05 remains the sole owner-outcome writer. This is repository support, not live delivery evidence. | `tests/builderops/test_issue_delivery_readback.py::test_production_issue_task_envelope_reaches_overview` covers native Issue creation/version readback into Overview/Focus. `::test_production_readback_uses_independent_github_evidence` covers forged worker success, missing/contradictory sources, late-head drift, partial closure and reconnect. `::test_issue_delivery_candidate_profile_linkage` proves exact FCA-09 candidate/profile binding and withdrawal on unsupported/mismatched candidates. |

After these pre-merge adapters/proofs, separately authorized host activation and deployment must
prove the exact service/destination/source/profile/epoch and scoped credentials before any live
Start. M1's admitted read journey and #4749 pilot remain a separate predecessor. M2 then needs one
real authorized Issue delivery, independently read back, followed by actual owner trial and
accept/reject under FCA-09. Supervised operation and visible manual handoffs are allowed; neither
source publication nor a composed fixture qualifies the live journey. FCA-06/07 pickup still needs
the particular implemented seams they consume. Full #5399/M4 platform and second-consumer criteria
remain unchanged. This operation consumes no DDO bridge/reducer; selecting DDO later retains
#4169/#4170 and their effect owners rather than borrowing their authority here.

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
| `active` or `launch_unknown`; valid inquiry terminal response/readback | `terminal`; render the actual outcome and limitations | Exit-zero launcher response whose entire stdout is one JSON object with non-empty `inquiry_id`, `final_state`, `terminal_receipt_id`, `human_readable_report`, matched to the bound destination artifacts. Lost-response recovery uses FCP-04 authenticated exact destination readback; ambiguity preserves staging/lock until the source-owned recovery path resolves it. |
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

<!-- anchor: FCA-ID-SECOND -->
### FCA-ID-SECOND — bounded Bifrost documentation delivery target

This is the source contract for exactly one later documentation candidate in
`RasmusTho/bifrost`, the existing ADR-0050 constituent. #5586 implements bounded v2 repository
support through authenticated admission, the default two-root reader, protected executor,
operation/outbox receipts and native-task independent readback. v1 remains hub-only with unchanged
approval normalization and hashes. Repository support and FCA-07 fixtures do not prove a live Bifrost journey. The owner's preparation mandate names
this one separate consumer, but neither it nor installed deploy/rollback delegation grants
Issue-delivery effects. No live Issue, branch, host, approval or human trial is selected here.
FCA-09-BIFROST repository documentation readiness and guarded outcome support are implemented by
#5587. Managed UI/host activation, real consumer policy and credentials, a selected pilot and
explicit human trial/acceptance remain pending. Bifrost projections cannot borrow VM102 candidate
readiness; #5405 owns the separate consumed-seam conformance matrix and pilot-plan artifact.

The v2 approval's `target_policies` binds exactly the consumer and hub protected policy snapshots,
including blob/content identities, effect sets and credential ID/generation. The consumer snapshot
also binds finite, explicit Markdown paths under `docs/`, its verification profile and required checks. The frozen
context carries `delivery_sources`; approval, operation and effect receipts retain that same pair.
Publication and merge each carry `diff_sha256` over independently read complete base/head tree
changes, including old/new modes, blobs and every rename/copy path. The production reader requires
an explicitly installed `trusted_workflow_root`; consumer artifacts and ambient roots cannot
supply its workflow pin. The existing GitHub readback independently addresses the hub Issue and
Bifrost PR, requiring an explicit `Governing-Issue: rasmustho/agentic-pkm-mvp#N` link.
V2 target-authority and effect-readback evidence bind the addressed effect repository explicitly.
Merge independently reads current-head collaborator reviews. Closure accepts only the exact
operation-owned merged-base transition proven by its durable merge slot and fresh GitHub evidence;
optional admitted hub parent evidence additionally names that consumer PR in its typed target.

**Compatibility and identity.** Extend the existing operation as `fca-issue-delivery.v2`, retaining
`deliver_ready_issue` and the same service, adapter, protected executor and receipt/outbox owners.
The bounded v2 consumer is only `rasmustho/bifrost`; v1 remains only `rasmustho/agentic-pkm-mvp`.
Keep v1 hashes, stored approvals, keys and historical readback unchanged. Never upgrade a v1
approval, reinterpret its single source revision, or replay it as v2. Unsupported versions and a
third repository refuse, even if a credential or generic RepoRef exists for them. A new v2
operation requires its own exact preview and authenticated human Start.

The closed v2 manifest must retain all FCA-ID-01 bindings and distinguish these two sources:

| Binding | Exact authority and independent reread |
| --- | --- |
| Consumer | `repository`, `source.revision` and destination base identify Bifrost, an immutable 40-character commit and the approved protected base ref/SHA. Bind one context/plan, branch/worktree/run, permitted documentation paths and the consumer verification profile. Re-read Bifrost base/policy and destination Git identity independently. A tracking Issue does not supply the consumer Git identity. |
| Tracking Issue | Bind `issue.repository = rasmustho/agentic-pkm-mvp` separately from the consumer, plus exact Issue number/node/URL, body/AC hashes and parent evidence target or explicit `none`. ADR-0050 retains hub tracking until Bifrost has its own board; this bounded target preserves that rule, with no duplicate Bifrost Issue. Independently read the addressed hub Issue and bind its relationship to the Bifrost candidate. A future tracking migration needs a separately governed contract change, not runtime fallback. |
| Trusted workflow | Add explicit `workflow.repository = rasmustho/agentic-pkm-mvp` and `workflow.source_revision` as a separately pinned immutable commit. Its canonical artifact manifest/hash binds the CLI/launcher, executor, isolation adapter, owning skills/shared gates and verification machinery at that commit. Read these from the host's existing protected `trusted_workflow_root`, verifying its repository/commit and artifact bytes independently of Bifrost. Bind the pair into approval, effect requests, operation/readback receipts and their hashes; equal-looking revision strings do not collapse repository identities. |

The frozen plan must preserve both pins, use Bifrost's governed stack/policy for validation, and
never assume that Python/hub checks prove a Bifrost result. Workflow code is not copied into the
consumer to satisfy artifact validation. Neither source may default from CWD, model text, an
ambient checkout, credential scope or an unpinned `main`. The implementation must update both
`issue_delivery_operation.py::_default_live_binding_reader` and the protected executor's artifact
and request validation, including the host composition's explicit workflow-root binding; its
existing separate root is reuse, not evidence that the default reader already separates sources.

**Policy before pilot.** Use existing RepoRef routing and
`GitHubProtectedRepositoryAuthority.delivery_manifest` to read Bifrost's
`.builderops/delivery-manifest.json` from the protected target base. Bind its revision/hash,
repository, allowed documentation paths/effects, required checks/profile and exact credential
identifier/rotation generation. A separately governed preparation must install and review that
consumer policy before pilot approval; the pilot cannot add or broaden its own policy, grants,
workflow, credential mapping or acceptance profile. Preparation must preserve Bifrost's inherited
governance and ADR-0050's hub tracking. No policy is installed here.

For each effect, the protected executor resolves credentials only with its exact addressed
repository, protected manifest credential ID and rotation generation through the existing
`HostCredentialResolver`. Bifrost publication/merge and hub Issue claim/closure or explicitly bound
hub parent evidence require their own target-base policy and effect grants. Bind both policy
identities/hashes into the exact approval; missing, unavailable or inconsistent policy/credential/
profile refuses before the first effect. Neither Bifrost access nor the trusted workflow pin grants
hub writes, and hub tracking authority grants no Bifrost mutation. No ambient credential fallback,
generic cross-repository grant or third-repository effect is admitted.
The presented human approval credential must itself address both the consumer and tracking
repositories; a same-principal sibling credential cannot supply its missing repository scope.
Preview, Start and fresh execution enforce this binding; historical readback remains available
without projecting withdrawn or formerly over-scoped approval as current authority.

The protected executor must independently inspect the entire approved-base-to-candidate tree diff
before publication and again for the exact merge head, not just selected document blobs. Every
changed path must be explicitly allowed; inspect both sides of renames/copies and deletions, and
reject non-regular files, out-of-set paths, code, scripts, policy or governance-bootstrap changes.
Bind the base/head and complete diff to verification/readback; an omitted extra file or changed
base/head cannot pass by presenting a valid subset of documentation.

**Continuing gates and readback.** Revalidate both source identities/artifacts, the target-base
policies, tracking Issue binding, consumer verification requirements, grant/epoch/expiry and destination isolation at Start,
pre-entry claim and each later effect boundary. Either-source drift, base/policy drift or a foreign
claim withdraws further permission; obtain a new exact approval after reconciliation. Distinguish
the operation's own expected claim/content/head changes from authority drift. Preserve the original
approval and completed effects; never silently substitute the new workflow or rebase under it.
FCA-ID-02/03 retain their reservation, attempt, entry, stop and ambiguous-replay semantics: a lost
response or non-unique source lookup cannot justify another attempt, key or worker. Authorized
historical readback survives expiry/withdrawal and carries the original version and both pins;
it does not reopen execution. Delivery still needs independently observed Bifrost PR/head/checks,
review and merge, plus exact hub Issue closure and owner-doc evidence, not worker success text.

The only candidate admission added to the target is
[FCA-09-BIFROST](../builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md#fca-09-bifrost--non-image-documentation-candidate-target).
It proves availability of exact documentation for an owner trial, never native-app behavior,
Xcode readiness or a human outcome. Repository work and later activation are ordered in the
[implementation dependency graph](../plans/DEVUI_IMPLEMENTATION.md#dependency-graph).

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
