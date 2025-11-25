from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple
from uuid import UUID

from app.reasoning.prompts import SYSTEM_PROMPT, build_user_prompt
from app.reasoning.schema import ReasoningInput, ReasoningOutput, ReasoningValidationError, validate_output
from app.reasoning.models import ReasoningMode, ReasoningRun
from app.services.llm import call_llm
from app.stores import get_object_store

_FIXTURE_PATH = Path("data") / "golden" / "reasoning_samples.jsonl"


class BaseReasoner:
    def reason(self, reasoning_input: ReasoningInput) -> ReasoningOutput:  # pragma: no cover - interface
        raise NotImplementedError


class MockReasoner(BaseReasoner):
    def __init__(self) -> None:
        self._fixtures = self._load_fixtures()

    def _load_fixtures(self) -> Dict[str, ReasoningOutput]:
        outputs: Dict[str, ReasoningOutput] = {}
        if not _FIXTURE_PATH.exists():
            return outputs
        with _FIXTURE_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                text = data.get("text", "")
                payload = {
                    "claims": data.get("claims") or [],
                    "evidence": data.get("evidence") or [],
                    "inferences": data.get("inferences") or [],
                }
                outputs[text] = ReasoningOutput.model_validate(payload)
        return outputs

    def reason(self, reasoning_input: ReasoningInput) -> ReasoningOutput:
        return self._fixtures.get(reasoning_input.text, ReasoningOutput())


class OllamaReasoner(BaseReasoner):
    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or os.getenv("REASONING_MODEL", "llama3.1:8b")

    def reason(self, reasoning_input: ReasoningInput) -> ReasoningOutput:
        prompt = build_user_prompt(reasoning_input.text, [rel.model_dump() for rel in reasoning_input.relations])
        metadata = reasoning_input.metadata if isinstance(reasoning_input.metadata, dict) else {}
        trace_id = metadata.get("trace_id")
        agent = metadata.get("agent") or "reasoning"
        kind = metadata.get("kind") or metadata.get("reasoning_kind") or "reasoning.claims"

        response = call_llm(
            "reasoning",
            {
                "system": SYSTEM_PROMPT,
                "user": prompt,
            },
            agent=agent,
            kind=kind,
            trace_id=trace_id,
        )
        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:  # pragma: no cover - network path not run in CI
            raise ReasoningValidationError("reasoning output was not JSON") from exc
        return validate_output(payload)


def get_reasoner() -> BaseReasoner:
    backend = os.getenv("REASONING_PROVIDER", "").strip().lower()
    llm_provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    ci = os.getenv("CI", "") == "1"

    if backend in {"mock", "golden"} or (ci and backend == ""):
        return MockReasoner()

    if backend == "":
        backend = "llm"

    if backend in {"llm", "ollama"}:
        if llm_provider == "mock":
            return MockReasoner()
        return OllamaReasoner()

    return MockReasoner()


def _load_object_text(object_id: str) -> Tuple[str, dict]:
    store = get_object_store()
    try:
        obj = store.get(UUID(str(object_id)))
    except Exception:
        obj = None
    payload = obj.get("payload") if obj else {}
    text = ""
    if isinstance(payload, dict):
        text = payload.get("text") or payload.get("content") or ""
    return text, payload if isinstance(payload, dict) else {}


def _reasoning_backend() -> str:
    backend = os.getenv("REASONING_PROVIDER", "").strip().lower()
    ci = os.getenv("CI", "") == "1"
    if backend in {"mock", "golden"} or (ci and backend == ""):
        return "mock"
    if backend == "":
        return "llm"
    return backend


def _simple_preview(text: str, limit: int = 120) -> str:
    text = text or ""
    return text[:limit] + ("..." if len(text) > limit else "")


