State: Accepted (target-state architecture decision, 2026-06-21).
Doc role: Decision record (ADR)
Authority: Authoritative target decision for OEF posture.
Owner: OEF / Architecture spine
Temporal class: Durable decision
Source of truth: This ADR plus `docs/architecture/SBS_FITNESS_RULES.md`

# ADR-0022: Treat OEF as first-class but non-authoritative

**Date:** 2026-06-21
**Status:** Accepted

## Context

Trust requires inspectability, diagnostics, evaluations, architecture fitness, and drift detection. Observability can also become unsafe if it silently rewrites policy, memory, retrieval, knowledge, agent behavior, configuration, or execution.

## Decision

Observability, Evaluation & Fitness is first-class because trust requires inspectability.

OEF may observe, trace, detect, evaluate, explain, warn, block CI when configured, produce findings, and propose remediation.

OEF must not silently rewrite policy, memory, retrieval, knowledge, agent behavior, configuration, or execution.

## Consequences

- The system gains architecture fitness and diagnostics without introducing an ungoverned control loop.
- OEF can enforce in CI where configured.
- Runtime remediation remains routed through GOV, HIX, EXE, or normal development workflow.

## Validation

The SBS fitness rules classify OEF automatic mutation of policy, memory, retrieval, knowledge, or execution as a blocking target invariant.

## References

- `docs/architecture/SBS_FITNESS_RULES.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/OBSERVABILITY.md`
- `docs/TESTING.md`
