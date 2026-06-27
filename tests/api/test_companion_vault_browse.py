"""Read-only folder-browser endpoint contract (#2565, part of #2561).

``GET /api/companion/vault/browse`` is the server-owned folder enumeration the
Choose-a-vault overlay's filesystem mode consumes (Ask 3b). It lists immediate
subdirectories only (folders, never files), declares which folders are vaults
via the runtime's own ``is_vault_root`` marker (``settings/vault.md``), and
confines browsing to a configurable base root — rejecting any path that escapes
it (``..`` traversal, absolute path outside the base, symlink escape) after
realpath resolution.

Shape mirrors ``tests/api/test_companion_no_vault_routing.py``: in-process
``TestClient(app)`` with a tmp ``VAULT_BROWSE_ROOT`` base so listings are
hermetic and never read the real filesystem.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.vault.manager import SETTINGS_DIR_NAME


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _make_vault(root: Path) -> Path:
    """Create a folder that ``is_vault_root`` recognizes (settings/vault.md)."""
    settings = root / SETTINGS_DIR_NAME
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "vault.md").write_text("---\nschema: design-handoff.vault.v1\n---\n", encoding="utf-8")
    return root


@pytest.fixture()
def browse_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "Obsidian"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VAULT_BROWSE_ROOT", str(base))
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    return base


# --- AC: listing returns subdirs + is_vault, folders only -------------------


def test_browse_lists_subdirectories_with_vault_flag(
    client: TestClient, browse_base: Path
) -> None:
    """Listing returns immediate subdirs (folders only), each with is_vault."""
    _make_vault(browse_base / "Niflheim")  # a vault folder
    (browse_base / "Drafts").mkdir()  # a plain folder
    (browse_base / "readme.md").write_text("not listed\n", encoding="utf-8")  # a file
    (browse_base / ".obsidian").mkdir()  # hidden — excluded

    resp = client.get("/api/companion/vault/browse")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["base"] == str(browse_base)
    assert body["path"] == str(browse_base)
    # Base is the floor — no parent above it.
    assert body["parent"] is None

    by_name = {entry["name"]: entry for entry in body["entries"]}
    # Folders only — the file is never listed; the hidden folder is excluded.
    assert "readme.md" not in by_name
    assert ".obsidian" not in by_name
    assert set(by_name) == {"Niflheim", "Drafts"}
    # Server-declared vault detection: the vault folder is flagged, the plain
    # folder is not.
    assert by_name["Niflheim"]["is_vault"] is True
    assert by_name["Drafts"]["is_vault"] is False


def test_browse_into_subfolder_exposes_parent_and_breadcrumb(
    client: TestClient, browse_base: Path
) -> None:
    """Navigating into a subfolder yields a base-confined parent + breadcrumb."""
    sub = browse_base / "Projects" / "2026"
    sub.mkdir(parents=True)

    resp = client.get("/api/companion/vault/browse", params={"path": str(sub)})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["path"] == str(sub)
    assert body["parent"] == str(browse_base / "Projects")
    # Breadcrumb runs from the base (inclusive) down to the target.
    crumb_paths = [seg["path"] for seg in body["breadcrumb"]]
    assert crumb_paths == [
        str(browse_base),
        str(browse_base / "Projects"),
        str(sub),
    ]


def test_browse_caps_entries(
    client: TestClient, browse_base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The number of listed entries is capped and ``truncated`` reports it."""
    monkeypatch.setenv("VAULT_BROWSE_MAX_ENTRIES", "2")
    # Re-resolve the module-level cap for this test.
    import app.api.routes.companion as companion_module

    monkeypatch.setattr(companion_module, "_BROWSE_MAX_ENTRIES", 2)
    for i in range(5):
        (browse_base / f"folder-{i}").mkdir()

    resp = client.get("/api/companion/vault/browse")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["entries"]) == 2
    assert body["truncated"] is True


# --- AC: traversal / escape attempts are rejected ---------------------------


def test_browse_rejects_parent_traversal(
    client: TestClient, browse_base: Path
) -> None:
    """A ``..`` escape above the base is rejected (400), never listed."""
    resp = client.get("/api/companion/vault/browse", params={"path": str(browse_base / "..")})
    assert resp.status_code == 400, resp.text
    assert "outside" in resp.text


