State: Concept contract (runtime vs durable semantic state boundary; target-state semantics).
Doc role: Core SoT
Authority: Owns the runtime-vs-durable state boundary under Layer 5 (Runtime) of `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`: which state is ephemeral runtime state, which is durable semantics, and the persistence / discardability / ownership / leakage-prevention rules that keep them apart. Consolidates the runtime-boundary semantics already implied by the architecture and contextualization docs; it does not redefine the runtime architecture or the durable-surface owners.
Owner: Runtime vs durable state boundary
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-05-29
Last verified against: docs/SEMANTIC_SYSTEM_ARCHITECTURE.md, docs/SEMANTIC_AUTHORITY_MATRIX.md, docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md, docs/CONTEXTUALIZATION_LAYER/HUMAN_AND_AGENTIC_ARTIFACTS.md, docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md, docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md, docs/ARCHITECTURE.md, docs/FRONTMATTER.md, companion-ui/docs/UI_RUNTIME_BOUNDARIES.md, companion-ui/docs/WORKSPACE_STATE_CONTRACT.md, epic #1363, issue #1369.

# Runtime vs Durable Semantic State Boundary

The system holds a lot of state while it runs — AgentState, sessions, workspace aggregates, panel/overlay state, retrieval results, staged proposals. None of that is durable knowledge unless it explicitly and legibly crosses into the durable surface under governance. This contract draws that boundary: it says what is runtime state, what is durable semantics, and the rules that stop runtime/session/UI state from silently contaminating durable artifacts.

It is the Layer 5 detail for `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md` and the runtime-persistence detail for `docs/SEMANTIC_AUTHORITY_MATRIX.md`.

## State categories

