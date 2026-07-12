"""Vault-ingest carries the note's vault-canonical episode_ref (ERE-05 round-2 Finding 1, #3180).

Regression for the CRITICAL durability bug the round-2 re-review found: the ERE-05 assignment seam
stamps ``episode_ref`` onto a note's frontmatter (the canonical source) AND projects it into the DB
payload, but ``app/ingest/vault_alpha.py`` -- the OTHER producer of that payload -- rebuilt
``store_payload`` from scratch with NO ``episode_ref`` key and blind-overwrote the whole payload
column on every reingest. So a later body edit / cold rebuild silently reverted the DB payload's
``episode_ref`` to absent (retrieval reads exactly this key -> ``unbound`` again), while the ledger
still said ``active`` -- the exact "ledger bound / bundle unbound" divergence the PR fixes, deferred
to the next content edit. Fix (invariant->producers): ingest now reads ``episode_ref`` from the
note frontmatter into ``store_payload``, so the frontmatter is the durable source and the DB payload
is a correct, reingest-stable projection.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.ingest.vault_alpha import run_vault_alpha_ingest
from app.retrieval.hybrid import get_store
from app.search import get_vector_index
from app.stores import get_object_store, reset_store_backends


def _write_layout(vault_root: Path) -> None:
    layout_path = vault_root / "⚙️ System" / "vault.layout.md"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(
        """---\ninclude_folders:\n  - "."\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )


def _clear_vector_index() -> None:
    vector_index = get_vector_index()
    entries = getattr(vector_index, "_entries", None)
    if isinstance(entries, dict):
        entries.clear()


def _payload_episode_ref(vault_root: Path, note_rel: str) -> object:
    from scripts.yaml_roundtrip import load_frontmatter

    fm, _ = load_frontmatter((vault_root / note_rel).read_text(encoding="utf-8"))
    note_uuid = uuid.UUID(str(fm.get("uuid") or ""))
    record = get_object_store().get(note_uuid)
    assert record is not None, "expected the note to be indexed"
    return (record.get("payload") or {}).get("episode_ref")


def _vector_payload_episode_ref(note_uuid: uuid.UUID) -> object:
    for row in get_vector_index().all_rows():
        if str(row.get("object_id")) == str(note_uuid):
            return (row.get("payload") or {}).get("episode_ref")
    return None


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response")
    reset_store_backends()
    get_store().set_documents([])
    _clear_vector_index()


def test_ingest_projects_frontmatter_episode_ref_and_survives_body_edit_reingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base_env(monkeypatch)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    note_uuid = "44444444-4444-4444-8444-444444444444"
    episode_id = "ep-durable-0001-4333-8444-555555555555"
    note_rel = "Bound.md"
    (vault_root / note_rel).write_text(
        f"---\nuuid: {note_uuid}\ntitle: Bound Note\nepisode_ref:\n  - {episode_id}\n---\n\nOriginal body.\n",
        encoding="utf-8",
    )

    summary = run_vault_alpha_ingest(vault_root, max_notes=10, force=True)
    assert summary.ingested >= 1

    # First ingest projects the frontmatter's episode_ref into BOTH DB payload projections.
    assert _payload_episode_ref(vault_root, note_rel) == [episode_id]
    assert _vector_payload_episode_ref(uuid.UUID(note_uuid)) == [episode_id]

    # A BODY edit (frontmatter, incl. episode_ref, unchanged) -> reingest rebuilds store_payload
    # from scratch and full-overwrites the payload column. BEFORE the fix this dropped episode_ref;
    # now it is reprojected from the canonical frontmatter and SURVIVES.
    (vault_root / note_rel).write_text(
        f"---\nuuid: {note_uuid}\ntitle: Bound Note\nepisode_ref:\n  - {episode_id}\n---\n\nEdited body, more words.\n",
        encoding="utf-8",
    )
    run_vault_alpha_ingest(vault_root, max_notes=10, force=True)

    assert _payload_episode_ref(vault_root, note_rel) == [episode_id], (
        "a body-edit reingest must reproject episode_ref from the canonical frontmatter, "
        "never blind-drop it (round-2 Finding 1 durability bug)"
    )
    assert _vector_payload_episode_ref(uuid.UUID(note_uuid)) == [episode_id]


def test_ingest_defaults_episode_ref_unbound_when_frontmatter_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base_env(monkeypatch)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_layout(vault_root)

    note_uuid = "55555555-5555-4555-8555-555555555555"
    note_rel = "Unbound.md"
    (vault_root / note_rel).write_text(
        f"---\nuuid: {note_uuid}\ntitle: Unbound Note\n---\n\nNo episode.\n",
        encoding="utf-8",
    )

    run_vault_alpha_ingest(vault_root, max_notes=10, force=True)

    # The honest default -- a note with no episode binding projects the 'unbound' sentinel, not a
    # missing key (so retrieval's episode_ref default and the ingest projection agree).
    assert _payload_episode_ref(vault_root, note_rel) == "unbound"
