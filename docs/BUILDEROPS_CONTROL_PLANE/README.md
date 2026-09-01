State: Accepted target-state specification. #5056 amends the BuilderOps VM deployment posture: BuilderOps is rebuildable operational state, while backup/restore is deferred and non-gating. Parent validation hub #3788 remains `agent:blocked` while child slices are outstanding. BCP-01 is implemented in the development baseline by #3792/PR #3852; the repo/deployment contract for BCP-02 is implemented by #3790 and #5056; BCP-03 is implemented in the development baseline by #3789/PR #3929 (mechanism only, no cutover); BCP-04 is implemented in the development baseline by #3791 (client transport and gates only, non-authoritative); live authority activation remains forbidden until BCP-03 through BCP-06 complete.
Doc role: Specification directory
Authority: Owns the bounded task decomposition and cross-task invariants after merge. ADR-0062 owns the architectural decision; ADR-0010 owns the repo/BuilderOps authority seam; shipped owner docs win for current behavior.
Owner: BuilderOps governance / Architecture spine
Temporal class: Target-state implementation contract
Source of truth: ADR-0062 plus this directory for task shape and dependency order.

# BuilderOps independent control plane

Build a permanent API-first BuilderOps control plane as part of the cohesive Dev System runtime
home on TARS VM 102 (`builder-system`), with one PostgreSQL operational authority, independent
deployment/trust lifecycle, API-only clients, durable outbox-based external effects, and scoped
review/merge execution. Then migrate every SQLite/file authority and remove BuilderOps ownership
from Product Runtime. The former Demerzel-only placement is superseded by this VM-102 target; the
BCP task names and historical file paths remain for traceability.

This specification does not transfer product or delivery authority. GitHub Issues, PR head SHA,
required CI, review gates, repository protection, and GitHub merge results remain authoritative.

