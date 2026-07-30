"""Live transcript + default analysis projections (CDLM-06, issue #4386).

Every test drives the production surfaces: segments enter through the real
`POST /api/heimdal/capture/media` admission path (the production trigger for
derivation), and reads come from `GET /api/heimdal/meeting/{id}/projection`.
ASR is stubbed at the one shared engine seam (`app.media.transcribe.run_asr`,
reached as the module attribute the projection actually calls) — no model
download, and the stub's call count is what proves derive-exactly-once.
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
from app.heimdal import meeting_projection
from app.heimdal.consent_ledger import reset_memory_consent_ledger
from app.heimdal.media_receipts import reset_memory_media_receipts
from app.heimdal.raw_store import reset_memory_raw_store
from app.media import transcribe as transcribe_module

pytestmark = pytest.mark.not_pg

_KEY = "9f" * 32


@pytest.fixture(autouse=True)
def _memory_runtime(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY)
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("HEIMDAL_MEETING_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_PROJECTION_PATH", str(tmp_path / "projection.sqlite3"))
    reset_memory_raw_store()
    reset_memory_consent_ledger()
    reset_memory_media_receipts()
    return tmp_path


@pytest.fixture
def asr_stub(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub the real shared seam; records one entry per derivation call."""
    calls: list[str] = []

    def fake_run_asr(path_wav: Path, **_: Any) -> dict[str, Any]:
        data = Path(path_wav).read_bytes()
        calls.append(hashlib.sha256(data).hexdigest())
        text = data.decode("utf-8", errors="replace")
        return {
            "text": text,
            "segments": [{"start": 0.0, "end": 1.0, "text": text}],
            "language": "en",
        }

    monkeypatch.setattr(transcribe_module, "run_asr", fake_run_asr)
    return calls


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _open_session(client: TestClient, session_id: str, **overrides: Any):
    body = {"session_id": session_id, "device_id": "ipad-1", "template_selection": {"mode": "default"}}
    body.update(overrides)
    return client.post("/api/heimdal/meeting/session", json=body)


def _close_session(client: TestClient, session_id: str, count: int):
    return client.post(
        f"/api/heimdal/meeting/{session_id}/close", json={"final_seq_count": count}
    )


def _projection(client: TestClient, session_id: str):
    return client.get(f"/api/heimdal/meeting/{session_id}/projection")


