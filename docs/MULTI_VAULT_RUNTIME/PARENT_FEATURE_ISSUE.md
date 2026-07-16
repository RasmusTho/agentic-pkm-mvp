# Parent feature issue — multi-vault runtime selection

State: Active future-state specification. GitHub issue **#2143** is the blocked parent validation
hub. It is not an implementation pickup and must never carry `agent:ready`.

## Context

The shipped runtime has no-vault and one-active-vault behavior, an app-local known-vault seed, and
a v0 ActiveContextSet adapter, but still binds most work through a process-global selection. The
owner direction in #2143 is one instance managing several content vaults, including explicit
default, request/session selection, and non-authoritative dimensions. This parent validates the
bounded delivery defined in `docs/MULTI_VAULT_RUNTIME/`; it is never directly implemented.

TCD route: Sol/high–xhigh for registry migration, resolution authority, ActiveContextSet,
concurrency, and background lifecycle design; Terra/medium–high only for mechanically bounded
consumer migration and validation after those contracts are frozen.

## Scope

- Establish a durable instance-local registry keyed by stable binding identity while preserving
  logical-vault and local-clone identity.
- Add an explicit default with one-time last-active compatibility migration and fail-closed
  precedence.
- Version request/session ActiveContextSet resolution with immutable context generations and
  full-context isolation.
- Add non-authoritative dimensions over binding identities.
- Migrate request and background production consumers, reusing #3163 for watcher/settings rebind.
- Prove no-vault/one-vault compatibility, update owner docs/debt, and assemble the parent ledger.

## Source Anchors

- `docs/MULTI_VAULT_RUNTIME/README.md :: Capability boundary`
- `docs/contracts/ACTIVE_CONTEXT_SET.md :: Multi-Vault Runtime V1 Decision`
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md :: Topology rules`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Future Multi-Vault`
- `app/vault/app_local.py :: AppLocalSettings / KnownVaultRef`
- GitHub issue #2143

## SBS Impact

- Primary subsystem: WSP
- Secondary subsystem(s): GOV, SFC, PDM, EBF, HKA, RCA, HIX, OEF
- Write class: mechanical durable instance registry/default/dimension/background intent; existing governed HKA writes only
- Authority impact: selection/grouping never grants authority; every binding is independently GOV-authorized
- Persistence impact: versioned instance-local Markdown registry plus lossless/compatible migrations
- Derived/rebuildable impact: context snapshots, caches, retrieval results, lifecycle instances, and health projections remain rebuildable
- Human knowledge impact: content stays in its vault; cross-vault work preserves source/target attribution
- Memory impact: memory/retrieval context becomes explicitly binding- and context-scoped
- Retrieval/context impact: public context generalizes from scalar global vault to immutable zero/one/many ActiveContextSet
- Sync/deployment impact: explicit cross-process binding handoff; env/mount paths remain bootstrap machinery
- External boundary impact: raw paths and client correlation IDs are not identity or authority
- New or changed contract: ActiveContextSet runtime version, registry/default/dimension selection model, lifecycle binding contract
- Owner-doc impact: final child updates architecture, context/topology, settings/environment, and docs index surfaces
- Transition debt impact: reduces D1/D13/D14; any retained adapter must be explicitly re-baselined
- Fitness rule impact: adds full-context isolation, producer/preflight, production-consumer, and single-vault compatibility gates

## Constraints

- Parent #2143 remains `agent:blocked`, is never claimed, and closes only through the final ledger.
- Single-vault/no-vault behavior remains the reversible floor; explicit invalid selection never
  silently falls back.
- `vault_binding_id`, logical `vault_id`, `local_instance_id`, paths/mounts, dimensions, sessions,
  and instances remain separate concepts.
- Dimensions and selection cannot upgrade authority; GOV evaluates every binding.
- Reuse #2566 and #3156/#3163 scope rather than creating parallel hubs or duplicate issues.
- Every persisted precondition updates all producers, migrations, fixtures, and fail-loud preflights.
- GitHub receipts redact host paths, secrets, note content, and raw binding payloads.

## Acceptance Criteria

- [ ] The authoritative capability directory decomposes registry, default, request/session active
  selection, dimensions, request/background migration, single-vault preservation, and final
  promotion into independently verifiable tasks.
  - Verify: doc writeback at `docs/MULTI_VAULT_RUNTIME/README.md :: Implementation tasks`
