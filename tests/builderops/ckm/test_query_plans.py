from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from app.builderops.ckm.contracts import ACCESS_POLICY_VERSION
from app.builderops.ckm.models import CkmValidationError, MATURITY_DIMENSIONS
from app.builderops.ckm.overview_html import render_overview_html
from app.builderops.ckm.projections import render_projection
from app.builderops.ckm.query_service import CkmQueryService
from app.builderops.ckm.schema import CKM_REQUIRED_QUERY_INDEXES
from app.builderops.ckm.store import CkmProjectionCaptureError, CkmStore
from tests.builderops.ckm.test_query_service import _mixed_epoch_payload


def _populated(tmp_path: Path, *, count: int = 3) -> tuple[CkmStore, list, object, object]:
    store = CkmStore(tmp_path / "ckm.sqlite")
    store.ensure_schema()
    root = store.upsert_capability(identity_key="root", name="root", definition="root", lifecycle="confirmed", existence_provenance="fixture")
    capabilities = [root]
    for index in range(1, count):
        capabilities.append(store.upsert_capability(identity_key=f"child:{index}", name=f"child-{index:03d}", definition="child", parent_id=root.id if index == 1 else None, lifecycle="confirmed", existence_provenance="fixture"))
    linked = store.upsert_artifact(source_ref="repo:linked", artifact_kind="source_file", source="repo", watermark="one", provenance="fixture")
    unlinked = store.upsert_artifact(source_ref="repo:unlinked", artifact_kind="source_file", source="repo", watermark="one", provenance="fixture")
    store.upsert_evidence_edge(artifact_id=linked.id, capability_id=root.id, evidence_kind="source", polarity="supports", maturity_dimension="functional_completeness", confidence=1.0, extraction_method="deterministic", lifecycle="confirmed", source_ref="repo:linked")
    store.set_watermark("repo", "one")
    store.append_assessment(capability_id=root.id, scores={key: 0.5 for key in MATURITY_DIMENSIONS}, citations={key: [] for key in MATURITY_DIMENSIONS}, aggregate=0.5, watermark_set={"repo": "one"})
    store.upsert_finding(kind="gap", capability_id=root.id, dimension="functional_completeness", statement="fixture gap", citations=[{"artifact_id": linked.id, "artifact": linked.to_dict()}])
    return store, capabilities, linked, unlinked


def test_bounded_filters_preserve_q1_completeness_contract(tmp_path: Path) -> None:
    store, capabilities, linked, unlinked = _populated(tmp_path)
    service = CkmQueryService(store.db_path)
    ids = [capabilities[1].public_id, capabilities[0].public_id]
    selected = service.list_resources("capability", filters={"public_ids": ids}).to_dict()
    assert [item["public_id"] for item in selected["resources"]] == sorted(ids)
    assert selected["snapshot"]["completeness"]["object_classes"] == [{"object_class": "capability", "included": 2, "filtered": 1, "omitted": 0, "truncated": 0}]
    assert selected == service.list_resources("capability", filters={"public_ids": list(reversed(ids))}).to_dict()
    subtree = service.list_resources("capability", filters={"subtree_root_public_id": capabilities[0].public_id}).to_dict()
    assert [item["display_name"] for item in subtree["resources"]] == ["child-001", "root"]
    for resource_type in ("evidence_edge", "assessment", "finding"):
        payload = service.list_resources(resource_type, filters={"capability_public_id": capabilities[0].public_id}).to_dict()
        assert len(payload["resources"]) == 1 and payload["snapshot"]["completeness"]["complete"] is True
    artifacts = service.list_resources("artifact", filters={"unlinked": True}).to_dict()
    assert [item["public_id"] for item in artifacts["resources"]] == [unlinked.public_id]
    assert linked.public_id != unlinked.public_id


def _statement_count(store: CkmStore, public_ids: list[str]) -> tuple[int, dict]:
    statements: list[str] = []
    original = sqlite3.connect
    def connect(uri: str) -> sqlite3.Connection:
        conn = original(uri, uri=True)
        conn.set_trace_callback(statements.append)
        return conn
    result = CkmQueryService(store.db_path, capture_limit=1000, _connection_factory=connect).list_resources("capability", filters={"public_ids": public_ids}).to_dict()
    selects = [statement for statement in statements if statement.lstrip().upper().startswith(("SELECT", "WITH"))]
    return len(selects), result


