State: SoT v5.5 Reality-MVP baseline locked (watcher safety, panel action provenance, and concurrency guardrails); forward line v5.6 tracking LangGraph and reasoning rollouts while referencing `docs/STATUS.md#baseline-definition`.
# Documentation Review Index — SoT v5.5 baseline + v5.x forward line

Central map of documentation and markdown artifacts in this repo. Review status values:
- `Unreviewed` — not yet aligned in this total-review pass.
- `Aligned (forward line v5.x)` — matches the active SoT forward line (currently v5.6) on top of the locked v5.5 baseline.
- `Aligned (forward line v5.x, with known debt)` — mostly aligned to v5.x; see Notes for drift.
- `Baseline-only (v4.10)` — reflects the locked baseline; forward-line review pending.
- `Legacy (archived)` — historical snapshot; not current truth.
- `Deprecated` — kept only for reference; avoid for current work.

Docs still tagged `Baseline-only (v4.10)` in tables below should be read as foundation-only and queued for baseline/forward-line review; the active SoT baseline is v5.5.

## SoT Notes
- v4.10 — locked Reality-MVP baseline (foundation only).
- v5.0 — PanelAgent Runtime V1 baseline on top of v4.10.
- v5.x — **active SoT forward line** (currently tracked through v5.5: PanelAgent planner pipeline + CLI-first orchestration on top of the watcher track) for Satellite Sync, Yggdrasil modules, Orchestrator/Reasoning 2.0.

