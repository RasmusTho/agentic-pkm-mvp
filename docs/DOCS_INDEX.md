State: SoT v5.5 Reality-MVP baseline locked (watcher safety, panel action provenance, and concurrency guardrails); forward line v5.6 tracking LangGraph and reasoning rollouts while referencing `docs/STATUS.md#baseline-definition`.
Doc role: Core SoT
Authority: Canonical map of document roles and review status for the current repo; use it to determine whether a document is Core SoT, Reference, Plan, or Historical.
# Documentation Review Index — SoT v5.5 baseline + v5.x forward line

Central map of active and archived documentation artifacts in this repo. Use this index before treating any document as decision input.

Reading order:
1. Find the document here and identify its role.
2. Read the owning `Core SoT` doc first.
3. Read adjacent `Core SoT` docs for neighboring boundaries.
4. Read `Reference` docs for implementation or operational detail.
5. Treat `Plan` and `Historical` docs as context only.

For cross-cutting semantic, architecture, or planning work, use
`docs/plans/ONTOLOGY_EXECUTION_COORDINATION.md` to connect the active human/ontology chain to
parallel execution work.

Review status values:
- `Unreviewed` — not yet aligned in this total-review pass.
- `Aligned (forward line v5.x)` — matches the active SoT forward line (currently v5.6) on top of the locked v5.5 baseline.
- `Aligned (forward line v5.x, with known debt)` — mostly aligned to v5.x; see Notes for drift.
- `Baseline-only (v4.10)` — reflects the locked baseline; forward-line review pending.
- `Legacy (archived)` — historical snapshot; not current truth.
- `Deprecated` — kept only for reference; avoid for current work.

Docs still tagged `Baseline-only (v4.10)` in tables below should be read as foundation-only and queued for baseline/forward-line review; the active SoT baseline is v5.5.

The 2026 docs cleanup work is archived under `docs/archive/docs-refactor/`. The active reading path is defined by the role map below.

## SoT Notes
- v4.10 — locked Reality-MVP baseline (foundation only).
- v5.0 — PanelAgent Runtime V1 baseline on top of v4.10.
- v5.x — **active SoT forward line** (currently tracked through v5.5: PanelAgent planner pipeline + CLI-first orchestration on top of the watcher track) for Satellite Sync, Yggdrasil modules, Orchestrator/Reasoning 2.0.

## Root and Repo Docs
- `docs/EMBEDDINGS.md` — Normative embeddings spec (identity, guardrails, rebuild policy).
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| README.md | Top-level overview | Aligned (forward line v5.x) | 2026-02-05 | v5.5 baseline quickstart + invariants; points to DOCS_INDEX/STATUS/ARCHITECTURE. |
| docs/archive/docs-refactor/DOCS_REFACTOR_PLAN.md | Documentation simplification plan | Legacy (archived) | 2026-03-14 | Archived planning record for the 2026 docs cleanup effort; no longer an active decision surface. |
| docs/archive/docs-refactor/DOCS_SECOND_WAVE_CLEANUP.md | Second-wave cleanup matrix | Legacy (archived) | 2026-03-14 | Archived execution matrix for the completed cleanup wave. |
| docs/archive/docs-refactor/HISTORICAL_EXTRACTION_REVIEW.md | Historical extraction review | Legacy (archived) | 2026-03-14 | Archived extraction review used during the historical-doc cleanup pass. |
| docs/archive/github-templates/CHANGELOG.md | Repo change log (archived) | Legacy (archived) | 2025-12-07 | Moved from root; superseded by STATUS/ROADMAP v4.10. |
| docs/archive/github-templates/ISSUE_TEMPLATE_v4.6-objective.md | Issue template (historical) | Legacy (archived) | 2025-12-07 | Moved from .github; v4.6 template kept for history. |
| docs/archive/github-templates/pull_request_template.md | PR template (historical) | Legacy (archived) | 2025-12-07 | Moved from .github; v4.6 scaffold not current CI expectations. |
| docs/archive/README.md | Archive index | Legacy (archived) | 2025-12-17 | Index of archived docs; not part of the active doc set. |

