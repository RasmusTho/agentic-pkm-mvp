State: Index (historical). ADRs are design records and may be partially outdated; treat as references, not runtime truth.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# ADR Index

- [ADR 0004: Control outbox-to-index latency <= 2s](./0004-outbox-latency.md)
- [ADR 0005: Standardize PER-loop agent base](./0005-per-loop.md)
- [ADR 0006: DeepAgents as outer agent harness (proposed)](./ADR-0006-deepagents-harness.md)
- [ADR 0007: Workspace State Contract — artifact-scoped vs note-independent scope split (proposed)](./ADR-0007-workspace-state-contract-scope-split.md)
- [ADR 0008: Leave-point cursor as bounded operational trace (proposed)](./ADR-0008-leave-point-cursor.md)
- [ADR 0009: Orientation MemoryCandidate intent threshold and trace semantics (proposed)](./ADR-0009-orientation-memory-candidate-intent.md)
- [ADR: Agentminne v1](./ADR-00X-agent-memory-v1.md)
- [ADR: Agentminne v4.2](./ADR-00X-agent-memory-v42.md)
