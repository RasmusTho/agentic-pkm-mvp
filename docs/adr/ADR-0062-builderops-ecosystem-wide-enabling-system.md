State: Accepted (owner decision, 2026-07-15). Re-scopes BuilderOps as an ecosystem-wide, API-first enabling system with an independent Demerzel deployment and one PostgreSQL operational authority. Docs/governance decision only; no runtime behavior changes here. Amended 2026-07-16 (A1-A3, owner ruling): asynchronous recovery durability replaces the synchronous watermark regime; failure-domain separation and a degraded-mode contract are added; CKM/CEG (ADR-0057) is named as a D6 migration source.
Doc role: Decision record (ADR)
Authority: Authoritative for BuilderOps scope, deployment/trust boundary, operational authority, client access, and extraction posture. Layers on ADR-0010 without changing repo/GitHub delivery authority.
Owner: BuilderOps governance / Architecture spine (Rasmus)
Temporal class: Durable decision (supersede by ADR if the ecosystem-wide scope, API-only boundary, PostgreSQL authority, independent lifecycle, or ADR-0010 relationship reverses).
Source of truth: This ADR plus ADR-0010. `docs/BUILDEROPS_CONTROL_PLANE/` is the executable target-state specification. `docs/audits/BUILDEROPS_CONTROL_PLANE_2026-07-15.md` and the recorded model inquiry are advisory evidence, not authority.

# ADR-0062: BuilderOps as an ecosystem-wide API-first enabling system

**Date:** 2026-07-14; revised 2026-07-15
**Status:** Accepted (owner decision, 2026-07-15)

## Context

Yggdrasil is multi-repo: Mimer, Heimdal, Bifrost, and future constituents are sovereign over their
own product truth. BuilderOps is the ISO/IEC/IEEE 15288 enabling system that coordinates how those
repos are built. It is not a Product Runtime subsystem or an ecosystem constituent. ADR-0010 fixes
that authority seam: repo files, GitHub Issues/PRs, required CI, protection rules, and merge state
remain delivery authority; BuilderOps holds operational orchestration state and evidence.

The existing implementation violates the intended operational separation:

- Product FastAPI owns `/api/builderops`, and Product dev/prod startup bootstraps BuilderOps and the
  dispatcher.
- generic BuilderOps state defaults to a CWD-relative SQLite database; the dispatcher has a second
  SQLite/JSONL authority; model inquiries and epic runs add file-first authorities;
- host CLI/bootstrap and container requests can resolve different database files, while issue
  #3686 demonstrates the same fragmentation across worktrees;
- current BuilderOps HTTP mutations have no BuilderOps-specific authentication;
- no independent BuilderOps Compose project, release pin, database/volume, migration lineage,
  health contract, backup/restore lifecycle, or credential boundary exists; and
- the dispatcher commits database events and its JSONL projection separately, while external
  GitHub effects have no transactional outbox.

PR #3691 originally proposed a host-stable SQLite file. That was a useful immediate diagnosis, but
the proposed ADR's own T2 trigger is already met: BuilderOps needs independent cadence and
availability, and Demerzel review/merge execution needs credentials outside the Product trust zone.
The 2026-07-15 owner direction therefore replaces that draft recommendation before ADR acceptance.

## Decision

### D1 — Ecosystem-wide enabling system; repo/GitHub authority remains hard

BuilderOps serves all Yggdrasil consumer repos. Every authority-bearing operation is explicitly
addressed to a fully qualified `RepoRef`; unsupported or ambiguous repo scope fails loudly. Per-repo
delivery manifests define stack, validation, review/merge policy, and accepted-delivery semantics.

BuilderOps does not replace repo or GitHub authority. It may coordinate work, hold leases, schedule
review, record attempts and receipts, and propose or execute an authorized delivery transition. A
GitHub Issue remains the executable task contract; the PR head SHA, required CI, review gate,
protection rules, and GitHub merge result remain authoritative for delivery.

### D2 — Permanent API-first control plane on Demerzel

Demerzel (the Mac mini) hosts one permanent BuilderOps control plane. MacBook clients use its
authenticated API over the Demerzel/Tailscale boundary. No client may open the production database,
invoke a database-owning CLI through SSH, or create a local SQLite fallback for an authority-bearing
operation.

Client behavior is fail-closed:

- an unavailable or unauthenticated API cannot produce a valid lease, idempotency result, terminal
  receipt, promotion, or merge decision;
