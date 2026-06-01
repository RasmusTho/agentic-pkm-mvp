"""Direct human note-save API contract tests.

`POST /api/companion/note/save` is the human-initiated direct edit path. Unlike
the Canvas-mediated update flow, it is **not** gated by ``CANVAS_ENABLED`` or
``WORKSPACE_UPDATE_FLOW_ENABLED`` — a human editing their own vault note should
not require agent-governance ceremony. Frontmatter is preserved; the only
retained guard is the runtime-health write block (fail-open when health cannot
be evaluated).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app


def _write_note(path: Path, *, frontmatter: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")


def _clear_gates(monkeypatch) -> None:
    # Prove the save works with NONE of the agent-ceremony gates set.
    monkeypatch.delenv("CANVAS_ENABLED", raising=False)
    monkeypatch.delenv("WORKSPACE_UPDATE_FLOW_ENABLED", raising=False)


def test_human_save_round_trip_without_canvas_or_flow_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _clear_gates(monkeypatch)
    note = tmp_path / "notes" / "My Note.md"
    _write_note(note, frontmatter="title: My Note\nuuid: abc-123", body="Original body.\n")

    client = TestClient(app)
    resp = client.post(
        "/api/companion/note/save",
        json={"note_path": "notes/My Note.md", "new_body": "# Rewritten\n\nNew text by the human.\n"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ok"
    written = note.read_text(encoding="utf-8")
    # Frontmatter preserved verbatim; body replaced.
    assert written.startswith("---\ntitle: My Note\nuuid: abc-123\n---")
    assert "New text by the human." in written
    assert "Original body." not in written


def test_frontmatter_in_body_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _clear_gates(monkeypatch)
    _write_note(tmp_path / "n.md", frontmatter="title: N", body="b\n")

    client = TestClient(app)
    resp = client.post(
        "/api/companion/note/save",
        json={"note_path": "n.md", "new_body": "---\ntitle: hijack\n---\nbad\n"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "frontmatter_in_body"


def test_stale_content_hash_conflicts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _clear_gates(monkeypatch)
    _write_note(tmp_path / "n.md", frontmatter="title: N", body="b\n")

    client = TestClient(app)
    resp = client.post(
        "/api/companion/note/save",
        json={"note_path": "n.md", "new_body": "x\n", "expected_content_hash": "stale"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "content_hash_mismatch"


def test_matching_content_hash_saves(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _clear_gates(monkeypatch)
    note = tmp_path / "n.md"
    _write_note(note, frontmatter="title: N", body="b\n")

    client = TestClient(app)
    # First save returns the current hash; reuse it as the expected token.
    first = client.post("/api/companion/note/save", json={"note_path": "n.md", "new_body": "v1\n"})
    h = first.json()["content_hash"]
    second = client.post(
        "/api/companion/note/save",
        json={"note_path": "n.md", "new_body": "v2\n", "expected_content_hash": h},
    )
    assert second.status_code == 200
    assert "v2" in note.read_text(encoding="utf-8")


def test_url_fragment_in_note_path_normalized_to_canonical_note(tmp_path: Path, monkeypatch) -> None:
    # #1447 — a leaked URL section anchor (#...) must not turn a valid edit into a
    # 404; the fragment is stripped and the canonical note is written.
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _clear_gates(monkeypatch)
    note = tmp_path / "Inbox" / "Note.md"
    _write_note(note, frontmatter="title: N", body="old\n")

    client = TestClient(app)
    resp = client.post(
        "/api/companion/note/save",
        json={"note_path": "Inbox/Note.md#14-3-long-section-c", "new_body": "# Saved\n"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["note_path"] == "Inbox/Note.md"
    assert "# Saved" in note.read_text(encoding="utf-8")


def test_missing_note_is_404(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _clear_gates(monkeypatch)

    client = TestClient(app)
    resp = client.post(
        "/api/companion/note/save",
        json={"note_path": "nope/missing.md", "new_body": "x\n"},
    )
    assert resp.status_code == 404


def test_symlink_escape_rejected_before_save(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("---\ntitle: Outside\n---\nunchanged\n", encoding="utf-8")
    link = vault / "linked.md"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _clear_gates(monkeypatch)

    resp = TestClient(app).post(
        "/api/companion/note/save",
        json={"note_path": "linked.md", "new_body": "changed\n"},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "path_escape"
    assert "unchanged" in outside.read_text(encoding="utf-8")
