"""Read-only vault link-index API contract tests (#1431).

`GET /api/companion/vault-link-index` returns the complete active-vault note-path
listing so the Companion UI can seed `VaultLinkResolver` and resolve
vault-internal wikilinks end-to-end. Invariants (per
`docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md` §6 read-only posture and
`companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`):

- complete (not paginated/filtered) note-path enumeration
- hidden / dot-prefixed folder exclusion
- read-only: no mutation, no write path, no file content read
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from tests.api._vault_test_helpers import bind_selected_vault


def _write_note(path: Path, *, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {title}\n---\n\nBody.\n", encoding="utf-8")


def test_returns_complete_index(tmp_path: Path, monkeypatch) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    _write_note(tmp_path / "notes" / "Existing Note.md", title="Existing Note")
    _write_note(tmp_path / "projects" / "Roadmap.md", title="Roadmap")
    _write_note(tmp_path / "Daily" / "2026-01-01.md", title="Daily")
    # excluded: non-markdown and dot-prefixed folder
    (tmp_path / "notes" / "ignore.txt").write_text("nope", encoding="utf-8")
    _write_note(tmp_path / ".obsidian" / "workspace.md", title="Hidden")

    client = TestClient(app)
    resp = client.get("/api/companion/vault-link-index")

    assert resp.status_code == 200
    data = resp.json()
    assert data["read_only"] is True
    assert data["identity_available"] is True
    assert data["vault_identity"]["channel"] == "dev"
    paths = set(data["note_paths"])
    # Complete: every non-hidden markdown note is present (full vault, not capped).
    assert paths == {
        "notes/Existing Note.md",
        "projects/Roadmap.md",
        "Daily/2026-01-01.md",
    }
    assert data["total_notes"] == 3
    assert data["truncated"] is False
    # Hidden + non-markdown excluded.
    assert not any(".obsidian" in p for p in paths)
    assert not any(p.endswith(".txt") for p in paths)


def test_endpoint_is_read_only_and_never_writes(tmp_path: Path, monkeypatch) -> None:
    # AC4 — the endpoint mutates nothing: the vault is byte-identical after the
    # call and the response declares read_only.
    bind_selected_vault(monkeypatch, tmp_path)
    note = tmp_path / "notes" / "Existing Note.md"
    _write_note(note, title="Existing Note")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    client = TestClient(app)
    resp = client.get("/api/companion/vault-link-index")

    assert resp.status_code == 200
    assert resp.json()["read_only"] is True
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before, "link-index endpoint must not create or modify files"


def test_index_respects_truncation_cap(tmp_path: Path, monkeypatch) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("VAULT_LINK_INDEX_MAX", "2")
    for i in range(5):
        _write_note(tmp_path / "notes" / f"Note {i}.md", title=f"Note {i}")

    client = TestClient(app)
    data = client.get("/api/companion/vault-link-index").json()

    assert len(data["note_paths"]) == 2
    assert data["truncated"] is True