- a read-only cache may support clearly marked stale display, but never mutation or authority; and
- direct GitHub operations remain possible only where the repo workflow independently authorizes
  them; they must not fabricate BuilderOps state or bypass a required BuilderOps lease.

Tailscale supplies the private network boundary, not application identity. The service requires
encrypted transport plus revocable, scoped client credentials. The concrete credential format is
an implementation choice, but anonymous tailnet mutation, a shared Product API key, and credentials
stored in a consumer checkout are forbidden.

Raw client, database, GitHub, model/session, and recovery-decryption credentials never enter
PostgreSQL, outbox payloads, receipts, artifacts, logs, metrics, WAL, or BuilderOps backups. Durable
state may carry only a secret reference, non-secret fingerprint, privilege/scope descriptor, and
rotation generation. Operational secret material remains in a Demerzel/MacBook host secret store
outside the BuilderOps data and backup boundary. Backup/WAL decryption instead uses independently
recoverable key custody or KMS authorization outside Demerzel's primary host/storage failure domains;
the restore path cannot depend solely on the lost host secret store.

### D3 — One PostgreSQL operational authority

One BuilderOps PostgreSQL store on Demerzel is the production authority for operational identity and
state, including tasks, attempts, records, transitions, leases/fencing tokens, idempotency keys,
promotion intents, outbox entries, and append-only receipts. Dispatcher coordination is folded into
this same authority; it does not retain a second production SQLite database or JSONL authority.

An accepted state transition that implies an external effect commits, in one PostgreSQL
transaction:

1. the idempotency reservation/result;
2. the guarded state mutation and lease/fencing validation;
3. the append-only BuilderOps receipt; and
4. an outbox intent.

> **Amended by A1 (2026-07-16):** the watermark/acknowledged-LSN gating in the two paragraphs below
> is superseded — the local PostgreSQL commit is the acknowledgement and eligibility gate, and
> recovery durability is asynchronous. See `## Amendments`.

The transaction records its commit/recovery LSN. No authority-bearing success response, idempotent
replay, dependent authority transition, or outbox claim may pass until the independent recovery
watermark covers that LSN in an encrypted target outside Demerzel's primary host and storage failure
domains. A co-resident volume or storage backend is not independent recovery durability. After an
eligible intent is claimed, the executor commits a fenced pre-effect attempt/receipt and also waits
for that transaction's LSN to cross the independent recovery watermark before calling GitHub. If the
watermark stalls, readiness fails closed, clients receive pending/unavailable rather than success,
and the executor leaves GitHub untouched.

GitHub cannot participate in either PostgreSQL transaction. Once both durability gates pass, the
privileged executor performs the external effect with deterministic reconciliation, reads GitHub
back, and records the observed outcome in a new transaction and receipt. A timed-out call is unknown,
never assumed failed; retries reconcile before repeating. Terminal success is never inferred solely
from the attempted call.

Immutable large artifacts may remain in a dedicated artifact store only as content-addressed
payloads referenced by PostgreSQL. No file-only manifest, receipt, JSON run state, or Markdown
projection may be the sole production authority for an orchestration transition. Existing
file-first model-inquiry and epic-run records are migration inputs whose authoritative envelopes,
state, and receipts move to the control plane; human-readable files remain projections/artifacts.

SQLite remains permitted only as a read-only migration source and as an explicitly injected test
adapter. Production paths contain no SQLite authority or automatic SQLite fallback.

### D4 — Independent deployment, lifecycle, and trust zone

BuilderOps reuses Demerzel's Docker/PostgreSQL operational capability but has its own Compose project
and lifecycle, separate from `pkm-dev`, `pkm-test`, and `pkm-prod`. It owns distinct:

- service processes and Compose project;
- PostgreSQL database/service, persistent volume, database role, and secrets;
- versioned migration lineage and migration gate;
- immutable release pin and deployment/rollback receipt;
- `/healthz`, `/readyz`, structured status/metrics, and alert/probe path;
- *(amended by A1, 2026-07-16: an asynchronous backup/WAL-archive regime and a restore-from-backup
  drill replace every synchronous/acknowledged-LSN item in this bullet, including the
  "restore-through-acknowledged-LSN drill" at its end)* scheduled full backup plus
  continuous encrypted WAL/recovery durability in a target that survives
  loss of Demerzel's primary host/storage failure domain, independently recoverable key/KMS custody,
  retention, restore tooling, and a proved restore-through-acknowledged-LSN drill with Demerzel's
  host secret store unavailable; and
- API and executor credentials with rotation/revocation procedures.

