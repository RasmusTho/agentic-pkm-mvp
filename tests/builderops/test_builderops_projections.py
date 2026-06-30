from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.projections import (
    PROJECTION_SPECS,
    BuilderOpsProjectionGenerator,
    BuilderOpsValidationError,
)
from app.builderops.store import SqliteBuilderOpsStore


GENERATED_AT = "2026-06-01T12:00:00Z"


def _actor(actor_id: str = "codex") -> dict[str, str]:
    return {"actor_type": "agent", "id": actor_id}


@pytest.fixture()
def store(tmp_path: Path) -> SqliteBuilderOpsStore:
    s = SqliteBuilderOpsStore(tmp_path / "builderops.sqlite3")
    s.initialize()
    return s


def test_projection_headers_mark_views_as_generated_and_non_authoritative(
    store: SqliteBuilderOpsStore,
) -> None:
    generator = BuilderOpsProjectionGenerator(store)

    for projection_type in PROJECTION_SPECS:
        markdown = generator.render_projection(
            projection_type,
            generated_at=GENERATED_AT,
        )

        assert "State: Generated projection" in markdown
        assert "Authority: non-authoritative BuilderOps Vault projection" in markdown
        assert "Source of truth: BuilderOps Vault" in markdown
        assert f"Generated at: {GENERATED_AT}" in markdown
        assert f"Projection type: {projection_type}" in markdown


def test_learning_summary_projection_matches_seeded_builderops_records(
    store: SqliteBuilderOpsStore,
) -> None:
    store.create_learning_signal(
        id="lrn_projection_001",
        summary="Capture projection source refs",
        content="Projection output keeps source refs visible.",
        signal_type="workflow",
        source_refs=[
            {
                "ref_type": "github_issue",
                "ref": "#1505",
                "authority_surface": "github",
                "locator": "Acceptance Criteria",
            },
            {
                "ref_type": "repo_doc",
                "ref": "docs/learning-log.md",
                "authority_surface": "repo",
            },
        ],
        created_by=_actor(),
        created_at="2026-06-01T10:00:00Z",
        updated_at="2026-06-01T10:00:00Z",
    )

    markdown = BuilderOpsProjectionGenerator(store).render_projection(
        "learning-summary",
        generated_at=GENERATED_AT,
    )

    assert markdown == (
        "State: Generated projection\n"
        "Authority: non-authoritative BuilderOps Vault projection\n"
        "Source of truth: BuilderOps Vault\n"
        "Generated at: 2026-06-01T12:00:00Z\n"
        "Projection type: learning-summary\n"
        "Do not edit: regenerate from BuilderOps Vault records.\n"
        "\n"
        "# BuilderOps Learning Summary Projection\n"
        "\n"
        "LearningSignal records grouped into a repo-readable summary view.\n"
        "\n"
        "Generated projection over BuilderOps Vault records. This Markdown view is non-authoritative and does not replace BuilderOps Vault operational state.\n"
        "\n"
        "Record count: 1\n"
        "\n"
        "## Records\n"
        "\n"
        "### lrn_projection_001 - Capture projection source refs\n"
        "\n"
        "- Object type: LearningSignal\n"
        "- Lifecycle state: active\n"
        "- Promotion status: candidate\n"
        "- Authority class: operational\n"
        "- Created at: 2026-06-01T10:00:00Z\n"
        "- Updated at: 2026-06-01T10:00:00Z\n"
        "- Signal type: workflow\n"
        "- Content: Projection output keeps source refs visible.\n"
        "- Source refs:\n"
        "  - github_issue:#1505 (authority_surface=github; locator=Acceptance Criteria)\n"
        "  - repo_doc:docs/learning-log.md (authority_surface=repo)\n"
        "- Receipt refs: none\n"
    )


