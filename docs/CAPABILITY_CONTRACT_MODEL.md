State: SoT v5.5 Reality-MVP baseline locked (v5.6 delivered, v6.0 seams shipped at capability-seam level); this document is target-state framing for the capability model and does not claim every capability listed below is uniformly implemented today.
Doc role: Core SoT
Authority: Contract spine for what a capability is in Yggdrasil and what shape every capability contract must take. Owns the capability definition (distinct from agents, UIs, services, and tools), the standard capability contract shape, and the canonical capability examples. Sits below `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md` (Capability subsystem) and beside `docs/INTEGRATION_FABRIC_CONTRACT.md`. Does not replace `docs/ARCHITECTURE.md` (`Capability Model`) for current runtime capability behavior or the per-capability spec directories under `docs/FINDING_AND_REORIENTING/`, `docs/COMMITMENT_AS_FIRST_CLASS/`, `docs/CANVAS_CHAT_SURFACE/`, and `docs/CONTEXT_BUNDLES/`.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-13
Last verified against: docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md, docs/INTEGRATION_FABRIC_CONTRACT.md, docs/PROJECT_KERNEL.md, docs/ARCHITECTURE.md, docs/COMPONENTS.md, docs/AGENTS.md, docs/FINDING_AND_REORIENTING/README.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/COMMITMENT_AS_FIRST_CLASS/README.md, docs/CONTEXT_BUNDLES/README.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md, docs/RETRIEVAL.md, parent initiative #877, prerequisite phase issue #878, governing slice issue #879, proportional-governance decision #1881.

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

## Cognitive mediation capability classes

<!-- Cognitive mediation capability classes -->

This section defines the first-pass taxonomy of capability classes for cognitive mediation. The taxonomy does not claim autonomous execution and does not make LLM output authoritative. Every class is bounded by the authority rules in `Standard capability contract shape` above and by the governance/policy gates in `docs/ARCHITECTURE.md`.

### Intent-space vs capability-space

<!-- Intent-space vs capability-space -->

**Intent-space** is what the human (or a governing agent) is trying to accomplish: "orient me," "find related material," "clarify this term," "draft a repair patch." Intent is expressed in human or structured-agent terms and carries no runtime semantics on its own.

**Capability-space** is the runtime-executable contract: a named capability with explicit typed inputs, typed outputs, authority class, and side-effect class. A capability translates an intent into a bounded, provenance-bearing, surface-independent result.

The two spaces are distinct by design:

- Intent originates from the human or a governing agent; it is never generated or overridden by a capability.
- A capability receives an intent (or a context bundle derived from one), performs its bounded function, and returns information or a proposal.
- The gap between intent-space and capability-space is where orchestration, policy evaluation, and admission gating live: a capability does not collapse that gap.

Mapping an intent to a capability class is a governance responsibility, not a capability responsibility. A capability must never claim to "interpret" or "decide" which intent applies.

### Proposal-only capability semantics

<!-- proposal-only capability semantics -->

Capabilities in the **proposal** authority class return a structured proposal to the caller. They never perform the mutation themselves.

Proposal-only semantics:

- Output is a structured proposal object with explicit fields: proposed change, scope, provenance, confidence signal, and expiry/freshness metadata.
- The proposal does not take effect until an authorizing layer (governance gate, Panel human confirmation, WriteGuard, or receipt-governed APPLY gate) accepts it.
- A proposal capability may emit an observability event but must not write to the durable surface.
- If the proposal is rejected or expires without acceptance, no side effect persists.
- LLM-generated content inside a proposal is marked as such in provenance metadata; it is never treated as authoritative without the acceptance step.

Execution semantics (governed-effect authority class) are distinct: they require an explicit acceptance receipt, pass through the event envelope, and produce a traceable receipt artifact. Proposal-only capabilities do not cross into governed-effect territory.

### Capability class definitions

<!-- capability metadata -->

Each capability class carries the following authority/risk metadata fields alongside the twelve standard contract fields:

| Metadata field | Description |
|---|---|
| `capability_class` | One of: `orientation`, `proposal`, `retrieval`, `clarification`, `synthesis_review`, `governed_execution`, `repair_maintenance`. |
| `authority_class` | One of: `read-only`, `proposal`, `governed_effect` (from Standard capability contract shape). |
| `mutation_risk` | One of: `none` (no durable write), `additive` (appends, does not overwrite), `destructive` (overwrites or deletes). |
| `requires_human_gate` | Boolean. Whether explicit human confirmation is required before any effect is applied. Stays boolean and keeps its existing runtime/catalog meaning; equivalent to `authorization_tier == ask-you` (see `Proportional governance tiers`). |
| `requires_policy_gate` | Boolean. Whether a policy/admission check is required before the capability may be invoked or its output acted upon. |
| `receipt_required` | Boolean. Whether a receipt artifact must be produced and persisted when this capability's output is applied. |
| `authorization_tier` | One of: `act`, `agent-review`, `ask-you` (see `Proportional governance tiers`). Additive, per-flow refinement of the human-gate axis. In the target state `requires_human_gate` is its derived boolean projection (`true` iff tier is `ask-you`); target-state only, not yet runtime-consumed (enforcement is v6.1+ work — see `Proportional governance tiers` → Enforcement status). Optional: entries that declare only `requires_human_gate` remain valid. |

#### Orientation

A capability that returns a situational frame for "where am I and what was I doing" without a query term. Draws on recent activity, open-loop proxies, and context-change signals.

- `capability_class`: `orientation`
- `authority_class`: `read-only`
- `mutation_risk`: `none`
- `requires_human_gate`: false
- `requires_policy_gate`: false
- `receipt_required`: false

Orientation does not advise the human on what to do next; it only frames the present situation. Intent derivation from the orientation frame is a human or governing-agent responsibility.

#### Proposal

A capability that returns a structured change proposal (note patch, metadata update, link addition, action suggestion, etc.) for a specific target artifact.

- `capability_class`: `proposal`
- `authority_class`: `proposal`
- `mutation_risk`: `none` (the capability itself does not mutate; the accepted proposal may be additive or destructive depending on its content)
- `requires_human_gate`: true (proposal must be reviewed before application)
- `requires_policy_gate`: true (proposal passes through governance/admission before acceptance)
- `receipt_required`: true (if the proposal is applied, a receipt is required)

The proposal capability is the primary mechanism for surfacing suggested changes without asserting mutation authority. Examples: note patch proposal, action catalog suggestion, freeform panel checkbox write-back.

#### Retrieval

A capability that finds candidate artifacts (or projections) relevant to a query or context bundle.

- `capability_class`: `retrieval`
- `authority_class`: `read-only`
- `mutation_risk`: `none`
- `requires_human_gate`: false
- `requires_policy_gate`: false (but caller must respect surface authority rules for returned artifacts)
- `receipt_required`: false

Retrieval results carry explicit provenance and temporal-validity flags. They are input to reasoning, not authoritative facts.

#### Clarification

A capability that returns a structured disambiguation or definition response when an intent, term, or artifact is ambiguous.

- `capability_class`: `clarification`
- `authority_class`: `read-only`
- `mutation_risk`: `none`
- `requires_human_gate`: false
- `requires_policy_gate`: false
- `receipt_required`: false

Clarification output is advisory. It does not resolve ambiguity autonomously or alter how a surface interprets subsequent inputs.

#### Synthesis / Review

A capability that assembles and summarizes information across retrieved artifacts, orientation signals, and session context. Returns a structured synthesis payload, not a mutation.

- `capability_class`: `synthesis_review`
- `authority_class`: `read-only` (synthesis output itself) or `proposal` (if synthesis produces a structured change recommendation)
- `mutation_risk`: `none` (read-only subclass) or inherits proposal semantics
- `requires_human_gate`: depends on subclass (false for read-only; true if output becomes a proposal)
- `requires_policy_gate`: depends on subclass
- `receipt_required`: false (read-only subclass); true (if proposal subclass is applied)

Examples: commitment surfacing, archive exposure summary, context bundle assembly, memory candidate extraction.

#### Governance-bearing execution

A capability that causes a durable change through the governance/authority layer, the event envelope, and the receipt mechanism.