- [ ] Registry identity and persistence preserve same-logical-vault clones, shipped corrupt-registry
  picker recovery, and lossless producer migration.
  - Verify: `tests/instance/test_vault_registry_migration.py::test_parent_registry_acceptance`
- [ ] Explicit default resolution and persistence survive process/container restart without being
  replaced by mutable last-active selection.
  - Verify: `tests/instance/test_default_vault_resolution.py::test_legacy_last_active_materializes_default_once`
  - Verify: `tests/integration/test_vault_registry_container_durability.py::test_default_survives_recreate_after_mvr02`
- [ ] Two bearer-capability sessions can concurrently use distinct vault contexts, and
  same-binding/same-generation sessions with different cognitive scope/sphere/situated identity or
  selection capability cannot share cache state. Endpoint action/permission remains a separate GOV
  input and no unsupported multi-user identity is claimed.
  - Verify: `tests/integration/test_multi_vault_request_isolation.py::test_parent_request_context_acceptance`
- [ ] Dimensions resolve explicit binding sets without becoming authority, while background work
  uses its distinct durable, re-authorized intent set and reuses #3163.
  - Verify: `tests/integration/test_multi_vault_lifecycle_and_dimension.py::test_parent_dimension_background_acceptance`
- [ ] No-vault and one-vault startup, picker, last-active restart migration, watcher idle/bind,
  requests, CLI/agents/MCP, receipts, and test-channel bootstrap preserve shipped behavior.
  - Verify: `tests/integration/test_single_vault_compatibility.py::test_existing_single_vault_journey_is_preserved`
- [ ] Every child receipt and parent Verify target is proven on merged `origin/main`; after MVR-08
  merges, the isolated test-channel journey records a redacted receipt on #2143 for two vault
  bindings, two sessions, one dimension read, one governed write, and truthful background health on
  that exact merged SHA. Owner docs and transition debt match shipped reality with
  #2566/#3156/#3163 reconciled.
  - Verify: runtime receipt on GitHub issue `#2143` + doc writeback at
  `docs/MULTI_VAULT_RUNTIME/PROMOTE_MULTI_VAULT_RUNTIME_TRUTH.md :: Acceptance Criteria`

## Out of Scope

- Implementing directly from the parent.
- The #2566 overlay UI, unrelated Settings Spine children, arbitrary/manual semantic cross-vault
  consolidation, multi-writer-policy redesign, distributed federation, or production promotion.
  MVR-07B's deterministic governed reduction package is in scope solely to prove topology-rule-6
  reversibility without merging meaning, attribution, or receipts.
- Treating dimensions as roles/confidentiality/sphere/topology authority.

## Suggested Validation

- Run every child task's `## How to Verify (Pre-Merge)` commands on its PR.
- On a clean detached worktree whose `HEAD` equals fetched `origin/main`, run every exact parent and
  capability target listed at
  `docs/MULTI_VAULT_RUNTIME/PROMOTE_MULTI_VAULT_RUNTIME_TRUTH.md :: How to Verify (Post-Merge Closure)`;
  branch-local or stale evidence is not a closure receipt.
- `python3 scripts/docs_guard.py` and `pytest -q tests/architecture/test_docs_index.py`.
- Live REST audit of #2143, every child/PR, #2566, #3156, and #3163.

