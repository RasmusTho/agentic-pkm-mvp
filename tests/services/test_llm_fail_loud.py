from __future__ import annotations

import socket
import threading
import time

import pytest

from app.services import llm as llm_service
from app.services.llm import LLMBackendTimeout, LLMError, _deterministic_llm_response, call_llm


class _HangingBackend:
    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._stop = threading.Event()
        self._accepted: socket.socket | None = None
        self.port = 0
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_HangingBackend":
        self._listener.bind(("127.0.0.1", 0))
        self.port = int(self._listener.getsockname()[1])
        self._listener.listen(1)
        self._listener.settimeout(2.0)
        self._thread = threading.Thread(target=self._serve_once, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args) -> None:
        self._stop.set()
        if self._accepted is not None:
            self._accepted.close()
        self._listener.close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def _serve_once(self) -> None:
        try:
            conn, _addr = self._listener.accept()
        except OSError:
            return
        self._accepted = conn
        self._stop.wait(timeout=5.0)


def test_ollama_provider_error_does_not_return_canned_response(monkeypatch, clean_llm_env) -> None:
    """A real-provider (ollama) HTTP error/timeout must propagate, never resolve
    to the canned deterministic blob.

    Masking a provider error with ``_deterministic_llm_response()`` manufactures
    a false-green ASK synthesis receipt and defeats the fail-loud promotion
    caution (#2108 / #1997 / #1999).
    """
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_PROVIDER_ENFORCE", "1")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    clean_llm_env.delenv("LLM_MOCK_RESPONSE", raising=False)
    # Keep the retry backoff instant for the test.
    monkeypatch.setattr(llm_service, "_DEFAULT_BASE_DELAY", 0.0)
    monkeypatch.setattr(llm_service, "_DEFAULT_MAX_RETRIES", 1)

    def _boom(*args, **kwargs):
        raise RuntimeError("ollama http 404: model 'gpt-4.1-mini' not found")

    monkeypatch.setattr(llm_service, "_ollama_chat", _boom)

    with pytest.raises(LLMError):
        call_llm("ask", {"system": "s", "user": "u"}, kind="ask.answer")


def test_issue_3151_ollama_backend_timeout_named_error(monkeypatch, clean_llm_env) -> None:
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_PROVIDER_ENFORCE", "1")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("LLM_TIMEOUT", "0.1")
    monkeypatch.setattr(llm_service, "_DEFAULT_MAX_RETRIES", 0)
    monkeypatch.setattr(llm_service, "_DEFAULT_BASE_DELAY", 0.0)

    with _HangingBackend() as backend:
        clean_llm_env.setenv("OLLAMA_URL", f"http://127.0.0.1:{backend.port}")
        start = time.perf_counter()
        with pytest.raises(LLMBackendTimeout) as excinfo:
            call_llm("ask", {"system": "s", "user": "u"}, kind="ask.answer")

    elapsed = time.perf_counter() - start
    assert elapsed < 1.0
    assert excinfo.value.provider == "ollama"
    assert excinfo.value.timeout_seconds == 0.1
    assert "timed out" in str(excinfo.value)


def test_deterministic_stub_confined_to_mock(monkeypatch, clean_llm_env) -> None:
    """Deterministic stub responses are reachable only when provider == 'mock'.

    A real provider returns its own output (success) or raises (failure); it is
    never silently replaced by the canned blob.
    """
    canned = _deterministic_llm_response()

    # provider == mock → the deterministic stub IS the response.
    clean_llm_env.setenv("LLM_PROVIDER", "mock")
    clean_llm_env.delenv("LLM_MOCK_RESPONSE", raising=False)
    mock_result = call_llm("decide", {"system": "s", "user": "u"}, kind="agent.decide")
    assert mock_result.strip() == canned.strip()

    # provider == ollama (real) with a successful call → the real output, never
    # the canned stub.
    clean_llm_env.setenv("LLM_PROVIDER", "ollama")
    clean_llm_env.setenv("LLM_MODEL", "llama3.1:8b")
    clean_llm_env.setenv("OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(llm_service, "_ollama_chat", lambda *a, **k: "a real generated answer")
    real_result = call_llm("ask", {"system": "s", "user": "u"}, kind="ask.answer")
    assert real_result == "a real generated answer"
    assert real_result.strip() != canned.strip()
