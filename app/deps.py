# Lättviktiga shims för att undvika importfel i tester som bara behöver att modulen finns.
from typing import Any

class _DummyAgentRepository:
    def __init__(self) -> None:
        self.ok = True

def get_agent_repository() -> _DummyAgentRepository:
    return _DummyAgentRepository()

def get_settings() -> Any:
    try:
        from .settings import settings  # re-export från app/_legacy eller fallback
        return settings
    except Exception:
        class _S:  # minimal fallback
            DEBUG = False
            DATABASE_URL = None
        return _S()
