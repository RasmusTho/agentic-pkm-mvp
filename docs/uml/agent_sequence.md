State: Legacy (archived).
# Agent Supervisor Sequence

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

## Updated Observations
- **Supervisor loop requires data**: utan seedade objekt i Postgres blir `run_agent.py` kortlivad och restarts loggas var 30:e sekund.
- **Loggrotation saknas**: `/tmp/agent_app.log` växer obegränsat; sätt upp `logrotate` eller container-volymer.
- **API-nyckel tom**: `.env` har `API_KEY=`; produktion måste sätta nyckel innan `/ingest` och `/search` exponeras.
- **Legacy watchfolder**: filesystem-droppar gör inget; ersätt med nytt ingest-trigger-script eller ta bort referenser.
- **Alerting**: övervaka `"Agent exited with code"` och migreringsfel för att fånga trasiga releaser.
