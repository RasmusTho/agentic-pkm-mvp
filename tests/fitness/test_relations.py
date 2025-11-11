from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.fitness.relations import RELATIONS_PATH, promotion_relation_coverage

pytestmark = pytest.mark.not_pg


def test_relation_coverage_reads_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = tmp_path / "relations.json"
    sample.write_text(
        json.dumps(
            {
                "promoted": [
                    {"doc_id": "a", "relations": ["b"]},
                    {"doc_id": "b", "relations": []},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.fitness.relations.RELATIONS_PATH", sample)
    assert promotion_relation_coverage() == pytest.approx(50.0)
