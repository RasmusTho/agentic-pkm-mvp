State: SoT v5.5 Reality-MVP baseline locked (v5.6 delivered, v6.0 seams shipped at capability-seam level); this document is target-state framing for the system-of-systems decomposition and does not claim every subsystem is implemented today.
Doc role: Core SoT
Authority: Architecture spine that frames Yggdrasil as a system-of-systems with a stable kernel and a replaceable extension fabric. Owns the kernel/extension boundary and the subsystem map. It does not replace `docs/ARCHITECTURE.md` (current runtime baseline) or `docs/PROJECT_KERNEL.md` (North Star); it sits above them and explains how their concerns compose.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-14
Last verified against: docs/PROJECT_KERNEL.md, docs/HUMAN-FLOWS.md, docs/ARCHITECTURE.md, docs/COGNITIVE_PROSTHESIS_CHARTER.md, docs/HUMAN_FLOW_TO_RUNTIME_MAP.md, docs/READING_PATHS.md, docs/COMPONENTS.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/FINDING_AND_REORIENTING/README.md, parent initiative #877, PR #883.

# System-of-Systems Architecture — Spine

This document is the architecture spine for Yggdrasil read as a system-of-systems. It is a docs-only artifact that frames the system above the current runtime baseline so later contract work (integration fabric, capability contracts, agent memory, context bundles, vault topology) has a stable place to attach.

Authority boundaries:
- `docs/PROJECT_KERNEL.md` owns the North Star and the non-negotiable kernel constraints.
- `docs/COGNITIVE_PROSTHESIS_CHARTER.md` owns the product-level thesis (what cognitive burdens are supported, why Markdown/vault stays primary, what the system is not).
- `docs/HUMAN-FLOWS.md` owns the user-facing behavior contract.
- `docs/ARCHITECTURE.md` owns the currently shipped runtime architecture, current-vs-planned status, and runtime contracts.
- This document owns the system-of-systems decomposition: kernel vs extension fabric, the subsystem map, and the authority boundaries between subsystems.

If this document conflicts with any of the owner docs above on their respective concerns, the owner doc wins. This document should be updated to reflect the resolved boundary, not the other way around.

## Reading rules

- Subsystems below are conceptual decompositions of the same single local-first runtime. They are not separate deployments, services, or processes.
- "Kernel" describes the stable surfaces and contracts that newer agents, capabilities, integrations, and UI surfaces must not violate. "Extension fabric" describes the surfaces that are expected to evolve, be replaced, or grow over time.
- Where a subsystem already has a shipped owner doc, that doc remains authoritative for current behavior. Where it does not, the subsystem entry is target-state framing and explicitly says so.
- This document does not introduce new lower-level contracts. Detailed contracts for integration fabric, capabilities, agent memory, context bundles, and companion-UI/vault topology are owned by the later phase issues in initiative #877.

## Kernel and extension fabric

Yggdrasil is read as a stable cognitive kernel with a replaceable extension fabric around it. The kernel is the small set of structural commitments that must remain stable for the system to function as a cognitive prosthesis; the extension fabric is the larger set of surfaces, capabilities, agents, integrations, and UI mirrors that are expected to evolve over time.

### Kernel (stable, non-negotiable)

The kernel is the structural commitment surface. Changes here are architecture-level decisions, not feature work.

- **Human-first authority.** The human is the durable author and the final authority over meaning. Agents propose; the human (or a human-authorized rule) decides. Authority lives with the human and with explicit governance, not with whichever runtime component happened to write a value.
- **Vault-first durable surface.** Human-readable Markdown/vault artifacts (vault notes plus system-owned companion notes) are the durable continuity set. Databases, indexes, workers, agents, APIs, and UIs are mirrors, adapters, or execution services on top of that durable surface; runtime DB/index state must be rebuildable from the vault + companion set.
- **Provenance, receipts, and write guards.** Every system-originated change to the durable surface must carry provenance, must produce a human-legible receipt, and must respect write-safety gates (idempotency, optimistic guards, per-note opt-outs, governed APPLY paths). This is not optional decoration; it is the trust contract.
- **Local-first operation.** The system must remain useful and safe with no external integration available. External providers (LLMs, embeddings, cloud connectors, remote tools) are capability, transport, inference, or interface; they are not allowed to become semantic authority without explicit Yggdrasil contracts.
- **Event/outbox compatibility.** The common event envelope and outbox semantics are a kernel contract. Agents, capabilities, and integrations cross subsystem boundaries through the envelope, not through bespoke side channels.
- **Authority separation between subsystems.** Cognition does not directly mutate notes. Execution does not invent intent. Integration does not decide meaning. Governance owns admissibility and audit. These separations are kernel rules, not implementation conveniences.
- **Single-user, single-vault posture as the current baseline.** Multi-user and multi-vault are not blocked by the kernel, but they are not in scope as a current commitment and must not be designed against as if shipped.

