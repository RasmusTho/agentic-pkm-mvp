State: Legacy (archived); describes old supervisor loop. See DIAGRAMS.md for current topology.
# Agent Supervisor Sequence (historical)

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Sup as start_agent_service.py
    participant Env as dotenv (optional)
    participant Alembic as Alembic CLI
    participant PG as Postgres
    participant Agent as run_agent.py
    participant Graph as LangGraph workflow
    participant Log as /tmp/agent_app.log

    Dev->>Sup: python scripts/start_agent_service.py
    Sup->>Env: load .env (if python-dotenv)
    Env-->>Sup: env merged / skipped
    Sup->>Alembic: alembic -c app/alembic.ini current
    Alembic-->>Sup: output (may contain (head))
    alt Already at head
        Sup->>Sup: log \"Detected Alembic at HEAD — skipping migrations\"
    else Needs upgrade
        Sup->>Alembic: alembic -c app/alembic.ini upgrade head (timeout 180s)
        Alembic-->>Sup: migrations applied
    end
    Sup->>Sup: log \"Starting agent loop…\"
    loop until SIGTERM/SIGINT
        Sup->>Agent: spawn python -u run_agent.py
        Agent->>Log: append stdout/stderr
        Agent->>Graph: invoke task/profile pipeline
        Graph-->>Agent: result / error
        Agent-->>Sup: exit code
        alt exit==0 and stop not set
            Sup->>Sup: log \"Agent exited with code 0 — restarting in 30s\"
        else exit!=0
            Sup->>Sup: log warning + restart countdown
        end
        Sup->>Sup: wait 30s (interrupted by stop_event)
    end
    Sup->>Sup: handle shutdown (terminate agent, close loop)
```

## Notes
- Captures a v4.x supervisor/run_agent.py restart loop that is not part of Reality-MVP.
- Ingestion watchers/endpoints referenced here are legacy. Use `docs/INGEST.md` + CLI for current ingest, and `docs/DIAGRAMS.md` for up-to-date C4 diagrams.
