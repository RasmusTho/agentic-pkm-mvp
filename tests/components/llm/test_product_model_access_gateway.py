from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import app.components.retrieval as retrieval
import app.components.llm.fabric as fabric
import app.model_access.codex_remote_transport as remote_transport_module
import app.stores as stores
from app.components.embeddings import EmbeddingIdentity
from app.components.llm.router import LLMRouteError, LLMRouter, LLMTaskIntent
from app.index.embedding_identity import IndexEmbeddingIdentityMismatch
from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.codex_executor_service import create_codex_executor_app
from app.model_access.codex_remote_transport import CodexRemoteTransport
from app.model_access.executor_network_policy import (
    EXECUTOR_NETWORK_PROFILE,
    ExecutorNetworkPathRouter,
)
from app.model_access.provider_api import ProductProviderApiAdapter
from app.model_access.remote_contract import (
    CompletionResponse,
    CompletionRouteIdentity,
    EmbeddingRouteIdentity,
    PreflightResponse,
    ProductEmbeddingResponse,
    ProductPreflightRequest,
)
from app.settings.models import InstanceSettings, LLMRoutingSettings, SettingsBundle

pytestmark = pytest.mark.not_pg

_GEMINI_KEY = "synthetic-gemini-key-never-return"
_SNAPSHOT_HASH = "sha256:" + "a" * 64


class _NoCodex:
    def execute(self, **_kwargs: Any) -> Any:
        raise AssertionError("embedding must use the provider API adapter")

    def preflight(self, **_kwargs: Any) -> Any:
        raise AssertionError("embedding must not preflight Codex CLI")

    def list_catalog_models(self) -> list[dict[str, Any]]:
        raise AssertionError("embedding must not use the Codex model catalog")


class _ProductChatPath:
    def __init__(self) -> None:
        self.preflight_requests: list[ProductPreflightRequest] = []
        self.completion_requests = []
        self._routes: dict[str, CompletionRouteIdentity] = {}
        self.closed = False

    def preflight_product(self, request: ProductPreflightRequest) -> Any:
        self.preflight_requests.append(request)
        transport_id = "codex_cli" if request.provider == "openai" else "ollama_http"
        route = CompletionRouteIdentity(
            provider=request.provider,
            model=request.model,
            transport_id=transport_id,
            catalog_snapshot_ref=f"catalog.{request.provider}_{transport_id}",
            catalog_snapshot_hash=_SNAPSHOT_HASH,
        )
        receipt = SimpleNamespace(
            receipt_id=f"preflight-{len(self.preflight_requests)}",
            failure_before_selection=None,
        )
        self._routes[receipt.receipt_id] = route
        return SimpleNamespace(
            response=PreflightResponse(route=route, preflight_status="passed"),
            receipt=receipt,
        )

    def discard_product_path_receipt(self, receipt: Any) -> None:
        if receipt is not None:
            self._routes.pop(receipt.receipt_id, None)

    def complete_product_selected_path(self, request: Any, *, receipt: Any) -> CompletionResponse:
        self.completion_requests.append(request)
        route = self._routes.pop(receipt.receipt_id)
        return CompletionResponse(route=route, content="answer from Mac portal")

    def close(self) -> None:
        self.closed = True


def _declared_factory() -> ModelAccessAdapterFactory:
    root = Path(__file__).resolve().parents[3]
    return ModelAccessAdapterFactory.from_declared_sources(
        adapters_path=root / "docs/settings/models/adapters.yaml",
        provider_census_path=root / "docs/settings/models/providers.yaml",
    )


def _gemini_adapter(transport: httpx.BaseTransport) -> ProductProviderApiAdapter:
    return ProductProviderApiAdapter(
        adapter_factory=_declared_factory(),
        credential_resolver=lambda name: (
            _GEMINI_KEY if name == "GEMINI_API_KEY" else None
        ),
        transport=transport,
    )


