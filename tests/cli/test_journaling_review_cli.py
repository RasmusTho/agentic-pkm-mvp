from __future__ import annotations

from datetime import date
from pathlib import Path

from click.testing import CliRunner

from app.cli.journaling import journaling_group
from app.journaling.review import (
    JournalReviewState,
    JournalReviewTickResult,
)


def test_review_tick_cli_invokes_production_observer(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    observed: dict[str, object] = {}

    def fake_tick(**kwargs: object) -> JournalReviewTickResult:
        observed.update(kwargs)
        return JournalReviewTickResult(scanned_dates=("2026-07-15",), results=())

    monkeypatch.setattr("app.cli.journaling.process_journal_reviews_tick", fake_tick)
    result = CliRunner().invoke(
        journaling_group,
        [
            "review-tick",
            "--vault-root",
            str(vault),
            "--date",
            "2026-07-15",
            "--outbox-path",
            str(tmp_path / "outbox.jsonl"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert observed["only_date"] == date(2026, 7, 15)
    assert '"scanned_dates": ["2026-07-15"]' in result.output


def test_review_status_cli_projects_without_processing(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    class Projection:
        state = JournalReviewState.ACCEPTED_PENDING_MATERIALIZATION
        candidate_path = "draft.md"
        canonical_path = "daily.md"
        status_message = "Accepted — waiting to save"

    monkeypatch.setattr(
        "app.cli.journaling.project_journal_review",
        lambda **_kwargs: Projection(),
    )
    result = CliRunner().invoke(
        journaling_group,
        [
            "review-status",
            "--vault-root",
            str(vault),
            "--date",
            "2026-07-15",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"state": "accepted_pending_materialization"' in result.output
