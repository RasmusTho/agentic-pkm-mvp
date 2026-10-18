from dataclasses import replace

from app.retrieval import hybrid
from app.retrieval.capability import RetrievalRequest, retrieve
from app.settings.models import RetrievalTuning
from tests.retrieval.test_retrieval_capability import _patch_embeddings, _scoped_context
from app.retrieval.hybrid import get_store
from app.vault.active_context_v1 import ActiveContextBinding


def test_production_retrieval_preserves_binding_provenance(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    class DurableIndex:
        def generation_for_bindings(self, _binding_ids=None):
            return "durable-generation-1"

        def all_rows_for_bindings(self, _binding_ids=None):
            return [
                {
                    "object_id": "wrong-binding",
                    "text": "needle needle needle needle",
                    "payload": {"domain": "core", "text": "needle needle needle needle"},
                    "vault_binding_id": "binding-b",
                    "embedding": [0.1, 0.1, 0.1],
                },
                {
                    "object_id": "legacy-unbound",
                    "text": "needle needle",
                    "payload": {"domain": "core", "text": "needle needle"},
                    "vault_binding_id": None,
                    "embedding": [0.1, 0.1, 0.1],
                },
                {
                    "object_id": "a",
                    "text": "needle",
                    "payload": {
                        "domain": "core",
                        "text": "needle",
                        "settings_bundle": "vault-a",
                    },
                    "vault_binding_id": "binding-a",
                    "embedding": [0.1, 0.1, 0.1],
                },
            ]

    monkeypatch.setattr("app.stores.get_vector_index", lambda: DurableIndex())
    hybrid.reset_durable_rebuild_state()
    hybrid.rebuild_from_durable_index(force=True)
    try:
        response = retrieve(
            RetrievalRequest(
                query="needle",
                k=1,
                scope="core",
                active_context=_scoped_context(),
                settings_bundle_digest="effective-vault-a",
            )
        )
        # Binding eligibility is applied before ranking/top-k: the high-scoring
        # other-binding and legacy rows cannot evict the selected row.
        assert [hit.doc_id for hit in response.hits] == ["a"]
        assert response.hits[0].payload["vault_binding_id"] == "binding-a"
        assert response.hits[0].payload["context_generation"] == 3
        assert response.metadata["provenance"]["active_context"]["rejected_unbound_hits"] == 2
        assert (
            response.metadata["provenance"]["active_context"]["cache_key"]
            != retrieve(
                RetrievalRequest(
                    query="needle",
                    k=1,
                    scope="core",
                    active_context=_scoped_context(),
                    settings_bundle_digest="effective-vault-b",
                )
            ).metadata["provenance"]["active_context"]["cache_key"]
        )

        # MVR-05B4a: one production request over several bindings. Every result
        # carries its own source binding, source vault and the request's context
        # generation, and the cache lookup is keyed by every binding at that
        # generation, so it can never be served across bindings or generations.
        many = replace(
            _scoped_context(),
            context_id="ctx-many",
            generation=5,
            source_bindings=(
                ActiveContextBinding("binding-a", 1, "epoch-a", vault_id="vault-a"),
                ActiveContextBinding("binding-b", 4, "epoch-b", vault_id="vault-b"),
            ),
        )
        combined = retrieve(
            RetrievalRequest(
                query="needle",
                k=3,
                scope="core",
                active_context=many,
                settings_bundle_digest="effective-a-and-b",
            )
        )
        assert {hit.doc_id for hit in combined.hits} == {"a", "wrong-binding"}
        provenance = {
            hit.doc_id: (
                hit.payload["vault_binding_id"],
                hit.payload["source_vault_id"],
                hit.payload["context_generation"],
            )
            for hit in combined.hits
        }
        assert provenance == {
            "a": ("binding-a", "vault-a", 5),
            "wrong-binding": ("binding-b", "vault-b", 5),
        }
        lookup = combined.metadata["provenance"]["active_context"]
        assert lookup["generation"] == 5
        assert lookup["bindings"] == [
            {"vault_binding_id": "binding-a", "vault_id": "vault-a", "binding_revision": 1, "context_generation": 5},
            {"vault_binding_id": "binding-b", "vault_id": "vault-b", "binding_revision": 4, "context_generation": 5},
        ]
        assert lookup["rejected_unbound_hits"] == 1

        def _key(context) -> str:  # type: ignore[no-untyped-def]
            return retrieve(
                RetrievalRequest(
                    query="needle",
                    k=3,
                    scope="core",
                    active_context=context,
                    settings_bundle_digest="effective-a-and-b",
                )
            ).metadata["provenance"]["active_context"]["cache_key"]

        keys = {
            _key(many),
            _key(replace(many, generation=6)),
            _key(replace(many, source_bindings=many.source_bindings[:1])),
            _key(
                replace(
                    many,
                    source_bindings=(
                        many.source_bindings[0],
                        ActiveContextBinding("binding-b", 5, "epoch-b", vault_id="vault-b"),
                    ),
                )
            ),
        }
        assert len(keys) == 4
        assert _key(many) == lookup["cache_key"]
    finally:
        get_store().set_documents([])


def test_multi_binding_cache_filters_before_scoring_and_keeps_legacy_unbound(monkeypatch) -> None:
    """A shared cache cannot let another binding win scoped top-k selection."""

    _patch_embeddings(monkeypatch)

    class DurableIndex:
        def generation_for_bindings(self, _binding_ids=None):
            return "durable-generation-2"

        def all_rows_for_bindings(self, _binding_ids=None):
            return [
                {
                    "object_id": "binding-b-hit",
                    "payload": {"domain": "core", "text": "needle needle needle"},
                    "source_ref": "vault-b/needle.md",
                    "vault_binding_id": "binding-b",
                    "embedding": [0.1, 0.1, 0.1],
                },
                {
                    "object_id": "legacy-hit",
                    "payload": {"domain": "core", "text": "needle needle"},
                    "source_ref": "legacy/needle.md",
                    "vault_binding_id": None,
                    "embedding": [0.1, 0.1, 0.1],
                },
                {
                    "object_id": "binding-a-hit",
                    "payload": {"domain": "core", "text": "needle"},
                    "source_ref": "vault-a/needle.md",
                    "vault_binding_id": "binding-a",
                    "embedding": [0.1, 0.1, 0.1],
                },
            ]

    monkeypatch.setattr("app.stores.get_vector_index", lambda: DurableIndex())
    hybrid.reset_durable_rebuild_state()
    hybrid.rebuild_from_durable_index(force=True)
    context_a = _scoped_context()
    context_b = replace(
        context_a,
        context_id="ctx-b",
        source_bindings=(ActiveContextBinding("binding-b", 1, "epoch-b"),),
    )
    try:
        selected_a = retrieve(
            RetrievalRequest(query="needle", k=1, scope="core", active_context=context_a)
        )
        selected_b = retrieve(
            RetrievalRequest(query="needle", k=1, scope="core", active_context=context_b)
        )
        legacy = retrieve(RetrievalRequest(query="needle", k=3, scope="core"))

        assert [hit.doc_id for hit in selected_a.hits] == ["binding-a-hit"]
        assert [hit.doc_id for hit in selected_b.hits] == ["binding-b-hit"]
        assert {hit.doc_id for hit in legacy.hits} == {
            "binding-a-hit",
            "binding-b-hit",
            "legacy-hit",
        }
    finally:
        get_store().set_documents([])


def test_scoped_request_tuning_controls_rerank_after_candidate_filter(monkeypatch) -> None:
    """Scoped rerank decisions use the resolved request bundle, not process-global tuning."""

    _patch_embeddings(monkeypatch)
    get_store().set_documents(
        [
            {
                "doc_id": "binding-a-hit",
                "text": "needle scoped result",
                "source_ref": "vault-a/needle.md",
                "payload": {"domain": "core", "vault_binding_id": "binding-a"},
            }
        ]
    )
    applied: list[str] = []
    monkeypatch.setattr(
        "app.retrieval.hook_adapter.get_retrieval_tuning",
        lambda: RetrievalTuning(rerank="always"),
    )

    def _spy_rerank(_query: str, items: list[dict]) -> list[dict]:
        applied.append(_query)
        return items

    monkeypatch.setattr(
        "app.retrieval.hook_adapter.apply_optional_rerank",
        _spy_rerank,
    )
    try:
        response = retrieve(
            RetrievalRequest(
                query="needle",
                k=1,
                scope="core",
                active_context=_scoped_context(),
                retrieval_tuning=RetrievalTuning(rerank="off"),
            )
        )
        assert response.hits
        assert applied == []
    finally:
        get_store().set_documents([])


def test_scoped_rerank_tuning_reaches_hook_and_overrides_global(monkeypatch) -> None:
    """Scoped rerank mode and size reach the lower hook despite conflicting global tuning."""

    from app.retrieval.hook_adapter import maybe_rerank

    seen_top_k: list[int] = []

    class _Reranker:
        def rerank(self, _query, items, *, top_k):
            seen_top_k.append(top_k)
            return [items[-1]]

    monkeypatch.setattr(
        "app.retrieval.hook_adapter.get_retrieval_tuning",
        lambda: RetrievalTuning(rerank="off"),
    )
    monkeypatch.setattr(
        "app.retrieval.hybrid_rerank_hook.get_retrieval_tuning",
        lambda: RetrievalTuning(rerank="off"),
    )
    monkeypatch.setattr("app.retrieval.hybrid_rerank_hook.get_reranker", lambda: _Reranker())

    items = [
        {"id": "first", "text": "first result"},
        {"id": "second", "text": "second result"},
    ]
    result = maybe_rerank(
        "result",
        items,
        tuning=RetrievalTuning(rerank="always", rerank_top_k=1),
    )

    assert seen_top_k == [1]
    assert [item["id"] for item in result] == ["second", "first"]
