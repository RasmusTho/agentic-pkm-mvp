State: SoT v5.x forward line (tracked through v5.5: PanelAgent planner pipeline + CLI-first orchestration) built on the locked v4.10 Reality-MVP baseline.
# Documentation Review Index — SoT v5.x forward line

Central map of documentation and markdown artifacts in this repo. Review status values:
- `Unreviewed` — not yet aligned in this total-review pass.
- `Aligned (forward line v5.x)` — matches the active SoT forward line (currently v5.4) on top of the locked v4.10 baseline.
- `Aligned (forward line v5.x, with known debt)` — mostly aligned to v5.x; see Notes for drift.
- `Baseline-only (v4.10)` — reflects the locked baseline; forward-line review pending.
- `Legacy (archived)` — historical snapshot; not current truth.
- `Deprecated` — kept only for reference; avoid for current work.

Docs still tagged `Baseline-only (v4.10)` in tables below should be read as `Baseline-only (v4.10)` and queued for forward-line review; the forward line is the active SoT.

## SoT Notes
- v4.10 — locked Reality-MVP baseline (foundation only).
- v5.0 — PanelAgent Runtime V1 baseline on top of v4.10.
- v5.x — **active SoT forward line** (currently tracked through v5.5: PanelAgent planner pipeline + CLI-first orchestration on top of the watcher track) for Satellite Sync, Yggdrasil modules, Orchestrator/Reasoning 2.0.

## Root and Repo Docs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| README.md | Top-level overview | Aligned (forward line v5.x) | 2025-12-17 | Highlights canonical warm/cold artifacts, rebuildable mirrors, and quickstart details. |
| CHANGELOG.md | Repo change log (root) | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; archived under docs/archive/github-templates/CHANGELOG.md. |
| .github/ISSUE_TEMPLATE/v4.6-objective.md | Issue template (historical, root) | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; archived under docs/archive/github-templates/ISSUE_TEMPLATE_v4.6-objective.md. |
| .github/pull_request_template.md | PR template (historical, root) | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; archived under docs/archive/github-templates/pull_request_template.md. |
| docs/archive/github-templates/CHANGELOG.md | Repo change log (archived) | Legacy (archived) | 2025-12-07 | Moved from root; superseded by STATUS/ROADMAP v4.10. |
| docs/archive/github-templates/ISSUE_TEMPLATE_v4.6-objective.md | Issue template (historical) | Legacy (archived) | 2025-12-07 | Moved from .github; v4.6 template kept for history. |
| docs/archive/github-templates/pull_request_template.md | PR template (historical) | Legacy (archived) | 2025-12-07 | Moved from .github; v4.6 scaffold not current CI expectations. |
| docs/archive/README.md | Archive index | Legacy (archived) | 2025-12-17 | Index of archived docs; not part of the active doc set. |

