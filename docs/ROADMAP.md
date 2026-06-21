State: SoT v5.5 baseline locked (Reality-MVP + watchers/panel policy); v5.6 delivery line closed; v6.0 seams baseline shipped at capability-seam level (orientation/resurfacing/commitment-domain/context-dimensions runtime seams plus closed v6.0 capability spec directories); broader v6.0 runtime consumption (Chat surface, full Panel/Chat capability consumption, commitment surfacing, persistence-surface runtime separation) is deferred to v6.1+. Post-v5.6 follow-ups are tracked separately for LangGraph/Reasoning expansion, Orchestrator V2 hardening, A2A/MCP lifecycle cleanup, and local verification hardening. Contextualization Layer docs/spec package (#1093–#1097) fully delivered 2026-05-19: life-wide taxonomy (#1093), media artifact contract (#1094/PR #1113), ingestion/triage policy (#1095/PR #1114), vault templates (#1096/PR #1115), vault audit runbook (#1097/PR #1116), roadmap refresh (#1098/PR #1117). Agent Memory implementation issues #1079–#1085 are shipped, and the orientation MemoryCandidate intent seam is shipped as a read-only handoff/trace boundary; remaining memory runtime follow-up centers on explicitly authorized durable receipt/store/query work. Companion UI real-note rendering, browser dev server, workspace state, and note-independent orientation/re-entry seams are delivered in dev/staging form; production hardening and packaging remain planned. High-churn execution movement state moved to BuilderOps `RoadmapExecutionItem` records and the generated `roadmap-execution` projection in #1508.
Doc role: Plan
Authority: Strategic sequencing and forward-looking delivery/follow-up framing; owner/current-state docs win on shipped reality and present-tense behavior. Current execution movement, active issues, blockers, last movement, next decision, and shipped refs are BuilderOps operational records, not roadmap authority.
Owner: Product / architecture forward line
Temporal class: strategic
Review cadence: biweekly
Source of truth: mixed
Last reviewed: 2026-06-18
Last verified against: docs/STATUS.md, docs/ARCHITECTURE.md, docs/DOCS_INDEX.md, docs/OPERATIONS.md, docs/HUMAN-FLOWS.md, docs/CONTEXTUAL_RELEVANCE_ENGINE/README.md, docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md, docs/CONCEPTS/RELEVANCE_EVALUATOR_CONTRACT.md, docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md, docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md, app/relevance/evaluator.py, app/relevance/materialization.py, app/relevance/now_surface.py, companion-ui/companion-app/companion_ui/workspace/now_surface.py, tests/relevance/test_vault_native_moments.py, merged PRs #1948/#1977/#2092/#2097/#2098/#2133/#2137/#2140/#2142, and current repo state at 522acf4b on 2026-06-18

# Roadmap — Strategic Control

This roadmap is forward-looking and skimmable. Deep track details live under `docs/tracks/`. Current truth stays in `docs/ARCHITECTURE.md` and `docs/STATUS.md`; removed history snapshots live only in git history.

BuilderOps roadmap execution boundary: `docs/ROADMAP.md` remains the repo strategic sequencing
surface. Daily movement state belongs in BuilderOps `RoadmapExecutionItem` records and the generated
`roadmap-execution` projection documented in `docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md`.
Use that projection for operational views of theme, capability, status, active issues, blockers,
last movement, next decision, and shipped refs. Do not update this roadmap merely to record routine
movement.

System Entry Point execution is now a completed Companion UI capability delivery, not a broader
product-baseline promotion. Parent #1782 closed through #1795 validation after the entry-state,
re-entry, overlay-host, palette, capture, memory, receipts, system-map, guidance, settings, and
state-gallery child surfaces shipped. Remaining context-lane/place-band decisions stay parked under
the gated follow-up issue #1796 and BuilderOps execution records.

Major roadmap reset boundary: `docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md` is the accepted
strategic reset input for the next sequencing pass. It freezes normal backlog-wave generation until
current-state evidence, owner-doc posture, and decision gates are reconciled. The reset does not
promote runtime capabilities by itself: `docs/ARCHITECTURE.md` and `docs/STATUS.md` still win on
shipped reality, and GitHub/BuilderOps movement remains execution state rather than product truth.

Security sequencing boundary: the security architecture spine and first review inputs
(`docs/SECURITY_ARCHITECTURE.md`, `docs/SECURITY_TRUST_BOUNDARIES.md`,
`docs/SECURITY_DATA_FLOWS.md`, `docs/security/API_SECURITY_MATRIX.md`, and
`docs/security/STRIDE_LITE_REVIEW_2026_06_04.md`) are now available as design-hardening inputs.
They guide future security work but do not, by themselves, change the roadmap baseline, widen
runtime exposure, or claim public internet readiness.

Contextual Relevance Engine sequencing: CRE-01/CRE-02 are delivered concept-contract groundwork,
CRE-03 shipped the vault-native pull moment plus glance-surface slice, and CRE-04 shipped the
governed in-app proactive reach-out loop (#1964): the relevance tick records a reach-out or
deliberate-suppression receipt per candidate and projects threshold-cleared in-app nudges. The
remaining reach-out work is OS-push delivery and external connectors, which stay deferred; routine
issue movement for this line belongs in BuilderOps RoadmapExecutionItem records.

## Status vocabulary
- **Shipped** — merged to main; code/doc exists.
- **Operationally accepted** — proven on real vault/external samples with runbook/soak.
- **Baseline locked** — scope frozen; only bugfixes allowed.
- **Post-delivery follow-up** — bounded work discovered after a delivery line closed; does not reopen that line unless the owner explicitly reclassifies it as a release blocker.
- **Planned / In progress** — tracked work not yet shipped.

## Baselines
- **SoT v4.10 (foundation)** — Reality-MVP ingest/ASK/observability runtime; now subsumed by the v5.5 baseline.
- **SoT v5.5 (baseline locked)** — watcher auto-run gate + panel action provenance + concurrency/idempotency guards (dedup queue, promotion consumer dedup, optimistic writes); baseline ships with the new settings compiler and CLI controls.
- **SoT v6.0 seams (shipped)** — capability-seam baseline that lands on top of v5.5/v5.6 without changing safety properties. Shipped surfaces: closed capability spec directories (`docs/FINDING_AND_REORIENTING/`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/`, `docs/SEPARATING_PERSISTENCE_SURFACES/`, `docs/COMMITMENT_AS_FIRST_CLASS/`, `docs/SCOPE_SPHERE_SITUATED_IDENTITY/`); minimal read-only orientation runtime (`app/orientation/runtime.py`) and resurfacing decision surface (`app/resurfacing/runtime.py`); commitment domain model and minimal commitment runtime (`app/domain/commitments.py`, delivered via #688); context-dimensions payload + runtime threading (`app/context_dimensions.py`, delivered via #730/#731/#733); read-only Chat cognition scaffold (`app/chat/read_only_cognition.py`) and flag-gated canvas session slice (`CANVAS_ENABLED=1`). Explicitly **not** included in v6.0 seams baseline: full Chat mutation surface, full Panel/Chat consumption of orientation/resurfacing, next-action / review-cycle commitment surfacing, persistence-surface runtime separation, relation-aware signal fusion. Those are v6.1+ work and remain tracked under their owning capability spec directories.

## Now / Next / Later
- **Now**
  - **Major roadmap reset and SoT reconciliation** — active sequencing guard. Do not generate the next normal backlog wave from target-state docs. First reconcile shipped runtime, delivered seams, owner-doc promotion state, BuilderOps projection boundaries, and open GitHub state using `docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md`.
  - **SBS operationalization initiative** — target-state architecture adoption and transition control. Purpose: make the 2030 target SBS actionable through ADRs, contracts, mapping, registers, fitness rules, issue tracking, and PR impact classification without claiming shipped runtime behavior. Status: target-state docs/contracts resident; the operating layer (operating model, roadmap, hardened debt register, prioritized fitness roadmap, review-gate fallback policy) is resident; implementation enforcement remains in progress. Tracking issue: #2337. Operating-model umbrella: #2378. Delivery issue set: #2355 with child delivery slices #2356-#2363. Operational usage (how to classify work, Definition of Ready/Done, owner-doc writeback, review-gate fallback policy, source-of-truth matrix) is owned by `docs/architecture/SBS_OPERATING_MODEL.md`; initiative phase intent/status is owned by `docs/architecture/SBS_ROADMAP.md` (Phase 0 architecture residency → Phase 5 opportunistic physical separation). Contract-first adoption phase plan: Phase 0 decision anchoring, Phase 1 current-to-target mapping, Phase 2 critical contracts, Phase 3 first enforcement rails, Phase 4 containment adapters, Phase 5 selective physical split (`docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`). Source docs: `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`, `docs/architecture/SBS_OPERATING_MODEL.md`, `docs/architecture/SBS_ROADMAP.md`, `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`, `docs/architecture/SBS_BOUNDARY_REGISTER.md`, `docs/architecture/SBS_TRANSITION_DEBT.md`, and `docs/architecture/SBS_FITNESS_RULES.md`. Non-goals: no immediate fourteen-module split, no no-vault rewrite, no Obsidian removal, no full distributed consensus, and no target-state-as-shipped claim. First slices: ActiveContextSet, GovernedWriteProtocol, ArtifactContract, StorePort, ContextBundle, MemoryRecord, ExecutionRequest, and ReplicationEnvelope.
  - **Integrated Runtime v1 release line (#1874)** — active integration sequencing item for route parity, readiness matrix, Panel staging persistence, golden-path UAT, negative-safety UAT, and docs reduction.
  - **Contextual Relevance Engine** — CRE-03 shipped the vault-native pull-only moments and a
    read-only glance projection, and CRE-04 (#1964) shipped the governed in-app proactive reach-out
    loop on the relevance tick; remaining reach-out work (OS-push delivery, external connectors) is
    deferred to bounded follow-up issues.
  - **v5.5 baseline lock + safety guard** — runtime/startup defaults `WATCHER_AUTO_EXEC=1`, but operators can force emit-only mode with `WATCHER_AUTO_EXEC=0`; allowlists, dedup/idempotency, optimistic writes, and write-guard/status signals remain the real enablement gates for safe rollout.
  - Keep the shipped PanelAgent LangGraph decider opt-in and watcher policy auto-exec plumbing stable under the v5.5 baseline guardrails while broader rollout stays gated.
  - Watcher → panel → planner/orchestrator automation with safety limits now includes dedup reports, promotion consumer visibility, and explicit skipped receipts.
  - Vault-first config validation (panel wiring, watcher, outbox) with schema enforcement and `python -m app.cli settings-explain`.
- **Closed v5.6 delivery line**
  - **Low-risk autonomy + automated sync validation** — delivered through child slices and final parent receipt: #355 is closed COMPLETED with iCloud sync transport validated end to end and an upper-bound transport latency receipt on 2026-04-13. Remaining #432/#433 work is follow-up infra/statistical timing, not a blocker for #355 closure. Source Anchor: AUTO-LOW-RISK-AUTONOMY
  - **Environment contract follow-through** — implement the remaining docs-first environment contract slices from `docs/ENVIRONMENTS.md` in bounded steps: explicit runtime environment selection and environment-scoped vault/store separation are shipped, and environment-aware operator diagnostics are delivered via Issue #265 / PR #272; remaining follow-through should stay bounded and avoid changing the shared architecture contracts.
  - **Companion note + Note Context rollout hardening** — the core companion-note and Note Context implementation is shipped, and the active doc-sync correction has landed. Delivery receipt: Issue #229, PR #237. Any remaining rollout verification or cleanup should be captured as new bounded follow-up issues rather than treated as missing first implementation.
  - **Quality Wave: Registry Watcher Evaluation Stack** — shipped and now serves as the v5.6 rollout gate via `docs/TESTING.md`, `docs/QUALITY_WAVE_IMPLEMENTATION.md`, and `docs/quality_wave/README.md`. Delivery receipt: PRs #197, #198, #199, #200, #201, #202, #210.
  - **ReasoningFacade + broader graph adoption** — the shared `ReasoningFacade` seam is present; the PanelAgent decider migration is shipped via Issue #230 / PR #236, and the review-flow agent migration is delivered via Issue #231. Delivery receipt: #230 (PR #236), #231 (closed COMPLETED). Source Anchor: RF-ADOPTION
    - Rationale: prevents pattern fragmentation; broader agent adoption should route reasoning/tool calls through the existing shared facade instead of introducing new direct call paths. Remaining phased rollout to Promotion/Reviewer/Hygiene is post-v5.6 adoption work.
  - **Orchestrator V2 pilot slice** — initial V2 runtime with flagged parallel execution and plan-graph scheduling shipped. Implements: `ORCHESTRATOR_VERSION=v1|v2` flag, dependency-aware step scheduling, parallel execution with ThreadPoolExecutor, event/trace compatibility with V1, compensation/rollback via `compensate_fn` metadata, retry metadata handling for failed steps, checkpoint/resume with configurable interval persistence, and retry/backoff observability for retry and terminal failure paths. Per-tool timeout via `tool_timeout_seconds` setting is supported on both V1 and V2 (see `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md`). No repo-wide A2A/runtime delivery SLA or plan-level timeout budget is claimed. Delivery receipt: Issue #250 (pilot), Issue #251 (compensation), Issue #252 (checkpoint/retry handling), Issue #444 (checkpoint/resume hardening), Issue #445 (retry/backoff observability), Issue #446 (timeout/SLA contract). Source Anchor: ORCHV2-TDD
    - Back-compat preserved: `ORCHESTRATOR_VERSION=v1` (default) uses existing sequential V1; `v2` selects parallel pilot with compensation.
    - Post-v5.6 slices: timeout discriminator bug #456, and possible later plan-level timeout budgets or repo-wide A2A/runtime delivery SLA work if owner docs promote those beyond the delivered #446 timeout/SLA contract.
  - PanelAgent 2.0 timeline: <!-- PA2-ROLLUP -->
    - v5.5C: decider — shipped (rule default + opt-in LLM mode + fallback + telemetry).
    - v5.6 shipped/accepted: engine-neutral cognition seam (#244, PR #249), freeform catalog-driven proposal path (#241, PR #248), suggested checkbox writeback for uncertain/freeform panel proposals (#242), multi-step plans (#243, PR #302), and real-vault acceptance (#240) now have a delivery receipt on the Alpha vault.
    - Broader expansion beyond the current PanelAgent 2.0 slices remains bounded; keep new work broken down from the owner docs / tracks before widening scope.
    - v5.7: advanced (panel versioning, cross-note coordination) remains future-line work and should stay in roadmap form until a governing slice issue exists.
  - Vault-as-GUI settings compiler (`@Settings` / System/Config) now covers panel-action catalogs, watcher settings, and outbox paths with CI schema checks (v5.6 track).
- **Post-v5.6 follow-ups**
  - LangGraph rollout to additional agents (Promotion/Reviewer/Hygiene) in phases:
    - Note-hygiene phased ReasoningFacade adoption is shipped via #543 as a facade-seam alignment slice; mutation authority and KnowledgePort write routing remain unchanged, and this does not claim a full Deep Agent/LangGraph baseline rollout.
    - Phase 1: single pilot agent behind a flag; AgentState + graph parity tests green.
    - Phase 2: two agents; planner/orchestrator integration stable; event/A2A contracts unchanged.
    - Phase 3: broader adoption; runtime metrics + rollback plan validated.
  - A2A/MCP orchestration routing with deterministic adapters and audit; current in-process A2A routing is implemented and covered, and parent lifecycle issue #359 is closed. A local registry-backed MCP ToolProvider boundary is implemented, and a flagged remote MCP multiplex seam with deterministic local fallback now exists; dynamic discovery and broader remote server integration remain separate follow-ups.
  - Orchestrator V2 timeout retry discriminator cleanup shipped via #456 / PR #458; possible later work is plan-level timeout budgets or repo-wide A2A/runtime delivery SLA only if owner docs promote that scope.
  - Runtime health and docs-index validation hardening: #334/#365 shipped deterministic checks; #441/PR #439 restored the richer runtime verifier contract and made the docs-index guard compatible with repo-local v6 spec metadata.
  - Canvas-session scaffolding is shipped in bounded form through #598/#599/#600/#601, and owner-doc promotion has landed via subsequent docs work: session logs, body-scoped co-authoring, governance-intent routing, and a gated API/CLI surface now exist behind `CANVAS_ENABLED`. Broader hybrid Panel/Chat behavior and richer Chat cognition remain separate follow-up work.
- **Later**
  - Watcher auto-exec of panel plans with guardrails and rollback; richer panel actions (summary/reply) via tool/MCP boundary.
  - PanelAgent 2.0 expansion beyond the current slices remains bounded even after real-vault acceptance; break new behavior into smaller tracked slices first.
  - Reasoning/reflective layers with eval gates; expanded observability counters for orchestration/A2A.
  - Collaboration/multi-user after single-user flows are stable.
  - Release-channels specification phase complete (Issues #609–#615 closed 2026-05-02): all six task specs (channel identity, DB-per-channel isolation, promotion plan contract, migration reversibility classification, concurrency rule, rollback contract) are delivered under `docs/RELEASE_CHANNELS/README.md`; promotion and rollback skills are authored; the go-live acceptance procedure is now documented at `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md` with a machine-readable receipt template. Operational acceptance — executing the runbook against the real vault and recording a pass receipt — is the outstanding step before the channel model is treated as fully live.
  - `v6.0` architecture target (**active design direction** — see `Capability-Based Architecture & Agent Evolution` above): a baseline-aware target operating model that preserves the
    vault-first / registry-watcher / DB-outbox / companion-note continuity baseline while making
    the next operating boundary explicit: `observation -> normalization/contract -> admission -> execution`.
    - Make the ontology/runtime bridge explicit so human loops, ontology classes, and runtime contracts can be read together without pretending they are the same layer.
    - Test commitment-first modeling where open loops, projects, waiting states, and execution accountability are not flattened into generic note state.
    - Separate retrieval, orientation, and resurfacing as related but distinct runtime concerns.
    - Clarify authority across writing, retention, system, runtime, and execution-record surfaces so receipt-bearing actions remain inspectable.
    - Treat current domain/zone/mirror/promotion findings as current-state bug fixes or enabling changes unless a later implementation slice explicitly realizes the v6 target state.
  - `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md` remains the active sequencing plan for turning the v6 capability specs into cognitive-support work. Priority 1 (salience/staleness), Priority 2 (scope/sphere/identity), Priority 3 (receipts plus SUGGEST/APPLY gating), and Priority 4 (retrieval capability extraction) are now closed on GitHub; Priority 5 (minimal commitment runtime) is now closed on GitHub (#688).
  - Context bundle implementation (CONTEXT-BUNDLES-01 through -06) is fully delivered at the typed-contract layer: schema (#895/PR #931), retrieval emission (#896), orientation consumer (#946/PR #950), resurfacing consumer (#947/PR #951), write-proposal linkage (#948/PR #952), and receipt recording (#949/PR #954). Parent feature #894 closed 2026-05-15. Production route wiring (API integration, real vault emission) is now shipped: the Context Bundles production runtime integration wave (#1559, closed 2026-06-04) delivered the construction route (#1560), real retrieval emission (#1562), orientation/resurfacing consumption (#1563), governed write-proposal linkage (#1564), and a read-only receipt projection (#1565), with owner-doc promotion in #1566. Agent Memory implementation issues #1079–#1085 are shipped and cover MemoryCandidate model, memory store, retrieval integration, and companion-note-aware handling; the v6.1 orientation MemoryCandidate intent seam is shipped as read-only awareness plus trace-backed handoff. Later work remains durable receipt/store/query authority and explicitly filed integration/consumption slices.
  - **Contextualization Layer docs/spec deliveries (2026-05-14–2026-05-19):**
    - Life-wide artifact taxonomy delivered at `docs/CONTEXTUALIZATION_LAYER/LIFE_WIDE_ARTIFACT_TAXONOMY.md` (#1078 / PR #1086). Names artifact classes, lifecycle, authority, provenance, work-relation axes across the full life-wide PKM scope.
    - Context activation semantics delivered at `docs/CONTEXTUALIZATION_LAYER/CONTEXT_ACTIVATION_SEMANTICS.md` (#943 / PR #1073 + owner-doc promotion #1077). Defines use-right semantics per class and lifecycle state.
    - Metadata contract updated to align with life-wide taxonomy (#1093 / PR — aligned in the same branch cycle). Adds concrete examples for evergreen note, source/literature note, media note, email summary, shopping list, agentic memory candidate, machine mirror.
    - Media artifact contract delivered at `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md` (#1094 / PR #1113). Defines roles, subtypes, authority/privacy rules, and metadata shape for photos, screenshots, scans, receipts, manuals, contracts.
    - Ingestion and triage policy delivered at `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md` (#1095 / PR #1114). Defines ingestion pipeline states, per-pipeline flows, and AI/governance boundaries for all major artifact types.
    - Life-wide vault templates delivered at `docs/examples/vault-templates/` (#1096 / PR #1115). Eleven example templates covering project MOC, area dashboard, media note, email summary, YouTube source, book source, literature note, decision record, shopping list, receipt scan note, weekly review.
    - Vault audit and migration strategy runbook delivered at `docs/runbooks/UNMANAGED_OBSIDIAN_VAULT_AUDIT.md` (#1097 / PR #1116). Safe phased approach for applying the taxonomy to unmanaged vaults.
    - These are docs/spec deliveries only. No runtime enforcement is claimed. No vault migration happened.
  - **v6.x — Cognitive mediation capability taxonomy** (architecture alignment step, #981): the capability taxonomy for cognitive mediation is now defined in `docs/CAPABILITY_CONTRACT_MODEL.md` (`Cognitive mediation capability classes`). It defines seven capability classes (orientation, proposal, retrieval, clarification, synthesis/review, governance-bearing execution, repair/maintenance), distinguishes intent-space from capability-space, defines proposal-only semantics as distinct from execution semantics, and adds authority/risk metadata fields (`capability_class`, `authority_class`, `mutation_risk`, `requires_human_gate`, `requires_policy_gate`, `receipt_required`). `docs/PANEL_AGENT.md` now references the taxonomy. This is a docs-only alignment step; no runtime capability behavior is claimed. Runtime consumption of the taxonomy is v6.1+ work.
  - **v6.x — Knowledge Compilation and Memory Curation** (follow-up after v6.0 structural separation): a bounded planning line for how the system supports knowledge compilation and memory curation over time, grounded in the `Capture -> clarify -> place`, `Retrieve -> orient -> act`, and `Review -> reclassify -> promote/archive` human loops from `docs/HUMAN-FLOWS.md`. Semantic boundaries, artifact classes, review/promotion posture, and suggested event families are defined in `docs/plans/V6X_KNOWLEDGE_COMPILATION_AND_MEMORY_CURATION.md` under parent feature #803. The first runtime-foundation slices are now shipped as pure, provider-free, non-canonical support seams: runtime artifact contracts (#1534), deterministic proposal builders (#1535), read-only reorientation packet assembly (#1536), explicit admission handoff (#1537), and a diagnostic trace harness (#1538). Storage/API/event/UI integration and durable promotion remain unclaimed future work unless bounded follow-up slices are filed.

## Capability-Based Architecture & Agent Evolution

This section defines the v6 direction without changing the locked SoT v5.5 guarantees or the delivered v5.6 contracts.
It follows the design rules in `docs/DESIGN_PRINCIPLES.md`: principles first, structure second, sequencing third, implementation detail elsewhere.
The working plan detail for this section lives in `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`.

Sequencing rule:
- v5.6 should be read here primarily as a delivered invariant and stabilization layer, not as a strict linear prerequisite list for every v6 design decision.
- The design goal is to preserve the contracts v5.6 established while allowing v6 structural work to be defined in parallel.

Decisions already fixed for this direction:
- ASK is deprecated as the architectural center rather than expanded.
- Retrieval is treated as a reusable capability rather than a standalone agent.
- Interaction is primary on the user-facing side; retrieval, reasoning, ingestion, and indexing remain foundational capabilities used by different interaction surfaces and automation paths.
- Deep Agents start only after structural separation is in place.
- Deep Agents start in a read-only Chat slice because read-only cognition is the safer first rollout posture; a bounded canvas-session surface now exists behind `CANVAS_ENABLED`, but richer Chat cognition, hybrid Panel/Chat behavior, and broader governed mutation expansion remain future work.
- Execution remains governed and mediated; reasoning alone must not trigger mutation.
- The long-term system spans manual through automated and reactive through proactive behavior under governance.

## Phase 0 — Stabilization (v5.6 delivered; post-v5.6 follow-up mode)

- Preserve the delivered v5.6 enablement work needed for structural separation.
- Track defects and lifecycle drift as post-v5.6 follow-ups instead of reopening the delivery line by default.
- Keep current runtime contracts stable and deterministic.
- No Deep Agents in production mutation flows.
- No execution outside the controlled action layer.

## Phase 1 — v6.0 Baseline (Structural Separation)

Introduce explicit operating layers:

- Human canonical layer:
  - vault notes as the human writing/reading surface
- Replication layer:
  - companion note + vault note continuity set and multi-device convergence posture
- Observation layer:
  - registry watcher, Panel/API/CLI inputs, and runtime signals
- Normalization / contract layer:
  - event envelopes, panel/action contracts, settings provenance, tool descriptors, scope/provenance checks
- Execution layer:
  - controlled actions only; no LLM direct mutation
- Derived machine layer:
  - rebuildable stores, indexes, retrieval projections, status, traces, and metrics
- Governance/admission layer:
  - policies, admissibility, provenance, approval, idempotency, and surface authority checks

Deliverables:

- ASK fully deprecated; no new development.
- Retrieval extracted into a capability layer.
- Interaction, cognition, execution, memory, and governance separated clearly enough to evolve independently.
- Template-based bounded agents and reusable capabilities can coexist without collapsing into one central agent.
- Governed mutation paths remain explicit and mediated across interaction and automation surfaces.
- The v6 target operating model classifies proposed changes as current-state bug fixes, enabling changes, or target-state changes before implementation begins.

## Abstraction Layer Hardening (v6.x planned)

Current-state inventory: 12 explicit abstraction protocols/ABCs span storage (ObjectStore, VectorIndex, RelationIndex, DecisionsStore, DispatcherStore), LLM/reasoning (LLM Adapter, BasePlanner, ReasoningFacade, EmbeddingProvider), vault (KnowledgePort, VaultPort), sync (SyncLayer), retrieval (BaseReranker), and execution (PlanExecutor). Six gaps were identified where concrete modules are wired together by callers without a shared protocol:

**Priority 1 — highest ROI, natural companions to Phase 1 structural separation:**
- `AgentProtocol` — no shared protocol for concrete agents in `agents/`; orchestrator, policy layer, and dispatcher each carry bespoke agent-handling logic. A protocol enables uniform reasoning about permissions, timeout, and budget across all agent implementations.
- `SearchPort` — `retrieval/`, `search/`, and `relevance/` are composed directly by callers. A single `SearchPort` (query → ranked results) decouples every consumer agent from retrieval topology (vector-only, hybrid, re-ranked) and makes retrieval strategies swappable. Required before the retrieval quality improvements below can be A/B tested safely.

**Priority 2 — enabling for Deep Agent introduction (Phase 2):**
- `ChunkIndexPipeline` — `ingest/` and `indexer/` share no protocol; a typed pipeline interface enables swappable chunking and indexing strategies without touching ingest orchestration.
- `ConfigPort` — three config systems (ENV, `config/`, `settings/`) are accessed directly; a unified access point improves testability and unblocks future hot-reload or remote config.

**Priority 3 — independent, pick up opportunistically:**
- `NotificationPort` — outbound delivery (webhooks, push, TTS trigger) is scattered across modules; a unified egress abstraction simplifies the outbox→consumer contract.
- Agent memory store alignment — `agent_memory/` state may not route through the same `ObjectStore` protocol as the rest of the system, creating a parallel persistence track that complicates the storage abstraction story.

Sequencing: Priority 1 items belong in Phase 1 deliverables. Priority 2 items are prerequisites or natural companions for Phase 2 (Deep Agent Introduction). Priority 3 items are independent and non-blocking.

### Retrieval quality improvements (post-SearchPort)

These are deferred until `SearchPort` exists as the safe boundary for swapping strategies:

- **RRF over weighted sum** — current hybrid scoring uses hardcoded 0.5/0.4/0.1 weights (BM25/semantic/overlap). Reciprocal Rank Fusion is more robust to score-scale differences between lexical and dense signals. Note: the weights are intentional as a first-pass trust encoding; RRF should be validated not to degrade the trust hierarchy before replacing them.
- **Provenance-aware signal weights** — the retrieval scoring has two deliberate trust layers: (1) signal trust (BM25 = exact match = high confidence; semantic = fuzzy = slightly lower), and (2) source provenance trust (vault origin +0.4, own_reviewed +0.2, evergreen +0.2, own_raw +0.1). The long-term direction is to make Layer 1 weights configurable per source type — AI-generated memory artifacts should receive a lower semantic weight than human-authored notes because LLM-generated text is semantically dense and inflates retrieval rank artificially.
- **Query expansion / HyDE** — single-pass retrieval misses abstract or personal queries ("what was I exploring about X last year"). HyDE (generate a hypothetical answer, embed it) or multi-query (N rephrased variants, merged via RRF) are the standard remedies. Most valuable for PKM-style retrospective queries.
- **Eval framework** — no automated signal when retrieval quality regresses. RAGAS or an LLM-as-judge faithfulness/relevance scorer in CI is the strategic gap with highest risk exposure.

### Retrieval / embedding topology ratified (baseline captured, 2026-06-20)

The current retrieval and embedding topology is now captured as decision records so the hardening
work above reasons against a ratified baseline rather than implicit code reality (#2317, part of the
RAG/memory decomposition epic #2314):

- **`docs/adr/ADR-0024-retrieval-topology.md`** — ratifies the shipped topology: in-memory hybrid
  serving (`app/retrieval/hybrid.py`), weighted linear fusion `combined = 0.5*bm25_norm +
  0.4*emb_norm + 0.1*overlap_bonus`, rerank-off by default, with the durable Postgres/pgvector
  `PgVectorIndex` as the forward **direction** (not yet the serving path). RRF / HyDE /
  low-trust-weights / eval remain named future work behind `SearchPort` (the items listed above).
- **`docs/adr/ADR-0023-embedding-egress-gemini-fallback.md`** — ratifies Ollama-primary embedding
  with an **identity-preserving** Gemini `text-embedding-004` @ 768 auto-fallback (normalization-
  matched, query==document), re-index on mixed identity. It supersedes the no-generic-fallback
  invariant as a scoped exception (not a blanket reversal).

These are docs/decision-only ratifications (no behavior change). The runtime work they ratify against
(durable-spine migration; Gemini adapter wiring; aligning the `DEFAULT_EMBED_DIM` code constant to
`768`) is tracked under #2314 / #2292 / #2296 / #2297. (ADR numbering note: #2317 originally named
ADR-0015/0016, but those plus 0017–0022 were already taken by the SBS series; the ratifications use
the next free numbers 0023/0024, with 0025 reserved for sibling #2318.)

## Deep Agents as runtime layer exploration (future work)

<!-- Deep Agents runtime exploration -->

Deep Agents are an **optional future operational harness and runtime layer** for planning, decomposition, and multi-step reasoning. They are not shipped, not active in the current baseline, and must not be described as cognition authority or semantic authority.

Design intent (not yet implemented):
- Deep Agents operate as a runtime execution harness on top of the capability layer — they compose capabilities (retrieval, orientation, resurfacing, context building) through planning, not by owning or replacing them.
- Deep Agents remain downstream of governance: WriteGuard, policy gates, and event receipts apply to any mutation intent surfaced through a Deep Agent harness, exactly as they do for any other execution path.
- Deep Agent runtime state is transient orchestration state, not canonical cognition. Vault notes remain the durable human-canonical surface.
- Introduction is gated on structural separation (Phase 1 — v6.0 Baseline) being complete. No Deep Agents in production mutation flows until that separation is verified.

This section names Deep Agents as a runtime layer exploration to distinguish it from cognition-authority claims, ASK-style centralization, or governance bypass. Any future implementation must satisfy the explicit rules in `Phase 2 — Deep Agent Introduction` below.

## Phase 2 — Deep Agent Introduction (Thin Slice, Post-v6.0)

<!-- deep-agents-runtime-exploration -->

Introduce Deep Agents under strict constraints.

Framing:
- Deep Agents are an **optional future operational harness / runtime layer**, not a shipped capability and not the cognitive mediation layer of the system.
- Like LangGraph (see `docs/ARCHITECTURE.md :: LangGraph runtime substrate`), Deep Agents are runtime/execution substrate: they orchestrate planning and multi-step reasoning under existing governance, capability contracts, and authority boundaries.
- Adopting a Deep Agents harness must not promote runtime orchestration state into canonical cognition. The vault remains the primary durable human cognitive surface (`docs/HUMAN-FLOWS.md :: vault-first human surface`), and orchestration state remains operational and rebuildable (`docs/ARCHITECTURE.md :: runtime state vs canonical cognition`).
- Deep Agents introduction is exploratory: no production Deep Agents integration is claimed in the current baseline or in the v6.0 seams. Future adoption is conditional on structural separation, observable runtime evidence, and explicit owner-doc promotion.

Scope:

- Chat surface only.
- Read-only Deep Agent mode.
- No system mutation.
- No execution access.

Capabilities:

- planning
- decomposition
- multi-step reasoning
- retrieval orchestration

Explicit rule: "Deep Agents cannot execute actions or mutate system state."

Deliverables:

- The read-only Chat slice becomes the first safe cognition sandbox for Deep Agents.
- Initial implementation routes read-only Chat cognition through `ReasoningFacade` and returns planning metadata only; execution and mutation pathways remain denied.
- Deep Agent behavior remains decoupled from execution authority.

## Phase 3 — Panel Integration (Controlled Cognition)

Extend Deep Agents into Panel.

Scope:

- planning only
- proposal generation only

Constraints:

- No direct execution.
- All actions must go through:
  - policy checks
  - validation
  - event pipeline

Panel remains a primary command-oriented mutation surface, but not the only governed mutation path in the long-term system.

## Phase 4 — Execution Layer Expansion (Future)

Introduce controlled execution evolution under governance and sandboxing.

Explicit rule: "LLM reasoning must never directly trigger execution."

## Phase 5 — Governance & Scaling

- Strengthen governance layer.
- Introduce:
  - policy enforcement engines
  - audit trails
  - execution constraints
- Consider NemoClaw-like patterns (optional).

## Interaction Model Evolution

- Panel = command surface (`intent -> action`).
- Chat = canvas-shaped exploration surface (`externalize -> manipulate -> optionally commit through governance`).
- Hybrid Panel/Chat integration is a future implementation lane governed by
  `docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md`; the docs-only schema
  preserves Panel as primary command surface without making it the exclusive authoritative intent
  source.
- The broader system spans manual, assisted, reactive automation, and proactive automation under governance.
- Both share:
  - `AgentState`
  - capability layer
  - cognition layer (Deep Agents, future)

## ASK Decomposition

- ASK marked deprecated as an architectural center.
- Retrieval extracted into capability layer.
- No new central retrieval agent should be created to recentralize the architecture.

## Fitness Functions Enforced in CI
- `pytest -q -c /dev/null -m "not pg and not alpha_llm"` is the primary smoke gate in CI.
- `ops/quality/baselines.yaml` writes the `GATES` block and must report `ok=true` for merges; CI pipelines rely on that signal.
- Docker smoke checks ensure the worker emits the `worker starting` log and that the stack responds to health probes.
- Latency thresholds are provisional while the stack is still stabilizing; they can be re-tuned as the system matures to avoid blocking CI before the runtime is fully healthy.

## Reality-MVP acceptance (operator outcomes)
- Vault ingest and external ingest run successfully on real samples with provenance preserved; no data loss.
- ASK API returns answers with sources/latency; interim GUI surfaces status + ASK.
- Observability shows per-plane object counts, ingest runs/errors, and ASK usage.
- Orchestrator runtime V1 executes internal tools (external ingest) via plan or direct CLI; green CI (`pytest -q -m "not pg"`, memory backend) and docs aligned.

## Reality-MVP scope (operator view)
1) Vault ingestion of selected folders into ObjectStore with Core-6 projection and provenance; Outbox events emitted; indexed into VectorIndex.
2) Minimal external ingest of real samples into `external_raw`; stored and indexed without creating Obsidian notes.
3) ASK API returning `{uuid, title, origin, zone?, path/source_ref}` with latency; hybrid retrieval across planes.
4) Observability backend + interim GUI surfacing object counts, ingest runs/errors, ASK usage.
5) Orchestrator runtime V1 available via CLI/plan path for external ingest; future LangGraph/MCP remains additive.

## Version ladder (summary)
| Version | Intent | State |
| --- | --- | --- |
| v4.10 | Reality-MVP baseline | Baseline locked |
| v5.0 | PanelAgent Runtime V1 | Shipped |
| v5.1–v5.4 | Watcher track (ingest/panel CLI, policy, ergonomics) | Operationally accepted |
| v5.5A/B | Panel planner pipeline + CLI-first orchestration/promotion consumer | Shipped |
| v5.5C/D | Panel LangGraph decider + watcher auto-exec; watcher→planner/orchestrator automation | Shipped |
| v5.6 | Engine-neutral cognition seam (PA2-ENGINE-SEAM, shipped), freeform catalog-discovery (shipped), suggested checkbox writeback for uncertain/no-checkbox panel proposals (shipped), multi-step plans (shipped, PR #302), real-vault acceptance (accepted on Alpha vault for #240), Companion note/doc-sync cleanup, shared ReasoningFacade + LangGraph rollout, Orchestrator V2 (flagged), Vault-as-GUI settings compiler, A2A in-process routing, iCloud transport chain validated + `.git.nosync` fix shipped (#421), low-risk autonomy + sync validation parent #355 closed | Closed delivery line; statistical sync/infra hardening remains follow-up work; A2A lifecycle issue #359 and timeout discriminator bug #456 are closed; local runtime/docs validation drift was fixed by #441 / PR #439 |
| v6.0 seams | Capability-seam baseline on top of v5.5/v5.6: closed capability spec directories, minimal orientation/resurfacing runtimes, commitment domain + minimal runtime, context-dimensions payload + runtime threading, read-only Chat cognition scaffold, flag-gated canvas session slice. Preserves all v5.5/v5.6 safety properties. | Shipped (seam-level baseline) |
| v6.1+ | Broader v6.0 target-state work that the seams enable: full Chat mutation surface, Panel/Chat capability consumption, next-action/review-cycle commitment surfacing, persistence-surface runtime separation, relation-aware signal fusion. Target described in `docs/plans/V60_ARCHITECTURE_TARGET.md`. | Planned (post-v6.0 seams) |

## Tracks (details moved)
- Watcher track details: `docs/tracks/TRACK_WATCHER.md`
- PanelAgent LangGraph track: `docs/tracks/TRACK_PANELAGENT_LANGGRAPH.md`
- AgentOps/A2A/MCP hardening: `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`
- Fitness/CI contract: `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`
- Historical ladder: removed from the live repo; use git history if the old snapshot is needed.

## Delivery Control Plane (GitHub)

The repo now adopts a GitHub-based delivery control plane for implementation work:

- Docs/ADRs/owner docs define intent and architecture.
- GitHub Issues are the canonical task contract.
- GitHub Project v2 is the delivery state machine.
- Local Agent Issue Dispatcher is the active hot-path claim/heartbeat coordination layer; GitHub
  Issues, labels, PRs, and Project state remain the durable lifecycle truth.
- Coding agents execute only bounded Issues.
- PR + CI are the validation loop.

Delivery lifecycle:

`Backlog -> Ready -> In Progress -> Review -> Done`

Builder-agent rule:

- agents only pick Issues with `Status=Ready` and label `agent:ready`
- `agent:ready` is the pickup qualifier for `Ready`, not a separate lifecycle state
- Issues must carry the full task contract, including `Source Anchors`, `Suggested Validation`, `Source Docs`, and acceptance criteria with inline `Verify:` targets
- agents must follow `Constraints`
- agents must satisfy `Acceptance Criteria`
- PRs must link the governing Issue

Platform-state note:

- repo-side enforcement lives in `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`, `.github/workflows/issue-pr-governance.yml`, and `.github/github-governance.yml`
- GitHub labels, Project fields/views, and Project automation must match that contract

## Release Channels

<!-- release-channels -->

The release-channel model gives the operator unambiguous answers to "what is running in prod right now?" and "how does prod differ from dev?" It is independent of the existing `dev`/`prod` environment layer, which controls code-execution path and settings resolution.

### Channel identity (shipped — Issue #610)

Three canonical channels — `stable`, `dev`, `test` — are defined. Each channel is identified by four mandatory properties: code ref, DB name, vault root, and runtime-artifact directory. The contract is implemented in `app/config/channel.py` and enforced at construction time via `ChannelIdentity`.

| Channel  | DB         | Vault root          | Artifacts  |
|----------|------------|---------------------|------------|
| `stable` | `pkm_prod` | operator-configured | `tmp`      |
| `dev`    | `pkm_dev`  | `vault-dev`         | `tmp-dev`  |
| `test`   | `pkm_test` | `vault-test`        | `tmp-test` |

Full identity contract: [`docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md`](RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md)

### Release-channel specification — delivered (2026-05-02)

All six task specs are complete and closed; promotion and rollback skills are authored:

- **DB-per-channel isolation** — resolver-level DB naming and two-layer isolation (Issue #611, closed).
- **Promotion plan contract** — `prepare-promotion` plan generation with deterministic receipts (Issue #612, closed).
- **Migration reversibility classification** — migrations classified as reversible or forward-only at promotion time (spec: `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`, closed).
- **Concurrency rule** — separate-checkout contract for prod and dev processes (spec: `docs/RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE.md`, Issue #614, closed).
- **Rollback contract** — operator-safe rollback to previous stable ref with vault immutability and migration reversal path (spec: `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`, Issue #615, closed).

### Outstanding follow-up

**Operational acceptance** — running a stable build against the real vault with a recorded promotion and rehearsed rollback. The acceptance procedure is now documented and ready to execute at `docs/runbooks/PROD_GO_LIVE_ACCEPTANCE.md` (including preflight, smoke test, soak guidance, rollback rehearsal, and the machine-readable receipt template). The acceptance itself — executing the runbook against the real vault and recording a pass receipt — remains the final step before the channel model is treated as fully live in production.

**Release-channel terminology docs** — delivered by Issue #965 / PR #1076. The terminology contract (`docs/RELEASE_CHANNELS/TERMINOLOGY.md` or equivalent) aligns channel, environment, and promotion vocabulary. Remaining hardening issues — startup targets (#966), promotion skill integration (#967), and channel isolation tests (#968) — remain open and should not be implied as delivered.

## Companion UI design artifact intake (2026-05-03)

- Converse wireframe/package intake completed at `companion-ui/design_handoff/2026-05-03-converse/`.
- Package includes implementation-spec README plus reference HTML/CSS/JSX prototypes.
- Initial implementation delivered in `companion-ui/companion-app/` across four bounded slices: layout shell + rail geometry (PR #745), rail thread/composer states (PR #746), staged suggestion moment (PR #750), and session drawer + portrait bottom-sheet (PR #762).
- All Converse interaction slices from the 2026-05-03 handoff (Issues #740–#743) are now delivered. A follow-up data-attribute token alignment fix (Issue #764, PR #763) is also delivered. The runtime-client boundary and vault-first durability constraints were preserved throughout.
- A later bounded runtime/client slice is also shipped: `POST /api/panel/confirm`, durable panel confirmation receipts/projection, `GET /api/artifacts/note`, the real-note workspace shell, and confirm-response artifact refresh (PRs #1054/#1056/#1068/#1069/#1070). These are shipped seam-level client/runtime integrations, not a claim that the full Companion UI product model is baseline.
- Earlier follow-ups #756 and #761 are now closed; remaining work for this area continues under the later companion-UI and cognitive-temporal tracks rather than those bugs.

## Companion UI design artifact intake (2026-05-08)

- Cognitive-temporal design exploration committed at `companion-ui/design_handoff/2026-05-08-cognitive-temporal/`.
- Package covers: cognitive modes, temporal cognition canvas, and re-entry mist variant exploration (21 files — HTML canvases, JSX source, CSS).
- Five vocabulary docs grounded in the package: EXPERIENTIAL_PATTERNS, ATTENTIONAL_PHYSICS, CONTINUITY_AND_DECAY, RESURFACING_HEURISTICS, TEMPORAL_OVERLAYS (PR #823, Issue #824).
- Implementation slices for the 2026-05-08 interaction model are not yet opened.

## Companion UI real-note vertical slice and browser dev server (2026-05-17–2026-05-19)

- Live HTTP workspace client and real-note dev page delivered (#1071 / #1072 / PR #1101): the Companion UI can now render a real vault note via a live HTTP client and a browser-accessible dev page. This is the first end-to-end real-note rendering path.
- Browser dev server delivered (#1103 / PR #1109): the Companion UI target architecture now includes a local browser dev server for the real-note workspace surface. Promoted to **Shipped** in the target architecture doc.
- Target architecture for the Companion UI is defined as a local-first web app at `companion-ui/docs/TARGET_ARCHITECTURE.md` (#1102). The architecture preserves vault-first durability constraints and defines the local-first, browser-rendered posture.
- Production Companion UI surface (full multi-note workspace, navigation, persistence) remains **planned** and not yet shipped. The delivered slices are the real-note rendering foundation.

## Companion UI integration roadmap (2026-05-19)

- First visual alignment pass delivered (#1119): Yggdrasil design tokens, note body as primary surface, companion rail placeholder, dev/staging marker. This is a dev/staging shell, not a production Companion UI contract.
- Existing model/runtime foundations confirmed shipped and not to be rebuilt: Canvas Core models and session API (`canvas_core/`, `app/api/routes/canvas.py`), Panel models and confirmation service (`panel/`, `app/panel/confirmation.py`), Canvas Suggestion Flow models (`canvas_suggestion_flow/`), `GET /api/artifacts/note` artifact read endpoint. Remaining Companion UI work is browser wiring, read-side state discovery, stub replacement, and production shell hardening.
- Governance stub replaced: `_StubPipeline` in `app/api/routes/canvas.py` wired to real `CanvasPanelPipeline` that stages proposals in `ProposalStore`; Panel correction path in `PanelConfirmationService` implemented.
- Product mode integration is implemented in the dev/staging workspace shell: Find renders source candidates with explanation and Panel handoff; Reorient renders read-only orientation sections from the orientation runtime with source links and Panel handoff hints; Resurface renders low-pressure why-now candidates from the resurfacing runtime with dismiss, snooze, and pin affordances; and Act renders Panel-first proposal review and receipts through the existing confirmation path.
- **Issue-first policy**: all future Companion UI implementation changes must be governed by a bounded GitHub issue before implementation begins. Docs-first where contracts are undecided. Any issue that discovers a shipped model must be rescoped as integration work, not reimplementation.
- Next implementation sequence (immediate queue — items 7–8 shipped above; items 3–6 and 9–10 are the active forward line):
  1. `docs(companion-ui)`: define post-dev-server implementation roadmap
  2. `companion-ui`: complete real-note workspace shell gaps after visual alignment pass
  3. `docs(companion-ui)`: define workspace state read-side contract (defines `GET /api/companion/workspace` aggregate; cross-references existing Canvas API; includes explicit `session_persistence` capability field; resolves canvas registry durability)
  4. `runtime-api`: expose read-side Companion workspace state endpoint
  5. `docs(companion-ui)`: define local auth and trusted-device access model (trigger: after #4 merges)
  6. `companion-ui`: bind browser shell to workspace state endpoint
  7. ~~`canvas-api`: wire governance endpoint stub to real Panel pipeline~~ — **shipped**
  8. ~~`panel`: implement correction payload path in PanelConfirmationService~~ — **shipped**
  9. `docs(canvas-ui)`: decide browser editor integration for shipped Canvas API (blocked on #3)
  10. `docs(panel-ui)`: define missing Panel state discovery delta — scoped as gap analysis against existing `PANEL_COMPANION_UI_CONTRACT.md`; not a new contract from scratch
  - Items 3–6 and items 9–10 are sequential; items in each group can run in parallel where independent.
  - Then: production hardening and packaging follow-ups after the dev/staging product modes.