Product Runtime must not start, stop, proxy, health-gate, migrate, back up, mount, authenticate, or
publish BuilderOps. Product configuration and containers receive no BuilderOps database or merge
credential. The independent BuilderOps service may initially remain source-controlled in this
repository behind a hard package/build boundary; independent deployment is required now, while a
separate source repository remains trigger-gated.

### D5 — Scoped review and merge authority on Demerzel

Demerzel runs the review/repair/verification/merge orchestration tracked by issue #3603. PR #3620
merged on 2026-07-15 and delivers the repo-side consumer, recovery, review, and gated-merge baseline;
subsequent correctness repairs are also present on `main`. That work is migrated, not duplicated:
BCP-05 moves its durable state and claims from dispatcher SQLite to the BuilderOps API and PostgreSQL
authority. The merged PR is an immutable delivery baseline, not a branch to reopen or rewrite.

The executor is a privileged BuilderOps client. It independently loads the delivery manifest from
the target repository's protected default branch/base SHA, binds its hash plus `RepoRef` and current
PR head SHA to the attempt, and selects only a host-side credential mapping already authorized for
that `RepoRef`. Client-supplied policy is advisory and cannot weaken the server-side manifest or
broaden the credential. The executor holds the narrowest practical repo-scoped GitHub credential
and host-local model/subscription sessions; general MacBook clients and Product Runtime never
receive those credentials. Merge remains gated by the governing Issue, current PR SHA, required CI,
the repository review gate, repository protection, and a GitHub readback receipt. BuilderOps
orchestration cannot broaden repository permission or make a merge authoritative by itself.

Final validation produces an authorization fence over protected-base OID, delivery-manifest blob
OID/hash, PR head OID, `RepoRef`, and credential generation. The privileged effect must use a
GitHub-enforced conditional merge/ruleset or merge-queue path that rejects or invalidates the attempt
if the protected base or manifest changes after validation. Where GitHub cannot enforce that fence,
direct merge fails closed. A merge queue/merge group repeats policy, credential, SHA, CI, review, and
protection validation against the queue-selected base before GitHub may merge; a base advance or
policy revocation while the pre-effect attempt becomes durable produces a stale/revalidation receipt,
not a merge.

### D6 — Governed migration and one-way cutover

Cutover inventories **all** legacy BuilderOps, dispatcher, model-inquiry, and epic-run SQLite/JSONL/
JSON stores across relevant worktrees and hosts. Each source is frozen, hashed, and imported through
a versioned read-only adapter with provenance, count, conflict, and deduplication reports.

Live leases are not migrated as live authority. They expire or are tombstoned, and the PostgreSQL
control plane starts a new authority epoch with fresh fencing tokens. Idempotency keys, durable
events, artifact identities, and receipts are imported only under deterministic uniqueness and
conflict rules. A pre-import backup, dry run, production import receipt, and post-import count/hash
reconciliation are required.

> **Amended by A1 (2026-07-16):** the acknowledged-LSN/watermark recovery language in the paragraph
> below is superseded — post-activation recovery restores the latest archived point, reconciles
> external effects against GitHub, and starts a new fencing epoch before writes reopen. See
> `## Amendments`.

The cutover gate proves authenticated API clients and the Demerzel executor against PostgreSQL
before disabling every legacy writer. It then removes Product Runtime BuilderOps routes/startup,
archives the legacy sources read-only under an explicit retention policy, and verifies that no
production command can recreate SQLite authority. Before authority activation, rollback may restore
the pre-import PostgreSQL backup. After activation, rollback is forward-only: a compatible prior
service image may run against the current database, or a proved point-in-time recovery must restore
the full backup and continuous WAL through the recorded highest acknowledged LSN/receipt sequence.
Writes reopen only after independently recovering the decryption capability, restoring through the
watermark, and reconciling unknown effects. No post-activation snapshot rewind may discard an
accepted transition, idempotency result, receipt, outbox outcome, or fencing state. SQLite is never
reactivated as authority.

### D7 — Multi-repo provenance and promotion remain explicit

