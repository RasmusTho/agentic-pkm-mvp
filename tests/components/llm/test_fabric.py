from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier
from types import SimpleNamespace

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.components.llm import fabric
from app.components.llm.fabric import (
    AdapterRuntimeConfig,
    ChatClient,
    LLMRoute,
    LLMTaskIntent,
    _resolve_product_access_route,
    get_chat_client,
    get_chat_client_for_route,
    get_embeddings_client,
)
from app.components.llm.router import LLMRouteError
from app.model_access.catalog import (
    CatalogCache,
    CatalogError,
    CatalogModelDescriptor,
    CatalogSnapshot,
)
from app.model_access.codex_remote_transport import (
    RemoteCatalogError,
    RemotePreflightError,
)
from app.model_access.remote_contract import CompletionResponse, PreflightResponse
from llm_contract import ModelCapabilities


@pytest.fixture(autouse=True)
def _configured_executor_network_paths(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT", "https://192.168.10.25:8443"
    )
    for variable, filename in (
        ("MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE", "ca.pem"),
        ("MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT", "client.pem"),
        ("MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY", "client.key"),
    ):
        path = tmp_path / filename
        path.write_text("test-only placeholder", encoding="utf-8")
        monkeypatch.setenv(variable, str(path))


def test_get_embeddings_client_uses_router_route_even_when_llm_provider_is_set(monkeypatch) -> None:
    class _Router:
        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return LLMRoute(
                provider="ollama",
                model="nomic-embed-text:latest",
                mode="embeddings",
                reason="settings",
            )

    captured: dict[str, str | None] = {}

    def _fake_get_embedding_client(*, override_provider=None, override_model=None):
        captured["provider"] = override_provider
        captured["model"] = override_model
        return object()

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("EMBED_PROVIDER", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.setattr("app.components.llm.fabric.LLMRouter", _Router)
    monkeypatch.setattr("app.components.llm.fabric.get_embedding_client", _fake_get_embedding_client)

    get_embeddings_client(LLMTaskIntent(task_kind="embed", strict_identity_required=True))

    assert captured == {"provider": "ollama", "model": "nomic-embed-text:latest"}


def test_product_call_sites_use_shared_model_access_router(monkeypatch) -> None:
    selected = LLMRoute(
        provider="openai", model="gpt-5.4", mode="chat", reason="settings"
    )

    class _Router:
        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return selected

    resolved = []
    original_router = fabric.ModelAccessRouter

    class _SpyRouter:
        def __init__(self, *, adapter_registry):
            self.inner = original_router(adapter_registry=adapter_registry)

        def resolve(self, *args, **kwargs):
            resolved.append(args[0])
            return self.inner.resolve(*args, **kwargs)

    called = {}

    def _fake_call_llm(name, pack, **kwargs):
        called.update(kwargs)
        return "ok"

    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(fabric, "ModelAccessRouter", _SpyRouter)
    monkeypatch.setattr(fabric, "call_llm", _fake_call_llm)

    client = get_chat_client(LLMTaskIntent(task_kind="qa"))
    assert client.chat("qa", {"system": "trusted", "user": "question"}) == "ok"

    assert len(resolved) == 1
    assert client.model_access_route is not None
    assert client.model_access_route.transport_id == "openai_api"
    assert (client.route.provider, client.route.model) == ("openai", "gpt-5.4")
    assert called["provider_override"] == "openai"
    assert called["model_override"] == "gpt-5.4"


def test_product_rejects_local_codex_transport_before_openai_http_dispatch(monkeypatch) -> None:
    selected = LLMRoute(
        provider="openai",
        model="gpt-5.4",
        mode="chat",
        reason="settings",
        transport_id="codex_cli",
    )

    class _Router:
        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return selected

    calls = []
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(
        fabric,
        "call_llm",
        lambda *args, **kwargs: calls.append((args, kwargs)) or "wrong transport",
    )

    with pytest.raises(LLMRouteError, match="cannot execute the local codex_cli transport"):
        client = get_chat_client(LLMTaskIntent(task_kind="qa"))
        client.chat("qa", {"system": "trusted", "user": "question"})

    assert calls == []


def test_luna_route_provenance_and_embedding_identity_are_separate(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    snapshot = CatalogSnapshot.create(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=now,
        models=(
            CatalogModelDescriptor(
                provider="openai",
                model="gpt-5.6-luna",
                transports=("codex_cli",),
                capabilities=ModelCapabilities(
                    structured_output=True, system_prompt_channel=True
                ),
                reasoning_efforts=("low", "xhigh"),
                release_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            CatalogModelDescriptor(
                provider="openai",
                model="gpt-6-luna",
                transports=("codex_cli",),
                capabilities=ModelCapabilities(
                    structured_output=True, system_prompt_channel=True
                ),
                reasoning_efforts=("low", "xhigh"),
                release_at=now,
            ),
        ),
    )

    class _Remote:
        def catalog(self, _request):
            return SimpleNamespace(snapshot=snapshot)

        def preflight(self, request):
            return PreflightResponse(route=request.route, preflight_status="passed")

        def close(self):
            pass

    class _Router:
        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return LLMRoute(
                provider="openai",
                model="gpt-5.6-luna",
                mode="chat",
                reason="settings",
                transport_id="codex_cli_tailscale",
                reasoning_effort="low",
            )

    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "https://executor.example.ts.net"
    )
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(fabric, "CodexRemoteTransport", lambda **_kwargs: _Remote())
    monkeypatch.setattr(fabric, "_PRODUCT_CATALOG_CACHE", CatalogCache())
    client = get_chat_client(LLMTaskIntent(task_kind="qa"))
    route = client.model_access_route
    assert route is not None

    assert route.model == "gpt-6-luna"
    assert route.transport_id == "codex_cli_tailscale"
    assert route.catalog_snapshot_ref == snapshot.snapshot_ref
    assert route.catalog_snapshot_hash == snapshot.snapshot_hash
    assert route.capability_provenance.source == "catalog_snapshot"

    class _Router:
        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return LLMRoute(
                provider="ollama",
                model="nomic-embed-text:latest",
                mode="embeddings",
                reason="settings",
                embedding_identity=EmbeddingIdentity(
                    provider="ollama", model="nomic-embed-text:latest", dim=768
                ),
            )

    captured: dict[str, str | None] = {}

    def _fake_get_embedding_client(*, resolved_identity=None):
        captured["identity"] = resolved_identity
        return object()

    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(fabric, "get_embedding_client", _fake_get_embedding_client)
    get_embeddings_client(LLMTaskIntent(task_kind="embed"))
    assert captured == {
        "identity": EmbeddingIdentity(
            provider="ollama", model="nomic-embed-text:latest", dim=768
        )
    }


@pytest.mark.parametrize(
    ("remote_error", "expected_error"),
    [
        ("catalog_auth_failed", "catalog_auth_failed"),
        ("catalog_transport_mismatch", "catalog_invalid"),
        ("catalog_response_invalid", "catalog_invalid"),
        (None, "catalog_invalid"),
    ],
)
def test_product_catalog_auth_or_invalid_refresh_never_routes_stale_snapshot(
    monkeypatch, remote_error: str | None, expected_error: str
) -> None:
    now = datetime.now(timezone.utc)
    snapshot = CatalogSnapshot.create(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=now,
        models=(
            CatalogModelDescriptor(
                provider="openai",
                model="gpt-5.6-luna",
                transports=("codex_cli",),
                capabilities=ModelCapabilities(
                    structured_output=True, system_prompt_channel=True
                ),
                reasoning_efforts=("low",),
                release_at=now - timedelta(seconds=1),
            ),
        ),
    )

    class _Router:
        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return LLMRoute(
                provider="openai",
                model="gpt-5.6-luna",
                mode="chat",
                reason="settings",
                transport_id="codex_cli_tailscale",
                reasoning_effort="low",
            )

    class _Remote:
        def __init__(self, **_kwargs) -> None:
            self.catalog_calls = 0

        def catalog(self, _request):
            self.catalog_calls += 1
            if self.catalog_calls > 1:
                if remote_error is None:
                    raise RuntimeError("unexpected catalog adapter failure")
                raise RemoteCatalogError(remote_error)
            return SimpleNamespace(snapshot=snapshot)

        def preflight(self, request):
            return PreflightResponse(route=request.route, preflight_status="passed")

        def close(self) -> None:
            pass

    remote = _Remote()
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "https://executor.example.ts.net"
    )
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(fabric, "CodexRemoteTransport", lambda **_kwargs: remote)
    monkeypatch.setattr(
        fabric,
        "_PRODUCT_CATALOG_CACHE",
        CatalogCache(refresh_ttl=timedelta(microseconds=1)),
    )

    first_client = get_chat_client(LLMTaskIntent(task_kind="qa"))
    assert first_client.model_access_route is not None
    assert first_client.model_access_route.catalog_snapshot_hash == snapshot.snapshot_hash

    with pytest.raises(CatalogError) as error:
        get_chat_client(LLMTaskIntent(task_kind="qa"))

    assert error.value.code == expected_error
    assert remote.catalog_calls == 2


def test_bound_client_keeps_catalog_route_after_cache_refresh(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    older = CatalogModelDescriptor(
        provider="openai",
        model="gpt-5.6-luna",
        transports=("codex_cli",),
        capabilities=ModelCapabilities(structured_output=True, system_prompt_channel=True),
        reasoning_efforts=("low",),
        release_at=now - timedelta(days=1),
    )
    newer = CatalogModelDescriptor(
        provider="openai",
        model="gpt-6-luna",
        transports=("codex_cli",),
        capabilities=ModelCapabilities(structured_output=True, system_prompt_channel=True),
        reasoning_efforts=("low",),
        release_at=now,
    )
    snapshot_a = CatalogSnapshot.create(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=now,
        models=(older,),
    )
    snapshot_b = CatalogSnapshot.create(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=now,
        models=(older, newer),
    )
    state = {"catalog_calls": 0, "preflight": [], "completion": []}

    class _Router:
        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return LLMRoute(
                provider="openai",
                model="gpt-5.6-luna",
                mode="chat",
                reason="settings",
                transport_id="codex_cli_tailscale",
                reasoning_effort="low",
            )

    class _Remote:
        def __init__(self, **_kwargs):
            pass

        def catalog(self, _request):
            state["catalog_calls"] += 1
            return SimpleNamespace(
                snapshot=snapshot_a if state["catalog_calls"] == 1 else snapshot_b
            )

        def preflight(self, request):
            state["preflight"].append(request)
            return PreflightResponse(route=request.route, preflight_status="passed")

        def complete(self, request):
            state["completion"].append(request)
            return CompletionResponse(route=request.route, content="bound answer")

        def close(self):
            pass

    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "https://executor.example.ts.net"
    )
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(fabric, "CodexRemoteTransport", _Remote)
    monkeypatch.setattr(
        fabric,
        "_PRODUCT_CATALOG_CACHE",
        CatalogCache(refresh_ttl=timedelta(microseconds=1)),
    )

    first = get_chat_client(LLMTaskIntent(task_kind="qa"))
    assert first.route.model == "gpt-5.6-luna"
    assert first.model_access_route is not None
    assert first.model_access_route.catalog_snapshot_hash == snapshot_a.snapshot_hash

    second = get_chat_client(LLMTaskIntent(task_kind="qa"))
    assert second.route.model == "gpt-6-luna"
    assert second.model_access_route is not None
    assert second.model_access_route.catalog_snapshot_hash == snapshot_b.snapshot_hash
    assert state["completion"] == []

    assert first.chat("qa", {"system": "", "user": "question"}, max_tokens=32) == "bound answer"
    assert state["completion"][0].route.model == "gpt-5.6-luna"
    assert first.model_access_route.catalog_snapshot_hash == snapshot_a.snapshot_hash
    assert state["catalog_calls"] == 2


def test_explicit_route_obeys_global_enforcement(monkeypatch) -> None:
    enforced = LLMRoute(
        provider="ollama", model="llama3.1:8b", mode="chat", reason="forced"
    )

    class _Router:
        def candidate_routes(self, _intent: LLMTaskIntent) -> list[LLMRoute]:
            return [
                LLMRoute(
                    provider=os.getenv("LLM_FORCE_PROVIDER", "ollama"),
                    model=os.getenv("LLM_FORCE_MODEL", "llama3.1:8b"),
                    mode="chat",
                    reason="forced",
                )
            ]

        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return enforced

    monkeypatch.setenv("LLM_FORCE_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_FORCE_MODEL", "llama3.1:8b")
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    matching = get_chat_client(
        LLMTaskIntent(task_kind="eval"), model_id="llama3.1:8b"
    )
    assert matching.route.provider == "ollama"
    assert matching.route.model == "llama3.1:8b"
    assert matching.model_access_route is not None
    assert matching.model_access_route.transport_id == "ollama_http"

    monkeypatch.setenv("LLM_FORCE_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FORCE_MODEL", "gpt-5.4")
    with pytest.raises(LLMRouteError, match="conflicts with active global route enforcement"):
        get_chat_client(LLMTaskIntent(task_kind="eval"), model_id="llama3.1:8b")


def test_eval_rejects_undeclared_exact_model_before_adapter_io(monkeypatch) -> None:
    monkeypatch.setattr(
        fabric,
        "CodexRemoteTransport",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("adapter I/O")),
    )
    with pytest.raises(LLMRouteError, match="exactly one declared Product chat model"):
        get_chat_client(LLMTaskIntent(task_kind="eval"), model_id="not-registered")


