"""Meeting block ownership guard (CDLM-07, issue #4387).

The guard (`app.heimdal.meeting_blocks.apply_block_write`) is the one seam
every production block mutation passes through — user edits via the user-note
route, transcript blocks via the real admission path, analysis blocks via the
real analysis re-derivation. The enforcement tests drive those production
paths end to end, and exercise each production writer *identity* (analysis,
reconciliation, template re-render, finalization) against user_note targets
through the same guard function those paths call.
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
from app.heimdal import meeting_blocks
from app.heimdal.consent_ledger import reset_memory_consent_ledger
from app.heimdal.media_receipts import reset_memory_media_receipts
from app.heimdal.raw_store import reset_memory_raw_store
from app.media import transcribe as transcribe_module

pytestmark = pytest.mark.not_pg

_KEY = "9f" * 32
USER_NOTE_EVENT = "heimdal.meeting.user_note.written"

DERIVED_WRITERS = [
    meeting_blocks.WriterIdentity(
        kind=meeting_blocks.WRITER_DERIVED, engine="heimdal-meeting-analysis", role="analysis"
    ),
    meeting_blocks.WriterIdentity(
        kind=meeting_blocks.WRITER_DERIVED,
        engine="heimdal-meeting-analysis",
        role="reconciliation",
    ),
    meeting_blocks.WriterIdentity(
        kind=meeting_blocks.WRITER_DERIVED,
        engine="heimdal-meeting-analysis",
        role="template_render",
    ),
    meeting_blocks.WriterIdentity(
        kind=meeting_blocks.WRITER_DERIVED,
        engine="heimdal-meeting-finalization",
        role="finalization",
    ),
]


@pytest.fixture(autouse=True)
def _memory_runtime(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    if request.node.get_closest_marker("pg") is None:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY)
    outbox = tmp_path / "outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("HEIMDAL_MEETING_LEDGER_PATH", str(tmp_path / "ledger.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_PROJECTION_PATH", str(tmp_path / "projection.sqlite3"))
    monkeypatch.setenv("HEIMDAL_MEETING_BLOCKS_PATH", str(tmp_path / "blocks.sqlite3"))
    reset_memory_raw_store()
    reset_memory_consent_ledger()
    reset_memory_media_receipts()
    return outbox


@pytest.fixture(autouse=True)
def _asr_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_asr(path_wav: Path, **_: Any) -> dict[str, Any]:
        text = Path(path_wav).read_bytes().decode("utf-8", errors="replace")
        return {"text": text, "segments": [], "language": "en"}

    monkeypatch.setattr(transcribe_module, "run_asr", fake_run_asr)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _open_session(client: TestClient, session_id: str):
    return client.post(
        "/api/heimdal/meeting/session",
        json={"session_id": session_id, "device_id": "ipad-1", "template_selection": {}},
    )


def _admit_segment(client: TestClient, session_id: str, seq: int, media: bytes, **kw: Any):
    sidecar = {
        "capture_id": kw.get("capture_id") or str(uuid4()),
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
            "media": (f"seg-{seq}.m4a", media, "audio/m4a"),
            "sidecar": ("sidecar.json", json.dumps(sidecar), "application/json"),
        },
    )


def _write_note(
    client: TestClient,
    session_id: str,
    note_block_id: str,
    revision: int,
    text: str,
    editor: str = "operator@ipad-1",
):
    return client.post(
        f"/api/heimdal/meeting/{session_id}/user-note",
        json={
            "note_block_id": note_block_id,
            "revision": revision,
            "text": text,
            "editor_identity": editor,
        },
    )


def _projection(client: TestClient, session_id: str):
    return client.get(f"/api/heimdal/meeting/{session_id}/projection")


def _events(outbox: Path, event: str) -> list[dict[str, Any]]:
    if not outbox.exists():
        return []
    return [
        rec
        for rec in (
            json.loads(line) for line in outbox.read_text().splitlines() if line.strip()
        )
        if rec.get("event") == event
    ]


def test_derived_writers_cannot_touch_user_notes(client: TestClient) -> None:
    """Every derived writer path is refused on user_note targets; content untouched."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    note_id = str(uuid4())
    original = "My own thinking — do not touch."
    assert _write_note(client, session_id, note_id, 1, original).status_code == 200

    for writer in DERIVED_WRITERS:
        for action in (
            meeting_blocks.ACTION_REVISE,
            meeting_blocks.ACTION_MOVE,
            meeting_blocks.ACTION_RETIRE,
        ):
            outcome = meeting_blocks.apply_block_write(
                session_id=session_id,
                writer=writer,
                action=action,
                block_id=note_id,
                content="machine rewrite",
                position=999,
            )
            assert outcome.allowed is False, (writer.role, action)
    # A derived writer also cannot CREATE a user_note.
    refused_create = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=DERIVED_WRITERS[0],
        action=meeting_blocks.ACTION_CREATE,
        block_id=str(uuid4()),
        block_type=meeting_blocks.TYPE_USER_NOTE,
        content="machine note",
    )
    assert refused_create.allowed is False

    block = meeting_blocks.get_block(note_id)
    assert block is not None and block.content == original and block.retired is False

    # Every refusal is recorded and surfaced on the projection read.
    projection = _projection(client, session_id).json()
    refusals = [
        item for item in projection["needs_attention"] if item.get("reason") == "block_write_refused"
    ]
    assert len(refusals) == len(DERIVED_WRITERS) * 3 + 1
    assert all(item["attempted_by"]["kind"] == "derived" for item in refusals)