`RepoRef`, `scope`, `stack`, actor, source references, and schema version are mandatory on authority-
bearing records. TCD routing keys on `(repo, stack, task-class)` with global → stack → repo priors so
learning from one stack does not silently distort another. Existing data is backfilled where
evidence supports it; provenance is never invented. Plain non-authoritative quarantine is permitted
only for evidence-only material that cannot authorize, suppress, or cause replay of an idempotency
result, transition, lease, outbox operation, promotion, merge, or receipt. For authority-bearing
ambiguity, plain quarantine is insufficient: before activation the item must either be evidence-
resolved or imported as an explicit non-authoritative tombstone that preserves source hashes and
reserves every legacy identity, idempotency key, and external-operation key. A tombstone fails
retries as quarantined/manual-conflict and can never authorize an effect; possible prior effects
reconcile against GitHub before any successor operation. Cutover blocks until every authority-
bearing ambiguity is resolved or has those duplicate-preventing tombstone semantics.

Promotion is addressed to one consumer repo and requires that repo's normal acceptance path. A
BuilderOps standing in repo A is non-transitive to repo B. BuilderOpsReceipt projections may be
committed into consumer repos as evidence, but projections are not the control-plane authority.
The privileged executor re-resolves the repo-governed delivery manifest and host credential mapping,
then binds the effect to the same protected-base/manifest authorization fence through a GitHub-
enforced conditional or merge-queue path. It never treats a client-selected manifest or routing prior
as merge authority, and it never merges under policy that changed after final validation.

### D8 — Layer on ADR-0010; extraction triggers split runtime from source

ADR-0010 is not reopened. This ADR pluralizes the consumer-repo boundary and defines the independent
BuilderOps runtime. The prior T2 trigger has fired, so **deployment/process/data/credential
extraction is mandatory now**.

Source-repository extraction remains a separate future decision. Revisit it when any of these occur:

- a consumer must build BuilderOps without cloning this repository;
- independent release work is materially blocked by this repository's source lifecycle;
- a cross-boundary incident shows the package seam is insufficient;
- an external tenant is admitted; or
- governance/ownership requires a distinct repository.

## Decision status

Owner-settled on 2026-07-15:

1. permanent API-first control plane on Demerzel;
2. authenticated MacBook clients with no direct-database or local-authority fallback;
3. one PostgreSQL operational authority, with SQLite limited to migration/tests;
4. independent Compose/data/credential/release/health/backup trust zone;
5. Product Runtime owns no BuilderOps process, data, credential, or route;
6. Demerzel owns scoped review/merge orchestration; and
7. repo/GitHub delivery authority remains unchanged.

This ADR additionally makes the necessary multi-repo provenance, atomic outbox, migration, and
extraction consequences explicit. They become repository authority when this ADR lands on `main`.
Exact port, DNS name, credential technology, backup destination/retention numbers, schema layout,
and whether/when source code moves repositories are implementation or later trigger decisions; none
requires an owner decision before specification and backlog preparation.

## Consequences

- This ADR and its specification do not implement the service. Runtime work begins only from the
  bounded issue sequence in `docs/BUILDEROPS_CONTROL_PLANE/`.
- Issue #3686 and PR #3695 remain valuable defect and migration-inventory evidence, but host-stable
  SQLite is superseded as the production target.
- Issue #3603 remains the review/merge-orchestration workstream after PR #3620 merged. BCP-05 reuses
  that delivered implementation and migrates its dispatcher-SQLite authority after BCP-02/04; it
  does not reopen the merged PR or create another orchestrator. Host authentication is green and
  #3812 / PR #3813 are closed/merged; the installed-main low-risk pilot receipt remains the blocking
  host-enablement evidence.
- Issue #3690 remains the owner-doc enactment task and must be rewritten to reflect this topology
  after the BCP-06 cutover is proved.
- Current local/file-first BuilderOps records are not silently discarded. Migration preserves
  identity/provenance, limits plain quarantine to evidence-only material, and emits a reviewable
  duplicate-preventing tombstone/conflict receipt for unresolved authority-bearing inputs.
- Independent full-backup + continuous-WAL restore-through-watermark with independently recoverable
  key/KMS custody is a launch gate *(superseded by A1, 2026-07-16: the launch gate is a
  restore-from-backup drill + GitHub reconciliation + new-epoch activation)*. A persistent volume or
  snapshot alone is not recoverability.
- Product availability and BuilderOps availability are independent: either may be down without the
  other process owning or restarting it.

## Amendments

### A1 (2026-07-16, owner ruling) — Local-commit authority; asynchronous recovery durability; watermark regime removed

Owner clarification: the 2026-07-15 direction requested one stable, shared, Demerzel-owned database
as the single source of truth. It did not request synchronous off-host durability gating; that
machinery arrived with the revision, not with the owner's ask, and is removed as a requirement:

- D3's single-transaction atomicity (idempotency + guarded mutation + receipt + outbox intent in one
  PostgreSQL transaction) stands unchanged, as do fencing, deterministic reconciliation,
  readback-before-terminal, and unknown-not-failed semantics.