def test_queue_projection_metadata_counts_exclude_terminal_records(
    store: SqliteBuilderOpsStore,
    tmp_path: Path,
) -> None:
    queue_records = (
        (
            "docs-freshness",
            store.create_docs_freshness_record,
            {
                "id": "docsfresh_active_001",
                "summary": "Active docs freshness record",
                "doc_ref": {"ref_type": "repo_doc", "ref": "docs/active.md"},
                "owner": "BuilderOps governance",
                "review_cadence": "event-driven",
                "freshness_posture": "current",
                "drift_status": "none",
                "last_reviewed_at": "2026-06-01T00:00:00Z",
                "last_verified_against": [{"ref_type": "repo_doc", "ref": "docs/active.md"}],
                "last_verified_at": "2026-06-01T00:00:00Z",
                "next_review_due_at": "2026-06-08T00:00:00Z",
                "stale_reasons": ["none"],
                "freshness_evidence_refs": [{"ref_type": "github_issue", "ref": "#1001"}],
                "next_review_owner": "BuilderOps governance",
                "source_refs": [{"ref_type": "repo_doc", "ref": "docs/active.md"}],
                "created_by": _actor(),
            },
            (
                {
                    "id": "docsfresh_discarded_001",
                    "summary": "Discarded docs freshness record",
                    "doc_ref": {"ref_type": "repo_doc", "ref": "docs/discarded.md"},
                    "owner": "BuilderOps governance",
                    "review_cadence": "event-driven",
                    "freshness_posture": "likely_stale",
                    "drift_status": "confirmed_stale",
                    "last_reviewed_at": "2026-06-01T00:00:00Z",
                    "last_verified_against": [{"ref_type": "repo_doc", "ref": "docs/discarded.md"}],
                    "last_verified_at": "2026-06-01T00:00:00Z",
                    "next_review_due_at": "2026-06-08T00:00:00Z",
                    "stale_reasons": ["discarded"],
                    "freshness_evidence_refs": [{"ref_type": "github_issue", "ref": "#1002"}],
                    "next_review_owner": "BuilderOps governance",
                    "lifecycle_state": "discarded",
                    "promotion_status": "discarded",
                    "source_refs": [{"ref_type": "repo_doc", "ref": "docs/discarded.md"}],
                    "created_by": _actor(),
                },
                {
                    "id": "docsfresh_superseded_001",
                    "summary": "Superseded docs freshness record",
                    "doc_ref": {"ref_type": "repo_doc", "ref": "docs/superseded.md"},
                    "owner": "BuilderOps governance",
                    "review_cadence": "event-driven",
                    "freshness_posture": "likely_stale",
                    "drift_status": "confirmed_stale",
                    "last_reviewed_at": "2026-06-01T00:00:00Z",
                    "last_verified_against": [{"ref_type": "repo_doc", "ref": "docs/superseded.md"}],
                    "last_verified_at": "2026-06-01T00:00:00Z",
                    "next_review_due_at": "2026-06-08T00:00:00Z",
                    "stale_reasons": ["superseded"],
                    "freshness_evidence_refs": [{"ref_type": "github_issue", "ref": "#1003"}],
                    "next_review_owner": "BuilderOps governance",
                    "lifecycle_state": "superseded",
                    "promotion_status": "superseded",
                    "source_refs": [{"ref_type": "repo_doc", "ref": "docs/superseded.md"}],
                    "created_by": _actor(),
                },
            ),
        ),
        (
            "roadmap-execution",
            store.create_roadmap_execution_item,
            {
                "id": "roadexec_active_001",
                "summary": "Active roadmap execution item",
                "roadmap_ref": {"ref_type": "github_issue", "ref": "#2001"},
                "theme": "BuilderOps Vault",
                "capability": "queue rendering",
                "execution_state": "in_progress",
                "status": "active",
                "owner": "BuilderOps governance",
                "active_issues": [{"ref_type": "github_issue", "ref": "#2002"}],
                "blockers": ["none"],
                "last_movement": "Active item remains in progress.",
                "next_decision": "Continue queue rendering work.",
                "shipped_refs": [{"ref_type": "pull_request", "ref": "#2003"}],
                "source_refs": [{"ref_type": "github_issue", "ref": "#2001"}],
                "created_by": _actor(),
            },
            (
                {
                    "id": "roadexec_discarded_001",
                    "summary": "Discarded roadmap execution item",
                    "roadmap_ref": {"ref_type": "github_issue", "ref": "#2004"},
                    "theme": "BuilderOps Vault",
                    "capability": "queue rendering",
                    "execution_state": "done",
                    "status": "discarded",
                    "owner": "BuilderOps governance",
                    "active_issues": [{"ref_type": "github_issue", "ref": "#2004"}],
                    "blockers": ["discarded"],
                    "last_movement": "Superseded by a later execution item.",
                    "next_decision": "none",
                    "shipped_refs": [{"ref_type": "pull_request", "ref": "#2004"}],
                    "lifecycle_state": "discarded",
                    "promotion_status": "discarded",
                    "source_refs": [{"ref_type": "github_issue", "ref": "#2004"}],
                    "created_by": _actor(),
                },
                {
                    "id": "roadexec_superseded_001",
                    "summary": "Superseded roadmap execution item",
                    "roadmap_ref": {"ref_type": "github_issue", "ref": "#2005"},
                    "theme": "BuilderOps Vault",
                    "capability": "queue rendering",
                    "execution_state": "done",
                    "status": "superseded",
                    "owner": "BuilderOps governance",
                    "active_issues": [{"ref_type": "github_issue", "ref": "#2005"}],
                    "blockers": ["superseded"],
                    "last_movement": "Superseded by a later execution item.",
                    "next_decision": "none",
                    "shipped_refs": [{"ref_type": "pull_request", "ref": "#2005"}],
                    "lifecycle_state": "superseded",
                    "promotion_status": "superseded",
                    "source_refs": [{"ref_type": "github_issue", "ref": "#2005"}],
                    "created_by": _actor(),
                },
            ),
        ),
        (
            "promotion-queue",
            store.create_promotion_intent,
            {
                "id": "prom_active_001",
                "summary": "Active promotion intent",
                "target_authority_surface": "github_issue",
                "target_action": "create",
                "target_ref": "#3001",
                "target_authority_class": "operational",
                "intended_output": "Bounded GitHub issue",
                "source_refs": [{"ref_type": "github_issue", "ref": "#3001"}],
                "created_by": _actor(),
            },
            (
                {
                    "id": "prom_discarded_001",
                    "summary": "Discarded promotion intent",
                    "target_authority_surface": "github_issue",
                    "target_action": "create",
                    "target_ref": "#3002",
                    "target_authority_class": "operational",
                    "intended_output": "Discard receipt",
                    "lifecycle_state": "discarded",
                    "promotion_status": "discarded",
                    "source_refs": [{"ref_type": "github_issue", "ref": "#3002"}],
                    "created_by": _actor(),
                },
                {
                    "id": "prom_superseded_001",
                    "summary": "Superseded promotion intent",
                    "target_authority_surface": "github_issue",
                    "target_action": "create",
                    "target_ref": "#3003",
                    "target_authority_class": "operational",
                    "intended_output": "Superseded replacement",
                    "lifecycle_state": "superseded",
                    "promotion_status": "superseded",
                    "source_refs": [{"ref_type": "github_issue", "ref": "#3003"}],
                    "created_by": _actor(),
                },
            ),
        ),
    )

    for projection_type, creator, active_record, terminal_records in queue_records:
        creator(**active_record)
        for terminal_record in terminal_records:
            creator(**terminal_record)

        output_dir = tmp_path / projection_type
        result = BuilderOpsProjectionGenerator(store).write_projections(
            output_dir,
            projection_types=[projection_type],
            generated_at=GENERATED_AT,
        )

        assert result == [
            {
                "projection_type": projection_type,
                "object_type": PROJECTION_SPECS[projection_type].object_type,
                "path": str(output_dir / PROJECTION_SPECS[projection_type].filename),
                "record_count": 1,
                "generated_at": GENERATED_AT,
            }
        ]
        markdown = (output_dir / PROJECTION_SPECS[projection_type].filename).read_text(
            encoding="utf-8",
        )
        assert f"Projection type: {projection_type}" in markdown
        assert "Record count: 1" in markdown
        assert active_record["summary"] in markdown
        for terminal_record in terminal_records:
            assert terminal_record["summary"] not in markdown


