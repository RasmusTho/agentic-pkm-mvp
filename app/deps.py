"""
Compatibility shim for dependencies.

- Primary: re-export legacy implementations so `app/_legacy/main.py` stays loadable.
- Fallback: provide safe dummies when legacy deps cannot be imported (e.g., tests).
"""
from __future__ import annotations

from typing import Any, Iterator

try:
    # Prefer the real legacy deps (keep legacy FastAPI wiring working)
    from ._legacy.deps import get_agent_repository, get_db  # type: ignore[attr-defined]
except Exception:
    # Fallbacks for test/shim contexts without a DB
    class _DummyAgentRepository:
        def record_heartbeat(self, *args, **kwargs) -> None:
            pass

        def interesting(self) -> list[dict[str, Any]]:
            return []

    def get_agent_repository() -> _DummyAgentRepository:  # type: ignore[override]
        return _DummyAgentRepository()

    def get_db() -> Iterator[Any]:  # FastAPI-style dependency signature
        yield None

__all__ = ["get_agent_repository", "get_db"]
