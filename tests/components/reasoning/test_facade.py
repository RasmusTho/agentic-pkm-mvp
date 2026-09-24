"""Tests for ReasoningFacade — the shared LLM reasoning entry point."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.components.llm.fabric import (
    ChatClient,
    LLMRoute,
    LLMTaskIntent,
    _resolve_product_access_route,
)
from app.components.llm.router import LLMRouter
from app.components.reasoning.facade import ReasoningFacade, TelemetryRecord, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_router(provider: str = "mock", model: str = "test-model") -> LLMRouter:
    router = MagicMock(spec=LLMRouter)
    router.route.return_value = LLMRoute(
        provider=provider,
        model=model,
        mode="chat",
        reason="test",
    )
    return router


def _facade(router: LLMRouter | None = None) -> ReasoningFacade:
    return ReasoningFacade(router=router or _mock_router())


SIMPLE_MESSAGES: list[dict[str, str]] = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello"},
]


def _bound_remote_client(intent: LLMTaskIntent, content: str):
    class _Remote:
        completion_request = None

        def preflight(self, _request):
            pass

        def complete(self, request):
            self.completion_request = request
            return SimpleNamespace(content=content)

    remote = _Remote()
    access_route = _resolve_product_access_route(
        intent,
        LLMRoute(
            provider="openai",
            model="gpt-5.4",
            mode="chat",
            reason="test",
            transport_id="codex_cli_tailscale",
            reasoning_effort="low",
        ),
        allow_catalog_promotion=False,
    )
    client = ChatClient(
        route=LLMRoute.from_model_access_route(
            access_route, mode="chat", reason="test"
        ),
        model_access_route=access_route,
        remote_transport=remote,
    )
    return client, remote


# ---------------------------------------------------------------------------
# chat()
# ---------------------------------------------------------------------------


class TestChat:
    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_routes_through_router(self, mock_get_client: MagicMock) -> None:
        instance = MagicMock()
        instance.route = LLMRoute(
            provider="mock", model="test-model", mode="chat", reason="test"
        )
        mock_get_client.return_value = instance
        instance.chat.return_value = "Hi there"

        facade = _facade()
        result = facade.chat(SIMPLE_MESSAGES, trace_id="t1")

        assert result == "Hi there"
        facade.router.route.assert_called_once()
        mock_get_client.assert_called_once()
        assert mock_get_client.call_args.args[0].task_kind == "chat"
        instance.chat.assert_called_once()

    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_captures_telemetry(self, mock_client_cls: MagicMock) -> None:
        instance = mock_client_cls.return_value
        instance.chat.return_value = "response"

        facade = _facade()
        facade.chat(SIMPLE_MESSAGES, trace_id="trace-abc")

        assert len(facade.telemetry) == 1
        rec = facade.telemetry[0]
        assert isinstance(rec, TelemetryRecord)
        assert rec.trace_id == "trace-abc"
        assert rec.method == "chat"
        assert rec.latency_ms >= 0
        assert rec.char_count_in > 0
        assert rec.char_count_out > 0
        assert rec.error is None

    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_records_error_on_failure(self, mock_client_cls: MagicMock) -> None:
        instance = mock_client_cls.return_value
        instance.chat.side_effect = RuntimeError("boom")

        facade = _facade()
        with pytest.raises(RuntimeError, match="boom"):
            facade.chat(SIMPLE_MESSAGES, trace_id="err-1")

        assert len(facade.telemetry) == 1
        assert facade.telemetry[0].error == "boom"

    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_auto_generates_trace_id(self, mock_client_cls: MagicMock) -> None:
        instance = mock_client_cls.return_value
        instance.chat.return_value = "ok"

        facade = _facade()
        facade.chat(SIMPLE_MESSAGES)

        assert len(facade.telemetry) == 1
        assert facade.telemetry[0].trace_id  # not empty


# ---------------------------------------------------------------------------
# structured()
# ---------------------------------------------------------------------------


class TestStructured:
    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_returns_parsed_dict(self, mock_client_cls: MagicMock) -> None:
        instance = mock_client_cls.return_value
        instance.chat.return_value = json.dumps({"answer": 42})

        facade = _facade()
        result = facade.structured(
            SIMPLE_MESSAGES,
            schema={"type": "object", "properties": {"answer": {"type": "integer"}}},
            trace_id="s1",
        )

        assert result == {"answer": 42}
        assert facade.telemetry[0].method == "structured"

    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_forwards_schema_to_bound_remote_route(
        self, mock_get_client: MagicMock
    ) -> None:
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "integer"}},
            "required": ["answer"],
        }
        client, remote = _bound_remote_client(
            LLMTaskIntent(task_kind="decide", json_schema_required=True),
            '{"answer":42}',
        )
        mock_get_client.return_value = client

        result = _facade().structured(
            SIMPLE_MESSAGES, schema=schema, task_kind="decide", trace_id="s3"
        )

        assert result == {"answer": 42}
        assert remote.completion_request is not None
        assert remote.completion_request.output_schema == schema

    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_raises_on_bad_json(self, mock_client_cls: MagicMock) -> None:
        instance = mock_client_cls.return_value
        instance.chat.return_value = "not json"

        facade = _facade()
        with pytest.raises(json.JSONDecodeError):
            facade.structured(SIMPLE_MESSAGES, schema={}, trace_id="s2")

        assert facade.telemetry[0].error is not None
        assert "json_parse" in facade.telemetry[0].error


# ---------------------------------------------------------------------------
# tool_use()
# ---------------------------------------------------------------------------


class TestToolUse:
    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_returns_tool_result(self, mock_client_cls: MagicMock) -> None:
        instance = mock_client_cls.return_value
        instance.chat.return_value = json.dumps(
            {"tool": "search", "arguments": {"query": "langgraph"}}
        )

        facade = _facade()
        result = facade.tool_use(
            SIMPLE_MESSAGES,
            tools=[{"name": "search", "description": "Search the web"}],
            trace_id="tu1",
        )

        assert isinstance(result, ToolResult)
        assert result.tool_name == "search"
        assert result.arguments == {"query": "langgraph"}
        assert facade.telemetry[0].method == "tool_use"

    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_forwards_tool_call_schema_to_bound_remote_route(
        self, mock_get_client: MagicMock
    ) -> None:
        client, remote = _bound_remote_client(
            LLMTaskIntent(task_kind="tool", json_schema_required=True),
            '{"tool":"search","arguments":{"query":"langgraph"}}',
        )
        mock_get_client.return_value = client
        tools = [
            {"name": "search", "description": "Search the web"},
            {"name": "summarize", "description": "Summarize a page"},
        ]

        result = _facade().tool_use(
            SIMPLE_MESSAGES, tools=tools, task_kind="tool", trace_id="tu3"
        )

        assert result.tool_name == "search"
        assert remote.completion_request is not None
        assert remote.completion_request.output_schema == {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "enum": ["search", "summarize"]},
                "arguments": {"type": "object"},
            },
            "required": ["tool", "arguments"],
            "additionalProperties": False,
        }

    @patch("app.components.reasoning.facade.get_chat_client_for_route")
    def test_raises_on_bad_json(self, mock_client_cls: MagicMock) -> None:
        instance = mock_client_cls.return_value
        instance.chat.return_value = "I don't know how to use tools"

        facade = _facade()
        with pytest.raises(json.JSONDecodeError):
            facade.tool_use(SIMPLE_MESSAGES, tools=[], trace_id="tu2")


# ---------------------------------------------------------------------------
# _messages_to_pack
# ---------------------------------------------------------------------------


class TestMessagesToPack:
    def test_separates_system_and_user(self) -> None:
        pack = ReasoningFacade._messages_to_pack([
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
        ])
        assert pack["system"] == "sys"
        assert pack["user"] == "usr"

    def test_appends_extra_system(self) -> None:
        pack = ReasoningFacade._messages_to_pack(
            [{"role": "system", "content": "base"}],
            extra_system="extra",
        )
        assert "base" in pack["system"]
        assert "extra" in pack["system"]

    def test_defaults_to_user_role(self) -> None:
        pack = ReasoningFacade._messages_to_pack([{"content": "hi"}])
        assert pack["user"] == "hi"
