State: BMI-01 through BMI-05 are implemented; parent acceptance remains pending under #3288. The
durable Model Inquiry contract is provider-neutral and capability-resolved. The current operational
profile enables only the Codex subscription transport; future provider/model changes require
declared configuration plus an explicitly registered compatible transport. The
configured remote host owns its subscription session and host-specific launcher settings. Under
ADR-0064's 2026-07-30 owner-cost ruling, that subscription-backed session is the sanctioned
operational auth for host-local Builder model inquiry. The provider-free intent, declared
provider-API adapters, and high-reasoning policy remain versioned for any future metered path, but
their API-key identifiers are intentionally unprovisioned and currently fail closed as
`credential_unavailable`. The Model Inquiry subscription exception is never a CKM source or
fallback.
Doc role: Specification directory
Authority: Defines the BuilderOps pre-ticket model-inquiry capability and its task decomposition. BuilderOps Vault authority remains owned by ADR-0010.
Owner: BuilderOps governance
Temporal class: operational
Review cadence: event-driven
Source of truth: ADR-0010, BuilderOps Vault contracts, and this directory for task shape.

# BuilderOps Model Inquiry

BuilderOps Model Inquiry turns one development question into a bounded, pre-ticket collaboration
between two neutral review perspectives over one resolver-selected capability target. Current operational
configuration enables only Codex subscription transport; durable selection remains provider-neutral
and configuration-resolved. It stores the question, context packets, model turns, synthesis,
readiness outcome, and promotion evidence in the BuilderOps plane. It does not make a GitHub Issue
until the result is executable work.

The shared artifact vault is configured per machine through `BUILDEROPS_VAULT_ROOT`. The current
deployment uses a dedicated iCloud Obsidian vault owned by Yggdrasil, separate from all human
knowledge vaults. It holds Markdown artifacts, queue files, receipts, transient worker state, and
TTL-based advisory claim signals. SQLite state, authoritative dispatcher leases, and temporary
provider credentials stay local to the machine that runs the worker. iCloud is not a lock service;
its advisory claim files never guarantee exclusive ownership.

## Scope

The inquiry intent and workflow roles stay provider-neutral. The declared capability boundary
resolves the current Codex-only profile; a future provider/model is not executable until a compatible
transport is explicitly registered and selected through declared configuration. Fable/GPT references
remain compatibility/provenance only and cannot reactivate a provider, transport, or acceptance target.

- one command/API request creates an `inquiry_id` before any ticket or Issue exists;
- the neutral `synthesis` and `verification` perspectives receive structured context packets over
  the same resolver-selected target; this is explicit single-target acceptance, not independent
  consensus and not a fallback claim;
- every model turn is traceable to its input artifacts, model identity, run, and content hash;
- a deterministic readiness gate decides `issue_ready`, `needs_input`, or `not_ready`;
- only an accepted promotion path may create a GitHub Issue through REST;
- desktop skills transfer one question to the configured remote-host launcher, which owns the same
  BuilderOps command and state while using the sanctioned host-local subscription-backed session.
  The separate declared provider-API mechanism remains fail-closed while its metered credentials are
  intentionally unprovisioned.

## Implementation Tasks

| Task | ID | Deliverable |
| --- | --- | --- |
| [External BuilderOps Vault Configuration](EXTERNAL_BUILDEROPS_VAULT_CONFIGURATION.md) | BMI-01 | Explicit shared artifact-root configuration with local SQLite and shared advisory claims. |
| [Pre-Ticket Inquiry Records](PRE_TICKET_INQUIRY_RECORDS.md) | BMI-02 | Durable inquiry/run/turn records, CLI/API entrypoint, and trace query. |
| [Model Turn Adapters](MODEL_TURN_ADAPTERS.md) | BMI-03 | Structured command/API adapter contract, retries, and bounded adversarial loop. |
| [Desktop Skill Launchers](DESKTOP_SKILL_LAUNCHERS.md) | BMI-04 | Codex and Claude Desktop skill packages that delegate to the configured remote-host inquiry launcher. |
| [Promotion And Traceability](PROMOTION_AND_TRACEABILITY.md) | BMI-05 | Readiness gate, PromotionIntent, Issue creation, and delivery lineage. |

