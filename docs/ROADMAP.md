State: Locked baseline SoT v5.5 (Reality-MVP + watchers/panel policy) with forward line now moving into v5.6 LangGraph/Reasoning rollouts.
Doc role: Plan
Authority: Strategic sequencing and forward-looking delivery framing for the active line; owner/current-state docs win on shipped reality and present-tense behavior.
Owner: Product / architecture forward line
Temporal class: strategic
Review cadence: biweekly
Source of truth: mixed
Last reviewed: 2026-04-01
Last verified against: docs/STATUS.md, docs/ARCHITECTURE.md, docs/DOCS_INDEX.md, current repo state on 2026-04-01
# Roadmap — Strategic Control

This roadmap is forward-looking and skimmable. History lives in `docs/history/SOT_4X_HISTORY.md`; deep track details live under `docs/tracks/`. Current truth stays in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.

## Status vocabulary
- **Shipped** — merged to main; code/doc exists.
- **Operationally accepted** — proven on real vault/external samples with runbook/soak.
- **Baseline locked** — scope frozen; only bugfixes allowed.
- **Planned / In progress** — tracked work not yet shipped.

## Baselines
- **SoT v4.10 (foundation)** — Reality-MVP ingest/ASK/observability runtime; now subsumed by the v5.5 baseline.
- **SoT v5.5 (baseline locked)** — watcher auto-run gate + panel action provenance + concurrency/idempotency guards (dedup queue, promotion consumer dedup, optimistic writes); baseline ships with the new settings compiler and CLI controls.

## Now / Next / Later
- **Now**
  - **v5.5 baseline lock + safety guard** — runtime/startup defaults `WATCHER_AUTO_EXEC=1`, but operators can force emit-only mode with `WATCHER_AUTO_EXEC=0`; allowlists, dedup/idempotency, optimistic writes, and write-guard/status signals remain the real enablement gates for safe rollout.
  - PanelAgent LangGraph decider opt-in, watcher policy auto-exec plumbing (v5.5C in progress).
  - Watcher → panel → planner/orchestrator automation with safety limits now includes dedup reports, promotion consumer visibility, and explicit skipped receipts.
  - Vault-first config validation (panel wiring, watcher, outbox) with schema enforcement and `python -m app.cli.settings_explain`.