## Core SoT Docs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/PROJECT_KERNEL.md | Project kernel (human flows + stability contracts) | Aligned (forward line v5.x) | 2025-12-17 | Canonical intent and stability contracts with trust/event/config anchors; notes default scope experiment under Tensions/Follow-ups. |
| docs/CONCEPTS/LAYERING_MODEL.md | Layering model (Domain/Plane/Trust/Zone) | Aligned (forward line v5.x) | 2025-12-17 | Orthogonal boundary model; adds the default scope policy experiment, one-shot includes, bridge fields, and missing-domain safe degradation. |
| docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md | Trust semantics contract (assert/suggest/apply) | Aligned (forward line v5.x) | 2025-12-17 | Defines trust tiers, gating rules, write constraints, and receipts. |
| docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md | Event/intent compatibility contract (versioning) | Aligned (forward line v5.x) | 2025-12-17 | Covers envelope invariants, versioning rules, idempotence, and new-event checklist. |
| docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md | Config-as-product contract | Aligned (forward line v5.x) | 2025-12-17 | Covers precedence, validation, rollback, audit, and portability rules for config. |
| docs/CONCEPTS/PORTABILITY_CONTRACT.md | Portability contract (macOS + Windows) | Aligned (forward line v5.x) | 2025-12-16 | Defines portability hazards and rules for portable artifacts and paths; referenced by PROJECT_KERNEL. |
| docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md | Archive exposure contract (cold brain safety) | Aligned (forward line v5.x) | 2025-12-17 | Defines discovery→citation→preview→materialization modes; notes scope experiment (active domain + global evergreens, with domain excludes + one-shot includes). |
| docs/ARCHITECTURE.md | Architecture (SoT v5.x forward line on v4.10 base) | Aligned (forward line v5.x) | 2025-12-17 | Adds a Contracts section pointing to kernel anchors and concept contracts. |
| docs/SYSTEM_DESIGN_v4.10.md | System design / topology | Baseline-only (v4.10) | 2025-12-07 | Matches deployment topology and local surfaces. |
| docs/STATUS.md | Operational snapshot | Aligned (forward line v5.x + v5.5/v5.6 planned) | 2025-12-17 | Notes that layering/portability/archive/trust/event/config are anchored by concept contracts. |
| docs/ROADMAP.md | Strategic roadmap | Aligned (forward line v5.x + v5.5/v5.6 planned) | 2025-03-14 | Forward line tracked through v5.5 (PanelAgent planner pipeline + CLI-first orchestration); Quality Wave (Runtime Loop Evaluation Stack) defined with A–F deliverables, exit criteria, and explicit module map; v5.6 LangGraph rollout planned; v4.10 baseline referenced only as foundation. |
| docs/tracks/TRACK_WATCHER.md | Watcher track (v5.1–v5.4) | Aligned (forward line v5.x) | 2025-03-12 | Snapshot watcher track details, policy gating, daemon/ergonomics. |
| docs/tracks/TRACK_PANELAGENT_LANGGRAPH.md | PanelAgent LangGraph track (v5.5) | Aligned (forward line v5.x) | 2025-03-12 | PanelAgent catalog/decider modes, planner/orchestrator pipeline, promotion consumer. |
| docs/tracks/TRACK_AGENTOPS_A2A_MCP.md | AgentOps / A2A / MCP track | Aligned (analysis) | 2025-03-12 | Pattern harvest themes for events/A2A/tools/ops; A2A/MCP scaffolding. |
| docs/ROADMAP.md | Strategic roadmap | Aligned (forward line v5.x + v5.5/v5.6 planned) | 2025-03-14 | Forward-looking, skimmable; links to history and track docs under docs/tracks/; includes Quality Wave: Runtime Loop Evaluation Stack (A–F deliverables + module list + exit criteria). |
| docs/ROADMAP.md | Quality Wave (Runtime Loop Evaluation Stack) section | Aligned (forward line v5.x) | 2025-03-14 | Contract tests, golden vault, metamorphic + cold rebuild runs, fitness gates, scripted UAT; modules/files explicitly mapped for upcoming implementation. |
| docs/COMPONENTS.md | Component catalog + dependency rules | Aligned (SoT v4.10 locked) | 2025-12-17 | Consolidates a single maturity taxonomy across the catalog. |
| docs/AGENTS.md | Agents overview | Aligned (forward line v5.x + LangGraph inner principle) | 2025-03-10 | Design principle set to LangGraph inner + events/A2A outer; PanelAgent exemplifies the pattern with a catalog-driven decider and planner pipeline opt-in plus CLI-first orchestration; SoT wording calls out forward line through v5.5 with v4.10 as locked base. |
| docs/PLANNER.md | Planner contract | Baseline-only (v4.10) | 2025-12-07 | Planner/PlanStep schema, guardrail layer, hierarchical planning loop. |
| docs/EVENTS.md | Outbox/event contracts | Aligned (forward line v5.x) | 2025-12-17 | Canonical Outbox envelope + selected event meanings; compatibility anchored in EVENT_COMPATIBILITY_CONTRACT. |
| docs/DIAGRAMS.md | C4 diagrams | Baseline-only (v4.10) | 2025-12-07 | Diagrams reflect current topology. |
| docs/HUMAN-FLOWS.md | Human flows | Aligned (forward line v5.x) | 2025-12-17 | Adds the trust semantics reference while keeping flow guidance. |
| docs/TESTING.md | Testing strategy | Aligned (forward line v5.x) | 2025-03-14 | Adds Evaluation Stack (Runtime Loop / Panel / Promotion) A–F layers (contracts, golden vault, metamorphic, cold rebuild, fitness gates, scripted UAT) with placeholder commands. |
| docs/PANEL_AGENT.md | PanelAgent / NoteInteractionAgent | Aligned (forward line v5.x + planned v5.5 LangGraph) | 2025-03-14 | Adds human-first semantics (freeform may execute with receipts, uncertainty becomes suggested checkboxes, receipts stay outside panel); intent vs mutation and wiring precedence documented. |
| docs/UAT_PANEL_WATCHER.md | UAT guide (panel + watcher) | Aligned | 2025-12-10 | Human-facing UAT flow for PanelAgent + Vault Watcher (prep notes, targeted ingest, panel run-many, watcher dry-run/run, observations). |
| docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md | Module map | Baseline-only (v4.10) | 2025-12-07 | High-level module map reviewed; Reality-MVP scope noted. |
| docs/research/pattern-harvest-agentic-architecture.md | Research synthesis (outer/inner agent architecture) | Aligned (analysis, docs-only) | 2025-03-10 | Pattern harvest of events/A2A/tools/observability/config; backlog + Mermaid diagram; no runtime wiring. |