BMI-02 stores its durable record graph under
`$BUILDEROPS_VAULT_ROOT/model-inquiries/<inquiry_id>/`. The CLI and HTTP routes share one service;
`resume` only returns a restart plan until BMI-03 supplies bounded provider execution.

BMI-03 adds `builderops inquiry run`. Its `--dry-run` mode is deterministic and read-only;
provider-enabled mode uses explicit neutral perspective adapters, strict response validation,
durable terminal receipts, and one target resolved from the configured Model Inquiry capability. The
subscription path may retry an eligible failed command for that same resolved target, but it never
selects a second provider/model or claims independent consensus.

BMI-04 adds Codex and portable Claude bridge skills that transfer the question to a configured
remote-host launcher. The configured remote host owns the BuilderOps command, configured neutral
perspective adapters, subscription session, and durable artifacts; its authentication and launcher-path settings
remain outside Git. The current host-local operational path uses the sanctioned subscription-backed
session through `yggdrasil-model-inquiry` under the owner-cost ruling. The versioned provider-API
path remains a separate dormant mechanism under `yggdrasil-model-inquiry-provider-api`:
it submits provider-free intent, resolves the configured Model Inquiry capability through the Builder census, and requires
explicit `xhigh` reasoning, but intentionally absent metered credentials produce a durable typed
`credential_unavailable` receipt before any adapter call. That failure does not select a subscription
or cross-provider fallback. The explicit Model Inquiry subscription exception is confined to this
host-local capability and cannot execute CKM semantic association.
BMI-05 adds the structured Issue proposal, readiness receipt, file-first
PromotionIntent, REST-only Issue crossing, crash reconciliation marker, and append-only delivery
references.

## Execution Order

`BMI-01 -> BMI-02 -> BMI-03 -> BMI-04 -> BMI-05`

BMI-04 may be prepared after BMI-02, but cannot claim autonomous model collaboration until BMI-03
is delivered. No task is ready to make a Product/Runtime write.

## Approved inquiry operation interface

