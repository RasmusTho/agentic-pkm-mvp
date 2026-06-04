from __future__ import annotations

from pathlib import Path

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
