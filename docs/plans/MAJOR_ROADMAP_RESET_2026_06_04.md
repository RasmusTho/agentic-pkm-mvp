State: Accepted strategic reset input. This document sets roadmap sequencing and drift-control rules; it does not promote runtime capabilities by itself.
Doc role: Plan
Authority: Strategic sequencing input downstream of `docs/ARCHITECTURE.md` and `docs/STATUS.md`. Current-state SoT and runnable verification win on shipped reality.
Owner: Product / architecture forward line
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-04
Last verified against: `docs/STATUS.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, `docs/DOCS_INDEX.md`, `docs/HUMAN-FLOWS.md`, `docs/EVENTS.md`, `docs/TESTING.md`, `docs/CONTEXT_BUNDLES_RUNTIME/README.md`, open issues #1559/#1565/#1566, open PRs #1573/#1574, and `main` at `e34a72b6`.

# Major Roadmap Reset - Agentic PKM / Yggdrasil

## Reset Decision

The next work sequence must not be generated as a normal backlog wave. The immediate strategy is to
restore truth boundaries first:

- shipped runtime vs delivered seam,
- product/runtime truth vs BuilderOps execution state,
- human artifact vs machine mirror,
- governance/authority vs ontology/semantic model.

The main drift risk is treating contract-level or partially integrated work as a product/runtime
capability before it has receipts, owner-doc promotion, and verification against the active runtime.
`docs/ROADMAP.md` remains the strategic sequencing surface, while high-churn movement belongs in
BuilderOps records and GitHub issue/PR state.

Historical doc path finding: `docs/AI_DEVELOPMENT.md` and `docs/QUALITY.md` remain intentionally
absent after the docs-refactor cleanup. The active destinations are `docs/development/DEV_WORKFLOW.md`
for builder workflow and `docs/TESTING.md` for testing/quality gates. Do not re-create redirect
stubs unless the owner decides compatibility paths are required again.

## Current Reality Summary

| Area | Current classification | Reset posture |
| --- | --- | --- |
| Vault as primary human surface | Shipped + verified | Preserve as primary control and durable knowledge surface. |
| DB/store/index/outbox | Shipped + verified | Keep as machine mirror and operational API, not semantic authority. |
| Watcher, WriteGuard, health | Shipped + verified | Treat as authority spine before expanding autonomy. |
| PanelAgent + confirmation | Shipped + verified | Use as the first vertical human-agent proof path. |
| Companion UI | Shipped but dev/staging biased | Define operational promise before polish or broad UX expansion. |
| AgentState/LangGraph | Bounded shipped usage | Active for ASK/PanelAgent; runtime-wide AgentState remains integration work. |
| Agent Memory | Bounded shipped slices | Do not expand into broad memory intelligence before admissibility is explicit. |
| Context Bundles | Runtime integration in progress | Route/emission/consumption/linkage slices are merged; receipt projection and owner-doc promotion remain open. |
| Contextualization Layer | Contract/doc only | Do not treat as runtime enforcement until code/tests prove it. |
| BuilderOps | Governance/build plane | Keep projections non-authoritative for product/runtime truth. |
| Release channels | Contract/runbook only | Operational acceptance receipt is still required. |

## Critical Path

1. Keep the reset boundary in force: no broad backlog slicing before the owner accepts current-state
   classifications and decision gates.
2. Finish Context Bundle runtime closure only to the filed scope under #1559: receipt projection
   (#1565/#1574), then owner-doc promotion (#1566) if and only if evidence is complete.
3. Stabilize the runtime authority spine: AgentState threshold, WriteGuard, events, receipts, health,
   provenance, and explicit no-authority-upgrade rules.
4. Prove one human-agent vertical loop: vault intent -> proposal -> human confirmation -> bounded
   action -> receipt -> UI/vault visibility.
5. Define memory/context admissibility before memory can influence proposals or action.
6. Keep BuilderOps roadmap/learning state separate from product/runtime current-state docs.
7. Only after the above, consider selective expansion into more agents, broader automation, Deep
   Agents, external artifact ingestion, or LLM-serving optimization.

## Roadmap Waves

| Wave | Strategic purpose | Exit criteria |
| --- | --- | --- |
| 1. Reality Map and SoT Reconciliation | Establish shipped vs seam vs plan. | Owner docs and roadmap point to the reset model without overclaiming runtime state. |
| 2. Runtime Authority and Receipt Spine | Tie state, events, receipts, health, and WriteGuard together. | Receipt/state boundaries are testable and visible for the next vertical slice. |
| 3. Companion UI Operational Loop | Make UI a human control surface, not just a renderer. | UI can inspect, queue, confirm, and show result/receipt posture for bounded actions. |
| 4. Panel Confirmation Vertical Slice | Prove the minimum meaningful human-agent loop. | Real note checkbox/confirmation/action/receipt path works end to end. |
| 5. Memory and Context Admissibility | Govern recall, provenance, review, and context influence. | Memory/context can influence output only with visible provenance and review posture. |
| 6. BuilderOps and Release Governance | Separate build-plane truth and prove stable operation. | BuilderOps projections are labeled non-authoritative; release acceptance has a receipt. |
| 7. Selective Expansion | Expand only on the proven control model. | New agents/automation reuse the same authority, receipt, and observability spine. |

## Do Not Do Yet

- Do not generate more normal backlog waves before this reset is accepted in owner-doc form.
- Do not expand broad multi-agent runtime before the single-agent state/authority/receipt loop is
  coherent.
- Do not expand autonomous background action before receipts and UI visibility are stable.
- Do not pursue generalized semantic memory intelligence before admissibility, provenance, and review
  are explicit.
- Do not spend major effort on Companion UI polish that does not prove an operational control loop.
- Do not ingest external agent artifacts beyond governed artifact/receipt boundaries.
- Do not treat BuilderOps projections or GitHub Project movement as product/runtime SoT.

## Decision Gates

| Decision | Recommended default |
| --- | --- |
| v6.1 Done definition | One vertical loop with receipt, not merely Context Bundle closure. |
| Reset canonicality | Promote this reset into owner-docs as strategic sequencing, not runtime truth. |
| BuilderOps authority | Keep ADR-0010 strict: BuilderOps governs building; repo governs product/runtime truth. |
| Companion UI promise | Near term: inspect, queue, confirm, and receipt visibility. |
| AgentState/PER threshold | Shared minimal spine for trace/authority/proposal/receipt; no durable memory claim. |
| Runtime memory admissibility | Review/provenance required before memory can influence proposals or action. |
| Docs/code divergence | Allow gated divergence only with issue/PR links and explicit owner-doc promotion trigger. |
| Release channels | Runbook pass with receipt before claiming operational acceptance. |

## Candidate Issue Bundles After Approval

Do not create these automatically from this document. They are safe bundle inputs after owner approval:

- Roadmap Reset SoT Reconciliation: update STATUS/ROADMAP/DOCS_INDEX and missing-doc routing.
- Context Bundles Runtime Closure: finish #1559 through #1565/#1566 without scope expansion.
- Runtime Authority/Receipt Spine: unify event-vs-receipt posture across governed loops.
- Companion UI Operational Loop: inspect/queue/confirm/receipt path over existing surfaces.
- Panel Confirmation Vertical Slice: real note intent-to-receipt UAT.
- Memory/Context Admissibility: review/provenance threshold for memory/context influence.
- BuilderOps/Release Governance: projection labeling and prod go-live acceptance receipt.

## Verification Rules

- Code plus tests or operator runbook evidence are required before a capability is marked shipped.
- Plan docs describe future intent until owner docs promote current runtime evidence.
- Events are operational traces unless a receipt/query contract explicitly makes them
  receipt-supporting.
- BuilderOps records and generated projections are not product/runtime truth unless explicitly promoted
  through repo authority gates.
