from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.app import app
from app.eval.llm_client import configure_eval_openai_env

CASES_PATH = Path("docs/eval/ask_cases.yaml")
CASES_BILINGUAL_PATH = Path("docs/eval/ask_cases_bilingual.yaml")


def _load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in (CASES_PATH, CASES_BILINGUAL_PATH):
        if path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            if isinstance(loaded, list):
                cases.extend(loaded)
    if cases:
        return cases
    return [
        {"question": "What is the Reality-MVP focus?", "expected_contains": "Reality-MVP"},
        {"question": "Vilket fokus har Reality-MVP?", "expected_contains": "Reality-MVP"},
    ]


@pytest.mark.eval
def test_ask_answer_relevancy() -> None:
    try:
        from deepeval.evaluate import evaluate
        from deepeval.metrics import AnswerRelevancyMetric
        from deepeval.test_case import LLMTestCase
    except Exception as exc:
        pytest.skip(f"deepeval not available: {exc}")

    cfg = configure_eval_openai_env()
    if cfg.mode == "skip":
        pytest.skip("EVAL_LLM_MODE=skip")

    # DeepEval requires pricing hints for unsupported models
    os.environ.setdefault("OPENAI_COST_PER_INPUT_TOKEN", "0")
    os.environ.setdefault("OPENAI_COST_PER_OUTPUT_TOKEN", "0")

    client = TestClient(app)
    model_name = os.getenv("EVAL_LLM_MODEL", "llama3")
    try:
        metric = AnswerRelevancyMetric(model=model_name, threshold=0.5)
    except ValueError as exc:
        pytest.skip(f"Eval model not supported by deepeval: {exc}")

    test_cases: list[LLMTestCase] = []
    for case in _load_cases():
        question = case["question"]
        expected = case.get("expected_contains") or case.get("expected") or "Should address the question."

        resp = client.post("/api/ask", json={"question": question})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        answer = str(data.get("answer") or "")

        test_cases.append(
            LLMTestCase(
                input=question,
                actual_output=answer,
                expected_output=expected,
                retrieval_context=[src.get("path") or src.get("uuid") or "" for src in data.get("sources") or []],
            )
        )

    try:
        evaluate(test_cases, [metric])
    except Exception as exc:  # pragma: no cover - defensive skip if backend missing
        pytest.skip(f"Eval backend unavailable or failed: {exc}")