def test_ambiguous_ownership_fails_closed(client: TestClient) -> None:
    """Unknown block id / unknown type / conflicting ownership all refuse."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    user = meeting_blocks.WriterIdentity(
        kind=meeting_blocks.WRITER_USER_EDITOR, editor_identity="operator@ipad-1"
    )
    analysis = DERIVED_WRITERS[0]

    # Unknown block id.
    assert (
        meeting_blocks.apply_block_write(
            session_id=session_id,
            writer=user,
            action=meeting_blocks.ACTION_REVISE,
            block_id=str(uuid4()),
            content="x",
        ).allowed
        is False
    )
    # Unknown type on create.
    assert (
        meeting_blocks.apply_block_write(
            session_id=session_id,
            writer=analysis,
            action=meeting_blocks.ACTION_CREATE,
            block_id=str(uuid4()),
            block_type="mystery_block",
            content="x",
        ).allowed
        is False
    )
    # Unknown writer kind.
    weird = meeting_blocks.WriterIdentity(kind="daemon")
    assert (
        meeting_blocks.apply_block_write(
            session_id=session_id,
            writer=weird,
            action=meeting_blocks.ACTION_CREATE,
            block_id=str(uuid4()),
            block_type=meeting_blocks.TYPE_DERIVED_PROJECTION,
            content="x",
        ).allowed
        is False
    )
    # Conflicting ownership: a user editor revising a derived block.
    created = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=analysis,
        action=meeting_blocks.ACTION_CREATE,
        block_id=f"{session_id}:analysis:summary-test",
        block_type=meeting_blocks.TYPE_DERIVED_PROJECTION,
        content="derived text",
    )
    assert created.allowed is True
    conflicted = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=user,
        action=meeting_blocks.ACTION_REVISE,
        block_id=f"{session_id}:analysis:summary-test",
        content="user rewrite of machine block",
    )
    assert conflicted.allowed is False
    block = meeting_blocks.get_block(f"{session_id}:analysis:summary-test")
    assert block is not None and block.content == "derived text"


def test_user_note_write_idempotent_and_durable(
    client: TestClient, _memory_runtime: Path
) -> None:
    """Idempotent by (note_block_id, revision); ack only after durable write + event."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    note_id = str(uuid4())

    first = _write_note(client, session_id, note_id, 1, "first thought")
    assert first.status_code == 200, first.text
    assert "idempotent_replay" not in first.json()
    assert len(_events(_memory_runtime, USER_NOTE_EVENT)) == 1

    replay = _write_note(client, session_id, note_id, 1, "first thought")
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert len(_events(_memory_runtime, USER_NOTE_EVENT)) == 1  # no second event

    # A failed event commit acknowledges nothing: no revision row, resend heals.
    import app.api.routes.heimdal_meeting as meeting_route

    real = meeting_route.outbox_service.append_jsonl_outbox_event
    try:
        def failing(*a: Any, **k: Any) -> bool:
            raise RuntimeError("sink down")

        meeting_route.outbox_service.append_jsonl_outbox_event = failing  # type: ignore[assignment]
        refused = _write_note(client, session_id, note_id, 2, "second thought")
        assert refused.status_code == 500
        assert refused.json()["detail"]["error"] == "note_event_commit_failed"
        assert meeting_blocks.get_note_revision(note_id, 2) is None
    finally:
        meeting_route.outbox_service.append_jsonl_outbox_event = real  # type: ignore[assignment]

    healed = _write_note(client, session_id, note_id, 2, "second thought")
    assert healed.status_code == 200
    assert meeting_blocks.get_note_revision(note_id, 2) is not None

    # Durable across a simulated restart: history and block survive from files.
    reset_memory_raw_store()
    reset_memory_media_receipts()
    restarted = TestClient(app)
    replay2 = _write_note(restarted, session_id, note_id, 2, "second thought")
    assert replay2.status_code == 200 and replay2.json()["idempotent_replay"] is True
    history = meeting_blocks.note_revisions(note_id)
    assert [rev["revision"] for rev in history] == [1, 2]
    block = meeting_blocks.get_block(note_id)
    assert block is not None and block.content == "second thought"