## Root and Repo Docs
- `docs/EMBEDDINGS.md` — Normative embeddings spec (identity, guardrails, rebuild policy).
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| README.md | Top-level overview | Aligned (forward line v5.x) | 2026-02-05 | v5.5 baseline quickstart + invariants; points to DOCS_INDEX/STATUS/ARCHITECTURE. |
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
| docs/PROJECT_KERNEL.md | Project kernel (human flows + stability contracts) | Aligned (forward line v5.x) | 2026-02-05 | Canonical intent and stability contracts with trust/event/config anchors; notes default scope experiment under Tensions/Follow-ups. |
| docs/CONCEPTS/LAYERING_MODEL.md | Layering model (Domain/Plane/Trust/Zone) | Aligned (forward line v5.x) | 2026-02-05 | Orthogonal boundary model; adds the default scope policy experiment, one-shot includes, bridge fields, and missing-domain safe degradation. |
| docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md | Trust semantics contract (assert/suggest/apply) | Aligned (forward line v5.x) | 2026-02-05 | Defines trust tiers, gating rules, write constraints, and receipts. |
| docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md | Event/intent compatibility contract (versioning) | Aligned (forward line v5.x) | 2026-02-05 | Covers envelope invariants, versioning rules, idempotence, and new-event checklist. |
| docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md | Config-as-product contract | Aligned (forward line v5.x) | 2026-02-05 | Covers precedence, validation, rollback, audit, and portability rules for config. |
| docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md | Cloud connectors decision (watcher/inbox contracts, delta feed guardrails) | Aligned (forward line v5.x) | 2026-02-05 | Source memo from Swedish draft; anchors delta feed alternatives, watcher matrix, inbox taxonomy, and automation safety signals. |
| docs/CONCEPTS/PORTABILITY_CONTRACT.md | Portability contract (macOS + Windows) | Aligned (forward line v5.x) | 2026-02-05 | Defines portability hazards and rules for portable artifacts and paths; referenced by PROJECT_KERNEL. |
| docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md | Archive exposure contract (cold brain safety) | Aligned (forward line v5.x) | 2026-02-05 | Defines discovery→citation→preview→materialization modes; notes scope experiment (active domain + global evergreens, with domain excludes + one-shot includes). |
| docs/CORE_CONTRACT.md | Core-6 contract (canonical) | Aligned (forward line v5.x) | 2026-02-05 | Canonical Core-6 semantic contract, ownership, and projection rules. |
| docs/CORE6_CONTRACT.md | Core-6 contract (compat alias) | Deprecated | 2025-12-28 | Superseded by `docs/CORE_CONTRACT.md`. |
| docs/NOTE_KIND_POLICIES.md | Note kind policies | Aligned (forward line v5.x) | 2026-02-05 | Policy profiles for kind routing and state-axis enablement. |
| docs/ARCHITECTURE.md | Architecture (SoT v5.x forward line on v5.5 base) | Aligned (forward line v5.x) | 2026-02-04 | Adds runtime watcher choice, DB outbox canonical queue, registry watcher topology; clarifies Core-6 contract, state axes, note kind policies, and derived overlays. |
| docs/CONCURRENCY.md | Concurrency + idempotency guardrails | Aligned (forward line v5.x) | 2026-02-05 | Normative concurrency/idempotency requirements and test placeholders. |
| docs/SYSTEM_DESIGN_v4.10.md | System design / topology | Baseline-only (v4.10) | 2026-02-05 | Historical reference; contains v5.5 delta note; not authoritative for current baseline. |
| docs/STATUS.md | Operational snapshot | Aligned (SoT v5.5 baseline locked + forward line v5.6 planned) | 2026-02-04 | Baseline definition (v5.5) covers watcher/panel settings provenance and concurrency guards; registry watcher default + DB outbox canonical queue noted. |
| docs/ROADMAP.md | Strategic roadmap | Aligned (SoT v5.5 baseline locked + forward line v5.6 planned) | 2026-02-05 | Forward line leans on the v5.5 baseline while v5.6 LangGraph/Reasoning stages are planned; runtime loop evaluation stack updated for registry watcher + DB outbox. |
| docs/V56_FORWARD_LINE.md | v5.6 forward line kickoff plan | Aligned (SoT v5.6 forward line) | 2026-02-05 | Now/Next/Later plan with acceptance criteria for watchers auto-run, LangGraph rollout, and orchestrator V2; links STATUS/ROADMAP for traceability. |
| docs/tracks/TRACK_WATCHER.md | Watcher track (v5.1–v5.4) | Aligned (forward line v5.x) | 2026-02-05 | Adds registry watcher as runtime standard; legacy snapshot watcher noted. |
| docs/tracks/TRACK_PANELAGENT_LANGGRAPH.md | PanelAgent LangGraph track (v5.5) | Aligned (forward line v5.x) | 2026-02-05 | PanelAgent catalog/decider modes, planner/orchestrator pipeline, promotion consumer. |
| docs/tracks/TRACK_AGENTOPS_A2A_MCP.md | AgentOps / A2A / MCP track | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Pattern harvest themes for events/A2A/tools/ops; some items are planned. |
| docs/tracks/TRACK_FITNESS_CI_CONTRACT.md | Fitness / CI contract | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Fitness gates are live; some reasoning/A2A/MCP gates are planned/flag-gated. |
| docs/ROADMAP.md | Strategic roadmap | Aligned (forward line v5.x) | 2026-02-05 | Forward-looking, skimmable; links to history and track docs under docs/tracks/; calls out registry watcher evaluation stack and settings compiler provenance. |
| docs/ROADMAP.md | Quality Wave (Runtime Loop Evaluation Stack) section | Aligned (forward line v5.x) | 2026-02-05 | Contract tests, golden vault, metamorphic + cold rebuild runs, fitness gates, scripted UAT; registry watcher focus. |
| docs/COMPONENTS.md | Component catalog + dependency rules | Aligned (forward line v5.x) | 2026-02-05 | Component catalog updated to v5.5 outbox reality (DB canonical + JSONL audit). |
| docs/EMBEDDINGS.md | Embedding spec | Aligned (forward line v5.x) | 2026-02-05 | Normative spec for provider-aware embeddings (identity, dims, outbox events, rebuild rules). |
| docs/AGENTS.md | Agents overview | Aligned (forward line v5.x + LangGraph inner principle) | 2026-02-04 | LangGraph inner + events/A2A outer; PanelAgent exemplifies the pattern with catalog decider + planner pipeline opt-in; SoT wording updated to v5.5 baseline and v5.6 forward line. |
| docs/PLANNER.md | Planner contract | Legacy (archived) | 2026-02-05 | Historical reference; planner/orchestrator behavior has evolved. |
| docs/EVENTS.md | Outbox/event contracts | Aligned (forward line v5.x) | 2026-02-04 | Canonical Outbox envelope + selected event meanings; compatibility anchored in EVENT_COMPATIBILITY_CONTRACT. |
| docs/DIAGRAMS.md | C4 diagrams | Baseline-only (v4.10) | 2026-02-05 | Legacy diagrams; prefer ARCHITECTURE/HUMAN-FLOWS for v5.5 baseline. |
| docs/HUMAN-FLOWS.md | Human flows | Aligned (forward line v5.x) | 2026-02-04 | Registry watcher runtime path, AI fence policy, UUID healing, and trust semantics reference. |
| docs/TESTING.md | Testing strategy | Aligned (forward line v5.x) | 2026-02-04 | Evaluation stack updated for registry watcher + DB outbox contracts; covers watcher dedup, promotion idempotency, settings validation. |
| docs/PANEL_AGENT.md | PanelAgent / NoteInteractionAgent | Aligned (forward line v5.x) | 2026-02-04 | Runtime V1 baseline + planner pipeline opt-in; human-first semantics, intent vs mutation, wiring precedence. |
| docs/UAT_PANEL_WATCHER.md | UAT guide (panel + watcher) | Aligned (forward line v5.x) | 2026-02-05 | Registry watcher UAT flow with AI fence policy and UUID healing. |
| docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md | Module map | Legacy (archived) | 2026-02-05 | Historical module map; may not reflect v5.5 wiring. |
| docs/research/pattern-harvest-agentic-architecture.md | Research synthesis (outer/inner agent architecture) | Aligned (analysis, docs-only) | 2026-02-05 | Pattern harvest of events/A2A/tools/observability/config; backlog + Mermaid diagram; no runtime wiring. |

