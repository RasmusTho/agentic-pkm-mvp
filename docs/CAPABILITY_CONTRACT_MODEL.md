State: SoT v5.5 Reality-MVP baseline locked (v5.6 delivered, v6.0 seams shipped at capability-seam level); this document is target-state framing for the capability model and does not claim every capability listed below is uniformly implemented today.
Doc role: Core SoT
Authority: Contract spine for what a capability is in Yggdrasil and what shape every capability contract must take. Owns the capability definition (distinct from agents, UIs, services, and tools), the standard capability contract shape, and the canonical capability examples. Sits below `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (Capability subsystem) and beside `docs/INTEGRATION_FABRIC_CONTRACT.md`. Does not replace `docs/ARCHITECTURE.md` (`Capability Model`) for current runtime capability behavior or the per-capability spec directories under `docs/FINDING_AND_REORIENTING/`, `docs/COMMITMENT_AS_FIRST_CLASS/`, `docs/CANVAS_CHAT_SURFACE/`, and `docs/CONTEXT_BUNDLES/`.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-14
Last verified against: docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/INTEGRATION_FABRIC_CONTRACT.md, docs/PROJECT_KERNEL.md, docs/ARCHITECTURE.md, docs/COMPONENTS.md, docs/AGENTS.md, docs/FINDING_AND_REORIENTING/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/COMMITMENT_AS_FIRST_CLASS/README.md, docs/CONTEXT_BUNDLES/README.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md, docs/RETRIEVAL.md, parent initiative #877, prerequisite phase issue #878, governing slice issue #879.

# Capability Contract Model

This document defines what a **capability** is in Yggdrasil and what every capability contract must answer. It is a docs-only model: it does not introduce a runtime capability registry, runtime enforcement, or new tests.

The model has three purposes:

1. Define **what a capability is** (and what it is not) so that capability work does not collapse into agents, UIs, services, or tools.
2. Define the **standard capability contract shape** (the fields every capability must answer) so a capability cannot quietly become semantic authority, a hidden source of truth, or a surface-specific feature.
3. Name **canonical capability examples** so reusable cognitive moves (retrieval, orientation, resurfacing, context building, citation checking, memory candidate extraction, note patch proposal, archive exposure, commitment surfacing) have a stable place to anchor as their per-capability specs evolve.

This document is target-state framing. Several capabilities listed here already have shipped runtime seams (retrieval, orientation, resurfacing); others are described as capability shape so later spec work has a consistent contract surface.

## Capability definition

A **capability** is a reusable, composable, surface-independent function that:

- has an **explicit typed contract** (named inputs, named outputs, named authority class, named side-effect class),
- is **callable by multiple interaction surfaces or agents** without rewiring its semantics for each caller,
- **returns information** or **proposes a change**, but does not by itself originate intent or decide meaning, and
- respects every kernel constraint in `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (`Kernel and extension fabric`).

A capability is distinct from each of the following:

- **Not an agent.** Agents orchestrate work, hold state across steps, and operate under governance. Capabilities are stateless reusable functions agents (and surfaces) invoke. An agent may use many capabilities; a capability does not become an agent by being useful.
- **Not a UI.** A capability has no opinion on how its outputs are rendered. Panel, Chat, CLI, HTTP API, and future companion-UI surfaces may all consume the same capability.
- **Not a service.** A capability is a contract, not a deployment topology. It may be implemented in-process today and remoted later, or vice versa, without changing the capability contract. "Service" is an implementation detail behind the contract.
- **Not a tool.** A tool (in the Tool / MCP provider sense in `docs/INTEGRATION_FABRIC_CONTRACT.md`) is a governed effector an agent chooses from inside a control flow. A capability is upstream of tool choice: it provides the information or proposal an agent reasons over before invoking a tool. Some capabilities propose tool-eligible changes (for example, note patch proposal); they still do not themselves perform the mutation.

Capabilities sit inside the Capability subsystem in `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`. They are part of the extension fabric: capabilities are expected to be added, replaced, or removed without changing the kernel.

## Standard capability contract shape

