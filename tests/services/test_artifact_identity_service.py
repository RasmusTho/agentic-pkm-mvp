from __future__ import annotations

from pathlib import Path

import pytest

from app.services.artifact_identity import resolve_note_artifact_identity


def test_resolve_note_artifact_identity_rejects_bodyless_outside_path_before_read(
    monkeypatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    outside = tmp_path / "outside.md"
    vault.mkdir()
    outside.write_text("---\nuuid: outside\n---\n\nBody\n", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError))

    try:
        resolve_note_artifact_identity(
            artifact_path=outside,
            vault_root=vault,
            safe_note_path="../outside.md",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("outside artifact path was accepted")


def test_configured_sources_note_is_not_uuid_healed(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", "Acquired")
    note = vault / "Acquired" / "source.md"
    note.parent.mkdir()
    body = "---\nartifact_class: youtube_source_note\n---\n\nSource\n"
    note.write_text(body, encoding="utf-8")

    identity = resolve_note_artifact_identity(
        artifact_path=note,
        vault_root=vault,
        safe_note_path="Acquired/source.md",
        body=body,
        heal_missing_uuid=True,
    )

    assert identity.artifact_id is None
    assert identity.identity_state == "unresolved_missing_uuid"
    assert note.read_text(encoding="utf-8") == body


@pytest.mark.parametrize(
    ("sources_alias", "note_path"),
    [
        ("SourcesAlias", "Acquired/source.md"),
        ("Cafe\u0301", "Caf\u00e9/source.md"),
    ],
)
def test_sources_alias_note_is_not_uuid_healed(
    tmp_path: Path,
    monkeypatch,
    sources_alias: str,
    note_path: str,
) -> None:
    from app.vault import path_overlap

    vault = tmp_path / "vault"
    vault.mkdir()
    if sources_alias == "SourcesAlias":
        (vault / "Acquired").mkdir()
        (vault / sources_alias).symlink_to("Acquired", target_is_directory=True)
    else:
        (vault / "Caf\u00e9").mkdir()
        # Model a filesystem where Unicode-normalized names alias. Keep this
        # test deterministic on Linux ext4, which is normalization-sensitive.
        monkeypatch.setattr(
            path_overlap,
            "_filesystem_name_semantics",
            lambda _path: (False, True, False),
        )
    note = vault / note_path
    body = "---\nartifact_class: source\n---\n\nSource\n"
    note.write_text(body, encoding="utf-8")
    monkeypatch.setenv("VAULT_SOURCES_DIR_REL", sources_alias)

    identity = resolve_note_artifact_identity(
        artifact_path=note,
        vault_root=vault,
        safe_note_path=note_path,
        body=body,
        heal_missing_uuid=True,
    )

    assert identity.identity_state == "unresolved_missing_uuid"
    assert note.read_text(encoding="utf-8") == body