## Supporting Docs (Quality, Ops, Flows, Data)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/CI.md | CI overview | Baseline-only (v4.10) | 2025-12-07 | ci-smoke/fitness gates documented; other workflows noted. |
| docs/TESTING.md | Testing strategy | Aligned (forward line v5.x) | 2025-03-14 | Adds Evaluation Stack (Runtime Loop / Panel / Promotion) A–F layers (contracts, golden vault, metamorphic, cold rebuild, fitness gates, scripted UAT) with placeholder commands. |
| docs/QUALITY.md | Quality gates | Baseline-only (v4.10) | 2025-12-07 | Clarified QA agent scope vs /api/ask; CI fitness gates noted. |
| docs/guardrails.md | Guardrails | Baseline-only (v4.10) | 2025-12-07 | Runtime guardrails + CI fitness gates; removed legacy thresholds. |
| docs/SECURITY.md | Security | Baseline-only (v4.10) | 2025-12-07 | Single-user/local; auth not wired; key handling guidance. |
| docs/PRIVACY.md | Privacy | Baseline-only (v4.10) | 2025-12-07 | Local-first, outbound only on optional remote LLMs. |
| docs/DEPENDENCIES.md | Dependencies | Baseline-only (v4.10) | 2025-12-07 | System deps + env matrix; ci-smoke defaults noted. |
| docs/PYTHON_VERSION_POLICY.md | Python version policy | Baseline-only (v4.10) | 2025-12-18 | Local dev targets 3.14, CI smoke floor 3.12 with Docker tripwires and scripts. |
| docs/OBSERVABILITY.md | Observability | Aligned (forward line v5.x) | 2025-03-14 | Adds observability-as-tests gates (counters/events as fitness), runtime tick latency budget (p95), and clarifies watcher/panel/promotion counters. |
| docs/OBSERVABILITY_STACK.md | Local observability stack | Baseline-only (v4.10) | 2025-12-07 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/OPERATIONS.md | Operations playbook | Baseline-only (v4.10) | 2025-12-07 | Reality-MVP stack (uvicorn/compose), CLI runbooks, targets noted. |
| docs/INFRASTRUCTURE.md | Infrastructure notes | Baseline-only (v4.10) | 2025-12-07 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/HEALTH.md | Health checks | Baseline-only (v4.10) | 2025-12-07 | CLI health checks (ffmpeg/yt-dlp/outbox/ollama) + ci-smoke reference. |
| docs/CLI.md | CLI reference | Baseline-only (v4.10) | 2025-12-07 | Updated commands (ingest/ask flows, alpha demos, health). |
| docs/LLM.md | LLM integration | Baseline-only (v4.10) | 2025-12-07 | Providers/env defaults (mock/Ollama/OpenAI/DeepSeek). |
| docs/LLM_BACKENDS.md | LLM backends | Baseline-only (v4.10) | 2025-12-07 | Providers mock/ollama/openai/deepseek; timeouts/keys noted. |
| docs/RETRIEVAL.md | Retrieval | Baseline-only (v4.10) | 2025-12-07 | Hybrid search + optional rerank; ASK graph defaults noted. |
| docs/FRONTMATTER.md | Frontmatter rules | Aligned (forward line v5.x) | 2025-12-17 | Defines the warm-surface write contract and receipt placement. |
| docs/DATA_MODEL.md | Data model | Baseline-only (v4.10) | 2025-12-07 | Active store_objects/vector_index/relations; legacy tables noted. |
| docs/DATA_GOVERNANCE.md | Data governance | Aligned (forward line v5.x) | 2025-12-17 | Clarifies canonical vs derived artifacts, trust semantics, and auditable persistence. |
| docs/DB_SCHEMA.md | DB schema | Partially outdated | 2025-12-07 | Current store_* tables documented; legacy AMG tables retained as historical. |
| docs/SCORECARDS.md | Scorecards | Partially outdated | 2025-12-07 | Draft targets only; not enforced in Reality-MVP. |
| docs/PROJECTOR.md | Projector | Baseline-only (v4.10) | 2025-12-07 | Promotion projector emits audit/membership; no filesystem projection. |
| docs/ALIGNMENT.md | Alignment guide | Legacy (archived) | 2025-12-07 | Legacy “Second-Brain” guide; superseded by SoT v4.10. |
| docs/SETTINGS.md | Settings | Baseline-only (v4.10) | 2025-12-07 | Core env vars (STORE_BACKEND/LLM/metrics flags) documented. |
| docs/AUTH_RATE_LIMITING.md | Auth/rate limiting | Partially outdated | 2025-12-07 | Planned API key + slowapi; not implemented in Reality-MVP. |
| docs/ingest.md | Ingest (historical/current) | Baseline-only (v4.10) | 2025-12-07 | Vault-first ingest (CLI, UUID healing, mirror, HybridStore); legacy commands noted. |
| docs/OBSIDIANSYNC.md | Obsidian sync | Baseline-only (v4.10) | 2025-03-10 | Reality-MVP: git watcher primary, filesystem watcher fallback; describes Obsidian → watcher → ingest/update → outbox → indexer; notes Docker-first watcher daemon (`vault-watcher-daemon`) with host fallback. |
| docs/OVERVIEW_WS.md | Workspace overview | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/AI_DEVELOPMENT.md | AI-assisted development policy | Baseline-only (v4.10) | 2025-12-07 | Matches current dev-layer policy and SoT references. |
| docs/DEV_WORKFLOW.md | Developer workflow | Baseline-only (v4.10) | 2025-12-07 | Current TDD/docs-first workflow aligned with v4.10. |
| docs/OPERATIONS.md | Operations playbook | Baseline-only (v4.10) | 2025-12-07 | Reality-MVP stack (uvicorn/compose), CLI runbooks, targets noted. |
| docs/OPS_WATCHER.md | Watcher operations (Docker + host) | Aligned (forward line v5.x) | 2025-03-10 | Docker-first watcher daemon with `/state` snapshot storage and host-service fallback; cooldown guidance for iCloud/Obsidian mounts. |
| docs/INVENTORY.md | Runtime inventory | Baseline-only (v4.10) | 2025-12-07 | Key env vars/CLI surfaces; defaults mock/ollama. |
| docs/GLOSSARY.md | Glossary | Baseline-only (v4.10) | 2025-12-07 | Updated definitions for hybrid/rerank/outbox/health. |
| docs/QUALITY.md | Quality | Baseline-only (v4.10) | 2025-12-07 | QA guardrails vs ASK graph clarified; CI fitness gates noted. |
| docs/CONTRIBUTING.md | Contributing guide | Partially outdated | 2025-12-07 | Setup/tests template; defer to DEV_WORKFLOW/CI for current practice. |
| docs/CHANGELOG.md | Docs changelog | Baseline-only (v4.10, with known debt) | 2025-12-07 | Tracks doc updates; may lag implementations. |
| docs/PRIVACY.md | Privacy | Unreviewed | — |  |
| docs/HEALTH.md | Health checks | Baseline-only (v4.10) | 2025-12-07 | CLI health checks (ffmpeg/yt-dlp/outbox/ollama) + ci-smoke reference. |
| docs/LLM_BACKENDS.md | LLM backends | Baseline-only (v4.10) | 2025-12-07 | Providers mock/ollama/openai/deepseek; timeouts/keys noted. |
| docs/INFRASTRUCTURE.md | Infrastructure | Baseline-only (v4.10) | 2025-12-07 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/OPERATIONS.md | Operations | Baseline-only (v4.10) | 2025-12-07 | Reality-MVP stack (uvicorn/compose), CLI runbooks, targets noted. |
| docs/INVENTORY.md | Inventory | Baseline-only (v4.10) | 2025-12-07 | Key env vars/CLI surfaces; defaults mock/ollama. |
| docs/OVERVIEW_WS.md | Overview | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/DEPENDENCIES.md | Dependencies | Baseline-only (v4.10) | 2025-12-07 | System deps + env matrix; ci-smoke defaults noted. |
| docs/PYTHON_VERSION_POLICY.md | Python version policy | Baseline-only (v4.10) | 2025-12-18 | Local dev targets 3.14, CI smoke floor 3.12 with Docker tripwires and scripts. |
| docs/OBSERVABILITY.md | Observability | Aligned (forward line v5.x) | 2025-03-14 | Adds observability-as-tests gates (counters/events as fitness), runtime tick latency budget (p95), and clarifies watcher/panel/promotion counters. |
| docs/OBSERVABILITY_STACK.md | Observability stack | Baseline-only (v4.10) | 2025-12-07 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/AI_DEVELOPMENT.md | AI development policy | Baseline-only (v4.10) | 2025-12-07 | Matches current dev-layer policy and SoT references. |
| docs/DEV_WORKFLOW.md | Dev workflow | Baseline-only (v4.10) | 2025-12-07 | Current TDD/docs-first workflow aligned with v4.10. |
| docs/scenarios/REALITY_MVP.md | Scenario walkthrough | Baseline-only (v4.10) | 2025-12-07 | Matches e2e pipeline test and ASK expectations. |

