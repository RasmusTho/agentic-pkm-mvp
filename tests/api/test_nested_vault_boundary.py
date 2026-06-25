"""Nested-vault boundary detection (#2313).

A vault may contain privately-initiated sub-vaults as subfolders — a parent
vault whose subtree includes child folders that are themselves initialized
vaults (their own ``settings/vault.md`` marker, possibly private). The parent's
read surfaces (browser, link index, note listing, relation/Find surfaces, the
recents anchor) must STOP at any nested vault root and act as if the child
subtree does not exist. The child's contents must NEVER surface through the
parent — this is a confidentiality boundary and the primary correctness
invariant.

Boundary rule: a folder is a vault root iff ``(<folder>/settings/vault.md)``
exists (the ``validate_vault`` marker; ``is_vault_root``). A note's owning vault
is the NEAREST ENCLOSING vault root, not the selected root if a deeper marker
exists. Nested roots are surfaced as selectable boundaries (drill-in), never
merged into the parent's listing.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes.companion import (
    _collect_relation_notes,
    _collect_vault_note_paths,
    _iter_nested_vault_roots,
    _orientation_recents_anchor,
    _owning_vault_root,
    _select_vault_notes,
)
from app.vault.manager import is_vault_root, nearest_enclosing_vault_root
from tests.api._vault_test_helpers import bind_selected_vault


def _write_note(path: Path, *, title: str, body: str = "Body.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {title}\n---\n\n{body}", encoding="utf-8")


def _make_vault_root(folder: Path) -> None:
    """Write the cheap vault-root marker (``settings/vault.md``) for ``folder``.

    Mirrors the single marker ``validate_vault``/``is_vault_root`` keys on,
    without running full initialization — enough to mark a nested vault root.
    """
    settings = folder / "settings"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "vault.md").write_text(
        "---\nschema: design-handoff.vault.v1\nvaultId: vault_child\n---\n\nChild vault.\n",
        encoding="utf-8",
    )


def _build_parent_with_nested_child(parent: Path) -> Path:
    """Construct a parent vault with notes AND a nested child vault root.

    Returns the child vault root path. The child holds private notes that must
    never surface through the parent's read surfaces.
    """
    # Parent-owned notes (must surface through the parent).
    _write_note(parent / "notes" / "Parent Note.md", title="Parent Note")
    _write_note(parent / "projects" / "Roadmap.md", title="Roadmap")
    # Nested child vault root with its own marker and private notes.
    child = parent / "projects" / "private-child"
    _make_vault_root(child)
    _write_note(child / "Secret Plan.md", title="Secret Plan")
    _write_note(child / "deep" / "Deeper Secret.md", title="Deeper Secret")
    return child


# --- is_vault_root / marker -------------------------------------------------


def test_is_vault_root_detects_marker(tmp_path: Path) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    assert is_vault_root(bare) is False
    _make_vault_root(bare)
    assert is_vault_root(bare) is True


# --- AC1: parent enumeration excludes child vault notes ---------------------


def test_parent_enumeration_excludes_child_vault_notes(
    tmp_path: Path, monkeypatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    child = _build_parent_with_nested_child(tmp_path)

    client = TestClient(app)

    # Vault browser: parent notes present, child notes absent.
    browser = client.get("/api/companion/vault-browser", params={"limit": 1000}).json()
    browser_paths = {note["note_path"] for note in browser["notes"]}
    assert "notes/Parent Note.md" in browser_paths
    assert "projects/Roadmap.md" in browser_paths
    assert not any("private-child" in p for p in browser_paths), browser_paths

    # Link index: same boundary.
    link_index = client.get("/api/companion/vault-link-index").json()
    link_paths = set(link_index["note_paths"])
    assert "notes/Parent Note.md" in link_paths
    assert not any("private-child" in p for p in link_paths), link_paths

    # /vault/notes listing: same boundary.
    notes_list = client.get("/api/companion/vault/notes").json()
    list_paths = {note["path"] for note in notes_list["notes"]}
    assert "notes/Parent Note.md" in list_paths
    assert not any("private-child" in p for p in list_paths), list_paths

    # Direct helper coverage (independent of route plumbing).
    selected, total, _filtered, _has_next, _prev = _select_vault_notes(
        tmp_path, query="", limit=1000
    )
    helper_paths = {note.note_path for note in selected}
    assert not any("private-child" in p for p in helper_paths), helper_paths
    # total_notes must also exclude the child's notes (no leak in counts).
    assert total == 2

    collected, _truncated = _collect_vault_note_paths(tmp_path, limit=5000)
    assert not any("private-child" in p for p in collected), collected

    relation_notes = _collect_relation_notes(tmp_path)
    relation_paths = {note["note_path"] for note in relation_notes}
    assert not any("private-child" in p for p in relation_paths), relation_paths

    # Recents anchor must never point at a child-vault note.
    anchor = _orientation_recents_anchor(tmp_path)
    if anchor is not None:
        assert "private-child" not in anchor.note_path

    # Sanity: the child genuinely contains notes (so the exclusion is real).
    assert (child / "Secret Plan.md").exists()


def test_private_child_vault_notes_never_leak_through_any_read_surface(
    tmp_path: Path, monkeypatch
) -> None:
    """Primary confidentiality invariant (#2313).

    No parent read surface may return a path under the private child vault, even
    by substring. This is the dedicated leak test.
    """
    bind_selected_vault(monkeypatch, tmp_path)
    _build_parent_with_nested_child(tmp_path)

    client = TestClient(app)
    surfaces = {
        "vault-browser": lambda: [
            n["note_path"]
            for n in client.get(
                "/api/companion/vault-browser", params={"limit": 1000}
            ).json()["notes"]
        ],
        "vault-link-index": lambda: client.get(
            "/api/companion/vault-link-index"
        ).json()["note_paths"],
        "vault-notes": lambda: [
            n["path"] for n in client.get("/api/companion/vault/notes").json()["notes"]
        ],
    }
    for name, getter in surfaces.items():
        paths = getter()
        leaked = [p for p in paths if "Secret" in p or "private-child" in p]
        assert leaked == [], f"{name} leaked child-vault content: {leaked}"


def test_direct_workspace_read_of_child_vault_note_is_not_found(
    tmp_path: Path, monkeypatch
) -> None:
    """Direct read-by-path must not bypass the boundary (#2313).

    Enumeration pruning hides child-vault notes from listings, but the
    confidentiality invariant also has to hold on a direct
    ``GET /api/companion/workspace?note_path=...`` where the caller already
    knows/guesses a child-vault-relative path. The parent-selected workspace
    read (and the read-then-write edit path that shares ``_find_workspace_note``)
    must resolve a child-vault note as not-found.
    """
    bind_selected_vault(monkeypatch, tmp_path)
    _build_parent_with_nested_child(tmp_path)
    client = TestClient(app)

    # Parent-owned note is readable.
    ok = client.get(
        "/api/companion/workspace", params={"note_path": "notes/Parent Note.md"}
    )
    assert ok.status_code == 200, ok.text

    # Direct read of a CHILD-vault note must be 404 (boundary), never the body.
    for child_path in (
        "projects/private-child/Secret Plan.md",
        "projects/private-child/deep/Deeper Secret.md",
    ):
        resp = client.get("/api/companion/workspace", params={"note_path": child_path})
        assert resp.status_code == 404, f"{child_path}: {resp.status_code} {resp.text}"
        assert resp.json()["detail"]["error"] == "note_not_found"


def test_symlink_into_child_vault_does_not_leak_through_enumeration(
    tmp_path: Path, monkeypatch
) -> None:
    """A ``.md`` symlink in the parent pointing into a child vault must not leak.

    ``os.walk`` prunes child-vault *directories*, but a file symlink can point
    past the boundary and ``read_text()`` would follow it. Enumeration gates
    symlinks on real-path ownership so the child note never surfaces through the
    parent's listings, and the direct ``/workspace`` read rejects it via realpath.
    """
    bind_selected_vault(monkeypatch, tmp_path)
    child = _build_parent_with_nested_child(tmp_path)
    # Symlink in the parent's own (non-pruned) area pointing into the child vault.
    link = tmp_path / "notes" / "link-to-secret.md"
    link.symlink_to(child / "Secret Plan.md")

    # Direct helper: the symlink is not yielded.
    collected, _ = _collect_vault_note_paths(tmp_path, limit=5000)
    assert "notes/link-to-secret.md" not in collected, collected

    client = TestClient(app)
    browser = {
        n["note_path"]
        for n in client.get(
            "/api/companion/vault-browser", params={"limit": 1000}
        ).json()["notes"]
    }
    assert "notes/link-to-secret.md" not in browser
    link_index = set(client.get("/api/companion/vault-link-index").json()["note_paths"])
    assert "notes/link-to-secret.md" not in link_index

    # Direct /workspace read of the symlink resolves to the child target -> 404.
    resp = client.get(
        "/api/companion/workspace", params={"note_path": "notes/link-to-secret.md"}
    )
    assert resp.status_code == 404, resp.text


# --- AC2: owning vault = nearest enclosing vault root -----------------------


def test_owning_vault_is_nearest_enclosing_root(tmp_path: Path) -> None:
    child = _build_parent_with_nested_child(tmp_path)

    # A parent-owned note resolves to the selected (parent) root.
    parent_note = tmp_path / "notes" / "Parent Note.md"
    assert _owning_vault_root(parent_note, selected_root=tmp_path) == tmp_path.resolve()

    # A note under the child resolves to the CHILD root, not the selected root.
    child_note = child / "Secret Plan.md"
    owner = _owning_vault_root(child_note, selected_root=tmp_path)
    assert owner == child.resolve()
    assert owner != tmp_path.resolve()

    # A deeper note under the child still resolves to the nearest (child) root.
    deeper = child / "deep" / "Deeper Secret.md"
    assert _owning_vault_root(deeper, selected_root=tmp_path) == child.resolve()

    # Manager-level helper agrees and is the single source of truth.
    assert (
        nearest_enclosing_vault_root(child_note, search_root=tmp_path)
        == child.resolve()
    )

    # A note outside the selected root has no owning vault under it.
    outside = tmp_path.parent / "outside.md"
    outside.write_text("x", encoding="utf-8")
    assert _owning_vault_root(outside, selected_root=tmp_path) is None


# --- Navigation/UX: nested root surfaces as selectable boundary -------------


def test_browser_surfaces_child_root_as_selectable_boundary_not_merged_notes(
    tmp_path: Path, monkeypatch
) -> None:
    bind_selected_vault(monkeypatch, tmp_path)
    child = _build_parent_with_nested_child(tmp_path)

    client = TestClient(app)
    data = client.get("/api/companion/vault-browser", params={"limit": 1000}).json()

    # The nested root appears as a selectable boundary (drill-in), by folder path.
    nested = data["nested_vault_roots"]
    nested_paths = {root["note_path"] for root in nested}
    assert "projects/private-child" in nested_paths
    assert all(root["kind"] == "nested_vault_root" for root in nested)
    assert any(root["name"] == "private-child" for root in nested)

    # It is NOT merged into the note listing.
    note_paths = {note["note_path"] for note in data["notes"]}
    assert "projects/private-child" not in note_paths
    assert not any(p.startswith("projects/private-child") for p in note_paths)

    # Direct helper: only the topmost nested root per branch is reported.
    roots = list(_iter_nested_vault_roots(tmp_path))
    assert roots == ["projects/private-child"]
    assert child.name == "private-child"


def test_nested_root_inside_pruned_child_is_not_reported_to_parent(
    tmp_path: Path, monkeypatch
) -> None:
    """A vault nested inside an already-pruned child is the child's concern."""
    bind_selected_vault(monkeypatch, tmp_path)
    child = _build_parent_with_nested_child(tmp_path)
    grandchild = child / "nested-deeper"
    _make_vault_root(grandchild)
    _write_note(grandchild / "Grand Secret.md", title="Grand Secret")

    roots = list(_iter_nested_vault_roots(tmp_path))
    # Only the topmost nested root on the branch is reported to the parent.
    assert roots == ["projects/private-child"]
    assert "projects/private-child/nested-deeper" not in roots
