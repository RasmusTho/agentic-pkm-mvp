"""KERNEL-06: transform provenance stamp — content_hash + chunk_policy_version
+ pipeline_version rides the same upsert as the vector.

Covers docs/RUNTIME_CORRECTNESS_KERNEL/TRANSFORM_PROVENANCE_STAMP.md and audit
invariant I-D1 (CW-6). Cross-task invariant #4: the stamp is written inside
the same upsert payload as the embedding — never a separate "stamp later"
write. Cross-task invariant #5: doctor detects, reconcile repairs, nothing
auto-mutates.

- test_upsert_writes_provenance: the production ingest_object() entrypoint
  stamps provenance into the same payload dict passed to VectorIndex.upsert().
- test_doctor_lists_stale_candidates / test_reconcile_incremental_on_stale_only:
  content-hash staleness detection and incremental repair are Postgres-backed
  capabilities (matching the existing `index reconcile` Postgres-only posture)
  — pg-marked, real DB required.
"""

from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest

from app.agents.panel.filters import strip_ai_panels
from app.components.embeddings import EmbeddingIdentity
from app.index.artifact_metadata import canonicalize_indexable_text, compute_content_hash
from app.ingest.chunk_policy import CHUNK_POLICY_VERSION
from app.settings.models import SettingsBundle

pytestmark = pytest.mark.not_pg


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


class CapturingVectorIndex:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.purge_calls: list[tuple[object, str]] = []

    def upsert(self, **kwargs) -> None:
        self.calls.append(kwargs)

    def purge_vectors(self, object_id, *, view: str) -> int:
        self.purge_calls.append((object_id, view))
        return 0


def _seed_legacy_panel_vector(*, source_ref: str) -> tuple[object, str]:
    """Construct the pre-fix panel-only vector state without a live producer."""
    from app.search import service as search_service
    from app.stores import get_object_store
    from app.stores.pg import _connect

    placeholder = "legacy placeholder used only to create a vector row"
    panel_only = "%% AI:Start %%\nLegacy indexed panel bytes.\n%% AI:End %%"
    oid, _ = search_service.ingest_object(
        kind="note",
        source_ref=source_ref,
        payload={"content": placeholder, "text": placeholder},
        text=placeholder,
    )
    get_object_store().put(
        oid,
        kind="note",
        source_ref=source_ref,
        payload={"content": panel_only, "text": panel_only},
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM store_vector_index WHERE object_id = %s",
                (oid,),
            )
            vector_payload = dict(cur.fetchone()["payload"])
            vector_payload["content"] = panel_only
            vector_payload["text"] = panel_only
            provenance = dict(vector_payload.get("provenance") or {})
            provenance["content_hash"] = compute_content_hash("")
            vector_payload["provenance"] = provenance
            cur.execute(
                "UPDATE store_vector_index SET payload = %s::jsonb WHERE object_id = %s",
                (json.dumps(vector_payload), oid),
            )

    return oid, panel_only