The kernel constraints above are owned in canonical form by `docs/PROJECT_KERNEL.md`, `docs/COGNITIVE_PROSTHESIS_CHARTER.md`, and `docs/ARCHITECTURE.md`. This document restates them only to make the system-of-systems decomposition legible.

### Extension fabric (replaceable, expected to evolve)

The extension fabric is everything that legitimately changes over time without changing what the system is.

- Interaction surfaces (Panel, Chat/canvas, CLI, HTTP API, companion-UI modes, future surfaces).
- Reusable capabilities (retrieval, reranking, orientation, resurfacing, summarization, planning support, future capabilities).
- Bounded agents and orchestration patterns (PanelAgent, reviewer, planner, Deep Agent rollout, future agents).
- Integration adapters (LLM/embedding providers, cloud connectors, watcher transports, MCP/tool descriptors, remote multiplex seams).
- Runtime persistence/index implementations behind the durable surface (Postgres/pgvector, embedding stacks, relation stores, future stores).
- Companion-UI implementations, onboarding flows, and vault-topology layouts.
- Observability/fitness implementations (status surfaces, dashboards, runbooks, CI gates).

Extension-fabric components are allowed to be added, replaced, or removed. They must not weaken the kernel constraints to do so.

### How kernel and extension fabric compose

- New features should emerge from governed composition of existing surfaces, context bundles, reusable capabilities, policies, events, receipts, and feedback signals. They should not require carving new authority paths through the kernel.
- A change that needs to weaken human-first authority, vault-first durability, provenance/receipts/write guards, local-first operation, the event envelope, or authority separation between subsystems is a kernel change and must be argued for at the kernel level — not slipped in through an extension-fabric component.
- Extension-fabric components that fail or are unavailable must degrade legibly. They must not silently take over authority or hide the failure from the human.

## Subsystem map

Yggdrasil's system-of-systems decomposition has eight subsystems. Each subsystem owns a distinct concern; together they cover the current runtime baseline and the v6.0 target-state direction. Each entry below states the concern, the kernel constraints that bind it, the primary owner doc(s), and the current implementation status.

### 1. Human Surface

- **Concern:** The surfaces where the human actually reads, writes, decides, and interacts. Vault notes in Obsidian, CLI, HTTP API, Panel-in-note, Chat/canvas, companion-UI modes.
- **Kernel binding:** Human-first authority; the durable surface is vault Markdown; intent comes from this layer or from human-authorized rules, not from cognition or runtime layers.
- **Owner docs:** `docs/HUMAN-FLOWS.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/PANEL_AGENT.md`, `docs/CANVAS_CHAT_SURFACE/README.md`, `docs/COGNITIVE_PROSTHESIS_CHARTER.md`.
- **Status:** Active. Obsidian vault, CLI, HTTP API, PanelAgent, and read-only Chat cognition scaffold are shipped. Bounded canvas-session slice exists behind `CANVAS_ENABLED`. Companion-UI is design-handoff + bounded reference code, not production runtime.

### 2. Knowledge & Artifact

- **Concern:** The durable human-meaning surface — vault notes, system-owned companion notes, and the artifact/lifecycle posture that keeps them portable, recoverable, and semantically primary.
- **Kernel binding:** Vault-first durability; provenance and receipts; the companion-note contract for continuity and repair.
- **Owner docs:** `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/plans/ARTIFACT_MODEL_AND_LIFECYCLES.md`, `docs/CORE_CONTRACT.md`, `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`, `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`.
- **Status:** Active reading model (human vault note + system companion note + rebuildable runtime projections). Vault topology and richer artifact taxonomy beyond the current allowlist remain phase-issue work.

