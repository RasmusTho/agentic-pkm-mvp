"""CAL-03 Companion API contract tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.calibration.scheduler import RevisitDue
from app.receipts.outcome_receipt_log import OUTCOME_RECEIPT_WRITE_ACTION
from app.receipts.revisit_dismissal_log import REVISIT_DISMISSAL_WRITE_ACTION
from tests.api._vault_test_helpers import bind_initialized_vault


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def vault_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bind_initialized_vault(monkeypatch, tmp_path, channel="test")
    note = tmp_path / "notes" / "decision.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\n"
        "uuid: decision-object-1\n"
        "artifact_class: decision_record\n"
        "decided_on: 2026-06-23\n"
        "---\n\n"
        "# Postgres as projection, not source of truth\n",
        encoding="utf-8",
    )
    return note


@pytest.fixture()
def due() -> RevisitDue:
    return RevisitDue(
        decision_object_id=uuid4(),
        decision_uuid=uuid4(),
        title="Postgres as projection, not source of truth",
        decided_on=date(2026, 6, 23),
        rung_index=0,
        rung_days=14,
        due_since=date(2026, 7, 7),
    )


def test_workspace_state_exposes_pending_revisit(
    client: TestClient,
    vault_note: Path,
    due: RevisitDue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "due_revisits", lambda **_: [due])

    response = client.get("/api/companion/workspace", params={"note_path": "notes/decision.md"})

    assert response.status_code == 200
    revisit = response.json()["calibration_revisit"]
    assert revisit["state"] == "pending"
    assert revisit["decision_id"] == str(due.decision_uuid)
    assert revisit["title"] == due.title
    assert revisit["decided_on"] == "2026-06-23"
    assert revisit["rung_days"] == 14
    assert revisit["degraded"] is False


def test_degraded_read_reports_degraded_not_empty(
    client: TestClient,
    vault_note: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**_: object) -> list[RevisitDue]:
        raise OSError("ledger unavailable")

    monkeypatch.setattr(companion_module, "due_revisits", fail)

    response = client.get("/api/companion/workspace", params={"note_path": "notes/decision.md"})

    assert response.status_code == 200
    revisit = response.json()["calibration_revisit"]
    assert revisit["state"] == "degraded"
    assert revisit["degraded"] is True
    assert revisit["decision_id"] is None
    assert revisit["degraded_reason"] == "scheduler_unavailable"


def test_answer_revisit_writes_outcome_receipt_via_writeguard(
    client: TestClient,
    vault_note: Path,
    due: RevisitDue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "due_revisits", lambda **_: [due])
    guard_actions: list[str] = []
    monkeypatch.setattr(
        companion_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: guard_actions.append(action),
    )
    writes: list[dict[str, object]] = []

    def append(**kwargs: object) -> dict[str, object]:
        writes.append(kwargs)
        return {"kind": "decision.outcome_receipt", "outcome": kwargs["outcome"]}

    monkeypatch.setattr(companion_module, "append_outcome_receipt", append)

    response = client.post(
        f"/api/companion/calibration/revisits/{due.decision_uuid}/decision",
        json={"outcome": "partly_held", "note": "Still in progress."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert guard_actions == [OUTCOME_RECEIPT_WRITE_ACTION]
    assert writes == [
        {
            "decision_object_id": due.decision_object_id,
            "decision_uuid": due.decision_uuid,
            "rung_index": 0,
            "outcome": "partly_held",
            "note": "Still in progress.",
            "vault_root": vault_note.parent.parent,
        }
    ]


def test_retry_replays_the_submitted_rung_instead_of_stamping_next_rung(
    client: TestClient,
    vault_note: Path,
    due: RevisitDue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    next_rung = RevisitDue(
        decision_object_id=due.decision_object_id,
        decision_uuid=due.decision_uuid,
        title=due.title,
        decided_on=due.decided_on,
        rung_index=1,
        rung_days=30,
        due_since=due.due_since,
    )
    monkeypatch.setattr(companion_module, "due_revisits", lambda **_: [next_rung])
    monkeypatch.setattr(
        companion_module,
        "iter_outcome_receipts",
        lambda _root: [
            {
                "decision_uuid": str(due.decision_uuid),
                "decision_object_id": str(due.decision_object_id),
                "rung_index": due.rung_index,
                "outcome": "held",
            }
        ],
    )
    monkeypatch.setattr(companion_module, "iter_revisit_dismissals", lambda _root: [])

    def must_not_stamp_next(**_: object) -> dict[str, object]:
        raise AssertionError("retry must not stamp the next rung")

    monkeypatch.setattr(companion_module, "append_outcome_receipt", must_not_stamp_next)
    response = client.post(
        f"/api/companion/calibration/revisits/{due.decision_uuid}/decision",
        json={
            "outcome": "held",
            "rung_index": due.rung_index,
            "decision_object_id": str(due.decision_object_id),
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["rung_index"] == due.rung_index


def test_omitted_rung_retry_cannot_stamp_the_next_rung(
    client: TestClient,
    vault_note: Path,
    due: RevisitDue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    next_rung = RevisitDue(
        decision_object_id=due.decision_object_id,
        decision_uuid=due.decision_uuid,
        title=due.title,
        decided_on=due.decided_on,
        rung_index=1,
        rung_days=30,
        due_since=due.due_since,
    )
    due_calls = iter(([due], [next_rung]))
    monkeypatch.setattr(companion_module, "due_revisits", lambda **_: next(due_calls))
    records: list[dict[str, object]] = []
    monkeypatch.setattr(companion_module, "iter_outcome_receipts", lambda _root: records)
    monkeypatch.setattr(companion_module, "iter_revisit_dismissals", lambda _root: [])
    monkeypatch.setattr(companion_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)

    def append(**kwargs: object) -> dict[str, object]:
        record = {
            "decision_uuid": str(kwargs["decision_uuid"]),
            "decision_object_id": str(kwargs["decision_object_id"]),
            "rung_index": kwargs["rung_index"],
            "outcome": kwargs["outcome"],
        }
        records.append(record)
        return record

    monkeypatch.setattr(companion_module, "append_outcome_receipt", append)
    path = f"/api/companion/calibration/revisits/{due.decision_uuid}/decision"

    first = client.post(path, json={"outcome": "held"})
    second = client.post(path, json={"outcome": "held"})

    assert first.status_code == 200
    assert first.json()["rung_index"] == 0
    assert second.status_code == 409
    assert second.json()["detail"]["error"] == "calibration_revisit_identity_required"
    assert [record["rung_index"] for record in records] == [0]


def test_answer_and_dismiss_arbitrate_one_durable_rung(
    client: TestClient,
    vault_note: Path,
    due: RevisitDue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "due_revisits", lambda **_: [due])
    monkeypatch.setattr(companion_module, "iter_outcome_receipts", lambda _root: [])
    monkeypatch.setattr(
        companion_module,
        "iter_revisit_dismissals",
        lambda _root: [
            {
                "decision_uuid": str(due.decision_uuid),
                "decision_object_id": str(due.decision_object_id),
                "rung_index": due.rung_index,
            }
        ],
    )
    monkeypatch.setattr(
        companion_module,
        "append_outcome_receipt",
        lambda **_: (_ for _ in ()).throw(AssertionError("answer raced a dismissal")),
    )
    response = client.post(
        f"/api/companion/calibration/revisits/{due.decision_uuid}/decision",
        json={"outcome": "held", "rung_index": due.rung_index},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "calibration_revisit_already_dismissed"


def test_dismiss_defers_without_outcome_receipt(
    client: TestClient,
    vault_note: Path,
    due: RevisitDue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "due_revisits", lambda **_: [due])
    guard_actions: list[str] = []
    monkeypatch.setattr(
        companion_module.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: guard_actions.append(action),
    )
    dismissals: list[dict[str, object]] = []
    monkeypatch.setattr(
        companion_module,
        "append_revisit_dismissal",
        lambda **kwargs: dismissals.append(kwargs) or {"kind": "dismissal"},
    )

    def outcome_must_not_run(**_: object) -> dict[str, object]:
        raise AssertionError("dismiss must not write an outcome receipt")

    monkeypatch.setattr(companion_module, "append_outcome_receipt", outcome_must_not_run)

    response = client.post(
        f"/api/companion/calibration/revisits/{due.decision_uuid}/dismiss",
        json={},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"
    assert response.json()["receipt"] is None
    assert guard_actions == [REVISIT_DISMISSAL_WRITE_ACTION]
    assert dismissals and dismissals[0]["rung_index"] == due.rung_index