## Supporting Docs (Quality, Ops, Flows, Data)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/CI.md | CI overview | Aligned (forward line v5.x) | 2026-02-04 | Updated for v5.5 baseline gates, smoke flows, and watcher controls. |
| docs/TESTING.md | Testing strategy | Aligned (forward line v5.x) | 2026-02-04 | Evaluation stack updated for registry watcher + DB outbox contracts; runtime loop UAT coverage. |
| docs/ISSUES_TESTING.md | Testing coverage issues | Unreviewed | — | Tracks coverage gaps referenced by docs/TESTING.md; update when issues close. |
| docs/QUALITY.md | Quality gates | Aligned (forward line v5.x) | 2026-02-04 | QA guardrails + fitness gates aligned with v5.5 baseline. |
| docs/guardrails.md | Guardrails | Aligned (forward line v5.x) | 2026-02-04 | Runtime guardrails + concurrency safety aligned with v5.5 baseline. |
| docs/SECURITY.md | Security | Aligned (forward line v5.x) | 2026-02-04 | Local-first security posture; keys/env handling aligned with v5.5 baseline. |
| docs/PRIVACY.md | Privacy | Aligned (forward line v5.x) | 2026-02-04 | Local-first, outbound only on optional remote LLMs. |
| docs/DEPENDENCIES.md | Dependencies | Aligned (forward line v5.x) | 2026-02-05 | External deps aligned to current modules (transcribe, llm, watcher). |
| docs/PYTHON_VERSION_POLICY.md | Python version policy | Aligned (forward line v5.x) | 2026-02-05 | Repo requires Python >=3.12; CI smoke pinned to 3.12. |
| docs/OBSERVABILITY.md | Observability | Aligned (forward line v5.x) | 2026-02-04 | Updated for v5.5 baseline + v5.6 forward line counters and watcher payload metadata. |
| docs/OBSERVABILITY_STACK.md | Local observability stack | Aligned (forward line v5.x) | 2026-02-04 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/OPERATIONS.md | Operations playbook | Aligned (forward line v5.x) | 2026-02-04 | Compose stack (api/worker/watcher/db) + v5.5 runtime runbooks. |
| docs/INFRASTRUCTURE.md | Infrastructure notes | Aligned (forward line v5.x, with known debt) | 2026-02-04 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/HEALTH.md | Health checks | Aligned (forward line v5.x) | 2026-02-04 | CLI health checks (ffmpeg/yt-dlp/outbox/ollama) + ci-smoke reference. |
| docs/CLI.md | CLI reference | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Partial reference; authoritative list is `python -m app.cli --help`. |
| docs/LLM_ROUTING.md | LLM routing contract (router + fabric) | Aligned (forward line v5.x) | 2026-02-05 | Canonical routing/fabric contract; documents env precedence and debug surfaces. |
| docs/LLM.md | LLM integration | Aligned (forward line v5.x) | 2026-02-05 | Updated env vars/endpoints + explicit delta notes. |
| docs/LLM_BACKENDS.md | LLM backends | Aligned (forward line v5.x) | 2026-02-05 | Backends/env vars documented (chat + embeddings via Ollama/mock; OpenAI/DeepSeek chat). |
| docs/RETRIEVAL.md | Retrieval | Aligned (forward line v5.x) | 2026-02-05 | Hybrid retrieval + optional rerank hooks (RERANK_ENABLE/RERANK_PROVIDER). |
| docs/FRONTMATTER.md | Frontmatter rules | Aligned (forward line v5.x) | 2026-02-05 | Defines metadata layers, ownership, and the warm-surface write contract. |
| docs/DATA_MODEL.md | Data model | Aligned (forward line v5.x) | 2026-02-05 | DB mirror of the Core-6 contract; derived overlays are rebuildable. |
| docs/DATA_GOVERNANCE.md | Data governance | Aligned (forward line v5.x) | 2026-02-05 | Clarifies canonical vs derived artifacts, trust semantics, and auditable persistence. |
| docs/DB_SCHEMA.md | DB schema | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Snapshot of current tables/views + DB outbox bootstrap; notes multiple historical Alembic heads. |
| docs/SCORECARDS.md | Scorecards | Planned / not implemented | 2026-02-05 | Spec only; not enforced by runtime unless CI gates/tests consume it. |
| docs/PROJECTOR.md | Projector | Legacy (archived) | 2026-02-05 | Historical reference; projector behavior is not current baseline. |
| docs/ALIGNMENT.md | Alignment guide | Legacy (archived) | 2025-12-07 | Legacy “Second-Brain” guide; superseded by SoT v4.10. |
| docs/SETTINGS.md | Settings | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Settings compiler + registries documented; some areas are forward-looking. |
| docs/AUTH_RATE_LIMITING.md | Auth/rate limiting | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Implemented for key routers (API key + SlowAPI); doc lists remaining wiring gaps. |
| docs/ingest.md | Ingest (historical/current) | Legacy (archived) | 2026-02-05 | Historical reference; prefer HUMAN-FLOWS/OPERATIONS for current ingest. |
| docs/OBSIDIANSYNC.md | Obsidian sync | Aligned (forward line v5.x) | 2026-02-05 | Registry watcher runtime + DB outbox canonical queue. |
| docs/OVERVIEW_WS.md | Workspace overview | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/MEMORY.md | Memory (legacy overview) | Legacy (archived) | 2025-12-07 | Historical memory-layer description; not used in Reality-MVP. |
| docs/AI_DEVELOPMENT.md | AI-assisted development policy | Aligned (forward line v5.x) | 2026-02-05 | Dev-layer policy tied to Core-6 guardrails and vault policy constraints. |
| docs/DEV_WORKFLOW.md | Developer workflow | Aligned (forward line v5.x) | 2026-02-04 | TDD/docs-first workflow aligned with the v5.5 baseline. |
| docs/OPERATIONS.md | Operations playbook | Aligned (forward line v5.x) | 2026-02-04 | Compose stack (api/worker/watcher/db) + v5.5 runtime runbooks; DB outbox canonical queue. |
| docs/OPS_WATCHER.md | Watcher operations (Docker + host) | Aligned (forward line v5.x) | 2026-02-05 | Registry watcher operations, config-driven scope, DB outbox requirement; legacy snapshot watcher noted. |
| docs/INVENTORY.md | Runtime inventory | Aligned (forward line v5.x) | 2026-02-05 | Reference inventory (no file:line); update alongside code. |
| docs/GLOSSARY.md | Glossary | Aligned (forward line v5.x) | 2026-02-05 | Definitions updated to match v5.5 baseline (outbox/JSONL audit, rerank hooks). |
| docs/QUALITY.md | Quality | Aligned (forward line v5.x) | 2026-02-04 | QA guardrails + fitness gates aligned with v5.5 baseline. |
| docs/CONTRIBUTING.md | Contributing guide | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Practical quickstart; defers deep workflow to DEV_WORKFLOW/TESTING. |
| docs/CHANGELOG.md | Docs changelog | Legacy (archived) | 2026-02-05 | Historical; prefer STATUS/ROADMAP for current baseline and forward line. |
| docs/PRIVACY.md | Privacy | Aligned (forward line v5.x) | 2026-02-04 | Local-first, outbound only on optional remote LLMs. |
| docs/HEALTH.md | Health checks | Aligned (forward line v5.x) | 2026-02-04 | CLI health checks (ffmpeg/yt-dlp/outbox/ollama) + ci-smoke reference. |
| docs/LLM_BACKENDS.md | LLM backends | Aligned (forward line v5.x) | 2026-02-05 | Backends/env vars documented (chat + embeddings via Ollama/mock; OpenAI/DeepSeek chat). |
| docs/INFRASTRUCTURE.md | Infrastructure | Aligned (forward line v5.x, with known debt) | 2026-02-04 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/OPERATIONS.md | Operations | Aligned (forward line v5.x) | 2026-02-04 | Compose stack (api/worker/watcher/db) + v5.5 runtime runbooks; DB outbox canonical queue. |
| docs/INVENTORY.md | Inventory | Aligned (forward line v5.x) | 2026-02-05 | Reference inventory (no file:line); update alongside code. |
| docs/OVERVIEW_WS.md | Overview | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/DEPENDENCIES.md | Dependencies | Aligned (forward line v5.x) | 2026-02-05 | External deps aligned to current modules (transcribe, llm, watcher). |
| docs/PYTHON_VERSION_POLICY.md | Python version policy | Aligned (forward line v5.x) | 2026-02-05 | Repo requires Python >=3.12; CI smoke pinned to 3.12. |
| docs/OBSERVABILITY.md | Observability | Aligned (forward line v5.x) | 2026-02-04 | Updated for v5.5 baseline + v5.6 forward line counters; registry watcher health + DB outbox canonical queue clarified. |
| docs/OBSERVABILITY_STACK.md | Observability stack | Aligned (forward line v5.x) | 2026-02-04 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/AI_DEVELOPMENT.md | AI development | Aligned (forward line v5.x) | 2026-02-05 | Current dev-layer AI policy aligned to Core-6 guardrails and vault settings. |
| docs/DEV_WORKFLOW.md | Dev workflow | Aligned (forward line v5.x) | 2026-02-04 | TDD/docs-first workflow aligned with the v5.5 baseline. |
| docs/PROJECTOR.md | Projector | Legacy (archived) | 2026-02-05 | Historical reference; projector behavior is not current baseline. |
| docs/ALIGNMENT.md | Alignment | Legacy (archived) | 2025-12-07 | Legacy “Second-Brain” guide; superseded by SoT v4.10. |
| docs/SYSTEM_OVERVIEW.md | System overview (historical) | Legacy (archived) | 2025-12-07 | Historical v4.2 overview; superseded by SoT v4.10 docs. |
| docs/GLOSSARY.md | Glossary | Aligned (forward line v5.x) | 2026-02-05 | Definitions updated to match v5.5 baseline (outbox/JSONL audit, rerank hooks). |