## Historical / Archived (Architecture Deep Dives)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/archive/architecture/next-steps.md | Architecture future/bridge (historical) | Legacy (archived) | 2025-12-17 | SoT v4.3-era addendum; kept for reference with an explicit HISTORICAL banner; not authoritative for current SoT. |
| docs/archive/architecture/obsidian_integration.md | Obsidian integration deep dive (historical) | Legacy (archived) | 2025-12-17 | SoT v4.3-era deep dive; kept for reference with an explicit HISTORICAL banner; not authoritative for current SoT. |
| docs/architecture/memory/api.md | Memory API v4.2 | Legacy (archived) | 2025-12-07 | V4.2 agent-memory API; not in Reality-MVP. |
| docs/architecture/memory/c4-component.md | Memory C4 component | Legacy (archived) | 2025-12-07 | Legacy memory component view; see ARCHITECTURE/DATA_MODEL. |
| docs/architecture/memory/c4-container.md | Memory C4 container | Legacy (archived) | 2025-12-07 | Legacy container diagram; superseded by SYSTEM_DESIGN_v4.10. |
| docs/architecture/memory/c4-context.md | Memory C4 context | Legacy (archived) | 2025-12-07 | Legacy context (AMG/SetDB); not applicable to v4.10. |
| docs/architecture/memory/data-model.md | Memory data model | Legacy (archived) | 2025-12-07 | Agent_memories/memory_edges tables not present in v4.10. |
| docs/architecture/memory/event-taxonomy.md | Memory event taxonomy | Legacy (archived) | 2025-12-07 | Memory events not emitted; use EVENTS.md/app.events.types. |
| docs/architecture/memory/observability.md | Memory observability | Legacy (archived) | 2025-12-07 | Proposed metrics for non-existent memory store. |
| docs/architecture/memory/perf.md | Memory performance | Legacy (archived) | 2025-12-07 | Legacy perf notes; see RETRIEVAL/INGEST for current concerns. |
| docs/architecture/memory/security.md | Memory security | Legacy (archived) | 2025-12-07 | Legacy security for memory store; see SECURITY/PRIVACY. |
| docs/architecture/memory/sequence-per.md | Memory PER sequence | Legacy (archived) | 2025-12-07 | PER sequence for memory store not in Reality-MVP. |
| docs/architecture/memory/overview.md | Memory overview | Legacy (archived) | 2025-12-07 | V4.2 memory overview; replaced by ObjectStore/VectorIndex. |
| docs/uml/README.md | UML index | Legacy (archived) | 2025-12-17 | Legacy UML overview + diagram index; replaced by the architecture docs. |
| docs/uml/agent_sequence.md | UML sequence | Legacy (archived) | 2025-12-07 | Run_agent supervisor loop; not part of Reality-MVP. |
| docs/uml/agent_components.md | UML components | Legacy (archived) | 2025-12-11 | Legacy agent service components; watcher block marked removed and superseded by planned v5.x watcher track (see ROADMAP/STATUS/HUMAN-FLOWS). |

