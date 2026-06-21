State: Target-state contract stub; current agent/orchestrator implementations are transitional references.
Doc role: Contract stub
Authority: Owns CAO target workflow and agent orchestration contract shape.
Owner subsystem: CAO - Cognitive Capability & Agent Orchestration
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# WorkflowContract

## Purpose

Define agent/task workflow lifecycle, plan state, roles, cancellation, handoff, decision requests, proposal outputs, and the no-direct-unmanaged-side-effects rule.

## Inputs

- Human intent or automation trigger.
- ActiveContextSet reference.
- CapabilityContract references.
- ContextBundle and MemoryRecord inputs where allowed.
- Agent role and workflow policy.
- GOV decision request requirements.

## Outputs

- Task state.
- Plan state.
- Proposal output.
- Human-decision request.
- ExecutionRequest for authorized side effects.
- Handoff/cancellation/completion state.

## Commands

- Start workflow.
- Plan.
- Invoke capability.
- Request human decision.
- Request GOV policy decision.
- Request execution.
- Cancel.
- Hand off.

## Queries

- What is the task state?
- Which agent role owns the step?
- Which decisions are pending?
- What proposals exist?
- Which side effects were requested?

## Events

- `workflow.started`
- `workflow.step_planned`
- `workflow.decision_requested`
- `workflow.proposal_created`
- `workflow.execution_requested`
- `workflow.handed_off`
- `workflow.cancelled`
- `workflow.completed`

## Invariants

- Workflow state is not human knowledge, policy, retrieval truth, or memory by itself.
- CAO coordinates cognition and proposals; EXE executes side effects after GOV.
- Cancellation and handoff are explicit.
- Agent runtime replacement should not redesign GOV/RCA/MEM/EXE.

## Allowed Producers

- HIX intents.
- Automation triggers under GOV policy.
- CAO agents and orchestrators.

## Allowed Consumers

- CAO agent runtimes, HIX status/review surfaces, GOV decision workflows, EXE execution paths, OEF traces.

## Forbidden Use

- Do not mutate HKA/MEM/PDM directly from workflow steps.
- Do not store policy decisions as workflow-local state only.
- Do not hide side effects inside agent runtime callbacks.

## Failure Modes

- Agent runtime owns policy/retrieval/memory/tool side effects.
- Workflow state becomes hidden authority.
- Cancellation/handoff loses accountability.

## Transitional Implementation Notes

PanelAgent, ASK, Orchestrator, A2A, LangGraph, and future Deep Agent work should be classified against this target contract before new workflow authority is added.

## Open Questions

- Which workflow states require durable receipts versus trace-only events?
- Which handoff boundaries need human review by default?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/AGENTS.md`
- `docs/LANGGRAPH_AGENT_ARCHITECTURE.md`
- `docs/contracts/A2A_CONTRACT_AND_TRACE.md`
- `docs/PANEL_AGENT.md`
