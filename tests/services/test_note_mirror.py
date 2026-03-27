from __future__ import annotations

from pathlib import Path

from app.services.note_log import note_log_path
from app.services.note_mirror import upsert_note_mirror
from scripts.yaml_roundtrip import load_frontmatter


def test_upsert_note_mirror_creates_missing_mirror_and_links_source_ref(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    rel_path = Path("Concepts/Example.md")
    note_uuid = "11111111-1111-1111-1111-111111111111"

    mirror_path = upsert_note_mirror(
        vault_root,
        rel_path,
        note_uuid=note_uuid,
        title="Example",
        review_state="provisional",
        maturity="note",
        ingest_fingerprint={"text_sha256": "abc", "mtime_ns": 1},
    )

    assert mirror_path == vault_root / note_log_path(note_uuid, rel_path)
    assert mirror_path.exists()
    frontmatter, body = load_frontmatter(mirror_path.read_text(encoding="utf-8"))
    assert frontmatter.get("uuid") == note_uuid
    assert frontmatter.get("source_ref") == "Concepts/Example.md"
    assert "Mirror for Concepts/Example.md" in body