### 3. Runtime Projection

- **Concern:** Rebuildable runtime views over the durable surface — object/store projections, embeddings, indexes, relations, derived overlays (`zone`, salience), and other operational state. These are mirrors, not authority.
- **Kernel binding:** Vault-first durability (runtime state must be rebuildable from vault + companion set); local-first operation; runtime state does not own meaning.
- **Owner docs:** `docs/ARCHITECTURE.md` (`Current Runtime Surfaces`, `Artifact surfaces`, `Zone Overlay`), `docs/COMPONENTS.md`, `docs/RETRIEVAL.md`, `docs/EMBEDDINGS.md`, `docs/SEPARATING_PERSISTENCE_SURFACES/README.md`.
- **Status:** Active baseline. ObjectStore, VectorIndex, RelationIndex, embedding stack, derived `zone` overlay, optional `sphere_membership`, and orientation/resurfacing signal payloads are shipped.

### 4. Capability

- **Concern:** Reusable, composable, surface-independent functions that any interaction surface or agent can invoke — retrieval, reranking, orientation, resurfacing, summarization, planning support, and similar. Capabilities have explicit typed contracts; they are not agents and are not surface-specific.
- **Kernel binding:** Authority separation (a capability returns information, it does not decide meaning or mutate the durable surface); event/outbox compatibility for any side effects that do cross into execution.
- **Owner docs:** `docs/ARCHITECTURE.md` (`Capability Model`), `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`, `docs/FINDING_AND_REORIENTING/README.md`, `docs/RETRIEVAL.md`.
- **Status:** Retrieval is a shipped typed-capability seam consumed by ASK. Orientation and resurfacing exist as minimal read-only runtime seams. Broader capability-contract work and capability registry are phase-issue work (#879).

### 5. Agent / Orchestration

- **Concern:** Bounded agents and orchestration patterns that compose capabilities into multi-step work — PanelAgent, reviewer, planner, ASK runtime, Orchestrator V1/V2, future Deep Agent rollout, A2A in-process routing. Agents have narrow responsibilities and explicit state.
- **Kernel binding:** Human-first authority (agents propose under governance); authority separation (cognition does not directly mutate notes); event/outbox compatibility; provenance on every action.
- **Owner docs:** `docs/AGENTS.md`, `docs/PANEL_AGENT.md`, `docs/ARCHITECTURE.md` (`Architecture Statement: Bounded Agents on Shared Foundations`, `Agent Implementation Pattern`), `docs/LANGGRAPH_AGENT_ARCHITECTURE.md`, `docs/contracts/A2A_CONTRACT_AND_TRACE.md`.
- **Status:** Active baseline. PanelAgent and ASK are LangGraph runtime paths; `ReasoningFacade` is the shared reasoning seam; Orchestrator V2 is flag-selected pilot work; Deep Agent rollout is read-only Chat cognition scaffold. Agent memory and context-bundle contracts are phase-issue work (#880).

### 6. Governance / Authority

- **Concern:** The admissibility, approval, audit, and write-safety layer that enforces what may change, who may approve it, and how the change is recorded. Includes write guards, APPLY gates, policy profiles, panel action catalog, watcher safety gates, governance routing for canvas/Chat mutations, and the receipt model.
- **Kernel binding:** Human-first authority; provenance, receipts, and write guards; authority separation (governance, not cognition or integration, owns admissibility).
- **Owner docs:** `docs/ARCHITECTURE.md` (`Concurrency & Idempotency`, `Boundary Enforcement`, `Core Contract, State Axes, and Overlays`), `docs/PANEL_AGENT.md`, `docs/NOTE_KIND_POLICIES.md`, `docs/COMMITMENT_AS_FIRST_CLASS/README.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CHAT_AUTHORITY_BOUNDARY.md`.
- **Status:** Active baseline. Optimistic write guards, `DEFAULT_WRITE_GUARD`, per-note opt-outs, watcher auto-run gates, panel action catalog, commitment APPLY gate, governance routing for canvas writes, and promotion-transition receipts are shipped.

### 7. Integration Fabric

- **Concern:** External integrations that provide capability, transport, inference, or interface — LLM and embedding providers, cloud connectors, watcher transports (filesystem, sync replicas), MCP/tool descriptors, A2A routing, remote multiplex seams, future external surfaces.
- **Kernel binding:** Local-first operation (external integrations must not be required for the system to function); external integrations are never semantic authority without an explicit Yggdrasil contract; event/outbox compatibility for any side effects.
- **Owner docs:** `docs/ARCHITECTURE.md` (`Abstraction boundaries`, `Operational topology`, MCP/tools and A2A sections), `docs/contracts/TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT.md`, `docs/contracts/A2A_CONTRACT_AND_TRACE.md`, `docs/CONCEPTS/CLOUD_CONNECTORS_DECISION.md`, `docs/LLM.md`, `docs/EMBEDDINGS.md`.
- **Status:** Mixed. MCP descriptor registry, registry-backed ToolProvider, flagged remote multiplex seam with deterministic local fallback, bounded in-process A2A routing, watcher abstractions, and provider boundaries are shipped. A unified integration-fabric contract is phase-issue work (#879).

### 8. Observability / Fitness

- **Concern:** The visibility surface that lets the human and the operator see whether the rest of the system is doing what it is supposed to do — status service, health checks, observability events, dashboards, runbooks, fitness functions, CI/test gates.
- **Kernel binding:** Provenance and receipts must be inspectable; failures must degrade legibly; local-first operation must remain verifiable without external observability.
- **Owner docs:** `docs/OBSERVABILITY.md`, `docs/HEALTH.md`, `docs/STATUS.md`, `docs/OPERATIONS.md`, `docs/TESTING.md`, `docs/ARCHITECTURE.md` (`Fitness Functions`).
- **Status:** Active baseline. Status service, health checks, watcher heartbeat/tick logs, outbox audit events, fitness/architecture tests, and CI gates are shipped. Broader fitness signal fusion across subsystems remains evolving work.

## Subsystem composition rules

- Each subsystem must respect every kernel constraint in `Kernel and extension fabric`.
- Cross-subsystem communication crosses through the event envelope, typed capability contracts, or explicit governance/authority surfaces — not through bespoke side channels.
- A subsystem may grow new components in its extension fabric without ceremony. Reassigning a concern from one subsystem to another is an architecture-level change and must be reflected here and in the affected owner docs in the same change.
- The Human Surface subsystem is the only one that may originate human intent. The Knowledge & Artifact subsystem is the only one that owns the durable surface. Runtime Projection, Capability, Agent/Orchestration, and Integration Fabric subsystems must not bypass Governance/Authority to mutate the durable surface.

## Out of scope for this document

This document is the spine. The following are intentionally not defined here and are owned elsewhere or by later phase issues in initiative #877:

- Detailed integration-fabric contract and capability-contract schema — phase issue #879.
- Agent memory and context-bundle contracts — phase issue #880.
- Emergent feature composition model — phase issue #881.
- Companion-UI onboarding and vault-topology alignment — phase issue #882.
- Current runtime contracts, current-vs-planned status, and runtime invariants — `docs/ARCHITECTURE.md`.
- Product-level thesis (what cognitive burdens are supported, kinds of state, failure modes that would violate the prosthesis purpose) — `docs/COGNITIVE_PROSTHESIS_CHARTER.md`.
- Mapping human flows to runtime support — `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`.
- Reading paths by change type — `docs/READING_PATHS.md`.

## Verification path

This document is verified by the existence of:
- a `Kernel and extension fabric` section that names the kernel constraints and what is allowed to evolve in the extension fabric, and
- a `Subsystem map` section that names all eight subsystems (Human Surface, Knowledge & Artifact, Runtime Projection, Capability, Agent/Orchestration, Governance/Authority, Integration Fabric, Observability/Fitness) and links each to its owner doc(s).

`docs/ARCHITECTURE.md` and `docs/DOCS_INDEX.md` point to this document without duplicating its content.
