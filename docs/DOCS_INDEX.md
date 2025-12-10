State: SoT v4.10 Reality-MVP (current core).
# Documentation Review Index — SoT v4.10

Central map of documentation and markdown artifacts in this repo. Review status values:
- `Unreviewed` — not yet aligned in this total-review pass.
- `Aligned (v4.10)` — matches SoT v4.10 Reality-MVP.
- `Aligned (v4.10, with known debt)` — mostly aligned; see Notes for drift.
- `Legacy (archived)` — historical snapshot; not current truth.
- `Deprecated` — kept only for reference; avoid for current work.

## Root and Repo Docs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| README.md | Top-level overview | Aligned (v4.10) | 2025-12-07 | Confirmed Reality-MVP overview/quickstart; points to SoT docs. |
| CHANGELOG.md | Repo change log (root) | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; archived under docs/archive/github-templates/CHANGELOG.md. |
| .github/ISSUE_TEMPLATE/v4.6-objective.md | Issue template (historical, root) | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; archived under docs/archive/github-templates/ISSUE_TEMPLATE_v4.6-objective.md. |
| .github/pull_request_template.md | PR template (historical, root) | Removed (2025-12-07) | 2025-12-07 | Removed in cleanup; archived under docs/archive/github-templates/pull_request_template.md. |
| docs/archive/github-templates/CHANGELOG.md | Repo change log (archived) | Legacy (archived) | 2025-12-07 | Moved from root; superseded by STATUS/ROADMAP v4.10. |
| docs/archive/github-templates/ISSUE_TEMPLATE_v4.6-objective.md | Issue template (historical) | Legacy (archived) | 2025-12-07 | Moved from .github; v4.6 template kept for history. |
| docs/archive/github-templates/pull_request_template.md | PR template (historical) | Legacy (archived) | 2025-12-07 | Moved from .github; v4.6 scaffold not current CI expectations. |

## Core SoT Docs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/ARCHITECTURE.md | Architecture (SoT v4.10) | Aligned (SoT v4.10 locked) | 2025-02-24 | Reality-MVP baseline; ingest hardening, external drop-folder path, status backend/CLI/GUI, orchestrator runtime V1; forward line is v5.x. |
| docs/SYSTEM_DESIGN_v4.10.md | System design / topology | Aligned (v4.10) | 2025-12-07 | Matches deployment topology and local surfaces. |
| docs/STATUS.md | Operational snapshot | Aligned (SoT v4.10 locked) | 2025-02-24 | Reality-MVP delivered; operational soak items noted; v5.x is the forward line. |
| docs/ROADMAP.md | Strategic roadmap | Aligned (SoT v4.10 locked) | 2025-02-24 | Reality-MVP baseline locked; operational acceptance noted; v5.x/Agentic PKM is the forward track. |
| docs/COMPONENTS.md | Component catalog + dependency rules | Aligned (SoT v4.10 locked) | 2025-02-24 | Reality-MVP components; v5.x will extend (PanelAgent, sync, richer orchestration). |
| docs/AGENTS.md | Agents overview | Aligned (SoT v4.10 locked) | 2025-02-24 | Reality-MVP agent set; v5.x Agentic extensions sit on top. |
| docs/PLANNER.md | Planner contract | Aligned (v4.10) | 2025-12-07 | Planner/PlanStep schema, guardrail layer, hierarchical planning loop. |
| docs/PANEL_AGENT.md | PanelAgent / NoteInteractionAgent | Aligned (v5.0 – PanelAgent step 1) | 2025-12-07 | Runtime loop documented (panel.intent.created, CLI run, ObjectStore source); next steps tied to v5.x roadmap. |
| docs/EVENTS.md | Outbox/event contracts | Aligned (v5.0 – PanelAgent step 1) | 2025-12-07 | Envelope + topic clusters aligned; adds `panel.intent.created`. |
| docs/DIAGRAMS.md | C4 diagrams | Aligned (v4.10) | 2025-12-07 | Diagrams reflect current topology. |
| docs/HUMAN-FLOWS.md | Human flows | Aligned (v5.0 – PanelAgent step 1) | 2025-12-07 | Panel flow notes manual CLI + panel.intent.created; ingest/ASK flows unchanged. |
| docs/SYSTEM_YGGDRASIL_Modules_And_Flows.md | Module map | Aligned (v4.10) | 2025-12-07 | High-level module map reviewed; Reality-MVP scope noted. |