## Runbooks, How-to, Settings Examples, and Examples
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/runbooks/ingest.md | Runbook: ingest | Baseline-only (v4.10, with known debt) | 2025-12-07 | Troubleshooting vault ingest/outbox; matches current CLI path. |
| docs/runbooks/RUNBOOK_GO_LIVE.md | Runbook: go-live checklist | Aligned (forward line v5.x) | 2025-12-18 | Dry-run go-live preflight (vault/outbox/settings), small-scope UAT, rollout and rollback posture. |
| docs/howto/memory.md | How-to: memory | Legacy (archived) | 2025-12-07 | Agent-memory guide superseded by ObjectStore/decisions in v4.10. |
| docs/settings/sample-flows/ingest.flow.md | Sample flow | Partially outdated | 2025-12-07 | Template for future planner/orchestrator ingest; not loaded in v4.10. |
| docs/settings/sample-agents/planner.md | Sample agent config | Partially outdated | 2025-12-07 | Planner config template for v5.x; unused in Reality-MVP. |
| docs/settings/sample-agents/normalizer.md | Sample agent config | Partially outdated | 2025-12-07 | Normalizer config template; runtime uses direct agents, not these YAMLs. |
| docs/settings/panel-actions.md | Panel action mappings | Aligned (v5.0 – PanelAgent runtime V1) | 2025-12-10 | Aligned with v5.0 PanelAgent Runtime V1 baseline; fallback mappings include promotion intent and runtime logging for unmapped actions. |
| docs/settings/prompts/classifier.v1.md | Prompt definition (classifier) | Baseline (v4.10) | 2025-12-18 | Settings-backed registry prompt for classifier.v1; frontmatter + schema enforced. |
| docs/settings/prompts/ask.answer.v1.md | Prompt definition (ask answer) | Baseline (v4.10) | 2025-12-18 | Settings-backed registry prompt for ask.answer.v1; references JSON Schema + standards. |
| docs/examples/ai-panel-example.md | AI panel example note | Baseline-only (v4.10, with known debt) | 2025-12-07 | Panel fences + Swedish headings; dispatch optional. |

