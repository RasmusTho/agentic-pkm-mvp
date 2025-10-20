from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from app.agent.repository import AgentRepository
from app.agent.service import AgentService
from app.config.agent import AgentConfigManager
from app.db import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_agent_repository(request: Request) -> AgentRepository:
    repo = getattr(request.app.state, "agent_repository", None)
    if repo is None:
        raise RuntimeError("Agent repository is not initialized.")
    return repo


def get_agent_service(request: Request) -> AgentService:
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise RuntimeError("Agent service is not initialized.")
    return service


def get_agent_config_manager(request: Request) -> AgentConfigManager:
    manager = getattr(request.app.state, "agent_config_manager", None)
    if manager is None:
        raise RuntimeError("Agent config manager is not initialized.")
    return manager
