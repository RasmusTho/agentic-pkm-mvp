State: Partially outdated (target not implemented in SoT v4.10).
# ADR 0004: Control outbox-to-index latency <= 2s

Date: 2025-10-25  
Status (v4.10): Target not implemented; kept as future aspiration.

## Context
Goal was to guarantee ingest events flow through Outbox to indexing within ~2 seconds (QAS-010).

## Reality in SoT v4.10
- Outbox envelope/schema exists (`app/events/schema.py`, `docs/EVENTS.md`), but Reality-MVP does not run an outbox worker or enforce latency SLAs.
- Indexing is in-process during ingest; there is no poller or CI latency assertion.
- Metrics/alerts for outbox lag are not present.

## Decision (historical target)
- Persist ingest mutations to an `outbox` table and poll into the indexer with deterministic embeddings.
- Assert in CI that outbox→index completes within 2 seconds.

## Current implementation
- No outbox poller/worker or latency test in CI.
- Indexing happens synchronously in the ingest path; outbox events are not the gating mechanism.

## Guidance
- Treat the latency target as future/roadmap work. If reintroduced, add worker + CI checks and observability.