def test_upsert_writes_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every ingest_object() write persists provenance superset fields."""
    from app.search import service as search_service

    identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=3, normalize=True)
    index = CapturingVectorIndex()
    monkeypatch.setattr(search_service, "embed_query", lambda text: ([0.1, 0.2, 0.3], identity))
    monkeypatch.setattr(search_service, "get_vector_index", lambda: index)

    text = "Provenance stamp fixture text."
    object_id, _dim = search_service.ingest_object(
        kind="note",
        source_ref="unit-test://provenance",
        payload={"title": "Provenance fixture"},
        text=text,
    )

    assert index.calls, "ingest_object must upsert into the vector index"
    captured = index.calls[-1]
    provenance = captured["payload"]["provenance"]

    assert provenance["source_ref"] == "unit-test://provenance"
    assert provenance["content_hash"] == compute_content_hash(text)
    assert provenance["chunk_policy_version"] == CHUNK_POLICY_VERSION
    assert provenance["pipeline_version"]
    assert provenance["embedding_identity"] == {
        "provider": identity.provider,
        "model": identity.model,
        "dim": identity.dim,
        "normalize": identity.normalize,
    }


def test_ingest_object_embeds_hashes_and_projects_exact_canonical_bytes(monkeypatch) -> None:
    from app.search import service as search_service

    identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=3, normalize=True)
    index = CapturingVectorIndex()
    embedded_texts: list[str] = []

    def fake_embed(text: str):
        embedded_texts.append(text)
        return [0.1, 0.2, 0.3], identity

    monkeypatch.setattr(search_service, "embed_query", fake_embed)
    monkeypatch.setattr(search_service, "get_vector_index", lambda: index)

    raw = "\n".join(
        (
            "retained before",
            "%% AI:Start %%",
            "fenced panel",
            "%% AI:End %%",
            "## AI-instruktion",
            "legacy panel",
            "## Retained section",
            "retained after",
        )
    )
    canonical = canonicalize_indexable_text({"content": raw})

    search_service.ingest_object(
        kind="note",
        source_ref="unit-test://producer-exact-bytes",
        payload={"content": raw, "text": "stale alias"},
        text=raw,
    )

    assert embedded_texts == [canonical]
    payload = index.calls[-1]["payload"]
    assert payload["content"] == canonical
    assert payload["text"] == canonical
    assert payload["provenance"]["content_hash"] == compute_content_hash(canonical)


def test_ingest_object_does_not_recreate_panel_only_vector(monkeypatch) -> None:
    from app.search import service as search_service

    index = CapturingVectorIndex()
    monkeypatch.setattr(search_service, "get_vector_index", lambda: index)

    def unexpected_embed(_text: str):
        raise AssertionError("panel-only source must not reach the embedder")

    monkeypatch.setattr(search_service, "embed_query", unexpected_embed)
    oid, dim = search_service.ingest_object(
        kind="note",
        source_ref="unit-test://producer-panel-only",
        payload={"content": "\n%% AI:Start %%\ntransient\n%% AI:End %%\n\n"},
        text="\n%% AI:Start %%\ntransient\n%% AI:End %%\n\n",
    )

    assert dim == 0
    assert index.calls == []
    assert index.purge_calls == [(oid, "markdown.semantic")]


def test_content_hash_is_stable_for_same_text() -> None:
    """content_hash is deterministic — a re-run over unchanged text is a no-op signal."""
    text = "Stable hash fixture."
    assert compute_content_hash(text) == compute_content_hash(text)
    assert compute_content_hash(text) != compute_content_hash(text + " changed")


@pytest.mark.pg
def test_doctor_lists_stale_candidates(tmp_path, monkeypatch) -> None:
    """Index doctor reports content-hash staleness as a read-only re-embed
    candidate listing (no mutation) when store_objects text has drifted past
    the stamped store_vector_index content_hash."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from app.index.doctor import diagnose_index, reset_diagnose_cache
    from app.stores import get_object_store
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    reset_diagnose_cache()
    try:
        from app.search import service as search_service
        from app.stores.pg import _connect

        oid, _dim = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://doctor-stale",
            payload={"text": "original content", "content": "original content"},
            text="original content",
        )
        # The staleness join needs a store_objects row (the "current" source
        # text side of the comparison) — ingest_object only writes the
        # vector-index side, so seed store_objects directly here.
        get_object_store().put(
            oid,
            kind="note",
            source_ref="unit-test://doctor-stale",
            payload={"text": "original content", "content": "original content"},
        )

        # Simulate the source drifting: store_objects text changes but the
        # store_vector_index row (and its stamped content_hash) is untouched —
        # exactly the divergence content-hash staleness detects.
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE store_objects SET payload = payload || '{\"text\": \"changed content\", \"content\": \"changed content\"}'::jsonb WHERE object_id = %s",
                    (oid,),
                )

        reset_diagnose_cache()
        result = diagnose_index()

        staleness = result.get("content_hash_staleness") or {}
        assert staleness.get("stale_count", 0) >= 1
        assert str(oid) in (staleness.get("stale_sample_ids") or [])

        # Read-only: the durable vector row's stamped content_hash is untouched
        # by diagnosis (still reflects the original, pre-drift text).
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload->'provenance'->>'content_hash' AS content_hash "
                    "FROM store_vector_index WHERE object_id = %s",
                    (oid,),
                )
                row = cur.fetchone()
        assert row["content_hash"] == compute_content_hash("original content")
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_doctor_uses_rebuild_text_precedence_for_content_hash(tmp_path, monkeypatch) -> None:
    """Doctor hashes the same ``content`` field that rebuild embeds when both
    ``content`` and a divergent legacy ``text`` field are present."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import cli
    from app.index.doctor import diagnose_index, reset_diagnose_cache
    from app.stores import get_object_store
    from app.stores.pg import _connect
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    reset_diagnose_cache()
    try:
        canonical_content = "\n".join(
            (
                "producer-selected content",
                "%% AI:Start %%",
                "fenced panel text",
                "%% AI:End %%",
                "## AI-instruktion",
                "legacy panel text",
                "## Retained section",
                "retained content",
            )
        )
        expected_canonical = "\n".join(
            ("producer-selected content", "## Retained section", "retained content")
        )
        oid = uuid4()
        get_object_store().put(
            oid,
            kind="note",
            source_ref="unit-test://doctor-content-precedence",
            payload={"content": canonical_content, "text": "legacy shadow text"},
        )

        rebuild = CliRunner().invoke(
            cli,
            ["index", "rebuild", "--backend", "pg", "--json", "--strict"],
            env=dict(os.environ),
        )
        assert rebuild.exit_code == 0, rebuild.output
        rebuild_summary = json.loads(rebuild.output)
        assert rebuild_summary["processed"] == 1

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM store_vector_index WHERE object_id = %s",
                    (oid,),
                )
                vector_row = cur.fetchone()

        assert vector_row["payload"]["content"] == expected_canonical
        assert vector_row["payload"]["text"] == expected_canonical
        assert vector_row["payload"]["provenance"]["content_hash"] == compute_content_hash(
            expected_canonical
        )

        reset_diagnose_cache()
        result = diagnose_index()
        staleness = result.get("content_hash_staleness") or {}
        assert staleness.get("stale_count", 0) == 0
        assert str(oid) not in (staleness.get("stale_sample_ids") or [])
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_reconcile_incremental_on_stale_only(tmp_path, monkeypatch) -> None:
    """`index reconcile` re-embeds only stale rows: unchanged rows are untouched."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import cli
    from app.stores import get_object_store
    from app.stores.pg import _connect
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    try:
        from app.search import service as search_service

        stale_oid, _ = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://reconcile-stale",
            payload={"text": "stale original", "content": "stale original"},
            text="stale original",
        )
        get_object_store().put(
            stale_oid,
            kind="note",
            source_ref="unit-test://reconcile-stale",
            payload={"text": "stale original", "content": "stale original"},
        )
        fresh_oid, _ = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://reconcile-fresh",
            payload={"text": "fresh unchanged", "content": "fresh unchanged"},
            text="fresh unchanged",
        )
        get_object_store().put(
            fresh_oid,
            kind="note",
            source_ref="unit-test://reconcile-fresh",
            payload={"text": "fresh unchanged", "content": "fresh unchanged"},
        )

        # Simulate content drift on ONE object only. The authoritative
        # ``content`` field includes an AI panel while the legacy ``text``
        # field diverges; reconcile and doctor must both use content-first
        # precedence and the producer's panel-stripping hash canonicalization.
        changed_content = """stale changed

%% AI:Start %%
## AI-instruktion
Transient panel text.
%% AI:End %%
"""
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE store_objects "
                    "SET payload = payload || "
                    "jsonb_build_object('content', %s::text, 'text', %s::text) "
                    "WHERE object_id = %s",
                    (changed_content, "legacy shadow text", stale_oid),
                )

        import importlib

        rebuild_module = importlib.import_module("app.cli.index_rebuild")
        resolved_client = rebuild_module.get_embedding_client(profile="default")
        embedded_texts: list[str] = []

        class CapturingClient:
            identity = resolved_client.identity

            def embed_text(self, text: str) -> list[float]:
                embedded_texts.append(text)
                return resolved_client.embed_text(text)

        monkeypatch.setattr(
            rebuild_module,
            "get_embedding_client",
            lambda *, profile="default": CapturingClient(),
        )

        runner = CliRunner()
        env = dict(os.environ)
        result = runner.invoke(cli, ["index", "reconcile", "--backend", "pg", "--json"], env=env)
        assert result.exit_code == 0, result.output

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT object_id, payload, "
                    "payload->'provenance'->>'content_hash' AS content_hash "
                    "FROM store_vector_index WHERE object_id IN (%s, %s)",
                    (stale_oid, fresh_oid),
                )
                rows_after = {row["object_id"]: row for row in cur.fetchall()}

        # Stale row is re-embedded: its hash matches the producer's canonical
        # panel-free form of the selected content field.
        assert rows_after[stale_oid]["content_hash"] == compute_content_hash(
            strip_ai_panels(changed_content)
        )
        # The derived retrieval payload must also carry the authoritative
        # source text.  Otherwise doctor can report convergence while hybrid
        # retrieval still serves the legacy ``text`` alias.
        canonical_changed_content = strip_ai_panels(changed_content)
        assert embedded_texts == [canonical_changed_content]
        assert rows_after[stale_oid]["payload"]["content"] == canonical_changed_content
        assert rows_after[stale_oid]["payload"]["text"] == canonical_changed_content

        # Fresh (unchanged) row is untouched: same content_hash as before —
        # incremental repair, not a blanket re-embed of the whole index.
        assert rows_after[fresh_oid]["content_hash"] == compute_content_hash("fresh unchanged")

        from app.index.doctor import diagnose_index, reset_diagnose_cache

        reset_diagnose_cache()
        diagnosis = diagnose_index()
        staleness = diagnosis.get("content_hash_staleness") or {}
        assert staleness.get("stale_count", 0) == 0
        assert str(stale_oid) not in (staleness.get("stale_sample_ids") or [])
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_reconcile_purges_vector_for_present_non_indexable_source(tmp_path, monkeypatch) -> None:
    """Explicit reconcile removes derived bytes after their source becomes non-indexable."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import cli
    from app.index.doctor import inspect_unembedded_pg_objects
    from app.stores import get_object_store
    from app.stores.pg import _connect, inspect_pg_content_hash_staleness
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    try:
        from app.search import service as search_service

        oid, _ = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://reconcile-non-indexable",
            payload={"content": "previous source text", "text": "previous source text"},
            text="previous source text",
        )
        get_object_store().put(
            oid,
            kind="note",
            source_ref="unit-test://reconcile-non-indexable",
            payload={"content": "previous source text", "text": "previous source text"},
        )

        authoritative_payload = {"url": "https://example.invalid/now-contentless"}
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE store_objects SET payload = %s::jsonb WHERE object_id = %s",
                    (json.dumps(authoritative_payload), oid),
                )

        result = CliRunner().invoke(
            cli,
            ["index", "reconcile", "--backend", "pg", "--json", "--strict"],
            env=dict(os.environ),
        )
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["purged_non_indexable"] == 1
        assert summary["reconciled"] == 0

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM store_objects WHERE object_id = %s",
                    (oid,),
                )
                source_row = cur.fetchone()
                cur.execute(
                    "SELECT count(*) AS total FROM store_vector_index WHERE object_id = %s",
                    (oid,),
                )
                vector_row = cur.fetchone()

        assert source_row["payload"] == authoritative_payload
        assert vector_row["total"] == 0
        assert inspect_unembedded_pg_objects(limit=10) == (0, [])
        assert inspect_pg_content_hash_staleness()["stale_count"] == 0
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_reconcile_purges_equal_empty_hash_panel_only_vector(tmp_path, monkeypatch) -> None:
    """A legacy panel vector is purgeable even when its hash already looks clean."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import cli
    from app.index.doctor import inspect_unembedded_pg_objects, reset_diagnose_cache
    from app.stores.pg import _connect, inspect_pg_content_hash_staleness
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    try:
        oid, panel_only = _seed_legacy_panel_vector(
            source_ref="unit-test://reconcile-equal-empty-panel"
        )

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload, provider, model FROM store_vector_index "
                    "WHERE object_id = %s",
                    (oid,),
                )
                before = cur.fetchone()

        assert before["payload"]["content"] == panel_only
        assert before["payload"]["provenance"]["content_hash"] == compute_content_hash("")
        assert before["provider"] == "mock"
        assert before["model"] == "mock-embedding"
        assert inspect_pg_content_hash_staleness()["stale_count"] == 0

        result = CliRunner().invoke(
            cli,
            ["index", "reconcile", "--backend", "pg", "--json", "--strict"],
            env=dict(os.environ),
        )
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["total_present_non_indexable"] == 1
        assert summary["purged_non_indexable"] == 1
        assert summary["reconciled"] == 0

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM store_objects WHERE object_id = %s",
                    (oid,),
                )
                source_row = cur.fetchone()
                cur.execute(
                    "SELECT count(*) AS total FROM store_vector_index WHERE object_id = %s",
                    (oid,),
                )
                vector_total = cur.fetchone()["total"]

        reset_diagnose_cache()
        assert source_row["payload"] == {"content": panel_only, "text": panel_only}
        assert vector_total == 0
        assert inspect_unembedded_pg_objects(limit=10) == (0, [])
        assert inspect_pg_content_hash_staleness()["stale_count"] == 0
    finally:
        reset_diagnose_cache()
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_reconcile_reclassifies_source_update_before_conditional_purge(
    tmp_path, monkeypatch
) -> None:
    """A concurrent source repair is embedded rather than purged from a stale read."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import cli
    from app.stores.pg import _connect
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    try:
        oid, _panel_only = _seed_legacy_panel_vector(
            source_ref="unit-test://reconcile-source-update-race"
        )
        repaired_raw = "retained before\n%% AI:Start %%\ntransient\n%% AI:End %%\nretained after"
        repaired_canonical = canonicalize_indexable_text({"content": repaired_raw})

        import importlib

        rebuild_module = importlib.import_module("app.cli.index_rebuild")
        original_resolve = rebuild_module._reconcile_object_payload
        resolved_client = rebuild_module.get_embedding_client(profile="default")
        embedded_texts: list[str] = []
        raced = False

        class CapturingClient:
            identity = resolved_client.identity

            def embed_text(self, text: str) -> list[float]:
                embedded_texts.append(text)
                return resolved_client.embed_text(text)

        def update_after_stale_read(object_id, vector_payload):
            nonlocal raced
            result = original_resolve(object_id, vector_payload)
            if not raced:
                with _connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE store_objects SET payload = %s::jsonb WHERE object_id = %s",
                            (json.dumps({"content": repaired_raw, "text": "stale alias"}), oid),
                        )
                raced = True
            return result

        monkeypatch.setattr(rebuild_module, "_reconcile_object_payload", update_after_stale_read)
        monkeypatch.setattr(
            rebuild_module,
            "get_embedding_client",
            lambda *, profile="default": CapturingClient(),
        )

        result = CliRunner().invoke(
            cli,
            ["index", "reconcile", "--backend", "pg", "--json", "--strict"],
            env=dict(os.environ),
        )
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["purged_non_indexable"] == 0
        assert summary["reconciled"] == 1
        assert embedded_texts == [repaired_canonical]

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM store_objects WHERE object_id = %s",
                    (oid,),
                )
                source_payload = cur.fetchone()["payload"]
                cur.execute(
                    "SELECT payload FROM store_vector_index WHERE object_id = %s",
                    (oid,),
                )
                vector_payload = cur.fetchone()["payload"]

        assert source_payload == {"content": repaired_raw, "text": "stale alias"}
        assert vector_payload["content"] == repaired_canonical
        assert vector_payload["text"] == repaired_canonical
        assert vector_payload["provenance"]["content_hash"] == compute_content_hash(
            repaired_canonical
        )
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_reconcile_reclassifies_source_delete_before_conditional_purge(
    tmp_path, monkeypatch
) -> None:
    """A concurrently deleted source retains the existing vector fallback."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import cli
    from app.stores.pg import _connect
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    try:
        oid, panel_only = _seed_legacy_panel_vector(
            source_ref="unit-test://reconcile-source-delete-race"
        )

        import importlib

        rebuild_module = importlib.import_module("app.cli.index_rebuild")
        original_resolve = rebuild_module._reconcile_object_payload
        raced = False

        def delete_after_stale_read(object_id, vector_payload):
            nonlocal raced
            result = original_resolve(object_id, vector_payload)
            if not raced:
                with _connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM store_objects WHERE object_id = %s", (oid,))
                raced = True
            return result

        monkeypatch.setattr(rebuild_module, "_reconcile_object_payload", delete_after_stale_read)

        result = CliRunner().invoke(
            cli,
            ["index", "reconcile", "--backend", "pg", "--json", "--strict"],
            env=dict(os.environ),
        )
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["purged_non_indexable"] == 0
        assert summary["reconciled"] == 0
        assert summary["skipped"] == 1

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) AS total FROM store_objects WHERE object_id = %s",
                    (oid,),
                )
                assert cur.fetchone()["total"] == 0
                cur.execute(
                    "SELECT payload FROM store_vector_index WHERE object_id = %s",
                    (oid,),
                )
                vector_row = cur.fetchone()

        assert vector_row is not None
        assert vector_row["payload"]["content"] == panel_only
        assert vector_row["payload"]["provenance"]["content_hash"] == compute_content_hash("")
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)