def run_reasoning(
    mode: ReasoningMode,
    object_ids: List[str],
    trace_id: str | None = None,
    *,
    question: str | None = None,
    agent: str | None = None,
    kind: str | None = None,
) -> ReasoningRun:
    agent_name = agent or "reasoning"
    kind_name = kind or f"reasoning.{mode.value}"
    if mode == ReasoningMode.CLAIMS:
        if not object_ids:
            return ReasoningRun(
                mode=mode,
                trace_id=trace_id,
                object_uuids=[],
                status="failed",
                error="no object ids provided",
            )
        object_id = object_ids[0]
        text, metadata = _load_object_text(object_id)
        if not text:
            return ReasoningRun(
                mode=mode,
                trace_id=trace_id,
                object_uuids=[object_id],
                status="failed",
                error="object missing or has no text",
                result={"claims": [], "evidence": [], "inferences": []},
            )
        reasoning_input = ReasoningInput(
            object_uuid=str(object_id),
            text=text,
            metadata={**metadata, "trace_id": trace_id, "agent": agent_name, "kind": kind_name},
            relations=[],
        )
        try:
            output = get_reasoner().reason(reasoning_input)
        except Exception as exc:  # pragma: no cover - defensive
            return ReasoningRun(
                mode=mode,
                trace_id=trace_id,
                object_uuids=[object_id],
                status="failed",
                error=str(exc),
                result={"claims": [], "evidence": [], "inferences": []},
        )
        result = output.model_dump()
        has_content = bool(output.claims or output.evidence)
        status_val = "ok" if has_content else "failed"
        err_val = None if has_content else "no claims or evidence produced"
        return ReasoningRun(
            mode=mode,
            trace_id=trace_id,
            object_uuids=[object_id],
            result=result,
            status=status_val,
            error=err_val,
        )
    if mode == ReasoningMode.REVIEW:
        if not object_ids:
            return ReasoningRun(mode=mode, trace_id=trace_id, object_uuids=[], status="failed", error="no object ids provided")
        object_id = object_ids[0]
        text, _ = _load_object_text(object_id)
        if not text:
            return ReasoningRun(
                mode=mode,
                trace_id=trace_id,
                object_uuids=[object_id],
                status="failed",
                error="object missing or has no text",
                result={"summary": "", "issues": [], "suggestions": []},
            )
        backend = _reasoning_backend()
        if backend == "mock":
            summary = f"Summary: {_simple_preview(text, 90)}"
            issues = ["needs review for clarity"]
            suggestions = ["Clarify objectives", "Add sources"]
            result = {"summary": summary, "issues": issues, "suggestions": suggestions}
            return ReasoningRun(mode=mode, trace_id=trace_id, object_uuids=[object_id], result=result, status="ok")
        prompt = f"NOTE:\n{text}\n\nReturn JSON with summary, issues (list), suggestions (list)."
        try:
            raw = call_llm(
                "reasoning",
                {"system": "You are a reviewer that summarizes and critiques notes. Respond with JSON.", "user": prompt},
                agent=agent_name,
                kind=kind_name,
                trace_id=trace_id,
            )
            data = json.loads(raw)
        except Exception as exc:
            return ReasoningRun(
                mode=mode,
                trace_id=trace_id,
                object_uuids=[object_id],
                status="failed",
                error=str(exc),
                result={"summary": "", "issues": [], "suggestions": []},
            )
        summary = str(data.get("summary") or "").strip()
        issues = data.get("issues") or []
        suggestions = data.get("suggestions") or []
        ok = bool(summary or issues or suggestions)
        return ReasoningRun(
            mode=mode,
            trace_id=trace_id,
            object_uuids=[object_id],
            result={"summary": summary, "issues": issues, "suggestions": suggestions},
            status="ok" if ok else "failed",
            error=None if ok else "empty review result",
        )
    if mode == ReasoningMode.RANKING:
        texts: List[Tuple[str, str]] = []
        for oid in object_ids:
            text, _ = _load_object_text(oid)
            if text:
                texts.append((oid, text))
        if not texts:
            return ReasoningRun(
                mode=mode,
                trace_id=trace_id,
                object_uuids=list(object_ids),
                status="failed",
                error="no candidate texts found",
                result={"ranking": []},
            )
        backend = _reasoning_backend()
        if backend == "mock":
            ranking = []
            for idx, (oid, text) in enumerate(texts):
                score = max(0.0, 1.0 - 0.05 * idx)
                ranking.append({"object_uuid": oid, "score": score, "reason": _simple_preview(text, 80)})
            status_val = "ok" if any((entry.get("reason") or "").strip() for entry in ranking) else "failed"
            error_val = None if status_val == "ok" else "ranking has no reasons"
            return ReasoningRun(
                mode=mode,
                trace_id=trace_id,
                object_uuids=list(object_ids),
                result={"ranking": ranking},
                status=status_val,
                error=error_val,
            )
        prompt_lines = ["You rank candidate notes for the given question. Return JSON {\"ranking\": [{\"object_uuid\":\"...\",\"score\":0-1,\"reason\":\"...\"}]}."]
        if question:
            prompt_lines.append(f"Question: {question}")
        prompt_lines.append("Candidates:")
        for oid, text in texts:
            prompt_lines.append(f"- {oid}: {_simple_preview(text, 180)}")
        prompt = "\n".join(prompt_lines)
        try:
            raw = call_llm(
                "reasoning",
                {"system": "You are a ranking agent. Respond with JSON ranking.", "user": prompt},
                agent=agent_name,
                kind=kind_name,
                trace_id=trace_id,
            )
            data = json.loads(raw)
        except Exception as exc:
            return ReasoningRun(
                mode=mode,
                trace_id=trace_id,
                object_uuids=list(object_ids),
                status="failed",
                error=str(exc),
                result={"ranking": []},
            )
        ranking = data.get("ranking") or []
        ok = bool(ranking) and any((entry.get("reason") or "").strip() for entry in ranking)
        return ReasoningRun(
            mode=mode,
            trace_id=trace_id,
            object_uuids=list(object_ids),
            result={"ranking": ranking},
            status="ok" if ok else "failed",
            error=None if ok else "ranking has no reasons" if ranking else "no ranking produced",
        )
    return ReasoningRun(
        mode=mode,
        trace_id=trace_id,
        object_uuids=list(object_ids),
        status="failed",
        error=f"mode {mode.value} not implemented",
    )


def run_reasoning_claims_for_object(object_id: str, trace_id: str | None = None) -> ReasoningOutput:
    run = run_reasoning(ReasoningMode.CLAIMS, [object_id], trace_id=trace_id)
    if isinstance(run.result, dict):
        try:
            return ReasoningOutput.model_validate(run.result)
        except Exception:
            return ReasoningOutput()
    return ReasoningOutput()


__all__ = ["get_reasoner", "MockReasoner", "OllamaReasoner", "run_reasoning", "ReasoningMode", "ReasoningRun", "run_reasoning_claims_for_object"]
