State: Non-authoritative pre-Fable handoff prompt; use only as planning context, not executable backlog truth.

# Fable Handoff Prompt - Integrated Runtime v1

Status: paste-ready prompt for a future Fable synthesis pass. This prompt assumes the model receives the evidence pack, errata, selected SoT excerpts, and relevant issue bodies.

## Input package to provide

Provide these files or concise excerpts:

- `docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK.md`
- `docs/plans/INTEGRATED_RUNTIME_V1_EVIDENCE_PACK_ERRATA.md`
- `docs/STATUS.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`
- Issue #1782 - System Entry Point validation hub
- Issue #1795 - state-gallery validation and parent closure
- Issue #1851 - System Entry Point review residuals
- Issue #1699 - TTS runtime health on Mac mini
- Issue #1702 - local TTS voice acceptance and dogfood

Use the errata as correction authority where it conflicts with the evidence pack.

## Prompt

```text
You are acting as the Yggdrasil Integrated Runtime v1 productization architect.

Goal:
Turn already-built Yggdrasil / Agentic PKM capabilities into one coherent production/operator workflow.

Do not invent a new architecture unless strictly required to integrate existing functionality.
Do not solve proportional governance now. Include it as a future design question.

Primary task:
Create the parent epic and dependency-ordered delivery line for "Yggdrasil Integrated Runtime v1".

Definition:
Integrated Runtime v1 means that already-built core capabilities are usable together from a normal Companion UI/operator session, without dev-shell-only paths, hidden flags for core behavior, mock-primary flows, dead affordances, API-only islands, missing receipt visibility, fragmented health/status, or unowned persistence assumptions.

Non-negotiable constraints:
- Vault remains the human/canonical surface.
- Runtime projections are not truth.
- No hidden writes.
- No direct LLM-triggered execution.
- Governed mutations remain governed.
- Body edits remain human save / authorized edit paths.
- Receipts and events remain distinct.
- Source Understanding outputs remain non-authoritative until promoted.
- Memory/context may support awareness and proposals but must not authorize mutation.
- BuilderOps remains build-plane/operator support, not product/runtime truth.
- WriteGuard and provenance requirements must not be weakened.

Important:
The evidence pack contains older or incomplete findings. Use the errata addendum as correction authority wherever it conflicts with the evidence pack. In particular: Capture, Memory Review, Receipts History, and several System Entry Point child surfaces are shipped, but still need production/operator release gates.

Required outputs:

A. Executive diagnosis
- Why the system currently feels like islands.
- Which islands are real implementation gaps.
- Which are route/parity/productization gaps.
- Which should be excluded from v1 rather than forced into scope.

B. Integrated Runtime v1 scope
Classify each capability as:
- core v1
- optional v1
- experimental / behind flag
- out of scope

Capabilities to classify:
- System Entry Point
- Companion UI shell/routes
- Orientation
- Resurfacing
- Capture
- Vault Browser
- Panel Confirm
- Receipts History
- Memory Review
- Source Understanding
- Canvas / Chat co-authoring
- Chat to Panel governance handoff
- TTS / Read-back
- BuilderOps projections
- Health / Status
- Environment / Config / Profiles / Feature flags
- Tests / UAT

C. Product operating loop
Define the integrated loop:

Start -> Orient -> Work -> Review -> Commit/Confirm -> Receipt -> Resume

For each step, map:
- UI surface
- runtime/API dependency
- authority posture
- receipt/event behavior
- degraded/failure state

D. Capability wiring map
For each capability:
- entry point
- input
- output
- next surface
- authority path
- receipt/event behavior
- health/status visibility
- v1 blocker
- release gate

E. Release gates
Define minimal gates for Integrated Runtime v1:
- one operator start path
- one Companion URL
- UI/API route parity
- runtime health/readiness
- feature flag state
- provider readiness
- receipt visibility
- persistence decision
- no-mock golden path
- negative safety UAT

F. Parent epic issue body
Write a GitHub issue body for:

epic(integration): ship Yggdrasil Integrated Runtime v1

It must include:
- Context
- Scope
- Non-goals
- Source Anchors
- Constraints
- Acceptance Criteria
- Suggested Validation
- Source Docs
- Delivery Waves
- Parent closure criteria

G. Child issue table
Create a dependency-ordered table of child issues.
For each child:
- proposed title
- scope
- why it exists
- blockers/dependencies
- verify targets
- v1 classification

H. First five child issue bodies in full
Write the first five bounded issue bodies using the repo's issue style:
- Context
- Scope
- Source Anchors
- Constraints
- Acceptance Criteria with Verify targets
- Out of Scope
- Suggested Validation
- Source Docs

I. Golden-path UAT scenarios
At minimum include:
1. cold start with real/test vault
2. returning user resume
3. read-only orientation + Vault Browser
4. capture to inbox / review path
5. Vault Browser queue-review to Panel confirm
6. Panel confirm to receipt history
7. no-vault/degraded state
8. WriteGuard blocked negative case
9. provider unavailable negative case
10. TTS/read-back if classified optional/core

J. Deferred design question: proportional governance
Do not solve it.
Frame it as a future design/research issue:
- Which flows deserve fast-path or lightweight governance?
- Which require full governed confirmation?
- Which are read-only/proposal-only?
- How can friction be reduced without weakening source/projection/receipt/event/mutation boundaries?

Output format:
1. Strategy summary
2. Parent epic body
3. Child issue table
4. First five child issue bodies
5. Golden-path UAT
6. Deferred proportional-governance question
7. Risks and explicit non-goals
```

## Fable review criteria

Ask Fable to be strict about these failure modes:

- Treating read-only projections as source of truth.
- Treating receipts-history as a new authority store.
- Treating Memory Review accept/reject/revise as unconstrained memory authority.
- Treating Capture as tasks, reminders, or app-managed commitments.
- Promoting Canvas/Chat into core v1 without resolving flag, provider, process-memory, and route parity constraints.
- Hiding route parity gaps behind broad "UI exists" language.
- Reopening future v6.1 work as a blocker for v1 productization.
- Solving proportional governance opportunistically instead of parking it as a future design issue.
