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
- Stage watcher och review endpoints finns nu; LangGraph-agent behöver kopplas mot `/ingest/pending` + `/ingest/review` för att automatisera QA & promotion.

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
- 2025-10-19: Observability hooks (JSON-loggar + Prometheus via `METRICS_ENABLED`) aktiverade i `app/observability.py`.
- 2025-10-19: Pre-commit hooks för ruff/mypy/pytest tillagda (`.pre-commit-config.yaml`).
- 2025-10-19: Arkivrotation tillåter retention via `--max-age-days` i `scripts/rotate_storage.py`.
- 2025-10-19: Lokal observability-stack dokumenterad i `docs/OBSERVABILITY_STACK.md` och Docker Compose-basen etablerad.
- 2025-10-19: Frontmatter- och API-kontrakt specificerade för agentflödet (docs/ALIGNMENT.md, README).
- 2025-10-19: Lokal watcher och vault-ingest (Obsidian `@Inbox`) implementerat via `app/ingest/watcher.py`.
- 2025-10-19: DuckDB-staging och review endpoints (`/ingest/pending`, `/ingest/review`) tillagda för agentstyrd QA.
- 2025-10-19: Semantic chunking & categorization scheman dokumenterade i alignment + system context.
- Äldre poster finns arkiverade i `docs/archive/decision-log-2025-10.md`.

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
CHUNK_SIZE: 800
CHUNK_OVERLAP: 120
CHUNK_POLICY: semantic
CHUNK_SOURCE: headings|tokens
CHUNK_STATE: staging|reviewed|indexed

### Metadata schema
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

### Promotion flow
staging → review → approve → index(main)

Chunkar genereras alltid i staging (`app.ingest.staging.PendingChunk`). När dokumentet markeras `trust="reviewed"` flyttas chunkarna in i huvudindex (DuckDB + Chroma). Fram tills dess kan sekundära RAG-processer läsa från staging.

## Categorization v0.1 – Semantisk Labeling

### Schema
{
  "quality.class": "spam|ham|low_quality|medium|high",
  "credibility": "unverified|credible|expert_consensus",
  "factuality": "fact|hypothesis|opinion|satire",
  "source_type": "email|youtube|article|paper|transcript|chatlog",
  "topic.primary": "mathematics|psychology|biology|philosophy|politics|economics|literature|history|other",
  "topic.secondary": ["free-form tags"]
}

### Flow
QA_GATE → CATEGORIZE → CHUNK
CATEGORIZE output is validated and written into frontmatter and metadata index.
