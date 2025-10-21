# Agent Service Component Overview

```mermaid
graph TD
    subgraph Runtime
        API[FastAPI app/main.py]
        AgentSvc[AgentService loop]
        ConfigMgr[AgentConfigManager]
        Repo[PostgresAgentRepository]
        Plugins[Plugin Loader]
        Retriever[retriever tool]
        Writer[write_note tool]
        WebGet[web_get tool]
    end

    subgraph Storage
        PG[(Postgres + pgvector)]
        Context[data/context/*.json]
        Reflect[storage/reflect/*.json]
        Logs[logs/*.json(l)]
    end

    subgraph Operations
        Alembic[Alembic migrations]
        ConfigFile[config/agent.yaml]
    end

    API -->|lifespan| AgentSvc
    AgentSvc --> ConfigMgr
    AgentSvc --> Repo
    AgentSvc --> Plugins
    Plugins --> Retriever
    Plugins --> Writer
    Plugins --> WebGet
    Retriever --> PG
    Writer --> Repo
    Writer --> Logs
    AgentSvc --> Logs
    AgentSvc --> Reflect
    Repo --> PG
    ConfigMgr --> ConfigFile
    Alembic --> PG
    API --> Context
    AgentSvc --> Context

    %% Missing / planned components
    subgraph Missing
        Watcher[File watcher ingest pipeline (removed)]
        Promotion[Ingest promotion endpoints / automation]
    end

    Watcher -.-> API
    Promotion -.-> API
```

## Gaps & Follow-Ups
- **File watcher ingestion**: Documentation now treats the watcher as legacy (tracked in `docs/TODO.md`); rebuild `app/ingest/watcher.py` or rely solely on `/ingest`.
- **Automation for promotion workflow**: The roadmap mentions `/ingest/pending` and `/ingest/review`; those endpoints are absent, so the cycle from provisional → reviewed is manual.
- **Observability hooks**: Logs and metrics exist, but running the agent standalone bypasses API middleware that sets up Prometheus and rate limiting.
- **Config drift**: Only a single agent config file is supported; validation warnings now surface in logs when parsing fails, but multi-profile support remains future work.
