State: SoT v4.10 Reality-MVP (current core).
# Global System Design — SoT v4.10 Reality-MVP

## Purpose & Scope
- Defines the global system design for the Reality-MVP, covering external dependencies, runtime components, and how they support the Human Flows.
- Anchors the SoT v4.10 runtime (single-user, vault-first) and points other docs (ARCHITECTURE, HUMAN-FLOWS, LLM, OBSERVABILITY_STACK) at the same reference surface.

## System Context (C4-style)
- Human user (Obsidian vault as Mimer, CLI, HTTP tools) creates/edits notes, runs ingest/ASK, and reads answers.
- Yggdrasil runtime (API + Agent processes) hosts ingestion, ASK, panel handling, promotion, and evaluation logic.
- Postgres/pgvector hold ObjectStore, VectorIndex, RelationIndex (where used), and Store-backed metadata.
- Redis (optional) for lightweight caches/queues; not required for core Reality-MVP runs.
- Ollama provides chat/LLM and embedding models locally.
- Observability stack (Prometheus, Grafana, Loki) scrapes metrics, renders dashboards, and aggregates logs.
- Git/GitHub store code, docs, and VaultMirror history; optional iCloud/Git move vault text between machines.

## Reference Deployment Topology (host)
- Container runtime: Docker/Colima (or compatible). Services can also run bare-metal for local dev.
- Core services (ports are defaults; adjust via env/compose):

| Service | Port | Required? | Notes |
| --- | ---: | --- | --- |
| api (FastAPI app.main) | 18000 | Yes | Reality-MVP HTTP API (`/api/status`, `/api/ask`, `/api/ingest`) |
| agent (PER/worker) | 18001 | Optional | Legacy/secondary API; can host agent loop endpoints |
| db (Postgres + pgvector) | 15432 | Yes | Stores ObjectStore/VectorIndex/RelationIndex tables |
| redis | 6379 | Optional | Used for transient queues/caches when enabled |
| ollama | 11434 | Yes (LLM) | Local LLM + embedding models |
| grafana | 3000 | Optional | Dashboards (pulls from Prometheus/Loki) |
| prometheus | 9090 | Optional | Scrapes API metrics when `METRICS_ENABLED=1` |
| loki | 3100 | Optional | Log aggregation for API/agents |
| portainer | 9443 | Optional | Container introspection; not required for core runs |

- Key environment variables (examples): `STORE_BACKEND=pg`, `DATABASE_URL=postgresql+psycopg://app:app@localhost:15432/app`, `INDEX_OUTBOX_PATH=./index-outbox.jsonl`, `LLM_PROVIDER=ollama`, `LLM_MODEL=llama3.1:8b`, `EMBED_MODEL=nomic-embed-text`, `RERANK_MODEL=llama3.1:8b`, `OPENAI_BASE_URL`/`OPENAI_API_KEY` (only when using remote providers), `METRICS_ENABLED=1`, `OBSERVABILITY_OTLP_ENDPOINT=http://localhost:4318`.

## Surfaces

| Surface | Role | Components hit |
| --- | --- | --- |
| Obsidian vault(s) (Mimer) | Human editing/reading; panels live in-note | Ingest CLI → ObjectStore/VectorIndex + VaultMirror; PanelAgent emits outbox events |
| CLI (`pipe`, `ask`, ingest helpers) | Local orchestration for ingest and ASK | CLI → API/agents → Stores (ObjectStore/VectorIndex/Outbox) |
| HTTP API (`/api/ask`, `/api/status`) | Programmatic ASK and status | API container → Stores + LLMs; emits metrics/logs |
| AI panel in notes | Human-to-system intent and suggestions | PanelAgent → Outbox → downstream classification/promotion |

## Stores & Data

| Store | Backend (Reality-MVP) | Data held | Human Flows |
| --- | --- | --- | --- |
| ObjectStore | Postgres | Canonical objects, metadata payloads, fingerprints | Capture & Ingest, ASK, Review & Promotion |
| VectorIndex | Postgres/pgvector | Embeddings for retrieval/rerank | Capture & Ingest, ASK |
| RelationIndex | Postgres (emerging) | Relations/edges; partial in v4.10 | ASK (early), future KG |
| Outbox | JSONL file (or DB table) | Events from ingest, panels, promotion, review | Capture & Ingest, Panel Interaction, Review & Promotion, Eval & QA |
| VaultMirror | Files under `System/Metadata/VaultMirror/**` | Per-note UUID + log | Capture & Ingest, Review & Promotion |

## LLM & Embeddings

| Use case | Component | Default (local) | Notes |
| --- | --- | --- | --- |
| ASK answering/drafting | ASK Agent | `LLM_MODEL=llama3.1:8b` (Ollama) | Switch via `LLM_PROVIDER`/`LLM_MODEL`; remote providers optional |
| Embeddings | Indexer | `EMBED_MODEL=nomic-embed-text` (Ollama) | Feeds VectorIndex |
| Rerank/self-check | ASK Agent | `RERANK_MODEL=llama3.1:8b` | Can share chat model |
| Panel suggestions | PanelAgent | `LLM_MODEL` | Lightweight prompts, no indexing of panel text |
| Eval/QA mocks | Eval stack | `LLM_PROVIDER=mock` or CI fixtures | Keeps CI deterministic |

## Observability
- API and agents export Prometheus metrics when `METRICS_ENABLED=1`; scraped by Prometheus, visualized in Grafana.
- Structured JSON logs go to stdout; Loki (optional) aggregates for queries/dashboards.
- Key signals: ingest throughput/errors, ASK latency and hit counts, panel intent events, promotion/review outcomes, OTLP traces when enabled.

## Human Flows → Infrastructure

| Flow | Entry surface | Agents/components | Stores touched | External deps |
| --- | --- | --- | --- | --- |
| Capture & Ingest | Obsidian, CLI ingest | Watcher/ingest CLI, Normalizer, Classifier, Chunker, Deduper, Indexer | ObjectStore, VectorIndex, VaultMirror, Outbox | Postgres/pgvector, Ollama (embeds), filesystem |
| ASK | CLI `ask`, `/api/ask` | ASK Agent (retrieve/rerank/answer) | ObjectStore, VectorIndex | Postgres/pgvector, Ollama (chat/rerank) |
| Review & Promotion | CLI/API triggers | Reviewer, SetEvaluator, Promotion Agent | ObjectStore, Outbox, VaultMirror | Postgres, outbox sink |
| Panel Interaction | Obsidian panels | PanelAgent → downstream classifiers | Outbox, ObjectStore (after follow-up) | Postgres, Ollama (suggestions) |
| Eval & QA | CLI eval | Eval runners, ASK Agent | ObjectStore, VectorIndex, Outbox | Postgres/pgvector, Ollama or mock LLMs |

## Future Work / SoT v5.x (planned)
- Richer RelationIndex/knowledge graph across objects.
- Satellite instances and sync protocol hardening.
- Munin/media pipelines and heavier external corpus ingest.
- Expanded observability (full OTLP traces, panel/promotion dashboards).
- Optional vLLM/remote provider support for larger models.