def test_batch_read_plan_has_constant_query_count(tmp_path: Path) -> None:
    small, small_caps, _, _ = _populated(tmp_path / "small", count=3)
    large, large_caps, _, _ = _populated(tmp_path / "large", count=500)
    small_count, small_result = _statement_count(small, [item.public_id for item in small_caps])
    large_count, large_result = _statement_count(large, [item.public_id for item in large_caps])
    assert small_count == large_count
    assert small_result["resources"] == CkmQueryService(small.db_path).list_capabilities().to_dict()["resources"]
    assert len(large_result["resources"]) == 500


def test_supported_filters_use_required_indexes(tmp_path: Path) -> None:
    store, capabilities, linked, _ = _populated(tmp_path)
    with sqlite3.connect(store.db_path) as conn:
        for index in CKM_REQUIRED_QUERY_INDEXES:
            conn.execute(f"DROP INDEX {index}")
    store.ensure_schema()
    with sqlite3.connect(store.db_path) as conn:
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert CKM_REQUIRED_QUERY_INDEXES <= indexes
        plans = " ".join(
            row[3]
            for statement, params in (
                ("SELECT * FROM ckm_capability WHERE parent_id = ? ORDER BY public_id", (capabilities[0].id,)),
                ("SELECT * FROM ckm_evidence_edge WHERE capability_id = ? ORDER BY public_id", (capabilities[0].id,)),
                ("SELECT * FROM ckm_evidence_edge WHERE artifact_id = ? ORDER BY public_id", (linked.id,)),
                ("SELECT * FROM ckm_assessment WHERE capability_id = ? ORDER BY asserted_at, public_id", (capabilities[0].id,)),
                ("SELECT * FROM ckm_finding WHERE capability_id = ? ORDER BY public_id", (capabilities[0].id,)),
            )
            for row in conn.execute(f"EXPLAIN QUERY PLAN {statement}", params)
        )
    assert CKM_REQUIRED_QUERY_INDEXES <= {name for name in CKM_REQUIRED_QUERY_INDEXES if name in plans}


def _projection_select_count(store: CkmStore) -> int:
    statements: list[str] = []
    original = store._readonly_connect
    def traced() -> sqlite3.Connection:
        conn = original()
        conn.set_trace_callback(statements.append)
        return conn
    store._readonly_connect = traced  # type: ignore[method-assign]
    render_projection(store, "ckm-maturity")
    render_overview_html(store, generated_at="2026-07-21T00:00:00Z")
    return len([item for item in statements if item.lstrip().upper().startswith("SELECT")])


def test_projection_consumers_do_not_regress_to_n_plus_one(tmp_path: Path) -> None:
    small, _, _, _ = _populated(tmp_path / "small", count=3)
    large, _, _, _ = _populated(tmp_path / "large", count=30)
    assert _projection_select_count(small) == _projection_select_count(large)

    missing_path = tmp_path / "missing" / "ckm.sqlite"
    with pytest.raises(CkmValidationError, match="does not exist"):
        render_projection(CkmStore(missing_path), "ckm-maturity")
    assert not missing_path.parent.exists()

    outdated, _, _, _ = _populated(tmp_path / "outdated")
    with sqlite3.connect(outdated.db_path) as conn:
        conn.execute("UPDATE ckm_state SET schema_version = 0")
    before = outdated.db_path.read_bytes()
    with pytest.raises(CkmValidationError, match="unsupported state row"):
        render_overview_html(outdated)
    assert outdated.db_path.read_bytes() == before


def test_projection_batch_snapshot_prevents_concurrent_revision_mix(
    tmp_path: Path,
) -> None:
    store, capabilities, _, _ = _populated(tmp_path)
    wal_keeper = sqlite3.connect(store.db_path)
    assert wal_keeper.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    wal_keeper.execute("UPDATE ckm_state SET updated_at = updated_at WHERE singleton = 1")
    wal_keeper.commit()
    original = store._readonly_connect
    writer_done = threading.Event()
    writer_errors: list[Exception] = []
    writer_started = False

    def write_revision() -> None:
        try:
            with sqlite3.connect(store.db_path, timeout=5) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE ckm_state SET state_revision = state_revision + 1 "
                    "WHERE singleton = 1"
                )
                conn.commit()
        except Exception as exc:  # pragma: no cover - asserted below
            writer_errors.append(exc)
        finally:
            writer_done.set()

    def traced() -> sqlite3.Connection:
        conn = original()

        def on_statement(statement: str) -> None:
            nonlocal writer_started
            if writer_started or not statement.startswith("SELECT * FROM ckm_capability"):
                return
            writer_started = True
            threading.Thread(target=write_revision, daemon=True).start()
            assert writer_done.wait(timeout=2)

        conn.set_trace_callback(on_statement)
        return conn

    store._readonly_connect = traced  # type: ignore[method-assign]
    batch = store.load_projection_batch()
    assert not writer_errors
    assert batch.capabilities == tuple(
        sorted(capabilities, key=lambda item: (item.name, item.id))
    )
    assert store.load_projection_batch().state_identity.state_revision == (
        batch.state_identity.state_revision + 1
    )
    wal_keeper.close()


