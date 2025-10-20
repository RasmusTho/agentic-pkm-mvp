from __future__ import annotations

import asyncio
from uuid import uuid4

from app.agent.service import AgentService
from app.config.agent import AgentConfig, AgentConfigManager
from app.plugins.base import ToolContext, ToolResult
from tests.stub_repositories import MemoryAgentRepository


class StubRetriever:
    name = "retriever"

    async def arun(self, ctx: ToolContext, **kwargs) -> ToolResult:
        object_id = uuid4()
        return ToolResult(
            name=self.name,
            output=[
                {
                    "object_id": str(object_id),
                    "score": 0.9,
                    "payload": {"title": "Test object"},
                }
            ],
        )


class StubNote:
    name = "write_note"

    async def arun(self, ctx: ToolContext, **kwargs) -> ToolResult:
        return ToolResult(name=self.name, output={"ok": True})


def test_agent_service_run_once() -> None:
    repo = MemoryAgentRepository()
    manager = AgentConfigManager()
    config = AgentConfig.model_validate(
        {
            "agent_name": "test-agent",
            "plan": {"seed_queries": ["alpha"], "max_actions": 2},
            "plugins": {"enabled": ["retriever", "write_note"]},
            "interestingness": {"score_threshold": 0.0},
        }
    )
    manager.set_config(config)

    def load_tools(names):
        return {"retriever": StubRetriever(), "write_note": StubNote()}

    service = AgentService(repo, manager, plugin_loader=load_tools)
    asyncio.run(service.run_once())

    assert repo.runs  # run persisted
    heartbeat = repo.get_last_heartbeat()
    assert heartbeat is not None
    assert heartbeat["status"] == "idle"
    assert repo.fetch_top_interesting(limit=5)
