State: Accepted (target-state architecture decision, 2026-06-21).
Doc role: Decision record (ADR)
Authority: Authoritative target decision for CES as stewardship practice rather than runtime subsystem.
Owner: CES practice / Architecture spine
Temporal class: Durable decision
Source of truth: This ADR plus operationalization docs

# ADR-0021: Treat CES as architecture stewardship practice, not a runtime peer subsystem

**Date:** 2026-06-21
**Status:** Accepted

## Context

The target SBS needs durable contracts, ADRs, glossary stewardship, compatibility rules, deprecation rules, boundary ownership, and change-impact playbooks. Turning that into a runtime subsystem would create unnecessary machinery and a likely god-core.

## Decision

Contract & Evolution Stewardship remains explicit as architecture practice: ADRs, charters, glossary, compatibility rules, deprecation rules, boundary ownership, and change-impact playbooks.

Executable enforcement lives in OEF/CI through dependency checks, contract tests, forbidden import checks, and architecture fitness rules.

## Consequences

- Architecture discipline becomes real without creating a runtime god subsystem.
- CES is tracked in the boundary register as a practice, not a physical module.
- OEF/CI owns executable enforcement where practical.

## Validation

Process surfaces include ADRs, contract stubs, registers, roadmap/status/index references, issue tracking, and PR SBS impact classification.

## References

- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`
- `docs/architecture/SBS_BOUNDARY_REGISTER.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
- `.github/pull_request_template.md`
