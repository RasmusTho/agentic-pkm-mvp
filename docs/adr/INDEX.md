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
- [ADR 0009: Orientation MemoryCandidate intent threshold and trace semantics (accepted, implemented by #1457)](./ADR-0009-orientation-memory-candidate-intent.md)
- [ADR 0010: BuilderOps Vault authority and promotion boundary (accepted, docs/governance)](./ADR-0010-builderops-vault-authority-boundary.md)
- [ADR 0011: Orientation push and ambient resurfacing boundary (accepted, docs/governance)](./ADR-0011-orientation-push-ambient-resurfacing.md)
- [ADR 0012: Orientation multi-agent reads boundary (accepted, docs/governance)](./ADR-0012-orientation-multiagent-reads.md)
- [ADR 0013: Code dependency direction — directional import-boundary contract (accepted, pending merge via #2070)](./ADR-0013-code-dependency-direction.md)
- [ADR 0014: Path-injection posture for the operator-chosen vault path (accepted, accept-and-dismiss)](./ADR-0014-vault-path-injection-posture.md)
- [ADR 0015: Adopt authority-first, volatility-disciplined target SBS](./ADR-0015-authority-first-target-sbs.md)
- [ADR 0016: Use contract-first, module-lazy instantiation](./ADR-0016-contract-first-module-lazy-sbs.md)
- [ADR 0017: Preserve one irreplaceable human knowledge set plus durable governance receipts](./ADR-0017-human-knowledge-and-governance-survivability.md)
- [ADR 0018: Split provenance into artifact-origin, action/decision, and derived semantic lineage](./ADR-0018-provenance-split.md)
- [ADR 0019: Enforce governed writes with DecisionToken and AuthorityReceipt](./ADR-0019-governed-writes-decision-token-authority-receipt.md)
- [ADR 0020: Declare SFC now with single-node/no-op posture until federation is scheduled](./ADR-0020-sfc-single-node-upgrade-path.md)
- [ADR 0021: Treat CES as architecture stewardship practice, not a runtime peer subsystem](./ADR-0021-ces-architecture-stewardship-practice.md)
- [ADR 0022: Treat OEF as first-class but non-authoritative](./ADR-0022-oef-first-class-non-authoritative.md)
