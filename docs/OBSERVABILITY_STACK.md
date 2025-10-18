# Local Observability Stack

This repo already emits structured logs (JSON) and exposes Prometheus metrics when `METRICS_ENABLED=1`. The steps below give a lightweight single-developer setup to inspect those signals locally.

## Prerequisites
- Docker Desktop (or any Docker engine)
- API server running locally on port 8000 with `METRICS_ENABLED=1`

```bash
export METRICS_ENABLED=1
uvicorn app.main:app --reload
```

## Start Prometheus + Grafana
```bash
docker compose -f ops/observability/docker-compose.yaml up
```

- Prometheus UI: http://localhost:9090 (uses `ops/observability/prometheus.yml` to scrape `host.docker.internal:8000/metrics`)
- Grafana UI: http://localhost:3000 (default login admin/admin)

Add Prometheus as a data source in Grafana (URL `http://prometheus:9090`) and build dashboards from metrics such as `http_requests_total` and `http_request_duration_seconds_bucket`.

When finished:
```bash
docker compose -f ops/observability/docker-compose.yaml down
```

## Log Consumption
While the stack runs, the API logs JSON to stdout. For quick inspection:
```bash
uvicorn app.main:app --reload | jq
```

For archival or forward shipping, feed stdout into your preferred log collector (Elastic, Loki, etc.).
