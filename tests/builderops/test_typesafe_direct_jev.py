from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from scripts import ygg_jev


def _request_bytes() -> bytes:
    return json.dumps(
        {
            "state": {"candidate_count": 2, "source": "synthetic"},
            "questions": {
                "best": {
                    "type": "choice",
                    "instructions": "Which option best fits the stated goal?",
                    "criteria": {"a": "Option A", "b": "Option B"},
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _response_bytes() -> bytes:
    return json.dumps(
        {
            "model": "jev-1.13.0",
            "answers": {
                "best": {
                    "type": "choice",
                    "choice": "a",
                    "probabilities": {"a": 0.8, "b": 0.2},
                    "confidence": 0.8,
                }
            },
            "usage": {"input_tokens": 12, "output_tokens": 3},
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _stdin(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(payload)))


class _FakeResponse(io.BytesIO):
    def getcode(self) -> int:
        return 200


class _FakeProcess:
    def __init__(self, output: bytes, returncode: int = 0) -> None:
        read_fd, write_fd = os.pipe()
        os.write(write_fd, output)
        os.close(write_fd)
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.returncode = returncode

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


class _RunningFakeProcess:
    def __init__(self) -> None:
        read_fd, self.write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, "rb", buffering=0)
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake-ygg-secret", timeout)
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15
        os.close(self.write_fd)

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        os.close(self.write_fd)


def test_cli_makes_one_validated_request_without_emitting_credential(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_key = "synthetic-key-canary"
    helper = Path("/fake/ygg-secret")
    monkeypatch.setattr(ygg_jev, "SECRET_HELPER", helper)
    _stdin(monkeypatch, _request_bytes())
    secret_calls: list[tuple[list[str], dict[str, Any]]] = []
    requests: list[Any] = []
    opener_handlers: list[Any] = []

    def fake_secret_run(args: list[str], **kwargs: Any) -> _FakeProcess:
        secret_calls.append((args, kwargs))
        return _FakeProcess(api_key.encode())

    class _FakeOpener:
        def open(self, request: Any, *, timeout: int) -> _FakeResponse:
            requests.append(request)
            assert timeout == ygg_jev.REQUEST_TIMEOUT_SECONDS
            assert request.full_url == ygg_jev.API_ENDPOINT
            assert request.get_method() == "POST"
            assert request.get_header("Authorization") == f"Bearer {api_key}"
            assert request.get_header("Content-type") == "application/json"
            sent = json.loads(request.data)
            assert sent["model"] == "jev-latest"
            assert sent["state"] == {"candidate_count": 2, "source": "synthetic"}
            assert set(sent) == {"state", "model", "questions"}
            return _FakeResponse(_response_bytes())

    monkeypatch.setattr(ygg_jev.subprocess, "Popen", fake_secret_run)
    def fake_build_opener(*handlers: Any) -> _FakeOpener:
        opener_handlers.extend(handlers)
        return _FakeOpener()

    monkeypatch.setattr(ygg_jev.urllib.request, "build_opener", fake_build_opener)

    assert ygg_jev.main([]) == 0

    captured = capsys.readouterr()
    assert len(secret_calls) == 1
    assert secret_calls[0][0] == [str(helper), "typesafe.api-key"]
    assert secret_calls[0][1]["stdin"] is subprocess.DEVNULL
    assert secret_calls[0][1]["stderr"] is subprocess.DEVNULL
    assert secret_calls[0][1]["close_fds"] is True
    assert "TYPESAFE_API_KEY" not in secret_calls[0][1]["env"]
    assert "BWS_ACCESS_TOKEN" not in secret_calls[0][1]["env"]
    assert len(requests) == 1
    assert isinstance(opener_handlers[0], ygg_jev.urllib.request.ProxyHandler)
    assert opener_handlers[0].proxies == {}
    assert opener_handlers[1] is ygg_jev._NoRedirectHandler
    returned = json.loads(captured.out)
    assert returned == {
        "model": "jev-1.13.0",
        "answers": {
            "best": {
                "type": "choice",
                "choice": "a",
                "probabilities": {"a": 0.8, "b": 0.2},
                "confidence": 0.8,
            }
        },
        "usage": {"input_tokens": 12, "output_tokens": 3},
    }
    assert api_key not in captured.out
    assert api_key not in captured.err
    assert "synthetic" not in captured.out
    assert "synthetic" not in captured.err


def test_invalid_missing_and_ambiguous_requests_are_terminal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    helper = Path("/fake/ygg-secret")
    monkeypatch.setattr(ygg_jev, "SECRET_HELPER", helper)
    secret_calls = 0
    network_calls = 0

    def unexpected_secret_run(*args: Any, **kwargs: Any) -> _FakeProcess:
        nonlocal secret_calls
        secret_calls += 1
        raise AssertionError("invalid input must fail before secret resolution")

    monkeypatch.setattr(ygg_jev.subprocess, "Popen", unexpected_secret_run)
    monkeypatch.setattr(
        ygg_jev.urllib.request,
        "build_opener",
        lambda handler: pytest.fail("invalid input must not call the provider"),
    )

    _stdin(
        monkeypatch,
        b'{"state":"synthetic","questions":{},"model":"caller-controlled"}',
    )
    assert ygg_jev.main([]) == 2
    invalid_output = capsys.readouterr()
    assert "synthetic" not in invalid_output.err
    assert secret_calls == 0

    _stdin(monkeypatch, b'{"state":"' + (b"x" * ygg_jev.MAX_REQUEST_BYTES) + b'"}')
    assert ygg_jev.main([]) == 2
    oversized_output = capsys.readouterr()
    assert "x" * 32 not in oversized_output.err
    assert secret_calls == 0

    def missing_secret_run(args: list[str], **kwargs: Any) -> _FakeProcess:
        nonlocal secret_calls
        secret_calls += 1
        return _FakeProcess(b"", returncode=1)

    monkeypatch.setattr(ygg_jev.subprocess, "Popen", missing_secret_run)
    _stdin(monkeypatch, _request_bytes())
    assert ygg_jev.main([]) == 3
    missing_output = capsys.readouterr()
    assert "synthetic-key-canary" not in missing_output.err
    assert secret_calls == 1

    def available_secret_run(args: list[str], **kwargs: Any) -> _FakeProcess:
        nonlocal secret_calls
        secret_calls += 1
        return _FakeProcess(b"synthetic-key-canary")

    class _TimeoutOpener:
        def open(self, request: Any, *, timeout: int) -> Any:
            nonlocal network_calls
            network_calls += 1
            raise TimeoutError("synthetic-key-canary transport detail")

    monkeypatch.setattr(ygg_jev.subprocess, "Popen", available_secret_run)
    monkeypatch.setattr(
        ygg_jev.urllib.request,
        "build_opener",
        lambda *handlers: _TimeoutOpener(),
    )
    _stdin(monkeypatch, _request_bytes())
    assert ygg_jev.main([]) == 4
    ambiguous_output = capsys.readouterr()
    assert "synthetic-key-canary" not in ambiguous_output.err
    assert "no retry was attempted" in ambiguous_output.err
    assert secret_calls == 2
    assert network_calls == 1


def test_secret_helper_output_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ygg_jev.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(b"x" * (ygg_jev.MAX_SECRET_BYTES + 1)),
    )

    with pytest.raises(ygg_jev.CredentialUnavailable):
        ygg_jev._read_api_key()


@pytest.mark.parametrize("failure", ["timeout", "interrupt"])
def test_secret_helper_is_stopped_on_timeout_or_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    process = _RunningFakeProcess()
    monkeypatch.setattr(ygg_jev.subprocess, "Popen", lambda *args, **kwargs: process)

    if failure == "timeout":
        monkeypatch.setattr(ygg_jev, "SECRET_TIMEOUT_SECONDS", 0)
        expected_exception: type[BaseException] = ygg_jev.CredentialUnavailable
    else:
        class _InterruptSelector:
            def __enter__(self) -> _InterruptSelector:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def register(self, *_args: object) -> None:
                return None

            def select(self, _timeout: float) -> list[object]:
                raise KeyboardInterrupt()

        monkeypatch.setattr(ygg_jev.selectors, "DefaultSelector", _InterruptSelector)
        expected_exception = KeyboardInterrupt

    with pytest.raises(expected_exception):
        ygg_jev._read_api_key()

    assert process.terminated
    assert not process.killed


@pytest.mark.parametrize(
    "raw_response",
    [
        b'{"model":"jev","answers":{},"usage":{"input_tokens":1,"output_tokens":1}}',
        b'{"model":"jev","answers":{"best":{"type":"noul","noul":0.5}},"usage":{"input_tokens":1,"output_tokens":1}}',
    ],
)
def test_mismatched_provider_answers_are_rejected(raw_response: bytes) -> None:
    questions = build_questions()
    with pytest.raises(ygg_jev.InvalidResponse):
        ygg_jev.validate_provider_response(raw_response, questions)


def test_response_validator_accepts_noul_choice_and_score_answers() -> None:
    questions = {
        "is_relevant": {
            "type": "noul",
            "instructions": "Is this synthetic example relevant?",
        },
        "category": {
            "type": "choice",
            "instructions": "Choose one synthetic category.",
            "criteria": {"a": None, "b": None},
        },
        "quality": {
            "type": "score",
            "instructions": "Score this synthetic example.",
            "criteria": ["low", "medium", "high"],
        },
    }
    response = json.dumps(
        {
            "model": "jev-1.13.0",
            "answers": {
                "is_relevant": {"type": "noul", "noul": 0.75},
                "category": {
                    "type": "choice",
                    "choice": "a",
                    "probabilities": {"a": 0.75, "b": 0.25},
                    "confidence": 0.75,
                },
                "quality": {
                    "type": "score",
                    "score": 1.25,
                    "legend": {"0": "low", "1": "medium", "2": "high"},
                    "probabilities": {"0": 0.25, "1": 0.25, "2": 0.5},
                    "confidence": 0.62,
                },
            },
            "usage": {"input_tokens": 20, "output_tokens": 7},
        },
        separators=(",", ":"),
    ).encode("utf-8")

    result = ygg_jev.validate_provider_response(response, questions)

    assert set(result["answers"]) == {"is_relevant", "category", "quality"}
    assert result["answers"]["is_relevant"]["noul"] == 0.75
    assert result["answers"]["category"]["choice"] == "a"
    assert result["answers"]["quality"]["score"] == 1.25


def test_response_validator_rejects_mismatched_score_legend() -> None:
    questions = {
        "quality": {
            "type": "score",
            "instructions": "Score this synthetic example.",
            "criteria": ["low", "medium", "high"],
        }
    }
    response = json.dumps(
        {
            "model": "jev-1.13.0",
            "answers": {
                "quality": {
                    "type": "score",
                    "score": 1,
                    "legend": {"0": "low", "1": "high", "2": "medium"},
                    "probabilities": {"0": 0.2, "1": 0.6, "2": 0.2},
                    "confidence": 0.6,
                }
            },
            "usage": {"input_tokens": 5, "output_tokens": 4},
        },
        separators=(",", ":"),
    ).encode("utf-8")

    with pytest.raises(ygg_jev.InvalidResponse):
        ygg_jev.validate_provider_response(response, questions)


@pytest.mark.parametrize(
    "criteria",
    [
        ["low", {"label": "high"}],
        ["low", ["high"]],
        ["low", "low", "high"],
    ],
)
def test_score_criteria_require_ordered_string_labels(criteria: list[Any]) -> None:
    request = json.dumps(
        {
            "state": "synthetic",
            "questions": {
                "quality": {
                    "type": "score",
                    "instructions": "Score this synthetic example.",
                    "criteria": criteria,
                }
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")

    with pytest.raises(ygg_jev.InvalidRequest):
        ygg_jev.build_provider_request(request)


def test_provider_error_body_is_not_emitted_or_retried(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api_key = "synthetic-key-canary"
    monkeypatch.setattr(ygg_jev, "SECRET_HELPER", Path("/fake/ygg-secret"))
    monkeypatch.setattr(
        ygg_jev.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(api_key.encode()),
    )
    calls = 0

    class _ErrorOpener:
        def open(self, request: Any, *, timeout: int) -> Any:
            nonlocal calls
            calls += 1
            raise ygg_jev.urllib.error.HTTPError(
                ygg_jev.API_ENDPOINT,
                500,
                "synthetic provider failure",
                hdrs=None,
                fp=io.BytesIO(b"synthetic-key-canary private provider body"),
            )

    monkeypatch.setattr(
        ygg_jev.urllib.request,
        "build_opener",
        lambda *handlers: _ErrorOpener(),
    )
    _stdin(monkeypatch, _request_bytes())

    assert ygg_jev.main([]) == 4

    captured = capsys.readouterr()
    assert calls == 1
    assert "synthetic-key-canary" not in captured.out + captured.err
    assert "private provider body" not in captured.out + captured.err
    assert "no retry was attempted" in captured.err


def build_questions() -> dict[str, Any]:
    return {
        "best": {
            "type": "choice",
            "instructions": "Choose one.",
            "criteria": {"a": None, "b": None},
        }
    }
