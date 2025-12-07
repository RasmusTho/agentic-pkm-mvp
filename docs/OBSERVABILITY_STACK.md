State: SoT v4.10 Reality-MVP (current core).
# Local Observability Stack

This repo already emits structured logs (JSON) and exposes Prometheus metrics when `METRICS_ENABLED=1`. The steps below give a lightweight single-developer setup to inspect those signals locally.
See `docs/SYSTEM_DESIGN_v4.10.md` for how observability ties into the full system design.

## Prerequisites
- Docker Desktop (or any Docker engine)
- API server running locally on port 18000 with `METRICS_ENABLED=1`

```bash
export METRICS_ENABLED=1
uvicorn app.main:app --reload --port 18000
```

## Start Prometheus + Grafana
```bash
docker compose -f ops/observability/docker-compose.yaml up
```

- Prometheus UI: http://localhost:9090 (uses `ops/observability/prometheus.yml` to scrape `host.docker.internal:18000/metrics`)
- Grafana UI: http://localhost:3000 (default login admin/admin)

Add Prometheus as a data source in Grafana (URL `http://prometheus:9090`) and build dashboards from metrics such as `http_requests_total` and `http_request_duration_seconds_bucket`.

When finished:
```bash
docker compose -f ops/observability/docker-compose.yaml down
```

## Flow coverage (Reality-MVP)
- Capture & Ingest: metrics for ingest throughput/errors, Outbox event counts; logs for normalization/classification steps.
- ASK: request latency/volume, rerank/LLM timings, answer error rates; traces when OTLP is enabled.
- Review & Promotion: promotion/review events in Outbox, frontmatter write spans, guardrail counters.
- Panel Interaction: panel intent events in Outbox; verify no panel text enters embeddings via ingest logs.
- Eval & QA: CI-safe logs/metrics around eval runs; optional ASK traces when running locally with OTLP.

## Log Consumption
While the stack runs, the API logs JSON to stdout. For quick inspection:
```bash
uvicorn app.main:app --reload | jq
```

For archival or forward shipping, feed stdout into your preferred log collector (Elastic, Loki, etc.).
