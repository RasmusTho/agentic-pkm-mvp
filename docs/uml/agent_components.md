State: Legacy (archived); component diagram is not current. See `docs/DIAGRAMS.md` for Reality-MVP.
# Agent Service Component Overview (historical)

```mermaid
graph TD
    subgraph Runtime
        Supervisor[start_agent_service.py]
        RunAgent[run_agent.py]
        API[FastAPI app/main.py]
        AgentSvc[AgentService / LangGraph]
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

    Supervisor -->|spawns| RunAgent
    RunAgent --> AgentSvc
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

## Notes
- Depicts run_agent.py-era services and plugins that are not part of Reality-MVP. Current runtime is FastAPI + agents/ASK + ingest CLI; see `docs/ARCHITECTURE.md` and `docs/DIAGRAMS.md` for the canonical view.
