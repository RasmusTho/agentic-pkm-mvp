State: ADR (historical).
# ADR 0004: Control outbox-to-index latency <= 2s

Date: 2025-10-25
Status: Accepted

## Delta vs SoT v5.5 baseline (current)
- The system uses a DB outbox as the canonical queue; JSONL outbox is audit/diagnostic only.
- The 2s outbox→index latency target is not enforced as a hard CI gate in the current baseline (treat this ADR as a design intent, not an operational guarantee).

## Context
Promotion and search rely on ingest events flowing through the outbox into the indexer in near real time. We target QAS-010 (eventual consistency <=2s).

## Decision
- Persist all ingest mutations to the `outbox` table with `occurred_at` timestamps.
- Run a lightweight worker polling the outbox and writing deterministic embeddings.
- Assert in CI (pytest) that outbox→index completes within 2 seconds.

## Consequences
- Requires operational monitoring for worker lag.
- Simplifies promotion/export flows; deterministic embeddings keep tests reproducible.

## Alternatives
- Use external queue (Kafka, Redis streams) – postponed until throughput demands it.