## Core SoT Docs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/PROJECT_KERNEL.md | Project kernel (human flows + stability contracts) | Aligned (forward line v5.x) | 2026-03-21 | Canonical intent and stability contracts with trust/event/config anchors; now distinguishes broader life spheres/contexts from narrower operational domains while keeping bounded cross-scope overlap and long-lived artifact comprehensibility explicit. |
| docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md | Cognitive axes and spheres | Aligned (forward line v5.x) | 2026-03-20 | Clarifies that salience, self-relevance, durability, integration, and actionability are different kinds of semantics, and that overlapping spheres may model lived context better than exclusive domains. |
| docs/CONCEPTS/CONTEXT_AND_ARTIFACT_DIMENSIONS.md | Context and artifact dimensions | Aligned (forward line v5.x) | 2026-03-20 | Separates human context, artifact dimensions, and filesystem/catalog projection so future metadata and path design can evolve without hard semantic lock-in. |
| docs/CONCEPTS/CATALOG_PROJECTION_PRINCIPLES.md | Catalog projection principles | Aligned (forward line v5.x) | 2026-03-20 | Defines the current path/catalog posture: small icon-prefixed functional roots as bootstrap defaults, without treating the filesystem tree as the whole ontology. |
| docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md | Context model decision frame | Aligned (forward line v5.x) | 2026-03-21 | Clarifies the remaining context-model choices and the recommended narrowing from `domain`/`bridge` toward operational scope plus overlap-first semantics before architecture starts silently choosing the model through runtime scope, retrieval, or path behavior. |
| docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md | Context terminology contract | Aligned (forward line v5.x) | 2026-03-21 | Narrows the context vocabulary so `sphere`, `context`, `shared participation`, `operational scope`, and `explicit cross-scope allowance` can be distinguished before schema or architecture decisions harden the wrong semantics. |
| docs/CONCEPTS/CONTEXT_REPRESENTATION_POSTURE.md | Context representation posture | Aligned (forward line v5.x) | 2026-03-21 | Defines which context primitives should usually be durable markers, explicit relations, situational projections, or explicit permission objects, so schema and architecture work do not flatten the model too early. |
| docs/CONCEPTS/COGNITIVE_ONTOLOGY.md | Cognitive ontology (actors, context structures, artifacts, commitments, operations) | Aligned (forward line v5.x) | 2026-03-21 | Canonical human-first ontology for the second-brain domain; now gives first-class ontological treatment to context structures such as sphere, context, shared participation, operational scope, retained artifact, and primary human artifacts before schema/runtime concerns. |
| docs/CONCEPTS/USER_NEEDS_MODEL.md | User needs model | Aligned (forward line v5.x) | 2026-03-20 | Canonical statement of the human needs, burdens, and intended benefits the system is meant to serve; now includes contextual integrity across role identities, archive-brain needs, and long-lived artifact continuity beyond the current system. |
| docs/CONCEPTS/ONTOLOGY_VOCABULARY.md | Ontology vocabulary (canonical terms + drift map) | Aligned (forward line v5.x) | 2026-03-21 | Canonical normalized vocabulary for overloaded terms such as `note`, `object`, `source`, `agent`, `review`, `promotion`, `memory`, `domain`, and `bridge`, with ontology-layer guidance and rewrite priorities. |
| docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md | Artifact / projection / source contract | Aligned (forward line v5.x) | 2026-03-21 | Clarifies the ontological difference between artifacts and bounded runtime/store/search projections, and narrows `source` toward a canonical epistemic role rather than a universal base artifact type. |
| docs/CONCEPTS/STATE_AXES_CONTRACT.md | State axes contract (`review_state` and `maturity`) | Aligned (forward line v5.x) | 2026-03-20 | Canonical semantic contract for artifact review posture and maturity, including canonical value sets and legacy compatibility guidance. |
| docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md | Commitment layer contract | Aligned (forward line v5.x) | 2026-03-20 | Canonical semantic contract for human commitment structures including commitment, project, next action, waiting, review cycle, and their boundary against execution artifacts. |
| docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md | Agent ontology contract | Aligned (forward line v5.x) | 2026-03-20 | Canonical semantic contract for system agents, agent roles, delegation, authority boundaries, receipts, and human-first accountability. |
| docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md | Mirror and receipt decision | Aligned (forward line v5.x) | 2026-03-20 | Canonical decision that mirror artifacts and receipt artifacts are distinct first-class implementation concepts, while current runtime surfaces remain partially transitional. |
| docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md | Receipt / trace / accountability contract | Aligned (forward line v5.x) | 2026-03-21 | Clarifies the semantic difference between human-legible receipts, operational traces, and longer-lived audit records so runtime events, mirrors, and accountability surfaces do not collapse into one vague record type. |
| docs/CONCEPTS/TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md | Temporal validity / staleness contract | Aligned (forward line v5.x) | 2026-03-21 | Clarifies temporal validity, staleness, drift, and re-evaluation need as semantics distinct from both `maturity` and `review_state`, so the repo can model time-sensitive epistemic change without flattening it into lifecycle axes. |
| docs/CONCEPTS/INSTANCE_DEVICE_AND_REPLICA_CONTRACT.md | Instance / device / replica contract | Aligned (forward line v5.x) | 2026-03-21 | Clarifies instance identity, device roles, replicas, and instance provenance as local-first multi-device semantics distinct from artifact identity, so sync and eventual consistency do not become the de facto ontology. |
| docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md | Salience / attentional relevance contract | Aligned (forward line v5.x) | 2026-03-21 | Clarifies attentional salience, attentional relevance, open-loop pressure, and surfacing need as semantics distinct from artifact identity, context boundaries, lifecycle axes, and runtime `zone` overlays. |
| docs/CONCEPTS/CREATIVE_PROCESS_CONTRACT.md | Creative process contract | Aligned (forward line v5.x) | 2026-03-21 | Clarifies creative fragments, threads, iteration, revision, world continuity, and selective stabilization so creative and hobby/RPG work are not flattened into knowledge maturation, task management, or miscellaneous notes. |
| docs/CONCEPTS/LAYERING_MODEL.md | Layering model (Domain/Plane/Trust/Zone) | Aligned (forward line v5.x) | 2026-03-21 | Orthogonal boundary model; frames domain as operational scope, keeps explicit include/allowance modes, and clarifies that recurring cross-domain overlap can be normal without making `bridge` the whole ontology of overlap. |
| docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md | Trust semantics contract (assert/suggest/apply) | Aligned (forward line v5.x) | 2026-02-05 | Defines trust tiers, gating rules, write constraints, and receipts. |
| docs/CONCEPTS/EVENT_COMPATIBILITY_CONTRACT.md | Event/intent compatibility contract (versioning) | Aligned (forward line v5.x) | 2026-02-05 | Covers envelope invariants, versioning rules, idempotence, and new-event checklist. |
| docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md | Config-as-product contract | Aligned (forward line v5.x) | 2026-02-05 | Covers precedence, validation, rollback, audit, and portability rules for config. |
| docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md | Cloud connectors decision (watcher/inbox contracts, delta feed guardrails) | Aligned (forward line v5.x) | 2026-02-05 | Source memo from Swedish draft; anchors delta feed alternatives, watcher matrix, inbox taxonomy, and automation safety signals. |
| docs/contracts/OBSIDIAN_KNOWLEDGE_PORT.md | Obsidian knowledge port contract | Aligned (forward line v5.x) | 2026-03-08 | Spec-first contract updated for centralized `write_ops` boundary (writes/appends/URI conversion) and CI guardrails. |
| docs/CONCEPTS/PORTABILITY_CONTRACT.md | Portability contract (macOS + Windows) | Aligned (forward line v5.x) | 2026-03-20 | Defines portability hazards and rules for portable artifacts and paths; now distinguishes directly comprehensible core artifacts from more replaceable derived support structures. |
| docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md | Retention surface contract (historical archive-brain filename) | Aligned (forward line v5.x) | 2026-03-20 | Defines the retained-material surface as a first-class cognitive function for long-horizon retention, rediscovery, citation, and reuse; upstream of exposure and storage details. |
| docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md | Retention surface exposure contract (historical archive filename) | Aligned (forward line v5.x) | 2026-03-20 | Defines discovery→citation→preview→materialization modes and bounded retained-material exposure; downstream of the broader retention-surface function contract. |
| docs/CORE_CONTRACT.md | Core-6 contract (canonical) | Aligned (forward line v5.x) | 2026-02-05 | Canonical Core-6 semantic contract, ownership, and projection rules. |
| docs/NOTE_KIND_POLICIES.md | Note kind policies | Aligned (forward line v5.x) | 2026-02-05 | Policy profiles for kind routing and state-axis enablement. |
| docs/ARCHITECTURE.md | Architecture (SoT v5.x forward line on v5.5 base) | Aligned (forward line v5.x) | 2026-03-21 | Active runtime architecture source of truth; focused on the current runtime/data model, explicit about forward-line versus historical material, and now includes a layered reading model while narrowing `domain`/`bridge` and temperature-zone language to runtime compatibility rather than full semantics. |
| docs/CORE_RUNTIME_AGENTIC_LAB_BOUNDARY.md | Core Runtime vs Agentic Lab boundary contract | Aligned (forward line v5.x) | 2026-03-09 | Defines the operator-safe core boundary, opt-in lab boundary, ownership map, and non-goals for simplification work. |
| docs/CONCURRENCY.md | Concurrency + idempotency guardrails | Aligned (forward line v5.x) | 2026-03-14 | Normative concurrency/idempotency requirements for the current runtime, with representative validation coverage and commands. |
| docs/archive/architecture/SYSTEM_DESIGN_v4.10.md | System design / topology | Baseline-only (v4.10) | 2026-03-14 | Historical reference for v4.10 topology/external surfaces; moved out of the active docs root and not authoritative for the current baseline. |
| docs/STATUS.md | Operational snapshot | Aligned (SoT v5.5 baseline locked + forward line v5.6 planned) | 2026-03-14 | Current snapshot of runtime reality, verification status, and forward-line Now/Next/Later; historical ladders moved out of the active status surface. |
| docs/ROADMAP.md | Strategic roadmap | Aligned (SoT v5.5 baseline locked + forward line v5.6 planned) | 2026-03-21 | Forward line leans on the v5.5 baseline while v5.6 LangGraph/Reasoning stages are planned; v6 inquiry is now explicit about the ontology/runtime bridge, commitment-first modeling, retrieval vs orientation vs resurfacing, and surface/authority contracts. |
| docs/plans/V56_FORWARD_LINE.md | v5.6 forward line kickoff plan | Aligned (SoT v5.6 forward line) | 2026-02-05 | Now/Next/Later plan with acceptance criteria for watchers auto-run, LangGraph rollout, and orchestrator V2; links STATUS/ROADMAP for traceability. |
| docs/plans/V56_COMMITMENT_RUNTIME_SLICE.md | v5.6 commitment runtime slice | Aligned (forward line v5.x) | 2026-03-22 | Bounded enablement spec for the first commitment-runtime slice after state-axis separation; keeps commitment support distinct from artifact state axes, execution plans, and full v6 realization. |
| docs/plans/SPHERE_CONTEXT_ENABLEMENT_PREP.md | Sphere/context enablement prep | Aligned (forward line v5.x) | 2026-03-23 | Records the first bounded enablement wave for additive `sphere_membership` support in the relation store while keeping operational scope and retrieval defaults unchanged. |
| docs/plans/ONTOLOGY_ALIGNMENT_PLAN.md | Ontology alignment plan | Aligned (forward line v5.x) | 2026-03-19 | Plan for revising active SoT docs and selected runtime seams against the new cognitive ontology and normalized vocabulary. |
| docs/tracks/TRACK_WATCHER.md | Watcher track (v5.1–v5.4) | Aligned (forward line v5.x) | 2026-02-05 | Adds registry watcher as runtime standard; legacy snapshot watcher noted. |
| docs/tracks/TRACK_PANELAGENT_LANGGRAPH.md | PanelAgent LangGraph track (v5.5) | Aligned (forward line v5.x) | 2026-02-05 | PanelAgent catalog/decider modes, planner/orchestrator pipeline, promotion consumer. |
| docs/tracks/TRACK_AGENTOPS_A2A_MCP.md | AgentOps / A2A / MCP track | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Pattern harvest themes for events/A2A/tools/ops; some items are planned. |
| docs/tracks/TRACK_FITNESS_CI_CONTRACT.md | Fitness / CI contract | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Fitness gates are live; some reasoning/A2A/MCP gates are planned/flag-gated. |
| docs/COMPONENTS.md | Component catalog + dependency rules | Aligned (forward line v5.x) | 2026-02-05 | Component catalog updated to v5.5 outbox reality (DB canonical + JSONL audit). |
| docs/EMBEDDINGS.md | Embedding spec | Aligned (forward line v5.x) | 2026-02-05 | Normative spec for provider-aware embeddings (identity, dims, outbox events, rebuild rules). |
| docs/DIAGRAMS.md | Current architecture diagrams | Aligned (forward line v5.x) | 2026-03-14 | Current visual companion to ARCHITECTURE/COMPONENTS/EVENTS for system boundary and runtime flows. |
| docs/AGENTS.md | Agents overview | Aligned (forward line v5.x + LangGraph inner principle) | 2026-03-21 | System-level runtime agent architecture doc covering shared patterns, agent matrix, and coordination direction; development-time coding-agent instructions live in `docs/DEV_WORKFLOW.md` and `.codex/AGENTS.md`. |
| docs/EVENTS.md | Outbox/event contracts | Aligned (forward line v5.x) | 2026-02-05 | Canonical Outbox envelope + selected event meanings; compatibility anchored in EVENT_COMPATIBILITY_CONTRACT. |
| docs/archive/architecture/DIAGRAMS.md | Legacy diagrams | Legacy (archived) | 2026-03-14 | Legacy diagrams moved out of the active docs root; use `docs/DIAGRAMS.md` for the current runtime view. |
| docs/HUMAN-FLOWS.md | Human flows | Aligned (forward line v5.x) | 2026-03-21 | User-facing behavior contract for the current system; now explicitly covers life spheres/contexts, role identities, overlap-first semantics with bounded cross-scope permissions, heterogeneous device roles, archive-brain use, artifact continuity beyond the current runtime, and canonical human loops used to read runtime support paths. |
| docs/TESTING.md | Testing strategy | Aligned (forward line v5.x) | 2026-03-14 | Current testing contract covering baseline checks, deterministic slices, and quality/guardrail validation for the v5.5 runtime. |
| docs/PANEL_AGENT.md | PanelAgent / NoteInteractionAgent | Aligned (forward line v5.x) | 2026-03-13 | PanelAgent-specific runtime contract covering panel syntax, runtime behavior, events, and wiring; complements the system-level `docs/AGENTS.md`. |
| docs/runbooks/UAT_PANEL_WATCHER.md | UAT guide (panel + watcher) | Aligned (forward line v5.x) | 2026-02-05 | Registry watcher UAT flow with AI fence policy and UUID healing. |
| docs/archive/architecture/SYSTEM_YGGDRASIL_Modules_And_Flows.md | Module map | Legacy (archived) | 2026-03-14 | Historical module map retained for orientation and naming continuity; moved out of the active docs root. |
| docs/research/pattern-harvest-agentic-architecture.md | Research synthesis (outer/inner agent architecture) | Aligned (analysis, docs-only) | 2026-02-05 | Pattern harvest of events/A2A/tools/observability/config; backlog + Mermaid diagram; no runtime wiring. |
| docs/research/cognitive-semantics-literature-memo.md | Research synthesis (cognitive semantics, PKM, identity, archives) | Aligned (analysis, docs-only) | 2026-03-20 | Literature memo on relevance axes, context/spheres, role identity, and archive/retention semantics; explicitly distinguishes strong source support from provisional repo language. |

