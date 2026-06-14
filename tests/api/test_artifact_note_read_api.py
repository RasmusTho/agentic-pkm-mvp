"""Read-only artifact note endpoint acceptance tests (no Postgres required).

All behavioral ACs from issue #1063, run against the API TestClient with
tmp_path vault files.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.api.app import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def vault_note(tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    """Create a minimal vault note in tmp_path and set VAULT_ROOT."""
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = tmp_path / "notes" / "test_artifact.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "# My Test Note\n\nSome body text.\n\n- [ ] action item\n",
        encoding="utf-8",
    )
    return note


# ---------------------------------------------------------------------------
# AC 1: endpoint returns real note payload
# ---------------------------------------------------------------------------


def test_read_artifact_note_returns_body_payload(
    client: TestClient, vault_note: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    # Use a vault-relative path; absolute paths are no longer accepted.
    relative_path = vault_note.relative_to(tmp_path)
    resp = client.get(
        "/api/artifacts/note",
        params={"note_path": str(relative_path), "artifact_id": "note-uuid-test-1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["artifact_id"] == "note-uuid-test-1"
    assert data["note_path"] == str(vault_note.resolve())
    assert data["title"] == "My Test Note"
    assert "Some body text" in data["body"]
    assert data["content_hash"]  # non-empty version marker
    # content_hash must be deterministic
    expected_hash = hashlib.sha1(vault_note.read_bytes()).hexdigest()[:16]
    assert data["content_hash"] == expected_hash


def test_read_artifact_note_strips_markdown_image_sigil_from_title(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = tmp_path / "notes" / "diagram.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# ![Diagram](https://example.com/x.png)\n\nSome body text.\n", encoding="utf-8")

    resp = client.get("/api/artifacts/note", params={"note_path": "notes/diagram.md"})

    assert resp.status_code == 200
    assert resp.json()["title"] == "Diagram"


# ---------------------------------------------------------------------------
# AC 2: missing note returns typed error
# ---------------------------------------------------------------------------


def test_read_artifact_note_missing_returns_typed_error(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    resp = client.get("/api/artifacts/note", params={"note_path": "does_not_exist.md"})
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error"] == "note_not_found"
    assert "note_path" in detail


# ---------------------------------------------------------------------------
# AC 3: path traversal is rejected
# ---------------------------------------------------------------------------


def test_read_artifact_note_rejects_path_traversal(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    traversal = "../etc/passwd"
    resp = client.get("/api/artifacts/note", params={"note_path": traversal})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_path"
    assert detail["reason"] == "path_traversal"


# ---------------------------------------------------------------------------
# AC 4: endpoint does not mutate the note file
# ---------------------------------------------------------------------------


def test_read_artifact_note_does_not_mutate_file(
    client: TestClient, vault_note: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    original = vault_note.read_text(encoding="utf-8")
    relative_path = vault_note.relative_to(tmp_path)
    client.get("/api/artifacts/note", params={"note_path": str(relative_path)})
    assert vault_note.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# AC 3b: absolute paths are rejected
# ---------------------------------------------------------------------------


def test_read_artifact_note_rejects_absolute_path(
    client: TestClient, vault_note: pathlib.Path
) -> None:
    resp = client.get("/api/artifacts/note", params={"note_path": str(vault_note)})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_path"
    assert detail["reason"] == "absolute_path_not_allowed"


# ---------------------------------------------------------------------------
# AC 5: Companion UI does not read vault files directly
# ---------------------------------------------------------------------------


def test_companion_ui_does_not_read_vault_directly() -> None:
    """Architecture guard: no vault-read/write code in companion_ui/ modules."""
    import ast
    import pathlib

    vault_io_calls = {"read_text", "read_bytes", "write_text", "write_bytes", "open"}
    companion_ui_root = pathlib.Path(__file__).parents[2] / "companion-ui"
    if not companion_ui_root.exists():
        pytest.skip("companion-ui directory not present")

    violations: list[str] = []
    for py_file in companion_ui_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in vault_io_calls:
                violations.append(f"{py_file}:{node.col_offset} uses .{node.attr}")

    assert not violations, (
        "companion_ui modules must not access vault files directly:\n"
        + "\n".join(violations)
    )


def test_read_artifact_note_rejects_path_traversal_escape(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    resp = client.get("/api/artifacts/note", params={"note_path": "../outside.md"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_path"
    assert detail["reason"] in {"path_traversal", "outside_vault"}


def test_read_artifact_note_rejects_symlink_escape(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    outside = tmp_path.parent / "outside-target.md"
    outside.write_text("outside", encoding="utf-8")
    link = tmp_path / "notes" / "escape.md"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)

    resp = client.get("/api/artifacts/note", params={"note_path": "notes/escape.md"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["error"] == "invalid_path"
    assert detail["reason"] == "outside_vault"


def test_read_artifact_note_uses_trusted_vault_relative_path(
    client: TestClient, tmp_path: pathlib.Path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    note = tmp_path / "notes" / "trusted.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Trusted\n\nok\n", encoding="utf-8")
    capture: dict[str, str] = {}
    original = pathlib.Path.read_text

    def _capture_read_text(self: pathlib.Path, *args, **kwargs) -> str:  # type: ignore[no-untyped-def]
        capture["path"] = str(self.resolve())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "read_text", _capture_read_text)
    resp = client.get("/api/artifacts/note", params={"note_path": "notes/trusted.md"})
    assert resp.status_code == 200
    assert capture["path"] == str(note.resolve())
