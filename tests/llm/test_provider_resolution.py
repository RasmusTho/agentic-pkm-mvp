from __future__ import annotations

from app.components.embeddings import resolve_embedding_identity
from app.config import llm as llm_config
from app.llm import adapter, embeddings


def test_runtime_helpers_follow_provider_resolution_without_hidden_ollama_default(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    assert adapter._prov() == "mock"
    assert embeddings.get_embedding_provider() == "mock"


def test_embedding_identity_uses_mock_model_without_embed_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    identity = resolve_embedding_identity()

    assert identity.provider == "mock"
    assert identity.model == "mock-embedding"
