"""Production ASGI regressions for synchronous ASK graph dispatch (#5925)."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes import ask as ask_routes
from app.components.llm.fabric import LLMBackendTimeout
from app.observability.tracer import current_trace_id
from tests._mvr03_principal_harness import principal_store, provisioned_instance
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, _extra, _record = provisioned_instance(tmp_path)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    return runtime, first


@pytest_asyncio.fixture()
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as value:
        yield value


def _ask_state(answer: str = "grounded answer", *, llm_route: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        answer=answer,
        hits=[],
        recalled=[],
        synthesis_source_ids=[],
        synthesis_receipt_id=None,
        llm_route=llm_route,
    )


def _set_event_with_timestamp(event: threading.Event, timestamps: dict[str, float], key: str) -> None:
    timestamps[key] = time.monotonic()
    event.set()


@pytest.mark.asyncio
async def test_ask_does_not_block_event_loop(client, monkeypatch) -> None:
    """A blocked synchronous graph still leaves the production event loop schedulable."""

    ask_entered = threading.Event()
    release_graph = threading.Event()
    unrelated_get_completed = threading.Event()
    timestamps: dict[str, float] = {}
    observed: dict[str, object] = {}
    loop_thread = threading.get_ident()

    def blocked_graph(*_args, **kwargs):  # type: ignore[no-untyped-def]
        observed.update(
            graph_thread=threading.get_ident(),
            explicit_trace=kwargs.get("trace_id"),
            context_trace=current_trace_id(),
        )
        _set_event_with_timestamp(ask_entered, timestamps, "ask_entered")
        assert release_graph.wait(timeout=2), "watchdog failed to release the blocked graph"
        return _ask_state()

    async def instrumented_app(scope, receive, send):  # type: ignore[no-untyped-def]
        async def observed_send(message):  # type: ignore[no-untyped-def]
            if (
                scope.get("path") == "/"
                and message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                _set_event_with_timestamp(unrelated_get_completed, timestamps, "get_completed")
            await send(message)

        await app(scope, receive, observed_send)

    monkeypatch.setattr(ask_routes, "run_ask_graph", blocked_graph)
    monkeypatch.setattr(ask_routes, "_ensure_hybrid_store_loaded", lambda: None)
    ask_routes._HYBRID_WARMED = True

    def watchdog() -> None:
        if not ask_entered.wait(timeout=1):
            release_graph.set()
            return
        # The fixed route lets the GET finish before this bounded release. The
        # old inline async route reaches this release only after monopolizing
        # the event loop, which makes the ordering assertion fail.
        unrelated_get_completed.wait(timeout=0.75)
        _set_event_with_timestamp(release_graph, timestamps, "graph_released")

    watchdog_thread = threading.Thread(target=watchdog, daemon=True)
    watchdog_thread.start()
    try:
        observed_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=instrumented_app),
            base_url="http://testserver",
        )
        async with observed_client:
            ask_request = asyncio.create_task(
                observed_client.post("/api/ask", json={"question": "blocked"})
            )
            get_request = asyncio.create_task(observed_client.get("/"))
            assert await asyncio.to_thread(ask_entered.wait, 1), "ASK graph did not start"
            ask_response, get_response = await asyncio.gather(ask_request, get_request)
        watchdog_thread.join(timeout=1)
    finally:
        release_graph.set()
        ask_routes._HYBRID_WARMED = False

    assert ask_response.status_code == 200, ask_response.text
    assert get_response.status_code == 200, get_response.text
    assert observed["graph_thread"] != loop_thread
    assert observed["explicit_trace"] == observed["context_trace"]
    assert timestamps["get_completed"] < timestamps["graph_released"]


@pytest.mark.asyncio
async def test_scoped_ask_preserves_lease_through_publication(instance, client, monkeypatch) -> None:
    """Scoped graph and JSON publication stay inside the existing read-effect lease."""

    runtime, first = instance
    selection = await client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [first.vault_binding_id]},
    )
    assert selection.status_code == 201, selection.text
    session_id = selection.json()["context_selection_id"]

    graph_entered = threading.Event()
    release_graph = threading.Event()
    serialization_entered = threading.Event()
    release_serialization = threading.Event()
    unrelated_get_completed = threading.Event()
    timestamps: dict[str, float] = {}
    observed: dict[str, object] = {}
    loop_thread = threading.get_ident()

    def blocked_graph(*_args, **kwargs):  # type: ignore[no-untyped-def]
        observed.update(
            graph_thread=threading.get_ident(),
            active_context=kwargs.get("active_context"),
            active_scope=kwargs.get("active_scope"),
            context_trace=current_trace_id(),
        )
        _set_event_with_timestamp(graph_entered, timestamps, "graph_entered")
        assert release_graph.wait(timeout=2), "watchdog failed to release the scoped graph"
        return _ask_state(answer="scoped answer")

    original_model_dump = ask_routes.AskResponse.model_dump

    def paused_model_dump(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        _set_event_with_timestamp(serialization_entered, timestamps, "serialization_entered")
        assert release_serialization.wait(timeout=2), "watchdog failed to release serialization"
        return original_model_dump(self, *args, **kwargs)

    async def instrumented_app(scope, receive, send):  # type: ignore[no-untyped-def]
        async def observed_send(message):  # type: ignore[no-untyped-def]
            if (
                scope.get("path") == "/"
                and message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                _set_event_with_timestamp(unrelated_get_completed, timestamps, "get_completed")
            await send(message)

        await app(scope, receive, observed_send)

    monkeypatch.setattr(ask_routes, "run_ask_graph", blocked_graph)
    monkeypatch.setattr(ask_routes, "_ensure_hybrid_store_loaded", lambda: None)
    monkeypatch.setattr(ask_routes.AskResponse, "model_dump", paused_model_dump)
    ask_routes._HYBRID_WARMED = True

    def watchdog() -> None:
        if not graph_entered.wait(timeout=1):
            release_graph.set()
            release_serialization.set()
            return
        unrelated_get_completed.wait(timeout=0.75)
        if not release_graph.is_set():
            _set_event_with_timestamp(release_graph, timestamps, "graph_released")
        if not serialization_entered.wait(timeout=1):
            release_serialization.set()
        else:
            release_serialization.wait(timeout=0.75)
            if not release_serialization.is_set():
                release_serialization.set()

    watchdog_thread = threading.Thread(target=watchdog, daemon=True)
    watchdog_thread.start()
    pool = ThreadPoolExecutor(max_workers=1)
    rotation_future = None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=instrumented_app),
            base_url="http://testserver",
        ) as observed_client:
            ask_request = asyncio.create_task(
                observed_client.post(
                    "/api/ask/scoped",
                    json={"question": "scoped blocked"},
                    headers={"X-Active-Context-Session": session_id, "x-trace-id": "trace-scoped"},
                )
            )
            get_request = asyncio.create_task(observed_client.get("/"))
            assert await asyncio.to_thread(graph_entered.wait, 1), "scoped graph did not start"

            rotation_future = pool.submit(
                principal_store(runtime).rotate_credential,
                credential="rotated-during-ask",
                _capability=STORAGE_MUTATION_CAPABILITY,
            )
            await asyncio.sleep(0.05)
            assert not rotation_future.done(), "authority rotation crossed the graph read lease"

            _set_event_with_timestamp(release_graph, timestamps, "graph_released")
            assert await asyncio.to_thread(serialization_entered.wait, 1), "serialization did not start"
            assert not rotation_future.done(), "authority rotation crossed the publication lease"
            assert await asyncio.to_thread(unrelated_get_completed.wait, 1)
            assert timestamps["get_completed"] < timestamps["graph_released"]

            release_serialization.set()
            ask_response, get_response = await asyncio.gather(ask_request, get_request)
            assert ask_response.status_code == 200, ask_response.text
            assert get_response.status_code == 200, get_response.text

            assert rotation_future.result(timeout=2).revision == 2
            stale = await observed_client.post(
                "/api/ask/scoped",
                json={"question": "stale"},
                headers={"X-Active-Context-Session": session_id},
            )
            assert stale.status_code == 401, stale.text
            assert stale.json()["detail"] == "reselection_required: selection is not resolvable for this caller"
    finally:
        release_graph.set()
        release_serialization.set()
        if rotation_future is not None:
            rotation_future.result(timeout=2)
        pool.shutdown(wait=True)
        watchdog_thread.join(timeout=1)
        ask_routes._HYBRID_WARMED = False

    context = observed["active_context"]
    assert getattr(context, "generation", None) == 1
    assert observed["active_scope"] == "default"
    assert observed["context_trace"] == "trace-scoped"
    assert observed["graph_thread"] != loop_thread


@pytest.mark.asyncio
async def test_ask_offload_preserves_request_trace(client, monkeypatch) -> None:
    """Each production request carries its own trace ContextVar into the worker."""

    observed: dict[str, tuple[object, object, int]] = {}
    loop_thread = threading.get_ident()

    def capture_graph(*args, **kwargs):  # type: ignore[no-untyped-def]
        query = str(args[0])
        observed[query] = (
            kwargs.get("trace_id"),
            current_trace_id(),
            threading.get_ident(),
        )
        return _ask_state()

    monkeypatch.setattr(ask_routes, "run_ask_graph", capture_graph)
    monkeypatch.setattr(ask_routes, "_ensure_hybrid_store_loaded", lambda: None)
    ask_routes._HYBRID_WARMED = True
    try:
        first = await client.post(
            "/api/ask", json={"question": "first"}, headers={"x-trace-id": "trace-first"}
        )
        second = await client.post(
            "/api/ask", json={"question": "second"}, headers={"x-trace-id": "trace-second"}
        )
    finally:
        ask_routes._HYBRID_WARMED = False

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert observed["first"][:2] == ("trace-first", "trace-first")
    assert observed["second"][:2] == ("trace-second", "trace-second")
    assert observed["first"][2] != loop_thread
    assert observed["second"][2] != loop_thread
    assert current_trace_id() is None


@pytest.mark.asyncio
async def test_ask_offload_preserves_response_and_error_contract(client, monkeypatch) -> None:
    """Sync dispatch keeps response fields and translated model timeout errors intact."""

    def successful_graph(*_args, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            answer="contract answer",
            hits=[
                {
                    "id": "source-1",
                    "title": "Source one",
                    "source_ref": "vault/source-1.md",
                    "payload": {"origin": "vault", "title": "Source one"},
                }
            ],
            recalled=[],
            synthesis_source_ids=["source-1"],
            synthesis_receipt_id="receipt-1",
            llm_route={"provider": "mock"},
        )

    monkeypatch.setattr(ask_routes, "run_ask_graph", successful_graph)
    monkeypatch.setattr(ask_routes, "_ensure_hybrid_store_loaded", lambda: None)
    ask_routes._HYBRID_WARMED = True
    try:
        response = await client.post(
            "/api/ask", json={"question": "contract"}, headers={"x-trace-id": "trace-contract"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["answer"] == "contract answer"
        assert body["sources"] == [
            {
                "uuid": "source-1",
                "title": "Source one",
                "origin": "vault",
                "plane": "vault",
                "zone": None,
                "path": "vault/source-1.md",
                "orientation": "unknown",
                "orientation_provenance": {},
                "orientation_degradation": None,
                "evidence_role": None,
            }
        ]
        assert body["synthesis_receipt_id"] == "receipt-1"
        assert body["synthesis_source_ids"] == ["source-1"]
        assert response.headers["x-trace-id"] == "trace-contract"

        def timeout_graph(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise LLMBackendTimeout(provider="ollama", timeout_seconds=0.1)

        monkeypatch.setattr(ask_routes, "run_ask_graph", timeout_graph)
        timeout = await client.post(
            "/api/ask", json={"question": "timeout"}, headers={"x-trace-id": "trace-timeout"}
        )
    finally:
        ask_routes._HYBRID_WARMED = False

    assert timeout.status_code == 504, timeout.text
    detail = timeout.json()["detail"]
    assert detail == {
        "error": "llm_backend_timeout",
        "provider": "ollama",
        "timeout_seconds": 0.1,
        "trace_id": "trace-timeout",
        "message": "ollama backend timed out after 0.1s",
    }
