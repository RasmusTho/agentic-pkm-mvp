State: Accepted (owner decision, 2026-07-15). Re-scopes BuilderOps as an ecosystem-wide, API-first enabling system with an independent Demerzel deployment and one PostgreSQL operational authority. Docs/governance decision only; no runtime behavior changes here.
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

GitHub cannot participate in that transaction. A privileged executor claims the durable outbox
intent, performs the external effect with deterministic reconciliation, reads GitHub back, and then
records the observed outcome in a new transaction and receipt. A timed-out call is unknown, never
assumed failed; retries reconcile before repeating. Terminal success is never inferred solely from
the attempted call.

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
- scheduled backup, retention, restore tooling, and a proved restore drill; and
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

The executor is a privileged BuilderOps client. It holds the narrowest practical repo-scoped GitHub
credential and host-local model/subscription sessions; general MacBook clients and Product Runtime
never receive those credentials. Merge remains gated by the governing Issue, current PR SHA,
required CI, the repository review gate, repository protection, and a GitHub readback receipt.
BuilderOps orchestration cannot broaden repository permission or make a merge authoritative by
itself.

### D6 — Governed migration and one-way cutover

Cutover inventories **all** legacy BuilderOps, dispatcher, model-inquiry, and epic-run SQLite/JSONL/
JSON stores across relevant worktrees and hosts. Each source is frozen, hashed, and imported through
a versioned read-only adapter with provenance, count, conflict, and deduplication reports.

Live leases are not migrated as live authority. They expire or are tombstoned, and the PostgreSQL
control plane starts a new authority epoch with fresh fencing tokens. Idempotency keys, durable
events, artifact identities, and receipts are imported only under deterministic uniqueness and
conflict rules. A pre-import backup, dry run, production import receipt, and post-import count/hash
reconciliation are required.

The cutover gate proves authenticated API clients and the Demerzel executor against PostgreSQL
before disabling every legacy writer. It then removes Product Runtime BuilderOps routes/startup,
archives the legacy sources read-only under an explicit retention policy, and verifies that no
production command can recreate SQLite authority. Rollback restores the previous PostgreSQL release
and database backup; it never reactivates SQLite as authority.

### D7 — Multi-repo provenance and promotion remain explicit

`RepoRef`, `scope`, `stack`, actor, source references, and schema version are mandatory on authority-
bearing records. TCD routing keys on `(repo, stack, task-class)` with global → stack → repo priors so
learning from one stack does not silently distort another. Existing data is backfilled where
evidence supports it and quarantined as `unknown`/unresolved where it does not; provenance is never
invented.

Promotion is addressed to one consumer repo and requires that repo's normal acceptance path. A
BuilderOps standing in repo A is non-transitive to repo B. BuilderOpsReceipt projections may be
committed into consumer repos as evidence, but projections are not the control-plane authority.

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
  does not reopen the merged PR or create another orchestrator. The host remains disabled until the
  separately recorded interactive keyring authorization and pilot receipt exist.
- Issue #3690 remains the owner-doc enactment task and must be rewritten to reflect this topology
  after the BCP-06 cutover is proved.
- Current local/file-first BuilderOps records are not silently discarded. Migration preserves
  identity and provenance or emits a reviewable quarantine/conflict receipt.
- Independent backup/restore is a launch gate. A persistent volume alone is not a backup.
- Product availability and BuilderOps availability are independent: either may be down without the
  other process owning or restarting it.

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
