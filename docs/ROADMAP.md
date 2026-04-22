State: SoT v5.5 baseline locked (Reality-MVP + watchers/panel policy); v5.6 delivery line closed; v6 is the active design and planning direction. Post-v5.6 follow-ups are tracked separately for LangGraph/Reasoning expansion, Orchestrator V2 hardening, A2A/MCP lifecycle cleanup, and local verification hardening.
Doc role: Plan
Authority: Strategic sequencing and forward-looking delivery/follow-up framing; owner/current-state docs win on shipped reality and present-tense behavior.
Owner: Product / architecture forward line
Temporal class: strategic
Review cadence: biweekly
Source of truth: mixed
Last reviewed: 2026-04-21
Last verified against: docs/STATUS.md, docs/ARCHITECTURE.md, docs/DOCS_INDEX.md, docs/EVENTS.md, docs/OBSERVABILITY.md, docs/contracts/A2A_CONTRACT_AND_TRACE.md, docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md, docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md, docs/plans/AUTONOMY_AND_SYNC_VALIDATION.md, docs/plans/LOCAL_TEST_ENVIRONMENT_BOOTSTRAP.md, docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md, docs/plans/V60_ARCHITECTURE_TARGET.md, docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/RECONCILE_CHAT_MUTATION_AUTHORITY.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_PANEL_AS_THE_PRIMARY_COMMAND_SURFACE.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md, docs/FINDING_AND_REORIENTING/README.md, docs/FINDING_AND_REORIENTING/DOCUMENT_SALIENCE_AS_DERIVED.md, docs/COMMITMENT_AS_FIRST_CLASS/README.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, app/orchestrator/runtime.py, app/orchestrator/v2_runtime.py, app/orchestrator/executor.py, tests/events/test_event_envelope_versioning.py, tests/events/test_outbox_consumer_contract.py, merged PRs #365/#376/#382/#383/#386/#389/#391/#423/#424/#425/#426/#427/#431/#434/#439/#448/#450/#452/#453/#454/#458/#460/#463/#467/#468/#469/#470/#471/#472/#473/#474/#475/#476/#477/#478/#479/#490/#491/#492/#493/#494/#496/#497/#499/#501/#502/#503/#505/#506/#507/#508/#509/#510/#521/#523/#525/#526/#527/#529/#531/#533/#547/#548, current repo state at 3c44161 on 2026-04-21, closed current-state bug issues #435/#436/#437/#456, closed lifecycle issue #359, and closed Orchestrator follow-up issues #444/#445/#446

# Roadmap — Strategic Control

This roadmap is forward-looking and skimmable. History lives in `docs/history/SOT_4X_HISTORY.md`; deep track details live under `docs/tracks/`. Current truth stays in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.

## Status vocabulary
- **Shipped** — merged to main; code/doc exists.
- **Operationally accepted** — proven on real vault/external samples with runbook/soak.
- **Baseline locked** — scope frozen; only bugfixes allowed.
- **Post-delivery follow-up** — bounded work discovered after a delivery line closed; does not reopen that line unless the owner explicitly reclassifies it as a release blocker.
- **Planned / In progress** — tracked work not yet shipped.

## Baselines
- **SoT v4.10 (foundation)** — Reality-MVP ingest/ASK/observability runtime; now subsumed by the v5.5 baseline.
- **SoT v5.5 (baseline locked)** — watcher auto-run gate + panel action provenance + concurrency/idempotency guards (dedup queue, promotion consumer dedup, optimistic writes); baseline ships with the new settings compiler and CLI controls.