Every capability must answer the following twelve fields. If a field cannot be answered, the capability is not contract-ready.

- **Name** — the canonical name of the capability. Stable; not surface-prefixed and not agent-prefixed. Used in code, docs, telemetry, and contracts as the single identifier.
- **Purpose** — one paragraph stating the cognitive move this capability supports. Phrased in human terms (what the human or agent is trying to do), not implementation terms.
- **Inputs** — the typed inputs the capability accepts. Each input names its type, whether it is required, and any meaningful constraints. Inputs are explicit; the capability does not silently consume hidden global state.
- **Outputs** — the typed outputs the capability returns. Each output names its type, its meaning, and any provenance/temporal-validity metadata that travels with it. Outputs are explicit; the capability does not silently mutate caller state.
- **Allowed callers** — which interaction surfaces, agents, or other capabilities may call this capability. Phrased as categories (for example, "any interaction surface", "agent runtimes only", "governance layer only"). Not phrased as a permission list of individual callers.
- **Authority class** — what kind of authority this capability holds. One of: **read-only** (returns information; no side effects), **proposal** (returns a structured proposal that another layer may accept or reject; no direct mutation), or **governed effect** (causes a change through governance/authority and the event envelope; never bypasses them). Capabilities are never "owns meaning" or "decides admissibility."
- **Side effects** — what observable effects, if any, the capability has beyond returning its output. Read-only capabilities have none. Proposal capabilities may emit observability events but must not mutate the durable surface. Governed-effect capabilities cross through the event envelope and produce receipts.
- **Provenance requirements** — what provenance must accompany the capability's output so the result is traceable: capability name and version, model/provider where inference is involved, input correlation, trace identifiers, and any temporal-validity flags.
- **Deterministic fallback** — what the capability does when an external integration (model provider, embedding provider, remote tool, etc.) is unavailable or fails. Capabilities consumed in local-first paths must have a deterministic local fallback or must degrade legibly per the integration-fabric contract. Capabilities that genuinely cannot have a fallback must say so explicitly.
- **Observability** — what the rest of the system must be able to see about this capability: call counts, latency, error class, fallback posture, and whether outputs were used by callers. Capability calls are inspectable through the same status/observability surfaces that cover the rest of the system.
- **Maturity** — one of: **Baseline** (locked Reality-MVP backbone), **Active** (delivered in the v5.x forward line; used in practice but still evolving), **Experimental** (opt-in; safe defaults off), or **Planned** (documented intent or stubs; not shipped as a user-reliable capability). Same taxonomy as `docs/COMPONENTS.md` (`Maturity taxonomy`).
- **Replacement strategy** — how this capability can be replaced or removed without violating the kernel. Includes: contract surface that lets a successor capability attach without rewriting callers, deterministic-fallback posture during the transition, and any data/provenance migration the successor must honor.

These twelve fields are the capability contract surface. A new capability is not blocked on a new doc; it is blocked on answering these fields somewhere authoritative (typically a per-capability spec directory under `docs/`).

## Examples

The capabilities below are the canonical examples for the capability contract model. Each entry names the capability, its cognitive move, its authority class, and its owner spec doc. Per-capability detail (full inputs/outputs/provenance/fallback) lives in the owner spec, not here.

