from __future__ import annotations

from pathlib import Path
from typing import Mapping

from app.knowledge.write_ops import write_note_from_absolute
from app.services.note_log import note_log_path
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


def upsert_note_mirror(
    vault_root: Path,
    vault_relative_path: Path | str,
    *,
    note_uuid: str,
    title: str,
    review_state: str,
    maturity: str,
    ingest_fingerprint: Mapping[str, int | str],
) -> Path:
    rel_path = Path(vault_relative_path)
    mirror_path = vault_root / note_log_path(note_uuid, rel_path)
    existing_frontmatter: dict[str, object] = {}
    existing_body = ""

    if mirror_path.exists():
        try:
            existing_frontmatter, existing_body = load_frontmatter(mirror_path.read_text(encoding="utf-8"))
        except Exception:
            existing_frontmatter, existing_body = {}, ""

    frontmatter = dict(existing_frontmatter or {})
    frontmatter.update(
        {
            "uuid": note_uuid,
            "title": title,
            "kind": "note",
            "origin": "vault",
            "source_ref": str(rel_path),
            "review_state": review_state,
            "maturity": maturity,
            "ingest_fingerprint": dict(ingest_fingerprint),
        }
    )
    body = existing_body if existing_body.strip() else f"Mirror for {rel_path}"

    resolved_root = vault_root.expanduser().resolve()
    resolved_mirror = mirror_path.expanduser().resolve()
    write_note_from_absolute(resolved_mirror, dump_frontmatter(frontmatter, body), vault_root=resolved_root)
    return mirror_path


__all__ = ["upsert_note_mirror"]
