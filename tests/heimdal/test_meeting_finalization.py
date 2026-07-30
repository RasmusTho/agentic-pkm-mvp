"""Meeting finalization (CDLM-08, issue #4388).

Every test drives the production trigger paths: session close via
`POST /api/heimdal/meeting/{id}/close` (which triggers finalization) and
post-close reconciliation via a real late admission through
`POST /api/heimdal/capture/media`. Artifacts land in a real temp vault through
the governed write seam; ASR is stubbed at the shared engine seam.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.app import app
from app.heimdal import meeting_blocks, meeting_finalization
from app.heimdal.consent_ledger import reset_memory_consent_ledger
from app.heimdal.media_receipts import reset_memory_media_receipts
from app.heimdal.raw_store import reset_memory_raw_store
from app.media import transcribe as transcribe_module

pytestmark = pytest.mark.not_pg

_KEY = "9f" * 32
FINALIZED_EVENT = "heimdal.meeting.finalized"


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
    monkeypatch.setenv("HEIMDAL_MEETING_BLOCKS_PATH", str(tmp_path / "blocks.sqlite3"))
    monkeypatch.setenv(
        "HEIMDAL_MEETING_FINALIZATION_PATH", str(tmp_path / "finalization.sqlite3")
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("HEIMDAL_MEETING_VAULT_ROOT", str(vault))
    reset_memory_raw_store()
    reset_memory_consent_ledger()
    reset_memory_media_receipts()
    return tmp_path


@pytest.fixture(autouse=True)
def _asr_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_asr(path_wav: Path, **_: Any) -> dict[str, Any]:
        text = Path(path_wav).read_bytes().decode("utf-8", errors="replace")
        return {"text": text, "segments": [], "language": "en"}

    monkeypatch.setattr(transcribe_module, "run_asr", fake_run_asr)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def vault(_memory_runtime: Path) -> Path:
    return _memory_runtime / "vault"


def _open_session(client: TestClient, session_id: str):
    return client.post(
        "/api/heimdal/meeting/session",
        json={"session_id": session_id, "device_id": "ipad-1", "template_selection": {}},
    )


def _close(client: TestClient, session_id: str, count: int):
    return client.post(
        f"/api/heimdal/meeting/{session_id}/close", json={"final_seq_count": count}
    )


def _admit(client: TestClient, session_id: str, seq: int, media: bytes):
    sidecar = {
        "capture_id": str(uuid4()),
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


def _write_note(client: TestClient, session_id: str, note_id: str, revision: int, text: str):
    return client.post(
        f"/api/heimdal/meeting/{session_id}/user-note",
        json={
            "note_block_id": note_id,
            "revision": revision,
            "text": text,
            "editor_identity": "operator@ipad-1",
        },
    )


def _frontmatter(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    front, sep, _ = raw.removeprefix("---\n").partition("\n---\n")
    assert sep
    return yaml.safe_load(front)


def _events(tmp: Path, event: str) -> list[dict[str, Any]]:
    outbox = tmp / "outbox.jsonl"
    if not outbox.exists():
        return []
    return [
        rec
        for rec in (json.loads(line) for line in outbox.read_text().splitlines() if line.strip())
        if rec.get("event") == event
    ]


def test_three_artifacts_materialize_with_correct_classes(
    client: TestClient, vault: Path
) -> None:
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    for seq in (0, 1):
        assert _admit(client, session_id, seq, f"we decided item {seq}.".encode()).status_code == 200
    note_id = str(uuid4())
    assert _write_note(client, session_id, note_id, 1, "my own thoughts").status_code == 200

    closed = _close(client, session_id, 2)
    assert closed.status_code == 200, closed.text
    finalization = closed.json()["finalization"]
    assert finalization["status"] == "finalized"
    refs = finalization["receipt"]["artifact_refs"]

    transcript = _frontmatter(vault / refs["transcript"])
    assert transcript["artifact_class"] == "meeting_transcript"
    assert transcript["zone"] == "sources"
    assert transcript["note_class"] == "create-once"
    assert transcript["completeness"] == "complete"
    assert transcript["provenance"]["kind"] == "derived"

    analysis = _frontmatter(vault / refs["analysis"])
    assert analysis["artifact_class"] == "meeting_analysis"
    assert analysis["standing"] == "draft"
    assert "human" in analysis["promotion"]
    assert analysis["template_id"] == "generic-default@1"
    assert analysis["provenance"]["kind"] == "derived"

    notes = _frontmatter(vault / refs["user_notes"])
    assert notes["artifact_class"] == "meeting_user_notes"
    assert notes["provenance"]["kind"] == "human"
    assert notes["note_blocks"][0]["block_id"] == note_id
    # Derived text never interleaves with the user's artifact.
    body = (vault / refs["user_notes"]).read_text()
    assert "my own thoughts" in body
    assert "we decided item" not in body


def test_finalization_idempotent_per_ledger_state(client: TestClient, vault: Path) -> None:
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    assert _admit(client, session_id, 0, b"only segment.").status_code == 200
    first = _close(client, session_id, 1)
    assert first.json()["finalization"]["status"] == "finalized"

    files_after_first = sorted(p.relative_to(vault) for p in vault.rglob("*.md"))

    # Re-triggering close (idempotent replay) with an unchanged ledger reuses
    # the existing finalization and creates nothing.
    second = _close(client, session_id, 1)
    assert second.status_code == 200
    assert second.json()["finalization"]["status"] == "replayed"
    assert second.json()["finalization"]["receipt"] == first.json()["finalization"]["receipt"]
    assert sorted(p.relative_to(vault) for p in vault.rglob("*.md")) == files_after_first


def test_gapped_close_is_legible_everywhere(
    client: TestClient, vault: Path
) -> None:
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    for seq in (0, 1, 3):
        assert _admit(client, session_id, seq, f"segment {seq} text.".encode()).status_code == 200
    closed = _close(client, session_id, 4)
    finalization = closed.json()["finalization"]
    receipt = finalization["receipt"]
    assert receipt["completeness"] == "needs_attention"
    assert receipt["missing_seqs"] == [2]

    projection = client.get(f"/api/heimdal/meeting/{session_id}/projection").json()
    assert projection["finalization"]["completeness"] == "needs_attention"
    assert projection["finalization"]["missing_seqs"] == [2]

    for name in ("transcript", "analysis"):
        front = _frontmatter(vault / receipt["artifact_refs"][name])
        assert front["completeness"] == "needs_attention"
        assert front["missing_seqs"] == [2]
    body = (vault / receipt["artifact_refs"]["transcript"]).read_text()
    assert "missing segment" in body


def test_post_close_reconciliation_supersedes_with_lineage(
    client: TestClient, vault: Path
) -> None:
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    for seq in (0, 1, 3):
        assert _admit(client, session_id, seq, f"segment {seq} text.".encode()).status_code == 200
    first_receipt = _close(client, session_id, 4).json()["finalization"]["receipt"]
    first_files = {
        p: (vault / p).read_bytes() for p in first_receipt["artifact_refs"].values()
    }

    # Late admission through the production path triggers re-finalization.
    assert _admit(client, session_id, 2, b"late segment two.").status_code == 200

    latest = meeting_finalization.latest_receipt(session_id)
    assert latest is not None
    assert latest["finalization_state"] != first_receipt["finalization_state"]
    assert latest["supersedes"] == first_receipt["finalization_state"]
    assert latest["completeness"] == "complete"
    assert latest["missing_seqs"] == []

    # New artifacts under new paths; old artifacts byte-identical in place.
    assert set(latest["artifact_refs"].values()).isdisjoint(first_files.keys())
    for rel, original in first_files.items():
        assert (vault / rel).read_bytes() == original
    new_front = _frontmatter(vault / latest["artifact_refs"]["transcript"])
    assert new_front["supersedes"] == first_receipt["finalization_state"]


def test_user_notes_materialize_verbatim_via_guard(client: TestClient, vault: Path) -> None:
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    assert _admit(client, session_id, 0, b"segment zero.").status_code == 200
    note_id = str(uuid4())
    note_text = "Exact bytes:\n- tabs\tand trailing space \n- unicode é å 中文"
    assert _write_note(client, session_id, note_id, 1, note_text).status_code == 200
    block_before = meeting_blocks.get_block(note_id)

    receipt = _close(client, session_id, 1).json()["finalization"]["receipt"]
    body = (vault / receipt["artifact_refs"]["user_notes"]).read_text(encoding="utf-8")
    assert note_text in body  # byte-identical content present, unaltered

    # Finalization's own write went through the CDLM-07 guard as the derived
    # finalization writer: its receipt block exists with that provenance...
    short = receipt["finalization_state"][:8]
    guard_block = meeting_blocks.get_block(f"{session_id}:finalization:{short}")
    assert guard_block is not None
    assert guard_block.provenance["engine"] == "heimdal-meeting-finalization"
    assert guard_block.provenance["role"] == "finalization"
    # ...and the same writer is structurally refused on the user note, whose
    # registry content is untouched by finalization.
    refused = meeting_blocks.apply_block_write(
        session_id=session_id,
        writer=meeting_finalization.FINALIZATION_WRITER,
        action=meeting_blocks.ACTION_REVISE,
        block_id=note_id,
        content="machine rewrite",
    )
    assert refused.allowed is False
    block_after = meeting_blocks.get_block(note_id)
    assert block_after.content == note_text == block_before.content
    assert block_after.revision == block_before.revision


def test_unsafe_session_ids_never_reach_path_construction(
    client: TestClient, vault: Path
) -> None:
    """A path-hostile session id maps to a digest slug inside the Meetings zone."""
    from app.heimdal import meeting_ledger

    # The sanitizer itself: every hostile shape maps to the digest namespace.
    for hostile in ("../evil", "..", "a/../../b", "evil/", ".hidden", "a\\b", "x" * 200):
        component = meeting_finalization._session_path_component(hostile)
        assert component.startswith("sess-"), hostile
        assert "/" not in component and ".." not in component
    assert meeting_finalization._session_path_component("mtg-42") == "mtg-42"

    # End to end below the HTTP layer (URL normalization would otherwise mask
    # the id before it reaches the route): a hostile id finalizes into the
    # digest directory, never outside the Meetings zone.
    session_id = "../evil"
    meeting_ledger.open_meeting_session(session_id=session_id, device_id="ipad-1")
    assert _admit(client, session_id, 0, b"segment zero.").status_code == 200
    meeting_ledger.close_meeting_session(session_id=session_id, final_seq_count=1)
    outcome = meeting_finalization.finalize_session(session_id)
    assert outcome["status"] == "finalized"
    for rel in outcome["receipt"]["artifact_refs"].values():
        assert rel.startswith("Sources/Meetings/sess-")
        assert ".." not in rel
        assert (vault / rel).resolve().is_relative_to(vault / "Sources" / "Meetings")


def test_healed_asr_failure_supersedes_stale_artifacts(
    client: TestClient, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed→ok derivation retry changes the finalization state (not just the ledger)."""
    poison = b"poisoned segment."

    def flaky(path_wav: Path, **_: Any) -> dict[str, Any]:
        data = Path(path_wav).read_bytes()
        if data == poison:
            raise RuntimeError("engine down")
        return {"text": data.decode(), "segments": [], "language": "en"}

    monkeypatch.setattr(transcribe_module, "run_asr", flaky)
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    assert _admit(client, session_id, 0, poison).status_code == 200
    first = _close(client, session_id, 1).json()["finalization"]["receipt"]
    assert "derivation failed" in (vault / first["artifact_refs"]["transcript"]).read_text()

    # Heal the derivation via a resend, then re-trigger close: the state
    # identity changed, so finalization supersedes instead of replaying.
    def healthy(path_wav: Path, **_: Any) -> dict[str, Any]:
        return {"text": Path(path_wav).read_bytes().decode(), "segments": [], "language": "en"}

    monkeypatch.setattr(transcribe_module, "run_asr", healthy)
    # The healing resend ALONE re-finalizes (admission-path trigger fires on a
    # replay into a closed, already-finalized session) — no re-close needed.
    assert _admit(client, session_id, 0, poison).status_code == 200
    healed = meeting_finalization.latest_receipt(session_id)
    assert healed is not None
    assert healed["supersedes"] == first["finalization_state"]
    second = _close(client, session_id, 1).json()["finalization"]
    assert second["status"] == "replayed"
    assert second["receipt"]["supersedes"] == first["finalization_state"]
    assert "poisoned segment." in (
        vault / second["receipt"]["artifact_refs"]["transcript"]
    ).read_text()


