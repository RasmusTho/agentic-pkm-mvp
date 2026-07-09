from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.ci_stall_classifier import classify_ci_state

REPO_ROOT = Path(__file__).resolve().parents[2]


def _check(
    name: str,
    *,
    status: str,
    conclusion: str | None = None,
    started_at: str = "2026-07-09T20:00:00Z",
    check_id: int = 1,
) -> dict[str, object]:
    return {
        "id": check_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": started_at,
    }


def test_queued_checks_within_threshold_classify_wait() -> None:
    result = classify_ci_state(
        {
            "check_runs": [
                _check(
                    "Unit tests (not pg)",
                    status="queued",
                    started_at="2026-07-09T20:00:00Z",
                )
            ]
        },
        now="2026-07-09T20:10:00Z",
        stall_threshold_seconds=1800,
    )

    assert result.classification == "wait"
    assert result.recommended_next_action == "wait"
    assert result.failure is False
    assert result.stalled is False
    assert result.pending_checks[0]["age_seconds"] == 600


def test_long_running_checks_classify_stalled() -> None:
    result = classify_ci_state(
        {
            "check_runs": [
                _check(
                    "Unit tests (not pg)",
                    status="in_progress",
                    started_at="2026-07-09T20:00:00Z",
                ),
                _check(
                    "smoke",
                    status="queued",
                    started_at="2026-07-09T20:25:00Z",
                    check_id=2,
                ),
            ]
        },
        now="2026-07-09T20:45:01Z",
        stall_threshold_seconds=1800,
    )

    assert result.classification == "stalled"
    assert result.recommended_next_action == "handoff_as_ci_pending_or_rerun_candidate"
    assert result.failure is False
    assert result.stalled is True
    assert [item["name"] for item in result.pending_checks] == [
        "Unit tests (not pg)",
        "smoke",
    ]


def test_failed_check_classifies_actionable_failure() -> None:
    result = classify_ci_state(
        {
            "check_runs": [
                _check(
                    "Unit tests (not pg)",
                    status="completed",
                    conclusion="failure",
                )
            ]
        },
        now="2026-07-09T20:10:00Z",
    )

    assert result.classification == "actionable_failure"
    assert result.recommended_next_action == "repair_failure"
    assert result.failure is True
    assert result.stalled is False
    assert result.failed_checks[0]["name"] == "Unit tests (not pg)"


def test_timeout_failure_classifies_rerun_candidate_not_actionable_repair() -> None:
    result = classify_ci_state(
        {
            "check_runs": [
                _check(
                    "panel-llm-e2e",
                    status="completed",
                    conclusion="timed_out",
                )
            ]
        },
        now="2026-07-09T20:10:00Z",
    )

    assert result.classification == "flaky_or_external_failure"
    assert result.recommended_next_action == "rerun_candidate"
    assert result.failure is True


def test_latest_check_run_per_name_wins_before_classification() -> None:
    result = classify_ci_state(
        {
            "check_runs": [
                _check(
                    "pr-contract",
                    status="completed",
                    conclusion="failure",
                    started_at="2026-07-09T20:00:00Z",
                    check_id=1,
                ),
                _check(
                    "pr-contract",
                    status="completed",
                    conclusion="success",
                    started_at="2026-07-09T20:05:00Z",
                    check_id=2,
                ),
            ]
        },
        now="2026-07-09T20:10:00Z",
    )

    assert result.classification == "green"
    assert [item["name"] for item in result.checks_considered] == ["pr-contract"]
    assert result.checks_considered[0]["conclusion"] == "success"


def test_latest_check_run_uses_numeric_id_to_break_timestamp_ties() -> None:
    result = classify_ci_state(
        {
            "check_runs": [
                _check(
                    "pr-contract",
                    status="completed",
                    conclusion="failure",
                    check_id=9,
                ),
                _check(
                    "pr-contract",
                    status="completed",
                    conclusion="success",
                    check_id=10,
                ),
            ]
        },
        now="2026-07-09T20:10:00Z",
    )

    assert result.classification == "green"
    assert result.checks_considered[0]["id"] == 10


def test_missing_expected_check_reports_missing_attachment() -> None:
    result = classify_ci_state(
        {
            "check_runs": [
                _check("smoke", status="completed", conclusion="success"),
            ]
        },
        now="2026-07-09T20:10:00Z",
        expected_checks=["smoke", "Unit tests (not pg)"],
    )

    assert result.classification == "missing_checks"
    assert result.recommended_next_action == "wait_for_check_attachment"
    assert result.missing_checks == ["Unit tests (not pg)"]


def test_cli_emits_json_payload(tmp_path: Path) -> None:
    checks_file = tmp_path / "checks.json"
    checks_file.write_text(
        json.dumps(
            {
                "check_runs": [
                    _check(
                        "Unit tests (not pg)",
                        status="queued",
                        started_at="2026-07-09T20:00:00Z",
                    )
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci_stall_classifier.py",
            "--check-runs-json",
            str(checks_file),
            "--now",
            "2026-07-09T20:10:00Z",
            "--stall-threshold-seconds",
            "1800",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["classification"] == "wait"