## Supporting Docs (Quality, Ops, Flows, Data)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/guardrails.md | Guardrails | Aligned (forward line v5.x) | 2026-02-05 | Runtime guardrails + concurrency safety aligned with v5.5 baseline. |
| docs/SECURITY.md | Security | Aligned (forward line v5.x) | 2026-02-05 | Local-first security posture; keys/env handling aligned with v5.5 baseline. |
| docs/PRIVACY.md | Privacy | Aligned (forward line v5.x) | 2026-02-05 | Local-first, outbound only on optional remote LLMs. |
| docs/DEPENDENCIES.md | Dependencies | Aligned (forward line v5.x) | 2026-02-05 | External deps aligned to current modules (transcribe, llm, watcher). |
| docs/OBSERVABILITY.md | Observability | Aligned (forward line v5.x) | 2026-03-13 | Runtime observability contract for heartbeats, counters, spans, and status interpretation. |
| docs/OPERATIONS.md | Operations playbook | Aligned (forward line v5.x) | 2026-03-14 | Top-level operator entrypoint focused on current runtime checks, watcher operations, and escalation to HEALTH, OBSERVABILITY, INFRASTRUCTURE, and runbooks. |
| docs/INFRASTRUCTURE.md | Infrastructure notes | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Compose stack (db/api/worker) for Reality-MVP. |
| docs/HEALTH.md | Health checks | Aligned (forward line v5.x) | 2026-03-13 | Health CLI behavior and runtime health contract; companion to OPERATIONS and OBSERVABILITY. |
| docs/LLM_ROUTING.md | LLM routing contract (router + fabric) | Aligned (forward line v5.x) | 2026-02-05 | Canonical routing/fabric contract; documents env precedence and debug surfaces. |
| docs/LLM.md | LLM integration | Aligned (forward line v5.x) | 2026-03-13 | Primary operational LLM document covering providers, env vars, backend scenarios, and limits; routing contract remains separate in `docs/LLM_ROUTING.md`. |
| docs/RETRIEVAL.md | Retrieval | Aligned (forward line v5.x) | 2026-02-05 | Hybrid retrieval + optional rerank hooks (`RERANK_ENABLE`/`RERANK_PROVIDER`). |
| docs/FRONTMATTER.md | Frontmatter rules | Aligned (forward line v5.x) | 2026-02-05 | Defines metadata layers, ownership, and the writing-surface write contract. |
| docs/ONTOLOGY_RUNTIME_BRIDGE.md | Ontology/runtime bridge | Aligned (forward line v5.x) | 2026-03-21 | Cross-layer reading guide linking human flows, compact semantic classes, persistence surfaces, and current runtime contracts without redefining the owning SoT docs. |
| docs/DATA_MODEL.md | Data model | Aligned (forward line v5.x) | 2026-03-21 | DB mirror of the Core-6 contract; now explicitly reminds readers that meaning-bearing artifacts, commitment structures, and system/receipt artifacts are different semantic classes even when runtime persistence sits nearby. |
| docs/DB_SCHEMA.md | DB schema | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Snapshot of current tables/views + DB outbox bootstrap; notes multiple historical Alembic heads. |
| docs/SETTINGS.md | Settings | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Settings compiler + registries documented; some areas are forward-looking. |
| docs/DEV_WORKFLOW.md | Developer workflow | Aligned (forward line v5.x) | 2026-03-21 | Primary development workflow and dev-layer AI policy; separates development-time coding agents from runtime system agents and consolidates change order, constraints, and required validation. |
| docs/templates/DOC_TEMPLATE.md | Document template | Aligned (forward line v5.x) | 2026-03-14 | Standard template for new docs; defines metadata, scope, authority, and writing structure. |
| docs/INVENTORY.md | Runtime inventory | Aligned (forward line v5.x) | 2026-02-05 | Reference inventory (no file:line); update alongside code. |
| docs/GLOSSARY.md | Glossary | Aligned (forward line v5.x) | 2026-02-05 | Definitions updated to match v5.5 baseline (outbox/JSONL audit, rerank hooks). |
| docs/CONCEPTS/DEFINITION_OWNERSHIP.md | Definition ownership convention | Reference | 2026-03-22 | Minimal working convention for precedence, downstream reference discipline, and semantic change visibility across Core SoT concept docs. |
| docs/legacy/CHANGELOG.md | Docs changelog | Legacy (archived) | 2026-02-05 | Historical; prefer STATUS/ROADMAP for current baseline and forward line. |
| docs/legacy/PLANNER.md | Planner contract | Legacy (archived) | 2026-02-05 | Historical reference; planner/orchestrator behavior has evolved. |
| docs/legacy/PROJECTOR.md | Projector | Legacy (archived) | 2026-02-05 | Historical reference; projector behavior is not current baseline. |
| docs/legacy/ALIGNMENT.md | Alignment guide | Legacy (archived) | 2025-12-07 | Legacy “Second-Brain” guide; superseded by SoT v4.10. |
| docs/legacy/ingest.md | Ingest (historical/current) | Legacy (archived) | 2026-02-05 | Historical reference; prefer HUMAN-FLOWS/OPERATIONS for current ingest. |
| docs/legacy/OVERVIEW_WS.md | Workspace overview | Legacy (archived) | 2025-12-07 | v4.3 walking-skeleton; superseded by SoT v4.10 docs. |
| docs/legacy/MEMORY.md | Memory (legacy overview) | Legacy (archived) | 2025-12-07 | Historical memory-layer description; not used in Reality-MVP. |
| docs/archive/architecture/SYSTEM_OVERVIEW.md | System overview (historical) | Legacy (archived) | 2026-03-14 | Historical v4.2 overview moved out of the active docs root; superseded by current SoT docs. |

