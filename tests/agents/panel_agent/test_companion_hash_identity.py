"""#3510 regression: companion hash refresh must key on the vault frontmatter uuid.

The panel chain carries the canonical ``store_objects`` id after the FK cutover.
For retained legacy rows that id differs from the vault-native frontmatter uuid
that names the companion file, so the refresh seam must resolve the companion
from the note's own frontmatter instead of the caller-supplied id.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from app.agents.panel.filters import strip_ai_panels
from app.agents.panel.writeback import strip_ai_status_block
from app.agents.panel_agent.runtime import _refresh_companion_hash
from app.services.companion_note import (
    CompanionNote,
    read_companion,
    write_companion,
)
from scripts.yaml_roundtrip import load_frontmatter


def _seed_companion(vault_root: Path, vault_uuid: str) -> None:
    write_companion(
        vault_root,
        CompanionNote(
            uuid=vault_uuid,
            source_ref="Notes/Retained.md",
            title="Retained",
            content_hash="stale-hash",
            ingest_state="tracked",
            last_ingested="2026-07-19T00:00:00Z",
            created_by_instance="test",
        ),
    )


def _note_text(vault_uuid: str) -> str:
    return f"---\nuuid: {vault_uuid}\n---\n\nRetained body after writeback.\n"


def _expected_hash(updated_text: str) -> str:
    _, body = load_frontmatter(updated_text)
    content = strip_ai_status_block(strip_ai_panels(body or updated_text)).strip()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_refresh_uses_frontmatter_uuid_when_canonical_id_differs(tmp_path: Path) -> None:
    vault_uuid = str(uuid4())
    canonical_id = str(uuid4())
    assert vault_uuid != canonical_id
    _seed_companion(tmp_path, vault_uuid)
    note_file = tmp_path / "Notes" / "Retained.md"
    note_file.parent.mkdir(parents=True, exist_ok=True)
    updated_text = _note_text(vault_uuid)
    note_file.write_text(updated_text, encoding="utf-8")

    _refresh_companion_hash(canonical_id, updated_text, tmp_path, note_file)

    refreshed = read_companion(tmp_path, vault_uuid)
    assert refreshed is not None
    assert refreshed.content_hash == _expected_hash(updated_text)
    assert refreshed.content_hash != "stale-hash"


def test_refresh_falls_back_to_caller_id_without_frontmatter_uuid(tmp_path: Path) -> None:
    note_uuid = str(uuid4())
    _seed_companion(tmp_path, note_uuid)
    note_file = tmp_path / "Notes" / "Plain.md"
    note_file.parent.mkdir(parents=True, exist_ok=True)
    updated_text = "Plain body without frontmatter.\n"
    note_file.write_text(updated_text, encoding="utf-8")

    _refresh_companion_hash(note_uuid, updated_text, tmp_path, note_file)

    refreshed = read_companion(tmp_path, note_uuid)
    assert refreshed is not None
    assert refreshed.content_hash != "stale-hash"
