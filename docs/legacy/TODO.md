> **DEPRECATED (WS)** This document reflects a previous iteration (FastAPI/SQLAlchemy/LangGraph integrated). It is kept for reference. The WS overview is in docs/OVERVIEW_WS.md and policies in data/context/*.yaml.

# TODO Backlog

- **Restore ingestion watcher** – either rebuild the file-system watcher pipeline (`app/ingest/watcher.py`) or fully document an alternative ingest path so filesystem drops are no longer referenced as active.
- **Implement promotion endpoints** – `/ingest/pending` and `/ingest/review` are referenced in docs but not implemented; design and add these to close the provisional → reviewed loop.
- **Seed reference data set** – provide a lightweight ingest script or fixture so the background agent has sample objects to work with during development.
A