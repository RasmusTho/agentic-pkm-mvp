from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.fitness.relations import RELATIONS_PATH, promotion_relation_coverage, relation_metrics

pytestmark = pytest.mark.not_pg


def test_relation_coverage_reads_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "relations.json"
    sample.write_text(
        json.dumps(
            {
                "promoted": [
                    {"doc_id": "a", "relations": [{"target": "b", "type": "supports"}]},
                    {"doc_id": "b", "relations": [{"type": "supports"}]},
                    {"doc_id": "c", "relations": [{"target": "d", "type": "extends"}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.fitness.relations.RELATIONS_PATH", sample)
    metrics = relation_metrics()
    assert metrics["coverage"] == pytest.approx(66.6666, rel=1e-3)
    assert metrics["validity"] == pytest.approx(66.6666, rel=1e-3)
    assert promotion_relation_coverage() == metrics["coverage"]
