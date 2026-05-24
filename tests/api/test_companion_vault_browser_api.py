"""Vault Browser MLP v0 API contract tests.

These tests pin the MLP v0 invariants from
``docs/VAULT_BROWSER_CAPABILITY_CONTRACT.md`` §6:

- read-only Markdown enumeration (no mutation path)
- active vault identity in the response payload
- deterministic case-insensitive path/title filtering via ``q``
- hidden / dot-prefixed folder exclusion

Future capabilities (metadata filters, inspector, actions, receipts, graph)
are out of scope for this surface; see §7 of the contract.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app


def _write_note(path: Path, *, title: str, body: str = "Body.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {title}\n---\n\n{body}", encoding="utf-8")


def test_vault_browser_lists_markdown_notes_for_active_dev_vault(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _write_note(tmp_path / "notes" / "Companion UI UAT.md", title="Companion UI UAT")
    _write_note(tmp_path / "projects" / "Roadmap.md", title="Roadmap")
    (tmp_path / "notes" / "ignore.txt").write_text("nope", encoding="utf-8")

    client = TestClient(app)
    resp = client.get("/api/companion/vault-browser")

    assert resp.status_code == 200
    data = resp.json()
    assert data["read_only"] is True
    assert data["identity_available"] is True
    assert data["vault_identity"]["channel"] == "dev"
    paths = [note["note_path"] for note in data["notes"]]
    assert "notes/Companion UI UAT.md" in paths
    assert "projects/Roadmap.md" in paths
    assert all(path.endswith(".md") for path in paths)


def test_vault_browser_filters_by_title_or_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _write_note(tmp_path / "notes" / "Companion UI UAT.md", title="Companion UI UAT")
    _write_note(tmp_path / "logs" / "journal.md", title="Daily Journal")
    _write_note(tmp_path / "projects" / "plan.md", title="Project Plan")

    client = TestClient(app)
    by_title = client.get("/api/companion/vault-browser", params={"q": "journal"}).json()
    by_path = client.get("/api/companion/vault-browser", params={"q": "projects"}).json()

    assert by_title["filtered_notes"] == 1
    assert by_title["notes"][0]["title"] == "Daily Journal"
    assert by_path["filtered_notes"] == 1
    assert by_path["notes"][0]["note_path"] == "projects/plan.md"


def test_vault_browser_excludes_hidden_and_system_folders(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _write_note(tmp_path / "notes" / "visible.md", title="Visible")
    _write_note(tmp_path / ".obsidian" / "hidden.md", title="ObsidianHidden")
    _write_note(tmp_path / ".git" / "git_hidden.md", title="GitHidden")
    _write_note(tmp_path / "projects" / ".scratch" / "nested_hidden.md", title="NestedHidden")

    client = TestClient(app)
    resp = client.get("/api/companion/vault-browser")

    assert resp.status_code == 200
    data = resp.json()
    paths = [note["note_path"] for note in data["notes"]]
    assert "notes/visible.md" in paths
    assert not any(p.startswith(".") for p in paths)
    assert not any("/.scratch/" in p or "/.git/" in p or "/.obsidian/" in p for p in paths)


def test_vault_browser_is_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    note_path = tmp_path / "notes" / "immutable.md"
    _write_note(note_path, title="Immutable", body="Original.\n")
    before = note_path.read_text(encoding="utf-8")

    client = TestClient(app)
    get_resp = client.get("/api/companion/vault-browser")
    post_resp = client.post("/api/companion/vault-browser", json={"note_path": "notes/immutable.md"})

    assert get_resp.status_code == 200
    assert get_resp.json()["read_only"] is True
    assert post_resp.status_code == 405
    assert note_path.read_text(encoding="utf-8") == before
