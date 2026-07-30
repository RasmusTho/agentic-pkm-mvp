"""Meeting session/segment ledger (CDLM-02, issue #4385).

Every test drives the **production surfaces**: the meeting routes on
`app.api.app.app` through `TestClient`, and segment recording through the real
admission path (`POST /api/heimdal/capture/media`) — the acceptance criteria
are about what an external capture client observes, and INV-CDLM-3/9 are only
meaningful on the paths a client actually calls.

The ledger is file-backed (SQLite at ``HEIMDAL_MEETING_LEDGER_PATH``) even in
the dev/test lane, precisely so `test_ledger_survives_restart` can assert the
restart AC honestly: the "restart" reads back from durable storage alone, with
no in-process state carried over.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.heimdal.consent_ledger import reset_memory_consent_ledger
from app.heimdal.media_receipts import reset_memory_media_receipts
from app.heimdal.raw_store import reset_memory_raw_store

pytestmark = pytest.mark.not_pg

_KEY = "9f" * 32
LATE_ADMITTED_EVENT = "heimdal.meeting.segment.late_admitted"


@pytest.fixture(autouse=True)
def _memory_runtime(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    """Volatile Heimdal backend, per-test JSONL outbox, per-test ledger file."""
    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY)
    outbox_path = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv("HEIMDAL_MEETING_LEDGER_PATH", str(tmp_path / "meeting-ledger.sqlite3"))
    reset_memory_raw_store()
    reset_memory_consent_ledger()
    reset_memory_media_receipts()
    return outbox_path


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _open_session(client: TestClient, session_id: str, **overrides: Any):
    body = {"session_id": session_id, "device_id": "ipad-1", "template_selection": {"mode": "default"}}
    body.update(overrides)
    return client.post("/api/heimdal/meeting/session", json=body)


def _close_session(client: TestClient, session_id: str, final_seq_count: int):
    return client.post(
        f"/api/heimdal/meeting/{session_id}/close",
        json={"final_seq_count": final_seq_count},
    )


def _gap_report(client: TestClient, session_id: str):
    return client.get(f"/api/heimdal/meeting/{session_id}/segments")


def _admit_segment(
    client: TestClient,
    session_id: str,
    seq: int,
    media: bytes,
    *,
    capture_id: str | None = None,
    declared_sha: str | None = None,
):
    sidecar = {
        "capture_id": capture_id or str(uuid4()),
        "content_sha256": declared_sha or hashlib.sha256(media).hexdigest(),
        "kind": "audio",
        "captured_at": "2026-07-30T12:00:00Z",
        "device_id": "ipad-1",
        "schema_version": 1,
        "session_id": session_id,
        "session_seq": seq,
    }
    return client.post(
        "/api/heimdal/capture/media",
        files={
            "media": (f"segment-{seq:03d}.m4a", media, "audio/m4a"),
            "sidecar": ("sidecar.json", json.dumps(sidecar), "application/json"),
        },
    )


def _events(outbox_path: Path, event: str) -> list[dict[str, Any]]:
    if not outbox_path.exists():
        return []
    return [
        record
        for record in (
            json.loads(line)
            for line in outbox_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if record.get("event") == event
    ]


def test_session_lifecycle_is_idempotent(client: TestClient) -> None:
    """Open/close replays recorded outcomes; session state never forks."""
    session_id = f"mtg-{uuid4()}"

    first = _open_session(client, session_id)
    assert first.status_code == 200, first.text
    opened = first.json()
    assert opened["closed"] is False
    assert "idempotent_replay" not in opened

    replayed_open = _open_session(client, session_id, device_id="other-device")
    assert replayed_open.status_code == 200
    replay = replayed_open.json()
    assert replay["idempotent_replay"] is True
    # The recorded outcome, not the replay's divergent fields: no fork.
    assert replay["device_id"] == "ipad-1"
    assert replay["opened_at"] == opened["opened_at"]

    closed = _close_session(client, session_id, 4)
    assert closed.status_code == 200, closed.text
    first_close = closed.json()
    assert first_close["closed"] is True
    assert first_close["final_seq_count"] == 4

    replayed_close = _close_session(client, session_id, 9)
    assert replayed_close.status_code == 200
    close_replay = replayed_close.json()
    assert close_replay["idempotent_replay"] is True
    # The first recorded close is the truth; a divergent re-post replays it.
    assert close_replay["final_seq_count"] == 4
    assert close_replay["closed_at"] == first_close["closed_at"]

    # Closing what was never opened mints nothing.
    unknown = _close_session(client, f"mtg-{uuid4()}", 1)
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["error"] == "meeting_session_unknown"


def test_segment_rows_unique_across_replays(client: TestClient) -> None:
    """Exactly one ledger row per (session_id, session_seq), via the production path."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200

    media = b"segment-zero-bytes"
    capture_id = str(uuid4())
    first = _admit_segment(client, session_id, 0, media, capture_id=capture_id)
    assert first.status_code == 200, first.text
    receipt_id = first.json()["receipt_id"]

    for _ in range(3):
        replay = _admit_segment(client, session_id, 0, media, capture_id=capture_id)
        assert replay.status_code == 200
        assert replay.json()["receipt_id"] == receipt_id

    report = _gap_report(client, session_id).json()
    assert report["received"] == [0]
    assert len(report["segments"]) == 1
    assert report["segments"][0]["receipt_id"] == receipt_id
    assert report["needs_attention"] == []


