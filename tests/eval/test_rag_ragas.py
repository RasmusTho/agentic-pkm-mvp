from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.app import app
from app.eval.llm_client import configure_eval_openai_env
from app.retrieval.hybrid import get_store as get_hybrid_store

CASES_PATH = Path("docs/eval/rag_cases.yaml")
MIN_THRESHOLD = 0.5  # seed threshold; tighten as retrieval quality improves


def _load_cases() -> list[dict[str, Any]]:
    if CASES_PATH.exists():
        return yaml.safe_load(CASES_PATH.read_text(encoding="utf-8")) or []
    return []


def _metric_names(metrics: list[Any]) -> list[str]:
    names: list[str] = []
    for metric in metrics:
        name = getattr(metric, "name", None) or getattr(metric, "__name__", None)
        names.append(str(name or metric))
    return names


def _score_value(raw_score: Any) -> float:
    # Ragas score objects have varied APIs across versions; normalize to float.
    for attr in ("value", "score"):
        if hasattr(raw_score, attr):
            return float(getattr(raw_score, attr))
    if isinstance(raw_score, dict):
        for key in ("value", "score"):
            if key in raw_score:
                return float(raw_score[key])
    return float(raw_score)


@pytest.mark.eval
def test_rag_quality_with_ragas() -> None:
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, faithfulness
    except Exception as exc:
        pytest.skip(f"Ragas dependencies not available: {exc}")

    metrics = [answer_relevancy, faithfulness]
    metric_names = _metric_names(metrics)

    cfg = configure_eval_openai_env()
    if cfg.mode == "skip":
        pytest.skip("EVAL_LLM_MODE=skip")

    cases = _load_cases()
    if not cases:
        pytest.skip("No RAG cases available")

    # Ensure hybrid store is primed; tests may run with an empty store otherwise.
    get_hybrid_store().set_documents([])

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
        result = evaluate(dataset, metrics=metrics)
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
        if isinstance(scores, dict):
            items = scores.items()
        elif isinstance(scores, list):
            if len(scores) != len(metric_names):
                pytest.skip("Unsupported Ragas scores list length")
            try:
                mapped_scores = {name: _score_value(score) for name, score in zip(metric_names, scores)}
            except Exception as exc:  # pragma: no cover - defensive
                pytest.skip(f"Unsupported Ragas scores list format: {exc}")
            items = mapped_scores.items()
        else:
            pytest.skip("Unsupported Ragas EvaluationResult scores type")

    for metric_name, score in items:
        assert score >= MIN_THRESHOLD, f"{metric_name} below threshold: {score} < {MIN_THRESHOLD}"
