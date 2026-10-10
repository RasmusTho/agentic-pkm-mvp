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

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from tests.api._vault_test_helpers import bind_selected_vault


def _write_note(path: Path, *, title: str, body: str = "Body.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {title}\n---\n\n{body}", encoding="utf-8")


def _fail_browser_file(monkeypatch, path: Path, *, operation: str = "read") -> None:
    if operation.startswith(("stat", "lstat")):
        original_stat = Path.stat

        def failing_stat(candidate, *, follow_symlinks=True):
            if candidate == path and follow_symlinks == (not operation.startswith("lstat")):
                if operation.endswith("_missing"):
                    raise FileNotFoundError(2, "private failure detail", str(path))
                if operation.endswith("_io"):
                    raise OSError(5, "private failure detail", str(path))
                raise PermissionError(13, "private failure detail", str(path))
            return original_stat(candidate, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(Path, "stat", failing_stat)
    else:
        original_read = Path.read_text

        def failing_read(candidate, *args, **kwargs):
            if candidate == path:
                if operation == "decode":
                    raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid byte")
                raise PermissionError(13, "private failure detail", str(path))
            return original_read(candidate, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", failing_read)


@pytest.mark.parametrize("operation", ["read", "stat", "stat_missing", "stat_io", "lstat", "lstat_missing", "lstat_io", "decode"])
@pytest.mark.parametrize("readable_count", [0, 1])
def test_vault_browser_returns_partial_state_when_one_note_is_unreadable(
    tmp_path: Path, monkeypatch, operation: str, readable_count: int
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    bad = tmp_path / "System" / "browser" / "unreadable.md"
    _write_note(bad, title="Private failed note", body="UNREADABLE_BODY_SENTINEL\n")
    for index in range(readable_count):
        _write_note(tmp_path / "notes" / f"readable-{index}.md", title="Readable")
    _fail_browser_file(monkeypatch, bad, operation=operation)

    response = TestClient(app).get("/api/companion/vault-browser")

    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "partial"
    assert data["degraded_reason"] == "note_read_failed"
    assert data["unreadable_notes"] == 1
    assert data["total_notes"] == readable_count + 1
    assert data["filtered_notes"] == readable_count
    assert len(data["notes"]) == readable_count
    assert data["read_only"] is True
    assert data["identity_available"] is True
    assert "UNREADABLE_BODY_SENTINEL" not in response.text
    assert "private failure detail" not in response.text
    assert "unreadable.md" not in response.text
    assert str(tmp_path) not in response.text


def test_vault_browser_partial_state_preserves_identity_health_pagination_and_boundaries(
    tmp_path: Path, monkeypatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    contents = {
        "a/uuidless.md": "# UUID-less human note\n",
        "b/non-indexed.md": "---\nuuid: non-indexed-id\nkind: human_note\n---\nBody\n",
        "c/invalid.md": "---\nuuid: [broken\n---\nBody\n",
        "System/browser/readable.md": "# Readable system sibling\n",
        "00 Infrastructure/System/companions/continuity.md": (
            "---\nuuid: continuity-id\nkind: companion_note\n---\nContinuity\n"
        ),
    }
    for relative, content in contents.items():
        note = tmp_path / relative
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(content, encoding="utf-8")
    bad = tmp_path / "System" / "browser" / "unreadable.md"
    _write_note(bad, title="Failed note")
    child = tmp_path / "private-child"
    _write_note(child / "settings" / "vault.md", title="Child vault")
    _write_note(child / "secret.md", title="Private secret")
    (tmp_path / "child-link.md").symlink_to(child / "secret.md")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    _write_note(outside, title="Outside secret")
    (tmp_path / "outside-link.md").symlink_to(outside)
    _write_note(tmp_path / ".hidden" / "secret.md", title="Hidden secret")
    _fail_browser_file(monkeypatch, bad)

    client = TestClient(app)
    rows = []
    cursor = None
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/api/companion/vault-browser", params=params)
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "partial"
        assert data["unreadable_notes"] == 1
        assert data["total_notes"] == 6
        assert data["filtered_notes"] == 5
        assert data["pagination"]["total_filtered_notes"] == 5
        assert data["identity_available"] is True
        assert data["vault_identity"]["channel"] == "dev"
        assert data["read_only"] is True
        assert data["nested_vault_roots"][0]["note_path"] == "private-child"
        assert "Private secret" not in response.text
        assert "Outside secret" not in response.text
        rows.extend(data["notes"])
        cursor = data["pagination"]["next_cursor"]
        if not data["pagination"]["has_next"]:
            break
    assert [row["note_path"] for row in rows] == sorted(contents)
    by_path = {row["note_path"]: row for row in rows}
    assert by_path["a/uuidless.md"]["uuid"] is None
    assert by_path["a/uuidless.md"]["frontmatter_valid"] is False
    assert by_path["b/non-indexed.md"]["uuid"] == "non-indexed-id"
    assert by_path["c/invalid.md"]["frontmatter_valid"] is False
    assert "uuid" in by_path["c/invalid.md"]["missing_required_fields"]
    assert by_path["00 Infrastructure/System/companions/continuity.md"]["kind"] == "companion_note"
    filtered = client.get("/api/companion/vault-browser", params={"q": "no-match"}).json()
    assert filtered["state"] == "partial"
    assert filtered["notes"] == []
    assert filtered["filtered_notes"] == 0
    assert filtered["unreadable_notes"] == 1


def test_vault_browser_per_file_failure_does_not_mutate_or_exclude_namespace(
    tmp_path: Path, monkeypatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    bad = tmp_path / "System" / "browser" / "unreadable.md"
    readable = bad.with_name("readable.md")
    _write_note(bad, title="Private failed note", body="UNREADABLE_BODY_SENTINEL\n")
    _write_note(readable, title="Readable sibling")
    before = {path: (path.read_bytes(), path.stat().st_mode) for path in (bad, readable)}
    _fail_browser_file(monkeypatch, bad)
    client = TestClient(app)

    for _ in range(2):
        response = client.get("/api/companion/vault-browser")
        assert response.status_code == 200
        assert [note["note_path"] for note in response.json()["notes"]] == [
            "System/browser/readable.md"
        ]
        assert response.json()["state"] == "partial"
    assert client.post("/api/companion/vault-browser", json={}).status_code == 405
    assert {path: (path.read_bytes(), path.stat().st_mode) for path in (bad, readable)} == before


def test_vault_browser_lists_markdown_notes_for_active_dev_vault(
    tmp_path: Path, monkeypatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
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
    bind_selected_vault(monkeypatch, tmp_path)
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
    bind_selected_vault(monkeypatch, tmp_path)
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
    bind_selected_vault(monkeypatch, tmp_path)
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
    bind_selected_vault(monkeypatch, tmp_path)
    monkeypatch.setenv("VAULT_BROWSE_MAX_NOTES", "2")
    _write_note(tmp_path / "z" / "late.md", title="Late")
    _write_note(tmp_path / "a" / "first.md", title="First")
    _write_note(tmp_path / "m" / "middle.md", title="Middle")
    data = TestClient(app).get("/api/companion/vault-browser").json()
    assert [n["note_path"] for n in data["notes"]] == ["a/first.md", "m/middle.md"]


def test_vault_browser_returns_pagination_metadata(tmp_path: Path, monkeypatch) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
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
        "previous_cursor": None,
        "page_size": 2,
        "returned_notes": 2,
        "total_filtered_notes": 3,
        "has_next": True,
        "has_previous": False,
    }


def test_vault_browser_pagination_composes_with_metadata_filters(
    tmp_path: Path, monkeypatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
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
    assert second_page["pagination"]["has_previous"] is True
    assert second_page["pagination"]["previous_cursor"] is None
    assert all(note["kind"] == "human_note" for note in second_page["notes"])


def test_vault_browser_pagination_exposes_previous_cursor_for_later_pages(
    tmp_path: Path, monkeypatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    for relative in ("a/first.md", "b/second.md", "c/third.md", "d/fourth.md"):
        _write_note(tmp_path / relative, title=Path(relative).stem)

    client = TestClient(app)
    first_page = client.get("/api/companion/vault-browser", params={"limit": 1}).json()
    second_page = client.get(
        "/api/companion/vault-browser",
        params={"limit": 1, "cursor": first_page["pagination"]["next_cursor"]},
    ).json()
    third_page = client.get(
        "/api/companion/vault-browser",
        params={"limit": 1, "cursor": second_page["pagination"]["next_cursor"]},
    ).json()

    assert [note["note_path"] for note in third_page["notes"]] == ["c/third.md"]
    assert third_page["pagination"]["has_previous"] is True
    assert third_page["pagination"]["previous_cursor"] == "a/first.md"


def test_vault_browser_pagination_is_read_only(tmp_path: Path, monkeypatch) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
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


def test_vault_browser_datetime_frontmatter_serializes_stably(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    note_path = tmp_path / "notes" / "timestamped.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "---\n"
        "title: Timestamped\n"
        "uuid: timestamped-uuid\n"
        "created: 2026-01-01T00:00:00Z\n"
        "updated: 2026-01-02T03:04:05+00:00\n"
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    note = next(note for note in resp.json()["notes"] if note["note_path"] == "notes/timestamped.md")
    assert note["created"] == "2026-01-01T00:00:00Z"
    assert note["updated"] == "2026-01-02T03:04:05Z"


def test_vault_browser_accepts_iso_timestamp_variants(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    note_path = tmp_path / "notes" / "timestamp-strings.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "---\n"
        "title: Timestamp Strings\n"
        "uuid: timestamp-strings-uuid\n"
        'created: "2026-01-01T00:00:00Z"\n'
        'updated: "2026-01-02T03:04:05+00:00"\n'
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    note = next(
        note for note in resp.json()["notes"] if note["note_path"] == "notes/timestamp-strings.md"
    )
    assert note["created"] == "2026-01-01T00:00:00Z"
    assert note["updated"] == "2026-01-02T03:04:05Z"


def test_vault_browser_preserves_non_utc_timestamp_offsets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    note_path = tmp_path / "notes" / "offset-timestamp.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "---\n"
        "title: Offset Timestamp\n"
        "uuid: offset-timestamp-uuid\n"
        "created: 2026-01-01T12:00:00-05:00\n"
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    note = next(
        note for note in resp.json()["notes"] if note["note_path"] == "notes/offset-timestamp.md"
    )
    assert note["created"] == "2026-01-01T12:00:00-05:00"


def test_vault_browser_includes_receipts_from_outbox_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    outbox = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))

    note_uuid = "00000000-0000-0000-0000-000000001279"
    note_path = tmp_path / "vault" / "notes" / "receipt.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        f"---\ntitle: Receipt Note\nuuid: {note_uuid}\n---\n\nBody.\n",
        encoding="utf-8",
    )
    bind_selected_vault(monkeypatch, tmp_path / "vault")
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
                    "source_event": "intent-1279",
                    "note_uuid": note_uuid,
                    "note_path": "notes/receipt.md",
                    "authority": {"component": "panel_agent.runtime"},
                    "basis": {"source_event": "intent-1279", "intent_type": "promotion"},
                    "outcome": {"status": "applied"},
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
            # Receipts v2 display fields (#3363) — additive, runtime-declared.
            "display_verb": "Promoted",
            "run_key": "trace-receipt-1279",
            "run_label": "Promotion",
            "target_absolute": str(tmp_path / "vault" / "notes" / "receipt.md"),
        }
    ]


def test_vault_browser_omits_receipts_when_receipt_source_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "missing-outbox.jsonl"))
    _write_note(tmp_path / "vault" / "notes" / "no-source.md", title="No Source")
    bind_selected_vault(monkeypatch, tmp_path / "vault")

    resp = TestClient(app).get("/api/companion/vault-browser")

    assert resp.status_code == 200
    note = resp.json()["notes"][0]
    assert note["note_path"] == "notes/no-source.md"
    assert "receipts" not in note
