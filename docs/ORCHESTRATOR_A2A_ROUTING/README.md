---
name: Orchestrator A2A Routing Specification
description: System specification for orchestrator-managed A2A routing and traceable agent-call execution
type: specification
authority: SoT for orchestrator-managed A2A routing implementation sequencing
source_of_truth: docs/tracks/TRACK_AGENTOPS_A2A_MCP.md :: A2A-ROUTING
related_docs:
  - docs/contracts/A2A_CONTRACT_AND_TRACE.md
  - docs/AGENTS.md
  - docs/ARCHITECTURE.md
  - docs/development/DEV_WORKFLOW.md
---

State: Task 1 delivered (issue #360). Tasks 2 and 3 in backlog.

# Orchestrator A2A Routing Specification

This directory contains the system specification for the orchestrator-managed A2A routing capability. Each document describes a discrete implementation task: its purpose, acceptance criteria, verification path, and how to know when it is complete.

These are not issue templates. The specification documents are the source of truth for what must be built. GitHub issues created from them are the execution artifacts used for pickup, sequencing, and delivery receipts.

## Capability Boundary

Current repo reality:

- A2A request/response/error envelopes and audit emitters are shipped under `app/a2a/`.
- `agent_call` plan steps already emit A2A requests from the orchestrator.
- Handler-registry routing delivered: supported targets now route through registered `AgentHandler` callables on `MockPlanExecutor`; unsupported targets fail the step clearly with `not_implemented`.

This specification covers the remaining bounded capability:

- emit complete request/response/error receipts with trace and correlation continuity
- prove the routing contract across multi-step plans and the current V1/V2 orchestrator surfaces

This specification does not claim a remote A2A transport, queueing layer, or long-running delivery SLA.

## Canonical Capability Shape

```text
plan step (agent_call)
  -> orchestrator resolves supported target
  -> request event emitted
  -> registered handler executes in-process
  -> response or error event emitted
  -> step result returned with traceable routing receipt
```

## Implementation Tasks (Execution Order)

1. **[ROUTE_AGENT_CALLS_THROUGH_REGISTERED_HANDLERS.md](ROUTE_AGENT_CALLS_THROUGH_REGISTERED_HANDLERS.md)** ✓ Delivered (issue #360)
   Replace the universal `not_implemented` fallback for supported targets with orchestrator-owned handler routing.

2. **[EMIT_AGENT_CALL_RESPONSES_AND_FAILURES.md](EMIT_AGENT_CALL_RESPONSES_AND_FAILURES.md)**
   Emit complete success and failure receipts for routed calls, including timeout and handler-error surfaces.

3. **[VERIFY_MULTI_AGENT_CHAIN_TRACEABILITY.md](VERIFY_MULTI_AGENT_CHAIN_TRACEABILITY.md)**
   Prove the routing contract across multi-step plans and the current V1/V2 orchestrator surfaces.

## Acceptance

The parent capability "Orchestrator-managed A2A routing" is accepted when:

- [x] All 3 task specifications are delivered through bounded GitHub issues. (1/3 done)
- [x] Supported `agent_call` steps no longer collapse into the generic `not_implemented` fallback. (delivered by #360)
- [ ] Request, response, and error receipts preserve `trace_id` and correlation data through the orchestrator-owned routing path.
- [ ] Multi-agent chain verification passes on the current orchestrator surfaces that execute `agent_call` steps, including flagged V2 where applicable.
- [ ] Validation receipts are recorded on the parent feature issue before owner docs are promoted to claim the capability as supported.

When those conditions are met, update the owning current-state docs in one narrow writeback pass rather than spreading partial claims across roadmap or track docs.

## Verification Path

- Task-level proof lives in focused pytest coverage for `app/a2a/`, `app/orchestrator/`, and current planner/orchestrator integration surfaces.
- Parent-capability validation lives in the GitHub feature issue as merge receipts plus one explicit post-merge validation summary.
- Owner-doc promotion happens only after the feature issue shows that the routed path is both implemented and verified.

## Relationship to GitHub Issues

Backlog receipts created from this specification:

- Parent feature issue: `#359`
- Task issue `#360`: `ROUTE_AGENT_CALLS_THROUGH_REGISTERED_HANDLERS` — delivered
- Task issue `#361`: `EMIT_AGENT_CALL_RESPONSES_AND_FAILURES`
- Task issue `#362`: `VERIFY_MULTI_AGENT_CHAIN_TRACEABILITY`

Keep the parent feature issue open as the live validation hub while the task issues are being delivered.

---

Status: Task 1 delivered. Tasks 2 and 3 in backlog.