## Eval and Quality
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/eval.md | Eval stack | Baseline-only (v4.10) | 2025-12-07 | Opt-in DeepEval/Ragas suites; skips when deps/LLM missing. |
| docs/SCORECARDS.md | Scorecards | Partially outdated | 2025-12-07 | Draft targets only; not enforced in Reality-MVP. |
| docs/QUALITY.md | Quality | Baseline-only (v4.10) | 2025-12-07 | QA guardrails vs ASK graph clarified; CI fitness gates noted. |

## Agents / Codex Guidance
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/agents/AGENT_SPEC.md | Agent spec | Baseline-only (v4.10, with known debt) | 2025-12-07 | Reality-MVP agent contracts; notes on stubs (chunks/outbox/index) and parked agents. |
| .codex/AGENTS.md | Coding agent guidance | Baseline-only (v4.10) | 2025-12-07 | Dev-layer system prompt; hierarchy/constraints/tests-first made current. |
| docs/codex/GUIDELINES.md | Codex guidelines | Baseline-only (v4.10) | 2025-12-07 | Quick checklist pointing to .codex/AGENTS and SoT anchors. |

## ADRs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/adr/INDEX.md | ADR index | Baseline-only (v4.10, with known debt) | 2025-12-07 | Index updated with legacy/partial states for ADRs. |
| docs/adr/ADR-00X-agent-memory-v1.md | ADR (agent memory v1) | Legacy (archived) | 2025-12-07 | Historical PG JSONB memory; superseded by ObjectStore/decisions in v4.10. |
| docs/adr/ADR-00X-agent-memory-v42.md | ADR (agent memory v42) | Legacy (archived) | 2025-12-07 | Scoped PG memory/edges not implemented in v4.10. |
| docs/adr/0001-externa-komponenter.md | ADR external components | Legacy (archived) | 2025-12-07 | Superseded by SYSTEM_DESIGN_v4.10 and LLM/COMPONENTS docs. |
| docs/adr/0004-outbox-latency.md | ADR outbox latency | Partially outdated | 2025-12-07 | Targeted outbox→index <=2s; no worker/CI gate in Reality-MVP. |
| docs/adr/0005-per-loop.md | ADR PER loop | Partially outdated | 2025-12-07 | Base PER class exists; agents use bespoke flows; not enforced. |
| docs/adrs/ADR-00xx-promotion-agent.md | ADR promotion agent | Partially outdated | 2025-12-07 | Promotion/projector stub only; event-driven file moves are future work. |

## Legacy and Archive
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/archive/NEXT-STEPS.md | Archived plan | Legacy (archived) | — |  |
| docs/archive/transcription.md | Archived transcription doc | Legacy (archived) | — |  |
| docs/archive/SoT-v4.1.md | Legacy SoT v4.1 | Legacy (archived) | — |  |
| docs/archive/TESTS.md | Archived tests doc | Legacy (archived) | — |  |
| docs/archive/RUNBOOK.md | Archived runbook | Legacy (archived) | — |  |
| docs/archive/decision-log-2025-10.md | Decision log | Legacy (archived) | — |  |
| docs/archive/VERSIONING.md | Versioning (archived) | Legacy (archived) | — |  |
| docs/archive/codex_plan.md | Codex plan (archived) | Legacy (archived) | — |  |
| docs/legacy/PROJECT_OVERVIEW.md | Legacy overview | Legacy (archived) | — |  |
| docs/legacy/TODO.md | Legacy TODO | Legacy (archived) | 2025-12-11 | Notes that the old ingestion watcher is deprecated; planned v5.x watcher track supersedes it. |

## Scenario and Protocol Docs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/scenarios/REALITY_MVP.md | Reality-MVP scenario | Baseline-only (v4.10) | 2025-12-07 | Matches e2e pipeline test and ASK expectations. |
| docs/PROTOCOL_SATELLITE_SYNC.md | Satellite sync protocol | Planned / not implemented | 2025-12-07 | Draft v5.x master/satellite sync; not implemented in Reality-MVP. |

