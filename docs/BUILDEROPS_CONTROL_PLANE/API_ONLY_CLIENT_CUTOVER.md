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

## Purpose

Current CLI, boundary, dispatcher, skills, automations, and SSH wrappers can construct/open local
SQLite or execute a remote CLI directly against Demerzel's database. All actual interactive clients
are on the MacBook and must cross one authenticated API boundary instead.

## What This Task Does

- provide a versioned client transport for records, worklogs, learnings, promotions, receipts,
  inquiries, tasks, leases, attempts, and status;
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

## Acceptance Criteria

- [ ] Representative MacBook commands for records, inquiry, task claim/heartbeat/complete, and
  receipts call the authenticated API and share one authority epoch.
  Verify: `tests/builderops/control_plane/test_api_clients.py::test_all_authority_commands_use_remote_api`.
- [ ] With the API unavailable or credentials invalid, mutation returns a typed error and creates no
  SQLite/JSONL/JSON authority or GitHub lease substitute.
  Verify: `tests/builderops/control_plane/test_api_clients.py::test_client_failure_never_creates_local_authority_fallback`.
- [ ] Production CLI/help/config exposes no direct database path or SSH-wrapped store mode; migration
  tooling retains explicit read-only source paths.
  Verify: `tests/governance/test_builderops_api_only_clients.py::test_production_clients_expose_no_direct_store_mode`.
- [ ] Repo-local BuilderOps/dispatcher skills and automations route authority-bearing operations
  through the client and document credential setup without secrets.
  Verify: `tests/governance/test_builderops_api_only_clients.py::test_skills_and_automations_route_through_authenticated_api`.
- [ ] A normal client credential cannot call privileged executor/merge operations or address a repo
  outside its granted scope.
  Verify: `tests/builderops/control_plane/test_service_auth.py::test_normal_client_cannot_use_executor_or_cross_repo_scope`.
- [ ] Static/runtime inventory rejects production imports/construction of SQLite stores outside the
  migration/test adapter allowlist.
  Verify: `tests/architecture/test_builderops_store_boundary.py::test_only_control_plane_data_layer_and_migration_adapters_access_stores`.

## Out of Scope

- executing merges;
- importing/finally freezing legacy stores;
- removing Product Runtime routes; and
- distributing credentials outside the owner-operated MacBook/Demerzel boundary.

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