## Supporting Docs (Quality, Ops, Flows, Data)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/CI.md | CI overview | Aligned (v4.10) | 2025-12-07 | ci-smoke/fitness gates documented; other workflows noted. |
| docs/TESTING.md | Testing strategy | Aligned (v4.10) | 2025-12-07 | Commands/markers match ci-smoke; eval marked opt-in. |
| docs/QUALITY.md | Quality gates | Aligned (v4.10) | 2025-12-07 | Clarified QA agent scope vs /api/ask; CI fitness gates noted. |
| docs/guardrails.md | Guardrails | Aligned (v4.10) | 2025-12-07 | Runtime guardrails + CI fitness gates; removed legacy thresholds. |
| docs/SECURITY.md | Security | Aligned (v4.10) | 2025-12-07 | Single-user/local; auth not wired; key handling guidance. |
| docs/PRIVACY.md | Privacy | Aligned (v4.10) | 2025-12-07 | Local-first, outbound only on optional remote LLMs. |
| docs/DEPENDENCIES.md | Dependencies | Aligned (v4.10) | 2025-12-07 | System deps + env matrix; ci-smoke defaults noted. |
| docs/OBSERVABILITY.md | Observability | Aligned (v4.10) | 2025-02-24 | JSON logs + span schema; status backend/CLI + interim GUI (status + ASK) share the snapshot service. |
| docs/OBSERVABILITY_STACK.md | Local observability stack | Aligned (v4.10) | 2025-12-07 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/OPERATIONS.md | Operations playbook | Aligned (v4.10) | 2025-12-07 | Reality-MVP stack (uvicorn/compose), CLI runbooks, targets noted. |
| docs/INFRASTRUCTURE.md | Infrastructure notes | Aligned (v4.10) | 2025-12-07 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/HEALTH.md | Health checks | Aligned (v4.10) | 2025-12-07 | CLI health checks (ffmpeg/yt-dlp/outbox/ollama) + ci-smoke reference. |
| docs/CLI.md | CLI reference | Aligned (v4.10) | 2025-12-07 | Updated commands (ingest/ask flows, alpha demos, health). |
| docs/LLM.md | LLM integration | Aligned (v4.10) | 2025-12-07 | Providers/env defaults (mock/Ollama/OpenAI/DeepSeek). |
| docs/LLM_BACKENDS.md | LLM backends | Aligned (v4.10) | 2025-12-07 | Providers mock/ollama/openai/deepseek; timeouts/keys noted. |
| docs/RETRIEVAL.md | Retrieval | Aligned (v4.10) | 2025-12-07 | Hybrid search + optional rerank; ASK graph defaults noted. |
| docs/FRONTMATTER.md | Frontmatter rules | Aligned (v4.10) | 2025-12-07 | Vault frontmatter minimal; UUID healing only. |
| docs/DATA_MODEL.md | Data model | Aligned (v4.10) | 2025-12-07 | Active store_objects/vector_index/relations; legacy tables noted. |
| docs/DATA_GOVERNANCE.md | Data governance | Aligned (v4.10) | 2025-12-07 | Stores + VaultMirror as truth; promotion gating flagged experimental. |
| docs/DB_SCHEMA.md | DB schema | Partially outdated | 2025-12-07 | Current store_* tables documented; legacy AMG tables retained as historical. |
| docs/SCORECARDS.md | Scorecards | Partially outdated | 2025-12-07 | Draft targets only; not enforced in Reality-MVP. |
| docs/PROJECTOR.md | Projector | Aligned (v4.10) | 2025-12-07 | Promotion projector emits audit/membership; no filesystem projection. |
| docs/ALIGNMENT.md | Alignment guide | Legacy (archived) | 2025-12-07 | Legacy “Second-Brain” guide; superseded by SoT v4.10. |
| docs/SETTINGS.md | Settings | Aligned (v4.10) | 2025-12-07 | Core env vars (STORE_BACKEND/LLM/metrics flags) documented. |
| docs/AUTH_RATE_LIMITING.md | Auth/rate limiting | Partially outdated | 2025-12-07 | Planned API key + slowapi; not implemented in Reality-MVP. |
| docs/ingest.md | Ingest (historical/current) | Aligned (v4.10) | 2025-12-07 | Vault-first ingest (CLI, UUID healing, mirror, HybridStore); legacy commands noted. |
| docs/OBSIDIANSYNC.md | Obsidian sync | Aligned (v4.10) | 2025-12-07 | Reality-MVP: manual CLI ingest; no active watcher; UUID healing only. |
| docs/OVERVIEW_WS.md | Workspace overview | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/AI_DEVELOPMENT.md | AI-assisted development policy | Aligned (v4.10) | 2025-12-07 | Matches current dev-layer policy and SoT references. |
| docs/DEV_WORKFLOW.md | Developer workflow | Aligned (v4.10) | 2025-12-07 | Current TDD/docs-first workflow aligned with v4.10. |
| docs/OPERATIONS.md | Operations playbook | Aligned (v4.10) | 2025-12-07 | Reality-MVP stack (uvicorn/compose), CLI runbooks, targets noted. |
| docs/INVENTORY.md | Runtime inventory | Aligned (v4.10) | 2025-12-07 | Key env vars/CLI surfaces; defaults mock/ollama. |
| docs/GLOSSARY.md | Glossary | Aligned (v4.10) | 2025-12-07 | Updated definitions for hybrid/rerank/outbox/health. |
| docs/QUALITY.md | Quality | Aligned (v4.10) | 2025-12-07 | QA guardrails vs ASK graph clarified; CI fitness gates noted. |
| docs/CONTRIBUTING.md | Contributing guide | Partially outdated | 2025-12-07 | Setup/tests template; defer to DEV_WORKFLOW/CI for current practice. |
| docs/CHANGELOG.md | Docs changelog | Aligned (v4.10, with known debt) | 2025-12-07 | Tracks doc updates; may lag implementations. |
| docs/PRIVACY.md | Privacy | Unreviewed | — |  |
| docs/HEALTH.md | Health checks | Aligned (v4.10) | 2025-12-07 | CLI health checks (ffmpeg/yt-dlp/outbox/ollama) + ci-smoke reference. |
| docs/LLM_BACKENDS.md | LLM backends | Aligned (v4.10) | 2025-12-07 | Providers mock/ollama/openai/deepseek; timeouts/keys noted. |
| docs/INFRASTRUCTURE.md | Infrastructure | Aligned (v4.10) | 2025-12-07 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/OPERATIONS.md | Operations | Aligned (v4.10) | 2025-12-07 | Reality-MVP stack (uvicorn/compose), CLI runbooks, targets noted. |
| docs/INVENTORY.md | Inventory | Aligned (v4.10) | 2025-12-07 | Key env vars/CLI surfaces; defaults mock/ollama. |
| docs/OVERVIEW_WS.md | Overview | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/DEPENDENCIES.md | Dependencies | Aligned (v4.10) | 2025-12-07 | System deps + env matrix; ci-smoke defaults noted. |
| docs/OBSERVABILITY.md | Observability | Aligned (v4.10) | 2025-02-24 | JSON logs + span schema; status backend/CLI + interim GUI (status + ASK) share the snapshot service. |
| docs/OBSERVABILITY_STACK.md | Observability stack | Aligned (v4.10) | 2025-12-07 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/AI_DEVELOPMENT.md | AI development policy | Aligned (v4.10) | 2025-12-07 | Matches current dev-layer policy and SoT references. |
| docs/DEV_WORKFLOW.md | Dev workflow | Aligned (v4.10) | 2025-12-07 | Current TDD/docs-first workflow aligned with v4.10. |
| docs/scenarios/REALITY_MVP.md | Scenario walkthrough | Aligned (v4.10) | 2025-12-07 | Matches e2e pipeline test and ASK expectations. |

