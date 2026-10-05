"""Fake HTTP runs the actual pinned SDK; model-profile changes do not edit this adapter."""

from importlib.metadata import version
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import socket
from threading import Barrier

import httpcore2
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
    result, usage = adapter.judge(
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
        TypeSafeAdapter(transport_factory=forbidden).judge(
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
        TypeSafeAdapter(transport_factory=lambda: httpx2.MockTransport(send)).judge(
            product_intent_request("å" * 1000), model="jev-1.13.0", api_key="synthetic-key"
        )
    assert exc.value.outcome == "provider_rejected" and len(calls) == 1


@pytest.mark.parametrize("overlapping_calls", [1, 2])
@pytest.mark.parametrize(
    ("wire_case", "outcome"),
    [
        ("rejection_header", "provider_rejected"),
        ("malformed_status", "outcome_unknown_after_dispatch"),
    ],
)
def test_actual_http_transport_never_logs_raw_provider_diagnostics(
    monkeypatch, caplog, overlapping_calls, wire_case, outcome
) -> None:
    """TSO02-R1-F1: MockTransport misses httpcore's headers/protocol DEBUG logs."""
    key = "synthetic-http-transport-key"
    intent = "synthetic-http-transport-intent"
    canaries = f"{key} {intent}".encode()
    wire = (
        b"HTTP/1.1 429 Too Many Requests\r\nX-Provider-Diagnostic: "
        + canaries
        + b"\r\nContent-Length: 0\r\n\r\n"
        if wire_case == "rejection_header"
        else canaries + b"\r\n\r\n"
    )
    names = (
        "typesafe_sdk", "httpx2", "httpcore2", "httpcore2.connection",
        "httpcore2.http11", "httpcore2.http2", "httpcore2.proxy", "httpcore2.socks",
    )
    for name in names:
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "disabled", False)
        # Include direct child handlers: parent filters/disabled flags cannot guard these.
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        caplog.set_level(logging.DEBUG, logger=name)
    caplog.set_level(logging.DEBUG)
    barrier = Barrier(overlapping_calls)
    backends = []

    class FakeNetwork(httpcore2.MockBackend):
        attempts = 0

        def connect_tcp(self, *args, **kwargs):
            self.attempts += 1
            barrier.wait(timeout=5)
            return super().connect_tcp(*args, **kwargs)

    def make_transport():
        backend = FakeNetwork([wire])
        backends.append(backend)
        transport = httpx2.HTTPTransport(retries=0, trust_env=False)
        transport._pool._network_backend = backend
        return transport

    def forbidden_network(*args, **kwargs):
        pytest.fail("transport conformance must never open a socket")

    monkeypatch.setattr(socket, "create_connection", forbidden_network)

    def execute():
        with pytest.raises(TypeSafeAdapterError) as exc:
            TypeSafeAdapter(transport_factory=make_transport).judge(
                product_intent_request(intent), model="jev-1.13.0", api_key=key
            )
        return exc.value.outcome, str(exc.value)

    with ThreadPoolExecutor(max_workers=overlapping_calls) as pool:
        results = list(pool.map(lambda _: execute(), range(overlapping_calls)))
    assert results == [(outcome, outcome)] * overlapping_calls
    assert len(backends) == overlapping_calls
    assert all(backend.attempts == 1 for backend in backends)
    assert key not in caplog.text and intent not in caplog.text
    assert "X-Provider-Diagnostic" not in caplog.text
    assert "illegal status line" not in caplog.text
    # Suppression remains in force after overlapping calls finish, including lazy branches.
    assert all(logging.getLogger(name).disabled for name in names)
