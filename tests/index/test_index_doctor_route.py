from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.index.doctor import diagnose_index, reset_diagnose_cache
from app.settings.models import SettingsBundle


def _pg_available() -> bool:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    try:
        conn = psycopg.connect(url, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _isolate_llm_routing_settings(monkeypatch) -> None:
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: SettingsBundle())


def test_index_doctor_expected_identity_uses_router(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    monkeypatch.setenv("EMBED_DIM", "12")

    result = diagnose_index()
    expected = result.get("expected_identity") or {}

    assert expected.get("provider") == "mock"
    assert expected.get("model") == "mock-embedding"
    assert expected.get("dim") == 12


def test_index_doctor_reports_rebuild_fields(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    monkeypatch.setenv("EMBED_DIM", "12")

    result = diagnose_index()

    assert "rebuild_required" in result
    assert "compatible_identity" in result
    assert "empty_index" in result


@pytest.mark.pg
def test_doctor_reports_indexed(tmp_path, monkeypatch) -> None:
    """Gate-0 AC2: after a seeded embedded vault, doctor reports a healthy index.

    Drives the durable spine (save -> request -> consumer embed/upsert into the
    Postgres ``store_vector_index``) and asserts ``diagnose_index()`` reports
    ``rebuild_required=False`` and ``empty_index=False`` for the seeded,
    identity-compatible index.
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from datetime import datetime, timezone

    from app.objects import DomainObject, ObjectStore
    from app.outbox import events
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drain_db_outbox_embedding_spine,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    dsn = os.environ["DATABASE_URL"]
    reset_diagnose_cache()
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    try:
        import app.store.object_store as legacy_object_store

        legacy_object_store._MEMORY_STORE.clear()

        store = ObjectStore()
        oid = uuid4()
        store.save_object(
            DomainObject(
                uuid=str(oid),
                kind="note",
                payload={"text": "doctor seed payload", "content": "doctor seed payload"},
                source_ref="unit-test:doctor-indexed",
                created_at=datetime.now(timezone.utc),
            ),
            emit_outbox=False,
            trace_id="trace-doctor-indexed",
        )
        events.emit_index_embedding_requested(
            {"object_id": oid, "trace_id": "trace-doctor-indexed", "source": "test"}
        )

        legacy_object_store._MEMORY_STORE.clear()

        # Drain ONLY this object's seeded embedding-request row, scoped by object_id
        # on the nested envelope path, through the same consumer entrypoint the
        # production worker dispatches to. A global ``poll_outbox_one`` loop would
        # ack pre-existing foreign rows on a shared/operator DB — destructive.
        processed_total = _drain_db_outbox_embedding_spine(dsn, str(oid))
        assert processed_total >= 1

        reset_diagnose_cache()
        result = diagnose_index()

        assert result["empty_index"] is False
        assert result["rebuild_required"] is False
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_doctor_flags_incomplete_metadata(tmp_path, monkeypatch) -> None:
    """#2324 AC1: doctor flags store_vector_index rows missing W3-SPINE-01 metadata.

    Writes a row directly (bypassing ``build_indexed_unit_payload``, which always
    stamps language/source_role/embedding_identity) to simulate a legacy row
    written before the retrieved-unit payload contract, then asserts
    ``diagnose_index()`` reports it via ``metadata_completeness`` without treating
    it as an identity-mismatch/mixed-identity issue (#2297's concern, not this
    issue's).
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from app.components.embeddings import EmbeddingIdentity
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    reset_diagnose_cache()
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    try:
        from app.stores import get_vector_index

        identity = EmbeddingIdentity(provider="mock", model="embed-test", dim=8, normalize=False)
        index_store = get_vector_index()
        oid = uuid4()
        # Deliberately minimal payload: no language/source_role/embedding_identity,
        # simulating a pre-contract legacy row.
        index_store.upsert(
            object_id=oid,
            kind="note",
            source_ref="unit-test:incomplete-metadata",
            payload={"text": "legacy row with no provenance stamp"},
            embedding=[0.1] * 8,
            model=identity.model,
            identity=identity,
        )

        reset_diagnose_cache()
        result = diagnose_index()

        completeness = result.get("metadata_completeness") or {}
        assert completeness.get("missing_count", 0) >= 1
        assert str(oid) in (completeness.get("missing_sample_ids") or [])
        # This is a completeness warning, not an identity mismatch/mixed-identity issue.
        assert result.get("mixed_identities") == []
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_health_surfaces_coverage(tmp_path, monkeypatch) -> None:
    """#2324 AC4: app/cli/health.py surfaces the new completeness/coverage findings."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from app.components.embeddings import EmbeddingIdentity
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    reset_diagnose_cache()
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    try:
        from app.cli.health import _check_embedding_index
        from app.stores import get_vector_index

        identity = EmbeddingIdentity(provider="mock", model="embed-test", dim=8, normalize=False)
        index_store = get_vector_index()
        oid = uuid4()
        index_store.upsert(
            object_id=oid,
            kind="note",
            source_ref="unit-test:health-coverage",
            payload={"text": "legacy row with no provenance stamp"},
            embedding=[0.1] * 8,
            model=identity.model,
            identity=identity,
        )

        reset_diagnose_cache()
        check = _check_embedding_index()

        assert "metadata_completeness" in check
        assert check["metadata_completeness"]["missing_count"] >= 1
        assert "vault_coverage" in check
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)