| Category | Definition | Durable? | Rebuildable? | Authority |
| --- | --- | --- | --- | --- |
| Durable semantic artifact | Human knowledge, companion notes, accepted agentic memory, receipts | Yes | No (it is the source) | authoritative / supporting |
| Machine mirror | DB/index/cache projections (owned by #1370) | No | Yes | derived (none of its own) |
| Runtime state | AgentState, in-flight computation, policy evaluations | No | No (discardable) | none |
| Session state | Per-session execution state, chat-session co-authoring state | No | No | none (session log may be a durable receipt) |
| Workflow state | In-flight multi-step workflow progress | No | No | none until a step produces a governed mutation |
| UI state | Panel layout, focus, view configuration | No | No | none |
| Temporary overlay | Derived attention/salience shaping (`zone`) | No | Yes (re-derivable) | none (never a gate) |
| Retrieval cache | Ranked candidates, retrieval results | No | Yes | derived |
| Activation state | Which artifacts are in working context now | No | No | none (recorded in bundle receipt) |
| Proposal staging state | Staged, not-yet-applied changes | No | No | proposal-bearing (non-durable until applied) |

The distinction that matters most: **durable semantic artifact** and **machine mirror** are both reconstructable system assets (mirror from artifact); everything else in the table is **runtime state** — discardable, non-authoritative, and not a rebuild target.

## Persistence rules

What each kind of state **may** do:

- **May persist to the vault (durable human surface):** only durable semantic artifacts — human knowledge, companion notes, and (as a governed transition) accepted agentic memory and the receipts that record mutations. Writing requires explicit human intent or bounded system-write authorization, passes WriteGuard, and produces a receipt (owners: `FRONTMATTER.md`, `TRUST_SEMANTICS_CONTRACT.md`, `SEMANTIC_AUTHORITY_MATRIX.md`).
- **May persist to the DB (as a mirror):** anything that is rebuildable from the durable surface — projections, indexes, caches. Persisting to the DB does not make a value durable semantics (owner: `MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`).
- **May persist to the DB as an explicit runtime record:** session logs, traces, dispatcher/outbox rows, and similar operational records — but classified as receipt/trace, never as a durable semantic artifact (owner: `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`).
- **Must remain runtime-only / be discarded safely:** AgentState, workflow progress, UI/panel state, overlays, activation state, retrieval results. Losing them costs convenience, not meaning.
- **Requires receipts/governance to become durable:** any runtime-derived value that the system wants to make durable. The path is `runtime value → proposal → governance → receipt → durable artifact`, never silent persistence (owner: semantic map artifact-flow topology).

## Runtime ownership map

Who owns each runtime structure (which subsystem holds it; none of these own durable meaning):

| Runtime structure | Owning subsystem | Notes |
| --- | --- | --- |
| Workspace state | Runtime Projection / UI projection | Aggregate view; a projection, not a durable artifact (owner: `WORKSPACE_STATE_CONTRACT.md`, #1368) |
| Overlays (`zone`, salience) | Runtime Projection | Derived, re-derivable; never a gate (owner: `LAYERING_MODEL.md` Zone) |
| Retrieval state / ranked candidates | Capability / Runtime Projection | Rebuildable mirror; not durable |
| Session logs | Governance/Observability | May be durable as a receipt/trace; classify explicitly |
| Panel state | UI projection | Discardable UI configuration |
| Active proposals | Governance/Authority | Staged; non-durable until applied (owner: #1371) |
| Staged edits | Human Surface / Governance | Co-authoring buffer; durable only on governed apply |
| AgentState | Agent/Orchestration | In-flight reasoning state; discardable |

## Leakage prevention

The prohibited contaminations this contract exists to prevent:

1. **UI state becoming semantic truth.** Panel layout, focus, view config, and workspace aggregates must not be written into frontmatter or note bodies as if authoritative.
2. **Retrieval state becoming semantic truth.** Ranked candidates, scores, and salience are derived; they never become durable fields.
3. **Runtime metadata polluting frontmatter.** Only the governed frontmatter contract (`FRONTMATTER.md`) defines durable fields. Runtime/session timestamps, evaluation traces, and overlay values do not silently appear there.
4. **Temporary overlays mutating durable artifacts implicitly.** A `zone`/salience overlay influences ranking and attention only; it must never change an artifact's durable meaning, domain, trust, or content.
5. **Activation state persisting as authority.** What was in working context for a task is recorded in the bundle receipt for audit; it is not a durable property of the artifacts that were activated.

## Discardability semantics

- Runtime, session, workflow, UI, overlay, retrieval, and activation state are **safely discardable**: the system must remain correct and useful after losing any of them (it re-derives or simply starts fresh).
- A correctness or meaning loss on discarding a piece of "runtime" state is a signal it was actually durable and is misplaced — resolve by routing it to the durable surface under governance, not by quietly persisting it where it sits.
- Proposal staging state is discardable on rejection without side effects; on acceptance it is consumed into a governed mutation + receipt, not retained as staging state.

## Relationship to adjacent boundaries

- **vs machine mirror (#1370):** a mirror is rebuildable from durable sources; runtime state is discardable and not a rebuild target. Both are non-authoritative.
- **vs agentic memory:** agentic memory is durable supporting material that crossed a review gate; runtime/session state has not crossed any gate and is not memory (owner: `AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`).
- **vs context bundle:** a bundle is a per-use assembly (rebuildable); its activation does not durably change its source artifacts (owner: `CONTEXT_BUNDLE_CONTRACT.md`).
- **vs UI projection (#1368):** UI overlay/workspace state is runtime/projection; the Companion UI projection contract details how the UI must keep it separate from durable semantics.

## Cross-references

- Parent semantic map (Layer 5) and runtime boundary map: `docs/SEMANTIC_SYSTEM_ARCHITECTURE.md`.
- Runtime persistence flags per entity: `docs/SEMANTIC_AUTHORITY_MATRIX.md`.
- Machine mirror boundary (rebuildable vs discardable): `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`.
- Receipts vs traces (for session logs): `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.
- UI runtime boundaries and workspace state: `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`, `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` (alignment detailed in #1368).
- Workflow/proposal staging detail: #1371 follow-up.

## Verification path

This document is verified by the existence of:
- a **state categories** table distinguishing durable semantic artifact, machine mirror, and the runtime/session/workflow/UI/overlay/retrieval/activation/proposal-staging categories;
- explicit **persistence rules** (what may persist to vault / DB-as-mirror / DB-as-runtime-record / must stay runtime / requires governance);
- a **runtime ownership map**; **discardability semantics**; and
- a **leakage-prevention** section prohibiting UI/retrieval/runtime/overlay/activation state from becoming or polluting durable semantics.