def test_product_chat_route_uses_remote_gateway_and_clone_profile(
    monkeypatch: pytest.MonkeyPatch, clean_llm_env: pytest.MonkeyPatch
) -> None:
    clean_llm_env.delenv("LLM_FORCE_PROVIDER", raising=False)
    clean_llm_env.delenv("LLM_FORCE_MODEL", raising=False)
    clean_llm_env.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    active_router: LLMRouter | None = None
    remotes: list[_ProductChatPath] = []
    direct_calls: list[Any] = []

    def create_remote(**_kwargs: Any) -> _ProductChatPath:
        remote = _ProductChatPath()
        remotes.append(remote)
        return remote

    monkeypatch.setattr(fabric, "_new_executor_path_router", create_remote)
    monkeypatch.setattr(fabric, "LLMRouter", lambda: active_router)
    monkeypatch.setattr(
        fabric,
        "call_llm",
        lambda *args, **kwargs: direct_calls.append((args, kwargs))
        or "unexpected local provider call",
    )

    observed: list[tuple[str, str]] = []
    clones = (
        ("ygg-primary", "openai.chat.gpt_6_luna"),
        ("work-satellite", "ollama.chat.llama3_1_8b"),
    )
    for profile_id, model_id in clones:
        active_router = LLMRouter(
            settings=SettingsBundle(
                instance=InstanceSettings(llm_routing_profile=profile_id),
                llm_routing=LLMRoutingSettings(
                    profiles={
                        profile_id: LLMRoutingSettings.RoutingProfile(
                            default_chat=LLMRoutingSettings.RouteTarget(
                                model_id=model_id
                            )
                        )
                    }
                ),
            )
        )
        intent = LLMTaskIntent(task_kind="qa")
        selected = active_router.route(intent)
        client = fabric.get_chat_client_for_route(
            intent,
            selected_route=selected,
            allow_catalog_promotion=False,
            allow_fallback=False,
        )

        assert client.chat("qa", {"system": "trusted", "user": "question"}) == (
            "answer from Mac portal"
        )
        assert client.model_access_route is not None
        assert client.model_access_route.execution_host_profile == EXECUTOR_NETWORK_PROFILE
        observed.append((client.route.provider, client.route.model))

    assert observed == [
        ("openai", "gpt-6-luna"),
        ("ollama", "llama3.1:8b"),
    ]
    assert direct_calls == []
    completions = [request for remote in remotes for request in remote.completion_requests]
    assert [(request.provider, request.model) for request in completions] == observed
    assert all("transport_id" not in request.model_dump() for request in completions)
    assert all(remote.closed for remote in remotes)


def test_embedding_route_uses_gateway_and_preserves_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, clean_llm_env: pytest.MonkeyPatch
) -> None:
    clean_llm_env.delenv("LLM_FORCE_PROVIDER", raising=False)
    clean_llm_env.delenv("LLM_FORCE_MODEL", raising=False)
    clean_llm_env.delenv("LLM_PROVIDER_ENFORCE", raising=False)

    provider_requests: list[httpx.Request] = []

    def provider_handler(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(
            200,
            json={"embedding": {"values": [0.25] * 768}},
            request=request,
        )

    server_app = create_codex_executor_app(
        codex_executor=_NoCodex(),  # type: ignore[arg-type]
        provider_api_adapter=_gemini_adapter(httpx.MockTransport(provider_handler)),
        adapter_factory=_declared_factory(),
    )
    server_client = TestClient(server_app, client=("127.0.0.1", 12345))

    def portal_handler(request: httpx.Request) -> httpx.Response:
        response = server_client.request(
            request.method,
            request.url.path,
            content=request.content,
            headers={
                key: value
                for key, value in request.headers.items()
                if key.lower() in {"content-type", "accept"}
            },
        )
        return httpx.Response(
            response.status_code,
            headers=dict(response.headers),
            content=response.content,
            request=request,
        )

    monkeypatch.setattr(
        remote_transport_module,
        "_private_ingress_ssl_context",
        lambda **_kwargs: __import__("ssl").create_default_context(),
    )
    ca_bundle = tmp_path / "ca.pem"
    certificate = tmp_path / "client.pem"
    private_key = tmp_path / "client-key.pem"
    for path in (ca_bundle, certificate, private_key):
        path.write_text("test-only TLS fixture", encoding="utf-8")
    host_environment = {
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT": "https://10.42.42.10:8443",
        "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE": str(ca_bundle),
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT": str(certificate),
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY": str(private_key),
    }

    def make_portal(**kwargs: Any) -> ExecutorNetworkPathRouter:
        return ExecutorNetworkPathRouter(
            **kwargs,
            environment=host_environment,
            transport_factory=lambda path: CodexRemoteTransport(
                endpoint=path.endpoint,
                path_adapter=path.adapter,
                tls_verify=path.tls_verify,
                client_certificate=path.client_certificate,
                transport=httpx.MockTransport(portal_handler),
            ),
        )

    monkeypatch.setattr(fabric, "_new_executor_path_router", make_portal)
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle",
        lambda: SettingsBundle(
            instance=InstanceSettings(llm_routing_profile="work-satellite"),
            llm_routing=LLMRoutingSettings(
                profiles={
                    "work-satellite": LLMRoutingSettings.RoutingProfile(
                        default_embedding=LLMRoutingSettings.RouteTarget(
                            model_id="gemini.embed.gemini_embedding_001"
                        )
                    )
                }
            ),
        ),
    )

    with server_client:
        client = fabric.get_embeddings_client(
            LLMTaskIntent(task_kind="embed", strict_identity_required=True)
        )
        try:
            vector = client.embed_text("gateway integration fixture")
            route_provenance = client.route_provenance
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    assert client.identity.provider == "gemini"
    assert client.identity.model == "gemini-embedding-001"
    assert client.identity.dim == 768
    assert len(vector) == client.identity.dim
    assert route_provenance is not None
    assert route_provenance["transport_id"] == "gemini_api"
    assert route_provenance["execution_host"] == EXECUTOR_NETWORK_PROFILE
    assert route_provenance["selected_path_profile"] == "ygg_vlan_primary"
    assert route_provenance["catalog_snapshot_ref"] == "catalog.gemini_gemini_api"
    assert route_provenance["catalog_snapshot_hash"].startswith("sha256:")
    assert len(provider_requests) == 1
    assert provider_requests[0].headers["x-goog-api-key"] == _GEMINI_KEY
    assert _GEMINI_KEY not in repr(route_provenance)