- An authority-bearing success response, idempotent replay, dependent authority transition, outbox
  claim, and external effect require the **local PostgreSQL commit only**. Every sentence in D2, D3,
  D4, and D6 that gates acknowledgement, outbox claim, executor effects, readiness, or write-reopen
  on an "independent recovery watermark" or "acknowledged LSN" is superseded.
- Recovery durability is **asynchronous**: scheduled encrypted full backups plus WAL archiving on an
  operator-chosen cadence to a target outside Demerzel's primary host and storage failure domains.
  Cadence and destination are implementation choices. A co-resident volume or snapshot alone still
  does not count as recovery durability, and independently recoverable key/KMS custody is unchanged.
  A structurally misconfigured recovery target (co-resident with the primary host/storage failure
  domain) fails readiness — misconfiguration stays fail-closed; a correctly configured but stalled or
  lagging archiving pipeline alerts loudly without gating acknowledgement.
- Accepted consequence (explicit): destructive loss of Demerzel's storage may lose the operational
  tail written since the last archived point. Recovery restores the latest backup/WAL point, starts a
  new lease/fencing authority epoch (D6 semantics), and **mandatorily reconciles external effects
  against GitHub** — which remains delivery authority per D1 — before the executor resumes external
  effects. No recovery path rewinds state that survived, and SQLite is never reactivated (unchanged).
- The launch gate becomes: a proved restore-from-backup drill to the latest archived point in an
  isolated target with Demerzel's host secret store unavailable, plus post-restore GitHub
  reconciliation and new-epoch activation. "Restore-through-acknowledged-LSN" is superseded
  accordingly. `docs/BUILDEROPS_CONTROL_PLANE/` is rewritten in the same change to match.

### A2 (2026-07-16, owner ruling) — Failure-domain separation on Demerzel; degraded-mode contract

Owner concern: a central database must not couple builder availability to the host's least stable
components. The observed instability lives in the shared container VM and Product stacks, not in the
host itself.

- The BuilderOps service and database must not share a container-VM/runtime failure domain with the
  `pkm-dev`/`pkm-test`/`pkm-prod` stacks. Product deploys, restarts, resource pressure, and
  container-VM lifecycle events must not be able to stop the builder plane. The BCP delivery selects
  a separate BuilderOps VM/container engine on Demerzel with the BuilderOps-only Compose project
  required by D4; a native host service is not an alternate target for this delivery. This
  strengthens D4's "own Compose project" to "own Compose project and failure domain".
- Degraded-mode contract (explicit): when the control plane is unreachable, repo-authorized direct
  git/GitHub work continues per D2 without fabricating BuilderOps state; orchestration-gated actions
  (claims, promotions, executor merges) wait. Control-plane unavailability is a loss of
  orchestration, not a work stoppage.
- BuilderOps `/healthz` joins the operator alerting path so control-plane outages are observed
  rather than discovered.

### A3 (2026-07-16) — CKM/CEG is a named migration source; ADR-0057 substrate clause superseded at cutover

ADR-0057 OD-K4 pins the Capability Evidence Graph to the SQLite BuilderOps substrate, and the
shipped `app/builderops/ckm/store.py` writes its rebuildable projection state and BuilderOps receipts
through that substrate, while D6's inventory did not name CKM.

- CKM/CEG tables are added to the D6 cutover inventory and to BCP-03's migration scope.
- Until cutover, CKM continues building on the SQLite substrate as a migration source; each schema
  addition is migration surface and must stay import-coverable.
- At cutover, ADR-0057 OD-K4's substrate clause is superseded by D3: the CEG lives in the BuilderOps
  PostgreSQL authority. ADR-0057's capability model and projection-only semantics are unchanged.

## Source docs and evidence

- `docs/adr/ADR-0010-builderops-vault-authority-boundary.md`
- `docs/architecture/SBS_OPERATING_MODEL.md §3`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/builderops/BUILDEROPS_VAULT_STORE.md`
- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`
- `docs/AGENT_ISSUE_DISPATCHER.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`
- `docs/audits/BUILDEROPS_CONTROL_PLANE_2026-07-15.md`
- Issue #3686 / PR #3695 (fragmented SQLite evidence; superseded target)
- Issue #3603 / merged PR #3620 (delivered Demerzel orchestration baseline; migration and host
  acceptance remain open)
- Issue #3690 (post-cutover owner-doc enactment)
