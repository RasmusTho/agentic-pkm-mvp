from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Iterator, Protocol, Sequence

from app.embedding_config import get_embed_dim
from app.index import embeddings as _index_embeddings
from app.llm.embeddings import EMBED_MODEL, get_embed_model, get_embedding_provider
from app.settings.runtime import get_settings_bundle

_MOCK_EMBED_MODEL = "mock-embedding"
_SUPPORTED_EMBED_PROVIDERS = {"mock", "ollama", "openai", "deepseek", "deterministic"}


class EmbeddingClientProtocol(Protocol):
    identity: "EmbeddingIdentity"

    def embed_text(self, text: str) -> list[float]:
        ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_batches(self, texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
        ...


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider: str
    model: str
    dim: int
    normalize: bool = True


@lru_cache(maxsize=1)
def _deterministic_embeddings_module():
    from app.search import embeddings as deterministic_embeddings

    return deterministic_embeddings


class _DeterministicEmbeddingClient:
    def __init__(self, identity: EmbeddingIdentity) -> None:
        self.identity = identity

    def embed_text(self, text: str) -> list[float]:
        module = _deterministic_embeddings_module()
        return module.embed_text(text, dimensions=self.identity.dim, normalize=self.identity.normalize)

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        module = _deterministic_embeddings_module()
        return module.embed_many(list(texts), dimensions=self.identity.dim, normalize=self.identity.normalize)

    def embed_batches(self, texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
        batch: list[str] = []
        for text in texts:
            batch.append(text)
            if len(batch) >= batch_size:
                yield self.embed_texts(batch)
                batch = []
        if batch:
            yield self.embed_texts(batch)


class _ProfiledEmbeddingClient:
    def __init__(self, identity: EmbeddingIdentity) -> None:
        self.identity = identity

    def embed_text(self, text: str) -> list[float]:
        return _index_embeddings.embed_text(
            text,
            provider=self.identity.provider,
            model=self.identity.model,
            dim=self.identity.dim,
            normalize=self.identity.normalize,
        )

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return _index_embeddings.embed_texts(
            list(texts),
            provider=self.identity.provider,
            model=self.identity.model,
            dim=self.identity.dim,
            normalize=self.identity.normalize,
        )

    def embed_batches(self, texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
        yield from _index_embeddings.embed_batches(
            texts,
            provider=self.identity.provider,
            model=self.identity.model,
            dim=self.identity.dim,
            normalize=self.identity.normalize,
            batch_size=batch_size,
        )


def _normalize_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _resolve_embedding_provider_name(value: str | None) -> str:
    normalized = (_normalize_name(value) or "").lower()
    if normalized == "llm":
        return "ollama"
    if normalized == "fake":
        return "mock"
    if not normalized:
        return "mock"
    if normalized not in _SUPPORTED_EMBED_PROVIDERS:
        return "mock"
    return normalized


def _resolve_embedding_model(provider: str, override_model: str | None, configured_model: str | None = None) -> str:
    if override_model:
        return override_model
    if configured_model:
        return configured_model
    if provider == "mock":
        return _MOCK_EMBED_MODEL
    env_model = _normalize_name(os.getenv("EMBED_MODEL")) or _normalize_name(os.getenv("OLLAMA_EMBED_MODEL"))
    if env_model:
        return env_model
    return get_embed_model()


def resolve_embedding_identity(profile: str | None = None, override_model: str | None = None, override_provider: str | None = None) -> EmbeddingIdentity:
    spec = _normalize_name(profile)
    override_model = _normalize_name(override_model)
    override_provider = _normalize_name(override_provider)
    if spec in {"deterministic", "test", "offline"}:
        dim = get_embed_dim()
        return EmbeddingIdentity(provider="deterministic", model="deterministic-hash", dim=dim, normalize=True)

    candidates: list[str] = []
    if spec:
        candidates.append(spec)
    env_profile = _normalize_name(os.getenv("EMBED_PROFILE"))
    if env_profile in {"deterministic", "test", "offline"} and (spec in {None, "default"}):
        dim = get_embed_dim()
        return EmbeddingIdentity(provider="deterministic", model="deterministic-hash", dim=dim, normalize=True)
    if env_profile:
        candidates.append(env_profile)
    bundle = None
    try:
        bundle = get_settings_bundle()
    except Exception:
        bundle = None
    default_name = None
    profiles_map = {}
    if bundle is not None:
        try:
            profiles = bundle.embedding_profiles
        except AttributeError:
            profiles = None
        if profiles is not None:
            profiles_map = {key.strip().lower(): cfg for key, cfg in profiles.profiles.items()}
            default_name = _normalize_name(profiles.default_profile)
        global_profile = _normalize_name(getattr(bundle.global_, "profile", None))
        if global_profile:
            candidates.append(global_profile)
    if default_name:
        candidates.append(default_name)
    candidates.append("default")

    seen: set[str] = set()
    for name in candidates:
        if not name:
            continue
        low = name.strip().lower()
        if low in seen:
            continue
        seen.add(low)
        cfg = profiles_map.get(low)
        if not cfg:
            continue
        provider = _resolve_embedding_provider_name(override_provider or cfg.provider or get_embedding_provider())
        model = _resolve_embedding_model(provider, override_model, cfg.model)
        dim = cfg.dim or get_embed_dim()
        normalize = cfg.normalize if cfg.normalize is not None else True
        return EmbeddingIdentity(provider=provider, model=model, dim=dim, normalize=normalize)

    provider = _resolve_embedding_provider_name(override_provider or get_embedding_provider())
    model = _resolve_embedding_model(provider, override_model)
    dim = get_embed_dim()
    return EmbeddingIdentity(provider=provider, model=model, dim=dim, normalize=True)


def get_embedding_client(profile: str = "default", override_model: str | None = None, override_provider: str | None = None) -> EmbeddingClientProtocol:
    identity = resolve_embedding_identity(profile=profile, override_model=override_model, override_provider=override_provider)
    if identity.provider == "deterministic":
        return _DeterministicEmbeddingClient(identity)
    return _ProfiledEmbeddingClient(identity)


def get_embedding_identity(
    client: EmbeddingClientProtocol | None = None,
    *,
    profile: str = "default",
    override_model: str | None = None,
) -> EmbeddingIdentity:
    if client is not None and getattr(client, "identity", None) is not None:
        return client.identity
    return resolve_embedding_identity(profile=profile, override_model=override_model, override_provider=None)


def describe_embedding(text: str, *, profile: str = "default", override_model: str | None = None, override_provider: str | None = None) -> tuple[EmbeddingIdentity, list[float]]:
    client = get_embedding_client(profile=profile, override_model=override_model, override_provider=override_provider)
    vector = client.embed_text(text)
    identity = client.identity
    return identity, vector


__all__ = [
    "EmbeddingClientProtocol",
    "EmbeddingIdentity",
    "get_embedding_client",
    "get_embedding_identity",
    "describe_embedding",
    "resolve_embedding_identity",
    "EMBED_MODEL",
]