## Architecture Subdocuments
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/architecture/next-steps.md | Architecture future/bridge | Legacy (archived) | 2025-12-07 | Historical v4.3 bridge; superseded by STATUS/ROADMAP v4.10. |
| docs/architecture/obsidian_integration.md | Obsidian integration deep dive | Legacy (archived) | 2025-12-07 | v4.3 watcher-based flow; superseded by INGEST/OBSIDIANSYNC (CLI, UUID healing). |
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
| docs/uml/README.md | UML overview | Legacy (archived) | 2025-12-07 | Supervisor-era UML; canonical diagrams in DIAGRAMS.md. |
| docs/uml/agent_sequence.md | UML sequence | Legacy (archived) | 2025-12-07 | Run_agent supervisor loop; not part of Reality-MVP. |
| docs/uml/agent_components.md | UML components | Legacy (archived) | 2025-12-07 | Legacy agent service components; see ARCHITECTURE/DIAGRAMS. |

## Runbooks, How-to, Settings Examples, and Examples
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/runbooks/ingest.md | Runbook: ingest | Aligned (v4.10, with known debt) | 2025-12-07 | Troubleshooting vault ingest/outbox; matches current CLI path. |
| docs/howto/memory.md | How-to: memory | Legacy (archived) | 2025-12-07 | Agent-memory guide superseded by ObjectStore/decisions in v4.10. |
| docs/settings/sample-flows/ingest.flow.md | Sample flow | Partially outdated | 2025-12-07 | Template for future planner/orchestrator ingest; not loaded in v4.10. |
| docs/settings/sample-agents/planner.md | Sample agent config | Partially outdated | 2025-12-07 | Planner config template for v5.x; unused in Reality-MVP. |
| docs/settings/sample-agents/normalizer.md | Sample agent config | Partially outdated | 2025-12-07 | Normalizer config template; runtime uses direct agents, not these YAMLs. |
| docs/settings/panel-actions.md | Panel action mappings | Aligned (v4.10, with known debt) | 2025-12-07 | Fallback mappings for PanelAgent; dispatch flag-gated. |
| docs/examples/ai-panel-example.md | AI panel example note | Aligned (v4.10, with known debt) | 2025-12-07 | Panel fences + Swedish headings; dispatch optional. |