- `capability_class`: `governed_execution`
- `authority_class`: `governed_effect`
- `mutation_risk`: `additive` or `destructive` (stated explicitly per capability instance)
- `requires_human_gate`: true (explicit acceptance or armed watcher policy with explicit allowlist)
- `requires_policy_gate`: true (WriteGuard, policy evaluation, idempotency check, and outbox admission all apply)
- `receipt_required`: true

No capability in this class bypasses WriteGuard, event envelope, policy gates, or the receipt contract. LLM output is never the direct source of a governed-execution side effect; it may inform a proposal that is then accepted through the governance path.

#### Repair / Maintenance

A capability that proposes or executes bounded self-correcting changes to the system's own derived artifacts (indexes, mirror metadata, receipt records, companion notes). Distinct from governance-bearing execution because it targets system-derived artifacts rather than human-canonical vault artifacts.

- `capability_class`: `repair_maintenance`
- `authority_class`: `proposal` (when identifying drift) or `governed_effect` (when applying a bounded repair with a policy gate)
- `mutation_risk`: `additive` (drift annotation) or `destructive` (index rebuild, stale-record removal) — stated explicitly
- `requires_human_gate`: depends on scope (false for index-only repair; true for vault-note repair)
- `requires_policy_gate`: true
- `receipt_required`: true for any durable repair write

Examples: index rebuild, companion note drift correction, receipt record backfill, stale-metadata removal from derived stores.

---

These capability classes compose with the existing governance, policy, WriteGuard, and event-receipt contracts. They do not replace or bypass those contracts. A capability class assignment is a constraint, not an enabler: assigning `governed_execution` to a capability does not grant it mutation rights; it names the class so the appropriate gates are invoked.

## Proportional governance tiers

<!-- proportional governance tiers -->

This section records the proportional-governance decision from issue #1881. It adds one metadata field — `authorization_tier` — that refines the human-gate axis defined in `Capability class definitions` into three values. It does **not** redefine `requires_human_gate`: that field stays a boolean with its existing shipped meaning (it is consumed today by the panel-action catalog in `docs/settings/panel-actions.md` and by `_is_governance_bearing` in `app/agents/panel_agent/graph.py`, per #982). The tier is the finer-grained value; in the **target state** the boolean is its derived projection — `requires_human_gate == (authorization_tier == ask-you)` — but that is design intent, not a change to today's runtime (see *Enforcement status* below). `requires_policy_gate` and `receipt_required` are unchanged: WriteGuard, policy evaluation, the event envelope, and the receipt contract apply at every tier exactly as before. A tier names *who authorizes a durable effect*, not whether the effect is governed. Read-only and proposal authority classes are unaffected — a read-only capability never reaches a tier because it produces no durable effect.

The per-class `requires_human_gate` values in `Capability class definitions` are class-level defaults. `governed_execution` and `repair_maintenance` span tiers. In the target state the operative gate for a specific flow is its `authorization_tier`, with the boolean following the projection above; **today** the shipped gate is still class-level (see *Enforcement status*). Existing catalog entries are unaffected by this PR.

Integrated Runtime v1 shipped a single posture: every durable mutation routed through full human-governed confirmation. Proportional governance relaxes that **only** where reversibility makes it safe, on the principle that **log + Git is the safety net** — an effect Git can reconstruct does not need a human gate; an effect that escapes Git's undo or leaves the local trust boundary does. Reversibility, not mutation-class alone, is the bright line between `agent-review` and `ask-you`.

### Tier definitions

| Tier | Authorizer | Applies to |
|---|---|---|
| `act` | the agent applies directly; deterministic gate only (WriteGuard + receipt) | additive or internal effects that are reversible via log + Git |
| `agent-review` | a second cognition verifies the proposed effect before commit; no human gate | canonical-note mutations that are Git-reversible but carry risk or provenance ambiguity |
| `ask-you` | explicit human confirmation | **only** irreversible or external effects — those that escape the Git undo or leave the local boundary |

**Boolean projection (target-state):** once enforcement lands, `act` and `agent-review` ⇒ `requires_human_gate: false`; `ask-you` ⇒ `requires_human_gate: true`. This is the target relationship — **not** an instruction to flip catalog `requires_human_gate` values today (see *Enforcement status*). `requires_policy_gate` and `receipt_required` are independent of the tier.

### Per-flow tier assignments

