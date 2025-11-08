# Agentic PKM — SoT v4.5 snapshot

## Overview

Agentic PKM is a file-first knowledge system where FastAPI surfaces route requests into LangGraph agents that run PER loops (Plan → Execute → Reflect). Agents write through Store interfaces (ObjectStore, VectorIndex, RelationIndex plan) that sit on top of Postgres 16 with pgvector. Interesting API endpoints prefer repository-backed methods with an in-memory fallback for tests. Events flow through a table-backed Outbox; workers poll, invoke handlers, and `ack` rows to keep downstream consumers (Indexer, Reviewer, Promotion, MergeResolver) coordinated. All interactions stay diffable and deterministic, so the Obsidian vault remains the human-facing source of truth while Stores, Agents, and the API present a consistent system view.

### Services & Ports

| Service     | Host Port → Container | Notes                         |
|-------------|-----------------------|-------------------------------|
| API         | 18000 → 8000          | FastAPI dev server            |
| Postgres    | 15432 → 5432          | Postgres 16                   |
| pgAdmin     | 5050 → 80             | Optional admin UI             |
| debugpy     | 15678 → 5678          | VS Code attach (Agents/API)   |

## Quick start (dev)

1. `python -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. `pytest -q`

Docker/Colima is the default runtime for shared services (`docker compose up`). Portainer (https://localhost:9443) is available when you need a UI to inspect containers.

## Architecture at a glance

See full details in [ARCHITECTURE](docs/ARCHITECTURE.md), [AGENTS](docs/AGENTS.md), and [EVENTS](docs/EVENTS.md).

```mermaid
flowchart TB
  subgraph Client
    U[User]
    OB[Obsidian Vault]
  end

  subgraph Backend
    API[FastAPI API]
    AG[Agents (LangGraph, PER loop)]
    STO[ObjectStore]
    VEC[VectorIndex (pgvector)]
    REL[(RelationIndex - planned)]
    DB[(Postgres 16)]
    OUT[(Outbox table)]
    WRK[Outbox Worker]
  end

  U --> API
  OB --> API
  API --> AG
  AG --> STO
  STO --> DB
  AG --> VEC
  AG -. planned .-> REL
  AG --> OUT
  WRK --> OUT
  WRK --> AG
```

Diagram source: [docs/diagrams/architecture.mmd](docs/diagrams/architecture.mmd).

## Status

**Status (2025-11-08):** Test suite green on `chore/ingest-export-fixes`. See [STATUS](docs/STATUS.md).

## Changelog

Latest updates are tracked in [docs/CHANGELOG.md](docs/CHANGELOG.md).