@pytest.mark.pg
def test_reconcile_absent_source_retains_vector_payload_fallback(tmp_path, monkeypatch) -> None:
    """An orphaned vector remains reconcilable from its derived payload."""
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    from click.testing import CliRunner

    from app.cli import cli
    from app.stores.pg import _connect
    from tests.indexer.test_outbox_roundtrip_pg import (
        _configure_isolated_pg_test,
        _drop_schema,
        _reset_store_backend_cache_only,
    )

    base_dsn, schema = _configure_isolated_pg_test(tmp_path, monkeypatch)
    try:
        from app.search import service as search_service

        fallback_text = "orphaned derived fallback"
        oid, _ = search_service.ingest_object(
            kind="note",
            source_ref="unit-test://reconcile-absent-source",
            payload={"content": fallback_text, "text": fallback_text},
            text=fallback_text,
        )

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE store_vector_index "
                    "SET provider = %s, model = %s "
                    "WHERE object_id = %s",
                    ("legacy-provider", "legacy-model", oid),
                )
                cur.execute(
                    "SELECT count(*) AS total FROM store_objects WHERE object_id = %s",
                    (oid,),
                )
                assert cur.fetchone()["total"] == 0

        result = CliRunner().invoke(
            cli,
            ["index", "reconcile", "--backend", "pg", "--json", "--strict"],
            env=dict(os.environ),
        )
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["reconciled"] == 1
        assert summary["purged_non_indexable"] == 0
        assert summary["skipped"] == 0

        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload, provider, model FROM store_vector_index "
                    "WHERE object_id = %s",
                    (oid,),
                )
                vector_row = cur.fetchone()
                cur.execute(
                    "SELECT count(*) AS total FROM store_objects WHERE object_id = %s",
                    (oid,),
                )
                source_count = cur.fetchone()["total"]

        assert vector_row["payload"]["content"] == fallback_text
        assert vector_row["payload"]["text"] == fallback_text
        assert vector_row["provider"] == "mock"
        assert vector_row["model"] == "mock-embedding"
        assert source_count == 0
    finally:
        _reset_store_backend_cache_only()
        _drop_schema(base_dsn, schema)
