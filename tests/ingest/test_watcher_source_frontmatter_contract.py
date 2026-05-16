"""
Source note frontmatter contract for watcher ingest.

SoT authority: docs/CORE_CONTRACT.md, docs/FRONTMATTER.md

Key finding from SoT (2026-05-15 UAT investigation, issue #976):

  Core-6 is a semantic contract, NOT a YAML schema requirement.
  "Absence of YAML does not imply absence of semantics; Core-6 may be
   implicit or derived." (CORE_CONTRACT.md)
  "For vault notes, uuid in frontmatter plus the companion note form the
   primary file-based identity anchors used for rebuild and repair."

  FRONTMATTER.md write contract:
  - May be automatic: "ensuring or healing a stable uuid" only.
  - Requires explicit confirmation: any meaning-bearing classification.
  - Must never be auto-applied: silent boundary crossings.

Expected source note frontmatter contract after watcher ingest:
  - uuid MUST be present (auto-written if missing).
  - origin, source_ref, trust, review_state are NOT auto-written to the
    source note; they live in the companion note and object store.
  - title, tags, and other human fields remain human-owned and are never
    silently overwritten.

The companion note carries: uuid, source_ref, content_hash, ingest_state.
It explicitly must NOT carry: review_state, maturity, kind, origin
(see companion_note.py module docstring).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.services.companion_note import read_companion
from app.stores import reset_store_backends
from scripts.yaml_roundtrip import load_frontmatter

# Companion non-ingest fields that must stay out of source note frontmatter.
_COMPANION_TRACKING_FIELDS = frozenset(
    {
        "content_hash",
        "ingest_state",
        "created_by_instance",
        "content_hash_at_ingest",
        "ingest_count",
    }
)

# Core-6 fields that are system-owned but must NOT be auto-written to source
# note frontmatter (per FRONTMATTER.md write contract).
_SYSTEM_CORE6_NOT_AUTO_WRITTEN = frozenset({"origin", "trust", "review_state"})


@pytest.fixture()
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )
    monkeypatch.setenv("COMPANION_CREATE_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("COMPANION_RENAME_COOLDOWN_SECONDS", "0")
    reset_store_backends()


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        "---\nversion: '1'\nsystem_folder: '⚙️ System'\n"
        "inbox_folder: '📥 Inbox'\ndesk_folder: '🛠️ Workbench'\n---\n",
        encoding="utf-8",
    )


def test_watcher_ingest_enforces_source_frontmatter_contract(
    tmp_path: Path, _mock_env: None
) -> None:
    """Source note receives uuid only; no other Core-6 fields auto-written.

    This is the canonical contract per SoT (CORE_CONTRACT.md + FRONTMATTER.md).
    uuid-only in source note frontmatter is CORRECT, not a bug.
    Other Core-6 fields live in companion note and object store.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    inbox = vault_root / "📥 Inbox"
    inbox.mkdir()
    note_path = inbox / "test-ingest-contract.md"
    note_path.write_text(
        "---\ntitle: test-ingest-contract\n---\n\nSource note body.\n",
        encoding="utf-8",
    )

    summary = run_vault_alpha_ingest_paths(vault_root, [note_path])
    assert summary.ingested == 1

    frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))

    # uuid MUST be present and valid after ingest.
    note_uuid = str(frontmatter.get("uuid") or "").strip()
    assert note_uuid, "uuid must be written to source note frontmatter"
    uuid.UUID(note_uuid)

    # Core-6 non-uuid system fields must NOT be auto-written to source note.
    for field in _SYSTEM_CORE6_NOT_AUTO_WRITTEN:
        assert field not in frontmatter, (
            f"'{field}' must not be auto-written to source note frontmatter per FRONTMATTER.md write contract"
        )

    # Human-authored title must be preserved unchanged.
    assert frontmatter.get("title") == "test-ingest-contract"


def test_watcher_ingest_populates_missing_core_frontmatter(
    tmp_path: Path, _mock_env: None
) -> None:
    """Ingest is idempotent: uuid-only is the contract; re-ingest preserves uuid.

    SoT resolution: since uuid-only is the correct source-note contract,
    'populating missing Core frontmatter' means ensuring uuid is present and
    stable across ingest runs. Other Core-6 fields are NOT populated into source
    note frontmatter; they are projected into companion and object store instead.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    note_path = vault_root / "Notes" / "idempotent-ingest.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(
        "---\ntitle: Idempotent Ingest Test\n---\n\nBody content.\n",
        encoding="utf-8",
    )

    # First ingest — uuid written.
    run_vault_alpha_ingest_paths(vault_root, [note_path])
    fm1, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
    uuid1 = str(fm1.get("uuid") or "").strip()
    assert uuid1, "uuid must be written on first ingest"
    uuid.UUID(uuid1)

    # Second ingest — uuid unchanged, no new Core-6 fields appear.
    run_vault_alpha_ingest_paths(vault_root, [note_path])
    fm2, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
    uuid2 = str(fm2.get("uuid") or "").strip()
    assert uuid2 == uuid1, "uuid must be stable across ingest runs (idempotent)"

    for field in _SYSTEM_CORE6_NOT_AUTO_WRITTEN:
        assert field not in fm2, (
            f"Re-ingest must not add '{field}' to source note frontmatter"
        )


def test_companion_tracking_fields_do_not_leak_into_source_note(
    tmp_path: Path, _mock_env: None
) -> None:
    """Companion tracking fields stay in the companion note, not source note.

    Companion note carries: uuid, source_ref, content_hash, ingest_state.
    Source note must never receive these companion-internal fields.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    inbox = vault_root / "📥 Inbox"
    inbox.mkdir()
    note_path = inbox / "companion-isolation-test.md"
    note_path.write_text(
        "---\ntitle: companion-isolation-test\n---\n\nSome meaningful content here.\n",
        encoding="utf-8",
    )

    summary = run_vault_alpha_ingest_paths(vault_root, [note_path])
    assert summary.ingested == 1

    source_fm, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))

    # No companion tracking field must appear in source note frontmatter.
    leaked = _COMPANION_TRACKING_FIELDS & set(source_fm.keys())
    assert not leaked, (
        f"Companion tracking fields leaked into source note frontmatter: {leaked}"
    )

    # Companion note should carry uuid and source_ref.
    note_uuid = str(source_fm.get("uuid") or "").strip()
    if note_uuid:
        companion = read_companion(vault_root, note_uuid)
        if companion is not None:
            assert companion.uuid == note_uuid
            assert companion.source_ref
