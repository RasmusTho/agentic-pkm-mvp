State: Accepted (target-state architecture decision, 2026-06-21).
Doc role: Decision record (ADR)
Authority: Authoritative decision to adopt the target SBS decomposition as the long-horizon architecture reference.
Owner: Architecture spine / CES practice
Temporal class: Durable decision
Source of truth: This ADR plus `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`

# ADR-0015: Adopt authority-first, volatility-disciplined target SBS

**Date:** 2026-06-21
**Status:** Accepted

## Context

Yggdrasil needs to remain viable despite likely replacement of Obsidian, vault assumptions, retrieval engines, embeddings, memory architecture, agent runtimes, storage, sync, and UI.

## Decision

Yggdrasil adopts a target SBS based on authority boundaries, volatility boundaries, and systems-of-systems thinking rather than current implementation structures.

## Consequences

- Architecture work classifies changes by target subsystem.
- Boundaries between knowledge, memory, retrieval, governance, execution, storage, sync, UI, and integrations are protected.
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` owns long-horizon decomposition while `docs/ARCHITECTURE.md` owns current runtime behavior.

## Validation

Future major changes must identify primary and secondary SBS subsystem impact in docs, issues, or PR process.

## References

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`
- `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`
