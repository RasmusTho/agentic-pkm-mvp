State: Accepted target-state specification (owner decision, 2026-07-15; amended per ADR-0062 A1-A3, 2026-07-16: asynchronous recovery durability, failure-domain separation, degraded-mode contract, CKM/CEG migration source). Parent validation hub #3788 remains `agent:blocked` while child slices are outstanding. BCP-01 is implemented in the development baseline by #3792/PR #3852; the repo/deployment contract for BCP-02 is implemented by #3790; BCP-03 is implemented in the development baseline by #3789/PR #3929 (mechanism only, no cutover); BCP-04 is implemented in the development baseline by #3791 (client transport and gates only, non-authoritative); live authority activation remains forbidden until BCP-03 through BCP-06 complete. BCP-05 still waits for BCP-04 acceptance, and BCP-06/07 remain dependency-blocked. Existing issues #3603 and #3690 are reconciled into the sequence.
Doc role: Specification directory
Authority: Owns the bounded task decomposition and cross-task invariants after merge. ADR-0062 owns the architectural decision; ADR-0010 owns the repo/BuilderOps authority seam; shipped owner docs win for current behavior.
Owner: BuilderOps governance / Architecture spine
Temporal class: Target-state implementation contract
Source of truth: ADR-0062 plus this directory for task shape and dependency order.

# BuilderOps independent control plane

Build a permanent API-first BuilderOps control plane on Demerzel with one PostgreSQL operational
authority, independent deployment/trust lifecycle, API-only MacBook clients, durable outbox-based
external effects, and scoped review/merge execution. Then migrate every SQLite/file authority and
remove BuilderOps ownership from Product Runtime.

This specification does not transfer product or delivery authority. GitHub Issues, PR head SHA,
required CI, review gates, repository protection, and GitHub merge results remain authoritative.

## Delivery status