## Historical / Archived (Architecture Deep Dives)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/history/SOT_4X_HISTORY.md | 4.x SoT history | Legacy (archived) | 2025-12-07 | Historical ladder and milestones for v4.x. |
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
| docs/runbooks/ingest.md | Runbook: ingest | Legacy (archived) | 2026-02-05 | Historical reference; prefer OPERATIONS + STARTUP_FULL_SYSTEM runbook. |
| docs/runbooks/RUNBOOK_GO_LIVE.md | Runbook: go-live checklist | Aligned (forward line v5.x) | 2026-01-28 | Go-live preflight updated for registry watcher + DB outbox. |
| docs/runbooks/RUNBOOK_STARTUP.md | Runbook: startup checklist | Legacy (archived) | 2026-02-05 | Historical reference; prefer RUNBOOK_STARTUP_FULL_SYSTEM + scripts/start_full_system.sh. |
| docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md | Runbook: full-system startup | Aligned (forward line v5.x) | 2026-02-05 | Brings up db/api/worker/watcher via scripts/start_full_system.sh; documents registry watcher + DB outbox requirement. |
| docs/runbooks/RUNBOOK_RUNTIME_GAP_TEST.md | Runbook: runtime gap test | Aligned (forward line v5.x) | 2025-12-23 | Verifies watcher registry ingest.vault.changed → worker heartbeat → /api/ask via scripts/gap_test_alpha.sh. |
| docs/RUNBOOK_RESET_TO_ZERO.md | Runbook: reset to zero | Aligned (forward line v5.x) | 2026-02-05 | Reset flow updated for DB outbox canonical queue + JSONL audit log. |
| docs/E2E_ALPHA.md | Alpha E2E contract | Aligned (forward line v5.x) | 2026-02-05 | Canonical alpha-up → alpha_e2e → alpha-smoke flow, runtime note cleanup, and status semantics. |
| docs/howto/memory.md | How-to: memory | Legacy (archived) | 2025-12-07 | Agent-memory guide superseded by ObjectStore/decisions in v4.10. |
| docs/settings/sample-flows/ingest.flow.md | Sample flow | Aligned (forward line v5.x, with known debt) | 2026-02-04 | Template for future planner/orchestrator ingest; not loaded in v4.10. |
| docs/settings/sample-agents/planner.md | Sample agent config | Aligned (forward line v5.x, with known debt) | 2026-02-04 | Planner config template for v5.x; unused in Reality-MVP. |
| docs/settings/sample-agents/normalizer.md | Sample agent config | Aligned (forward line v5.x, with known debt) | 2026-02-04 | Normalizer config template; runtime uses direct agents, not these YAMLs. |
| docs/settings/panel-actions.md | Panel action mappings | Aligned (v5.0 – PanelAgent runtime V1) | 2026-02-05 | Aligned with v5.0 PanelAgent Runtime V1 baseline; fallback mappings include promotion intent and runtime logging for unmapped actions. |
| docs/settings/prompts/classifier.v1.md | Prompt definition (classifier) | Aligned (forward line v5.x) | 2026-02-05 | Settings-backed registry prompt for classifier.v1; frontmatter + schema enforced. |
| docs/settings/prompts/ask.answer.v1.md | Prompt definition (ask answer) | Aligned (forward line v5.x) | 2026-02-05 | Settings-backed registry prompt for ask.answer.v1; references JSON Schema + standards. |
| docs/examples/ai-panel-example.md | AI panel example note | Aligned (forward line v5.x, with known debt) | 2026-02-04 | Panel fences + Swedish headings; dispatch optional. |
| docs/examples/vault_test_seed/evergreen-strategy.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/manual-policy.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/mixed-actions.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/reflection-journal.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/summary-request.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/unknown-action.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |

