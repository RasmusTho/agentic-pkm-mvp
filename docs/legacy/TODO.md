State: Legacy (archived).
> **DEPRECATED (WS)** This document reflects a previous iteration (FastAPI/SQLAlchemy/LangGraph integrated). It is kept for reference. The WS overview is in docs/legacy/OVERVIEW_WS.md and policies in data/context/*.yaml.

# TODO Backlog

- **Restore ingestion watcher** – previously referenced file-system watcher pipeline (`app/ingest/watcher.py`) is deprecated; the planned v5.x watcher/agent track (v5.1–v5.4) supersedes this with a new Vault Watcher path that reuses CLI/service entrypoints (see ROADMAP/STATUS/HUMAN-FLOWS).
- **Implement promotion endpoints** – `/ingest/pending` and `/ingest/review` are referenced in docs but not implemented; design and add these to close the provisional → reviewed loop.
- **Seed reference data set** – provide a lightweight ingest script or fixture so the background agent has sample objects to work with during development.
A
