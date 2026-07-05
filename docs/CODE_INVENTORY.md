State: SoT v5.6 baseline (audit pass 2026-05-18: residual-caller map and cleanup follow-ups added; package status unchanged). Updated 2026-05-22: `app/agent`, `app/plugins`, and `run_agent.py` removed (#1171). Updated 2026-06-24: `api/app.py` (fake WS stub) and `app/indexer/runner.py` (disabled stub) deleted; `app/obs/` merged into `app/observability/`; `app/memory/` renamed to `app/memory_kv/` (#2480).
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

### `app/agent` — **Removed** (#1171, 2026-05-22)

`app/agent`, `app/plugins`, `run_agent.py`, `tests/test_agent_service.py`, and `tests/stub_repositories.py` were removed in this slice. `app/health.py` was decoupled from `AgentRepository` in the same change.

---

### `app/store`

**Files (3):** `membership_store.py`, `relation_index.py`, `vector_index.py`

**Removed (KERNEL-03, #2765):** `object_store.py` and `vector_store.py` — the legacy write generation is gone. `DomainObject` and the `ObjectStore` facade are owned by `app/objects` and write only through the `app.stores` provider seam, with no silent in-memory fallback. Guard: `tests/architecture/test_single_store_writer.py`.

**Current role:** `relation_index.py` and `vector_index.py` are compatibility shims re-exported through `app.objects`; `membership_store.py` is a direct-DB membership writer used by `app/agents/projector`.

**Stable canonical import boundary (shipped v5.6.1+):** `app/objects` — the canonical home for `DomainObject`, `ObjectStore`, `RelationEdge`, `GraphSlice`, `RelationIndex`, `ScoredNeighbor`, and `VectorIndex`. New code must import from `app.objects`.

**Residual callers outside `app/store/` (production code):** `app/objects/__init__.py` (re-exports the `relation_index`/`vector_index` shim types), `app/agents/projector/agent.py` (`membership_store.save_membership`).

**Test callers:** `tests/test_relation_index_contract.py`, `tests/test_vector_index_contract.py`, `tests/fakes/fake_relation_index.py`, `tests/fakes/fake_vector_index.py`, `tests/architecture/test_module_layout.py`.

**Doc references:** `docs/CODE_INVENTORY.md`, `docs/STATUS.md`, `docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md`

**Removal blocker:** The remaining shim types (`RelationIndex`, `VectorIndex`) are the contract types re-exported by `app.objects`; relocating them and migrating `membership_store` are bounded follow-ups.

**Recommended cleanup:** One bounded issue to move `relation_index.py`/`vector_index.py` types into `app/objects` and migrate `membership_store`; then delete the package. See [Cleanup follow-ups](#cleanup-follow-ups).

---

### `app/stores`

**Files (9):** `base.py`, `db_health.py`, `decisions.py`, `memory.py`, `pg.py`, `plan_store.py`, `postgres.py`, `provider.py`, `relation_candidates.py`

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
| ~~Remove `app/agent` + `app/plugins`~~ | **Done** — removed in #1171 (2026-05-22) | — |
| ~~Migrate `app.store.object_store` callers + delete the legacy writers~~ | **Done** — KERNEL-03 (#2765): callers import `app.objects`; `object_store.py`/`vector_store.py` deleted | — |
| Migrate remaining `app/store` shims | Move `relation_index.py`/`vector_index.py` contract types into `app/objects`; migrate `membership_store.py` off direct DB writes; delete `app/store` | Bounded; guard tests in `tests/architecture/` must be updated in the same change |
These issues are not yet created in GitHub. When created, they should be `type:refactor`, scoped to one area each, and carry explicit `Verify:` targets before being marked `agent:ready`.

---

## Support Packages

Production-support packages active in the runtime but not on the primary data path. Extend with care; keep changes bounded to their named concern.

Notable support packages include: `app/auth`, `app/capture`, `app/chat`, `app/components`, `app/config`, `app/context_dimensions`, `app/deps`, `app/diarization`, `app/domain`, `app/eval`, `app/fitness`, `app/guardrails`, `app/io`, `app/jobs`, `app/knowledge`, `app/knowledge_acquisition` (Knowledge Acquisition Platform source plugins + raw-record persistence; `youtube_url` plugin fetch shipped in KA-01, #2796; deterministic raw→normalized stage with rolling-cue dedup shipped in KA-03, #2798), `app/langgraph`, `app/llm`, `app/mcp`, `app/media`, `app/memory_kv` (KV memory substrate; renamed from `app/memory` in #2480), `app/middleware`, `app/observability` (now includes `log.py` and `redaction.py` merged from former `app/obs/` in #2480), `app/orchestrator`, `app/planner`, `app/policy`, `app/ports`, `app/promotion`, `app/quality`, `app/reasoning`, `app/release_channels`, `app/runtime`, `app/schemas`, `app/services`, `app/tracing`, `app/web`, `app/write_guard`.

Agent surfaces: `app/agents`, `app/a2a`.

Infrastructure packages (not on the primary data path; extend only under their named concern):

| Package | Role |
| --- | --- |
| `app/alembic` | Database migration scripts managed by Alembic. |
| `app/scripts` | Operational scripts for local and production administration. |
| `app/testing` | Shared test fixtures, factories, and helpers used across the test suite. |