def test_bge_m3_profile_creates_mac_portal_embedding_client(
    monkeypatch: pytest.MonkeyPatch, clean_llm_env: pytest.MonkeyPatch
) -> None:
    clean_llm_env.delenv("EMBED_MODEL", raising=False)
    clean_llm_env.delenv("EMBED_PROVIDER", raising=False)
    clean_llm_env.delenv("EMBED_PRIMARY_PROVIDER", raising=False)
    clean_llm_env.delenv("EMBED_PROFILE", raising=False)
    bundle = SettingsBundle()
    monkeypatch.setattr(fabric, "get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(
        "app.components.embeddings.legacy.get_settings_bundle", lambda: bundle
    )

    requests: list[Any] = []
    closed: list[bool] = []

    class _Portal:
        def embed_product(self, request: Any) -> Any:
            requests.append(request)
            response = ProductEmbeddingResponse(
                route=EmbeddingRouteIdentity(
                    provider="ollama",
                    model="bge-m3:latest",
                    transport_id="ollama_http",
                    catalog_snapshot_ref="catalog.ollama_ollama_http",
                    catalog_snapshot_hash=_SNAPSHOT_HASH,
                ),
                dimensions=request.dimensions,
                vector=tuple([0.125] * request.dimensions),
            )
            return SimpleNamespace(
                response=response,
                selected_path_profile="ygg_vlan_primary",
            )

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(fabric, "_new_executor_path_router", lambda **_kwargs: _Portal())
    monkeypatch.setattr(
        fabric,
        "get_embedding_client",
        lambda **_kwargs: pytest.fail("BGE Product profile invoked a local embedding client"),
    )

    client = fabric.get_product_embedding_client(profile="bge-m3")
    try:
        vector = client.embed_text("profile-bound Mac portal embedding")
        provenance = client.route_provenance
    finally:
        client.close()

    assert client.identity.provider == "ollama"
    assert client.identity.model == "bge-m3:latest"
    assert client.identity.dim == 1024
    assert len(vector) == 1024
    assert len(requests) == 1
    assert requests[0].model == "bge-m3:latest"
    assert provenance is not None
    assert provenance["transport_id"] == "ollama_http"
    assert provenance["execution_host"] == EXECUTOR_NETWORK_PROFILE
    assert closed == [True]