def test_eval_exact_model_binds_declared_transport_without_catalog_promotion(
    monkeypatch,
) -> None:
    state = {"catalog": 0, "preflight": [], "completion": [], "closed": 0}

    class _Remote:
        def __init__(self):
            self.preflight_requests = []

        def catalog(self, _request):
            state["catalog"] += 1
            raise AssertionError("exact eval model must not discover/promote")

        def preflight(self, request):
            self.preflight_requests.append(request)
            state["preflight"].append((self, request))
            return SimpleNamespace(
                response=PreflightResponse(
                    route=request.route, preflight_status="passed"
                ),
                receipt=SimpleNamespace(failure_before_selection="PATH_UNAVAILABLE"),
            )

        def complete_selected_path(self, request, *, receipt):
            state["completion"].append((self, request, receipt))
            return SimpleNamespace(content="remote eval")

        def close(self):
            state["closed"] += 1

    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "https://executor.example.ts.net"
    )
    remotes = []

    def create_remote(**_kwargs):
        remote = _Remote()
        remotes.append(remote)
        return remote

    monkeypatch.setattr(
        fabric,
        "_new_executor_path_router",
        create_remote,
    )

    client = get_chat_client(
        LLMTaskIntent(task_kind="eval"),
        model_id="gpt-5.6-luna",
        adapter_runtime_config=AdapterRuntimeConfig(
            base_url="https://private-eval-provider.example/v1",
            api_key="private-eval-key",
        ),
    )

    assert client.route.model == "gpt-5.6-luna"
    assert client.model_access_route is not None
    assert client.model_access_route.transport_id == "codex_cli_tailscale"
    assert client.model_access_route.catalog_snapshot_hash is None
    assert client.remote_transport is None
    assert client.preflight_transport_observation == {
        "status": "degraded",
        "reason_code": "transport_fallback_used",
    }
    assert state["catalog"] == 0
    assert len(state["preflight"]) == 1
    assert "private-eval-key" not in repr(client)
    assert "private-eval-provider.example" not in repr(client)

    assert client.chat(
        "eval",
        {"system": "trusted", "user": "evaluate this"},
        response_format={"type": "object"},
    ) == "remote eval"

    preflight_remote, preflight_request = state["preflight"][-1]
    completion_remote, request, receipt = state["completion"][0]
    assert preflight_remote is completion_remote
    assert preflight_request.route == request.route
    assert preflight_request.reasoning_effort == request.reasoning_effort
    assert preflight_request.capability_intent == request.capability_intent
    assert preflight_request.capability_intent.structured_output is True
    assert receipt is not None
    assert len(remotes) == 2
    assert state["closed"] == 2


