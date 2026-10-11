"""Deterministic rollback proof for live evaluation acquisition."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.components import retrieval
from app.components.llm.router import LLMRouter
from app.llm import embeddings
from app.model_access.executor_network_policy import ExecutorNetworkConfigurationError
from app.retrieval import hybrid, tuning
from tests.evals import sv_en_retrieval as evaluation

_ACTUAL_PRODUCT_ROUTE = LLMRouter.route

_ENV_KEYS = (
    "EMBED_PRIMARY_PROVIDER", "EMBED_MODEL", "OLLAMA_EMBED_MODEL", "EMBED_DIM",
    "RETRIEVAL_FUSION", "OLLAMA_HOST", "ASK_DOMAIN_SCOPE",
    "LLM_FORCE_PROVIDER", "LLM_FORCE_MODEL",
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


def test_actual_product_embedding_entry_restores_state(monkeypatch, isolated_state):
    """Keep embed_docs and its Product facade; fail at client acquisition below them."""
    from app.components.llm import fabric

    original_embed_docs = retrieval.embed_docs
    calls = []
    failure = ExecutorNetworkConfigurationError("path_configuration_missing")

    def fail_client(identity, *, router):
        calls.append((identity, router))
        raise failure

    monkeypatch.setattr(fabric, "_product_embedding_client_for_identity", fail_client)
    with pytest.raises(ExecutorNetworkConfigurationError) as caught:
        with evaluation.IdentityRun("nomic", "linear"):
            pytest.fail("failed Product client acquisition must not enter the body")
    assert retrieval.embed_docs is original_embed_docs
    assert len(calls) == 1
    assert calls[0][0].dim > 0
    assert caught.value is failure
    _assert_restored(isolated_state)
    assert embeddings.get_primary_provider() == "mock"
    assert len(embeddings.embed_text("downstream", normalize=False)) == 4


@pytest.mark.parametrize("interrupted", [False, True])
def test_acquisition_failure_survives_cleanup_failure(monkeypatch, isolated_state, interrupted):
    acquisition_error = KeyboardInterrupt() if interrupted else RuntimeError("acquisition failed")
    cleanup_error = RuntimeError("store restoration failed")
    store = isolated_state[0]

    def fail_acquisition(*args, **kwargs):
        raise acquisition_error

    def fail_cleanup(*args, **kwargs):
        raise cleanup_error

    with monkeypatch.context() as scoped:
        scoped.setattr(retrieval, "embed_docs", fail_acquisition)
        scoped.setattr(store, "set_documents", fail_cleanup)
        with pytest.raises(type(acquisition_error)) as caught:
            with evaluation.IdentityRun("nomic", "linear"):
                pytest.fail("failed acquisition must not enter the body")
    assert caught.value is acquisition_error
    assert caught.value.__cause__ is cleanup_error
    _assert_restored(isolated_state)
    assert len(embeddings.embed_text("downstream", normalize=False)) == 4


@pytest.mark.parametrize("identity_key", ["nomic", "bge_m3"])
def test_identity_run_selects_declared_product_requests_under_compiled_target(
    monkeypatch, isolated_state, product_model_access_gateway, identity_key,
):
    """Resolve actual compiled policy and inspect real Product corpus/query request objects."""
    from app.components.llm.router import LLMRouter
    from app.settings.models import LLMRoutingSettings, SettingsBundle

    bundle = SettingsBundle(llm_routing=LLMRoutingSettings(
        default_embedding=LLMRoutingSettings.TaskPolicy(primary=LLMRoutingSettings.RouteTarget(
            model_id="ollama.embed.nomic_embed_text", provider="ollama",
            model="nomic-embed-text:latest", profile="default",
        )),
    ))
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    # The gateway fixture normally supplies mock route defaults. Keep the actual
    # compiled policy method here, while reusing its typed response transport only.
    monkeypatch.setattr(LLMRouter, "route", _ACTUAL_PRODUCT_ROUTE)
    spec = evaluation.IDENTITIES[identity_key]
    query = "synthetic corpus query about mountains"
    with evaluation.IdentityRun(identity_key, "linear") as run:
        assert run.resolved_identity.provider == "ollama"
        assert run.resolved_identity.model == spec["model"]
        assert run.resolved_identity.dim == spec["dim"]
        corpus_requests = list(product_model_access_gateway.embedding_requests)
        assert len(corpus_requests) == len(run.docs)
        assert [request.input_text for request in corpus_requests] == [doc.text for doc in run.docs]
        run.ranked(query, k=2)
        requests = product_model_access_gateway.embedding_requests
        assert len(requests) == len(corpus_requests) + 1
        assert requests[-1].input_text == query
        assert all(request.provider == "ollama" for request in requests)
        assert all(request.model == spec["model"] for request in requests)
        assert all(request.dimensions == spec["dim"] for request in requests)
    _assert_restored(isolated_state)


@pytest.mark.parametrize("failed_entry", [False, True])
def test_identity_run_restores_prior_explicit_product_selection(
    monkeypatch, isolated_state, failed_entry,
):
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FORCE_MODEL", "caller-prior-model")
    isolated_state[2].update({
        "LLM_FORCE_PROVIDER": "mock", "LLM_FORCE_MODEL": "caller-prior-model",
    })
    failure = RuntimeError("embedding acquisition failed")

    def embed(texts):
        assert os.environ["LLM_FORCE_PROVIDER"] == "ollama"
        assert os.environ["LLM_FORCE_MODEL"] == evaluation.IDENTITIES["nomic"]["model"]
        if failed_entry:
            raise failure
        return _fake_embed(texts)

    monkeypatch.setattr(retrieval, "embed_docs", embed)
    if failed_entry:
        with pytest.raises(RuntimeError) as caught:
            with evaluation.IdentityRun("nomic", "linear"):
                pytest.fail("failed acquisition must not enter the body")
        assert caught.value is failure
    else:
        with evaluation.IdentityRun("nomic", "linear"):
            pass
    _assert_restored(isolated_state)
