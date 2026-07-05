"""KERNEL-06: watcher companion-uuid recovery must ignore AI-status receipts.

``_note_uuid_from_frontmatter`` recovers a note's companion identity by hashing
the stripped body and looking the hash up against the companion ``content_hash``
recorded by the ingest path. Panel writeback appends a ``> [!info]- AI status``
receipt callout (with a per-run timestamp) *outside* the AI fence, so unless it is
removed via ``strip_ai_status_block`` the recovery hash drifts and no longer
matches the stored ``content_hash`` — silently breaking uuid recovery on every
panel run. This mirrors the ingest-side fix in
tests/ingest/test_vault_alpha_companion_skip.py.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.services.companion_note import CompanionNote, write_companion
from app.watcher.vault_watcher import _note_uuid_from_frontmatter

_AI_STATUS_CALLOUT = (
    "\n"
    "> [!info]- AI status\n"
    "> - Executed: Draft summary (2026-07-04 19:08)\n"
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_uuid_recovery_ignores_ai_status_receipt(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    note_uuid = "ffff6666-aaaa-bbbb-cccc-dddddddddddd"
    rel_path = Path("Notes/recover.md")
    note_path = vault_root / rel_path
    note_path.parent.mkdir(parents=True, exist_ok=True)

    clean_body = "Recoverable body that survives panel receipts."
    # Companion content_hash recorded by ingest is the hash of the *stripped* body.
    write_companion(
        vault_root,
        CompanionNote(
            uuid=note_uuid,
            source_ref=str(rel_path),
            title="Recover",
            content_hash=_sha256(clean_body),
            ingest_state="tracked",
            last_ingested="2025-01-01T00:00:00+00:00",
            created_by_instance="",
        ),
    )

    # Note has no frontmatter uuid → recovery must fall through to content-hash
    # lookup. The on-disk body has gained a timestamped AI-status receipt callout.
    body_with_receipt = f"{clean_body}\n{_AI_STATUS_CALLOUT}"
    recovered = _note_uuid_from_frontmatter(
        {},
        rel_path=rel_path,
        vault_root=vault_root,
        note_path=note_path,
        body=body_with_receipt,
    )

    assert recovered == note_uuid, (
        "content-hash recovery must strip the AI-status receipt before hashing"
    )
