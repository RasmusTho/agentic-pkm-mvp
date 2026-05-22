State: SoT v5.6 baseline (audit pass 2026-05-18: residual-caller map and cleanup follow-ups added; package status unchanged).
Doc role: Reference
Authority: Canonical map of app/ package status for the current baseline; use it to determine whether a package is canonical runtime, deprecated, planned, or production support. Wins over ad-hoc comments or import graphs on current-state package classification questions.

# Code Inventory

Status inventory for the `app/` package tree. Use this document before extending, removing, or reclassifying any package.

## Package Status Vocabulary

| Status | Meaning |
| --- | --- |
| `canonical` | Active, owned runtime path. Extend freely. CI and tests cover this package. |
| `deprecated` | Legacy surface retained for compatibility. Do not add new callers or extend functionality. Schedule for removal when the replacement surface is stable. |
| `planned` | Seam reserved for a future capability. Do not delete as dead code. Do not extend beyond the minimal scaffold already present. |
| `support` | Production-support package (auth, middleware, config, tracing, etc.). Active but not part of the primary runtime data path. Extend with care; keep bounded. |

## Canonical Runtime Paths

Primary runtime packages that form the active data path. These are the packages the system is built on and are safe to extend.

| Package | Role |
| --- | --- |
| `app/api` | FastAPI HTTP surface and routes |
| `app/cli` | CLI entrypoints for operator commands |
| `app/watcher` | Registry watcher (file change detection) |
| `app/workers` | Background worker loop (outbox consumer, indexing) |
| `app/events` | Event envelope definitions |
| `app/outbox` | DB outbox: write, consume, and ack |
| `app/settings` | Settings compiler and registry |
| `app/health` | Health check surface |
| `app/vault` | Vault abstraction (path resolution, UUID, companion notes) and Vault Action Layer (governed artifact placement and lifecycle) |
| `app/ingest` | Note ingestion pipeline |
| `app/search` | Hybrid search surface |
| `app/db` | Database session and migration bootstrap |
| `app/index` | Index management |
| `app/indexer` | Indexing logic |
| `app/retrieval` | Typed retrieval capability wrapper |
| `app/dispatcher` | Agent Issue Dispatcher (local claim/lease coordination) |
| `app/embedding_config` | Embedding provider configuration |

## Deprecated Packages

These packages are retained for compatibility or historical reference. **Do not extend.** Do not add new callers. Schedule for removal when the replacement surface is ready.

| Package | Replacement direction |
| --- | --- |
| `app/agent` | Superseded by `app/agents` and the orchestrator runtime. No new callers. |
| `app/plugins` | Plugin adapter pattern replaced by the MCP adapter and component entrypoints. No new callers. |
| `app/store` | Superseded by `app/stores` and bounded service/outbox patterns. No new callers. |
| `app/stores` | Transitional store layer. Migrate callers toward service + outbox boundaries. No new extensions. |

## Planned Packages

These packages are seams reserved for future capabilities. They contain minimal scaffold or stub runtimes. **Do not delete as dead code.** Do not extend beyond what a governing spec issue authorizes.

| Package | Governing capability |
| --- | --- |
| `app/sync` | Future multi-device sync surface; reserved seam, not yet runtime-active. |
| `app/orientation` | v6.0 orientation capability (finding/reorienting); minimal scaffold runtime shipped. See `docs/FINDING_AND_REORIENTING/README.md`. |
| `app/resurfacing` | v6.0 resurfacing capability (salience-driven recall); minimal scaffold runtime shipped. See `docs/FINDING_AND_REORIENTING/README.md`. |

## Known legacy/prototype candidates

Audit pass 2026-05-18 against the `main` baseline. For each deprecated package: residual callers, blocker conditions, and recommended cleanup scope.

### `app/agent`

**Files (10):** `actions.py`, `execute.py`, `graph.py`, `interestingness.py`, `models.py`, `nodes.py`, `plan.py`, `reflect.py`, `repository.py`, `service.py`

**Residual callers outside `app/agent/`:**

| File | Symbol imported | Notes |
| --- | --- | --- |
| `app/health.py` | `AgentRepository` | Canonical health package; must be decoupled before removal |
| `app/plugins/base.py` | `AgentRepository` | Conditional import inside deprecated `app/plugins`; co-removed with `app/agent` |
| `run_agent.py` | `invoke` from `app.agent.graph` | Top-level entrypoint script; must be retired before package removal |
| `tests/stub_repositories.py` | `InterestingnessResult` | Shared test helper; update when removing `app/agent` |
| `tests/test_agent_service.py` | `AgentService` | Direct test of deprecated service; remove with package |

**Doc references:** `docs/CODE_INVENTORY.md` (this file), `docs/legacy/ALIGNMENT.md`, `docs/legacy/PROJECT_OVERVIEW.md`

**Removal blocker:** `app/health.py` and `run_agent.py` must be decoupled first. `app/plugins` can be co-removed in the same slice.