The BuilderOps specification follows the [RSC-01 continuity classification](../REBUILDABLE_SYSTEM_CONTINUITY/README.md#rsc-01-continuity-classification): retained human artifacts and document-backed governance receipts remain authority, BuilderOps machine state is rebuildable operational state, and its journals/leases/fences protect effects rather than human meaning. Missing lineage uses an inactive new fenced bootstrap and GitHub readback. Diagnostic dumps and optional backups are evidence/ergonomics only, never semantic authority or a mandatory restore proof. The historical restore-first/WAL proposal is superseded and not an active capability; deployment and total-loss recovery remain target-state unless their own receipts exist.

## Delivery status

BCP-01 is implemented in the development baseline by #3792/PR #3852 with the independent
PostgreSQL migration lineage, domain-neutral store port, atomic local task/transition/receipt/
idempotency/outbox transaction, fenced leases, crash-safe reconciliation, and explicit SQLite
migration/test adapter. BCP-02 (#3790) adds the independent scoped-auth service, migration-gated
BuilderOps Compose project, separate-engine preflight, immutable pins, authenticated probes,
secret-safe status/metrics, deploy/rollback receipts, and rebuildable local durability. Candidate
images and readiness deliberately have no WAL-G, backup service, recovery target, or restore gate.
This is still not a production cutover: the checked-in zero pins are non-runnable placeholders, no
live authority was activated, and client migration, legacy import, privileged execution, and Product
Runtime route removal remain owned by BCP-03 through BCP-06.

## Builder-system rebuildable deployment posture

BuilderOps is rebuilt from the repository, attested immutable control-plane and PostgreSQL images,
pinned configuration, and VM-local secret references. Backup and restore are deferred capabilities,
not candidate, migration, readiness, rollout, or closure gates. Rebuild preserves schema/migration,
authority epoch/fencing, no dual writer, loopback API, private authenticated ingress, health/readiness,
disk/WAL guardrails, and truthful receipts. Rollback selects code/config/image only and never rewinds
surviving database state. Manual `pg_wal` deletion, `pg_resetwal`, and reset/cleanup tools remain
prohibited.

## Complete Dev System VM-102 topology contract

BuilderOps, BuilderOps-owned providers, and Dev UI are one Builder System / Dev System for
placement purposes. VM 102 is the intended cohesive runtime home for the complete system, not a
Dev UI-only deployment. This is a target placement contract: this document does not claim that VM
102 is qualified, that any service is resident, or that a deployment occurred. A guest readback,
screen observation, or running default-engine container is not a deployment or qualification
receipt.

The inventory below is complete for the components currently named by the governing Issue. Each
row must be retained in `devsystem_vm102_component_inventory.v1`, including rows whose status is
`gap` or `unknown`; a missing row is not an acceptable omission.

| Component ID | Placement class | Owner / service or project | Identity, ingress, health, and lifecycle contract | Migration / rollback boundary | Current reconciliation state |
| --- | --- | --- | --- | --- | --- |
| `devui_projection` | VM-102 resident (target) | Dev UI owner; read-only projection component | Exact source SHA and image digest; internal authenticated GET-only path; `devsystem_vm102_health.v1` plus #4748 browser evidence; GitHub/BuilderOps remain authority | No local workflow state; no migration; restore previous image/config only | `gap`: no VM-102 Dev UI deployment receipt or candidate identity is proven |
| `builderops_control_plane` | VM-102 resident (target) | BuilderOps; PostgreSQL, migrations, API, worker, internal network, dedicated engine/context, service manager, epoch fencing, journal/outbox, health receipts; `builderops-control-plane` | Repository SHA and attested image digests; loopback API with private authenticated ingress and no Funnel; schema/epoch/fencing and BuilderOps receipts | Migration-gated; classify forward-only versus reversible; rollback pins compatible code/config/image and never rewinds authority data | `gap`: no bound receipt proves the complete engine/project/service identity and runtime state |
| `builderops_cockpit` | VM-102 resident (target) | BuilderOps Cockpit read-time join | Source-owned BuilderOps read path; authenticated internal access; health/version and freshness in component inventory; BuilderOps receipt lineage | Read-only projection; no independent state migration; rebuild from source and prior compatible image | `gap`: service/project and runtime identity not evidenced |
| `dispatcher_signboard` | VM-102 resident (target) | Dispatcher queue/claim/lease/activity providers and Signboard diagnostic projection | BuilderOps-owned API/read path, fenced lease evidence, exact source/image identity, health/readiness receipt; no local lifecycle authority | Lease/state migration only through BuilderOps contract; rollback preserves GitHub and BuilderOps authority | `gap`: complete VM-102 service and project inventory not evidenced |
| `ddo` | VM-102 resident (target) | Deterministic Delivery Orchestration plans, reducer, worker/effect boundaries, reconciliation, receipts | Source/image identity and authenticated internal boundary; reducer and receipt health evidence; BuilderOps journal/outbox lifecycle | Apply only governed, classified migrations; rollback compatible executor/config without replaying or rewinding effects | `gap`: runtime residency and version evidence not proven |
| `ckm_kvasir` | VM-102 resident (target) | CKM/Kvasir capability and evidence projections | Read-only source-owned projections with freshness/refusal semantics; exact candidate identity and health/version evidence | Rebuildable derived state; no authority migration; rollback to compatible image/config | `gap`: provider topology and identity not evidenced |
| `focus_conversation_port` | VM-102 resident (target) | Focus / Conversation Port read surfaces | Authenticated internal read boundary, source-owned references, exact image/source identity, health and browser/read proof where applicable | No local workflow authority; rebuild projection; rollback preserves external source authority | `gap`: runtime residency and version evidence not proven |
| `soi_evidence` | explicit external dependency | Product/Runtime-owned SoI Evidence provider consumed read-only by Dev UI | External source identity, freshness, refusal, and auth posture must be named; Dev UI cannot copy or upgrade its authority | Product/Runtime owns its migrations and rollback; Dev System only withdraws unavailable claims | `gap`: no fresh provider/residency evidence on VM 102 |
| `github_git_ci_delivery` | explicit external dependency | GitHub, Git, review, CI, merge, closure, and promotion/verification adapters | GitHub/repository/CI exact refs and head SHAs are lifecycle authority; any VM adapter is subordinate and credential-free in receipts | External systems own migration/rollback; deployment cannot replace or rewind their authority | `external`: never replaced by VM-local state; adapter placement remains an explicit gap |
| `model_service` | explicit external dependency | Model Access Substrate / model-service dependency | Provider identity, endpoint class, auth reference (never secret), health/version and degradation evidence | Provider-specific; no model data or credential migration in this contract; deployment withdraws unavailable capability | `gap`: no fresh evidence proves model service residency or reachability from VM 102 |
| `tars_proxmox_control` | explicit external dependency | TARS/Proxmox host qualification, deploy, health, and rollback control | Host/VM identity, ownership, private ingress, qualification receipt, and operator boundary; host key verification must remain strict | Host/VM operations stay with #5052/#5056 and operator controls; no guest contract authorizes host mutation | `gap`: no current qualification receipt binds host ownership and inventory evidence |
| `product_runtime` | intentionally non-runtime | Product Runtime and its data, credentials, routes, and lifecycle | No `pkm-*` project, Product credential, vault, or network identity on the BuilderOps engine/VM; separation must be evidenced | Product migrations and rollback remain Product-owned; never run them from this contract | `excluded`: separate authority class by design |

For every `VM-102 resident (target)` row, a future qualification receipt must bind the actual
service/project, engine, source/image identity, ingress/auth posture, health/version, deployment
owner, lifecycle evidence, migration boundary, and rollback identity. `gap` is a required state,
not permission to deploy or to infer residency. Runtime evidence remains an explicit `gap` until a
bound receipt proves it; transient screen, guest, or default-engine observations are not frozen as
contract truth.

## VM-102 evidence and receipt contract

The following receipt names are contract identifiers, not evidence that a receipt exists. Each
receipt is redaction-safe and binds its observations to the target VM identity and a timestamp;
deployment and health receipts additionally bind the exact candidate SHA, image digests, and
configuration fingerprint. `tars_host_qualification.v1` is only the repository-side candidate
policy receipt and cannot substitute for live qualification.

### Normative receipt dependency order

The required successful-deployment path is ordered by evidence dependency, not merely by receipt
appearance:

1. `devsystem_vm102_component_inventory.v1` records the complete topology and every unresolved gap.
2. `builderops_vm_rebuild_activation.v1` and `devui_vm102_runtime_qualification.v1` each depend on
   that inventory. They may run in parallel, but both must pass before deployment.
3. `devsystem_vm102_deploy.v1` depends on both qualification receipts and binds the exact candidate,
   migration result, configuration, inventory digest, and rollback-baseline state.
4. `devsystem_vm102_health.v1` depends on the completed deployment and binds post-deploy identity,
   readiness, ingress/auth, topology, and read-only smoke to that deployed candidate.
5. `devui-stage-a-read-only-owner-pilot.v1` depends on the health receipt plus #4748 exact-SHA
   browser evidence; it is not deployment or health proof.

`devsystem_vm102_rollback.v1` is a conditional side path after a deployment attempt, not a required
step in the successful-deployment path. It is admitted only when
`rollback_baseline_state: available` names a complete compatible identity and restored health/smoke
passes. `rollback_baseline_state: no_baseline` refuses rollback until a later successful deployment
establishes that runnable baseline.

| Receipt | Required proof | Does not prove by itself |
| --- | --- | --- |
| `devsystem_vm102_component_inventory.v1` | All inventory rows, placement class, owner, service/project, source/image, ingress/auth, health/version, deployment/lifecycle, migration/rollback fields, observed-at, and inventory digest; gaps are explicit | Residency or deployment |
| `builderops_vm_rebuild_activation.v1` | Fresh VM identity/ownership, rebuild activation, dedicated engine/project, migration/readiness, fencing, no dual writer, and redacted operator evidence | Complete Dev System topology or Dev UI deployment |
| `devui_vm102_runtime_qualification.v1` | Complete resident-component topology, exact engine/project/service identities, source/image identities, internal ingress/auth, health/version, no dual writer, and deployment/rollback ownership | Candidate-policy pass or a successful deployment |
| `devsystem_vm102_deploy.v1` | Component-inventory digest, VM identity, exact candidate SHA, all image digests, pinned config fingerprint, owner, timestamp, migration classification/completion, and typed rollback-baseline state with a previous identity only when available | Post-deploy health, a runnable rollback target, or owner acceptance |
| `devsystem_vm102_health.v1` | Exact deployed identities, complete topology, health/version/readiness, internal ingress/auth, no-dual-writer proof, and read-only smoke results | Deployment authorization, promotion, or owner acceptance |
| `devui-stage-a-read-only-owner-pilot.v1` | Receipt-sourced URL/SHA, #4748 exact-SHA browser evidence, source-backed normal/review/blocked/completed projections, zero-effect journey, and owner acknowledgement | Any claim about components not covered by the pilot |
| `devsystem_vm102_rollback.v1` | An available previous known-good source/image/config identity, selected rollback identity, migration classification, restored health/version/read-only smoke, and preserved GitHub/BuilderOps authority | Reversal of a forward-only migration, authority data rewind, or rollback when no compatible baseline exists |

Required common fields are `receipt_type`, `receipt_version`, `target_vm` (`vmid: 102`,
`name: builder-system`), `observed_at`, `source_refs`, `candidate_identity` when applicable,
`component_inventory_digest` when applicable, `evidence_fingerprint`, `secret_material: absent`,
and an explicit `gaps`/`refusals` list. A receipt without the required evidence or with secret
material is invalid. A live guest check without the named receipt remains only an observation.

The inventory-only boundary is executable through the
[`devsystem_vm102_component_inventory.v1` schema](../../config/platform/devsystem_vm102_component_inventory.v1.schema.json)
and its [pure producer/validator](../../app/ops/devsystem_vm102_component_inventory.py). The
`python -m app.ops.devsystem_vm102_component_inventory --evidence <operator-supplied.json>` entrypoint
uses caller-supplied JSON only; it performs no host inspection and cannot emit residency,
qualification, activation, deployment, health, or rollback proof.
Its component evidence, owner, gap, refusal, and clear-text source-reference fields use
schema-closed non-claim values rather than free-form prose; additional operator or receipt evidence
is digest-referenced, so a gap cannot carry a credential or contradict the required refusals.

`devsystem_vm102_deploy.v1` has an explicit rollback-baseline state:

- `rollback_baseline_state: available` requires a complete, compatible, runnable previous
  source/image/configuration identity.
- `rollback_baseline_state: no_baseline` is the only valid first-deployment state. Previous identity
  fields are absent or null, `refusals` includes `no_compatible_baseline`, and rollback is refused.

Committed all-zero source, image, or configuration placeholders are invalid rollback identities;
they are bootstrap sentinels, not releases. Rollback remains refused until a later successful
deployment establishes a runnable baseline. The existing lower-level deploy-script receipt is
implementation evidence only and is not `devsystem_vm102_deploy.v1` until a separate code/test slice
implements and verifies this typed schema.

BCP-03 is implemented in the development baseline by #3789/PR #3929
(`app/builderops/control_plane/legacy_migration.py`): producer-derived expected-source
inventory across enumerated hosts/worktrees/mounts/automation/vault roots with real
resolver semantics and env-override consultation, host/user/freshness/manifest-hash-bound
acknowledgement, read-only hash-verified (pre- and post-read) adapters for the BuilderOps
SQLite store (including co-resident CKM/CEG tables), dispatcher SQLite/JSONL, epic-run
JSON, and file-first model inquiries, deterministic restart-safe import into a
domain-neutral authority sink under a new epoch with evidence quarantine,
duplicate-preventing tombstones, and expired-lease evidence, plus the
preflight/dry-run/import/reconciliation receipts BCP-06 consumes. This is the migration
mechanism only: no production cutover, writer disablement, or PostgreSQL adapter wiring
(BCP-06 owns the freeze window and the sink adapter), and remote-host env snapshots are a
recorded preflight limitation.

BCP-04 (#3791) adds the versioned authenticated control-plane client
(`app/builderops/control_plane/client.py`), its API-only CLI
(`python -m app.builderops.control_plane`) and `scripts/builderops_api_client.sh`
wrapper, delivery-manifest `(RepoRef, stack, task-class)` routing, the
client-facing service routes (records, inquiries, tasks claim/heartbeat/complete,
attempts, promotions, receipts, status, and the executor outbox claim), repo and
executor scope enforcement, typed fail-closed transport/auth/scope/conflict/
stale-lease errors with idempotent retry, and the control-plane store-boundary
and governance gates. This is not a production cutover either: the client targets
whatever service/store backend is configured and ships non-authoritative; the
legacy direct-SQLite `app.dispatcher`/`app.builderops` CLIs remain in place, and
BCP-06 owns activating production authority and freezing those legacy writers.
Issue #3968 closes the BCP-04 review residuals: all mutation paths now require
delivery-manifest routing before dispatch, reject stale cached/prior-route
reuse by reloading the addressed manifest per invocation, and promotion updates
can carry the store-required fenced lease through the client CLI. This remains
client-side request formation only; temporal protected-base manifest freshness
stays with BCP-05, and BCP-06 cutover authority is unchanged.

Issue #4898 adds the nullable, dormant row-derived post-effect recovery substrate. Its post-effect
claim and LSN identity are derived only from the locked outbox row; the API accepts only a row
locator, minimum fence, and closed readback outcome. This is mechanism support only: consumers,
production authority activation, and legacy `finish_effect`/self-closure behavior remain unchanged
and are not claimed as delivered here.

## TARS qualification contract

The repository-side candidate evaluator is `tars_host_qualification.v1`, with policy version
`tars-builder-system-baseline.v1`. This is the canonical BuilderOps owner contract for that evaluator;
the Platform and Operations specification remains the separate owner of host/platform boundaries.
It does not qualify a live host, authorize host or Proxmox mutation, or change Product/Runtime,
deployment, credential, network, or firewall authority.

The fixed VM 102 BuilderOps isolation baseline is: VM ID `102`, name `builder-system`, two cores,
4096 MiB memory, 60 GiB disk, `vmbr0`, VLAN tag `42`, and network scope `guest-vlan-42`. The
candidate evaluator requires a non-empty BuilderOps engine identifier that does not equal the
supplied Product engine identifier, no `pkm-*` Product Compose project, and no production
credential, vault, or network-identity references on VM 102. It does not establish that a separate
Product engine was supplied or valid; that admission defect is governed by Issue #5072.

Candidate evidence is accepted only when it is no more than 24 hours old and fingerprint-verifiable.
The evaluator redacts recognized secret-key and secret-value patterns, and refuses evidence it
recognizes as secret-bearing. It does not yet prove universal raw-secret exclusion for opaque
credential-like fields; that admission defect is governed by Issue #5072. A passing candidate result
is still not live qualification: `live_qualified` remains `false` until a separate governed
live-operations receipt exists.

GPU passthrough and test Tailscale are deliberately not qualification prerequisites. Repository
fixtures and candidate-policy tests are evidence of evaluator behavior only; they cannot establish
the live TARS state.

## Target boundary

- VM 102 hosts the independently deployed BuilderOps API, PostgreSQL store, migration gate, outbox
  worker, and the other resident Dev System components only after the complete topology and
  qualification receipts pass.
- MacBook workflows call the authenticated API over an approved private path; no workflow opens
  PostgreSQL, shells into a database-owning CLI, or creates local authority.
- a privileged Builder System executor, wherever its separately evidenced execution adapter runs,
  calls the same API and alone holds any scoped GitHub/model credentials for
  review/repair/verification/merge orchestration;
- Product Runtime has no BuilderOps route, startup hook, state mount, credential, health path, or
  deployment ownership; and
- SQLite/JSONL/JSON remains only read-only migration input or an explicitly injected test adapter.

## Implementation tasks

| # | Task | ID | Issue | Delivers | Depends on |
|---|---|---|---|---|---|
| 1 | [PostgreSQL Transaction Kernel](POSTGRES_TRANSACTION_KERNEL.md) | BCP-01 | #3792 | Store port, PostgreSQL schema/migrations, fenced leases, atomic idempotency + state + receipt + outbox | — |
| 2 | [Independent Authenticated Deployment](INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md) | BCP-02 | #3790 / #5056 | Separate service app/Compose project outside the `pkm-*` failure domain, auth, release pin, rebuildable durability, health + alerting, trust boundary | BCP-01 |
| 3 | [Legacy Authority Migration](LEGACY_AUTHORITY_MIGRATION.md) | BCP-03 | #3789 | Complete SQLite/JSONL/JSON inventory, read-only import, evidence-quarantine/authority-tombstone report, authority epoch | BCP-01 |
| 4 | [API-Only Client Cutover](API_ONLY_CLIENT_CUTOVER.md) | BCP-04 | #3791 | MacBook skills/CLI/automation use authenticated API and fail closed with no local/direct-DB fallback | BCP-02 |
| 5 | [Demerzel Review And Merge Orchestration](DEMERZEL_REVIEW_MERGE_ORCHESTRATION.md) | BCP-05 | existing #3603; baseline PR #3620 merged | Migrate the delivered executor to API/PostgreSQL/outbox and scoped merge authority | BCP-02, BCP-04 |
| 6 | [Authority Cutover And Product Separation](AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md) | BCP-06 | #3793 | Import/cutover, disable legacy writers, remove Product routes/startup, prove rebuild/no-fallback, archive sources | BCP-03, BCP-04, BCP-05 |
| 7 | [Owner-Doc Enactment And Closure](OWNER_DOC_ENACTMENT_AND_CLOSURE.md) | BCP-07 | existing #3690 | Reconcile shipped Builder System/store/dispatcher/deployment/security/health docs and close parent | BCP-06 |

Execution order:

`BCP-01 -> BCP-02`; `BCP-03` may start after BCP-01 and run beside BCP-02. Then
`BCP-02 -> BCP-04 -> BCP-05`; `BCP-03 + BCP-04 + BCP-05 -> BCP-06 -> BCP-07`.

Parent validation hub: #3788. BCP-01 is implemented in the development baseline by #3792/PR #3852,
BCP-02's repo/deployment contract is implemented by #3790 without live authority activation,
BCP-03 (#3789) is implemented in the development baseline by PR #3929 (mechanism only), and
BCP-04 (#3791) is implemented in the development baseline (client transport and gates only,
non-authoritative). The BCP-05 migration (#3603) follows BCP-04 acceptance, and BCP-06/07 remain
blocked.
BCP-05 and BCP-07 reuse existing issues rather than creating duplicate work. PR #3620 is the
merged BCP-05 implementation baseline; later migration lands in a new PR under the existing issue,
not by rewriting that merge.

## Cross-task invariants / partial-failure safety

1. **One authority epoch.** At most one production PostgreSQL authority epoch accepts mutations.
   Legacy sources are frozen before import; no live SQLite lease is imported.
2. **API-only authority.** Every production client, including the Builder System executor, uses the
   authenticated API. Only the BuilderOps data layer reaches PostgreSQL.
3. **Atomic local transition.** Idempotency result, guarded state mutation, receipt, and outbox intent
   commit in one PostgreSQL transaction. If any part fails, none becomes visible. The local
   PostgreSQL commit is the acknowledgement gate for API success/replay, dependent authority
   transitions, and outbox claim eligibility. BuilderOps durability is rebuildable: no archive
   pipeline or recovery target is admitted, and a deferred backup capability cannot affect readiness.
4. **Durable, reconciled external effects.** After an eligible intent is claimed, the executor
   commits a fenced pre-effect attempt/receipt locally before calling GitHub; an uncommitted attempt
   leaves GitHub untouched (ADR-0062 A1). A timeout is `unknown`, not `failed`; retry reads GitHub
   before repeating, and terminal success requires GitHub readback bound to repo and current SHA.
   After a service rebuild, external effects reconcile against GitHub before the executor resumes.
5. **Fenced leases.** Stale workers cannot mutate after expiry/reassignment; fencing survives API,
   worker, and database restarts.
6. **Credential/policy non-transitivity and non-persistence.** A credential/lease for repo A cannot
   act on repo B. The privileged executor re-resolves the protected-base delivery manifest and a
   host-side `RepoRef` credential mapping; client-selected policy cannot weaken it. The GitHub effect
   is conditional on the same protected-base/manifest authorization fence or a merge queue that
   revalidates it, so a post-validation base/policy change produces no merge. Product and general
   clients cannot obtain merge credentials. Raw secrets never enter PostgreSQL, outbox payloads,
   receipts, artifacts, logs/metrics, or WAL. A future deferred backup capability requires a separate
   custody decision and cannot be inferred from this deployment contract.
7. **Independent lifecycle and failure domain.** Product start/stop/deploy/health cannot
   start, stop, publish, or rebuild BuilderOps, and BuilderOps failure does not change Product
   process ownership. The BuilderOps service/database run outside the `pkm-*` container-VM failure
   domain (ADR-0062 A2), and `/healthz` is wired into the operator alerting path. Degraded mode:
   with the control plane unreachable, repo-authorized direct git/GitHub work continues without
   fabricating BuilderOps state; orchestration-gated actions wait.
8. **No authority rewind.** Rollback selects a compatible prior code/config/image pin. After a
   rebuild, external effects reconcile against GitHub before writes reopen under current fencing;
   BuilderOps never rewinds surviving state or re-enables SQLite/JSONL/JSON.
9. **Artifact integrity.** Large artifacts may remain content-addressed files, but identity, state,
   terminal receipts, and promotion/outbox status are PostgreSQL-authoritative.
10. **Fail-loud cutover.** Incomplete producer-derived source coverage, an unenumerated host/
    worktree/container root, authority-bearing ambiguity that is neither evidence-resolved nor
    converted into a duplicate-preventing non-authoritative tombstone, failed rebuild preflight,
    unhealthy schema/outbox, missing credentials, or an extant Product route blocks cutover. Plain
    quarantine is permitted only for evidence-only material that cannot authorize or replay effects.

Partial-failure examples:

- If the API commits an outbox row and crashes before responding, an idempotent client retry creates
  no second intent and returns the original committed result.
- If the executor crashes between claiming an intent and committing its fenced pre-effect attempt,
  GitHub is untouched; on restart the same deterministic operation executes once.
- If GitHub accepts a merge/create request and the executor times out, the executor reconciles by
  deterministic marker/repo/SHA before retry and records the readback receipt.
- If import sees two authority-bearing records with one identity and different hashes, neither is
  chosen silently; cutover stays blocked until evidence resolves the conflict or a non-authoritative
  tombstone reserves every identity/operation key and makes replay fail closed.
- A deferred backup/restore proposal has no effect on BuilderOps deployment or cutover until it is
  separately governed and accepted.
- If BuilderOps is unavailable, MacBook commands return a typed unavailable/auth error. They do not
  initialize SQLite or fall back to direct GitHub lease simulation.

## Capability acceptance criteria

- [ ] One authenticated API endpoint on VM 102 coordinates records, tasks, leases, attempts,
  idempotency, receipts, and outbox state against one PostgreSQL authority.
  Verify: BCP-01/02 contract tests named in their task files.
- [ ] Every authority-bearing record carries the mandatory multi-repo envelope; leases,
  idempotency, promotions, and routing are namespaced by repo and fail closed on absent/ambiguous
  `(repo, stack, task-class)` policy.
  Verify: BCP-01 multi-repo namespace test plus BCP-04 delivery-manifest routing test.
- [ ] A MacBook client and the privileged Builder System executor can complete a restart-safe task flow
  without direct database access or local-authority fallback.
  Verify: `tests/builderops/control_plane/test_end_to_end_api_flow.py::test_remote_client_and_executor_share_one_authority_epoch`.
- [ ] A crash at each state/outbox/external-effect boundary produces no duplicate accepted transition
  and a reconcilable receipt chain.
  Verify: `tests/builderops/control_plane/test_outbox_recovery.py::test_external_effect_crash_windows_reconcile_once`.
- [ ] A producer-derived manifest proves the complete client/VM-102 worktree/container source
  universe, and every expected source is imported, quarantined, tombstoned, explicitly accounted
  missing, or archived, with no live lease carried into the new epoch. Evidence-backed repo
  provenance is backfilled. Plain quarantine contains only evidence-only material; every authority-
  bearing ambiguity is evidence-resolved or represented by a duplicate-preventing,
  non-authoritative tombstone before activation.
  Verify: BCP-03 migration reconciliation receipt plus BCP-06 cutover receipt.
- [ ] Product Runtime contains no BuilderOps route, process bootstrap, data mount, secret, or health
  dependency, and its lifecycle remains healthy with BuilderOps stopped.
  Verify: `tests/architecture/test_builderops_product_separation.py::test_product_runtime_has_no_builderops_ownership`.
- [ ] A rebuild from repository source, attested images, configuration, and VM-local secret references
  reaches migration-gated readiness without a backup, restore, recovery target, or WAL archive.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_deploy_and_rollback_receipts_bind_pin_schema_and_epoch`.
- [ ] Durable state contains no raw client/database/GitHub/model credential, and rollback/rebuild
  cannot rewind surviving state.
  Verify: `tests/ops/test_builderops_deploy_contract.py::test_readiness_failure_reactivates_previous_live_release`.
- [ ] A verification-gated merge uses the repo-scoped executor credential, independently binds the
  protected-base delivery manifest and host credential mapping to the current PR SHA, executes only
  through a GitHub-enforced base/manifest conditional or revalidated merge queue, rejects a base or
  policy change after final validation, and becomes terminal only after GitHub readback.
  Verify: the migrated #3603/#3620 test baseline, BCP-05 protected-base race test, and runtime receipt.

## Backlog reconciliation

- **Reuse #3603 and the merged PR #3620 baseline** for BCP-05. Preserve the delivered
  review/repair/recovery logic; replace its dispatcher-SQLite ledger and direct claim boundary with
  the BuilderOps API/PostgreSQL contract in later migration work. Do not reopen or rewrite #3620.
- **Reuse #3690** for BCP-07. Its old host-stable-SQLite wording is superseded and must be updated
  when the BCP-06 cutover is proved.
- **Supersede the target of #3686 / PR #3695.** Their fragmentation and host-ack evidence is required
  by BCP-03; host-stable SQLite is not a production destination.
- **Do not duplicate #3174.** Repo-explicit skill targeting and cross-repo promotion-copy work remains
  there; BCP-04 consumes its contract where delivered.
- **Preserve #3288 model inquiry behavior.** BCP-03/06 migrates its file-only authoritative envelope
  and receipts while retaining immutable content-addressed artifacts.
- **Preserve #3224** as the existing autonomous review/repair/closure validation hub.

## Validation and owner-doc promotion

Each child posts its verification receipt to the parent validation hub. BCP-06 performs the one-way
authority cutover only after BCP-01 through BCP-05 are accepted. BCP-07 updates current-state owner
docs only after the deployed topology proves the claims; this specification must not make future
behavior read as shipped.

## Related docs

- `docs/adr/ADR-0010-builderops-vault-authority-boundary.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/audits/BUILDEROPS_CONTROL_PLANE_2026-07-15.md`
- `docs/architecture/SBS_OPERATING_MODEL.md §3`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/AGENT_ISSUE_DISPATCHER.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
