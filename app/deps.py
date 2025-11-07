from __future__ import annotations
from typing import Any, Iterator
from fastapi import Request

# Minimal dummy som uppfyller de metoder som routrarna använder
class _DummyAgentRepository:
    def get_last_heartbeat(self) -> dict[str, Any] | None:
        return {"status": "unknown"}
    def fetch_top_interesting(self, limit: int = 20) -> list[dict[str, Any]]:
        return []
    def interesting_summary(self) -> dict[str, Any]:
        return {"items": 0}

def get_agent_repository(request: Request) -> Any:
    """
    FastAPI dependency: hämta repository från app.state (primärt),
    fall tillbaka till app.main.app.state, annars dummy.
    """
    repo = getattr(getattr(request, "app", None).state, "agent_repository", None)
    if repo is not None:
        return repo
    try:
        from app import main as main_module  # late import för att undvika cykler
        repo = getattr(getattr(main_module, "app", None).state, "agent_repository", None)
        if repo is not None:
            return repo
    except Exception:
        pass
    return _DummyAgentRepository()

def get_db() -> Iterator[Any]:
    """
    FastAPI dependency: yield en DB-session om main.SessionLocal finns,
    annars yield None i smoke/CI utan PG-koppling.
    """
    try:
        from app import main as main_module  # late import
        SessionLocal = getattr(main_module, "SessionLocal", None)
        if SessionLocal is None:
            yield None
            return
        db = SessionLocal()
        try:
            yield db
        finally:
            close = getattr(db, "close", None)
            if callable(close):
                close()
    except Exception:
        yield None