def test_user_notes_survive_all_derived_passes(client: TestClient) -> None:
    """Analysis revision, template re-render, late reconciliation: notes byte-identical."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    note_id = str(uuid4())
    note_text = "Ideas:\n- keep bytes exactly\n- même les accents é å 中文"
    assert _write_note(client, session_id, note_id, 1, note_text).status_code == 200
    snapshot = meeting_blocks.get_block(note_id)
    assert snapshot is not None

    # Analysis derivation over real admissions (production derived pass #1).
    for seq in (0, 1, 3):
        assert _admit_segment(client, session_id, seq, f"we decided item {seq}.".encode()).status_code == 200
    # Close, then late reconciliation (production derived pass #2).
    assert client.post(
        f"/api/heimdal/meeting/{session_id}/close", json={"final_seq_count": 4}
    ).status_code == 200
    assert _admit_segment(client, session_id, 2, b"late segment two.").status_code == 200
    # Template re-render pass through the guard seam (no second template ships,
    # so the production re-render is exercised as its writer identity re-emitting
    # its own derived blocks — allowed — while the note stays untouched).
    rerender = meeting_blocks.WriterIdentity(
        kind=meeting_blocks.WRITER_DERIVED,
        engine="heimdal-meeting-analysis",
        role="analysis",
    )
    summary_block_id = f"{session_id}:analysis:summary"
    assert meeting_blocks.get_block(summary_block_id) is not None
    assert meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=rerender,
        action=meeting_blocks.ACTION_REVISE,
        block_id=summary_block_id,
        content=json.dumps("re-rendered summary"),
    ).allowed is True

    after = meeting_blocks.get_block(note_id)
    assert after is not None
    assert after.content == note_text  # byte-identical
    assert after.content.encode("utf-8") == snapshot.content.encode("utf-8")
    assert after.position == snapshot.position  # in place
    assert after.provenance == snapshot.provenance  # provenance intact
    assert after.revision == snapshot.revision

    # And the projection still carries the analysis outcome, so the derived
    # passes genuinely ran.
    projection = _projection(client, session_id).json()
    assert projection["analysis"]["revision"] is not None
    note_rows = [b for b in projection["page_blocks"] if b["block_id"] == note_id]
    assert note_rows and note_rows[0]["content"] == note_text


def test_derived_writers_confined_to_own_provenance(client: TestClient) -> None:
    """No move/merge/reorder/renumber outside a derived writer's own provenance."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    # A real transcript block minted through the production admission path.
    assert _admit_segment(client, session_id, 0, b"hello transcript.").status_code == 200
    transcript_id = f"{session_id}:transcript:0"
    transcript = meeting_blocks.get_block(transcript_id)
    assert transcript is not None

    analysis = DERIVED_WRITERS[0]
    finalization = DERIVED_WRITERS[3]

    # Analysis writer cannot move/revise/retire the ASR-owned transcript block.
    for action in (
        meeting_blocks.ACTION_MOVE,
        meeting_blocks.ACTION_REVISE,
        meeting_blocks.ACTION_RETIRE,
    ):
        assert (
            meeting_blocks.apply_block_write(
                session_id=session_id,
                writer=analysis,
                action=action,
                block_id=transcript_id,
                content="tampered",
                position=42,
            ).allowed
            is False
        ), action
    # Finalization writer cannot touch analysis-owned blocks either.
    summary_id = f"{session_id}:analysis:summary"
    assert meeting_blocks.get_block(summary_id) is not None
    assert (
        meeting_blocks.apply_block_write(
            session_id=session_id,
            writer=finalization,
            action=meeting_blocks.ACTION_MOVE,
            block_id=summary_id,
            position=7,
        ).allowed
        is False
    )
    # Untouched: content and position preserved.
    assert meeting_blocks.get_block(transcript_id).content == "hello transcript."
    assert meeting_blocks.get_block(transcript_id).position == 0

    # Its own provenance remains writable (the boundary confines, not disables).
    own = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=analysis,
        action=meeting_blocks.ACTION_MOVE,
        block_id=summary_id,
        position=1_000_500,
    )
    assert own.allowed is True