def test_gap_report_names_missing_sequences(client: TestClient) -> None:
    """Missing holes are named before and after close; complete only at full cover."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200

    for seq in (0, 1, 3):
        assert _admit_segment(client, session_id, seq, f"seg-{seq}".encode()).status_code == 200

    before = _gap_report(client, session_id).json()
    assert before["received"] == [0, 1, 3]
    assert before["missing"] == [2]
    assert before["closed"] is False
    assert before["complete"] is False
    assert [seg["seq"] for seg in before["segments"]] == [0, 1, 3]
    assert all(seg["receipt_id"].startswith("rcp_") for seg in before["segments"])

    assert _close_session(client, session_id, 4).status_code == 200
    after = _gap_report(client, session_id).json()
    assert after["missing"] == [2]
    assert after["closed"] is True
    assert after["complete"] is False

    # Filling the hole flips complete; nothing else does.
    assert _admit_segment(client, session_id, 2, b"seg-2").status_code == 200
    complete = _gap_report(client, session_id).json()
    assert complete["missing"] == []
    assert complete["complete"] is True

    unknown = _gap_report(client, f"mtg-{uuid4()}")
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["error"] == "meeting_session_unknown"


def test_seq_conflict_fails_closed(client: TestClient) -> None:
    """A different content hash for an existing pair preserves the original row."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200

    original = _admit_segment(client, session_id, 0, b"the-original-bytes")
    assert original.status_code == 200
    original_receipt = original.json()["receipt_id"]
    original_sha = original.json()["content_sha256"]

    conflicting = _admit_segment(client, session_id, 0, b"different-bytes-entirely")
    assert conflicting.status_code == 200  # the *admission* is real; the ledger fails closed
    attempted_sha = conflicting.json()["content_sha256"]
    assert attempted_sha != original_sha

    report = _gap_report(client, session_id).json()
    assert report["received"] == [0]
    assert len(report["segments"]) == 1
    assert report["segments"][0]["receipt_id"] == original_receipt
    assert report["segments"][0]["content_sha256"] == original_sha

    assert len(report["needs_attention"]) == 1
    conflict = report["needs_attention"][0]
    assert conflict["seq"] == 0
    assert conflict["reason"] == "sequence_content_conflict"
    assert conflict["attempted_content_sha256"] == attempted_sha

    # A retry loop re-presenting the same conflicting bytes records ONE
    # logical conflict, not one entry per resend.
    retry = _admit_segment(
        client,
        session_id,
        0,
        b"different-bytes-entirely",
        capture_id=conflicting.json()["capture_id"],
    )
    assert retry.status_code == 200
    assert len(_gap_report(client, session_id).json()["needs_attention"]) == 1


def test_late_segment_reconciliation(client: TestClient, _memory_runtime: Path) -> None:
    """Late admission into a closed session: ledger updates, event emits, no re-open."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    for seq in (0, 1, 3):
        assert _admit_segment(client, session_id, seq, f"seg-{seq}".encode()).status_code == 200
    assert _close_session(client, session_id, 4).status_code == 200

    assert _events(_memory_runtime, LATE_ADMITTED_EVENT) == []

    late = _admit_segment(client, session_id, 2, b"seg-2-late")
    assert late.status_code == 200

    report = _gap_report(client, session_id).json()
    assert report["missing"] == []
    assert report["complete"] is True
    assert report["closed"] is True  # never re-opened
    late_rows = [seg for seg in report["segments"] if seg["seq"] == 2]
    assert late_rows and late_rows[0]["late"] is True

    events = _events(_memory_runtime, LATE_ADMITTED_EVENT)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["session_id"] == session_id
    assert payload["session_seq"] == 2
    assert payload["complete"] is True
    assert payload["missing"] == []
    assert payload["receipt_id"] == late.json()["receipt_id"]

    # A replay of the late admission emits no second event and adds no row.
    replay = _admit_segment(
        client, session_id, 2, b"seg-2-late", capture_id=late.json()["capture_id"]
    )
    assert replay.status_code == 200
    assert len(_events(_memory_runtime, LATE_ADMITTED_EVENT)) == 1


def test_ledger_survives_restart(client: TestClient) -> None:
    """A simulated hub restart loses no ledger state: read-back from durable storage alone."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    for seq in (0, 1):
        assert _admit_segment(client, session_id, seq, f"seg-{seq}".encode()).status_code == 200

    pre_restart = _gap_report(client, session_id).json()
    del pre_restart["trace_id"]

    # Simulated restart: every volatile in-process store is wiped; only the
    # durable ledger file remains. The ledger module holds no in-process cache,
    # so a fresh client answers from durable state alone.
    reset_memory_raw_store()
    reset_memory_media_receipts()
    restarted_client = TestClient(app)

    post_restart = _gap_report(restarted_client, session_id).json()
    del post_restart["trace_id"]
    assert post_restart == pre_restart

    # The restarted hub keeps taking admissions against the surviving ledger.
    assert _admit_segment(restarted_client, session_id, 2, b"seg-2").status_code == 200
    assert _gap_report(restarted_client, session_id).json()["received"] == [0, 1, 2]
