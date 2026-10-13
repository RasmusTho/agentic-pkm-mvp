"""Regression proof for explicit Product model-access fixture enrollment."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from app.components.llm.router import LLMRouter
from app.search.service import ingest_object
from app.workers.outbox_worker import handle_ingest_vault_changed

pytestmark = pytest.mark.not_pg

_ORIGINAL_LLM_ROUTER_ROUTE = LLMRouter.route


_AFFECTED_MODULES = (
    "tests/companion_ui/test_vault_initialize_layout.py",
    "tests/eval/test_benchmark.py",
    "tests/eval/test_classification_golden.py",
    "tests/eval/test_eval_run_route.py",
    "tests/eval/test_golden_metrics.py",
    "tests/evals/test_general_knowledge_crosses_clean.py",
    "tests/evals/test_private_not_in_work_results.py",
    "tests/evals/test_rpg_not_confused_with_software.py",
    "tests/e2e/test_pipe_graph.py",
    "tests/e2e/test_reality_mvp_pipeline.py",
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
    "tests/retrieval/test_envelope_consumption.py",
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


def test_e2e_pipe_and_reality_callers_are_enrolled() -> None:
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

    admission_path = Path("tests/model_access/test_executor_network_policy.py")
    assert not _uses_product_gateway_marker(admission_path)
    admission_tree = ast.parse(admission_path.read_text(encoding="utf-8"))
    admission_tests = [
        node
        for node in admission_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "test_missing_path_configuration_fails_before_transport_creation"
    ]
    assert len(admission_tests) == 1
    assert "product_model_access_gateway" not in {
        argument.arg
        for argument in admission_tests[0].args.args
    }


def test_e2e_callers_remain_hermetic_with_compiled_product_routes(
    monkeypatch: pytest.MonkeyPatch,
    product_model_access_gateway,
    tmp_path: Path,
) -> None:
    """Real E2E callers use typed gateway responses with compiled routes and no host path."""
    from app.model_access.remote_contract import (
        ProductCompletionRequest,
        ProductEmbeddingRequest,
        ProductPreflightRequest,
    )
    from app.settings import runtime
    from tests.e2e.test_pipe_graph import test_e2e_pipe
    from tests.e2e.test_reality_mvp_pipeline import test_reality_mvp_note_ingest_and_ask

    for name in _MODEL_ACCESS_PATH_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_ENFORCE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    response = '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'
    monkeypatch.setenv("LLM_MOCK_RESPONSE", response)
    product_model_access_gateway.completion_content = response

    runtime_dir = tmp_path / "compiled-runtime"
    runtime_dir.mkdir()
    (runtime_dir / "llm_routing.yaml").write_text(
        "default_chat:\n"
        "  primary:\n"
        "    model_id: openai.chat.gpt_6_luna\n"
        "default_reasoning:\n"
        "  primary:\n"
        "    model_id: openai.chat.gpt_6_luna\n"
        "default_embedding:\n"
        "  primary:\n"
        "    model_id: ollama.embed.nomic_embed_text\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    compiled_bundle = runtime._build_bundle()
    monkeypatch.setattr(
        "app.components.llm.router.get_settings_bundle", lambda: compiled_bundle
    )
    # Keep production route precedence while reusing only the typed gateway seam.
    monkeypatch.setattr(LLMRouter, "route", _ORIGINAL_LLM_ROUTER_ROUTE)

    gateway = product_model_access_gateway
    pipe_preflight_start = len(gateway.preflight_requests)
    pipe_completion_start = len(gateway.completion_requests)
    pipe_root = tmp_path / "pipe"
    pipe_root.mkdir()
    test_e2e_pipe(pipe_root)
    pipe_preflight = gateway.preflight_requests[pipe_preflight_start:]
    pipe_completions = gateway.completion_requests[pipe_completion_start:]
    assert pipe_preflight
    assert all(isinstance(request, ProductPreflightRequest) for request in pipe_preflight)
    assert any(
        isinstance(request, ProductCompletionRequest)
        and request.provider == "openai"
        and request.model == "gpt-6-luna"
        for request in pipe_completions
    )

    reality_embedding_start = len(gateway.embedding_requests)
    reality_root = tmp_path / "reality"
    reality_root.mkdir()
    test_reality_mvp_note_ingest_and_ask(reality_root, monkeypatch)
    reality_embeddings = gateway.embedding_requests[reality_embedding_start:]

    assert all(name not in os.environ for name in _MODEL_ACCESS_PATH_ENV)
    assert any(
        isinstance(request, ProductEmbeddingRequest)
        and request.provider == "ollama"
        and request.model == "nomic-embed-text:latest"
        for request in reality_embeddings
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