def _admit_segment(
    client: TestClient,
    session_id: str,
    seq: int,
    media: bytes,
    *,
    capture_id: str | None = None,
):
    sidecar = {
        "capture_id": capture_id or str(uuid4()),
        "content_sha256": hashlib.sha256(media).hexdigest(),
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


def test_segment_derives_exactly_once(
    client: TestClient, asr_stub: list[str]
) -> None:
    """One derivation per content hash across replays and a simulated restart."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200

    media = b"We decided to ship the ledger."
    capture_id = str(uuid4())
    assert _admit_segment(client, session_id, 0, media, capture_id=capture_id).status_code == 200
    assert len(asr_stub) == 1

    # Idempotent replays through the production path derive nothing new.
    for _ in range(3):
        assert (
            _admit_segment(client, session_id, 0, media, capture_id=capture_id).status_code
            == 200
        )
    assert len(asr_stub) == 1

    # Simulated restart: volatile stores wiped; the derivation row is durable,
    # so a resend after restart still re-derives nothing.
    reset_memory_raw_store()
    reset_memory_media_receipts()
    restarted = TestClient(app)
    assert _admit_segment(restarted, session_id, 0, media, capture_id=capture_id).status_code == 200
    assert len(asr_stub) == 1

    projection = _projection(restarted, session_id).json()
    entries = [row for row in projection["transcript"] if row["kind"] == "segment"]
    assert len(entries) == 1
    assert entries[0]["text"] == media.decode()


def test_transcript_orders_and_marks_gaps(client: TestClient, asr_stub: list[str]) -> None:
    """Ordered by sequence, explicit gap markers, no person attribution fields."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    for seq in (3, 0, 1):  # deliberately out of order
        assert _admit_segment(client, session_id, seq, f"segment {seq} text.".encode()).status_code == 200

    projection = _projection(client, session_id).json()
    transcript = projection["transcript"]
    assert [row["seq"] for row in transcript] == [0, 1, 2, 3]
    assert transcript[2]["kind"] == "gap"
    assert transcript[2]["reason"] == "segment_missing"
    assert [row["kind"] for row in transcript] == ["segment", "segment", "gap", "segment"]
    assert projection["missing"] == [2]

    forbidden = {"speaker", "person", "attendee", "participant", "author", "name"}
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, sub in value.items():
                assert key.lower() not in forbidden, key
                walk(sub)
        elif isinstance(value, list):
            for sub in value:
                walk(sub)

    walk(projection)


def test_analysis_provenance_and_convergence(
    client: TestClient, asr_stub: list[str]
) -> None:
    """Blocks carry full provenance; identical admitted sets converge block-for-block."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    media0 = b"We decided to adopt the ledger. What about retention? Alice will draft notes."
    media1 = b"Budget was the main theme. Budget matters. We agreed on budget caps."
    assert _admit_segment(client, session_id, 0, media0).status_code == 200
    assert _admit_segment(client, session_id, 1, media1).status_code == 200

    first = _projection(client, session_id).json()["analysis"]
    assert first["revision"] == 2  # one revision per input-set change (seg0, then seg0+1)
    assert first["template_id"] == "generic-default@1"
    assert {b["block_type"] for b in first["blocks"]} == {
        "summary",
        "themes",
        "provisional_decisions",
        "open_questions",
        "action_candidates",
    }
    for block in first["blocks"]:
        assert block["ownership"] == "derived_projection"
        assert block["revision"] == first["revision"]
        assert block["derived_from"] == first["derived_from"]
        assert block["template_id"] == "generic-default@1"
        assert block["engine"]["engine"] == "heimdal-meeting-analysis"
    assert [item["seq"] for item in first["derived_from"]] == [0, 1]

    # Idempotent replay of the same admitted set: no new revision, block-level equality.
    assert _admit_segment(client, session_id, 1, media1).status_code == 200
    second = _projection(client, session_id).json()["analysis"]
    assert second == first


def test_template_precedence_resolution(client: TestClient, asr_stub: list[str]) -> None:
    """User selection > permitted metadata > default, via the production seam."""
    resolve = meeting_projection.resolve_template

    assert resolve({"template_id": "generic-default@1"}) == {
        "template_id": "generic-default@1",
        "source": "user_selection",
    }
    # The metadata branch resolves only under an explicit permission flag; no
    # such flag ships, so production calls fall through to the default.
    assert resolve(
        None,
        permitted_metadata_template="generic-default@1",
        metadata_mapping_permitted=True,
    ) == {"template_id": "generic-default@1", "source": "permitted_metadata"}
    assert resolve(None, permitted_metadata_template="generic-default@1") == {
        "template_id": "generic-default@1",
        "source": "default",
    }
    # User selection wins over a permitted metadata mapping.
    assert resolve(
        {"template_id": "generic-default@1"},
        permitted_metadata_template="other@1",
        metadata_mapping_permitted=True,
    )["source"] == "user_selection"
    # An unshipped selection falls back to the default, recorded.
    fallback = resolve({"template_id": "rich-standup@3"})
    assert fallback["template_id"] == "generic-default@1"
    assert fallback["source"] == "default"
    assert "rich-standup@3" in fallback["fallback_reason"]

    # And through the production read path: a session with an explicit
    # selection reports it with user_selection provenance.
    session_id = f"mtg-{uuid4()}"
    assert _open_session(
        client, session_id, template_selection={"template_id": "generic-default@1"}
    ).status_code == 200
    assert _admit_segment(client, session_id, 0, b"hello world meeting.").status_code == 200
    projection = _projection(client, session_id).json()
    assert projection["template"] == {
        "template_id": "generic-default@1",
        "source": "user_selection",
    }
    assert projection["analysis"]["template_id"] == "generic-default@1"


def test_late_segment_creates_new_revision(
    client: TestClient, asr_stub: list[str]
) -> None:
    """Late admission derives a new revision including the late segment."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    for seq in (0, 1, 3):
        assert _admit_segment(client, session_id, seq, f"segment {seq} spoken text.".encode()).status_code == 200
    assert _close_session(client, session_id, 4).status_code == 200

    before = _projection(client, session_id).json()
    revision_before = before["analysis"]["revision"]
    assert before["complete"] is False
    assert 2 not in [item["seq"] for item in before["analysis"]["derived_from"]]

    assert _admit_segment(client, session_id, 2, b"late segment two text.").status_code == 200
    after = _projection(client, session_id).json()
    assert after["analysis"]["revision"] == revision_before + 1
    assert 2 in [item["seq"] for item in after["analysis"]["derived_from"]]
    assert after["complete"] is True
    assert after["closed"] is True
    revs = [r["revision"] for r in after["revisions"]]
    assert revision_before in revs and revision_before + 1 in revs


def test_transcript_shows_segments_beyond_declared_count(
    client: TestClient, asr_stub: list[str]
) -> None:
    """A segment at/beyond an undercounted close still renders — never elided."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    assert _admit_segment(client, session_id, 0, b"segment zero text.").status_code == 200
    assert _close_session(client, session_id, 1).status_code == 200
    # Declared count says 1, but a late over-count segment arrives at seq 2.
    assert _admit_segment(client, session_id, 2, b"over-count segment two.").status_code == 200

    projection = _projection(client, session_id).json()
    seqs = [row["seq"] for row in projection["transcript"]]
    assert seqs == [0, 1, 2]
    kinds = {row["seq"]: row["kind"] for row in projection["transcript"]}
    assert kinds[0] == "segment"
    assert kinds[1] == "gap"  # declared but never admitted
    assert kinds[2] == "segment"  # admitted beyond the declared count — shown, not elided
    assert 2 in [item["seq"] for item in projection["analysis"]["derived_from"]]


def test_asr_failure_is_legible_and_isolated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing segment surfaces as needs-attention; other segments stay derived."""
    poison = b"poisoned segment audio."

    def flaky_run_asr(path_wav: Path, **_: Any) -> dict[str, Any]:
        data = Path(path_wav).read_bytes()
        if data == poison:
            raise RuntimeError("engine exploded")
        text = data.decode("utf-8", errors="replace")
        return {"text": text, "segments": [], "language": "en"}

    monkeypatch.setattr(transcribe_module, "run_asr", flaky_run_asr)

    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    assert _admit_segment(client, session_id, 0, b"good segment zero.").status_code == 200
    # The poisoned admission still succeeds — derivation failure is projection
    # state, never an admission failure.
    assert _admit_segment(client, session_id, 1, poison).status_code == 200
    assert _admit_segment(client, session_id, 2, b"good segment two.").status_code == 200

    projection = _projection(client, session_id).json()
    kinds = {row["seq"]: row["kind"] for row in projection["transcript"]}
    assert kinds == {0: "segment", 1: "needs_attention", 2: "segment"}
    failed = [row for row in projection["transcript"] if row["seq"] == 1][0]
    assert "engine exploded" in failed["error"]
    assert any(
        item.get("reason") == "asr_failed" and item.get("seq") == 1
        for item in projection["needs_attention"]
    )
    # Analysis derives over the healthy segments only.
    assert [item["seq"] for item in projection["analysis"]["derived_from"]] == [0, 2]