def test_browse_rejects_absolute_path_outside_base(
    client: TestClient, browse_base: Path, tmp_path: Path
) -> None:
    """An absolute path outside the base is rejected (400)."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    resp = client.get("/api/companion/vault/browse", params={"path": str(outside)})
    assert resp.status_code == 400, resp.text


def test_browse_rejects_symlink_escape(
    client: TestClient, browse_base: Path, tmp_path: Path
) -> None:
    """A symlink inside the base whose target escapes the base is rejected.

    Containment is checked on the realpath (after symlink resolution), so a
    symlink pointing outside the base fails the descendant check — the endpoint
    never lists outside the base via an indirection.
    """
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "private.md").write_text("secret\n", encoding="utf-8")
    link = browse_base / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks not supported on this platform")

    resp = client.get("/api/companion/vault/browse", params={"path": str(link)})
    assert resp.status_code == 400, resp.text
    assert "private.md" not in resp.text


def test_browse_listing_excludes_symlink_escape_child(
    client: TestClient, browse_base: Path, tmp_path: Path
) -> None:
    """A symlinked child whose real target escapes the base is omitted from the
    PARENT's listing — not just rejected on direct navigation (#2565). is_dir()
    and is_vault_root() follow symlinks, so each child is realpath-checked for
    containment before it is listed or probed; an escaping child is skipped."""
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "private.md").write_text("secret\n", encoding="utf-8")
    (browse_base / "RealChild").mkdir()
    link = browse_base / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks not supported on this platform")

    resp = client.get("/api/companion/vault/browse", params={"path": str(browse_base)})
    assert resp.status_code == 200, resp.text
    names = [entry["name"] for entry in resp.json()["entries"]]
    assert "RealChild" in names
    assert "escape" not in names  # symlink escaping the base is not listed
    assert "private.md" not in resp.text


# --- AC: vault folder detected; plain folder not ----------------------------


def test_browse_target_is_vault_flag(client: TestClient, browse_base: Path) -> None:
    """Browsing INTO a vault folder reports the target itself as a vault."""
    vault = _make_vault(browse_base / "Niflheim")
    (vault / "notes").mkdir()

    resp = client.get("/api/companion/vault/browse", params={"path": str(vault)})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_vault"] is True


def test_browse_plain_folder_is_not_a_vault(
    client: TestClient, browse_base: Path
) -> None:
    """A folder without the settings/vault.md marker is not a vault."""
    plain = browse_base / "Drafts"
    plain.mkdir()

    resp = client.get("/api/companion/vault/browse", params={"path": str(plain)})

    assert resp.status_code == 200, resp.text
    assert resp.json()["is_vault"] is False


def test_browse_404_for_non_directory(client: TestClient, browse_base: Path) -> None:
    """A path inside the base that is a file (not a dir) yields 404, not a list."""
    note = browse_base / "note.md"
    note.write_text("# note\n", encoding="utf-8")

    resp = client.get("/api/companion/vault/browse", params={"path": str(note)})
    assert resp.status_code == 404, resp.text


def test_browse_base_defaults_to_filesystem_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no VAULT_BROWSE_ROOT and no configured vault (fresh install / standard
    Compose posture), the base defaults to the filesystem root so the visual
    picker can navigate to wherever host vaults are mounted instead of
    dead-ending at the process home (#2565 / Codex P1)."""
    from app.api.routes import companion as companion_module

    monkeypatch.delenv("VAULT_BROWSE_ROOT", raising=False)
    monkeypatch.setattr(companion_module, "resolve_optional_vault_root", lambda: None)
    assert companion_module._resolve_browse_base() == Path("/").resolve()


def test_browse_symlink_loop_does_not_500(client: TestClient, browse_base: Path) -> None:
    """A symlink loop must not 500 the endpoint: Path.resolve() raises RuntimeError
    (not OSError) on a loop, so navigating into the loop is a 400 and listing the
    parent skips it — never a 500 (#2565 Codex P2). Matters because the base can
    default to '/' and enumerate arbitrary user filesystem entries."""
    loop = browse_base / "loop"
    try:
        loop.symlink_to(loop, target_is_directory=True)  # self-referential loop
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("symlinks not supported on this platform")

    # Navigating INTO the loop: rejected (400), never a 500.
    into = client.get("/api/companion/vault/browse", params={"path": str(loop)})
    assert into.status_code != 500, into.text
    assert into.status_code == 400, into.text

    # Listing the PARENT that contains the loop: 200, the loop child skipped.
    parent = client.get("/api/companion/vault/browse", params={"path": str(browse_base)})
    assert parent.status_code == 200, parent.text
    assert "loop" not in [entry["name"] for entry in parent.json()["entries"]]
