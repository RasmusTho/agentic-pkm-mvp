from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root
from app.builderops.epic_run_state import TERMINAL_LEARNING_EVALUATION_OUTCOMES
from app.builderops.retrospective_closure import (
    RetrospectiveClosureError,
    build_retrospective_closure_ledger,
)


def _target_ref(outcome: str) -> dict[str, str]:
    targets = {
        "applied": ("pull_request", "#3270"),
        "already_satisfied": ("repo_doc", "docs/development/DELIVERY_FEEDBACK_LOOP.md"),
        "issue_created": ("github_issue", "#3262"),
        "promotion_pending": ("builderops_object", "prom_20260709_0001"),
        "debt_or_fitness_recorded": (
            "repo_doc",
            "docs/architecture/SBS_TRANSITION_DEBT.md::D12",
        ),
        "discarded_or_superseded": ("builderops_object", "receipt_20260709_0001"),
    }
    ref_type, ref = targets[outcome]
    return {"ref_type": ref_type, "ref": ref}


def test_retrospective_closure_records_one_terminal_outcome_per_signal() -> None:
    signals = [
        {"id": f"lrn-{outcome}", "summary": f"Signal for {outcome}"}
        for outcome in TERMINAL_LEARNING_EVALUATION_OUTCOMES
    ]
    outcomes = [
        {
            "signal_id": f"lrn-{outcome}",
            "outcome": outcome,
            "target_refs": [_target_ref(outcome)],
        }
        for outcome in TERMINAL_LEARNING_EVALUATION_OUTCOMES
    ]

    ledger = build_retrospective_closure_ledger(
        signals=signals,
        outcomes=outcomes,
    )

    assert ledger["complete"] is True
    assert ledger["unresolved_signals"] == []
    assert [
        item["outcome"] for item in ledger["processed_signal_outcomes"]
    ] == list(TERMINAL_LEARNING_EVALUATION_OUTCOMES)
    for outcome in TERMINAL_LEARNING_EVALUATION_OUTCOMES:
        assert f"lrn-{outcome}={outcome}" in ledger["receipt_body"]


def test_retrospective_closure_reports_unresolved_signal() -> None:
    ledger = build_retrospective_closure_ledger(
        signals=[
            {"id": "lrn-applied", "summary": "Applied signal"},
            {"id": "lrn-open", "summary": "Open signal"},
        ],
        outcomes=[
            {
                "signal_id": "lrn-applied",
                "outcome": "applied",
                "target_refs": [{"ref_type": "pull_request", "ref": "#3270"}],
            }
        ],
    )

    assert ledger["complete"] is False
    assert ledger["unresolved_signals"] == [
        {"signal_id": "lrn-open", "summary": "Open signal"}
    ]
    assert "unresolved=lrn-open" in ledger["receipt_body"]


def test_retrospective_closure_rejects_invalid_outcome_and_missing_target_refs() -> None:
    signals = [{"id": "lrn-1"}]

    with pytest.raises(RetrospectiveClosureError, match="outcome.outcome"):
        build_retrospective_closure_ledger(
            signals=signals,
            outcomes=[
                {
                    "signal_id": "lrn-1",
                    "outcome": "later",
                    "target_refs": [{"ref_type": "github_issue", "ref": "#3262"}],
                }
            ],
        )

    with pytest.raises(RetrospectiveClosureError, match="outcome.target_refs"):
        build_retrospective_closure_ledger(
            signals=signals,
            outcomes=[
                {
                    "signal_id": "lrn-1",
                    "outcome": "issue_created",
                    "target_refs": [],
                }
            ],
        )


def test_retrospective_closure_cli_outputs_signal_ids_and_outcomes(tmp_path: Path) -> None:
    signals_file = tmp_path / "signals.json"
    outcomes_file = tmp_path / "outcomes.json"
    signals_file.write_text(
        json.dumps({"signals": [{"id": "lrn-1"}, {"id": "lrn-2"}]}),
        encoding="utf-8",
    )
    outcomes_file.write_text(
        json.dumps({
            "outcomes": [
                {
                    "signal_id": "lrn-1",
                    "outcome": "issue_created",
                    "target_refs": [{"ref_type": "github_issue", "ref": "#3262"}],
                }
            ]
        }),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "retrospective-closure",
            "check",
            "--signals-file",
            str(signals_file),
            "--outcomes-file",
            str(outcomes_file),
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["complete"] is False
    assert payload["processed_signal_outcomes"] == [
        {
            "signal_id": "lrn-1",
            "summary": None,
            "outcome": "issue_created",
            "target_refs": [{"ref_type": "github_issue", "ref": "#3262"}],
        }
    ]
    assert payload["unresolved_signals"] == [{"signal_id": "lrn-2"}]
    assert "lrn-1=issue_created" in payload["receipt_body"]