def test_retrieval_and_indexer_embedding_entrypoints_use_product_portal(
    monkeypatch: pytest.MonkeyPatch, clean_llm_env: pytest.MonkeyPatch
) -> None:
    clean_llm_env.delenv("LLM_FORCE_PROVIDER", raising=False)
    clean_llm_env.delenv("LLM_FORCE_MODEL", raising=False)
    clean_llm_env.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle",
        lambda: SettingsBundle(
            instance=InstanceSettings(llm_routing_profile="work-satellite"),
            llm_routing=LLMRoutingSettings(
                profiles={
                    "work-satellite": LLMRoutingSettings.RoutingProfile(
                        default_embedding=LLMRoutingSettings.RouteTarget(
                            model_id="gemini.embed.gemini_embedding_001"
                        )
                    )
                }
            ),
        ),
    )

    requests: list[Any] = []
    closed: list[bool] = []

    class _Portal:
        def embed_product(self, request: Any) -> Any:
            requests.append(request)
            response = ProductEmbeddingResponse(
                route=EmbeddingRouteIdentity(
                    provider="gemini",
                    model="gemini-embedding-001",
                    transport_id="gemini_api",
                    catalog_snapshot_ref="catalog.gemini_gemini_api",
                    catalog_snapshot_hash=_SNAPSHOT_HASH,
                ),
                dimensions=request.dimensions,
                vector=tuple([0.25] * request.dimensions),
            )
            return SimpleNamespace(
                response=response,
                selected_path_profile="ygg_vlan_primary",
            )

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(fabric, "_new_executor_path_router", lambda **_kwargs: _Portal())
    monkeypatch.setattr(
        fabric,
        "get_embedding_client",
        lambda **_kwargs: pytest.fail("Product path called the legacy local provider"),
    )

    from app.components.retrieval import embed_query
    from app.services.indexer import llm_embed_text

    query_vector, query_identity = embed_query("retrieval uses the selected satellite model")
    indexer_client = fabric.get_product_embedding_client()
    try:
        indexed_vector = llm_embed_text(
            text="indexing uses the selected satellite model",
            client=indexer_client,
        )
    finally:
        indexer_client.close()

    assert query_identity.provider == "gemini"
    assert query_identity.model == "gemini-embedding-001"
    assert query_identity.dim == 768
    assert len(query_vector) == len(indexed_vector) == 768
    assert [(request.provider, request.model) for request in requests] == [
        ("gemini", "gemini-embedding-001"),
        ("gemini", "gemini-embedding-001"),
    ]
    assert closed == [True, True]


