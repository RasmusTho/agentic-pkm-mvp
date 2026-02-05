State: ADR (historical).
# ADR 0005: Standardize PER-loop agent base

Date: 2025-10-25
Status: Accepted

## Context
Each agent (Normalizer, Classifier, etc.) follows Plan → Execute → Reflect semantics. The implementation was ad-hoc, making it harder to propagate trace IDs and shared behavior.

## Decision
- Provide `app.agents.base.loop.Agent` with `plan`, `act`, `reflect`, and `run` methods.
- Ensure every agent uses this base or mirrors its structure; `run` generates/propagates `trace_id`.
- Emit reflection events via `reflection_event` helper for downstream observability.

## Consequences
- Easier testing of agent lifecycles (single place to assert trace propagation).
- Shared extension point for future metrics/OTel spans.

## Alternatives
- Keep bespoke loops per agent (rejected as too error-prone).