## Eval and Quality
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/eval.md | Eval stack | Aligned (v4.10) | 2025-12-07 | Opt-in DeepEval/Ragas suites; skips when deps/LLM missing. |
| docs/SCORECARDS.md | Scorecards | Partially outdated | 2025-12-07 | Draft targets only; not enforced in Reality-MVP. |
| docs/QUALITY.md | Quality | Aligned (v4.10) | 2025-12-07 | QA guardrails vs ASK graph clarified; CI fitness gates noted. |

## Agents / Codex Guidance
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/agents/AGENT_SPEC.md | Agent spec | Aligned (v4.10, with known debt) | 2025-12-07 | Reality-MVP agent contracts; notes on stubs (chunks/outbox/index) and parked agents. |
| .codex/AGENTS.md | Coding agent guidance | Aligned (v4.10) | 2025-12-07 | Dev-layer system prompt; hierarchy/constraints/tests-first made current. |
| docs/codex/GUIDELINES.md | Codex guidelines | Aligned (v4.10) | 2025-12-07 | Quick checklist pointing to .codex/AGENTS and SoT anchors. |

## ADRs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/adr/INDEX.md | ADR index | Aligned (v4.10, with known debt) | 2025-12-07 | Index updated with legacy/partial states for ADRs. |
| docs/adr/ADR-00X-agent-memory-v1.md | ADR (agent memory v1) | Legacy (archived) | 2025-12-07 | Historical PG JSONB memory; superseded by ObjectStore/decisions in v4.10. |
| docs/adr/ADR-00X-agent-memory-v42.md | ADR (agent memory v42) | Legacy (archived) | 2025-12-07 | Scoped PG memory/edges not implemented in v4.10. |
| docs/adr/0001-externa-komponenter.md | ADR external components | Legacy (archived) | 2025-12-07 | Superseded by SYSTEM_DESIGN_v4.10 and LLM/COMPONENTS docs. |
| docs/adr/0004-outbox-latency.md | ADR outbox latency | Partially outdated | 2025-12-07 | Targeted outbox→index <=2s; no worker/CI gate in Reality-MVP. |
| docs/adr/0005-per-loop.md | ADR PER loop | Partially outdated | 2025-12-07 | Base PER class exists; agents use bespoke flows; not enforced. |
| docs/adrs/ADR-00xx-promotion-agent.md | ADR promotion agent | Partially outdated | 2025-12-07 | Promotion/projector stub only; event-driven file moves are future work. |