def test_receipt_and_event_before_finalized_ack(
    client: TestClient, _memory_runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = f"mtg-{uuid4()}"
    assert _open_session(client, session_id).status_code == 200
    assert _admit(client, session_id, 0, b"segment zero.").status_code == 200

    # A failed event commit acknowledges nothing as finalized: no receipt,
    # named failure in the close response, close itself still succeeds.
    real = meeting_finalization.outbox_service.append_jsonl_outbox_event

    def failing(*a: Any, **k: Any) -> bool:
        raise RuntimeError("sink down")

    monkeypatch.setattr(
        meeting_finalization.outbox_service, "append_jsonl_outbox_event", failing
    )
    closed = _close(client, session_id, 1)
    assert closed.status_code == 200
    assert closed.json()["closed"] is True
    assert closed.json()["finalization"]["status"] == "failed"
    assert meeting_finalization.latest_receipt(session_id) is None
    assert _events(_memory_runtime, FINALIZED_EVENT) == []

    # Re-trigger heals: event commits, then the receipt row is the ack.
    monkeypatch.setattr(
        meeting_finalization.outbox_service, "append_jsonl_outbox_event", real
    )
    healed = _close(client, session_id, 1)
    assert healed.json()["finalization"]["status"] == "finalized"
    events = _events(_memory_runtime, FINALIZED_EVENT)
    assert len(events) == 1
    receipt = meeting_finalization.latest_receipt(session_id)
    assert receipt is not None
    assert events[0]["payload"]["finalization_state"] == receipt["finalization_state"]

    # Replay: no second event, same receipt.
    replay = _close(client, session_id, 1)
    assert replay.json()["finalization"]["status"] == "replayed"
    assert len(_events(_memory_runtime, FINALIZED_EVENT)) == 1
