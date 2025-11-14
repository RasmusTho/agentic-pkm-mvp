# Local Ports & Services

The workspace binds a few predictable ports whenever you run the local Docker stack, observability helpers, or the Ollama LLM runtime. Use the table below to see which script or container owns each port and where it is configured.

| Port(s) | Owner / Component | Where It’s Defined | Notes |
| --- | --- | --- | --- |
| 1455 | _unused_ | — | Historical tunnel placeholder. No scripts reference it; if a listener appears it is not part of this repo. |
| 4317 | Jaeger gRPC ingest | `otelcol.yaml`, `scripts/dev/init_vault.py`, `vault/_system/settings/system-settings.yaml` | The OpenTelemetry Collector exports traces to `jaeger:4317`, and bootstrap settings point `observability.otlp_endpoint` at `http://localhost:4317`. Start Jaeger (e.g. via Docker) if you want traces on this port. |
| 4318 | OTLP/HTTP receiver | `otelcol.yaml`, `vault/_system/settings/system-settings.yaml` | Collector listens on `0.0.0.0:4318` for OTLP/HTTP spans. All agents read the endpoint from settings, so set `observability.otlp_endpoint` if you move it. |
| 5432 ↔ 15432 | Postgres (container ↔ host) | `docker-compose.yaml` (`db` service), numerous `DATABASE_URL` defaults (e.g. `app/agents/base/memory.py`) | Postgres runs inside Docker on 5432 and is published to the host on 15432. All scripts default to `postgresql://app:app@127.0.0.1:15432/app` unless `DATABASE_URL` overrides it. |
| 15433 | _unused_ | — | Mentioned in legacy ops notes as an “idle watcher”, but no container binds it. Safe to reuse or remove from checklists. |
| 8000 | FastAPI / Uvicorn in-container | `Dockerfile`, `scripts/start_api.sh`, `docker-compose.yaml` (`api` service) | The API process always listens on 8000 inside containers. Docker publishes it to 18000 for host access (see below). Enable metrics (`METRICS_ENABLED=1`) to expose `/metrics` on the same port. |
| 11434 | Ollama HTTP API | `app/services/llm.py`, `app/llm/embeddings.py`, docs (`docs/LLM*.md`) | Local inference defaults to `http://127.0.0.1:11434`. Update `OLLAMA_HOST` / `OLLAMA_URL` env vars if you run Ollama elsewhere. |
| 16686 | Jaeger UI | `scripts/dev/init_vault.py`, `vault/_system/settings/system-settings.yaml` | Only referenced as a URL in settings so links inside the app point at the standard Jaeger UI. Requires a separate Jaeger container or desktop app. |
| 18000 | Host-exposed API | `docker-compose.yaml`, tooling (`scripts/query_ws.py`, `scripts/k6_search.js`, `docs/RUNBOOK.md`) | Docker maps container port 8000 to host port 18000 so browsers and tests can hit `http://localhost:18000/...`. |
| 18001 | _unused_ | — | Listed in historical notes as a reload socket. No scripts bind or expect it. |

## Quick verification commands

```bash
# Postgres
pg_isready -h 127.0.0.1 -p 15432 -d app

# API health (host mapping)
curl -sS http://127.0.0.1:18000/healthz

# Ollama
curl -sS http://127.0.0.1:11434/api/tags | jq .
```

Run `docker compose up api db` to start the API/Postgres ports, `docker compose -f ops/observability/docker-compose.yaml up` for the OTLP + Jaeger stack, and `ollama serve` for 11434.
