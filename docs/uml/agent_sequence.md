# Agent Service Sequence

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant CLI as start_agent_service.py
    participant Alembic as Alembic CLI
    participant PG as Postgres
    participant ConfigMgr as AgentConfigManager
    participant Service as AgentService
    participant Repo as PostgresAgentRepository
    participant Plugins as Plugin Loader
    participant Tools as Plugins (retriever, write_note, web_get)

    Dev->>CLI: python scripts/start_agent_service.py
    CLI->>Alembic: command.upgrade(config, "head")
    Alembic-->>PG: Apply migrations
    PG-->>Alembic: Schema up-to-date
    CLI->>Repo: PostgresAgentRepository(settings.psycopg_dsn)
    CLI->>ConfigMgr: load config/agent.yaml + start watch thread
    CLI->>Service: AgentService(repo, config_manager)
    CLI->>Service: start()
    Service->>ConfigMgr: get_config()
    Service->>Repo: record_run_start(run_id, config)
    Service->>Repo: record_heartbeat(agent_name, run_id, "running")
    Service->>Plugins: load_tools(config.enabled_plugins)
    Plugins-->>Service: {"retriever", "write_note", ...}
    Service->>Tools: execute_plan(actions)
    Tools-->>Repo: register_task / complete_task
    Tools-->>Repo: add_memory (write_note)
    Tools-->>PG: search_hybrid (retriever)
    Service->>Repo: upsert_interesting_item()
    Service->>Repo: record_run_complete(..., "completed")
    Service->>Repo: record_heartbeat(agent_name, run_id, "idle")
    Service->>ConfigMgr: wait for interval + jitter
    Service-->>Service: repeat loop until stop signal
```

## Observed/Potential Issues
- **Local runs assume repo root on `sys.path`**: the script now injects the repository root automatically, but any custom entrypoint must do the same before importing `app.*`.
- **Empty tool outputs without ingest**: the default plan queries `seed_queries`, but if `/ingest` has never populated `objects`/`embeddings`, retriever returns zero results and downstream interestingness scores nothing.
- **No watcher pipeline**: docs still reference `app/ingest/watcher.py`, but that module is no longer present, so dropping files into the legacy watch folder has no effect (tracked in `docs/TODO.md`).
- **Configuration reload**: invalid YAML now triggers a warning and defaults, but consider adding higher-level alerts if repeated.
- **Reflection queue errors**: failures are logged as warnings; add monitoring if these appear frequently.
