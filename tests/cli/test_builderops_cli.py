from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli


def _run(args: list[str]):
    return CliRunner().invoke(cli, args, catch_exceptions=False)


def _json(output: str):
    return json.loads(output)


def test_builderops_cli_create_list_read_worklog(tmp_path: Path) -> None:
    db_path = tmp_path / "builderops.sqlite3"

    created = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "create-worklog",
            "--summary",
            "CLI worklog",
            "--body",
            "Captured via CLI.",
            "--task-context",
            '{"issue":"#1501"}',
            "--source-ref",
            "github_issue:#1501",
            "--created-by",
            "codex",
            "--idempotency-key",
            "cli:create-worklog",
            "--json",
        ]
    )
    assert created.exit_code == 0, created.output
    record = _json(created.output)
    assert record["object_type"] == "AgentWorklog"
    assert record["idempotency_key"] == "cli:create-worklog"
    assert record["source_refs"] == [{"ref_type": "github_issue", "ref": "#1501"}]

    duplicate = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "create-worklog",
            "--summary",
            "CLI worklog",
            "--body",
            "Captured via CLI.",
            "--task-context",
            '{"issue":"#1501"}',
            "--source-ref",
            "github_issue:#1501",
            "--created-by",
            "codex",
            "--idempotency-key",
            "cli:create-worklog",
            "--json",
        ]
    )
    assert duplicate.exit_code == 0, duplicate.output
    assert _json(duplicate.output) == record

    listed = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "list",
            "--type",
            "AgentWorklog",
            "--json",
        ]
    )
    assert listed.exit_code == 0, listed.output
    assert [item["id"] for item in _json(listed.output)] == [record["id"]]

    read = _run(
        ["builderops", "--db-path", str(db_path), "read", record["id"], "--json"]
    )
    assert read.exit_code == 0, read.output
    assert _json(read.output) == record


def test_builderops_cli_create_core_records_and_receipt(tmp_path: Path) -> None:
    db_path = tmp_path / "builderops.sqlite3"

    learning = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "create-learning-signal",
            "--summary",
            "CLI learning",
            "--content",
            "A workflow signal.",
            "--signal-type",
            "workflow",
            "--source-ref",
            "github_issue:#1501",
            "--json",
        ]
    )
    assert learning.exit_code == 0, learning.output
    learning_record = _json(learning.output)
    assert learning_record["object_type"] == "LearningSignal"
    assert learning_record["promotion_status"] == "candidate"

    promotion = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "create-promotion-intent",
            "--summary",
            "CLI promotion",
            "--target-authority-surface",
            "github_issue",
            "--target-action",
            "create",
            "--target-ref",
            "pending",
            "--target-authority-class",
            "operational",
            "--intended-output",
            "Draft follow-up issue.",
            "--source-ref",
            f"builderops_object:{learning_record['id']}",
            "--json",
        ]
    )
    assert promotion.exit_code == 0, promotion.output
    assert _json(promotion.output)["object_type"] == "PromotionIntent"

    freshness = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "create-docs-freshness-record",
            "--summary",
            "CLI freshness",
            "--doc-ref",
            "repo_doc:docs/DOCS_INDEX.md",
            "--owner",
            "Documentation role map",
            "--review-cadence",
            "event-driven",
            "--freshness-posture",
            "current",
            "--last-reviewed-at",
            "2026-06-01T00:00:00Z",
            "--next-review-due-at",
            "2026-06-15T00:00:00Z",
            "--source-ref",
            "repo_doc:docs/DOCS_INDEX.md",
            "--json",
        ]
    )
    assert freshness.exit_code == 0, freshness.output
    assert _json(freshness.output)["object_type"] == "DocsFreshnessRecord"

    roadmap = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "create-roadmap-execution-item",
            "--summary",
            "CLI roadmap execution",
            "--roadmap-ref",
            "repo_doc:docs/ROADMAP.md",
            "--execution-state",
            "in_progress",
            "--owner",
            "BuilderOps governance",
            "--next-decision",
            "Continue with #1502 after #1501 merges.",
            "--source-ref",
            "github_issue:#1498",
            "--json",
        ]
    )
    assert roadmap.exit_code == 0, roadmap.output
    assert _json(roadmap.output)["object_type"] == "RoadmapExecutionItem"

    receipt = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "append-receipt",
            "--summary",
            "CLI receipt",
            "--event-type",
            "object_created",
            "--actor",
            "codex",
            "--occurred-at",
            "2026-06-01T00:00:00Z",
            "--target-ref",
            f"builderops_object:{learning_record['id']}",
            "--action",
            "create",
            "--receipt-body",
            "Created learning signal.",
            "--idempotency-key",
            f"object_created:{learning_record['id']}",
            "--source-ref",
            "github_issue:#1501",
            "--json",
        ]
    )
    assert receipt.exit_code == 0, receipt.output
    receipt_record = _json(receipt.output)
    assert receipt_record["object_type"] == "BuilderOpsReceipt"
    assert receipt_record["promotion_status"] == "not_promotable"


def test_builderops_cli_lease_and_transition(tmp_path: Path) -> None:
    db_path = tmp_path / "builderops.sqlite3"
    promotion = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "create-promotion-intent",
            "--summary",
            "CLI promotion transition",
            "--target-authority-surface",
            "github_issue",
            "--target-action",
            "create",
            "--target-ref",
            "pending",
            "--target-authority-class",
            "operational",
            "--intended-output",
            "Draft follow-up issue.",
            "--source-ref",
            "builderops_object:lrn_cli_transition",
            "--idempotency-key",
            "cli:create-promotion-transition",
            "--json",
        ]
    )
    assert promotion.exit_code == 0, promotion.output
    promotion_record = _json(promotion.output)

    missing_lease = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "transition",
            promotion_record["id"],
            "--actor",
            "codex",
            "--lease-id",
            "missing",
            "--idempotency-key",
            "cli:transition-promotion",
            "--source-ref",
            "github_issue:#1502",
            "--summary",
            "Promotion accepted",
            "--action",
            "accept",
            "--receipt-body",
            "Accepted promotion intent.",
            "--lifecycle-state",
            "accepted",
            "--json",
        ]
    )
    assert missing_lease.exit_code != 0
    assert "active lease required" in missing_lease.output

    lease = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "acquire-lease",
            promotion_record["id"],
            "--actor",
            "codex",
            "--json",
        ]
    )
    assert lease.exit_code == 0, lease.output
    lease_record = _json(lease.output)

    transitioned = _run(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "transition",
            promotion_record["id"],
            "--actor",
            "codex",
            "--lease-id",
            lease_record["lease_id"],
            "--idempotency-key",
            "cli:transition-promotion",
            "--source-ref",
            "github_issue:#1502",
            "--summary",
            "Promotion accepted",
            "--action",
            "accept",
            "--receipt-body",
            "Accepted promotion intent.",
            "--lifecycle-state",
            "accepted",
            "--json",
        ]
    )
    assert transitioned.exit_code == 0, transitioned.output
    result = _json(transitioned.output)
    assert result["record"]["lifecycle_state"] == "accepted"
    assert result["receipt"]["object_type"] == "BuilderOpsReceipt"
    assert result["receipt"]["id"] in result["record"]["receipt_refs"]


def test_builderops_cli_rejects_invalid_object_type_on_list(tmp_path: Path) -> None:
    result = _run(
        [
            "builderops",
            "--db-path",
            str(tmp_path / "builderops.sqlite3"),
            "list",
            "--type",
            "InvalidType",
            "--json",
        ]
    )
    assert result.exit_code != 0
    assert "unsupported object_type" in result.output
