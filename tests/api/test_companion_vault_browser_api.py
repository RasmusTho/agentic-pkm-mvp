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

import json
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
    # Dot-prefixed filenames in a non-hidden folder are NOT excluded (only folders are).
    _write_note(tmp_path / "notes" / ".daily.md", title="DotPrefixedFile")

    client = TestClient(app)
    resp = client.get("/api/companion/vault-browser")

    assert resp.status_code == 200
    data = resp.json()
    paths = [note["note_path"] for note in data["notes"]]
    assert "notes/visible.md" in paths
    # Dot-prefixed files in normal folders remain visible.
    assert "notes/.daily.md" in paths
    # Dot-prefixed directories are excluded entirely.
    assert not any("/.scratch/" in p or "/.git/" in p or "/.obsidian/" in p for p in paths)
    assert not any(p.startswith(".obsidian/") or p.startswith(".git/") for p in paths)


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


def test_vault_browser_cap_preserves_lexicographic_subset(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "2")
    _write_note(tmp_path / "z" / "late.md", title="Late")
    _write_note(tmp_path / "a" / "first.md", title="First")
    _write_note(tmp_path / "m" / "middle.md", title="Middle")
    data = TestClient(app).get("/api/companion/vault-browser").json()
    assert [n["note_path"] for n in data["notes"]] == ["a/first.md", "m/middle.md"]


def test_vault_browser_returns_pagination_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    _write_note(tmp_path / "a" / "first.md", title="First")
    _write_note(tmp_path / "b" / "second.md", title="Second")
    _write_note(tmp_path / "c" / "third.md", title="Third")

    resp = TestClient(app).get("/api/companion/vault-browser", params={"limit": 2})

    assert resp.status_code == 200
    data = resp.json()
    assert [note["note_path"] for note in data["notes"]] == [
        "a/first.md",
        "b/second.md",
    ]
    assert data["pagination"] == {
        "mode": "cursor",
        "cursor": None,
        "next_cursor": "b/second.md",
        "page_size": 2,
        "returned_notes": 2,
        "total_filtered_notes": 3,
        "has_next": True,
        "has_previous": False,
    }


def test_vault_browser_pagination_composes_with_metadata_filters(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    for relative, title, kind in (
        ("a/alpha.md", "Alpha", "human_note"),
        ("b/companion.md", "Companion", "companion_note"),
        ("c/charlie.md", "Charlie", "human_note"),
    ):
        note = tmp_path / relative
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            f"---\ntitle: {title}\nuuid: {title.lower()}\nkind: {kind}\n---\n\n{title}.\n",
            encoding="utf-8",
        )

    client = TestClient(app)
    first_page = client.get(
        "/api/companion/vault-browser",
        params={"kind": "human_note", "limit": 1},
    ).json()
    second_page = client.get(
        "/api/companion/vault-browser",
        params={
            "kind": "human_note",
            "limit": 1,
            "cursor": first_page["pagination"]["next_cursor"],
        },
    ).json()

    assert first_page["active_filters"] == {"kind": ["human_note"]}
    assert first_page["filtered_notes"] == 2
    assert [note["note_path"] for note in first_page["notes"]] == ["a/alpha.md"]
    assert first_page["pagination"]["next_cursor"] == "a/alpha.md"
    assert [note["note_path"] for note in second_page["notes"]] == ["c/charlie.md"]
    assert second_page["pagination"]["has_next"] is False
    assert all(note["kind"] == "human_note" for note in second_page["notes"])


def test_vault_browser_pagination_is_read_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    first = tmp_path / "a" / "first.md"
    second = tmp_path / "b" / "second.md"
    _write_note(first, title="First")
    _write_note(second, title="Second")
    before = {
        first: first.read_text(encoding="utf-8"),
        second: second.read_text(encoding="utf-8"),
    }

    resp = TestClient(app).get(
        "/api/companion/vault-browser",
        params={"limit": 1, "cursor": "a/first.md"},
    )

    assert resp.status_code == 200
    assert [note["note_path"] for note in resp.json()["notes"]] == ["b/second.md"]
    assert first.read_text(encoding="utf-8") == before[first]
    assert second.read_text(encoding="utf-8") == before[second]


def test_vault_browser_includes_receipts_from_outbox_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    note_uuid = "00000000-0000-0000-0000-000000001279"
    note_path = tmp_path / "vault" / "notes" / "receipt.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\ntitle: Receipt Note\nuuid: {note_uuid}\n---\n\nBody.\n",
        encoding="utf-8",
    )
    outbox.write_text(
        json.dumps(
            {
                "event": "promotion.transition.applied",
                "event_id": "evt-receipt-1279",
                "trace_id": "trace-receipt-1279",
                "source": "promotion.consumer",
                "timestamp": "2026-05-30T12:00:00Z",
                "payload": {
                    "intent_event_id": "intent-1279",
                    "note_uuid": note_uuid,
                    "note_path": "notes/receipt.md",
                    "outcome": {"status": "applied"},
                    "authority": {"component": "panel_agent.runtime"},
                    "artifact_linkage": {
                        "note_uuid": note_uuid,
                        "note_path": "notes/receipt.md",
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    receipt_note = next(
        note for note in resp.json()["notes"] if note["note_path"] == "notes/receipt.md"
    )
    assert receipt_note["receipts"] == [
        {
            "receipt_id": "evt-receipt-1279",
            "trace_id": "trace-receipt-1279",
            "action_id": "intent-1279",
            "action_type": "promotion.transition.applied",
            "artifact_uuid": note_uuid,
            "artifact_path": "notes/receipt.md",
            "path": "notes/receipt.md",
            "requested_by": "panel_agent.runtime",
            "approved_by": None,
            "status": "applied",
            "timestamp": "2026-05-30T12:00:00Z",
            "state": "applied",
        }
    ]


def test_vault_browser_omits_receipts_when_receipt_source_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "missing-outbox.jsonl"))
    _write_note(tmp_path / "vault" / "notes" / "no-source.md", title="No Source")

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    note = resp.json()["notes"][0]
    assert note["note_path"] == "notes/no-source.md"
    assert "receipts" not in note
