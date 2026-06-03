from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_queue import MemoryCandidateReviewQueue
from app.api.app import app
from app.api.routes import companion as companion_module


def _isolate_sources(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "")
    outbox = tmp_path / "index-outbox.jsonl"
    outbox.write_text("", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    return tmp_path / "vault"


def _write_note(
    vault_root: Path,
    relative_path: str,
    *,
    uuid: str,
    review_state: str = "reviewed",
    trust: str = "assert",
) -> Path:
    path = vault_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "title: Memory Source\n"
        f"uuid: {uuid}\n"
        "kind: human_note\n"
        f"review_state: {review_state}\n"
        f"trust: {trust}\n"
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )
    return path


def _candidate(*refs: str) -> MemoryCandidate:
    return MemoryCandidate(
        title="Observed posture candidate",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        source_refs=list(refs),
        generated_by="agent_memory.test",
    )


def test_vault_browser_includes_agent_memory_posture_from_review_queue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault_root = _isolate_sources(tmp_path, monkeypatch)
    note_uuid = "memory-posture-uuid"
    _write_note(vault_root, "notes/memory.md", uuid=note_uuid)
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(
        _candidate(
            "note_path:notes/memory.md",
            f"artifact_uuid:{note_uuid}",
            "session:ignored",
        )
    )
    monkeypatch.setattr(companion_module, "_MEMORY_CANDIDATE_REVIEW_QUEUE", queue)

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    note = next(note for note in resp.json()["notes"] if note["note_path"] == "notes/memory.md")
    posture = note["agent_memory_posture"]
    assert posture["source"] == "agent_memory.review_queue"
    assert posture["authority"] == "non_authoritative"
    assert posture["state"] == "pending"
    assert posture["counts"]["pending"] == 1
    assert posture["items"][0]["status"] == "pending"
    assert posture["items"][0]["review_state"] == "unreviewed"
    assert posture["items"][0]["memory_type"] == "preference_memory"


def test_vault_browser_agent_memory_posture_is_separate_from_frontmatter_and_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault_root = _isolate_sources(tmp_path, monkeypatch)
    note_uuid = "separate-posture-uuid"
    _write_note(vault_root, "notes/separate.md", uuid=note_uuid)
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(_candidate("note_path:notes/separate.md"))
    monkeypatch.setattr(companion_module, "_MEMORY_CANDIDATE_REVIEW_QUEUE", queue)

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    note = next(note for note in resp.json()["notes"] if note["note_path"] == "notes/separate.md")
    assert note["review_state"] == "reviewed"
    assert note["trust"] == "assert"
    assert note["receipts"] == []
    assert note["agent_memory_posture"]["items"][0]["review_state"] == "unreviewed"
    assert "agent_memory_posture" in note
    assert "receipts" in note


def test_vault_browser_agent_memory_posture_read_is_non_mutating(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault_root = _isolate_sources(tmp_path, monkeypatch)
    note_path = _write_note(vault_root, "notes/non-mutating.md", uuid="non-mutating-uuid")
    before_content = note_path.read_text(encoding="utf-8")
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate("note_path:notes/non-mutating.md")
    queue.enqueue(candidate)
    monkeypatch.setattr(companion_module, "_MEMORY_CANDIDATE_REVIEW_QUEUE", queue)
    pending_before = [entry.candidate_id for entry in queue.pending()]
    decided_before = [entry.candidate_id for entry in queue.decided()]

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    assert note_path.read_text(encoding="utf-8") == before_content
    assert [entry.candidate_id for entry in queue.pending()] == pending_before
    assert [entry.candidate_id for entry in queue.decided()] == decided_before