BCP-01 is implemented in the development baseline by #3792/PR #3852 with the independent
PostgreSQL migration lineage, domain-neutral store port, atomic local task/transition/receipt/
idempotency/outbox transaction, fenced leases, crash-safe reconciliation, and explicit SQLite
migration/test adapter. BCP-02 (#3790) adds the independent scoped-auth service, migration-gated
BuilderOps Compose project, separate-engine preflight, immutable pins, authenticated probes,
secret-safe status/metrics, deploy/rollback receipts, asynchronous WAL-G backup/archive contract,
and independently credentialed restore drill with a new recovery epoch and executor fence. This is
still not a production cutover: the checked-in zero pins are non-runnable placeholders, no live
Demerzel authority was activated, and client migration, legacy import, privileged execution, final
restore rehearsal, and Product Runtime route removal remain owned by BCP-03 through BCP-06.

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

- Demerzel hosts the independently deployed BuilderOps API, PostgreSQL store, migration gate, and
  outbox worker.
- MacBook workflows call the authenticated API over Tailscale; no workflow opens PostgreSQL, shells
  into a database-owning CLI, or creates local authority.
- a privileged Demerzel executor calls the same API and alone holds scoped GitHub/model credentials
  for review/repair/verification/merge orchestration;
- Product Runtime has no BuilderOps route, startup hook, state mount, credential, health path, or
  deployment ownership; and
- SQLite/JSONL/JSON remains only read-only migration input or an explicitly injected test adapter.

## Implementation tasks

| # | Task | ID | Issue | Delivers | Depends on |
|---|---|---|---|---|---|
| 1 | [PostgreSQL Transaction Kernel](POSTGRES_TRANSACTION_KERNEL.md) | BCP-01 | #3792 | Store port, PostgreSQL schema/migrations, fenced leases, atomic idempotency + state + receipt + outbox | — |
| 2 | [Independent Authenticated Deployment](INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md) | BCP-02 | #3790 | Separate service app/Compose project outside the `pkm-*` failure domain, auth, release pin, health + alerting, encrypted backup + archived-WAL recovery, trust boundary | BCP-01 |
| 3 | [Legacy Authority Migration](LEGACY_AUTHORITY_MIGRATION.md) | BCP-03 | #3789 | Complete SQLite/JSONL/JSON inventory, read-only import, evidence-quarantine/authority-tombstone report, authority epoch | BCP-01 |
| 4 | [API-Only Client Cutover](API_ONLY_CLIENT_CUTOVER.md) | BCP-04 | #3791 | MacBook skills/CLI/automation use authenticated API and fail closed with no local/direct-DB fallback | BCP-02 |
| 5 | [Demerzel Review And Merge Orchestration](DEMERZEL_REVIEW_MERGE_ORCHESTRATION.md) | BCP-05 | existing #3603; baseline PR #3620 merged | Migrate the delivered executor to API/PostgreSQL/outbox and scoped merge authority | BCP-02, BCP-04 |
| 6 | [Authority Cutover And Product Separation](AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md) | BCP-06 | #3793 | Import/cutover, disable legacy writers, remove Product routes/startup, prove restore-from-backup/no-fallback, archive sources | BCP-03, BCP-04, BCP-05 |
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
2. **API-only authority.** Every production client, including the Demerzel executor, uses the
   authenticated API. Only the BuilderOps data layer reaches PostgreSQL.
3. **Atomic local transition.** Idempotency result, guarded state mutation, receipt, and outbox intent
   commit in one PostgreSQL transaction. If any part fails, none becomes visible. The local
   PostgreSQL commit is the acknowledgement gate for API success/replay, dependent authority
   transitions, and outbox claim eligibility (ADR-0062 A1). Recovery durability is asynchronous:
   encrypted backups plus archived WAL to a target outside Demerzel's primary host/storage failure
   domains. A co-resident recovery target fails readiness (structural misconfiguration is
   fail-closed); stalled archiving raises a loud alert, not an acknowledgement block.
4. **Durable, reconciled external effects.** After an eligible intent is claimed, the executor
   commits a fenced pre-effect attempt/receipt locally before calling GitHub; an uncommitted attempt
   leaves GitHub untouched (ADR-0062 A1). A timeout is `unknown`, not `failed`; retry reads GitHub
   before repeating, and terminal success requires GitHub readback bound to repo and current SHA.
   After a restore, external effects reconcile against GitHub before the executor resumes.
5. **Fenced leases.** Stale workers cannot mutate after expiry/reassignment; fencing survives API,
   worker, and database restarts.
6. **Credential/policy non-transitivity and non-persistence.** A credential/lease for repo A cannot
   act on repo B. The privileged executor re-resolves the protected-base delivery manifest and a
   host-side `RepoRef` credential mapping; client-selected policy cannot weaken it. The GitHub effect
   is conditional on the same protected-base/manifest authorization fence or a merge queue that
   revalidates it, so a post-validation base/policy change produces no merge. Product and general
   clients cannot obtain merge credentials. Raw secrets never enter PostgreSQL, outbox payloads,
   receipts, artifacts, logs/metrics, WAL, or BuilderOps backups. Backup/WAL decryption uses
   independently recoverable key/KMS custody outside Demerzel's failure domains rather than depending
   solely on its host secret store.
7. **Independent lifecycle and failure domain.** Product start/stop/deploy/health/backup cannot
   start, stop, publish, or restore BuilderOps, and BuilderOps failure does not change Product
   process ownership. The BuilderOps service/database run outside the `pkm-*` container-VM failure
   domain (ADR-0062 A2), and `/healthz` is wired into the operator alerting path. Degraded mode:
   with the control plane unreachable, repo-authorized direct git/GitHub work continues without
   fabricating BuilderOps state; orchestration-gated actions wait.
8. **No authority rewind.** Before activation, rollback may use the pre-import PostgreSQL backup.
   After activation, recovery restores the latest archived point, reconciles external effects
   against GitHub, and starts a new fencing epoch before writes reopen (ADR-0062 A1: the tail since
   the last archived point is an accepted loss window); it never rewinds surviving state or
   re-enables SQLite/JSONL/JSON.
9. **Artifact integrity.** Large artifacts may remain content-addressed files, but identity, state,
   terminal receipts, and promotion/outbox status are PostgreSQL-authoritative.
10. **Fail-loud cutover.** Incomplete producer-derived source coverage, an unenumerated host/
    worktree/container root, authority-bearing ambiguity that is neither evidence-resolved nor
    converted into a duplicate-preventing non-authoritative tombstone, failed restore drill,
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
- If backup succeeds but the restore drill fails, deployment may continue in a non-authoritative test
  environment but production cutover is rejected.
- If BuilderOps is unavailable, MacBook commands return a typed unavailable/auth error. They do not
  initialize SQLite or fall back to direct GitHub lease simulation.

## Capability acceptance criteria

- [ ] One authenticated API endpoint on Demerzel coordinates records, tasks, leases, attempts,
  idempotency, receipts, and outbox state against one PostgreSQL authority.
  Verify: BCP-01/02 contract tests named in their task files.
- [ ] Every authority-bearing record carries the mandatory multi-repo envelope; leases,
  idempotency, promotions, and routing are namespaced by repo and fail closed on absent/ambiguous
  `(repo, stack, task-class)` policy.
  Verify: BCP-01 multi-repo namespace test plus BCP-04 delivery-manifest routing test.
- [ ] A MacBook client and the privileged Demerzel executor can complete a restart-safe task flow
  without direct database access or local-authority fallback.
  Verify: `tests/builderops/control_plane/test_end_to_end_api_flow.py::test_remote_client_and_executor_share_one_authority_epoch`.
- [ ] A crash at each state/outbox/external-effect boundary produces no duplicate accepted transition
  and a reconcilable receipt chain.
  Verify: `tests/builderops/control_plane/test_outbox_recovery.py::test_external_effect_crash_windows_reconcile_once`.
- [ ] A producer-derived manifest proves the complete MacBook/Demerzel worktree/container source
  universe, and every expected source is imported, quarantined, tombstoned, explicitly accounted
  missing, or archived, with no live lease carried into the new epoch. Evidence-backed repo
  provenance is backfilled. Plain quarantine contains only evidence-only material; every authority-
  bearing ambiguity is evidence-resolved or represented by a duplicate-preventing,
  non-authoritative tombstone before activation.
  Verify: BCP-03 migration reconciliation receipt plus BCP-06 cutover receipt.
- [ ] Product Runtime contains no BuilderOps route, process bootstrap, data mount, secret, or health
  dependency, and its lifecycle remains healthy with BuilderOps stopped.
  Verify: `tests/architecture/test_builderops_product_separation.py::test_product_runtime_has_no_builderops_ownership`.
- [ ] An encrypted full backup plus archived WAL restores into a disposable database to the latest
  archived point with Demerzel's host secret store unavailable, using independently recoverable
  key/KMS custody, and passes readiness/invariant checks before authoritative cutover.
  Verify: BCP-02 restore-from-backup drill and BCP-06 cutover/recovery gate.
- [ ] Durable-state, WAL, and restored-backup negative scans prove no raw client/database/GitHub/
  model/recovery-decryption credential is persisted, and post-activation recovery cannot rewind
  surviving state.
  Verify: BCP-02 credential-persistence test plus BCP-06 no-authority-rewind rehearsal.
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
