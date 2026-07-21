---
name: API-Only Client Cutover
description: Move every MacBook and automation client to the authenticated BuilderOps API.
task_id: BCP-04
source_anchor: docs/BUILDEROPS_CONTROL_PLANE/README.md :: Target boundary
parent_capability: BuilderOps independent control plane
prerequisites: [BCP-02]
depends_on: [INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md]
can_parallelize_with: []
---

# API-Only Client Cutover

Delivery status: the versioned authenticated control-plane client
(`app/builderops/control_plane/client.py`), its API-only CLI
(`python -m app.builderops.control_plane`), delivery-manifest routing, the
client-facing service routes, repo/executor scope enforcement, and the
store-boundary/governance gates are implemented in the development baseline by
#3791. The client transport ships non-authoritative: it targets whatever
BuilderOps service/store backend is configured, and BCP-06 owns activating
production authority and freezing the legacy SQLite writers. The legacy
direct-SQLite `app.dispatcher`/`app.builderops` CLIs remain until that
BCP-06 freeze; this slice adds the API-only client alongside them and gates the
control-plane package against local-store fallback.

## Purpose

Current CLI, boundary, dispatcher, skills, automations, and SSH wrappers can construct/open local
SQLite or execute a remote CLI directly against Demerzel's database. All actual interactive clients
are on the MacBook and must cross one authenticated API boundary instead.

## What This Task Does

- provide a versioned client transport for records, worklogs, learnings, promotions, receipts,
  inquiries, tasks, leases, attempts, and status;
- load the addressed repo's delivery manifest and select policy/TCD routing by
  `(RepoRef, stack, task-class)`, rejecting missing or ambiguous routing instead of borrowing
  another repo's defaults;
- configure base URL and scoped credential through host/user secret configuration, never repo files;
- migrate MacBook CLI wrappers, repo-local skills, automations, dispatcher commands, Signboard/read
  clients, model-inquiry launchers, and other authority-bearing callers to the transport;
- remove client-visible `--db-path` and direct SQLite construction from production commands;
- replace SSH-to-database-owning-CLI access with API calls;
- implement typed fail-closed unavailable/auth/scope/conflict/stale-lease errors and idempotent retry;
  and
- add an inventory gate that rejects production direct-store imports, SQLite defaults, or local
  authority creation outside migration/tests.

## Concretely

The existing BuilderOps/dispatcher commands keep task-level ergonomics but resolve a Demerzel API
URL and scoped user credential. Running them with the service unavailable returns a typed error and
leaves no database/file authority behind; a governance test inventories every production call site.

## Why This Matters

An authoritative server is ineffective if a client can silently reopen a worktree-local database.
This slice makes the API boundary a property of every real MacBook workflow rather than a deployment
recommendation.

## Source Anchors

- `docs/AGENT_ISSUE_DISPATCHER.md :: Operational Deployment`
- `docs/builderops/BUILDEROPS_VAULT_BOUNDARY.md :: Scope`
- `AGENTS.md :: Dispatcher policy`

## SBS Impact

Builder System client-boundary work. Product/runtime clients receive no new authority; the change
removes direct operational-store access from builder clients.

## Constraints

- Read-only stale caches, if any, are visibly non-authoritative and cannot feed mutation.
- API unavailability never falls back to SQLite, SSH direct-store CLI, or fabricated GitHub lease.
- Repo/GitHub direct actions that remain workflow-authorized do not fabricate BuilderOps receipts.
- Credential material is not logged, checked in, forwarded to Product, or shared across privilege
  scopes.
- Preserve command-level compatibility only where semantics remain API-authoritative; fail loudly
  for removed local-store flags.
- BCP-04 prepares clients; BCP-06 chooses the authoritative cutover moment.
- Every authority-bearing request names one `RepoRef`; no implicit current-directory repo inference
  may authorize a mutation.
- Client manifest/routing selection improves request formation but is never privileged authority;
  BCP-05 independently re-resolves protected-base policy and host credential binding.

## Acceptance Criteria

- [x] Representative MacBook commands for records, inquiry, task claim/heartbeat/complete, and
  receipts call the authenticated API and share one authority epoch.
  Verify: `tests/builderops/control_plane/test_api_clients.py::test_all_authority_commands_use_remote_api`.
- [x] With the API unavailable or credentials invalid, mutation returns a typed error and creates no
  SQLite/JSONL/JSON authority or GitHub lease substitute.
  Verify: `tests/builderops/control_plane/test_api_clients.py::test_client_failure_never_creates_local_authority_fallback`.