## Historical / Archived (Architecture Deep Dives)
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/history/SOT_4X_HISTORY.md | 4.x SoT history | Legacy (archived) | 2026-03-14 | Historical ladder and milestones for v4.x; use only for background, not current-state decisions. |
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
| docs/runbooks/RUNBOOK_GO_LIVE.md | Runbook: go-live checklist | Aligned (forward line v5.x) | 2026-02-05 | Go-live preflight updated for registry watcher + DB outbox + Ollama embeddings defaults. |
| docs/runbooks/RUNBOOK_STARTUP.md | Runbook: startup checklist | Legacy (archived) | 2026-03-08 | Historical SoT v4.10 checklist; updated with Obsidian contract notes, but current runtime source remains RUNBOOK_STARTUP_FULL_SYSTEM + scripts/start_full_system.sh. |
| docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md | Runbook: full-system startup | Aligned (forward line v5.x) | 2026-03-08 | Canonical v5.x startup; includes strict Obsidian gate (`STARTUP_ENFORCE_OBSIDIAN`), health boundary checks, and startup-status telemetry fields. |
| docs/runbooks/RUNBOOK_RUNTIME_GAP_TEST.md | Runbook: runtime gap test | Aligned (forward line v5.x) | 2026-02-05 | Verifies watcher registry `panel.scan.requested` → index event (`index.embedding.created`) → /api/ask via scripts/gap_test_alpha.sh. |
| docs/runbooks/RUNBOOK_RESET_TO_ZERO.md | Runbook: reset to zero | Aligned (forward line v5.x) | 2026-02-05 | Reset flow updated for DB outbox canonical queue + JSONL audit log. |
| docs/runbooks/E2E_ALPHA.md | Alpha E2E contract | Aligned (forward line v5.x) | 2026-02-05 | Canonical alpha-up → alpha_e2e → alpha-smoke flow, runtime note cleanup, and status semantics. |
| docs/howto/memory.md | How-to: memory | Legacy (archived) | 2025-12-07 | Agent-memory guide superseded by ObjectStore/decisions in v4.10. |
| docs/settings/sample-flows/ingest.flow.md | Sample flow | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Template for future planner/orchestrator ingest; not loaded in v4.10. |
| docs/settings/sample-agents/planner.md | Sample agent config | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Planner config template for v5.x; unused in Reality-MVP. |
| docs/settings/sample-agents/normalizer.md | Sample agent config | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Normalizer config template; runtime uses direct agents, not these YAMLs. |
| docs/settings/panel-actions.md | Panel action mappings | Aligned (v5.0 – PanelAgent runtime V1) | 2026-02-05 | Aligned with v5.0 PanelAgent Runtime V1 baseline; fallback mappings include promotion intent and runtime logging for unmapped actions. |
| docs/settings/prompts/classifier.v1.md | Prompt definition (classifier) | Aligned (forward line v5.x) | 2026-02-05 | Settings-backed registry prompt for classifier.v1; frontmatter + schema enforced. |
| docs/settings/prompts/ask.answer.v1.md | Prompt definition (ask answer) | Aligned (forward line v5.x) | 2026-02-05 | Settings-backed registry prompt for ask.answer.v1; references JSON Schema + standards. |
| docs/examples/ai-panel-example.md | AI panel example note | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Panel fences + Swedish headings; dispatch optional. |
| docs/examples/vault_test_seed/evergreen-strategy.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/manual-policy.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/mixed-actions.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/reflection-journal.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/summary-request.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |
| docs/examples/vault_test_seed/unknown-action.md | Vault test seed | Aligned (forward line v5.x) | 2026-02-05 | Seed note for golden vault UAT. |