FCP-04/#4697 delivers this bounded repository implementation; live host activation and parent
acceptance remain separate verification gates. It preserves the eight Start/Hold outcomes and extends the
previous question-file-only skill mechanics explicitly. The [FCA-08 manifest](../BUILDER_FACTORY_ACCEPTANCE/README.md#immutable-approval-manifest-and-operation-permissions)
remains the approval-field authority. This section owns the finite executable interface; it grants
no new provider, credential, delivery, Product, or stop authority.

### One skill-owned facade

`app/builderops/model_inquiry_workflow.py::SanctionedModelInquiryWorkflow` is the single executable
implementation of `.codex/skills/start-model-inquiry/SKILL.md`. The existing authenticated service's
`production_app` constructs it. Manual skill use delegates through
`scripts/start_model_inquiry_workflow.py --question-file <exact-file>` to the same implementation.
Neither production entrypoint may require a test-only injected callback, a generic agent executor,
or a second copy of the host/lock/staging/cleanup recipe.

The service exposes `POST /v1/inquiries/command/preview`,
`POST /v1/inquiries/command/start` with exact `start` or `hold`,
`POST /v1/inquiries/command/authority` for the four fixed destination control purposes, and
`GET /v1/inquiries/command/{approval_id}` for authenticated readback. The existing record owner
persists `ModelInquiryApproval` at `inquiry-approval:<approval_id>`; generic record writes cannot
create or overwrite that reserved admission surface. Its permission version hashes the current
credential registration, scope/repository grants, principal, rotation and verifier identity;
raw bearer material is never part of the proposal or operation envelope.

The facade preserves the fixed `Tailscale_macmini` alias, verified local/remote route, exclusive
`/tmp/yggdrasil-model-inquiry.lock`, exact `/tmp/model-inquiry-question.md` staging and host-owned
`$HOME/.local/bin/yggdrasil-model-inquiry` launcher. Local route proof still requires effective
SSH alias expansion, exact principal/home binding and a matching pinned public host key before any
connection or lock action. Missing proof selects the fixed remote route; connection failure never
permits a local fallback. Caller text cannot select an executable, host, path, environment mapping,
provider, or capability substitute. Question UTF-8 bytes are preserved, including trailing newlines.

The operational wrapper and subscription session stay host-owned and outside Git. The repository
provides the complete operation protocol in `app/builderops/model_inquiry_operation.py`, backed by
`ModelInquiryService` and the existing configured runner. An operator must separately install or
confirm the wrapper's delegation to that protocol. This task neither inspects nor modifies the
live wrapper, subscription bridge, provider adapters, credentials, or host configuration.

### Fixed operation verbs and authentication

All operation envelopes are canonical UTF-8 JSON on stdin. Never interpolate their fields or the
question into a command. No additional fixed staging file is introduced. Only these new verbs of
the existing operational launcher are admitted:

| Verb | Bounded result and effect |
| --- | --- |
| `--operation-capabilities` | Read-only protocol version, supported verb set and workflow/destination revision. No secret/profile values, inquiry access, reservation or model call. Unsupported/malformed version or incomplete support withdraws Start before reservation. |
| `--operation-reserve-stdin` | Authenticate the exact service-owned approval and durably reserve one operation/key/manifest to one inquiry identity in the existing destination artifacts; no launch, staging or lock cleanup. |
| `--operation-attempt-stdin` | Authenticate that approval again, compare the exact reservation, and atomically record the one attempt before crossing the launch boundary; no model call. |
| `--question-file /tmp/model-inquiry-question.md --approved-operation-stdin` | The only operation launch verb. Authenticate and bind the reservation and attempt, atomically consume the attempt once before any runner effect, re-read final current authority, compare exact staged bytes, and pass the reserved `inquiry_id` to `ModelInquiryService.start(inquiry_id=...)` and the existing runner. |
| `--operation-readback-stdin` | Authenticate read access through the same service and compare the full stored approval/binding before reading that destination's operation artifacts. No launch, lock/staging change, cleanup or retry. |

The updated single-flight rule permits control verbs that never call a model and exactly one
invocation of the launch verb. A transport retry cannot turn a control verb into launch. Reserve,
attempt and readback must authenticate their exact approval with the existing control-plane client;
SSH transport, manifest text and self-computed hashes alone are not admission evidence. Readback
may inspect an expired approval with current authorized read permission; expiry never authorizes
another launch. A capabilities response is compatibility evidence only, never owner approval.

The operation envelope carries the full immutable manifest and hash, exact admission receipt,
canonical repository/subject, operation type/key, reserved inquiry ID and the reservation/attempt
hashes required by its verb. It carries no bearer token or credential material. Derive the operation
key from the stable approval identity, repository, operation type and fixed destination/workflow
identity, and derive `inquiry_id` as `inq_operation_<operation_key>`. Bind both into the immutable
approval. Same-key changed content and same-approval changed-key attempts refuse.

### Current authority and finite source scope

The existing service uses `CredentialRegistry`, repository guards, the store authority epoch and
`store.commit_record`/receipt primitives. Persist a `ModelInquiryApproval` payload in that existing
record authority with immutable first-write content and idempotency conflict checks; add no service,
task store, queue or approval ledger. Owner confirmation requires explicit repository-scoped
`inquiries:approve`; existing `inquiries:write`, a record commit, model-supplied identity and the
local loopback/Host read route are insufficient. Readback requires `inquiries:read`. A destination
caller with `inquiries:execute` may query the exact prelaunch authority but cannot approve it.
These scopes do not provision or broaden any credential.

After authenticating the caller, the service persists only the approving principal's identity,
credential reference, permission/rotation version and epoch metadata. Before every authority-bearing
control verb, and again at the destination immediately before a runner effect, it re-reads the
approving credential's current registration and permission, exact sources, expiry and epoch.
The destination uses `BuilderOpsControlPlaneClient` and existing host-owned client configuration
for this check; the owner's bearer token is never forwarded. Deletion/revocation, changed identity,
permission, source, workflow, policy/configuration/resolved target or epoch, and unavailable or
contradictory authority all refuse launch. Destination policy/profile checks use the declared
resolver and current local workflow version, not client-provided executable choices or cached proof.

Initial addressed subjects are an exact configured GitHub Issue or an explicit-null pre-ticket
question. Reuse the existing admitted bounded GitHub REST reader and exact question/context/source
material. Pre-ticket Issue number/body/AC fields are explicitly null. Restrict source kinds to the
already-admitted `github_issue` and bounded repo-owned `owner_document` references; unsupported
source kinds and unconfigured roots withdraw Start. Do not add a capability-subject reader, general
URL fetcher, session discovery, inferred Issue/correlation or broad repository-history collector.
The delivered Conversation Port composer remains the canonical pack/hash/freshness owner.

### Durability, recovery and cleanup

Reserve before invocation and record the attempt before the facade crosses the launch boundary.
Only a newly created reservation may enter that route; duplicate submit, refresh, restart or
unknown outcome first reads the same binding. A separate immutable invocation-entry artifact
consumes the exact attempt atomically inside the destination before the first runner effect, so a
second process cannot execute that attempt even if a caller violates the no-retry rule. Reservation
and attempt receipts never establish a running process. All artifacts remain under the existing
Model Inquiry destination; shared-vault sync is not a distributed lock service.

A reservation interrupted before its attempt remains reconciliation-needed. Any loss after attempt
recording or invocation entry is indeterminate until the destination proves the exact outcome;
absence, time elapsed or an empty result cannot permit a second launch or new key. Authenticated
readback names the approval/manifest/subject/key/workflow/destination, admission and destination
receipts/hashes, known inquiry ID, observation time/source epoch, truthful state and uncertainty.
Valid terminal output preserves the four existing launcher fields and exact inquiry identity.
`stop_support` and `stop_status` remain `unsupported`; Hold invokes nothing.

The facade owns one exact-path runtime cleanup helper. This explicitly replaces the former
assistant-tool-specific `apply_patch` requirement for this skill's temporary-file mechanics; it is
not a general deletion helper or an expansion of cleanup authority. It records and validates the
caller temporary path, rejects symlinks/unowned paths and globs, and deletes only that caller temp
unconditionally. Stage and lock release use the selected route only after a failure before the
attempt boundary or a valid terminal response. Ambiguous attempt/launcher output preserves both.
Delete the exact staging path before releasing the empty fixed lock. Cleanup failures are reported
separately and cannot replace the captured launcher exit status or response. Never delete inquiry
artifacts, inspect the vault to infer a substitute response, or clean another invocation's files.

Manual skill invocations without an operation manifest use the same facade and retain the current
fixed `--question-file` host launch, one invocation and cleanup/ambiguity matrix. They gain no DevUI
approval or access to an operation reservation; their host launcher may choose its own inquiry ID.

### Verification and activation boundary

Pre-merge proof exercises the real production service constructor/handlers, concrete facade,
operation protocol and destination artifact methods with a fake at the host-process/provider seam.
It must demonstrate success and refusal, exact reserved-ID propagation, per-verb authentication,
final revocation/expiry after queued work, concurrent/restart/partial-write behavior and manual
cleanup/route compatibility. A permanently unwired production port cannot satisfy FCP-04.
A complete production implementation must instead report an unsupported live destination honestly.

Focused proof is executable at the Issue's 15 `Verify:` targets, including the actual
`production_app` constructor, facade/process boundary, destination protocol CLI, existing runner
and artifact readback. The BuilderOps image packages OpenSSH client tools and the exact skill
contract used for its workflow hash. Its documented Uvicorn factory boot remains independent of
Product Runtime. Existing managed source configuration and operator-owned SSH alias/key/credential
configuration must be present; absence withdraws Start without provisioning them.

Live operation separately requires an operator-confirmed conforming wrapper and deliberate scoped
credential/service deployment. Repo implementation tests do not install that wrapper, change
credentials, restart services, run an inquiry, or establish parent capability/owner acceptance.

## Cross-Task Invariants / Interaction Safety

1. **Vault separation.** Shared iCloud files are Builder System artifacts, never a Mimer human vault
   or Product/Runtime source of truth. SQLite, provider credentials, and authoritative dispatcher
   leases are local-only; vault claim files are shared TTL advisory signals only.
2. **Artifact-first turns.** A model receives immutable input artifact IDs and content hashes; it
   never relies on a chat transcript as sole state.
3. **No silent promotion.** An inquiry may produce a synthesis but cannot create an Issue, PR, or
   owner-doc change without a recorded PromotionIntent and receipt.
4. **Bounded autonomy.** Provider refusal, exhausted candidates, exhausted rounds, or unresolved
   blocking questions terminally record `needs_input` or `not_ready`; no model invents missing
   requirements to reach Issue-ready. An eligible unavailable, timed-out, empty, or malformed
   subscription turn may try the one alternate configured adapter only on legacy/compatibility
   paths with distinct effective targets. Active v2 single-target execution has no alternate;
   adapter or command failure is terminal `provider_error`, never `degraded_consensus`, and cannot
   become ready or promotable. Explicit refusal, unsafe output, credential or session failure, and
   persistence failure never fall back. The owner-controlled
   host launcher selects this fixed bridge only with
   `BUILDEROPS_MODEL_INQUIRY_OPERATIONAL_SUBSCRIPTION=1`; that boolean cannot name targets or
   secrets, and the provider-API launcher refuses to start if it is present or inherited.
5. **Traceability survives partial failure.** Each completed turn is persisted before a successor
   call. A worker restart can resume from the latest committed turn without replaying an accepted
   provider call. Duplicate command retries use idempotency keys. Legacy v1 records remain readable;
   only the v2 current configured path is executable after the migration boundary.

Partial failure examples:

- If iCloud is unavailable, new artifact writes fail closed; the local worker must not continue with
  an untraceable run.
- If a provider call succeeds but receipt persistence fails, the run remains incomplete and the
  provider output is not treated as an accepted turn.
- If the configured target is unavailable, the run ends with a typed provider failure and cannot
  be promoted. A successful run ends `single_target_acceptance` with `independence: false`; it never
  becomes `consensus` merely because both neutral perspectives agree.
- If the models reach their round limit without a common accepted artifact hash, the inquiry ends
  `not_ready` and produces no Issue.

## Capability Acceptance Criteria

- [x] An operator can start and resume a pre-ticket inquiry from a BuilderOps command without
  copying model output between tools. Verify: `tests/builderops/test_model_inquiry_cli.py::test_start_and_resume_inquiry`.
- [x] Each turn, synthesis, and readiness result can be traced to the source question and its input
  artifacts. Verify: `tests/builderops/test_model_inquiry_trace.py::test_trace_links_question_turns_and_synthesis`.
- [x] Shared iCloud artifacts never place SQLite databases or provider credentials in the
  synchronized vault, and claim files remain explicitly advisory. Verify:
  `tests/builderops/test_builderops_paths.py::test_shared_vault_bootstrap_creates_advisory_claims_but_never_sqlite`.
- [x] A GitHub Issue is created only after readiness and promotion evidence are recorded. Verify:
  `tests/builderops/test_model_inquiry_promotion.py::test_issue_promotion_requires_ready_receipt`.
- [x] Desktop launcher instructions transfer the question to the configured remote-host launcher rather
  than starting local BuilderOps or automating a desktop app. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] The dormant provider-API mechanism produces a secret-safe diagnostic receipt and one
  desktop-launch JSON result without fallback or retry; operational desktop skills never invoke
  that mechanism. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_local_launcher_emits_terminal_provider_error_json`.
- [x] The operational subscription runner uses one resolved target for both neutral perspectives and
  records truthful single-target acceptance. Verify:
  `tests/builderops/test_model_inquiry_runner.py::test_single_target_acceptance_is_truthful_and_receipted`.
- [x] The configured Model Inquiry profile binds the Model Inquiry capability without provider/model selection
  in the inquiry intent, and API/subscription adapters consume the same resolved target. Verify:
  `tests/settings/test_provider_census.py::test_model_inquiry_profiles_bind_configured_capability`
  and `tests/builderops/test_model_inquiry_adapters.py::test_subscription_adapter_uses_resolved_target_profile`.

## Relationship To GitHub Issues

Parent feature Issue: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288). It is the
validation hub for this capability. Child issues are #3289 (BMI-01), #3290 (BMI-02), #3291
(BMI-03), #3292 (BMI-04), and #3293 (BMI-05). All five child issues are delivered and closed; the
parent remains open for the end-to-end validation described below.

## Validation / Acceptance Path

After BMI-05, run the deterministic dry-run and the repo-verifiable contract checks. Under the
ADR-0064 owner-cost ruling, parent acceptance does not request a metered provider-API inquiry,
provision API keys, or retire the sanctioned subscription bridge. Ordinary host-local inquiries
continue through the sanctioned subscription-backed session; that operational path is Model
Inquiry-only and never a CKM credential source or fallback. Promote BuilderOps owner-doc claims only
after the remaining parent validation is satisfied.
