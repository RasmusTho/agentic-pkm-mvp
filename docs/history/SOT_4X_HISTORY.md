State: Archived SoT v4.x ladder and Reality-MVP background (superseded by forward-looking ROADMAP).
# System-of-Truth 4.x History

This document preserves the detailed 4.x ladder narrative that previously lived in `docs/ROADMAP.md`. It is historical context only; the active forward-looking plan now lives in `docs/ROADMAP.md` and current truth in `docs/ARCHITECTURE.md` + `docs/STATUS.md`.

## Reality-MVP (SoT v4.10 — baseline locked)
- Delivered a single-user Reality-MVP: stable vault ingest, minimal external ingest, ASK API, observability backend + interim GUI, and orchestrator runtime V1.
- Zones overlay (Active/Warm/Cold) runs as a derived projection across Stores; orthogonal to lifecycle (inbox → processed → evergreen → archived) and temporal value (ephemeral/normal/evergreen).
- Two planes: vault (human graph with minimal frontmatter) and external corpus (newsletters/emails/PDFs) that are indexed and retrievable but not shown as Obsidian notes.
- Human frontmatter stays lightweight; system metadata (signals, usage, relations, promotions, zone inference) lives in SetDB/AMG + Stores. Core-6 remains a projection. Collaboration/multi-user flows are explicitly deferred.

### Reality-MVP acceptance (v4.10)
- Operational soak of vault ingest and external drop-folder ingest on real samples.
- Orchestrator runtime V1 executes internal tools (external ingest) with dual CLI/orchestrator paths; LangGraph/parallel/MCP expansion is future work. Interim GUI (status + ASK surface at `/`) is delivered as a minimal page on the FastAPI app.

### Reality-MVP scope
1) **Vault ingestion** — ingest selected vault folders into ObjectStore with Core-6 fields and provenance; emit Outbox events; index into VectorIndex.
2) **External corpus (minimal)** — ingest a small, real set of external documents into `external_raw`; store + index them without creating Obsidian notes (txt/md drop-folder path implemented).
3) **ASK API** — FastAPI endpoint answering with sources `{uuid, title, origin (vault/external), zone if known, path/source_ref}` and latency.
4) **Observability backend** — status service + CLI surfacing per-plane object counts, ingest timestamps/errors, and ASK query counts/latency.
5) **Interim GUI** — FastAPI-served page at `/` showing system status and an ASK box; explicitly a temporary observability/interaction surface.

## Version Ladder (historical)
| Version | Intent | State |
| --- | --- | --- |
| Reality-MVP (SoT v4.10) | Vault ingestion + external corpus plane + ASK API + observability + interim GUI + orchestrator runtime V1 | Delivered (baseline locked) |
| v4.3 | Establish the PER ingest loop, Outbox wiring, and CI contracts. | Delivered |
| v4.4 | Harden observability, Store abstraction, and identity plus conflict handling. | Delivered |
| v4.5A | Stabilize unified ingestion, deterministic memory-first CI, promotion rules documented. | Delivered |
| v4.5B | Fitness guards + ingestion polish, rerank + chunk dedup readiness. | Delivered |
| v4.6 | Retrieval quality upgrades (cross-encoder, diarization adapter, RelationIndex fitness, golden eval). | Historical foundation (Objectives A–D maintained) |
| v4.6-B | Relation coverage lift (deterministic extraction + audit trail). | Delivered |
| v4.6-C | Diarization-aware chunking & metrics. | Delivered (flagged feature) |
| v4.6-D | CI gates + summary hardening. | Delivered (2025-02-18) |
| v4.7 | Reasoning layer & reflexive agents over the knowledge graph. | Deferred (flag-gated/mocks in CI) |
| v4.8 | Agent Coordination (A2A Protocol V1 + Orchestrator messaging hooks). | Planned (post-MVP) |
| v4.9 | MCP Integration V1 + Planner Agent (LLM) plan schema. | Delivered (planning schema + descriptors; transport mocked) |
| v4.10 | Orchestrator Runtime V1 (LangGraph execution of Planner Agent output). | Delivered skeleton; further LangGraph/MCP execution planned alongside Reality-MVP |

## Historical Detail (selected objectives)
- **v4.5B Fitness & Hook Readiness** — unified chunk/dedup pipeline; rerank hook; CI fitness guards (QAS-003, QAS-010); deterministic memory-mode enforcement.
- **v4.6-A/B/C/D** — ce_local rerank heuristics and golden set; relation coverage lift with audit events; diarization-aware chunking metrics; CI summary gates and baselines in `ops/quality/baselines.yaml`.
- **v4.7 Reasoning (deferred)** — `REASONING_ENABLE` flag routes notes through a deliberation agent with schema validation (`claims`, `evidence`, `inferences`); CI line planned but gated off by default.
- **v4.8 A2A (planned)** — canonical envelopes `agent.request/response/error`; Orchestrator-managed routing; deterministic fixtures when `A2A_ENABLE=1`.
- **v4.9 MCP + Planning** — Plan/PlanStep schema finalized; MockPlanner and Ollama-backed planner with fallback; MCP descriptor registry with mocks; pipeline hook emits `planner.plan.created` gated by planner/orchestrator flags.
- **v4.10 Orchestrator Runtime V1** — executes validated plans, emits `orchestrator.step.*`, runs internal tools (external ingest), keeps LangGraph/MCP expansion as follow-on work.

## Vault-as-GUI Settings Architecture (historical concept)
Goal: make system configuration human-editable in the vault (Markdown) and machine-safe via a typed compiler producing canonical runtime artifacts. Vault is the control panel; code reads only compiled artifacts.
- Scope: `@Settings/` files in the vault; Markdown parsing of checkboxes/key-value tables/authoritative YAML blocks; Pydantic validation; `${SECRET:NAME}` resolution from `.env`/SOPS; compilation to `runtime/settings/**`; event `settings.changed`; CLI `python -m app.cli settings compile|watch`; hot-reload hook.
- Fitness targets: compile ≤500 ms; 100% schema validation coverage for Global + ≥4 agent settings; deterministic artifacts; hot-reload ≤2 s; zero secret leakage in `runtime/`.

For the active forward-looking plan, see `docs/ROADMAP.md`. Current architecture and operational truth live in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.
