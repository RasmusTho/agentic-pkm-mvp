# ADR 0004: Control outbox-to-index latency <= 2s

Date: 2025-10-25
Status: Accepted

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
