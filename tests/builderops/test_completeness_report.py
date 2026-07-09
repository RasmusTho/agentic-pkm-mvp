from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.completeness_report import build_completeness_report


def _learning_signal(signal_id: str, summary: str) -> dict[str, object]:
    return {
        "id": signal_id,
        "object_type": "LearningSignal",
        "created_at": f"2026-07-09T12:0{signal_id[-1]}:00Z",
        "summary": summary,
        "signal_type": "workflow_divergence",
    }


def _retro_receipt(
    receipt_id: str,
    *,
    target_ids: list[str],
    receipt_body: str,
) -> dict[str, object]:
    return {
        "id": receipt_id,
        "object_type": "BuilderOpsReceipt",
        "event_type": "learning_retrospective",
        "summary": "Learning retrospective",
        "occurred_at": "2026-07-09T13:00:00Z",
        "target_refs": [
            {"ref_type": "builderops_object", "ref": signal_id}
            for signal_id in target_ids
        ],
        "receipt_body": receipt_body,
    }


def test_completeness_report_identifies_processed_and_unprocessed_signals() -> None:
    report = build_completeness_report(
        records=[
            _learning_signal("lrn-1", "Processed signal"),
            _learning_signal("lrn-2", "Unprocessed signal"),
            _retro_receipt(
                "receipt-1",
                target_ids=["lrn-1"],
                receipt_body="Retrospective complete; outcomes: lrn-1=applied.",
            ),
        ],
        storage={"available": True, "source": "fixture"},
    )

    assert report["complete"] is False
    assert report["unprocessed_learning_signals"] == [
        {
            "id": "lrn-2",
            "summary": "Unprocessed signal",
            "created_at": "2026-07-09T12:02:00Z",
            "signal_type": "workflow_divergence",
        }
    ]
    assert report["retrospective_receipts_missing_terminal_outcomes"] == []


def test_completeness_report_identifies_receipts_without_terminal_outcomes() -> None:
    report = build_completeness_report(
        records=[
            _learning_signal("lrn-1", "Claimed signal"),
            _retro_receipt(
                "receipt-1",
                target_ids=["lrn-1"],
                receipt_body="Retrospective complete; processed lrn-1.",
            ),
        ],
        storage={"available": True, "source": "fixture"},
    )

    assert report["complete"] is False
    assert report["retrospective_receipts_missing_terminal_outcomes"] == [
        {
            "receipt_id": "receipt-1",
            "summary": "Learning retrospective",
            "occurred_at": "2026-07-09T13:00:00Z",
            "target_signal_ids": ["lrn-1"],
            "terminal_outcomes": [],
            "terminal_signal_ids": [],
            "missing_terminal_outcomes": ["lrn-1"],
        }
    ]


def test_completeness_report_handles_unavailable_storage_honestly() -> None:
    report = build_completeness_report(
        records=None,
        storage={
            "available": False,
            "source": "runtime/builderops/missing.sqlite3",
            "reason": "missing_builderops_db",
        },
    )

    assert report["complete"] is False
    assert report["storage"]["available"] is False
    assert report["storage"]["reason"] == "missing_builderops_db"
    assert "unavailable" in report["receipt_body"]


def test_completeness_report_is_observe_only_and_reports_candidates_and_log_entries() -> None:
    report = build_completeness_report(
        records=[],
        storage={"available": True, "source": "fixture"},
        reevaluation_candidates=[
            {
                "id": "cand-open",
                "summary": "Needs routing",
                "evidence_kind": "review_finding",
                "upstream_artifact_hint": ".codex/skills/verification-and-closure/SKILL.md",
            },
            {
                "id": "cand-done",
                "summary": "Done",
                "outcome": "issue_created",
            },
        ],
        learning_log_text=(
            "## 2026-07-01 - #1 (old)\n"
            "--- retro 2026-07-02: applied 1/1 proposals ---\n"
            "## 2026-07-03 - #2 (new)\n"
        ),
    )

    assert report["observe_only"] is True
    assert report["mutations_performed"] is False
    assert report["reevaluation_candidates_without_outcome"] == [
        {
            "id": "cand-open",
            "summary": "Needs routing",
            "outcome": None,
            "evidence_kind": "review_finding",
            "upstream_artifact_hint": ".codex/skills/verification-and-closure/SKILL.md",
        }
    ]
    assert report["stale_compatibility_entries"] == [
        {"heading": "2026-07-03 - #2 (new)"}
    ]


def test_completeness_report_cli_outputs_unavailable_storage(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing.sqlite3"

    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "--db-path",
            str(missing_db),
            "completeness-report",
            "check",
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["complete"] is False
    assert payload["storage"]["available"] is False
    assert payload["storage"]["reason"] == "missing_builderops_db"
    assert payload["mutations_performed"] is False


def test_completeness_report_cli_reads_fixture_file(tmp_path: Path) -> None:
    records_file = tmp_path / "records.json"
    records_file.write_text(
        json.dumps({
            "records": [
                _learning_signal("lrn-1", "Processed"),
                _retro_receipt(
                    "receipt-1",
                    target_ids=["lrn-1"],
                    receipt_body="Retrospective complete; outcomes: lrn-1=already_satisfied.",
                ),
            ],
            "learning_evaluation_candidates": [],
        }),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "completeness-report",
            "check",
            "--records-file",
            str(records_file),
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["complete"] is True
    assert payload["unprocessed_learning_signals"] == []