def test_projection_batch_refuses_mixed_database_identity(tmp_path: Path) -> None:
    store, _, _, _ = _populated(tmp_path / "original")
    replacement, _, _, _ = _populated(tmp_path / "replacement")
    original = store._readonly_connect
    replaced = False

    def traced() -> sqlite3.Connection:
        conn = original()

        def on_statement(statement: str) -> None:
            nonlocal replaced
            if replaced or not statement.startswith("SELECT * FROM ckm_capability"):
                return
            replaced = True
            replacement.db_path.replace(store.db_path)

        conn.set_trace_callback(on_statement)
        return conn

    store._readonly_connect = traced  # type: ignore[method-assign]
    with pytest.raises(CkmProjectionCaptureError) as refusal:
        store.load_projection_batch()
    assert refusal.value.code == "mixed_epoch"
    assert "identity changed" in str(refusal.value)


def test_projection_batch_refuses_over_bound_before_materialization(
    tmp_path: Path,
) -> None:
    store, _, _, _ = _populated(tmp_path, count=4)
    statements: list[str] = []
    original = store._readonly_connect

    def traced() -> sqlite3.Connection:
        conn = original()
        conn.set_trace_callback(statements.append)
        return conn

    store._readonly_connect = traced  # type: ignore[method-assign]
    before = store.db_path.read_bytes()
    with pytest.raises(CkmProjectionCaptureError) as class_refusal:
        store.load_projection_batch(class_capture_limit=3)
    assert class_refusal.value.code == "snapshot_too_large"
    assert class_refusal.value.details["over_bound_classes"] == {"capability": 4}
    with pytest.raises(CkmProjectionCaptureError) as aggregate_refusal:
        store.load_projection_batch(
            class_capture_limit=100,
            aggregate_capture_limit=3,
        )
    assert aggregate_refusal.value.code == "snapshot_too_large"
    assert aggregate_refusal.value.details["aggregate_count"] > 3
    assert not any(statement.startswith("SELECT * FROM") for statement in statements)
    assert store.db_path.read_bytes() == before


def test_query_optimization_cannot_weaken_q1_bounds(tmp_path: Path) -> None:
    store, capabilities, _, _ = _populated(tmp_path)
    service = CkmQueryService(store.db_path, capture_limit=2)
    for filters in ({"unknown": True}, {"public_ids": [item.public_id for item in capabilities]}, {"unlinked": False}):
        resource_type = "artifact" if "unlinked" in filters else "capability"
        refusal = service.list_resources(resource_type, filters=filters).to_dict()
        assert refusal["error"]["code"] in {"unsupported_filter", "snapshot_too_large"} and "resources" not in refusal
    complete = CkmQueryService(store.db_path).list_capabilities().to_dict()
    assert [item["public_id"] for item in complete["resources"]] == sorted(item.public_id for item in capabilities)
    assert complete["snapshot"]["completeness"]["complete"] is True
    assert complete["snapshot"]["access_policy_version"] == ACCESS_POLICY_VERSION
    mixed = _mixed_epoch_payload(store.db_path)
    assert mixed["error"]["code"] == "mixed_epoch" and "resources" not in mixed


def test_related_resource_bounds_refuse_before_materializing_rows(tmp_path: Path) -> None:
    store, capabilities, _, _ = _populated(tmp_path, count=3)
    statements: list[str] = []
    original = sqlite3.connect

    def connect(uri: str) -> sqlite3.Connection:
        conn = original(uri, uri=True)
        conn.set_trace_callback(statements.append)
        return conn

    service = CkmQueryService(store.db_path, capture_limit=1, _connection_factory=connect)
    result = service.list_resources("evidence_edge", filters={"capability_public_id": capabilities[0].public_id}).to_dict()
    assert result["resources"]

    oversized = service.list_resources("artifact").to_dict()
    assert oversized["error"]["code"] == "snapshot_too_large"
    assert "resources" not in oversized
    after_error = statements[statements.index(next(item for item in statements if "COUNT(*) FROM (SELECT resource.* FROM ckm_artifact" in item)) :]
    assert not any("SELECT resource.* FROM ckm_artifact" in item for item in after_error[1:])