## Eval and Quality
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/eval.md | Eval stack | Aligned (forward line v5.x, with known debt) | 2026-02-05 | Opt-in DeepEval/Ragas; env vars reflect `app/eval/llm_client.py`. |

## Agents / Codex Guidance
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/agents/AGENT_SPEC.md | Agent spec | Legacy (archived) | 2026-02-05 | Historical reference; prefer AGENTS + EVENTS for current contracts. |
| .codex/AGENTS.md | Coding agent guidance | Aligned (forward line v5.x, with known debt) | 2026-03-21 | Dev-layer system prompt and repo-specific docs workflow for development-time coding agents; explicitly distinct from runtime/system-agent documents. |
| docs/codex/GUIDELINES.md | Codex guidelines | Legacy (archived) | 2026-02-05 | Historical guidelines; prefer DEV_WORKFLOW/AI_DEVELOPMENT and repo contracts. |

## ADRs
| Path | Scope | Review status | Last reviewed | Notes |
| --- | --- | --- | --- | --- |
| docs/adr/INDEX.md | ADR index | Baseline-only (v4.10, with known debt) | 2026-02-05 | Design records index; not runtime truth; may be partially outdated. |
| docs/adr/ADR-00X-agent-memory-v1.md | ADR (agent memory v1) | Legacy (archived) | 2025-12-07 | Historical PG JSONB memory; superseded by ObjectStore/decisions in v4.10. |
| docs/adr/ADR-00X-agent-memory-v42.md | ADR (agent memory v42) | Legacy (archived) | 2025-12-07 | Scoped PG memory/edges not implemented in v4.10. |
| docs/adr/0001-externa-komponenter.md | ADR external components | Legacy (archived) | 2025-12-07 | Superseded by SYSTEM_DESIGN_v4.10 and LLM/COMPONENTS docs. |
| docs/adr/0004-outbox-latency.md | ADR outbox latency | Partially outdated | 2026-02-05 | Targeted outbox→index <=2s; intent only (not enforced as CI gate); delta vs v5.5 baseline noted. |
| docs/adr/0005-per-loop.md | ADR PER loop | Partially outdated | 2026-02-05 | Historical rationale for shared PER base; v5.5 uses mixed loop/graph implementations; delta noted. |
| docs/adrs/ADR-00xx-promotion-agent.md | ADR promotion agent | Partially outdated | 2026-02-05 | Historical lifecycle intent; current baseline uses DB outbox + idempotent promotion consumer; delta noted. |

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
| docs/plans/PROTOCOL_SATELLITE_SYNC.md | Satellite sync protocol | Planned / not implemented | 2026-02-05 | Spec only; not implemented in v5.5 baseline. |
| docs/plans/ONTOLOGY_ALIGNMENT_PLAN.md | Ontology alignment plan | Plan | 2026-03-19 | Tracks documentation-first ontology alignment across active SoT docs and runtime seams. |
| docs/plans/ONTOLOGY_STATUS_NEXT_DECISIONS.md | Ontology status + next decisions | Plan | 2026-03-20 | Consolidates what is now established in the ontology pass, what runtime changes already align, and which decisions follow next. |
| docs/plans/ONTOLOGY_EXECUTION_COORDINATION.md | Ontology execution coordination | Plan | 2026-03-21 | Coordination contract for contributors, coding agents, and parallel workstreams: defines the authoritative reading path, how aligned plans should continue, and how work should be bucketed into current-state correction, enablement, or v6.0 target-state. |
| docs/plans/ARCHITECTURE_REVIEW_READINESS.md | Architecture review readiness | Plan | 2026-03-21 | Entry criteria for architecture/system-design review; context terminology and representation posture are now mostly ready, so the next pass can move into a narrow architecture check rather than more vocabulary work. |
| docs/plans/SPHERE_CONTEXT_ENABLEMENT_PREP.md | Sphere/context enablement prep | Plan | 2026-03-23 | Bounded v5.x enablement note for additive `sphere_membership` support through the canonical relation-store boundary, explicitly below the v6.0 target state. |
| docs/plans/V60_ARCHITECTURE_TARGET.md | v6.0 architecture target | Plan | 2026-03-21 | Wanted-state architecture target for larger semantics-aligned changes that should not be written into `docs/ARCHITECTURE.md` before they actually exist in the runtime. |
| docs/plans/USER_STORIES_AND_REQUIREMENTS.md | User stories and requirements | Plan | 2026-03-20 | Operational translation of human flows and user needs into user stories, requirement themes, and ontology implications for planning and implementation, including contextual integrity and artifact longevity. |
| docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md | Scenario acceptance matrix | Plan | 2026-03-20 | Scenario-level planning and validation surface connecting human flows and user needs to expected user outcomes, acceptance signals, and ontology consequences, including role-identity overlap and system-independent artifact continuity. |
| docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md | Runtime ontology normalization | Plan | 2026-03-19 | Concrete normalization recommendations for `note`, `review_state`, `maturity`, `promotion`, `plan`, and mirror/receipt semantics before field or event renames. |
| docs/plans/STATE_AXIS_SEPARATION_SPEC.md | State axis separation spec | Plan | 2026-03-19 | First implementation-spec draft for separating review posture, maturity, promotion transitions, and execution-plan semantics in the runtime. |
