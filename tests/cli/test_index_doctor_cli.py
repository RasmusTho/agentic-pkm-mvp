from __future__ import annotations

from uuid import uuid4

from click.testing import CliRunner

from app.cli import cli
from app.components.embeddings import get_embedding_client, get_embedding_identity
from app.stores import get_vector_index, reset_store_backends


def _seed_vector() -> None:
    idx = get_vector_index()
    client = get_embedding_client()
    identity = get_embedding_identity(client=client)
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
    monkeypatch.setenv("EMBED_DIM", "8")

    _seed_vector()

    monkeypatch.setenv("EMBED_DIM", "16")

    runner = CliRunner()
    result = runner.invoke(cli, ["index", "doctor", "--strict"])

    assert result.exit_code == 2
    assert "Identity mismatch" in result.output

    reset_store_backends()
