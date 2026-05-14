State: SoT v5.5 baseline (descriptive package status inventory; update when packages are promoted, deprecated, or removed).
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
