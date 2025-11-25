from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

from app.reasoning.prompts import SYSTEM_PROMPT, build_user_prompt
from app.reasoning.schema import ReasoningInput, ReasoningOutput, ReasoningValidationError, validate_output
from app.services.llm import call_llm

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
        trace_id = None
        if isinstance(reasoning_input.metadata, dict):
            trace_id = reasoning_input.metadata.get("trace_id")

        response = call_llm(
            "reasoning",
            {
                "system": SYSTEM_PROMPT,
                "user": prompt,
            },
            agent="reasoning",
            kind="reasoning.single_note",
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


__all__ = ["get_reasoner", "MockReasoner", "OllamaReasoner"]