## Additional Docs (misc)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/LLM_BACKENDS.md | LLM backends | Baseline-only (v4.10) | 2025-12-07 | Providers mock/ollama/openai/deepseek; timeouts/keys noted. |
| docs/INFRASTRUCTURE.md | Infrastructure | Baseline-only (v4.10) | 2025-12-07 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/OVERVIEW_WS.md | Overview workspace | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/DEPENDENCIES.md | Dependencies | Baseline-only (v4.10) | 2025-12-07 | System deps + env matrix; ci-smoke defaults noted. |
| docs/PYTHON_VERSION_POLICY.md | Python version policy | Baseline-only (v4.10) | 2025-12-18 | Local dev targets 3.14, CI smoke floor 3.12 with Docker tripwires and scripts. |
| docs/OBSERVABILITY.md | Observability | Aligned (forward line v5.x) | 2025-03-14 | Adds observability-as-tests gates (counters/events as fitness), runtime tick latency budget (p95), and clarifies watcher/panel/promotion counters. |
| docs/OBSERVABILITY_STACK.md | Observability stack | Baseline-only (v4.10) | 2025-12-07 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/AI_DEVELOPMENT.md | AI development | Baseline-only (v4.10) | 2025-12-07 | Current dev-layer AI policy (docs-first, mocks/defaults). |
| docs/DEV_WORKFLOW.md | Dev workflow | Baseline-only (v4.10) | 2025-12-07 | TDD/docs-first workflow aligned with SoT v4.10. |
| docs/PROJECTOR.md | Projector | Baseline-only (v4.10) | 2025-12-07 | Promotion projector emits audit/membership; no filesystem projection. |
| docs/ALIGNMENT.md | Alignment | Legacy (archived) | 2025-12-07 | Legacy “Second-Brain” guide; superseded by SoT v4.10. |
| docs/SYSTEM_OVERVIEW.md | System overview (historical) | Legacy (archived) | 2025-12-07 | Historical v4.2 overview; superseded by SoT v4.10. |
| docs/GLOSSARY.md | Glossary | Baseline-only (v4.10) | 2025-12-07 | Updated definitions for hybrid/rerank/outbox/health. |
| docs/MEMORY.md | Memory design (historical) | Legacy (archived) | 2025-12-07 | v4.3 memory plan; superseded by DATA_MODEL/ARCHITECTURE v4.10. |

## Settings / Vault / System / Inbox
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| System/Dashboards/inbox.md | System dashboard | Baseline-only (v4.10) | 2025-12-07 | Minimal vault dashboard for system inbox notes. |
| System/Dashboards/conflicts.md | System dashboard | Baseline-only (v4.10) | 2025-12-07 | Minimal vault dashboard for conflicts inbox. |
| System/Settings/system.md | System settings | Partially outdated | 2025-12-07 | Illustrative sync settings; not enforced in Reality-MVP. |
| Inbox/System-changes.md | Inbox/system changes | Baseline-only (v4.10) | 2025-12-07 | Log stub for system change notes. |
| vault/0_Atlas/Home.md | Vault note | Baseline-only (v4.10, with known debt) | 2025-12-07 | Home navigation; points to settings/inbox/desks; panels optional. |
| vault/@Desk/galaxy-test.md | Vault note | Example / sandbox | 2025-12-07 | Sample note with UUID; non-authoritative. |
| vault/@Desk/Test fil 2.md | Vault note | Example / sandbox | 2025-12-07 | Empty example note. |
| vault/Konfigurera.md | Vault note | Example / sandbox | 2025-12-07 | Placeholder/config sandbox. |
| vault/Test fil1.md | Vault note | Example / sandbox | 2025-12-07 | Empty example note. |
| vault/@Inbox/Desicion science for data scientists 2.md | Vault inbox note | Example / sandbox | 2025-12-07 | Sample inbox content; non-authoritative. |
| vault/settings/Overview.md | Vault settings overview | Example / sandbox | 2025-12-07 | Human-facing overview; runtime config is env + _system YAML. |
| vault/@Settings/global.md | Vault settings | Example / sandbox | 2025-12-17 | Global settings surface; ingested by the settings compiler when the vault is mounted (e.g., ./vault). |
| vault/@Settings/agents/promotion.md | Vault agent settings | Example / sandbox | 2025-12-17 | Promotion agent settings (vault surface); ingested by the settings compiler when the vault is mounted (e.g., ./vault). |
| vault/@Settings/agents/classifier.md | Vault agent settings | Example / sandbox | 2025-12-17 | Classifier agent settings (vault surface); ingested by the settings compiler when the vault is mounted (e.g., ./vault). |
| vault/@Settings/agents/qa.md | Vault agent settings | Example / sandbox | 2025-12-17 | QA agent settings (vault surface); ingested by the settings compiler when the vault is mounted (e.g., ./vault). |
| vault/@Settings/agents/reviewer.md | Vault agent settings | Example / sandbox | 2025-12-17 | Reviewer agent settings (vault surface); ingested by the settings compiler when the vault is mounted (e.g., ./vault). |
| vault/@Settings/providers.md | Vault provider settings | Example / sandbox | 2025-12-17 | Provider settings surface; ingested by the settings compiler when the vault is mounted (e.g., ./vault). |

