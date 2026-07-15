State: Accepted target-state specification (owner decision, 2026-07-15). Parent validation hub #3788 remains `agent:blocked` while child slices are outstanding; BCP-01 becomes the first executable child after PR #3691 merges and strict readiness validation passes. Existing issues #3603 and #3690 are reconciled into the sequence.
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
| 2 | [Independent Authenticated Deployment](INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md) | BCP-02 | #3790 | Separate service app/Compose project, auth, release pin, health, full backup + continuous WAL recovery, trust boundary | BCP-01 |
| 3 | [Legacy Authority Migration](LEGACY_AUTHORITY_MIGRATION.md) | BCP-03 | #3789 | Complete SQLite/JSONL/JSON inventory, read-only import, conflict/quarantine report, authority epoch | BCP-01 |
| 4 | [API-Only Client Cutover](API_ONLY_CLIENT_CUTOVER.md) | BCP-04 | #3791 | MacBook skills/CLI/automation use authenticated API and fail closed with no local/direct-DB fallback | BCP-02 |
| 5 | [Demerzel Review And Merge Orchestration](DEMERZEL_REVIEW_MERGE_ORCHESTRATION.md) | BCP-05 | existing #3603; baseline PR #3620 merged | Migrate the delivered executor to API/PostgreSQL/outbox and scoped merge authority | BCP-02, BCP-04 |
| 6 | [Authority Cutover And Product Separation](AUTHORITY_CUTOVER_PRODUCT_SEPARATION.md) | BCP-06 | #3793 | Import/cutover, disable legacy writers, remove Product routes/startup, prove restore-through-watermark/no-fallback, archive sources | BCP-03, BCP-04, BCP-05 |
| 7 | [Owner-Doc Enactment And Closure](OWNER_DOC_ENACTMENT_AND_CLOSURE.md) | BCP-07 | existing #3690 | Reconcile shipped Builder System/store/dispatcher/deployment/security/health docs and close parent | BCP-06 |

Execution order:

`BCP-01 -> BCP-02`; `BCP-03` may start after BCP-01 and run beside BCP-02. Then
`BCP-02 -> BCP-04 -> BCP-05`; `BCP-03 + BCP-04 + BCP-05 -> BCP-06 -> BCP-07`.

Parent validation hub: #3788. BCP-01 is the first `agent:ready` candidate after PR #3691 merges;
dependency-blocked children remain `agent:blocked`.
BCP-05 and BCP-07 reuse existing issues rather than creating duplicate work. PR #3620 is the
merged BCP-05 implementation baseline; later migration lands in a new PR under the existing issue,
not by rewriting that merge.

## Cross-task invariants / partial-failure safety

1. **One authority epoch.** At most one production PostgreSQL authority epoch accepts mutations.
   Legacy sources are frozen before import; no live SQLite lease is imported.
2. **API-only authority.** Every production client, including the Demerzel executor, uses the
   authenticated API. Only the BuilderOps data layer reaches PostgreSQL.
3. **Atomic local transition.** Idempotency result, guarded state mutation, receipt, and outbox intent
   commit in one PostgreSQL transaction. If any part fails, none becomes visible. The API
   acknowledges only after the commit/recovery LSN is durable outside Demerzel's primary host and
   storage failure domains; a co-resident target fails readiness.
4. **Reconciled external effects.** An outbox timeout is `unknown`, not `failed`. Retry reads GitHub
   before repeating; terminal success requires GitHub readback bound to repo and current SHA.
5. **Fenced leases.** Stale workers cannot mutate after expiry/reassignment; fencing survives API,
   worker, and database restarts.
6. **Credential/policy non-transitivity and non-persistence.** A credential/lease for repo A cannot
   act on repo B. The privileged executor re-resolves the protected-base delivery manifest and a
   host-side `RepoRef` credential mapping; client-selected policy cannot weaken it. Product and
   general clients cannot obtain merge credentials. Raw secrets never enter PostgreSQL, outbox
   payloads, receipts, artifacts, logs/metrics, or BuilderOps backups.
7. **Independent lifecycle.** Product start/stop/deploy/health/backup cannot start, stop, publish, or
   restore BuilderOps, and BuilderOps failure does not change Product process ownership.
8. **No authority rewind.** Before activation, rollback may use the pre-import PostgreSQL backup.
   After activation, a compatible image or full-backup + continuous-WAL recovery must reach the
   highest acknowledged LSN/receipt sequence before writes reopen; it never rewinds accepted state
   or re-enables SQLite/JSONL/JSON.
9. **Artifact integrity.** Large artifacts may remain content-addressed files, but identity, state,
   terminal receipts, and promotion/outbox status are PostgreSQL-authoritative.
10. **Fail-loud cutover.** Incomplete producer-derived source coverage, an unenumerated host/
    worktree/container root, unresolved conflicts, failed restore drill, unhealthy schema/outbox,
    missing credentials, or an extant Product route blocks cutover.

Partial-failure examples:

- If the API commits an outbox row and crashes before responding, an idempotent client retry returns
  the committed result; it does not create a second intent.
- If GitHub accepts a merge/create request and the executor times out, the executor reconciles by
  deterministic marker/repo/SHA before retry and records the readback receipt.
- If import sees two records with one identity and different hashes, neither is chosen silently; the
  conflict is quarantined and cutover stays blocked.
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
  universe, and every expected source is imported, quarantined, explicitly accounted missing, or
  archived, with no live lease carried into the new epoch. Evidence-backed repo provenance is
  backfilled; unresolved provenance remains non-authoritative quarantine.
  Verify: BCP-03 migration reconciliation receipt plus BCP-06 cutover receipt.
- [ ] Product Runtime contains no BuilderOps route, process bootstrap, data mount, secret, or health
  dependency, and its lifecycle remains healthy with BuilderOps stopped.
  Verify: `tests/architecture/test_builderops_product_separation.py::test_product_runtime_has_no_builderops_ownership`.
- [ ] A full backup plus synchronously durable continuous WAL restores into a disposable database
  through the highest acknowledged LSN/receipt sequence and passes readiness/invariant checks before
  authoritative cutover.
  Verify: BCP-02 restore-through-watermark drill and BCP-06 cutover/recovery gate.
- [ ] Durable-state and restored-backup negative scans prove no raw client/database/GitHub/model
  credential is persisted, and post-activation recovery cannot lose acknowledged state.
  Verify: BCP-02 credential-persistence test plus BCP-06 no-authority-rewind rehearsal.
- [ ] A verification-gated merge uses the repo-scoped executor credential, independently binds the
  protected-base delivery manifest and host credential mapping to the current PR SHA, and becomes
  terminal only after GitHub readback.
  Verify: the migrated #3603/#3620 test baseline and BCP-05 runtime receipt.

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