def test_product_trusted_and_user_messages_remain_separate_on_remote_route() -> None:
    access_route = _resolve_product_access_route(
        LLMTaskIntent(task_kind="qa"),
        LLMRoute(
            provider="openai",
            model="gpt-5.4",
            mode="chat",
            reason="settings",
            transport_id="codex_cli_tailscale",
            reasoning_effort="low",
        ),
    )

    class _Remote:
        preflight_request = None
        completion_request = None

        def preflight(self, request):
            self.preflight_request = request

        def complete(self, request):
            self.completion_request = request
            return SimpleNamespace(content="remote answer")

    remote = _Remote()
    client = ChatClient(
        route=LLMRoute.from_model_access_route(
            access_route, mode="chat", reason="settings"
        ),
        model_access_route=access_route,
        remote_transport=remote,
    )

    assert client.chat(
        "qa", {"system": "trusted system", "user": "untrusted question"}
    ) == "remote answer"
    request = remote.completion_request
    assert request.trusted_instructions == "trusted system"
    assert request.user_input == "untrusted question"
    assert request.route.transport_id == "codex_cli"
    assert remote.preflight_request.route == request.route


def test_concurrent_remote_chats_have_exclusive_router_lifetimes(monkeypatch) -> None:
    intent = LLMTaskIntent(task_kind="qa")
    access_route = _resolve_product_access_route(
        intent,
        LLMRoute(
            provider="openai",
            model="gpt-5.4",
            mode="chat",
            reason="settings",
            transport_id="codex_cli_tailscale",
            reasoning_effort="low",
        ),
    )
    barrier = Barrier(2)
    remotes = []

    class _Remote:
        def __init__(self):
            self.preflight_count = 0
            self.completion_count = 0
            self.closed = False

        def preflight(self, _request):
            self.preflight_count += 1
            barrier.wait(timeout=5)
            return SimpleNamespace(receipt=self)

        def complete_selected_path(self, _request, *, receipt):
            assert receipt is self
            self.completion_count += 1
            return SimpleNamespace(content="remote answer")

        def close(self):
            self.closed = True

    def create_remote(**_kwargs):
        remote = _Remote()
        remotes.append(remote)
        return remote

    monkeypatch.setattr(fabric, "_new_executor_path_router", create_remote)
    client = ChatClient(
        route=LLMRoute.from_model_access_route(
            access_route, mode="chat", reason="settings"
        ),
        model_access_route=access_route,
        _intent=intent,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(
            pool.map(
                lambda user_text: client.chat(
                    "qa", {"system": "trusted", "user": user_text}
                ),
                ("question one", "question two"),
            )
        )

    assert answers == ["remote answer", "remote answer"]
    assert len(remotes) == 2
    assert all(remote.preflight_count == 1 for remote in remotes)
    assert all(remote.completion_count == 1 for remote in remotes)
    assert all(remote.closed for remote in remotes)


def test_product_remote_fallback_is_selected_before_one_completion(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    snapshot = CatalogSnapshot.create(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=now,
        models=(
            CatalogModelDescriptor(
                provider="openai",
                model="gpt-5.6-luna",
                transports=("codex_cli",),
                capabilities=ModelCapabilities(
                    structured_output=True, system_prompt_channel=True
                ),
                reasoning_efforts=("high", "low"),
                release_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            CatalogModelDescriptor(
                provider="openai",
                model="gpt-6-luna",
                transports=("codex_cli",),
                capabilities=ModelCapabilities(
                    structured_output=True, system_prompt_channel=True
                ),
                reasoning_efforts=("high", "low"),
                release_at=now,
            ),
        ),
    )
    primary = LLMRoute(
        provider="openai",
        model="gpt-5.6-luna",
        mode="chat",
        reason="settings",
        transport_id="codex_cli_tailscale",
        reasoning_effort="low",
    )
    fallback = LLMRoute(
        provider="ollama",
        model="llama3.1:8b",
        mode="chat",
        reason="fallback",
        degraded=True,
        transport_id="ollama_http_tailscale",
    )

    class _Router:
        def candidate_routes(self, _intent: LLMTaskIntent) -> list[LLMRoute]:
            return [primary, fallback]

        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return primary

    class _Remote:
        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []
            self.completion_requests = []

        def catalog(self, request):
            self.events.append(("catalog", request.transport_id))
            return SimpleNamespace(snapshot=snapshot)

        def preflight(self, request):
            transport_id = request.route.transport_id
            self.events.append(("preflight", transport_id))
            if transport_id == "codex_cli":
                raise RemotePreflightError("session_expired")
            return PreflightResponse(
                route=request.route, preflight_status="passed"
            )

        def complete(self, request):
            self.events.append(("complete", request.route.transport_id))
            self.completion_requests.append(request)
            return CompletionResponse(
                route=request.route, content="remote fallback answer"
            )

        def close(self) -> None:
            self.events.append(("close", ""))

    remote = _Remote()
    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "https://executor.example.ts.net"
    )
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(
        fabric,
        "CodexRemoteTransport",
        lambda **_kwargs: remote,
    )
    monkeypatch.setattr(fabric, "_PRODUCT_CATALOG_CACHE", CatalogCache())

    client = get_chat_client(LLMTaskIntent(task_kind="qa"))

    assert client.model_access_route is not None
    assert client.model_access_route.provider == "ollama"
    assert client.model_access_route.model == "llama3.1:8b"
    assert client.model_access_route.transport_id == "ollama_http_tailscale"
    assert client.model_access_route.preflight_status == "passed"
    assert client.model_access_route.fallback_provenance.used is True
    assert client.model_access_route.fallback_provenance.reason_code == "session_expired"
    assert client.model_access_route.fallback_provenance.source_effective_identity == (
        "openai/gpt-6-luna"
    )
    assert remote.events == [
        ("catalog", "codex_cli"),
        ("preflight", "codex_cli"),
        ("preflight", "ollama_http"),
        ("close", ""),
    ]
    assert client.chat("qa", {"system": "trusted", "user": "question"}) == (
        "remote fallback answer"
    )
    assert remote.events.count(("complete", "ollama_http")) == 1
    assert remote.events[-1:] == [("close", "")]
    assert len(remote.completion_requests) == 1


def test_product_remote_preflight_can_forbid_fallback(monkeypatch) -> None:
    primary = LLMRoute(
        provider="openai",
        model="gpt-6-luna",
        mode="chat",
        reason="settings",
        transport_id="codex_cli_tailscale",
        reasoning_effort="low",
    )
    fallback = LLMRoute(
        provider="ollama",
        model="llama3.1:8b",
        mode="chat",
        reason="fallback",
        degraded=True,
        transport_id="ollama_http_tailscale",
    )

    class _Router:
        def candidate_routes(self, _intent: LLMTaskIntent) -> list[LLMRoute]:
            return [primary, fallback]

        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return primary

    class _Remote:
        def __init__(self) -> None:
            self.preflight_routes: list[str] = []
            self.completion_requests = []

        def preflight(self, request):
            self.preflight_routes.append(request.route.transport_id)
            raise RemotePreflightError("session_expired")

        def complete(self, request):
            self.completion_requests.append(request)
            raise AssertionError("a failed preflight must not dispatch a completion")

        def close(self) -> None:
            return None

    remote = _Remote()
    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "https://executor.example.ts.net"
    )
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(fabric, "CodexRemoteTransport", lambda **_kwargs: remote)

    with pytest.raises(RemotePreflightError) as error:
        get_chat_client_for_route(
            LLMTaskIntent(task_kind="health"),
            selected_route=primary,
            allow_catalog_promotion=False,
            allow_fallback=False,
        )

    assert error.value.code == "session_expired"
    assert remote.preflight_routes == ["codex_cli"]
    assert remote.completion_requests == []


def test_product_remote_fallback_does_not_downgrade_strong_reasoning(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    snapshot = CatalogSnapshot.create(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=now,
        models=(
            CatalogModelDescriptor(
                provider="openai",
                model="gpt-5.6-luna",
                transports=("codex_cli",),
                capabilities=ModelCapabilities(system_prompt_channel=True),
                reasoning_efforts=("high",),
                release_at=now,
            ),
        ),
    )
    primary = LLMRoute(
        provider="openai",
        model="gpt-5.6-luna",
        mode="chat",
        reason="settings",
        transport_id="codex_cli_tailscale",
        reasoning_effort="high",
    )
    fallback = LLMRoute(
        provider="ollama",
        model="llama3.1:8b",
        mode="chat",
        reason="fallback",
        degraded=True,
        transport_id="ollama_http_tailscale",
    )

    class _Router:
        def candidate_routes(self, _intent: LLMTaskIntent) -> list[LLMRoute]:
            return [primary, fallback]

        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return primary

    class _Remote:
        def __init__(self) -> None:
            self.preflight_routes: list[str] = []

        def catalog(self, _request):
            return SimpleNamespace(snapshot=snapshot)

        def preflight(self, request):
            self.preflight_routes.append(request.route.transport_id)
            raise RemotePreflightError("session_expired")

        def close(self) -> None:
            return None

    remote = _Remote()
    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "https://executor.example.ts.net"
    )
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(
        fabric,
        "CodexRemoteTransport",
        lambda **_kwargs: remote,
    )
    monkeypatch.setattr(fabric, "_PRODUCT_CATALOG_CACHE", CatalogCache())

    with pytest.raises(RemotePreflightError) as error:
        get_chat_client(LLMTaskIntent(task_kind="reasoning", risk="high"))

    assert error.value.code == "session_expired"
    assert remote.preflight_routes == ["codex_cli"]


def test_product_output_limit_uses_preflight_approved_ollama_route(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    snapshot = CatalogSnapshot.create(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=now,
        models=(
            CatalogModelDescriptor(
                provider="openai",
                model="gpt-5.6-luna",
                transports=("codex_cli",),
                capabilities=ModelCapabilities(
                    structured_output=True, system_prompt_channel=True
                ),
                reasoning_efforts=("low",),
                release_at=now,
            ),
        ),
    )
    primary = LLMRoute(
        provider="openai",
        model="gpt-5.6-luna",
        mode="chat",
        reason="settings",
        transport_id="codex_cli_tailscale",
        reasoning_effort="low",
    )
    fallback = LLMRoute(
        provider="ollama",
        model="llama3.1:8b",
        mode="chat",
        reason="fallback",
        degraded=True,
        transport_id="ollama_http_tailscale",
    )

    class _Router:
        def candidate_routes(self, _intent: LLMTaskIntent) -> list[LLMRoute]:
            return [primary, fallback]

        def route(self, _intent: LLMTaskIntent) -> LLMRoute:
            return primary

    class _Remote:
        def __init__(self) -> None:
            self.events: list[tuple[str, str, bool | int | None]] = []
            self.completion_requests = []

        def catalog(self, request):
            self.events.append(("catalog", request.transport_id, None))
            return SimpleNamespace(snapshot=snapshot)

        def preflight(self, request):
            self.events.append(
                (
                    "preflight",
                    request.route.transport_id,
                    request.capability_intent.max_output_tokens_required,
                )
            )
            if (
                request.route.transport_id == "codex_cli"
                and request.capability_intent.max_output_tokens_required
            ):
                raise RemotePreflightError("output_token_limit_unavailable")
            return PreflightResponse(
                route=request.route, preflight_status="passed"
            )

        def complete(self, request):
            self.events.append(
                ("complete", request.route.transport_id, request.max_output_tokens)
            )
            self.completion_requests.append(request)
            return CompletionResponse(route=request.route, content="bounded answer")

        def close(self) -> None:
            self.events.append(("close", "", None))

    remote = _Remote()
    monkeypatch.setenv(
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "https://executor.example.ts.net"
    )
    monkeypatch.setattr(fabric, "LLMRouter", _Router)
    monkeypatch.setattr(fabric, "CodexRemoteTransport", lambda **_kwargs: remote)
    monkeypatch.setattr(fabric, "_PRODUCT_CATALOG_CACHE", CatalogCache())

    client = get_chat_client(LLMTaskIntent(task_kind="qa"))
    assert client.route.provider == "openai"
    assert client.chat(
        "qa", {"system": "trusted", "user": "question"}, max_tokens=160
    ) == "bounded answer"

    assert client.route.provider == "ollama"
    assert client.model_access_route is not None
    assert client.model_access_route.fallback_provenance.used is True
    assert client.model_access_route.fallback_provenance.reason_code == (
        "adapter_unavailable"
    )
    assert remote.completion_requests[0].route.transport_id == "ollama_http"
    assert remote.completion_requests[0].max_output_tokens == 160
    assert [event for event in remote.events if event[0] == "complete"] == [
        ("complete", "ollama_http", 160)
    ]
    assert (
        "preflight",
        "codex_cli",
        True,
    ) in remote.events
    assert ("preflight", "ollama_http", True) in remote.events


def test_gpt56_eval_api_admission_preserves_implicit_luna_transport(monkeypatch) -> None:
    intent = LLMTaskIntent(task_kind="eval")
    factory = fabric._adapter_factory()
    implicit = fabric._exact_product_model_route(intent, "gpt-5.6-luna", factory=factory)
    assert implicit.transport_id == "codex_cli_tailscale"
    for tier in ("luna", "terra", "sol"):
        client = get_chat_client(intent, model_id=f"gpt-5.6-{tier}", transport_id="openai_api")
        assert client.route.model == f"gpt-5.6-{tier}"
        assert client.route.transport_id == "openai_api"
        assert client.model_access_route.request.intent.fallback_requirement == "fallback_forbidden"


@pytest.mark.parametrize("task_kind", ["decide", "eval"])
def test_settings_resolved_luna_without_explicit_eval_transport_retains_refusal(monkeypatch, task_kind) -> None:
    from app.settings.models import LLMRoutingSettings, SettingsBundle
    from app.components.llm import router
    for name in ("LLM_FORCE_PROVIDER", "LLM_FORCE_MODEL", "LLM_PROVIDER_ENFORCE", "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    bundle = SettingsBundle(llm_routing=LLMRoutingSettings(tasks={
        task_kind: LLMRoutingSettings.TaskPolicy(
            primary=LLMRoutingSettings.RouteTarget(model_id="openai.chat.gpt_5_6_luna")
        )
    }))
    monkeypatch.setattr(router, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(fabric, "call_llm", lambda *a, **kw: pytest.fail("inference started"))
    selected = router.LLMRouter().route(LLMTaskIntent(task_kind=task_kind))
    assert selected.model == "gpt-5.6-luna"
    assert selected.transport_id is None
    with pytest.raises(LLMRouteError, match="selected transport is not allowed"):
        get_chat_client(LLMTaskIntent(task_kind=task_kind))