## Prompts / Data Context
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| data/context/prompts/context_summarizer.md | Prompt context | Baseline-only (v4.10, with known debt) | 2025-12-07 | Manual prompt snippet; not wired into runtime, English-only, review-before-write. |

## Examples / Golden Samples
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| golden/note_evergreen.md | Golden sample | Example / sandbox | 2025-12-07 | Golden example note; contracts defined in SoT docs. |
| golden/creative_scene.md | Golden sample | Example / sandbox | 2025-12-07 | Golden creative example; illustrative only. |
| golden/dataset.md | Golden dataset doc | Example / sandbox | 2025-12-07 | Golden dataset description; illustrative. |
| tests/fixtures/reality_mvp/demo_note.md | Test fixture note | Example / sandbox | 2025-12-07 | Test fixture for Reality-MVP flows; keep stable for tests. |
| tests/fixtures/vault_alpha/Templates/NoteTemplate.md | Test fixture | Example / sandbox | 2025-12-07 | Vault alpha template fixture used in tests. |
| tests/fixtures/vault_alpha/Test/Alpha-HumanFlows.md | Test fixture | Example / sandbox | 2025-12-07 | Fixture for human flows tests. |
| tests/fixtures/vault_alpha/System/Internal.md | Test fixture | Example / sandbox | 2025-12-07 | Vault alpha internal fixture. |
| tests/fixtures/vault_alpha/Concepts/NeedsUUID.md | Test fixture | Example / sandbox | 2025-12-07 | UUID-healing fixture; keep stable. |
| tests/fixtures/vault_alpha/Concepts/MirrorConflict.md | Test fixture | Example / sandbox | 2025-12-07 | Mirror conflict fixture; keep stable. |
| tests/fixtures/vault_alpha/Concepts/HasPanel.md | Test fixture | Example / sandbox | 2025-12-07 | Panel parsing fixture; keep stable. |
| tests/fixtures/vault_alpha/Concepts/ExistingUUID.md | Test fixture | Example / sandbox | 2025-12-07 | Existing UUID fixture. |
| tests/fixtures/vault_alpha/System/Metadata/VaultMirror/Concepts/44444444-4444-4444-4444-444444444444.md | Test fixture | Example / sandbox | 2025-12-07 | VaultMirror fixture; keep stable. |
| tests/fixtures/merge/nd_concise.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/nd_base.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/cd_dump.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/st_reviewed.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/id_a.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/id_base.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/st_base.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/cd_base.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/nd_rambly.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/ov_base.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/st_promoted.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/cd_prose.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/ov_refs.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/id_b.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |
| tests/fixtures/merge/ov_polished.md | Test fixture (merge) | Example / sandbox | 2025-12-07 | Merge fixture; keep for tests. |

## Archive / Trash / Temp
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| Archive/Trash/2025-10/note.md | Trash | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; no impact on SoT. |
| Archive/Trash/2025-11/note.md | Trash | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; no impact on SoT. |
| Archive/Trash/2025-12/note.md | Trash | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; no impact on SoT. |
| tmp-test/renamed.md | Temp/test file | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; no impact on SoT. |
| tmp-test/original.md | Temp/test file | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; no impact on SoT. |
| tmp-test2/a.md | Temp/test file | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; no impact on SoT. |
| docs/tracks/TRACK_FITNESS_CI_CONTRACT.md | Fitness & CI contract track | Aligned (forward line v5.x) | 2025-03-12 | Fitness gates QAS003/010, rerank/relations/diarization CI summary lines; reasoning/A2A gates planned. |
| docs/history/SOT_4X_HISTORY.md | SoT 4.x history | Legacy (archived) | 2025-03-12 | Historical v4.x ladder; roadmap now forward-only. |
| docs/examples/vault_test_seed/evergreen-strategy.md | UAT seed note | Aligned (UAT seeds) | 2025-03-12 | Promote-evergreen scenario for watcher/panel UAT. |
| docs/examples/vault_test_seed/reflection-journal.md | UAT seed note | Aligned (UAT seeds) | 2025-03-12 | Reflection-only scenario (no promotion expected). |
| docs/examples/vault_test_seed/mixed-actions.md | UAT seed note | Aligned (UAT seeds) | 2025-03-12 | Mixed actions; only mapped actions trigger intents. |
| docs/examples/vault_test_seed/summary-request.md | UAT seed note | Aligned (UAT seeds) | 2025-03-12 | Summary-only scenario aligned with panel wiring. |
| docs/examples/vault_test_seed/unknown-action.md | UAT seed note | Aligned (UAT seeds) | 2025-03-12 | Unknown action should log but not promote. |
| docs/examples/vault_test_seed/manual-policy.md | UAT seed note | Aligned (UAT seeds) | 2025-03-12 | Manual policy example; watcher should skip panel. |
