from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.builderops.config import load_paths
from app.builderops.models import BuilderOpsValidationError
from app.builderops.schema import SCHEMA_VERSION
from app.builderops.store import SqliteBuilderOpsStore


def _source_ref(ref: str = "#1501") -> list[dict[str, str]]:
    return [{"ref_type": "github_issue", "ref": ref, "authority_surface": "github"}]


def _actor(actor_id: str = "codex") -> dict[str, str]:
    return {"actor_type": "agent", "id": actor_id}


@pytest.fixture()
def store(tmp_path: Path) -> SqliteBuilderOpsStore:
    s = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    s.initialize()
    return s


def test_initialize_creates_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "builderops.sqlite3"
    store = SqliteBuilderOpsStore(db_path)
    store.initialize()
    store.initialize()

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"builderops_records", "builderops_meta"} <= names
        version = conn.execute(
            "SELECT value FROM builderops_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert version == str(SCHEMA_VERSION)


def test_create_read_list_core_builderops_records(store: SqliteBuilderOpsStore) -> None:
    worklog = store.create_agent_worklog(
        id="awl_test_001",
        summary="Worklog",
        body="Captured #1501 implementation context.",
        task_context={"issue": "#1501"},
        source_refs=_source_ref(),
        created_by=_actor(),
    )
    learning = store.create_learning_signal(
        id="lrn_test_001",
        summary="Learning",
        content="BuilderOps records need source refs.",
        signal_type="workflow",
        source_refs=_source_ref(),
        created_by=_actor(),
    )
    promotion = store.create_promotion_intent(
        id="prom_test_001",
        summary="Promotion",
        target_authority_surface="github_issue",
        target_action="create",
        target_ref="pending",
        target_authority_class="operational",
        intended_output="Draft a follow-up issue.",
        source_refs=[
            {
                "ref_type": "builderops_object",
                "ref": learning["id"],
                "authority_surface": "builderops",
            }
        ],
        created_by=_actor(),
    )
    docs = store.create_docs_freshness_record(
        id="docsfresh_test_001",
        summary="Docs freshness",
        doc_ref={"ref_type": "repo_doc", "ref": "docs/DOCS_INDEX.md"},
        owner="Documentation role map",
        review_cadence="event-driven",
        freshness_posture="current",
        last_reviewed_at="2026-06-01T00:00:00Z",
        next_review_due_at="2026-06-15T00:00:00Z",
        source_refs=[{"ref_type": "repo_doc", "ref": "docs/DOCS_INDEX.md"}],
        created_by=_actor(),
    )
    roadmap = store.create_roadmap_execution_item(
        id="roadexec_test_001",
        summary="Roadmap execution",
        roadmap_ref={"ref_type": "repo_doc", "ref": "docs/ROADMAP.md"},
        execution_state="in_progress",
        owner="BuilderOps governance",
        next_decision="Continue with #1502 after #1501 merges.",
        source_refs=[{"ref_type": "github_issue", "ref": "#1498"}],
        created_by=_actor(),
    )
    receipt = store.append_receipt(
        id="receipt_test_001",
        summary="Created worklog",
        event_type="object_created",
        actor=_actor(),
        occurred_at="2026-06-01T00:00:00Z",
        target_refs=[
            {
                "ref_type": "builderops_object",
                "ref": worklog["id"],
                "authority_surface": "builderops",
            }
        ],
        action="create",
        receipt_body="Created worklog for #1501 test.",
        idempotency_key="object_created:awl_test_001",
        source_refs=_source_ref(),
        created_by=_actor(),
    )

    assert store.get_record(worklog["id"]) == worklog
    assert store.get_record(learning["id"]) == learning
    assert store.get_record(promotion["id"]) == promotion
    assert store.get_record(docs["id"]) == docs
    assert store.get_record(roadmap["id"]) == roadmap
    assert store.get_record(receipt["id"]) == receipt

    listed = store.list_records()
    assert [record["id"] for record in listed] == [
        "awl_test_001",
        "lrn_test_001",
        "prom_test_001",
        "docsfresh_test_001",
        "roadexec_test_001",
        "receipt_test_001",
    ]
    assert [record["id"] for record in store.list_records("LearningSignal")] == [
        "lrn_test_001"
    ]


def test_store_supports_retro_cluster_member_ids(
    store: SqliteBuilderOpsStore,
) -> None:
    cluster = store.create_retro_cluster(
        id="retro_test_001",
        summary="Retro cluster",
        analysis="Two delivery signals share a root cause.",
        cluster_subject="pickup_state",
        member_refs=["lrn_test_001", "awl_test_001"],
        source_refs=[{"ref_type": "builderops_object", "ref": "lrn_test_001"}],
        created_by=_actor(),
    )

    assert store.get_record(cluster["id"])["member_refs"] == [
        "lrn_test_001",
        "awl_test_001",
    ]


def test_store_preserves_source_refs_and_promotion_status(
    store: SqliteBuilderOpsStore,
) -> None:
    record = store.create_learning_signal(
        id="lrn_test_refs",
        summary="Promotion candidate",
        content="Round-trip promotion status and provenance.",
        signal_type="workflow",
        promotion_status="promotion_pending",
        source_refs=[
            {
                "ref_type": "github_issue",
                "ref": "#1501",
                "locator": "Acceptance Criteria",
                "authority_surface": "github",
            }
        ],
        created_by=_actor(),
    )

    fetched = store.get_record(record["id"])
    assert fetched is not None
    assert fetched["promotion_status"] == "promotion_pending"
    assert fetched["source_refs"] == record["source_refs"]


def test_invalid_object_type_rejected(store: SqliteBuilderOpsStore) -> None:
    with pytest.raises(BuilderOpsValidationError, match="unsupported object_type"):
        store.create_record(
            {
                "object_type": "ProductRuntimeTruth",
                "summary": "invalid",
                "source_refs": _source_ref(),
            }
        )


def test_required_fields_and_source_refs_enforced(
    store: SqliteBuilderOpsStore,
) -> None:
    with pytest.raises(BuilderOpsValidationError, match="missing required"):
        store.create_agent_worklog(
            summary="Missing body",
            task_context={"issue": "#1501"},
            source_refs=_source_ref(),
            created_by=_actor(),
        )

    with pytest.raises(BuilderOpsValidationError, match="source_refs must be"):
        store.create_learning_signal(
            summary="Missing source refs",
            content="No provenance.",
            signal_type="workflow",
            source_refs=[],
            created_by=_actor(),
        )


def test_store_uses_configured_path(tmp_path: Path) -> None:
    configured = tmp_path / "state" / "custom-builderops.sqlite3"
    paths = load_paths({"BUILDEROPS_DB_PATH": str(configured)})
    store = SqliteBuilderOpsStore(paths.db_path)
    store.initialize()

    assert paths.db_path == configured
    assert configured.exists()


def test_receipts_are_not_promotable(store: SqliteBuilderOpsStore) -> None:
    with pytest.raises(BuilderOpsValidationError, match="must be not_promotable"):
        store.append_receipt(
            summary="Bad receipt",
            event_type="object_created",
            actor=_actor(),
            occurred_at="2026-06-01T00:00:00Z",
            target_refs=[{"ref_type": "builderops_object", "ref": "awl_test_001"}],
            action="create",
            receipt_body="Bad receipt.",
            idempotency_key="bad-receipt",
            source_refs=_source_ref(),
            created_by=_actor(),
            promotion_status="candidate",
        )


def test_object_specific_authority_and_lifecycle_constraints(
    store: SqliteBuilderOpsStore,
) -> None:
    with pytest.raises(BuilderOpsValidationError, match="authority_class must be"):
        store.append_receipt(
            summary="Bad receipt authority",
            event_type="object_created",
            actor=_actor(),
            occurred_at="2026-06-01T00:00:00Z",
            target_refs=[{"ref_type": "builderops_object", "ref": "awl_test_001"}],
            action="create",
            receipt_body="Bad authority.",
            idempotency_key="bad-receipt-authority",
            source_refs=_source_ref(),
            created_by=_actor(),
            authority_class="raw",
        )

    with pytest.raises(BuilderOpsValidationError, match="lifecycle_state must be"):
        store.append_receipt(
            summary="Bad receipt lifecycle",
            event_type="object_created",
            actor=_actor(),
            occurred_at="2026-06-01T00:00:00Z",
            target_refs=[{"ref_type": "builderops_object", "ref": "awl_test_001"}],
            action="create",
            receipt_body="Bad lifecycle.",
            idempotency_key="bad-receipt-lifecycle",
            source_refs=_source_ref(),
            created_by=_actor(),
            lifecycle_state="discarded",
        )

    with pytest.raises(BuilderOpsValidationError, match="authority_class must be"):
        store.create_agent_worklog(
            summary="Bad worklog authority",
            body="Worklogs cannot be decision authority.",
            task_context={"issue": "#1501"},
            source_refs=_source_ref(),
            created_by=_actor(),
            authority_class="decision",
        )
