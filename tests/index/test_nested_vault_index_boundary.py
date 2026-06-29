from __future__ import annotations

from pathlib import Path

import app.ingest.vault_alpha as vault_alpha
from app.index.build import build_index, walk_markdown_files
from app.knowledge.adapters import FsVaultAdapter
from app.orientation.leave_point_cursor import find_artifact_by_uuid
from app.relevance.evaluator import DeterministicRelevanceEvaluator

RULES = [
    {"when": {"review_state": "provisional"}, "action": "include", "weight": 1.0},
]


def _write_note(path: Path, *, title: str, body: str, note_uuid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {title}\nuuid: {note_uuid}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _make_vault_root(path: Path) -> None:
    settings = path / "settings"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "vault.md").write_text(
        "---\nschema: design-handoff.vault.v1\nvaultId: child-vault\n---\n",
        encoding="utf-8",
    )


def _build_parent_with_nested_child(vault_root: Path) -> tuple[Path, dict[str, str]]:
    uuids = {
        "parent_note": "parent-note-uuid",
        "roadmap": "roadmap-uuid",
        "child_note": "child-note-uuid",
    }
    _write_note(
        vault_root / "notes" / "Parent Note.md",
        title="Parent Note",
        body="Parent context only.",
        note_uuid=uuids["parent_note"],
    )
    _write_note(
        vault_root / "projects" / "Roadmap.md",
        title="Roadmap",
        body="- [ ] Parent roadmap item",
        note_uuid=uuids["roadmap"],
    )
    child_root = vault_root / "projects" / "private-child"
    _make_vault_root(child_root)
    _write_note(
        child_root / "Secret Plan.md",
        title="Secret Plan",
        body="Highly secret child vault content.",
        note_uuid=uuids["child_note"],
    )
    return child_root, uuids


def test_index_build_excludes_child_vault_notes(
    tmp_path: Path, monkeypatch
) -> None:
    vault_root = tmp_path / "vault"
    child_root, uuids = _build_parent_with_nested_child(vault_root)
    (vault_root / "notes" / "link-to-secret.md").symlink_to(child_root / "Secret Plan.md")

    monkeypatch.setattr(vault_alpha, "get_vault_system_dir_rel", lambda _root: "_system")

    walked = {path.relative_to(vault_root).as_posix() for path in walk_markdown_files(vault_root, [])}
    assert walked == {"notes/Parent Note.md", "projects/Roadmap.md"}

    index_paths = {
        Path(doc["path"]).relative_to(vault_root).as_posix()
        for doc in build_index(vault_root, RULES, ignore_glob=[])
    }
    assert index_paths == walked

    candidates, _included = vault_alpha._select_candidates(
        vault_root,
        include_folders=["."],
        ignore_glob=(),
        include_test_note=False,
        max_notes=50,
    )
    candidate_paths = {path.relative_to(vault_root).as_posix() for path in candidates}
    assert candidate_paths == walked

    nested_candidates, _included = vault_alpha._select_candidates(
        vault_root,
        include_folders=["projects/private-child"],
        ignore_glob=(),
        include_test_note=False,
        max_notes=50,
    )
    assert nested_candidates == []

    evaluator = DeterministicRelevanceEvaluator(vault_root)
    evaluated_paths = {note.rel_path for note in evaluator._read_vault_notes()}
    assert evaluated_paths == walked

    assert find_artifact_by_uuid(vault_root, uuids["child_note"]) is None
    parent_artifact = find_artifact_by_uuid(vault_root, uuids["parent_note"])
    assert parent_artifact is not None
    assert parent_artifact[0] == "notes/Parent Note.md"

    adapter = FsVaultAdapter(vault_root)
    parent_hits = adapter.search_notes("Parent", "roadmap", limit=10)
    assert [hit.locator.path for hit in parent_hits] == ["projects/Roadmap.md"]
    assert adapter.search_notes("Parent", "secret", limit=10) == []
