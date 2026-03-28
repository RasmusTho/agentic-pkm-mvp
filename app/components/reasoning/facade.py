"""ReasoningFacade — single entry point for all LLM reasoning calls.

Every future LangGraph agent routes reasoning and tool calls through this
facade.  It delegates to the existing ``LLMRouter`` / ``ChatClient`` pipeline
so that routing rules, provider fallback, and model selection remain in one
place.  The facade adds:

* Consistent telemetry (trace-id, latency, token estimate) as structured
  log-dicts that fitness gates can consume downstream.
* A thin typed API (``chat``, ``structured``, ``tool_use``) that hides
  the pack/name ceremony from callers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Sequence
from uuid import uuid4

from app.components.llm.fabric import ChatClient
from app.components.llm.router import LLMRouter, LLMTaskIntent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolResult:
    """Minimal container for a tool-use LLM response."""

    tool_name: str
    arguments: dict[str, Any]
    raw: str


@dataclass
class TelemetryRecord:
    """Structured metrics for a single LLM call."""

    trace_id: str
    method: str
    task_kind: str
    model: str
    provider: str
    latency_ms: float
    char_count_in: int
    char_count_out: int
    error: str | None = None


@dataclass
class ReasoningFacade:
    """Wraps the LLM router with a clean per-method API and telemetry."""

    router: LLMRouter
    _telemetry: list[TelemetryRecord] = field(default_factory=list, repr=False)

    # -- public helpers -------------------------------------------------------

    @property
    def telemetry(self) -> Sequence[TelemetryRecord]:
        """Read-only view of captured telemetry records."""
        return list(self._telemetry)

    # -- public API -----------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        task_kind: str = "chat",
        trace_id: str | None = None,
    ) -> str:
        """Plain chat completion — returns the assistant text."""
        trace_id = trace_id or uuid4().hex
        intent = LLMTaskIntent(task_kind=task_kind)
        client = self._resolve_client(intent)
        pack = self._messages_to_pack(messages)

        t0 = time.monotonic()
        error: str | None = None
        result = ""
        try:
            result = client.chat(
                "reasoning.chat",
                pack,
                agent="reasoning_facade",
                kind=task_kind,
                trace_id=trace_id,
            )
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            self._record(
                trace_id=trace_id,
                method="chat",
                task_kind=task_kind,
                client=client,
                t0=t0,
                pack=pack,
                result=result,
                error=error,
            )
        return result

    def structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        task_kind: str = "decide",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Chat completion that requests JSON conforming to *schema*.

        The facade injects the schema description into the system prompt so
        that any provider can attempt structured output.  Parsing is best-
        effort (``json.loads``); callers should validate.
        """
        import json

        trace_id = trace_id or uuid4().hex
        intent = LLMTaskIntent(task_kind=task_kind, json_schema_required=True)
        client = self._resolve_client(intent)

        schema_instruction = (
            "Respond with valid JSON matching this schema:\n"
            f"```json\n{json.dumps(schema, indent=2)}\n```"
        )
        pack = self._messages_to_pack(messages, extra_system=schema_instruction)

        t0 = time.monotonic()
        error: str | None = None
        raw = ""
        try:
            raw = client.chat(
                "reasoning.structured",
                pack,
                agent="reasoning_facade",
                kind=task_kind,
                trace_id=trace_id,
            )
            return json.loads(raw or "{}")  # type: ignore[no-any-return]
        except json.JSONDecodeError as exc:
            error = f"json_parse: {exc}"
            raise
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            self._record(
                trace_id=trace_id,
                method="structured",
                task_kind=task_kind,
                client=client,
                t0=t0,
                pack=pack,
                result=raw,
                error=error,
            )

    def tool_use(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        *,
        task_kind: str = "tool",
        trace_id: str | None = None,
    ) -> ToolResult:
        """Chat completion with tool definitions.

        Since the underlying ``call_llm`` pipeline is text-based, we inject
        tool descriptions into the system prompt and parse a JSON tool-call
        from the response.
        """
        import json

        trace_id = trace_id or uuid4().hex
        intent = LLMTaskIntent(task_kind=task_kind, json_schema_required=True)
        client = self._resolve_client(intent)

        tool_descriptions = json.dumps(tools, indent=2)
        tool_instruction = (
            "You have these tools available:\n"
            f"```json\n{tool_descriptions}\n```\n"
            'To call a tool respond with JSON: {"tool": "<name>", "arguments": {...}}'
        )
        pack = self._messages_to_pack(messages, extra_system=tool_instruction)

        t0 = time.monotonic()
        error: str | None = None
        raw = ""
        try:
            raw = client.chat(
                "reasoning.tool_use",
                pack,
                agent="reasoning_facade",
                kind=task_kind,
                trace_id=trace_id,
            )
            parsed = json.loads(raw or "{}")
            return ToolResult(
                tool_name=parsed.get("tool", ""),
                arguments=parsed.get("arguments", {}),
                raw=raw,
            )
        except json.JSONDecodeError as exc:
            error = f"json_parse: {exc}"
            raise
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            self._record(
                trace_id=trace_id,
                method="tool_use",
                task_kind=task_kind,
                client=client,
                t0=t0,
                pack=pack,
                result=raw,
                error=error,
            )

    # -- internals ------------------------------------------------------------

    def _resolve_client(self, intent: LLMTaskIntent) -> ChatClient:
        route = self.router.route(intent)
        return ChatClient(route=route)

    @staticmethod
    def _messages_to_pack(
        messages: list[dict[str, str]],
        extra_system: str | None = None,
    ) -> dict[str, str]:
        """Convert a messages list to the ``{system, user}`` pack format."""
        system_parts: list[str] = []
        user_parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            else:
                user_parts.append(content)
        if extra_system:
            system_parts.append(extra_system)
        return {
            "system": "\n".join(system_parts),
            "user": "\n".join(user_parts),
        }

    def _record(
        self,
        *,
        trace_id: str,
        method: str,
        task_kind: str,
        client: ChatClient,
        t0: float,
        pack: dict[str, str],
        result: str,
        error: str | None,
    ) -> None:
        latency_ms = (time.monotonic() - t0) * 1000
        char_in = sum(len(v) for v in pack.values())
        char_out = len(result) if result else 0
        record = TelemetryRecord(
            trace_id=trace_id,
            method=method,
            task_kind=task_kind,
            model=client.route.model,
            provider=client.route.provider,
            latency_ms=round(latency_ms, 2),
            char_count_in=char_in,
            char_count_out=char_out,
            error=error,
        )
        self._telemetry.append(record)
        logger.debug(
            "reasoning.%s trace=%s model=%s/%s latency=%.1fms chars_in=%d chars_out=%d%s",
            method,
            trace_id[:8],
            record.provider,
            record.model,
            latency_ms,
            char_in,
            char_out,
            f" error={error}" if error else "",
        )


__all__ = ["ReasoningFacade", "TelemetryRecord", "ToolResult"]