## Legacy and Archive
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/archive/README.md | Archive index | Legacy (archived) | — |  |
| docs/archive/NEXT-STEPS.md | Archived plan | Legacy (archived) | — |  |
| docs/archive/transcription.md | Archived transcription doc | Legacy (archived) | — |  |
| docs/archive/SoT-v4.1.md | Legacy SoT v4.1 | Legacy (archived) | — |  |
| docs/archive/TESTS.md | Archived tests doc | Legacy (archived) | — |  |
| docs/archive/RUNBOOK.md | Archived runbook | Legacy (archived) | — |  |
| docs/archive/decision-log-2025-10.md | Decision log | Legacy (archived) | — |  |
| docs/archive/VERSIONING.md | Versioning (archived) | Legacy (archived) | — |  |
| docs/archive/codex_plan.md | Codex plan (archived) | Legacy (archived) | — |  |
| docs/legacy/PROJECT_OVERVIEW.md | Legacy overview | Legacy (archived) | — |  |
| docs/legacy/TODO.md | Legacy TODO | Legacy (archived) | — |  |

## Scenario and Protocol Docs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/scenarios/REALITY_MVP.md | Reality-MVP scenario | Aligned (v4.10) | 2025-12-07 | Matches e2e pipeline test and ASK expectations. |
| docs/PROTOCOL_SATELLITE_SYNC.md | Satellite sync protocol | Planned / not implemented | 2025-12-07 | Draft v5.x master/satellite sync; not implemented in Reality-MVP. |

## Additional Docs (misc)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/LLM_BACKENDS.md | LLM backends | Aligned (v4.10) | 2025-12-07 | Providers mock/ollama/openai/deepseek; timeouts/keys noted. |
| docs/INFRASTRUCTURE.md | Infrastructure | Aligned (v4.10) | 2025-12-07 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/OVERVIEW_WS.md | Overview workspace | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/DEPENDENCIES.md | Dependencies | Aligned (v4.10) | 2025-12-07 | System deps + env matrix; ci-smoke defaults noted. |
| docs/OBSERVABILITY.md | Observability | Aligned (v4.10) | 2025-02-24 | JSON logs + span schema; status backend/CLI + interim GUI (status + ASK) share the snapshot service. |
| docs/OBSERVABILITY_STACK.md | Observability stack | Aligned (v4.10) | 2025-12-07 | Prometheus/Grafana compose scrape `/metrics`. |
| docs/AI_DEVELOPMENT.md | AI development | Aligned (v4.10) | 2025-12-07 | Current dev-layer AI policy (docs-first, mocks/defaults). |
| docs/DEV_WORKFLOW.md | Dev workflow | Aligned (v4.10) | 2025-12-07 | TDD/docs-first workflow aligned with SoT v4.10. |
| docs/PROJECTOR.md | Projector | Aligned (v4.10) | 2025-12-07 | Promotion projector emits audit/membership; no filesystem projection. |
| docs/ALIGNMENT.md | Alignment | Legacy (archived) | 2025-12-07 | Legacy “Second-Brain” guide; superseded by SoT v4.10. |
| docs/SYSTEM_OVERVIEW.md | System overview (historical) | Legacy (archived) | 2025-12-07 | Historical v4.2 overview; superseded by SoT v4.10. |
| docs/GLOSSARY.md | Glossary | Aligned (v4.10) | 2025-12-07 | Updated definitions for hybrid/rerank/outbox/health. |
| docs/MEMORY.md | Memory design (historical) | Legacy (archived) | 2025-12-07 | v4.3 memory plan; superseded by DATA_MODEL/ARCHITECTURE v4.10. |

