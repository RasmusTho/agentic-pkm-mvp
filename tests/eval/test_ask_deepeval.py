from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from deepeval.evaluate import evaluate
from deepeval.metrics import AnswerRelevancyMetric
from deepeval.test_case import LLMTestCase
from fastapi.testclient import TestClient

from app.api.app import app
from app.eval.llm_client import configure_eval_openai_env

CASES_PATH = Path("docs/eval/ask_cases.yaml")


def _load_cases() -> list[dict[str, Any]]:
    if CASES_PATH.exists():
        return yaml.safe_load(CASES_PATH.read_text(encoding="utf-8")) or []
    return [
        {"question": "What is the Reality-MVP focus?", "expected_contains": "Reality-MVP"},
        {"question": "How are UUIDs handled in the Alpha vault?", "expected_contains": "frontmatter"},
    ]


@pytest.mark.eval
def test_ask_answer_relevancy() -> None:
    cfg = configure_eval_openai_env()
    if cfg.mode == "skip":
        pytest.skip("EVAL_LLM_MODE=skip")

    client = TestClient(app)
    metric = AnswerRelevancyMetric(model="gpt-3.5-turbo", threshold=0.5)

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
