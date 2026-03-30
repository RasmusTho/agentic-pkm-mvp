"""ReasoningFacade — single entry point for all LLM reasoning calls.

Every future LangGraph agent routes reasoning and tool calls through this
facade.  It delegates to the existing ``LLMRouter`` / ``ChatClient`` pipeline
so that routing rules, provider fallback, and model selection remain in one
place.  The facade adds:

* Consistent telemetry (trace-id, latency, token estimate) as structured
  log-dicts that fitness gates can consume downstream.
* A thin typed API (``chat``, ``structured``, ``tool_use``, ``reason``) that
  hides the pack/name ceremony from callers.
* ``ReasoningTaskKind`` enum so all agents declare intent uniformly.
* Audit logging consistent with ``app/agents/base/audit.py``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence
from uuid import uuid4

from pydantic import BaseModel, Field

from app.components.llm.fabric import ChatClient
from app.components.llm.router import LLMRouter, LLMTaskIntent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task-kind taxonomy
# ---------------------------------------------------------------------------


class ReasoningTaskKind(str, Enum):
    """Canonical task kinds for all LangGraph agent reasoning calls.

    Each kind maps to a specific ``LLMTaskIntent.task_kind`` string so that
    the router can apply per-task model/provider policies.
    """

    CLAIMS = "claims"
    REVIEW = "review"
    RANKING = "ranking"
    PLANNING = "planning"
    ASK_ANSWER = "ask_answer"
    DECIDE = "decide"
    CLASSIFY = "classify"

    @property
    def llm_task_kind(self) -> str:
        """Return the string passed to ``LLMTaskIntent`` for routing."""
        # decide and plan already used by existing routing policies
        if self == ReasoningTaskKind.DECIDE:
            return "decide"
        if self == ReasoningTaskKind.PLANNING:
            return "plan"
        if self == ReasoningTaskKind.CLASSIFY:
            return "classify"
        # reasoning/*  tasks route through the default_reasoning policy
        return "reasoning"


# ---------------------------------------------------------------------------
# Structured output types
# ---------------------------------------------------------------------------


class ClaimOutput(BaseModel):
    id: str
    object_uuid: str = ""
    text: str
    modality: str = "assertion"
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)


class ReasoningClaimsResult(BaseModel):
    claims: list[ClaimOutput] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    inferences: list[dict[str, Any]] = Field(default_factory=list)


class ReviewResult(BaseModel):
    summary: str = ""
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class RankingEntry(BaseModel):
    object_uuid: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class RankingResult(BaseModel):
    ranking: list[RankingEntry] = Field(default_factory=list)


class PlanningResult(BaseModel):
    plan: str = ""
    steps: list[str] = Field(default_factory=list)


class AskAnswerResult(BaseModel):
    answer: str = ""


class DecideResult(BaseModel):
    decision: str = ""
    reason: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.7)


class ClassifyResult(BaseModel):
    type: str = "note"
    tags: list[str] = Field(default_factory=list)
    trust: str = "provisional"
    confidence: float = Field(ge=0.0, le=1.0, default=0.66)


# Union type for the reason() return value
ReasoningResult = (
    ReasoningClaimsResult
    | ReviewResult
    | RankingResult
    | PlanningResult
    | AskAnswerResult
    | DecideResult
    | ClassifyResult
)


# ---------------------------------------------------------------------------
# Telemetry / tool-use helpers (unchanged from original)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ReasoningFacade
# ---------------------------------------------------------------------------


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

    # -- unified reason() API -------------------------------------------------

    def reason(
        self,
        task_kind: ReasoningTaskKind,
        input: dict[str, Any],  # noqa: A002  (shadow builtin intentional)
        trace_id: str | None = None,
    ) -> ReasoningResult:
        """Route a reasoning task through the unified facade.

        Parameters
        ----------
        task_kind:
            One of the ``ReasoningTaskKind`` enum values.  Determines both the
            LLM routing policy and the structured output type.
        input:
            Task-specific payload.  Keys depend on ``task_kind``:
            - CLAIMS / REVIEW / RANKING: ``text`` (str), optional ``object_uuid``
            - PLANNING / DECIDE: ``system`` (str), ``user`` (str)
            - ASK_ANSWER: ``question`` (str), optional ``context`` (str)
            - CLASSIFY: ``text`` (str), optional ``object_uuid``
        trace_id:
            Optional distributed trace identifier.
        """
        trace_id = trace_id or uuid4().hex

        if task_kind == ReasoningTaskKind.CLAIMS:
            return self._reason_claims(input, trace_id)
        if task_kind == ReasoningTaskKind.REVIEW:
            return self._reason_review(input, trace_id)
        if task_kind == ReasoningTaskKind.RANKING:
            return self._reason_ranking(input, trace_id)
        if task_kind == ReasoningTaskKind.PLANNING:
            return self._reason_planning(input, trace_id)
        if task_kind == ReasoningTaskKind.ASK_ANSWER:
            return self._reason_ask_answer(input, trace_id)
        if task_kind == ReasoningTaskKind.DECIDE:
            return self._reason_decide(input, trace_id)
        if task_kind == ReasoningTaskKind.CLASSIFY:
            return self._reason_classify(input, trace_id)
        # Should be unreachable with the enum, but safe fallback
        raise ValueError(f"Unknown ReasoningTaskKind: {task_kind}")

    # -- public low-level API (chat / structured / tool_use) ------------------

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

    # -- reason() sub-handlers ------------------------------------------------

    def _reason_claims(self, input: dict[str, Any], trace_id: str) -> ReasoningClaimsResult:
        from app.reasoning.prompts import SYSTEM_PROMPT, build_user_prompt

        text = input.get("text") or input.get("content") or ""
        relations = input.get("relations") or []
        object_uuid = input.get("object_uuid") or ""
        prompt = build_user_prompt(text, [r if isinstance(r, dict) else r.model_dump() for r in relations])
        pack = {"system": SYSTEM_PROMPT, "user": prompt}
        raw = self._call_pack(pack, task_kind=ReasoningTaskKind.CLAIMS, trace_id=trace_id, agent="reasoning_facade", kind="reasoning.claims")
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
        self._audit(trace_id=trace_id, agent="reasoning_facade", action="reason.claims", object_id=object_uuid or None, details={"text_len": len(text)})
        return ReasoningClaimsResult.model_validate(data)

    def _reason_review(self, input: dict[str, Any], trace_id: str) -> ReviewResult:
        text = input.get("text") or input.get("content") or ""
        object_uuid = input.get("object_uuid") or ""
        owner_agent = str(input.get("_agent") or "reasoning_facade")
        prompt = f"NOTE:\n{text}\n\nReturn JSON with summary, issues (list), suggestions (list)."
        pack = {"system": "You are a reviewer that summarizes and critiques notes. Respond with JSON.", "user": prompt}
        raw = self._call_pack(pack, task_kind=ReasoningTaskKind.REVIEW, trace_id=trace_id, agent=owner_agent, kind="reasoning.review")
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
        self._audit(trace_id=trace_id, agent=owner_agent, action="reason.review", object_id=object_uuid or None, details={"text_len": len(text)})
        return ReviewResult.model_validate(data)

    def _reason_ranking(self, input: dict[str, Any], trace_id: str) -> RankingResult:
        candidates = input.get("candidates") or []
        question = input.get("question") or ""
        prompt_lines = ["You rank candidate notes for the given question. Return JSON {\"ranking\": [{\"object_uuid\":\"...\",\"score\":0-1,\"reason\":\"...\"}]}."]
        if question:
            prompt_lines.append(f"Question: {question}")
        prompt_lines.append("Candidates:")
        for c in candidates:
            oid = c.get("object_uuid") or c.get("id") or ""
            text = (c.get("text") or "")[:180]
            prompt_lines.append(f"- {oid}: {text}")
        pack = {"system": "You are a ranking agent. Respond with JSON ranking.", "user": "\n".join(prompt_lines)}
        raw = self._call_pack(pack, task_kind=ReasoningTaskKind.RANKING, trace_id=trace_id, agent="reasoning_facade", kind="reasoning.ranking")
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {}
        self._audit(trace_id=trace_id, agent="reasoning_facade", action="reason.ranking", object_id=None, details={"candidate_count": len(candidates)})
        return RankingResult.model_validate(data)

    def _reason_planning(self, input: dict[str, Any], trace_id: str) -> PlanningResult:
        system = input.get("system") or "You are a planning assistant. Return JSON with plan (str) and steps (list of str)."
        user = input.get("user") or input.get("text") or ""
        pack = {"system": system, "user": user}
        raw = self._call_pack(pack, task_kind=ReasoningTaskKind.PLANNING, trace_id=trace_id, agent="reasoning_facade", kind="reasoning.planning")
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {"plan": raw or "", "steps": []}
        self._audit(trace_id=trace_id, agent="reasoning_facade", action="reason.planning", object_id=None, details={})
        return PlanningResult.model_validate(data)

    def _reason_ask_answer(self, input: dict[str, Any], trace_id: str) -> AskAnswerResult:
        question = input.get("question") or input.get("user") or ""
        context = input.get("context") or ""
        system = input.get("system") or "You answer questions using only the provided sources."
        user_lines = [f"Question: {question}"]
        if context:
            user_lines += ["", "Sources:", context]
        pack = {"system": system, "user": "\n".join(user_lines)}
        raw = self._call_pack(pack, task_kind=ReasoningTaskKind.ASK_ANSWER, trace_id=trace_id, agent="reasoning_facade", kind="ask.answer")
        self._audit(trace_id=trace_id, agent="reasoning_facade", action="reason.ask_answer", object_id=None, details={"question_len": len(question)})
        return AskAnswerResult(answer=(raw or "").strip())

    def _reason_decide(self, input: dict[str, Any], trace_id: str) -> DecideResult:
        system = input.get("system") or (
            "You are a decision agent. Return JSON with decision (str), reason (str), confidence (float 0-1)."
        )
        user = input.get("user") or input.get("text") or ""
        pack = {"system": system, "user": user}
        raw = self._call_pack(pack, task_kind=ReasoningTaskKind.DECIDE, trace_id=trace_id, agent="reasoning_facade", kind="agent.decide")
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError:
            data = {"decision": raw or "", "reason": "", "confidence": 0.7}
        self._audit(trace_id=trace_id, agent="reasoning_facade", action="reason.decide", object_id=None, details={})
        return DecideResult.model_validate(data)

    def _reason_classify(self, input: dict[str, Any], trace_id: str) -> ClassifyResult:
        text = input.get("text") or input.get("content") or ""
        object_uuid = input.get("object_uuid") or ""
        pack = {
            "system": (
                "Returnera JSON {type, tags, trust, confidence}. "
                "type∈{note,seed,idea,doc}. trust∈{own,provisional,external,conflict}. "
                "tags=[topic/*]. Svara enbart JSON."
            ),
            "user": text[:4000],
        }
        raw = self._call_pack(pack, task_kind=ReasoningTaskKind.CLASSIFY, trace_id=trace_id, agent="reasoning_facade", kind="classification")
        data = _parse_json_block(raw or "") or {}
        confidence = _as_float(data.get("confidence") if isinstance(data, dict) else None, default=0.66)
        if not data or not isinstance(data, dict) or confidence < 0.7:
            # Heuristic fallback
            data = _heuristic_classify(text)
            confidence = _as_float(data.get("confidence"), default=0.66)
        # Normalize raw dict fields before model_validate so that non-strict
        # LLM payloads (scalar tags, out-of-range confidence, missing fields)
        # do not cause a ValidationError.
        data = _normalize_classify_payload(data)
        self._audit(trace_id=trace_id, agent="reasoning_facade", action="reason.classify", object_id=object_uuid or None, details={"confidence": data.get("confidence", 0.66)})
        return ClassifyResult.model_validate(data)

    # -- internals ------------------------------------------------------------

    def _call_pack(
        self,
        pack: dict[str, str],
        *,
        task_kind: ReasoningTaskKind,
        trace_id: str,
        agent: str,
        kind: str,
    ) -> str:
        intent = LLMTaskIntent(task_kind=task_kind.llm_task_kind)
        client = self._resolve_client(intent)
        t0 = time.monotonic()
        error: str | None = None
        result = ""
        try:
            result = client.chat(
                f"reasoning.{task_kind.value}",
                pack,
                agent=agent,
                kind=kind,
                trace_id=trace_id,
            )
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            self._record(
                trace_id=trace_id,
                method=f"reason.{task_kind.value}",
                task_kind=task_kind.llm_task_kind,
                client=client,
                t0=t0,
                pack=pack,
                result=result,
                error=error,
            )
        return result

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

    @staticmethod
    def _audit(
        *,
        trace_id: str | None,
        agent: str,
        action: str,
        object_id: str | None,
        details: dict[str, Any],
    ) -> None:
        """Best-effort audit log — never raises."""
        try:
            from app.agents.base.audit import audit_log

            audit_log(
                object_id=object_id,
                agent=agent,
                action=action,
                trace_id=trace_id,
                details=details,
            )
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Module-level factory
# ---------------------------------------------------------------------------


def get_reasoning_facade() -> ReasoningFacade:
    """Return a ``ReasoningFacade`` backed by the default ``LLMRouter``."""
    return ReasoningFacade(router=LLMRouter())


# ---------------------------------------------------------------------------
# Private helpers (shared with classifier fallback)
# ---------------------------------------------------------------------------


def _parse_json_block(s: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _as_float(value: Any, default: float = 0.66) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _ensure_labels(value: Any) -> list[str]:
    """Coerce a raw LLM tags/labels value to a list of strings.

    LLMs sometimes return a single string, a comma-separated string, a dict,
    or a list that contains non-string items.  This normaliser handles all of
    those cases so that ``ClassifyResult.model_validate`` never receives an
    unexpected type for the ``tags`` field.
    """
    if value is None:
        return []
    if isinstance(value, str):
        # Handle comma-separated strings like "topic/foo, topic/bar"
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, dict):
        return [str(v) for v in value.values() if v]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    # Fallback: stringify whatever we got
    return [str(value)]


def _normalize_classify_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw classify dict so that ``ClassifyResult.model_validate``
    never fails on common non-strict LLM outputs.

    Handles:
    - ``tags`` as scalar string, dict, or mixed list → always a list[str]
    - ``confidence`` outside [0, 1] or non-numeric → clamped float
    - ``trust`` missing or non-string → defaults to "provisional"
    - ``type`` missing or non-string → defaults to "note"
    """
    normalized: dict[str, Any] = dict(data)
    # tags: always a list of strings
    normalized["tags"] = _ensure_labels(data.get("tags"))
    # confidence: clamp to [0.0, 1.0]
    raw_conf = _as_float(data.get("confidence"), default=0.66)
    normalized["confidence"] = max(0.0, min(1.0, raw_conf))
    # trust: must be a non-empty string
    trust = data.get("trust")
    normalized["trust"] = trust if isinstance(trust, str) and trust.strip() else "provisional"
    # type: must be a non-empty string
    obj_type = data.get("type")
    normalized["type"] = obj_type if isinstance(obj_type, str) and obj_type.strip() else "note"
    return normalized


def _heuristic_classify(text: str) -> dict[str, Any]:
    """Lightweight rule-based classifier fallback — no LLM call."""
    import re as _re

    tags = []
    if "TODO" in text.upper():
        tags.append("topic/todo")
    if "http" in text:
        tags.append("topic/links")
    if _re.search(r"^#\s+", text, _re.M):
        tags.append("topic/has_title")
    return {"type": "note", "trust": "provisional", "tags": sorted(set(tags)), "confidence": 0.55}


__all__ = [
    "ReasoningFacade",
    "ReasoningTaskKind",
    "TelemetryRecord",
    "ToolResult",
    "ReasoningClaimsResult",
    "ReviewResult",
    "RankingResult",
    "PlanningResult",
    "AskAnswerResult",
    "DecideResult",
    "ClassifyResult",
    "get_reasoning_facade",
]