## Now / Next / Later
- **Now**
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
  - **Orchestrator V2 pilot slice** — initial V2 runtime with flagged parallel execution and plan-graph scheduling shipped. Implements: `ORCHESTRATOR_VERSION=v1|v2` flag, dependency-aware step scheduling, parallel execution with ThreadPoolExecutor, event/trace compatibility with V1, compensation/rollback via `compensate_fn` metadata, retry metadata handling for failed steps, checkpoint/resume with configurable interval persistence, retry/backoff observability for retry and terminal failure paths, and optional `plan_timeout_seconds` plan-level timeout budgets on both V1 and V2 while preserving `tool_timeout_seconds` semantics (see `docs/contracts/TIMEOUT_AND_SLA_CONTRACT.md`). No repo-wide A2A/runtime delivery SLA is claimed. Delivery receipt: Issue #250 (pilot), Issue #251 (compensation), Issue #252 (checkpoint/retry handling), Issue #444 (checkpoint/resume hardening), Issue #445 (retry/backoff observability), Issue #446 (timeout/SLA contract), Issue #540 (plan timeout budget). Source Anchor: ORCHV2-TDD
    - Back-compat preserved: `ORCHESTRATOR_VERSION=v1` (default) uses existing sequential V1; `v2` selects parallel pilot with compensation.
    - Post-v5.6 slices: timeout discriminator bug #456, and possible later repo-wide A2A/runtime delivery SLA work if owner docs promote those beyond the delivered timeout contract.
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
  - A2A/MCP orchestration routing with deterministic adapters and audit; current in-process A2A routing is implemented and covered, and parent lifecycle issue #359 is closed. Remaining MCP ToolProvider integration stays a separate follow-up.
  - Orchestrator V2 timeout retry discriminator cleanup shipped via #456 / PR #458; optional plan-level timeout budgets shipped via #540, while repo-wide A2A/runtime delivery SLA remains future-only unless owner docs promote that scope.
  - Runtime health and docs-index validation hardening: #334/#365 shipped deterministic checks; #441/PR #439 restored the richer runtime verifier contract and made the docs-index guard compatible with repo-local v6 spec metadata.
- **Later**
  - Watcher auto-exec of panel plans with guardrails and rollback; richer panel actions (summary/reply) via tool/MCP boundary.
  - PanelAgent 2.0 expansion beyond the current slices remains bounded even after real-vault acceptance; break new behavior into smaller tracked slices first.
  - Reasoning/reflective layers with eval gates; expanded observability counters for orchestration/A2A.
  - Collaboration/multi-user after single-user flows are stable.
  - `v6.0` architecture target (**active design direction** — see `Capability-Based Architecture & Agent Evolution` above): a baseline-aware target operating model that preserves the
    vault-first / registry-watcher / DB-outbox / companion-note continuity baseline while making
    the next operating boundary explicit: `observation -> normalization/contract -> admission -> execution`.
    - Make the ontology/runtime bridge explicit so human loops, ontology classes, and runtime contracts can be read together without pretending they are the same layer.
    - Test commitment-first modeling where open loops, projects, waiting states, and execution accountability are not flattened into generic note state.
    - Separate retrieval, orientation, and resurfacing as related but distinct runtime concerns.
    - Clarify authority across writing, retention, system, runtime, and execution-record surfaces so receipt-bearing actions remain inspectable.
    - Treat current domain/zone/mirror/promotion findings as current-state bug fixes or enabling changes unless a later implementation slice explicitly realizes the v6 target state.
  - `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md` is the active sequencing plan for turning the v6 capability specs into cognitive-support work. It orders salience/staleness signals, scope/sphere/identity split, receipts plus SUGGEST/APPLY gating, retrieval capability extraction, and minimal commitment runtime work without claiming those surfaces are already shipped.

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
- Deep Agents start in a read-only Chat slice because read-only cognition is the safer first rollout posture; Chat itself is a canvas-shaped interaction surface that may later carry governed mutation rights through the gated execution pipeline.
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

## Phase 2 — Deep Agent Introduction (Thin Slice, Post-v6.0)

Introduce Deep Agents under strict constraints.

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
| v6.0 | Baseline-aware target operating model that preserves the current vault-first/runtime-queue/continuity baseline while aligning operating boundaries with human/context/artifact semantics, ontology/runtime bridge, commitment-first modeling, retrieval vs orientation vs resurfacing separation, and clearer surface/authority contracts; target described in `docs/plans/V60_ARCHITECTURE_TARGET.md` | Active design/planning direction |

## Tracks (details moved)
- Watcher track details: `docs/tracks/TRACK_WATCHER.md`
- PanelAgent LangGraph track: `docs/tracks/TRACK_PANELAGENT_LANGGRAPH.md`
- AgentOps/A2A/MCP hardening: `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`
- Fitness/CI contract: `docs/tracks/TRACK_FITNESS_CI_CONTRACT.md`
- Historical ladder: `docs/history/SOT_4X_HISTORY.md`

## Delivery Control Plane (GitHub)

The repo now adopts a GitHub-based delivery control plane for implementation work:

- Docs/ADRs/owner docs define intent and architecture.
- GitHub Issues are the canonical task contract.
- GitHub Project v2 is the delivery state machine.
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