## Eval and Quality
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/eval.md | Eval stack | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Opt-in DeepEval/Ragas; env vars reflect app/eval/llm_client.py. |
| docs/SCORECARDS.md | Scorecards | Planned / not implemented | 2026-02-05 | Spec only; not enforced by runtime unless CI gates/tests consume it. |
| docs/QUALITY.md | Quality | Aligned (forward line v5.x) | 2026-02-04 | QA guardrails + fitness gates aligned with v5.5 baseline. |

## Agents / Codex Guidance
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/agents/AGENT_SPEC.md | Agent spec | Legacy (archived) | 2026-02-05 | Historical reference; prefer AGENTS + EVENTS for current contracts. |
| .codex/AGENTS.md | Coding agent guidance | Aligned (forward line v5.x, with known debt) | 2026-02-04 | Dev-layer system prompt; hierarchy/constraints/tests-first made current. |
| docs/codex/GUIDELINES.md | Codex guidelines | Legacy (archived) | 2026-02-05 | Historical guidelines; prefer DEV_WORKFLOW/AI_DEVELOPMENT and repo contracts. |

## ADRs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/adr/INDEX.md | ADR index | Baseline-only (v4.10, with known debt) | 2026-02-05 | Design records index; not runtime truth; may be partially outdated. |
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
| docs/scenarios/REALITY_MVP.md | Reality-MVP scenario | Legacy (archived) | 2026-02-05 | Historical reference; current baseline tracked in STATUS. |
| docs/PROTOCOL_SATELLITE_SYNC.md | Satellite sync protocol | Planned / not implemented | 2026-02-05 | Spec only; not implemented in v5.5 baseline. |

