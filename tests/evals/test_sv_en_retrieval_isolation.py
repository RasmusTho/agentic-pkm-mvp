"""Deterministic rollback proof for live evaluation acquisition."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.components import retrieval
from app.llm import embeddings
from app.model_access.executor_network_policy import ExecutorNetworkConfigurationError
from app.retrieval import hybrid, tuning
from tests.evals import sv_en_retrieval as evaluation

_ENV_KEYS = (
    "EMBED_PRIMARY_PROVIDER", "EMBED_MODEL", "OLLAMA_EMBED_MODEL", "EMBED_DIM",
    "RETRIEVAL_FUSION", "OLLAMA_HOST", "ASK_DOMAIN_SCOPE",
)


@pytest.fixture
def isolated_state(monkeypatch):
    store = hybrid.get_store()
    prior = store.all()
    store.set_documents([{
        "doc_id": "prior", "text": "preexisting document", "language": "sv",
        "source_ref": "fixture://prior", "payload": {"title": "Preserve me"},
        "embedding": [0.25, 0.75],
    }])
    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "4")
    monkeypatch.setenv("RETRIEVAL_FUSION", "rrf")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    tuning.reset_retrieval_tuning_cache()
    docs = store.all()
    env = {key: os.environ.get(key) for key in _ENV_KEYS}
    monkeypatch.setattr(evaluation, "ollama_base_url", lambda: "http://unused.invalid")
    yield store, docs, env
    store.set_documents([vars(doc) for doc in prior])
    tuning.reset_retrieval_tuning_cache()


def _assert_restored(state):
    store, docs, env = state
    assert {key: os.environ.get(key) for key in _ENV_KEYS} == env
    assert store.all() == docs
    assert tuning.get_retrieval_tuning().fusion == "rrf"


@pytest.mark.parametrize("failure_stage", ["tuning", "embedding", "corpus"])
@pytest.mark.parametrize("interrupted", [False, True])
def test_failed_entry_restores_process_state(monkeypatch, isolated_state, failure_stage, interrupted):
    failure = KeyboardInterrupt() if interrupted else ExecutorNetworkConfigurationError("path_configuration_missing")

    def fail(*args, **kwargs):
        if failure_stage == "corpus":
            isolated_state[0].set_documents([])
        raise failure

    if failure_stage == "tuning":
        with monkeypatch.context() as scoped:
            scoped.setattr(tuning, "get_retrieval_tuning", fail)
            with pytest.raises(type(failure)) as caught:
                with evaluation.IdentityRun("nomic", "linear"):
                    pytest.fail("failed entry must not execute the body")
    else:
        if failure_stage == "embedding":
            monkeypatch.setattr(retrieval, "embed_docs", fail)
        else:
            monkeypatch.setattr(retrieval, "embed_docs", _fake_embed)
            monkeypatch.setattr(evaluation, "_load_corpus_into_store", fail)
        with pytest.raises(type(failure)) as caught:
            with evaluation.IdentityRun("nomic", "linear"):
                pytest.fail("failed entry must not execute the body")
    assert caught.value is failure
    _assert_restored(isolated_state)


def _fake_embed(texts):
    spec = evaluation.IDENTITIES["nomic"]
    return [[0.0] * int(spec["dim"]) for _ in texts], SimpleNamespace(
        provider="ollama", model=spec["model"], dim=spec["dim"]
    )


@pytest.mark.parametrize("body_fails", [False, True])
def test_context_exit_restores_process_state(monkeypatch, isolated_state, body_fails):
    monkeypatch.setattr(retrieval, "embed_docs", _fake_embed)
    failure = RuntimeError("body failed")
    try:
        with evaluation.IdentityRun("nomic", "linear"):
            assert os.environ["EMBED_PRIMARY_PROVIDER"] == "ollama"
            assert isolated_state[0].all() != isolated_state[1]
            if body_fails:
                raise failure
    except RuntimeError as caught:
        assert body_fails and caught is failure
    _assert_restored(isolated_state)


def test_failed_entry_does_not_change_downstream_embedding_identity(monkeypatch, isolated_state):
    failure = ExecutorNetworkConfigurationError("path_configuration_missing")

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(retrieval, "embed_docs", fail)
    with pytest.raises(ExecutorNetworkConfigurationError):
        with evaluation.IdentityRun("nomic", "linear"):
            pass
    assert embeddings.get_primary_provider() == "mock"
    assert len(embeddings.embed_text("downstream", normalize=False)) == 4