| Flow | `capability_class` | Tier |
|---|---|---|
| Orientation, retrieval, resurfacing, citation checking, commitment surfacing, context building, clarification | read-only classes | none — no durable effect |
| Capture append | `governed_execution` (additive) | `act` |
| Checkbox projection | `governed_execution` (additive, derived projection) | `act` |
| Index / derived-store repair | `repair_maintenance` (index scope) | `act` |
| Companion-note drift correction | `repair_maintenance` (system-derived) | `act` |
| Queue-review classification, low-risk classes | `proposal` → additive label/state | `act` |
| Note patch applied to a canonical vault note (cross-note) | `governed_execution` | `agent-review` |
| Frontmatter / metadata change | `governed_execution` (additive) | `agent-review` |
| Memory candidate admission | `proposal` → `governed_effect` | `agent-review` |
| Vault-note repair | `repair_maintenance` (vault scope) | `agent-review` |
| Synthesis that becomes an applied change | `synthesis_review` (proposal subclass) | `agent-review` |
| Body edit to a canonical note | `governed_execution` | `ask-you` (deliberate exception — see below) |
| External send / publish | `governed_effect` (external) | `ask-you` |
| Destructive op not Git-recoverable (bulk delete, untracked loss) | `governed_execution` (destructive) | `ask-you` |
| Archive materialization | `governed_effect` at materialization | `ask-you` |
| Schema / migration-class change | `governed_effect` (destructive) | `ask-you` |

### Ratified boundary decisions

Three lines sit where the relaxation collides with the v1 posture. They were decided explicitly on #1881, not derived mechanically:

1. **Body edits stay human (`ask-you`) — for now.** Git makes body edits reversible, so the reversibility principle would otherwise place them at `agent-review`. They are deliberately held at the human gate (the v1 human-save / canvas-suggestion model) because direct prose authorship is the human's primary creative surface. This is the one principled exception to "human only for irreversible/external," and is revisitable under the evidence gate below.
2. **Cross-note mutation and frontmatter changes move to `agent-review`.** Issue #1881's pre-decision framing listed these as always-human; the decision moves the Git-reversible cases to a verifying cognition with no human gate. This is the relaxation that reduces friction: agents apply reversible structural edits after review, backed by the Git undo.
3. **Destructive-but-Git-recoverable effects are `agent-review`, not `ask-you`.** Overwriting a tracked note is destructive but reconstructable from Git, so it stays at `agent-review`. Only destruction that escapes the Git undo — deleting untracked/uncommitted material, bulk irreversible operations — is `ask-you`. Git-recoverability, not the `destructive` mutation-class alone, is the line for the human gate.

### Enforcement status (target-state; not yet enforced)

This section is design intent, consistent with this document's target-state framing, and #1881 explicitly scopes out any change to current confirm/WriteGuard behavior.

Today, `_is_governance_bearing` (`app/agents/panel_agent/graph.py`, #982) returns governance-bearing for every `governed_execution` capability class and `governed_effect` authority class **before** it consults `requires_human_gate`. So all such flows remain human-gated regardless of the tier assigned above, and the `requires_human_gate` values in `docs/settings/panel-actions.md` are unchanged by this PR. Assigning a governed-effect flow to `act` or `agent-review` here states the target, not current behavior: realizing it requires a coordinated change to `_is_governance_bearing` and the catalog, filed as separate implementation work. Until that lands, do not set `requires_human_gate: false` for a governed-effect flow on the strength of this section alone.

### Constraints carried from #1881

- Every durable effect at every tier still produces a receipt and passes WriteGuard, the policy gate, and the event envelope. No tier introduces a hidden write.
- No tier permits an LLM output to be the direct source of a governed effect. `agent-review` is a verifying cognition over a proposal, not autonomous execution.
- A tier assignment is a constraint, not an enabler (consistent with the class-assignment rule above): assigning `act` does not grant mutation rights a capability would not otherwise hold.
- Moving a flow to a lower tier requires the evidence gate — UAT receipts, negative-safety coverage, and incident history recorded against this section.
- This section is the recorded design proposal for #1881. Runtime enforcement of tiers is implementation work opened as separate issues; this document remains docs-only target-state framing.

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
