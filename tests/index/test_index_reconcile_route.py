from __future__ import annotations

import os

import pytest

from app.index.doctor import diagnose_index, inspect_vault_coverage_gap, reset_diagnose_cache
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


@pytest.mark.pg
def test_reconcile_detects_coverage_gap(tmp_path, monkeypatch) -> None:
    """#2324 AC2: coverage detection finds a vault note absent from store_objects.

    This is the vault -> store_objects half of the coverage-gap pipeline this
    issue owns (distinct from #2297's identity-convergence 'index reconcile').
    Seeds a vault directory with one markdown note and never ingests it, then
    asserts ``inspect_vault_coverage_gap()`` (wired through
    ``diagnose_index(include_vault_coverage=True)``) reports it with a count and
    sample path.
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    reset_diagnose_cache()
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    try:
        vault_root = tmp_path / "vault"
        settings_dir = vault_root / ".pkm-settings"
        settings_dir.mkdir(parents=True)
        (settings_dir / "vault.md").write_text("# vault marker\n", encoding="utf-8")
        note_path = vault_root / "orphan-note.md"
        note_path.write_text("# Orphan note\n\nNever ingested.\n", encoding="utf-8")

        monkeypatch.setenv("VAULT_ROOT", str(vault_root))
        monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
        monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)

        gap = inspect_vault_coverage_gap()
        assert gap.get("missing_count", 0) >= 1
        assert str(note_path) in (gap.get("missing_sample_paths") or [])

        reset_diagnose_cache()
        result = diagnose_index(include_vault_coverage=True)
        vault_coverage = result.get("vault_coverage") or {}
        assert vault_coverage.get("missing_count", 0) >= 1
        assert any("store_objects row" in w for w in result.get("warnings") or [])
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_reconcile_read_only_default(tmp_path, monkeypatch) -> None:
    """#2324 AC3 / Constraints: coverage detection is read-only by default.

    ``diagnose_index`` (with or without ``include_vault_coverage``) and
    ``inspect_vault_coverage_gap`` must never write to ``store_objects`` or
    ``store_vector_index`` — no auto-ingest, no auto-embed/backfill. Repair
    stays an explicit, separate, operator-invoked action (out of scope here;
    #2297's `index reconcile` remains the only reconcile *write* path and is
    untouched by this coverage/completeness diagnosis).
    """
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    reset_diagnose_cache()
    monkeypatch.setenv("EMBED_MODEL", "embed-test")
    try:
        vault_root = tmp_path / "vault"
        settings_dir = vault_root / ".pkm-settings"
        settings_dir.mkdir(parents=True)
        (settings_dir / "vault.md").write_text("# vault marker\n", encoding="utf-8")
        note_path = vault_root / "orphan-note.md"
        note_path.write_text("# Orphan note\n\nNever ingested.\n", encoding="utf-8")

        monkeypatch.setenv("VAULT_ROOT", str(vault_root))
        monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
        monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)

        def _count_rows(table: str) -> int:
            from app.stores.pg import _connect

            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) AS total FROM {table}")
                    row = cur.fetchone()
                    return int((row.get("total") if isinstance(row, dict) else row[0]) or 0)

        before_objects = _count_rows("store_objects")
        before_vectors = _count_rows("store_vector_index")

        inspect_vault_coverage_gap()
        reset_diagnose_cache()
        diagnose_index(include_vault_coverage=True)

        after_objects = _count_rows("store_objects")
        after_vectors = _count_rows("store_vector_index")

        assert after_objects == before_objects
        assert after_vectors == before_vectors

        # No 'index reconcile' collision: the coverage-gap diagnosis path exposes
        # no re-embed/backfill entrypoint of its own; the only reconcile *write*
        # path is #2297's `index reconcile` CLI command, unchanged by this test.
        import app.cli.index_rebuild as index_rebuild_cli

        assert index_rebuild_cli.index.commands.get("reconcile") is not None
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)