## Source Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/contracts/ACTIVE_CONTEXT_SET.md`
- `docs/CONCEPTS/VAULT_TOPOLOGY_CONTRACT.md`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/architecture/SBS_TRANSITION_DEBT.md`

## Applies learning (optional)

Preserves the invariant→producers rule from #1991/#1997, the no-silent-fallback deliveries
#2003/#2311, corrupt-registry picker recovery #2185, and merged-head receipt discipline.

## Implementation Tasks

| Order | Task | Issue | Status |
| --- | --- | --- | --- |
| 01A | [ESTABLISH_INSTANCE_VAULT_REGISTRY — core](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/ESTABLISH_INSTANCE_VAULT_REGISTRY.md#bounded-implementation-issue-decomposition) | [#3853](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3853) | ready for pickup; specification merged and strict validation passed |
| 01B | [ESTABLISH_INSTANCE_VAULT_REGISTRY — durability/ownership/basic rollback](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/ESTABLISH_INSTANCE_VAULT_REGISTRY.md#bounded-implementation-issue-decomposition) | [#3854](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3854) | blocked on #3853 |
| 01C | [ESTABLISH_INSTANCE_VAULT_REGISTRY — rollback](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/ESTABLISH_INSTANCE_VAULT_REGISTRY.md#bounded-implementation-issue-decomposition) | [#3855](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3855) | blocked on #3854 |
| 02 | [RESOLVE_INSTANCE_DEFAULT_VAULT](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/RESOLVE_INSTANCE_DEFAULT_VAULT.md) | [#3856](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3856) | blocked on #3855 |
| 03 | [VERSION_ACTIVE_CONTEXT_SELECTION](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/VERSION_ACTIVE_CONTEXT_SELECTION.md) | [#3857](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3857) | blocked on #3856 |
| 04 | [GROUP_VAULT_BINDINGS_BY_DIMENSION](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/GROUP_VAULT_BINDINGS_BY_DIMENSION.md) | [#3858](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3858) | blocked on #3857 |
| 05A | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT — persistence](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md#bounded-implementation-issue-decomposition) | [#3859](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3859) | blocked on #3858 |
| 05B | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT — ingress/reads](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md#bounded-implementation-issue-decomposition) | [#3860](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3860) | blocked on #3859 and #3163 |
| 05C | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT — governed writes](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md#bounded-implementation-issue-decomposition) | [#3861](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3861) | blocked on #3860 |
| 05D | [ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT — outbox/delivery](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md#bounded-implementation-issue-decomposition) | [#3862](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3862) | blocked on #3861 |
| 06A | [BIND_BACKGROUND_LIFECYCLES — intent/authority](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md#bounded-implementation-issue-decomposition) | [#3863](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3863) | blocked on #3862 |
| 06B | [BIND_BACKGROUND_LIFECYCLES — bridge handoff](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md#bounded-implementation-issue-decomposition) | [#3864](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3864) | blocked on #3863 and #3163 |
| 06C | [BIND_BACKGROUND_LIFECYCLES — supervision](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md#bounded-implementation-issue-decomposition) | [#3865](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3865) | blocked on #3864 |
| 06D | [BIND_BACKGROUND_LIFECYCLES — queued work/aggregate proof](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/BIND_BACKGROUND_LIFECYCLES.md#bounded-implementation-issue-decomposition) | [#3866](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3866) | blocked on #3865 |
| 07A | [PRESERVE_SINGLE_VAULT_MIGRATION — compatibility/smoke](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/PRESERVE_SINGLE_VAULT_MIGRATION.md#bounded-implementation-issue-decomposition) | [#3867](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3867) | blocked on #3858 and #3859–#3866 |
| 07B | [PRESERVE_SINGLE_VAULT_MIGRATION — governed reduction](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/PRESERVE_SINGLE_VAULT_MIGRATION.md#bounded-implementation-issue-decomposition) | [#3868](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3868) | blocked on #3867 |
| 08 | [PROMOTE_MULTI_VAULT_RUNTIME_TRUTH](https://github.com/RasmusTho/agentic-pkm-mvp/blob/main/docs/MULTI_VAULT_RUNTIME/PROMOTE_MULTI_VAULT_RUNTIME_TRUTH.md) | [#3869](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3869) | blocked on #3867–#3868; final validation child |

All child Issue numbers above were populated after specification PR #3728 merged and each contract
passed strict section, Verify-marker, SBS, and source-anchor validation. No parallel parent or child hub is created for #2566, #3156/#3163,
#2003/#2311, #2356, or ADR-0055.

## Verification Path

Each child PR executes its declared production-call-site `Verify:` targets, passes CI and an
independent review gate, merges, and posts a receipt to #2143 containing merged SHA, exact tests,
owner-doc/debt result, and residual dependency state. The coordinator then refreshes `origin/main`,
live Issues/PRs, and dispatcher truth before the next pickup.

## Validation / Acceptance Path

#2143 closes only after:

1. issues 01A–01C, tasks 02–04, issues 05A–05D, 06A–06D, 07A–07B, and 08 have merged with no residual `agent:*` labels;
2. all capability-acceptance targets in `README.md` pass on merged `origin/main`;
3. #2566 and #3156/#3163 are reconciled without duplicated scope and their state is truthful;
4. architecture, ActiveContextSet, topology, settings/context, environment, transition-debt, and
   DOCS_INDEX owner surfaces describe shipped reality;
5. the parent contains one receipt per child plus a final ledger mapping every parent AC to merged
   evidence.

If a real device/channel operation remains, task 08 records the exact operator command and expected
receipt. The parent stays blocked until that evidence exists; it is never converted into an
implementation issue.