## Settings / Vault / System / Inbox
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| System/Dashboards/inbox.md | System dashboard | Aligned (v4.10) | 2025-12-07 | Minimal vault dashboard for system inbox notes. |
| System/Dashboards/conflicts.md | System dashboard | Aligned (v4.10) | 2025-12-07 | Minimal vault dashboard for conflicts inbox. |
| System/Settings/system.md | System settings | Partially outdated | 2025-12-07 | Illustrative sync settings; not enforced in Reality-MVP. |
| Inbox/System-changes.md | Inbox/system changes | Aligned (v4.10) | 2025-12-07 | Log stub for system change notes. |
| vault/README.md | Vault README | Aligned (v4.10, with known debt) | 2025-12-07 | Vault surface overview; ingest via CLI, UUID healing, panels optional. |
| vault/0_Atlas/Home.md | Vault note | Aligned (v4.10, with known debt) | 2025-12-07 | Home navigation; points to settings/inbox/desks; panels optional. |
| vault/@Desk/galaxy-test.md | Vault note | Example / sandbox | 2025-12-07 | Sample note with UUID; non-authoritative. |
| vault/@Desk/Test fil 2.md | Vault note | Example / sandbox | 2025-12-07 | Empty example note. |
| vault/Konfigurera.md | Vault note | Example / sandbox | 2025-12-07 | Placeholder/config sandbox. |
| vault/Test fil1.md | Vault note | Example / sandbox | 2025-12-07 | Empty example note. |
| vault/@Inbox/Desicion science for data scientists 2.md | Vault inbox note | Example / sandbox | 2025-12-07 | Sample inbox content; non-authoritative. |
| vault/settings/Overview.md | Vault settings overview | Example / sandbox | 2025-12-07 | Human-facing overview; runtime config is env + _system YAML. |
| vault/@Settings/README.md | Vault settings README | Example / sandbox | 2025-12-07 | Explains settings examples; not parsed by runtime. |
| vault/@Settings/global.md | Vault settings | Example / sandbox | 2025-12-07 | Illustrative global settings; runtime uses env/code defaults. |
| vault/@Settings/agents/promotion.md | Vault agent settings | Example / sandbox | 2025-12-07 | Promotion settings example; runtime does not ingest. |
| vault/@Settings/agents/classifier.md | Vault agent settings | Example / sandbox | 2025-12-07 | Classifier settings example; runtime does not ingest. |
| vault/@Settings/agents/qa.md | Vault agent settings | Example / sandbox | 2025-12-07 | QA settings example; runtime does not ingest. |
| vault/@Settings/agents/reviewer.md | Vault agent settings | Example / sandbox | 2025-12-07 | Reviewer settings example; runtime does not ingest. |
| vault/@Settings/providers.md | Vault provider settings | Example / sandbox | 2025-12-07 | Provider defaults example; runtime uses env vars and defaults. |

## Prompts / Data Context
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| data/context/prompts/context_summarizer.md | Prompt context | Aligned (v4.10, with known debt) | 2025-12-07 | Manual prompt snippet; not wired into runtime, English-only, review-before-write. |

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