def test_replays_and_revisions_never_bypass_authorization(client: TestClient) -> None:
    """Convergence-review regressions: replays are authorized; revisions honest."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    note_id = str(uuid4())
    assert _write_note(client, session_id, note_id, 1, "mine").status_code == 200

    # A wrong editor replaying IDENTICAL text gets refused, not a success ack.
    wrong_editor = _write_note(client, session_id, note_id, 1, "mine", editor="intruder")
    assert wrong_editor.status_code == 409
    assert wrong_editor.json()["detail"]["error"] == "block_write_refused"

    # A derived block id targeted through the user-note route cannot mint a
    # user-note ack/history row: derived ids are structured (non-UUID), and
    # the route's UUID contract refuses them before anything else runs.
    assert _admit_segment(client, session_id, 0, b"transcript text.").status_code == 200
    derived_id = f"{session_id}:transcript:0"
    forged = _write_note(client, session_id, derived_id, 1, "transcript text.")
    assert forged.status_code == 422
    assert meeting_blocks.note_revisions(derived_id) == []
    # And even below the route, the guard itself refuses the same attempt.
    guard_forged = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=meeting_blocks.WriterIdentity(
            kind=meeting_blocks.WRITER_USER_EDITOR, editor_identity="operator@ipad-1"
        ),
        action=meeting_blocks.ACTION_REVISE,
        block_id=derived_id,
        content="user rewrite",
    )
    assert guard_forged.allowed is False

    # Same (note, revision) with different text: named conflict, stored text wins.
    conflict = _write_note(client, session_id, note_id, 1, "rewritten history")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "note_revision_conflict"
    assert meeting_blocks.get_block(note_id).content == "mine"

    # Stale (lower/equal, non-replay) revision numbers are refused.
    assert _write_note(client, session_id, note_id, 3, "third").status_code == 200
    stale = _write_note(client, session_id, note_id, 2, "late arrival")
    assert stale.status_code == 409
    assert stale.json()["detail"]["error"] == "stale_note_revision"

    # provenance_extra can never override structural provenance keys.
    analysis = DERIVED_WRITERS[0]
    outcome = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=analysis,
        action=meeting_blocks.ACTION_CREATE,
        block_id=f"{session_id}:analysis:poisoned",
        block_type=meeting_blocks.TYPE_DERIVED_PROJECTION,
        content="x",
        provenance_extra={"kind": "user_editor", "engine": "other", "note": "kept"},
    )
    assert outcome.allowed is True
    prov = outcome.block.provenance
    assert prov["kind"] == "derived"
    assert prov["engine"] == "heimdal-meeting-analysis"
    assert prov["note"] == "kept"

    # A verify_only probe mirrors the real create path exactly: a non-ASR
    # derived writer probing a transcript_segment create is refused, and the
    # probe never inserts anything.
    probe_id = f"{session_id}:transcript:999"
    probe = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=analysis,
        action=meeting_blocks.ACTION_CREATE,
        block_id=probe_id,
        block_type=meeting_blocks.TYPE_TRANSCRIPT_SEGMENT,
        content="probe",
        verify_only=True,
    )
    assert probe.allowed is False
    assert meeting_blocks.get_block(probe_id) is None
    allowed_probe = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=analysis,
        action=meeting_blocks.ACTION_CREATE,
        block_id=f"{session_id}:analysis:probe",
        block_type=meeting_blocks.TYPE_DERIVED_PROJECTION,
        content="probe",
        verify_only=True,
    )
    assert allowed_probe.allowed is True
    assert meeting_blocks.get_block(f"{session_id}:analysis:probe") is None


def test_editor_identity_required_for_user_notes(client: TestClient) -> None:
    """Only the user's editor identity passes; forged identities from derived contexts refuse."""
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    note_id = str(uuid4())
    assert _write_note(client, session_id, note_id, 1, "mine", editor="operator@ipad-1").status_code == 200

    # A derived writer carrying a *forged* editor_identity string is still a
    # derived writer: the guard keys on the structural kind, not the string.
    forged = meeting_blocks.WriterIdentity(
        kind=meeting_blocks.WRITER_DERIVED,
        engine="heimdal-meeting-analysis",
        role="analysis",
        editor_identity="operator@ipad-1",
    )
    assert (
        meeting_blocks.apply_block_write(
            session_id=session_id,
            writer=forged,
            action=meeting_blocks.ACTION_REVISE,
            block_id=note_id,
            content="forged rewrite",
        ).allowed
        is False
    )

    # A different editor identity than the note's recorded editor refuses at
    # the production seam (the route), preserving content.
    other = _write_note(client, session_id, note_id, 2, "other editor", editor="someone-else")
    assert other.status_code == 409
    assert other.json()["detail"]["error"] == "block_write_refused"
    assert meeting_blocks.get_block(note_id).content == "mine"

    # The recorded editor still writes normally.
    ok = _write_note(client, session_id, note_id, 2, "still mine", editor="operator@ipad-1")
    assert ok.status_code == 200
    assert meeting_blocks.get_block(note_id).content == "still mine"
