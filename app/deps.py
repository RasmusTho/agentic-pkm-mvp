from __future__ import annotations
import logging
from typing import Any, Iterator
from fastapi import Request

logger = logging.getLogger(__name__)

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
        # Intentional swallow: fall through to the dummy repository so the
        # route still answers — but a silent dummy hides real wiring failures,
        # so log the cause (#3894).
        logger.warning(
            "Falling back to dummy agent repository after lookup failure", exc_info=True
        )
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
        # Intentional swallow: smoke/CI runs without Postgres get a None
        # session — but in a wired environment this hides a real DB failure,
        # so log it (#3894).
        logger.warning("DB session dependency failed; yielding None", exc_info=True)
        yield None
