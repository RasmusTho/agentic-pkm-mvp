from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.not_pg

CASES_PATH = Path("docs/eval/retrieval_bilingual_seed.yaml")
CORPUS_PATH = Path("data/golden/bilingual_corpus.jsonl")

REQUIRED_FIELDS = {
    "id",
    "language",
    "query",
    "relevant_artifact_ids",
    "route_intent",
    "provenance_expectation",
    "trust_expectation",
}
LANGUAGES = {"sv", "en"}
ROUTE_INTENTS = {
    "exact_lexical",
    "hybrid_semantic",
    "recall_into_ask",
    "low_trust_citation",
}


def _load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == "retrieval_eval_case.v1"
    return list(raw["cases"])


def _load_corpus_ids(path: Path = CORPUS_PATH) -> set[str]:
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        ids.add(str(doc["doc_id"]))
    return ids


def _validate_cases(cases: list[dict[str, Any]], valid_ids: set[str]) -> None:
    seen_ids: set[str] = set()
    for idx, case in enumerate(cases):
        missing = sorted(REQUIRED_FIELDS - set(case))
        assert not missing, f"case[{idx}] missing required field(s): {missing}"

        case_id = str(case["id"])
        assert case_id not in seen_ids, f"duplicate eval case id: {case_id}"
        seen_ids.add(case_id)

        language = case["language"]
        assert language in LANGUAGES, (
            f"{case_id} language must be one of {sorted(LANGUAGES)}, got {language!r}"
        )
        route_intent = case["route_intent"]
        assert route_intent in ROUTE_INTENTS, (
            f"{case_id} route_intent must be one of {sorted(ROUTE_INTENTS)}, "
            f"got {route_intent!r}"
        )
        relevant_ids = case["relevant_artifact_ids"]
        assert isinstance(relevant_ids, list) and relevant_ids, (
            f"{case_id} relevant_artifact_ids must be a non-empty list"
        )
        unresolved = sorted(set(relevant_ids) - valid_ids)
        assert not unresolved, (
            f"{case_id} references unresolved relevant_artifact_ids: {unresolved}"
        )


def test_seed_covers_slices() -> None:
    cases = _load_cases()
    _validate_cases(cases, _load_corpus_ids())

    assert len(cases) == 11
    by_route: dict[str, set[str]] = {route: set() for route in ROUTE_INTENTS}
    for case in cases:
        by_route[case["route_intent"]].add(case["language"])

    assert set(by_route) == ROUTE_INTENTS
    for route, languages in by_route.items():
        assert languages == LANGUAGES, (
            f"{route} must include at least one Swedish and one English case"
        )


def test_malformed_case_fails_loud() -> None:
    valid_ids = {"known-doc"}
    missing_language = [
        {
            "id": "bad-missing-language",
            "query": "Where is the note?",
            "relevant_artifact_ids": ["known-doc"],
            "route_intent": "exact_lexical",
            "provenance_expectation": "source_ref visible",
            "trust_expectation": "own",
        }
    ]
    with pytest.raises(AssertionError, match="missing required field.*language"):
        _validate_cases(missing_language, valid_ids)

    unresolved = [
        {
            "id": "bad-unresolved-id",
            "language": "en",
            "query": "Where is the note?",
            "relevant_artifact_ids": ["missing-doc"],
            "route_intent": "exact_lexical",
            "provenance_expectation": "source_ref visible",
            "trust_expectation": "own",
        }
    ]
    with pytest.raises(AssertionError, match="unresolved relevant_artifact_ids"):
        _validate_cases(unresolved, valid_ids)
