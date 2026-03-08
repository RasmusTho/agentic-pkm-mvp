from __future__ import annotations

from pathlib import Path

from app.ingest.vault_alpha import _write_mirror
from app.services.note_log import note_log_path
from scripts.yaml_roundtrip import load_frontmatter


def test_write_mirror_uses_knowledge_port(tmp_path: Path, monkeypatch) -> None:
    vault_root = tmp_path / "vault"
    rel_path = Path("Concepts/Example.md")
    note_uuid = "11111111-1111-1111-1111-111111111111"
    writes: list[str] = []

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            writes.append(locator.path)
            target = (vault_root / locator.path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return None

    monkeypatch.setattr("app.ingest.vault_alpha.resolve_knowledge_port", lambda **kwargs: FakePort())

    mirror_path = _write_mirror(
        vault_root,
        rel_path,
        note_uuid=note_uuid,
        title="Example",
        review_state="provisional",
        maturity="note",
        ingest_fingerprint={"text_sha256": "abc", "mtime_ns": 1},
    )

    expected_path = note_log_path(note_uuid, rel_path).as_posix()
    assert expected_path in writes
    frontmatter, _ = load_frontmatter(mirror_path.read_text(encoding="utf-8"))
    assert frontmatter.get("uuid") == note_uuid