- **Next**
  - **Environment contract follow-through** — implement the remaining docs-first environment contract slices from `docs/ENVIRONMENTS.md` in bounded steps: explicit runtime environment selection and environment-scoped vault/store separation are shipped, and environment-aware operator diagnostics are delivered via Issue #265 / PR #272; remaining follow-through should stay bounded and avoid changing the shared architecture contracts.
  - **Companion note + Note Context rollout hardening** — the core companion-note and Note Context implementation is shipped, and the active doc-sync correction has landed. Delivery receipt: Issue #229, PR #237. Any remaining rollout verification or cleanup should be captured as new bounded follow-up issues rather than treated as missing first implementation.
  - **Quality Wave: Registry Watcher Evaluation Stack** — shipped and now serves as the v5.6 rollout gate via `docs/TESTING.md`, `docs/QUALITY_WAVE_IMPLEMENTATION.md`, and `docs/quality_wave/README.md`. Delivery receipt: PRs #197, #198, #199, #200, #201, #202, #210.
  - **ReasoningFacade + broader graph adoption** — the shared `ReasoningFacade` seam is present; the PanelAgent decider migration is shipped via Issue #230 / PR #236, and the review-flow agent migration is delivered via Issue #231. Delivery receipt: #230 (PR #236), #231 (closed COMPLETED). Source Anchor: RF-ADOPTION
    - Rationale: prevents pattern fragmentation; broader agent adoption should route reasoning/tool calls through the existing shared facade instead of introducing new direct call paths. Remaining phased rollout to Promotion/Reviewer/Hygiene is gated on v5.6A pilot stabilization (see Later).
  - **Orchestrator V2 pilot slice** — initial V2 runtime with flagged parallel execution and plan-graph scheduling shipped. Implements: `ORCHESTRATOR_VERSION=v1|v2` flag, dependency-aware step scheduling, parallel execution with ThreadPoolExecutor, event/trace compatibility with V1. Compensation/rollback slice shipped: failed-step triggers reverse-order compensation of completed predecessors via `compensate_fn` metadata, with compensation events and `orchestration.rolled_back` lifecycle event. Out of scope in pilot: checkpointing, retry policy (deferred to follow-up slices). Delivery receipt: Issue #250 (pilot), Issue #251 (compensation). Source Anchor: ORCHV2-TDD
    - Back-compat preserved: `ORCHESTRATOR_VERSION=v1` (default) uses existing sequential V1; `v2` selects parallel pilot with compensation.
    - Next slices: checkpoint persistence, retry/timeout policy.
  - PanelAgent 2.0 timeline: <!-- PA2-ROLLUP -->
    - v5.5C: decider — shipped (rule default + opt-in LLM mode + fallback + telemetry).
    - v5.6 shipped/in progress: engine-neutral cognition seam (#244, PR #249), freeform catalog-driven proposal path (#241, PR #248), suggested checkbox writeback for uncertain/freeform panel proposals (#242), multi-step plans (#243, PR #302). Remaining: real-vault acceptance (#240).
    - v5.7: advanced (panel versioning, cross-note coordination).
  - Vault-as-GUI settings compiler (`@Settings` / System/Config) now covers panel-action catalogs, watcher settings, and outbox paths with CI schema checks (v5.6 track).
  - LangGraph rollout to additional agents (Promotion/Reviewer/Hygiene) in phases:
    - Phase 1: single pilot agent behind a flag; AgentState + graph parity tests green.
    - Phase 2: two agents; planner/orchestrator integration stable; event/A2A contracts unchanged.
    - Phase 3: broader adoption; runtime metrics + rollback plan validated.
  - A2A/MCP orchestration routing with deterministic adapters and audit.
- **Later**
  - Watcher auto-exec of panel plans with guardrails and rollback; richer panel actions (summary/reply) via tool/MCP boundary.
  - Reasoning/reflective layers with eval gates; expanded observability counters for orchestration/A2A.
  - Collaboration/multi-user after single-user flows are stable.
  - `v6.0` architecture target: semantics-aligned runtime architecture where context layering,
    overlap relations, primary-human-artifact boundaries, and local-first multi-device assumptions
    are expressed more cleanly than in the current v5.x transitional runtime.
    - Make the ontology/runtime bridge explicit so human loops, ontology classes, and runtime contracts can be read together without pretending they are the same layer.
    - Test commitment-first modeling where open loops, projects, waiting states, and execution accountability are not flattened into generic note state.
    - Separate retrieval, orientation, and resurfacing as related but distinct runtime concerns.
    - Clarify surface and authority contracts so writing, retention, and system surfaces stay distinct and receipt-bearing actions remain inspectable.

## Capability-Based Architecture & Agent Evolution

This section defines the v6 direction without changing the locked SoT v5.5 guarantees or the active v5.6 rollout contracts.
It follows the design rules in `docs/DESIGN_PRINCIPLES.md`: principles first, structure second, sequencing third, implementation detail elsewhere.
The working plan detail for this section lives in `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md`.

Sequencing rule:
- v5.6 should be read here primarily as an invariant and stabilization layer, not as a strict linear prerequisite list for every v6 design decision.
- The design goal is to preserve the contracts v5.6 is establishing while allowing v6 structural work to be defined in parallel.

Decisions already fixed for this direction:
- ASK is deprecated as the architectural center rather than expanded.
- Retrieval is treated as a reusable capability rather than a standalone agent.
- Interaction is primary on the user-facing side; retrieval, reasoning, ingestion, and indexing remain foundational capabilities used by different interaction surfaces and automation paths.
- Deep Agents start only after structural separation is in place.
- Chat precedes Panel for Deep Agent rollout because read-only cognition is the safer entry surface.
- Execution remains governed and mediated; reasoning alone must not trigger mutation.
- The long-term system spans manual through automated and reactive through proactive behavior under governance.

## Phase 0 — Stabilization (v5.6, current)

- Finish the current v5.6 enablement work needed for structural separation.
- Keep current runtime contracts stable and deterministic.
- No Deep Agents in production mutation flows.
- No execution outside the controlled action layer.

## Phase 1 — v6.0 Baseline (Structural Separation)

Introduce explicit system layers:

- Interaction Layer:
  - Panel (primary, mutation-capable)
  - Chat (planned, read-only)
- Orchestration Layer:
  - LangGraph (control plane, deterministic)
- Capability Layer:
  - retrieval (`retrieve`, `rerank`, `context_build`)
  - reasoning (future)
  - transformation (future)
- Execution Layer:
  - controlled actions only
  - no LLM direct mutation
- Memory Layer:
  - AMG + stores
- Governance Layer:
  - policies
  - admissibility
  - provenance
  - approval

Deliverables:

- ASK fully deprecated; no new development.
- Retrieval extracted into a capability layer.
- Interaction, cognition, execution, memory, and governance separated clearly enough to evolve independently.
- Template-based bounded agents and reusable capabilities can coexist without collapsing into one central agent.
- Governed mutation paths remain explicit and mediated across interaction and automation surfaces.

## Phase 2 — Deep Agent Introduction (Thin Slice, Post-v6.0)

Introduce Deep Agents under strict constraints.

Scope:

- Chat surface only.
- Read-only mode.
- No system mutation.
- No execution access.

Capabilities:

- planning
- decomposition
- multi-step reasoning
- retrieval orchestration

Explicit rule: "Deep Agents cannot execute actions or mutate system state."

Deliverables:

- Chat becomes the first safe cognition sandbox.
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
- Chat = exploration surface (`reasoning -> insight`).
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
| v5.5C/D | Panel LangGraph decider + watcher auto-exec; watcher→planner/orchestrator automation | Planned/In progress |
| v5.6 | Engine-neutral cognition seam (PA2-ENGINE-SEAM, shipped), freeform panel catalog-discovery (shipped), suggested checkbox writeback for uncertain/no-checkbox panel proposals (shipped), multi-step plans (shipped, PR #302), Companion note/doc-sync cleanup, shared ReasoningFacade + LangGraph rollout, Orchestrator V2 (flagged), Vault-as-GUI settings compiler; remaining: real-vault acceptance | Selective forward work (seam + freeform shipped) |
| v6.0 | Wanted-state architecture pass to align runtime boundaries with the newer human/context/artifact semantics, ontology/runtime bridge, commitment-first modeling, retrieval vs orientation vs resurfacing separation, and clearer surface/authority contracts; target described in `docs/plans/V60_ARCHITECTURE_TARGET.md` | Proposed target state |

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
- agents must follow `Constraints`
- agents must satisfy `Acceptance Criteria`
- PRs must link the governing Issue

Platform-state note:

- repo-side enforcement lives in `.github/ISSUE_TEMPLATE/*`, `.github/pull_request_template.md`, `.github/workflows/issue-pr-governance.yml`, and `.github/github-governance.yml`
- GitHub labels, Project fields/views, and Project automation must match that contract
