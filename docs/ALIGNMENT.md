# Alignment Guide

## Why This Exists
- Keep the Agentic PKM API and agent tools aligned with the "Second-Brain" project goals.
- Protect the user's preferred way of working: short, concrete steps; iterate safely; default to open-source friendly solutions.
- Make expectations explicit so new changes can be checked against them quickly.

## Current Stage (Oct 2025)
- FastAPI backend in `app/` exposes `/`, `/items`, and `/context`.
- Agent workflow lives under `app/agent/`; `run_agent.py` is the CLI entry point.
- Data/context JSON drives memory and preferences for the agent.
- Alembic migrations are current with baseline `3ddfc7237248_baseline.py`.

## Near-Term Focus
- Rulla ut API-nyckel + rate limiting i deployment (env + Redis).
- Koppla loggar/metrics till observability-stack (t.ex. Grafana).
- Införa pre-commit-flöde (klar med hooks i repo, rulla ut i teamet).
- Planera data governance för arkiverade körningar (retention/purge regler).
- Bygg pipeline som flyttar chunkar från staging till huvudindex efter `trust="reviewed"`.
- Frontmatter-spec och API-kontrakt för /ingest och /recall (beskrivs nedan).

## Operating Principles
- Bias for maintainable, well-tested changes; add tests when behavior shifts or bugs are fixed.
- Prefer configuration via environment variables and `.env`, never check secrets into git.
- Leverage DuckDB locally (`storage/agent.duckdb`) unless requirements change.
- Document new behaviors (README, docs/) alongside code so the agent's memory stays current.

## Collaboration Norms
- Communication: respond in Swedish or English; keep replies kort & konkret.
- Process: one focused change at a time, TDD där det passar.
- Privacy: inga hemligheter i prompts; stay within opened context when possible.

## Decision Log
- 2025-10-18: Context loader added exposing repo memory through `/context`.
- 2025-10-18: Launch configuration standardized on debugpy attach at port `15678`.
- 2025-10-19: `run_agent.py` CLI now supports `--task`, `--input`, and `--dry-run` flags (plus tests).
- 2025-10-19: Added `/health` (DB ping) and `/version` endpoints with tests.
- 2025-10-19: FastAPI startup migrated to lifespan handler that ensures tables exist.
- 2025-10-19: `/health` now validates DuckDB connectivity and provenance.jsonl access.
- 2025-10-19: `/items` endpoints extracted to router with expanded coverage.
- 2025-10-19: CI pipeline (pytest, Ruff, mypy) established with supporting configs.
- 2025-10-19: Operations playbook dokumenterar versionering + lagringsrotation.
- 2025-10-19: `scripts/bump_version.py` infördes för att automatisera versionsflödet.
- 2025-10-19: `scripts/tag_release.py` automatiserar annoterade release-taggar.
- 2025-10-19: `scripts/rotate_storage.py` roterar DuckDB och provenance-loggar.
- 2025-10-19: Projektöversikt dokumenterad i `docs/PROJECT_OVERVIEW.md`.
- 2025-10-19: Auth + rate limiting strategi dokumenterad i `docs/AUTH_RATE_LIMITING.md`.
- 2025-10-19: Observability hooks (JSON-loggar + Prometheus via `METRICS_ENABLED`) aktiverade i `app/observability.py`.
- 2025-10-19: Pre-commit hooks för ruff/mypy/pytest tillagda (`.pre-commit-config.yaml`).
- 2025-10-19: Arkivrotation tillåter retention via `--max-age-days` i `scripts/rotate_storage.py`.
- 2025-10-19: Lokal observability-stack dokumenterad i `docs/OBSERVABILITY_STACK.md`.
- 2025-10-19: Docker Compose (API + Postgres + Redis) tillagd för stabil lokalbas.
- 2025-10-19: Frontmatter- och API-kontrakt specificerade för agentflödet.

## Frontmatter v0.1
```yaml
---
title: "<auto>"
origin: "<url|file>"
created: "YYYY-MM-DD"
tags: [topic/…, project/…]
trust: provisional|reviewed
source_ref: "<sha|url>"
amg:
  nodes: ["n:Concept/…","n:Entity/…"]
  edges: ["e:rel(type):A->B"]
chunks:
  algo: "recursive"
  size: 800
  overlap: 120
---
```

*Markdown filen ska alltid skrivas till Obsidian/vault med ovanstående frontmatter, följt av innehållet (t.ex. sammanfattning eller extraherad text).*

## API-kontrakt (MVP)

### `POST /ingest`
- **Request** (`multipart/form-data` eller JSON):
  ```json
  {
    "source": {
      "type": "file|url|text",
      "path": "/Users/rasmus/Documents/foo.pdf",
      "url": "https://example.com/foo",
      "text": "…"
    },
    "tags": ["topic/ai", "project/second-brain"],
    "notes": "valfri kommentar"
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "ok": true,
    "title": "Foo",
    "path": "vault/Foo.md",
    "tags": ["topic/ai", "project/second-brain"],
    "chunks": [
      {"id": "chunk-1", "text": "...", "size": 800},
      {"id": "chunk-2", "text": "...", "size": 640}
    ]
  }
  ```
- Sidolistan (`chunks`) används för att fylla Chroma v2 (`collection=second_brain`) och kopplas till `source_ref`.

### `GET /recall`
- **Query params**: `q` (frågetext), `k` (antal träffar, default 5)
- **Response** (`200 OK`):
  ```json
  {
    "query": "hur hänger ontocoding ihop med PKM?",
    "results": [
      {
        "path": "vault/Foo.md",
        "title": "Foo",
        "score": 0.83,
        "snippet": "…highlight…",
        "tags": ["topic/ai"]
      }
    ]
  }
  ```
- Resultatsvaret ska även logga `trace_id` i JSON-loggen så att klienten kan korrelera med loggar.

### Testfall (kommande)
- `tests/test_ingest_poc.py` – validerar att `/ingest` sparar frontmatter + pushar chunkar till Chroma.
- `tests/test_recall_poc.py` – validerar top-k recall (mockad Chroma tills riktig integration finns).

## Chunking v0.2 – Semantisk & Reviderbar

### Configuration
- `CHUNK_SIZE`: 800 (default via `settings.chunk_size` / env `CHUNK_SIZE`)
- `CHUNK_OVERLAP`: 120 (`settings.chunk_overlap`)
- `CHUNK_POLICY`: `semantic_v1` (förberedd att använda headings + token fallback)
- `CHUNK_SOURCE`: `headings|tokens`
- `CHUNK_STATE`: `staging|reviewed|indexed`

### Metadata schema
```json
{
  "chunk_id": "<uuid>",
  "doc_id": "<item_id>",
  "hash": "<sha1>",
  "state": "staging|reviewed|indexed",
  "source_ref": "<url|git_sha>",
  "title": "<string>",
  "tags": ["..."],
  "trust": "provisional|reviewed",
  "size": 800,
  "created": "ISO8601",
  "policy": "semantic_v1"
}
```

### Promotion flow
```
staging → reviewed → indexed
```
Chunkar genereras alltid i staging (`app.ingest.staging.PendingChunk`). När dokumentet markeras `trust="reviewed"` flyttas chunkarna in i huvudindex (DuckDB + Chroma). Fram tills dess kan sekundära RAG-processer läsa från staging.