def test_queue_projection_shrink_guard_uses_filtered_active_count(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "generated" / "builderops"

    existing_store = SqliteBuilderOpsStore(tmp_path / "existing.sqlite3")
    existing_store.initialize()
    existing_store.create_docs_freshness_record(
        id="docsfresh_existing_active_001",
        summary="Existing active docs freshness record 1",
        doc_ref={"ref_type": "repo_doc", "ref": "docs/existing-1.md"},
        owner="BuilderOps governance",
        review_cadence="event-driven",
        freshness_posture="current",
        drift_status="none",
        last_reviewed_at="2026-06-01T00:00:00Z",
        last_verified_against=[{"ref_type": "repo_doc", "ref": "docs/existing-1.md"}],
        last_verified_at="2026-06-01T00:00:00Z",
        next_review_due_at="2026-06-08T00:00:00Z",
        stale_reasons=["none"],
        freshness_evidence_refs=[{"ref_type": "github_issue", "ref": "#1001"}],
        next_review_owner="BuilderOps governance",
        source_refs=[{"ref_type": "repo_doc", "ref": "docs/existing-1.md"}],
        created_by=_actor(),
    )
    existing_store.create_docs_freshness_record(
        id="docsfresh_existing_active_002",
        summary="Existing active docs freshness record 2",
        doc_ref={"ref_type": "repo_doc", "ref": "docs/existing-2.md"},
        owner="BuilderOps governance",
        review_cadence="event-driven",
        freshness_posture="current",
        drift_status="none",
        last_reviewed_at="2026-06-01T00:00:00Z",
        last_verified_against=[{"ref_type": "repo_doc", "ref": "docs/existing-2.md"}],
        last_verified_at="2026-06-01T00:00:00Z",
        next_review_due_at="2026-06-08T00:00:00Z",
        stale_reasons=["none"],
        freshness_evidence_refs=[{"ref_type": "github_issue", "ref": "#1002"}],
        next_review_owner="BuilderOps governance",
        source_refs=[{"ref_type": "repo_doc", "ref": "docs/existing-2.md"}],
        created_by=_actor(),
    )
    BuilderOpsProjectionGenerator(existing_store).write_projections(
        output_dir,
        projection_types=["docs-freshness"],
        generated_at=GENERATED_AT,
    )

    incomplete_store = SqliteBuilderOpsStore(tmp_path / "incomplete.sqlite3")
    incomplete_store.initialize()
    incomplete_store.create_docs_freshness_record(
        id="docsfresh_incomplete_active_001",
        summary="Incomplete active docs freshness record",
        doc_ref={"ref_type": "repo_doc", "ref": "docs/incomplete.md"},
        owner="BuilderOps governance",
        review_cadence="event-driven",
        freshness_posture="current",
        drift_status="none",
        last_reviewed_at="2026-06-01T00:00:00Z",
        last_verified_against=[{"ref_type": "repo_doc", "ref": "docs/incomplete.md"}],
        last_verified_at="2026-06-01T00:00:00Z",
        next_review_due_at="2026-06-08T00:00:00Z",
        stale_reasons=["none"],
        freshness_evidence_refs=[{"ref_type": "github_issue", "ref": "#1003"}],
        next_review_owner="BuilderOps governance",
        source_refs=[{"ref_type": "repo_doc", "ref": "docs/incomplete.md"}],
        created_by=_actor(),
    )
    incomplete_store.create_docs_freshness_record(
        id="docsfresh_incomplete_discarded_001",
        summary="Incomplete discarded docs freshness record",
        doc_ref={"ref_type": "repo_doc", "ref": "docs/incomplete.md"},
        owner="BuilderOps governance",
        review_cadence="event-driven",
        freshness_posture="likely_stale",
        drift_status="confirmed_stale",
        last_reviewed_at="2026-06-01T00:00:00Z",
        last_verified_against=[{"ref_type": "repo_doc", "ref": "docs/incomplete.md"}],
        last_verified_at="2026-06-01T00:00:00Z",
        next_review_due_at="2026-06-08T00:00:00Z",
        stale_reasons=["discarded"],
        freshness_evidence_refs=[{"ref_type": "github_issue", "ref": "#1004"}],
        next_review_owner="BuilderOps governance",
        lifecycle_state="discarded",
        promotion_status="discarded",
        source_refs=[{"ref_type": "repo_doc", "ref": "docs/incomplete.md"}],
        created_by=_actor(),
    )

    with pytest.raises(BuilderOpsValidationError, match="selected store appears incomplete"):
        BuilderOpsProjectionGenerator(incomplete_store).write_projections(
            output_dir,
            projection_types=["docs-freshness"],
            generated_at=GENERATED_AT,
        )


def test_learning_summary_keeps_terminal_learning_records(
    store: SqliteBuilderOpsStore,
) -> None:
    store.create_learning_signal(
        id="lrn_learning_active_001",
        summary="Active learning signal",
        content="Active learning content.",
        signal_type="workflow",
        source_refs=[{"ref_type": "github_issue", "ref": "#4001"}],
        receipt_refs=["receipt_lrn_active_001"],
        created_by=_actor(),
    )
    store.create_learning_signal(
        id="lrn_learning_discarded_001",
        summary="Discarded learning signal",
        content="Discarded learning content.",
        signal_type="workflow",
        lifecycle_state="discarded",
        promotion_status="discarded",
        source_refs=[{"ref_type": "github_issue", "ref": "#4002"}],
        receipt_refs=["receipt_lrn_discarded_001"],
        created_by=_actor(),
    )
    store.create_learning_signal(
        id="lrn_learning_superseded_001",
        summary="Superseded learning signal",
        content="Superseded learning content.",
        signal_type="workflow",
        lifecycle_state="superseded",
        promotion_status="superseded",
        source_refs=[{"ref_type": "github_issue", "ref": "#4003"}],
        receipt_refs=["receipt_lrn_superseded_001"],
        created_by=_actor(),
    )

    markdown = BuilderOpsProjectionGenerator(store).render_projection(
        "learning-summary",
        generated_at=GENERATED_AT,
    )

    assert "Record count: 3" in markdown
    assert "Active learning signal" in markdown
    assert "Discarded learning signal" in markdown
    assert "Superseded learning signal" in markdown
    assert "receipt_lrn_discarded_001" in markdown
    assert "receipt_lrn_superseded_001" in markdown


def test_write_projections_emits_expected_repo_markdown_files(
    store: SqliteBuilderOpsStore,
    tmp_path: Path,
) -> None:
    store.create_docs_freshness_record(
        id="docsfresh_projection_001",
        summary="DOCS_INDEX freshness checked",
        doc_ref={"ref_type": "repo_doc", "ref": "docs/DOCS_INDEX.md"},
        owner="Documentation role map",
        review_cadence="event-driven",
        freshness_posture="current",
        drift_status="none",
        last_reviewed_at="2026-06-01T00:00:00Z",
        last_verified_against=[{"ref_type": "repo_doc", "ref": "docs/ARCHITECTURE.md"}],
        last_verified_at="2026-06-01T01:00:00Z",
        next_review_due_at="2026-06-15T00:00:00Z",
        stale_reasons=["none"],
        freshness_evidence_refs=[{"ref_type": "github_issue", "ref": "#1507"}],
        next_review_owner="BuilderOps governance",
        source_refs=[{"ref_type": "repo_doc", "ref": "docs/DOCS_INDEX.md"}],
        created_by=_actor(),
    )
    store.create_roadmap_execution_item(
        id="roadexec_projection_001",
        summary="BuilderOps projection issue active",
        roadmap_ref={"ref_type": "github_issue", "ref": "#1498"},
        theme="BuilderOps Vault",
        capability="shared operating plane",
        execution_state="in_progress",
        status="active",
        owner="BuilderOps governance",
        active_issues=[{"ref_type": "github_issue", "ref": "#1508"}],
        blockers=["none"],
        last_movement="PR #1519 merged #1507.",
        next_decision="Continue with #1508 after #1507 merges.",
        shipped_refs=[{"ref_type": "pull_request", "ref": "#1519"}],
        source_refs=[{"ref_type": "github_issue", "ref": "#1505"}],
        created_by=_actor(),
    )
    store.create_promotion_intent(
        id="prom_projection_001",
        summary="Promote generated projection docs",
        target_authority_surface="generated_projection",
        target_action="write",
        target_ref="docs/generated/builderops/learning-summary.md",
        target_authority_class="projection",
        intended_output="Write non-authoritative projection Markdown.",
        source_refs=[{"ref_type": "github_issue", "ref": "#1505"}],
        created_by=_actor(),
    )
    store.create_learning_signal(
        id="lrn_projection_active_001",
        summary="Projection write keeps terminal learning history",
        content="Learning summary metadata still counts terminal records.",
        signal_type="workflow",
        source_refs=[{"ref_type": "github_issue", "ref": "#1505"}],
        created_by=_actor(),
    )
    store.create_learning_signal(
        id="lrn_projection_discarded_001",
        summary="Discarded projection learning history",
        content="Discarded learning summary content.",
        signal_type="workflow",
        lifecycle_state="discarded",
        promotion_status="discarded",
        source_refs=[{"ref_type": "github_issue", "ref": "#1506"}],
        receipt_refs=["receipt_lrn_projection_discarded_001"],
        created_by=_actor(),
    )
    store.create_learning_signal(
        id="lrn_projection_superseded_001",
        summary="Superseded projection learning history",
        content="Superseded learning summary content.",
        signal_type="workflow",
        lifecycle_state="superseded",
        promotion_status="superseded",
        source_refs=[{"ref_type": "github_issue", "ref": "#1507"}],
        receipt_refs=["receipt_lrn_projection_superseded_001"],
        created_by=_actor(),
    )

    output_dir = tmp_path / "generated" / "builderops"
    result = BuilderOpsProjectionGenerator(store).write_projections(
        output_dir,
        generated_at=GENERATED_AT,
    )

    assert [item["projection_type"] for item in result] == [
        "docs-freshness",
        "learning-summary",
        "promotion-queue",
        "roadmap-execution",
    ]
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "docs-freshness.md",
        "learning-summary.md",
        "promotion-queue.md",
        "roadmap-execution.md",
    ]
    result_by_type = {item["projection_type"]: item for item in result}
    assert result_by_type["learning-summary"]["record_count"] == 3
    docs_freshness = (output_dir / "docs-freshness.md").read_text(encoding="utf-8")
    assert "- Drift status: none" in docs_freshness
    assert "- Last verified against: repo_doc:docs/ARCHITECTURE.md" in docs_freshness
    assert "- Last verified at: 2026-06-01T01:00:00Z" in docs_freshness
    assert "- Stale reasons: none" in docs_freshness
    assert "- Freshness evidence refs: github_issue:#1507" in docs_freshness
    assert "- Next review owner: BuilderOps governance" in docs_freshness
    roadmap_execution = (output_dir / "roadmap-execution.md").read_text(encoding="utf-8")
    assert "- Theme: BuilderOps Vault" in roadmap_execution
    assert "- Capability: shared operating plane" in roadmap_execution
    assert "- Status: active" in roadmap_execution
    assert "- Active issues: github_issue:#1508" in roadmap_execution
    assert "- Blockers: none" in roadmap_execution
    assert "- Last movement: PR #1519 merged #1507." in roadmap_execution
    assert "- Shipped refs: pull_request:#1519" in roadmap_execution
    learning_summary = (output_dir / "learning-summary.md").read_text(encoding="utf-8")
    assert "Record count: 3" in learning_summary
    assert "Projection write keeps terminal learning history" in learning_summary
    assert "Discarded projection learning history" in learning_summary
    assert "Superseded projection learning history" in learning_summary
    promotion_queue = (output_dir / "promotion-queue.md").read_text(encoding="utf-8")
    assert "Source of truth: BuilderOps Vault" in promotion_queue
    assert "non-authoritative" in promotion_queue
    assert "prom_projection_001" in promotion_queue
    assert "github_issue:#1505" in promotion_queue
