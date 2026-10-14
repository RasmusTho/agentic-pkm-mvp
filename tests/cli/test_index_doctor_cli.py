from __future__ import annotations

import json
from uuid import uuid4

from click.testing import CliRunner

from app.cli import cli
from app.components.llm.fabric import LLMTaskIntent, get_embeddings_client
from app.stores import get_vector_index, reset_store_backends


def test_json_reports_unembedded_object_count(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.cli.index_doctor.diagnose_index",
        lambda **_kwargs: {"unembedded_object_count": 1},
    )

    result = CliRunner().invoke(cli, ["index", "doctor", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["unembedded_object_count"] == 1


def _seed_vector() -> None:
    idx = get_vector_index()
    client = get_embeddings_client(LLMTaskIntent(task_kind="embed", determinism_required=False))
    identity = client.identity
    idx.upsert(
        object_id=uuid4(),
        kind="note",
        source_ref="tests/index-doctor",
        payload={"text": "doctor"},
        embedding=client.embed_text("doctor"),
        model=identity.model,
        identity=identity,
    )


def test_index_doctor_strict_ok(monkeypatch) -> None:
    reset_store_backends()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_vector()

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "doctor", "--strict"])

    assert result.exit_code == 0
    assert "VectorIndex backend" in result.output

    reset_store_backends()


def test_index_doctor_strict_detects_drift(monkeypatch) -> None:
    reset_store_backends()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_vector()

    monkeypatch.setenv("EMBED_DIM", "16")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "doctor", "--strict"])

    assert result.exit_code == 2
    assert "Identity mismatch" in result.output

    reset_store_backends()
