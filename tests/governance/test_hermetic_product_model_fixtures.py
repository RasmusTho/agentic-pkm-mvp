"""Regression proof for explicit Product model-access fixture enrollment."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.search.service import ingest_object
from app.workers.outbox_worker import handle_ingest_vault_changed

pytestmark = pytest.mark.not_pg


_AFFECTED_MODULES = (
    "tests/companion_ui/test_vault_initialize_layout.py",
    "tests/eval/test_benchmark.py",
    "tests/eval/test_classification_golden.py",
    "tests/eval/test_eval_run_route.py",
    "tests/eval/test_golden_metrics.py",
    "tests/evals/test_general_knowledge_crosses_clean.py",
    "tests/evals/test_private_not_in_work_results.py",
    "tests/evals/test_rpg_not_confused_with_software.py",
    "tests/fitness/test_ci_fitness.py",
    "tests/heimdal/test_attribution.py",
    "tests/indexer/test_embed_queue_ingest.py",
    "tests/ingest/test_vault_alpha_episode_ref.py",
    "tests/ingest/test_vault_alpha_title_fallback.py",
    "tests/ingest/test_ingest_embedding_identity.py",
    "tests/integration/test_multi_vault_client_carriers.py",
    "tests/invariants/test_invariant_residue.py",
    "tests/invariants/test_retrieval_spine_invariants.py",
    "tests/jobs/test_backfill.py",
    "tests/knowledge_acquisition/test_summary_extractor.py",
    "tests/mcp/test_mimer_server_smoke.py",
    "tests/properties/test_receipt_before_ack.py",
    "tests/quality_wave/test_registry_chain.py",
    "tests/retrieval/test_active_scope_request_binding.py",
    "tests/retrieval/test_conditional_rerank.py",
    "tests/retrieval/test_hybrid_stored_vectors.py",
    "tests/retrieval/test_mixed_identity_observability.py",
    "tests/retrieval/test_retrieval_durable_equivalence.py",
    "tests/retrieval/test_retrieval_tuning_config.py",
    "tests/retrieval/test_scope_prefilter_before_rank.py",
    "tests/runtime/test_worker_ingest_event.py",
    "tests/runtime/test_worker_uuid_heal_retry.py",
    "tests/standing_questions/test_answer_refresh.py",
    "tests/test_agent_smoke.py",
    "tests/test_hybrid_search.py",
    "tests/test_ingest_lifecycle.py",
    "tests/test_ingest_roundtrip.py",
)

_MODEL_ACCESS_PATH_ENV = (
    "MODEL_ACCESS_CODEX_VLAN_ENDPOINT",
    "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT",
    "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY",
)


def _uses_product_gateway_marker(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in targets):
            continue
        if any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "usefixtures"
            and any(
                isinstance(grandchild, ast.Constant)
                and grandchild.value == "product_model_access_gateway"
                for grandchild in ast.walk(call)
            )
            for call in ast.walk(node.value)
        ):
            return True
    return False


def test_ingest_and_worker_paths_use_synthetic_model_access_without_host_paths(
    monkeypatch: pytest.MonkeyPatch,
    product_model_access_gateway,
    tmp_path: Path,
) -> None:
    """Both real production call sites stay hermetic when host admission is unavailable."""
    for name in _MODEL_ACCESS_PATH_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_FORCE_MODEL", "nomic-embed-text:latest")

    _, ingest_dimensions = ingest_object(
        object_id=None,
        kind="note",
        source_ref="governance/ingest.md",
        payload={"title": "Synthetic ingest"},
        text="A deterministic ingest body.",
    )
    assert ingest_dimensions > 0

    vault_root = tmp_path / "vault"
    note_path = vault_root / "note.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        "uuid: 11111111-1111-1111-1111-111111111111\n"
        "title: Worker note\n"
        "---\n\n"
        "A deterministic worker body.\n",
        encoding="utf-8",
    )
    summary = handle_ingest_vault_changed(
        {
            "vault_path": str(note_path),
            "relative_path": "note.md",
            "hash": "governance-hash",
            "mtime": 1.0,
        },
        vault_root=vault_root,
    )

    assert summary.ingested == 1
    assert product_model_access_gateway.embedding_requests
    assert all(request.dimensions > 0 for request in product_model_access_gateway.embedding_requests)


def test_enumerated_unit_callers_are_enrolled_without_live_transport() -> None:
    """The finite CI failure set opts in explicitly; admission tests stay un-enrolled."""
    missing = [
        path
        for path in _AFFECTED_MODULES
        if not _uses_product_gateway_marker(Path(path))
    ]
    assert missing == []

    conftest = ast.parse(Path("tests/conftest.py").read_text(encoding="utf-8"))
    gateway_fixtures = [
        node
        for node in conftest.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "product_model_access_gateway"
    ]
    assert len(gateway_fixtures) == 1
    assert not any(
        keyword.arg == "autouse"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in ast.walk(gateway_fixtures[0])
        if isinstance(keyword, ast.keyword)
    )


def test_product_gateway_catalog_is_typed_and_rejects_unsupported_provider(
    product_model_access_gateway,
) -> None:
    """The synthetic catalog covers Product routing without accepting unknown providers."""
    from app.model_access.codex_remote_transport import RemoteCatalogError
    from app.model_access.remote_contract import ProductCatalogRequest

    response = product_model_access_gateway.catalog(
        ProductCatalogRequest(provider="openai", model="gpt-6-luna")
    )
    assert response.snapshot.provider == "openai"
    assert response.snapshot.transport_id == "codex_cli"
    assert {model.model for model in response.snapshot.models} == {
        "gpt-5.6-luna",
        "gpt-6-luna",
    }

    with pytest.raises(RemoteCatalogError) as error:
        product_model_access_gateway.catalog(
            ProductCatalogRequest(provider="ollama", model="nomic-embed-text:latest")
        )
    assert error.value.code == "catalog_unavailable"