def test_indexer_ingest_entrypoint_embeds_through_product_portal(
    monkeypatch: pytest.MonkeyPatch, clean_llm_env: pytest.MonkeyPatch
) -> None:
    from app.services import indexer

    clean_llm_env.delenv("LLM_FORCE_PROVIDER", raising=False)
    clean_llm_env.delenv("LLM_FORCE_MODEL", raising=False)
    clean_llm_env.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    clean_llm_env.delenv("EMBED_FALLBACK_PROVIDER", raising=False)
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle",
        lambda: SettingsBundle(
            instance=InstanceSettings(llm_routing_profile="work-satellite"),
            llm_routing=LLMRoutingSettings(
                profiles={
                    "work-satellite": LLMRoutingSettings.RoutingProfile(
                        default_embedding=LLMRoutingSettings.RouteTarget(
                            model_id="gemini.embed.gemini_embedding_001"
                        )
                    )
                }
            ),
        ),
    )

    requests: list[Any] = []
    closed: list[bool] = []
    upserts: list[dict[str, Any]] = []
    embedded_events: list[dict[str, Any]] = []

    class _Portal:
        def embed_product(self, request: Any) -> Any:
            requests.append(request)
            response = ProductEmbeddingResponse(
                route=EmbeddingRouteIdentity(
                    provider="gemini",
                    model="gemini-embedding-001",
                    transport_id="gemini_api",
                    catalog_snapshot_ref="catalog.gemini_gemini_api",
                    catalog_snapshot_hash=_SNAPSHOT_HASH,
                ),
                dimensions=request.dimensions,
                vector=tuple([0.25] * request.dimensions),
            )
            return SimpleNamespace(
                response=response,
                selected_path_profile="ygg_vlan_primary",
            )

        def close(self) -> None:
            closed.append(True)

    class _Store:
        def get_object(self, _object_id: str) -> None:
            return None

        def save_object(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _Index:
        def purge_vectors(self, *_args: Any, **_kwargs: Any) -> int:
            return 0

        def upsert(self, *_args: Any, **kwargs: Any) -> None:
            upserts.append(kwargs)

    monkeypatch.setattr(fabric, "_new_executor_path_router", lambda **_kwargs: _Portal())
    monkeypatch.setattr(indexer, "ObjectStore", _Store)
    monkeypatch.setattr(indexer, "resolve_canonical_object_id", lambda value: value)
    monkeypatch.setattr(indexer, "get_vector_index", _Index)
    monkeypatch.setattr(indexer, "emit_index_object_embedded", lambda **kwargs: embedded_events.append(kwargs))
    monkeypatch.setattr(indexer, "emit_index_embedding_failed", lambda **_kwargs: pytest.fail("portal embedding failed"))
    monkeypatch.setattr(
        fabric,
        "get_embedding_client",
        lambda **_kwargs: pytest.fail("Product indexer called the legacy local provider"),
    )

    indexer.handle_ingest_object_created(
        {
            "uuid": "33333333-3333-3333-3333-333333333333",
            "content": "portal-backed indexer fixture",
            "kind": "note",
            "source_ref": "vault/portal-backed.md",
            "payload": {},
        }
    )

    assert len(requests) == 1
    assert (requests[0].provider, requests[0].model, requests[0].dimensions) == (
        "gemini",
        "gemini-embedding-001",
        768,
    )
    assert len(upserts) == len(embedded_events) == 1
    assert upserts[0]["identity"].provider == "gemini"
    assert upserts[0]["identity"].model == "gemini-embedding-001"
    assert embedded_events[0]["provider"] == "gemini"
    assert closed == [True]


def test_query_identity_mismatch_fails_before_embedding_dispatch(monkeypatch) -> None:
    requested = EmbeddingIdentity(
        provider="gemini", model="gemini-embedding-001", dim=768
    )
    stored = EmbeddingIdentity(
        provider="ollama", model="nomic-embed-text", dim=768
    )
    dispatches: list[str] = []
    closed: list[bool] = []

    class _Client:
        identity = requested

        def embed_text(self, _text: str) -> list[float]:
            dispatches.append("embed")
            raise AssertionError("identity mismatch must fail before embedding")

        def close(self) -> None:
            closed.append(True)

    class _Index:
        def get_identity(self) -> EmbeddingIdentity:
            return stored

    monkeypatch.setattr(retrieval, "_embedding_client_for_profile", lambda _profile: _Client())
    monkeypatch.setattr(stores, "get_vector_index", lambda: _Index())

    with pytest.raises(IndexEmbeddingIdentityMismatch, match="index rebuild"):
        retrieval.embed_query("same dimensions, different embedding space", profile="work-satellite")

    assert dispatches == []
    assert closed == [True]


def test_indeterminate_embedding_outbox_delivery_is_terminal_after_host_inference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    clean_llm_env: pytest.MonkeyPatch,
) -> None:
    import ssl

    from app.indexer import consumer
    from app.llm import fallback_orchestrator

    clean_llm_env.delenv("LLM_FORCE_PROVIDER", raising=False)
    clean_llm_env.delenv("LLM_FORCE_MODEL", raising=False)
    clean_llm_env.delenv("LLM_PROVIDER", raising=False)
    clean_llm_env.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    clean_llm_env.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle",
        lambda: SettingsBundle(
            instance=InstanceSettings(llm_routing_profile="work-satellite"),
            llm_routing=LLMRoutingSettings(
                profiles={
                    "work-satellite": LLMRoutingSettings.RoutingProfile(
                        default_embedding=LLMRoutingSettings.RouteTarget(
                            model_id="gemini.embed.gemini_embedding_001"
                        )
                    )
                }
            ),
        ),
    )

    provider_requests: list[httpx.Request] = []
    portal_requests: list[httpx.Request] = []
    failed_events: list[dict[str, Any]] = []
    created_events: list[dict[str, Any]] = []
    upserts: list[dict[str, Any]] = []

    def provider_handler(request: httpx.Request) -> httpx.Response:
        provider_requests.append(request)
        return httpx.Response(
            200,
            json={"embedding": {"values": [0.25] * 768}},
            request=request,
        )

    server_app = create_codex_executor_app(
        codex_executor=_NoCodex(),  # type: ignore[arg-type]
        provider_api_adapter=_gemini_adapter(httpx.MockTransport(provider_handler)),
        adapter_factory=_declared_factory(),
    )
    server_client = TestClient(server_app, client=("127.0.0.1", 12345))

    def lose_response_after_host_inference(request: httpx.Request) -> httpx.Response:
        portal_requests.append(request)
        response = server_client.request(
            request.method,
            request.url.path,
            content=request.content,
            headers={
                key: value
                for key, value in request.headers.items()
                if key.lower() in {"content-type", "accept"}
            },
        )
        assert response.status_code == 200
        raise httpx.ReadTimeout("simulated response loss after Mac provider inference")

    monkeypatch.setattr(
        remote_transport_module,
        "_private_ingress_ssl_context",
        lambda **_kwargs: ssl.create_default_context(),
    )
    ca_bundle = tmp_path / "ca.pem"
    certificate = tmp_path / "client.pem"
    private_key = tmp_path / "client-key.pem"
    for path in (ca_bundle, certificate, private_key):
        path.write_text("test-only TLS fixture", encoding="utf-8")
    host_environment = {
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT": "https://10.42.42.10:8443",
        "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE": str(ca_bundle),
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT": str(certificate),
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY": str(private_key),
    }

    def make_portal(**kwargs: Any) -> ExecutorNetworkPathRouter:
        return ExecutorNetworkPathRouter(
            **kwargs,
            environment=host_environment,
            transport_factory=lambda path: CodexRemoteTransport(
                endpoint=path.endpoint,
                path_adapter=path.adapter,
                tls_verify=path.tls_verify,
                client_certificate=path.client_certificate,
                transport=httpx.MockTransport(lose_response_after_host_inference),
            ),
        )

    monkeypatch.setattr(fabric, "_new_executor_path_router", make_portal)
    monkeypatch.setattr(
        fallback_orchestrator,
        "_resolve_fallback_identity",
        lambda _provider: pytest.fail("indeterminate embedding must not resolve a fallback"),
    )
    monkeypatch.setattr(
        fallback_orchestrator,
        "get_product_embedding_client_for_identity",
        lambda _identity: pytest.fail("indeterminate embedding must not call a fallback model"),
    )

    class _Store:
        def get_object(self, _object_id: str, *, strict_backend: bool) -> Any:
            assert strict_backend is True
            return SimpleNamespace(
                uuid="44444444-4444-4444-4444-444444444444",
                kind="note",
                payload={"content": "the host executes this exactly once"},
                source_ref="vault/indeterminate.md",
            )

    class _Index:
        def purge_vectors(self, *_args: Any, **_kwargs: Any) -> int:
            return 0

        def upsert(self, *_args: Any, **kwargs: Any) -> None:
            upserts.append(kwargs)

    monkeypatch.setattr(consumer, "ObjectStore", _Store)
    monkeypatch.setattr(consumer, "get_vector_index", _Index)
    monkeypatch.setattr(
        consumer.outbox_events,
        "emit_index_embedding_failed",
        lambda **kwargs: failed_events.append(kwargs),
    )
    monkeypatch.setattr(
        consumer.outbox_events,
        "emit_index_embedding_created",
        lambda **kwargs: created_events.append(kwargs),
    )

    with server_client:
        consumer.process_event(
            {
                "event": consumer.outbox_events.INDEX_EMBEDDING_REQUESTED,
                "payload": {"object_id": "44444444-4444-4444-4444-444444444444"},
            }
        )

    assert len(portal_requests) == len(provider_requests) == 1
    assert portal_requests[0].url.path == "/v1/product/embed"
    assert upserts == []
    assert created_events == []
    assert len(failed_events) == 1
    assert failed_events[0]["provider"] == "gemini"
    assert failed_events[0]["model"] == "gemini-embedding-001"


def test_invalid_route_fails_before_provider_dispatch(
    monkeypatch: pytest.MonkeyPatch, clean_llm_env: pytest.MonkeyPatch
) -> None:
    clean_llm_env.delenv("LLM_FORCE_PROVIDER", raising=False)
    clean_llm_env.delenv("LLM_FORCE_MODEL", raising=False)
    clean_llm_env.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    path_router_calls: list[Any] = []
    provider_calls: list[Any] = []

    monkeypatch.setattr(
        fabric,
        "_new_executor_path_router",
        lambda **kwargs: path_router_calls.append(kwargs),
    )
    monkeypatch.setattr(
        fabric,
        "get_embedding_client",
        lambda **kwargs: provider_calls.append(kwargs),
    )
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle",
        lambda: SettingsBundle(
            instance=InstanceSettings(llm_routing_profile="unknown-satellite-profile")
        ),
    )

    with pytest.raises(LLMRouteError, match="Unknown Product routing profile"):
        fabric.get_embeddings_client(
            LLMTaskIntent(task_kind="embed", strict_identity_required=True)
        )

    assert path_router_calls == []
    assert provider_calls == []
