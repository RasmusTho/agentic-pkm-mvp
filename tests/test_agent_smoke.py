from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
import app.legacy_http as main_module
from app.agents.qa import agent as qa_agent
from app.retrieval.hybrid import get_store
from tests.stub_repositories import MemoryAgentRepository


def test_agent_endpoints(monkeypatch) -> None:
    repo = MemoryAgentRepository()
    sqlite_engine = create_engine("sqlite:///:memory:", future=True)
    session_factory = sessionmaker(bind=sqlite_engine, autoflush=False, autocommit=False)

    db_module.Base.metadata.create_all(sqlite_engine)
    monkeypatch.setattr(db_module, "engine", sqlite_engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "engine", sqlite_engine)

    class StubService:
        def __init__(self, repository, config_manager):
            self.repository = repository

        async def start(self) -> None:  # pragma: no cover - executed via TestClient lifespan
            self.repository.record_heartbeat("background-agent", None, "idle")
            object_id = uuid4()
            self.repository.interesting_items[object_id] = {
                "object_id": object_id,
                "run_id": uuid4(),
                "novelty": 0.4,
                "anomaly": 0.3,
                "uncertainty": 0.2,
                "value": 0.9,
                "score": 0.7,
                "reason": "Smoke item",
                "payload": {"title": "Smoke item"},
                "created_at": datetime.now(tz=timezone.utc),
            }

        async def stop(self) -> None:
            return

    def fake_repo(dsn: str) -> MemoryAgentRepository:
        return repo

    def fake_service(repository, config_manager) -> StubService:
        return StubService(repository, config_manager)

    monkeypatch.setattr(main_module, "PostgresAgentRepository", fake_repo)
    monkeypatch.setattr(main_module, "AgentService", fake_service)
    monkeypatch.setattr(main_module, "SessionLocal", session_factory, raising=False)

    client = TestClient(main_module.app)
    with client:
        resp = client.get("/agent/health")
        assert resp.status_code == 200
        assert resp.json()["heartbeat"]["status"] == "idle"

        resp = client.get("/interesting")
        data = resp.json()
        assert resp.status_code == 200
        assert data["items"]

        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "Interesting Items" in resp.text


def test_qa_agent_answer(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    store = get_store()
    store.set_documents(
        [
            {"doc_id": "doc-1", "text": "Alpha dokument innehåller fakta.", "source_ref": "alpha.md"},
            {"doc_id": "doc-2", "text": "Beta dokument är orelaterat."},
        ]
    )

    def fake_call(messages, trace_id, max_tokens):
        return "Sammanfattning av alpha [#1]"

    monkeypatch.setattr(qa_agent, "_call_llm", fake_call)

    result = qa_agent.answer("Vad säger alpha dokumentet?", trace_id="T-QA")

    assert result["sources"]
    assert "[#1]" in result["answer"]
