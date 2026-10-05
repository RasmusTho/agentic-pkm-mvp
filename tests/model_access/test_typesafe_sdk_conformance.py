"""Fake HTTP runs the actual pinned SDK; model-profile changes do not edit this adapter."""

from importlib.metadata import version
import json

import httpx2
import pytest

from llm_contract import SystemOneJudgmentRequest

from app.model_access.product_judgment_contract import product_intent_request
from app.model_access.typesafe_adapter import (
    TypeSafeAdapter,
    TypeSafeAdapterError,
    TYPESAFE_SDK_VERSION,
)


def test_pinned_sdk_round_trips_all_neutral_primitives() -> None:
    assert version("typesafe-sdk") == TYPESAFE_SDK_VERSION == "0.7.2"
    request = SystemOneJudgmentRequest.model_validate(
        {
            "state": {"synthetic": "conformance"},
            "questions": [
                {
                    "question_id": "c",
                    "kind": "choice",
                    "instructions": "Choose",
                    "criteria": {"a": None, "b": None},
                },
                {
                    "question_id": "s",
                    "kind": "score",
                    "instructions": "Rate",
                    "criteria": ["low", "high"],
                },
                {"question_id": "n", "kind": "noul", "instructions": "Is it true?"},
            ],
        }
    )
    calls = []

    def send(wire: httpx2.Request) -> httpx2.Response:
        calls.append(wire)
        payload = json.loads(wire.content)
        assert set(payload) == {"state", "questions", "model"}
        assert payload["model"] == "jev-1.13.0"
        assert [q["type"] for q in payload["questions"].values()] == ["choice", "score", "noul"]
        assert "x-typesafe-retry-count" not in wire.headers
        return httpx2.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {},
                "answers": {
                    "c": {
                        "type": "choice",
                        "choice": "a",
                        "confidence": 0.8,
                        "probabilities": {"a": 0.9, "b": 0.1},
                    },
                    "s": {
                        "type": "score",
                        "score": 0.3,
                        "confidence": 0.8,
                        "legend": {"0": "low", "1": "high"},
                        "probabilities": {"0": 0.7, "1": 0.3},
                    },
                    "n": {"type": "noul", "noul": 0.5},
                },
            },
        )

    adapter = TypeSafeAdapter(transport_factory=lambda: httpx2.MockTransport(send))
    result, usage = adapter.execute(
        request, model="jev-1.13.0", api_key="synthetic-conformance-key"
    )
    assert result.validate_against(request) == result
    assert len(calls) == 1 and usage.input_tokens is None
    assert result.provenance.model == "jev-1.13.0"


def test_sdk_version_mismatch_fails_before_transport_creation(monkeypatch) -> None:
    monkeypatch.setattr("app.model_access.typesafe_adapter.version", lambda _: "0.8.0")

    def forbidden():
        pytest.fail("unreviewed SDK must not create transport")

    with pytest.raises(TypeSafeAdapterError) as exc:
        TypeSafeAdapter(transport_factory=forbidden).execute(
            product_intent_request("synthetic"), model="jev-1.13.0", api_key="synthetic-key"
        )
    assert exc.value.outcome == "unavailable_before_send"


def test_provider_request_at_utf8_intent_limit_is_within_four_kibibytes() -> None:
    calls = []

    def send(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        assert len(request.content) <= 4096
        return httpx2.Response(429, json={"error": "synthetic"})

    with pytest.raises(TypeSafeAdapterError) as exc:
        TypeSafeAdapter(transport_factory=lambda: httpx2.MockTransport(send)).execute(
            product_intent_request("å" * 1000), model="jev-1.13.0", api_key="synthetic-key"
        )
    assert exc.value.outcome == "provider_rejected" and len(calls) == 1