- [x] Production CLI/help/config exposes no direct database path or SSH-wrapped store mode; migration
  tooling retains explicit read-only source paths.
  Verify: `tests/governance/test_builderops_api_only_clients.py::test_production_clients_expose_no_direct_store_mode`.
- [x] Repo-local BuilderOps/dispatcher skills and automations route authority-bearing operations
  through the client and document credential setup without secrets.
  Verify: `tests/governance/test_builderops_api_only_clients.py::test_skills_and_automations_route_through_authenticated_api`.
- [x] A normal client credential cannot call privileged executor/merge operations or address a repo
  outside its granted scope.
  Verify: `tests/builderops/control_plane/test_service_auth.py::test_normal_client_cannot_use_executor_or_cross_repo_scope`.
- [x] Client policy loads the addressed repo's delivery manifest and routes by
  `(RepoRef, stack, task-class)`; missing/ambiguous manifests and cross-repo prior reuse fail closed.
  Verify: `tests/builderops/control_plane/test_delivery_manifest_routing.py::test_repo_stack_task_routing_is_explicit_and_non_transitive`.
- [x] Static/runtime inventory rejects production imports/construction of SQLite stores outside the
  migration/test adapter allowlist.
  Verify: `tests/architecture/test_builderops_store_boundary.py::test_only_control_plane_data_layer_and_migration_adapters_access_stores`.

## Out of Scope

- executing merges;
- importing/finally freezing legacy stores;
- removing Product Runtime routes; and
- distributing credentials outside the owner-operated MacBook/Demerzel boundary.

## Client setup (secret-safe)

Repo-local skills and automations route authority-bearing BuilderOps operations
through the authenticated API client, not a local store. The canonical entry
points are `python -m app.builderops.control_plane <command>` and the
`scripts/builderops_api_client.sh` automation wrapper. Both resolve their base
URL and scoped bearer credential from host-owned configuration only; no
credential is inlined in the repo, skills, docs, or logs:

- `BUILDEROPS_API_URL` — the control-plane base URL (required), reached over
  Tailscale, e.g. `https://demerzel.<tailnet>.ts.net:<port>`.
- `BUILDEROPS_API_TOKEN_FILE` — path to a host secret file holding the scoped
  bearer token (preferred), or
- `BUILDEROPS_API_TOKEN` — the scoped bearer token in the host environment.

Exactly one of `BUILDEROPS_API_TOKEN_FILE` or `BUILDEROPS_API_TOKEN` is set by
the host. A credential's authority is fail-closed by default: a credential with
no `repositories` list and no explicit `all_repositories: true` opt-in can
address NO repository. A normal client credential is scoped to its granted
repositories and cannot call the privileged executor/outbox operations; the
executor holds the only credential with the explicit `all_repositories: true`
opt-in and the only `outbox:write` scope. With the service unavailable or the
credential rejected, the client and wrapper fail closed with a non-zero exit and
create no local SQLite/JSONL/JSON authority and no fabricated GitHub lease.

Every mutating CLI command requires `--delivery-manifest-dir` and
`--task-class` and resolves delivery-manifest `(RepoRef, stack, task-class)`
routing (`app.builderops.control_plane.routing`) before dispatch. Missing,
ambiguous, stale cached/prior-route, or cross-repository manifests/routes fail
closed before a client is constructed; every invocation reloads the addressed
repository's manifest rather than reusing a prior route. Temporal
base-SHA/manifest-hash freshness remains BCP-05 protected-base authority. The
resolved policy remains advisory request shaping
(for example, a `ttl_seconds` default), never privileged authority; BCP-05
still independently re-resolves protected-base policy and credential binding.
Promotion updates pass the caller-supplied fenced `--lease` object through the
same API boundary; the store rejects missing or stale lease evidence without a
local or fabricated fallback.

## How to Verify (Pre-Merge)

- run client contract tests against a disposable BCP-02 service;
- test network timeout, 401/403, idempotent response loss, and stale fencing token;
- inspect all `SqliteBuilderOpsStore`, dispatcher store, `--db-path`, and SSH-wrapper call sites; and
- run governance skill tests plus `ruff check app tests`.

## Related Docs

- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`
- `docs/AGENT_ISSUE_DISPATCHER.md`

## Related GitHub Issues

- [#3791](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3791), blocked on BCP-02.
- Consumes, but does not duplicate, repo-explicit targeting work in issue #3174.
