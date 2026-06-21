State: Target-state contract stub; complements the existing capability contract model.
Doc role: Contract stub
Authority: Owns CAO target capability contract shape for reusable cognitive operations.
Owner subsystem: CAO - Cognitive Capability & Agent Orchestration
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# CapabilityContract

## Purpose

Define reusable cognitive operations as bounded capabilities with explicit inputs, outputs, authority class, side-effect posture, fallback, versioning, and provenance requirements.

## Inputs

- Capability name/version.
- ActiveContextSet reference.
- ContextBundle or evidence references.
- MemoryRecord recall inputs where allowed.
- Authority class and mutation risk.
- Fallback posture.

## Outputs

- Capability result.
- Proposal output where applicable.
- Explanation and provenance references.
- Error/fallback result.
- ExecutionRequest only when side effects are needed and authorized.

## Commands

- Invoke capability.
- Validate inputs.
- Produce proposal.
- Request context.
- Request execution.
- Report failure/fallback.

## Queries

- Which capability/version applies?
- What authority class does it carry?
- What inputs and outputs are allowed?
- Which fallback applies?

## Events

- `capability.invoked`
- `capability.completed`
- `capability.failed`
- `capability.execution_requested`

## Invariants

- Capabilities do not become agents, tools, UIs, or storage owners.
- Capability output does not grant authority by itself.
- Side-effecting capability work routes through GOV/EXE.
- Provider-specific fields stay behind EBF/CAO adapters.

## Allowed Producers

- CAO capability registry/workflows.
- HIX surfaces requesting capability execution.
- Agents under WorkflowContract.

## Allowed Consumers

- HIX, CAO workflows, GOV policy, RCA/MEM where appropriate, OEF evals.

## Forbidden Use

- Do not encode policy decisions inside capability implementation.
- Do not call tools directly for side effects.
- Do not use capability output as accepted HKA truth without HKA/GOV path.

## Failure Modes

- Agent runtime owns policy/retrieval/memory/tool side effects.
- Capability becomes a hidden execution path.
- Retrieval or memory output becomes truth through capability output.

## Transitional Implementation Notes

`docs/CAPABILITY_CONTRACT_MODEL.md` remains the richer current target-state capability model. This stub ties that model to the SBS owner boundary and execution constraints.

## Open Questions

- Which existing capabilities need explicit versioned contracts first?
- Which authority classes require mechanical checks before invocation?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md`
- `docs/FINDING_AND_REORIENTING/README.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`