**Recommended cleanup:** One bounded slice — decouple `app/health.py` from `AgentRepository`, retire `run_agent.py`, remove `app/agent` and `app/plugins` and their tests. See [Cleanup follow-ups](#cleanup-follow-ups).

---

### `app/plugins`

**Files (5):** `base.py`, `loader.py`, `retriever.py`, `web_get.py`, `write_note.py`

**Residual callers outside `app/plugins/`:**

| File | Notes |
| --- | --- |
| `app/agent/execute.py`, `app/agent/interestingness.py`, `app/agent/reflect.py`, `app/agent/service.py` | All within deprecated `app/agent`; no canonical callers |
| `tests/test_agent_service.py` | Test of deprecated `app/agent`; co-removed |

**No canonical callers remain.** Safe to remove together with `app/agent`.

---

### `app/store`

**Files (5):** `membership_store.py`, `object_store.py`, `relation_index.py`, `vector_index.py`, `vector_store.py`

**Current role:** `object_store.py` is a compatibility shim — it delegates actual storage to `app/stores` (imports `get_object_store`, `resolve_store_backend`) but re-exports `DomainObject`, `ObjectStore`, and index types that callers import directly.

**Residual callers outside `app/store/` (production code):**

`app/agents/` (chunker, citation_checker, classifier, deduper, indexer, normalizer, panel, panel_agent/agent+execution+runtime, planner, projector, reviewer, set_evaluator), `app/cli/index_rebuild.py`, `app/cli/smoke.py`, `app/domain/plan.py`, `app/indexer/consumer.py`, `app/ingest/api.py`, `app/ingest/vault_alpha.py`, `app/orchestrator/executor.py`, `app/promotion/consumer.py`, `app/services/indexer.py`, `app/watcher/vault_watcher.py`

**Test callers:** Very broad — `tests/fakes/`, `tests/agents/`, `tests/cli/`, `tests/e2e/`, `tests/indexer/`, `tests/panel/`, `tests/quality_wave/`, `tests/runtime/`, `tests/stores/`, `tests/test_domain_write_boundary.py`, `tests/test_object_store_contract.py`, `tests/test_relation_index_contract.py`, `tests/test_vector_index_contract.py`

**Doc references:** `docs/CODE_INVENTORY.md`, `docs/STATUS.md`, `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md`

**Removal blocker:** Very broad caller surface across canonical packages. Migration requires relocating `DomainObject` and type aliases to a canonical home (e.g. `app/domain` or `app/stores`) and updating all callers. Too large for a single slice.

**Recommended cleanup:** One issue per package area (agents, ingest+indexer, cli, tests/fakes). Do not attempt in a single PR. See [Cleanup follow-ups](#cleanup-follow-ups).

---

### `app/stores`

**Files (9):** `base.py`, `db_health.py`, `decisions.py`, `memory.py`, `pg.py`, `plan_store.py`, `postgres.py`, `provider.py`, `relation_index.py`

**Current role:** Transitional store layer; many canonical packages call it directly. Not ready for removal.

**Removal blocker:** Active canonical caller surface. Retirement requires service/outbox boundary migration work that is out of scope here.

**Recommended cleanup:** Track broader `app/stores` retirement separately, after the `app/store` caller migration is complete.

---

## Planned/future packages that should not be deleted as dead code

The following packages contain minimal scaffold or reserved seams. They are **not** dead code. Do not delete them without a governing spec issue authorizing the removal or replacement.

| Package | Why it must not be deleted | Governing doc |
| --- | --- | --- |
| `app/sync` | Reserved seam for future multi-device sync; no runtime activity is not a signal of abandonment | No governing spec yet; hold until one exists |
| `app/orientation` | v6.0 orientation capability with minimal scaffold runtime; has shipped stub | `docs/FINDING_AND_REORIENTING/README.md` |
| `app/resurfacing` | v6.0 resurfacing capability with minimal scaffold runtime; has shipped stub | `docs/FINDING_AND_REORIENTING/README.md` |

**Audit result:** None of these packages have callers in deprecated code. No risk of being pulled into legacy cleanup. Classification confirmed as `planned`.

---

## Cleanup follow-ups

Issues recommended by the 2026-05-18 audit. Each is bounded and safe to implement independently. Do not start deletion before the corresponding issue is created and scoped.

| Issue | Scope | Blocker |
| --- | --- | --- |
| Remove `app/agent` + `app/plugins` | Decouple `app/health.py` from `AgentRepository`, retire `run_agent.py`, delete both packages and their tests | None beyond the decoupling work above |
| Migrate `app/store` callers — agents area | Update `app/agents/**` to import from `app/stores` or canonical boundaries instead of `app.store.object_store` | `DomainObject` must be re-exported from a stable location first |
| Migrate `app/store` callers — ingest + indexer area | Update `app/ingest/`, `app/indexer/`, `app/services/indexer.py`, `app/promotion/consumer.py` | Same as above |
| Migrate `app/store` callers — cli + domain area | Update `app/cli/`, `app/domain/plan.py`, `app/orchestrator/executor.py`, `app/watcher/vault_watcher.py` | Same as above |
These issues are not yet created in GitHub. When created, they should be `type:refactor`, scoped to one area each, and carry explicit `Verify:` targets before being marked `agent:ready`.

---

## Support Packages

Production-support packages active in the runtime but not on the primary data path. Extend with care; keep changes bounded to their named concern.

Notable support packages include: `app/auth`, `app/capture`, `app/chat`, `app/components`, `app/config`, `app/context_dimensions`, `app/deps`, `app/diarization`, `app/domain`, `app/eval`, `app/fitness`, `app/guardrails`, `app/io`, `app/jobs`, `app/knowledge`, `app/langgraph`, `app/llm`, `app/mcp`, `app/media`, `app/memory`, `app/middleware`, `app/obs`, `app/observability`, `app/orchestrator`, `app/planner`, `app/policy`, `app/ports`, `app/promotion`, `app/quality`, `app/reasoning`, `app/release_channels`, `app/runtime`, `app/schemas`, `app/services`, `app/tracing`, `app/web`, `app/write_guard`.

Agent surfaces: `app/agents`, `app/a2a`.

Infrastructure packages (not on the primary data path; extend only under their named concern):

| Package | Role |
| --- | --- |
| `app/alembic` | Database migration scripts managed by Alembic. |
| `app/scripts` | Operational scripts for local and production administration. |
| `app/testing` | Shared test fixtures, factories, and helpers used across the test suite. |
