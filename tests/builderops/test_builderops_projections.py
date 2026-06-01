from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.projections import PROJECTION_SPECS, BuilderOpsProjectionGenerator
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
        execution_state="in_progress",
        owner="BuilderOps governance",
        next_decision="Continue with #1506 after #1505 merges.",
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
    docs_freshness = (output_dir / "docs-freshness.md").read_text(encoding="utf-8")
    assert "- Drift status: none" in docs_freshness
    assert "- Last verified against: repo_doc:docs/ARCHITECTURE.md" in docs_freshness
    assert "- Last verified at: 2026-06-01T01:00:00Z" in docs_freshness
    assert "- Stale reasons: none" in docs_freshness
    assert "- Freshness evidence refs: github_issue:#1507" in docs_freshness
    assert "- Next review owner: BuilderOps governance" in docs_freshness
    promotion_queue = (output_dir / "promotion-queue.md").read_text(encoding="utf-8")
    assert "Source of truth: BuilderOps Vault" in promotion_queue
    assert "non-authoritative" in promotion_queue
    assert "prom_projection_001" in promotion_queue
    assert "github_issue:#1505" in promotion_queue