## Additional Docs (misc)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/LLM_BACKENDS.md | LLM backends | Aligned (forward line v5.x) | 2026-02-05 | Backends/env vars documented (chat + embeddings via Ollama/mock; OpenAI/DeepSeek chat). |
| docs/INFRASTRUCTURE.md | Infrastructure | Aligned (forward line v5.x, with known debt) | 2026-02-04 | Compose stack; DB outbox canonical, JSONL audit only. |
| docs/OVERVIEW_WS.md | Overview workspace | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/DEPENDENCIES.md | Dependencies | Aligned (forward line v5.x) | 2026-02-05 | External deps aligned to current modules (transcribe, llm, watcher). |
| docs/PYTHON_VERSION_POLICY.md | Python version policy | Aligned (forward line v5.x) | 2026-02-05 | Repo requires Python >=3.12; CI smoke pinned to 3.12. |
| docs/OBSERVABILITY.md | Observability | Aligned (forward line v5.x) | 2026-02-04 | Updated for v5.5 baseline + v5.6 forward line counters; registry watcher health + DB outbox canonical queue clarified. |
| docs/OBSERVABILITY_STACK.md | Observability stack | Aligned (forward line v5.x) | 2026-02-04 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/AI_DEVELOPMENT.md | AI development | Aligned (forward line v5.x) | 2026-02-05 | Current dev-layer AI policy aligned to Core-6 guardrails and vault settings. |
| docs/DEV_WORKFLOW.md | Dev workflow | Aligned (forward line v5.x) | 2026-02-04 | TDD/docs-first workflow aligned with the v5.5 baseline. |
| docs/PROJECTOR.md | Projector | Legacy (archived) | 2026-02-05 | Historical reference; projector behavior is not current baseline. |
| docs/ALIGNMENT.md | Alignment | Legacy (archived) | 2025-12-07 | Legacy “Second-Brain” guide; superseded by SoT v4.10. |
| docs/SYSTEM_OVERVIEW.md | System overview (historical) | Legacy (archived) | 2025-12-07 | Historical v4.2 overview; superseded by SoT v4.10 docs. |
| docs/GLOSSARY.md | Glossary | Aligned (forward line v5.x) | 2026-02-05 | Definitions updated to match v5.5 baseline (outbox/JSONL audit, rerank hooks). |
