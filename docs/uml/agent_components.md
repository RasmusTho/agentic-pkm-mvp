# Agent Service Component Overview

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

## Gaps & Follow-Ups
- **File watcher ingestion**: Dokumentationen flaggar watchern som legacy (se `docs/TODO.md`); ersätt med script/UI-trigger.
- **Promotion automation**: `/ingest/pending` och `/ingest/review` saknas fortfarande; utan dem är provisional → reviewed manuellt.
- **Loggrotation & alerting**: Supervisor/agent-loggar ligger i `/tmp`; konfigurera rotation och larm för frekventa omstarter.
- **Konfigurationsdrift**: Endast en `config/agent.yaml`-profil stöds; överväg validering + multi-profile om behov uppstår.
