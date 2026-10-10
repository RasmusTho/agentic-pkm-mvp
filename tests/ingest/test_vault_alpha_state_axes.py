from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import app.ingest.vault_alpha as vault_alpha
from app.objects import ObjectStore
from app.ingest.vault_alpha import run_vault_alpha_ingest
from app.stores import get_object_store, reset_memory_store_backend

pytestmark = pytest.mark.not_pg


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        "---\n"
        "system_folder: ⚙️ System\n"
        "inbox_folder: 📥 Inbox\n"
        "desk_folder: 🛠️ Workbench\n"
        "include_folders:\n"
        "  - Notes\n"
        "---\n\n"
        "Layout note.\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("source_backed_rebuild", [False, True], ids=["ordinary", "source-backed"])
@pytest.mark.parametrize(
    ("frontmatter", "expected_review_state"),
    [
        ({"review_state": "unrecognized-source-token"}, "provisional"),
        ({"maturity": "stable"}, "reviewed"),
        ({"review_state": "protected", "maturity": "raw"}, "protected"),
    ],
    ids=["unrecognized-review-token", "maturity-derived-default", "explicit-canonical-state"],
)
def test_alpha_projects_canonical_review_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    source_backed_rebuild: bool,
    frontmatter: dict[str, str],
    expected_review_state: str,
) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_store_backend()
    request.addfinalizer(reset_memory_store_backend)
    monkeypatch.setattr(vault_alpha, "classify_run", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(vault_alpha, "index_ingest_object", lambda **_kwargs: None)
    monkeypatch.setattr(vault_alpha, "append_jsonl", lambda *_args, **_kwargs: None)

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)
    note_uuid = "11111111-1111-4111-8111-111111111111"
    note_path = vault_root / "Notes" / "product.md"
    fields = "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
    source_text = (
        f"---\nuuid: {note_uuid}\n{fields}\n---\n\n"
        "Meaning-bearing Product note.\n"
    )
    note_path.parent.mkdir(parents=True)
    note_path.write_text(source_text, encoding="utf-8")

    before = note_path.read_bytes()
    summary = run_vault_alpha_ingest(
        vault_root,
        max_notes=10,
        force=True,
        source_backed_rebuild=source_backed_rebuild,
    )

    assert summary.ingested == 1
    assert note_path.read_bytes() == before
    projection = get_object_store().get(uuid.UUID(note_uuid))
    assert projection is not None
    payload = projection["payload"]
    assert payload["review_state"] == expected_review_state
    domain_projection = ObjectStore().get_object(note_uuid)
    assert domain_projection is not None
    assert domain_projection.payload["maturity"] == frontmatter.get("maturity", "note")
