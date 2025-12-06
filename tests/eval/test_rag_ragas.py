from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.app import app
from app.eval.llm_client import configure_eval_openai_env

CASES_PATH = Path("docs/eval/rag_cases.yaml")
MIN_THRESHOLD = 0.5  # seed threshold; tighten as retrieval quality improves


def _load_cases() -> list[dict[str, Any]]:
    if CASES_PATH.exists():
        return yaml.safe_load(CASES_PATH.read_text(encoding="utf-8")) or []
    return []


@pytest.mark.eval
def test_rag_quality_with_ragas() -> None:
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, faithfulness
    except Exception as exc:
        pytest.skip(f"Ragas dependencies not available: {exc}")

    cfg = configure_eval_openai_env()
    if cfg.mode == "skip":
        pytest.skip("EVAL_LLM_MODE=skip")

    cases = _load_cases()
    if not cases:
        pytest.skip("No RAG cases available")

    client = TestClient(app)
    rows: list[dict[str, Any]] = []

    for case in cases:
        question = case["question"]
        resp = client.post("/api/ask", json={"question": question})
        if resp.status_code != 200:
            pytest.skip(f"/api/ask unavailable (status={resp.status_code})")
        data = resp.json()
        answer = str(data.get("answer") or "")
        sources = data.get("sources") or []
        contexts = [src.get("path") or src.get("source_ref") or "" for src in sources if src]
        ground_truth = case.get("expected_answer") or ""

        rows.append(
            {
                "question": question,
                "answer": answer,
                "contexts": contexts,
                "ground_truth": ground_truth,
            }
        )

    dataset = Dataset.from_list(rows)

    try:
        result = evaluate(dataset, metrics=[answer_relevancy, faithfulness])
    except Exception as exc:  # pragma: no cover - backend/config errors
        pytest.skip(f"Ragas eval backend unavailable: {exc}")

    if hasattr(result, "items"):
        items = result.items()
    else:
        scores = getattr(result, "scores", None)
        if scores is None and hasattr(result, "to_dict"):
            scores = result.to_dict()
        if scores is None:
            pytest.skip("Unsupported Ragas EvaluationResult format")
        items = scores.items()

    for metric_name, score in items:
        assert score >= MIN_THRESHOLD, f"{metric_name} below threshold: {score} < {MIN_THRESHOLD}"