- **Retrieval** — find candidate artifacts (or projections) relevant to a query or context. Authority class: read-only. Returns a result set with explicit provenance and temporal-validity flags; never mutates. Owner: `docs/FINDING_AND_REORIENTING/README.md`, `docs/RETRIEVAL.md`, and the retrieval capability seam referenced in `docs/ARCHITECTURE.md` (`Capability Model`). Maturity: Baseline as the shipped typed-capability seam consumed by ASK.
- **Orientation** — return a situational frame for "where am I and what was I doing" without a query term. Authority class: read-only. Composes derived signals (recent activity, open-loop proxies, context-change hints) and exposes explicit explanation fields. Owner: `docs/FINDING_AND_REORIENTING/README.md`, `app/orientation/runtime.py`. Maturity: Active (minimal read-only runtime seam shipped).
- **Resurfacing** — return "why now" candidates for surfacing material the human has not asked for but plausibly needs. Authority class: read-only (resurfacing-triggered mutations remain future work). Emits signal provenance without mutation. Owner: `docs/FINDING_AND_REORIENTING/README.md`, `app/resurfacing/runtime.py`. Maturity: Active (minimal read-only runtime seam shipped).
- **Context building** — assemble a context bundle that ties retrieval, orientation, resurfacing, provenance, receipts, and write guards together for a given task or surface. Authority class: read-only (the bundle itself is inspectable; it does not mutate). Owner: `docs/CONTEXT_BUNDLES/README.md`, `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`. Maturity: Planned (capability spec filed; runtime is phase-issue work).
- **Citation checking** — validate outbound references in agent or ASK outputs against the durable surface and runtime projections. Authority class: read-only (returns a verdict and evidence; does not rewrite outputs). Owner: `docs/COMPONENTS.md` (`CitationChecker`), `docs/TESTING.md`. Maturity: Baseline (with Experimental use in CI).
- **Memory candidate extraction** — propose candidate items for agent memory or long-lived recall from a session, run, or artifact, with provenance back to the source. Authority class: proposal (returns candidates; admission to memory goes through governance and receipts). Owner: `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` and the agent-memory phase work in initiative #877 (#880). Maturity: Planned.
- **Note patch proposal** — propose a structured patch to a vault note (body edit, metadata change, link addition, etc.). Authority class: proposal (returns a structured patch that governance, Panel, or canvas-Chat accepts/rejects/applies; the capability never mutates). Owner: `docs/PANEL_AGENT.md`, `docs/CANVAS_CHAT_SURFACE/README.md`, `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_CANVAS_COEDITING_MODEL.md`. Maturity: Active for Panel-shaped action proposals; broader canvas/Chat patch flow is phase work.
- **Archive exposure** — expose retained material through discovery, citation, preview, and bounded materialization modes without violating retention or trust semantics. Authority class: read-only at discovery/citation/preview; governed effect at materialization. Owner: `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md`, `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md`. Maturity: Planned.
- **Commitment surfacing** — return open commitments, next actions, and waiting items as a structured surfacing payload distinct from note `review_state` and `maturity`. Authority class: read-only (mutations to commitment state go through the receipt-governed APPLY gate, not through this capability). Owner: `docs/COMMITMENT_AS_FIRST_CLASS/README.md`, `docs/ARCHITECTURE.md` (`Commitment-runtime surface`). Maturity: Active (bounded commitment runtime delivered).

These examples are the canonical capability set the rest of the architecture composes around. New capabilities should fit alongside these (or extend one of them through a per-capability spec) rather than be invented inside an agent or surface.

## Out of scope for this document

This is the capability **contract model**, not the capability **runtime**. The following are intentionally not defined here:

- A runtime capability registry, capability discovery service, or capability contract validator. Those are implementation lanes opened from initiative #877, not docs-only contracts.
- Per-capability behavior, inputs/outputs schema, ranking logic, or provider routing. Those are owned by the per-capability spec directories named above.
- The integration-fabric taxonomy and the authority rule for external components — defined separately in `docs/INTEGRATION_FABRIC_CONTRACT.md`.
- Current runtime capability behavior and current-vs-planned status — owned by `docs/ARCHITECTURE.md` (`Capability Model`) and the per-capability specs.
- Kernel constraints and the subsystem map — owned by `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md`.

## Verification path

This document is verified by the existence of:

- a `Capability definition` section that defines a capability as a reusable, composable, surface-independent function distinct from agents, UIs, services, and tools,
- a `Standard capability contract shape` section that names the twelve fields every capability must answer (name, purpose, inputs, outputs, allowed callers, authority class, side effects, provenance requirements, deterministic fallback, observability, maturity, replacement strategy), and
- an `Examples` section that names retrieval, orientation, resurfacing, context building, citation checking, memory candidate extraction, note patch proposal, archive exposure, and commitment surfacing.

`docs/ARCHITECTURE.md`, `docs/COMPONENTS.md`, and `docs/DOCS_INDEX.md` point to this document without duplicating its content.
