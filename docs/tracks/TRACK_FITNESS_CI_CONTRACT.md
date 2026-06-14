State: Fitness/CI gates from v4.5B–v4.6 live; reasoning/A2A/MCP gates planned but flag-gated.
# Track — Fitness & CI Contract

Scope: deterministic fitness functions, CI summary lines, baselines, and gating for retrieval, rerank, relations, diarization, and future reasoning.

## Delivered (v4.5B–v4.6)
- Fitness guards QAS-003 (hybrid search latency) and QAS-010 (outbox→index latency) enforced via `app.fitness.report`; CI parses summary lines and fails on regression.
- ce_local rerank heuristics + golden set expansion (16 queries × 10 candidates); evaluation deltas reported in CI summary.
- Relation coverage/validity gates (≥95%) with audit events (`relation.added` / `relation.missing`); baselines in `ops/quality/baselines.yaml`.
- Diarization-aware chunking metrics with CI summary line for chunk p95 and speaker avg; flag-controlled via `DIARIZE_ENABLE`.
- CI summary lines emitted and parsed (latency, eval, eval delta, relation coverage/validity, diarization); `GATE_STRICT` tightens expectations; deterministic memory backend defaults.

## Planned
- Reasoning layer gates (claims/inferences/conflicts) under `REASONING_ENABLE` once delivered.
- A2A/MCP execution metrics once orchestration routes real tool calls; maintain mock determinism in CI.

## Links
- Roadmap Now/Next: `docs/ROADMAP.md`.
- Historical detail: removed from the live repo; use git history for the old v4.x ladder.
- Pattern harvest/backlog: `docs/research/pattern-harvest-agentic-architecture.md`.
