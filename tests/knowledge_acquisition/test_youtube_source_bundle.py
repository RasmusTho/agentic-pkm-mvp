"""YSNV2-06 portable, immutable YouTube source-bundle contract tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.knowledge_acquisition.candidate_writeback import assemble_candidate, write_candidate_note
from app.knowledge_acquisition.extraction_persistence import persist_normalized_transcript
from app.knowledge_acquisition.normalize import normalize
from app.knowledge_acquisition.raw_record import persist_raw_record
from app.knowledge_acquisition.source_bundle import (
    DEFAULT_YOUTUBE_ATTACHMENT_ROOT,
    SourceBundleError,
    materialize_youtube_source_bundle,
)
import app.knowledge_acquisition.source_bundle as source_bundle_module
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.invariants._helpers import assert_validates
from tests.knowledge_acquisition.test_replay import RAW_PAYLOAD


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext("selected", "vault-test", "Vault Test", str(root))


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _source_material(tmp_path: Path, *, item_ref: str = "dQw4w9WgXcQ", identity: str | None = None):
    raw = {**RAW_PAYLOAD, "item_ref": item_ref}
    if identity is not None:
        raw["content_identity"] = identity
    persisted = persist_raw_record(
        source_kind="youtube_url", item_ref=item_ref,
        content_identity=str(raw["content_identity"]), payload=raw, source_ref="test:bundle",
    )
    normalized = normalize(dict(persisted.record))
    transcript = persist_normalized_transcript(
        raw_record_id=str(persisted.object_id), raw_record=persisted.record, normalized=normalized,
    )
    candidate = assemble_candidate(
        persisted.record, normalized=normalized, raw_record_id=str(persisted.object_id),
        normalized_artifact_id=transcript.object_id, extraction_results=(),
    )
    return persisted, transcript, candidate


def test_configured_attachment_root_is_source_identity_keyed_and_note_is_non_destructive(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _raw, transcript, candidate = _source_material(tmp_path)
    note = write_candidate_note(candidate, vault_context=vault, write_guard=_guard())
    before = (Path(vault.active_vault_path) / str(note.artifact_path)).read_bytes()
    bundle = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard(), youtube_attachment_root="Sources/YouTube/Attachments")
    assert bundle.source_folder == "Sources/YouTube/Attachments/yt-dQw4w9WgXcQ"
    assert (Path(vault.active_vault_path) / str(note.artifact_path)).read_bytes() == before


def test_bundle_members_are_immutable_and_versioned_by_content_identity(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _raw, transcript, candidate = _source_material(tmp_path)
    first = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard())
    _, newer_transcript, newer = _source_material(tmp_path, identity="sha256:new-content")
    second = materialize_youtube_source_bundle(newer, newer_transcript, vault_context=vault, write_guard=_guard())
    assert first.bundle_folder != second.bundle_folder
    assert Path(vault.active_vault_path, first.transcript_path).read_text(encoding="utf-8")


def test_youtube_attachment_root_is_configurable_and_vault_relative(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    result = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard())
    assert result.source_folder.startswith(f"{DEFAULT_YOUTUBE_ATTACHMENT_ROOT}/")
    for unsafe in ("/tmp/escape", "Sources/../escape"):
        with pytest.raises(SourceBundleError):
            materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard(), youtube_attachment_root=unsafe)


def test_bundle_write_failure_remains_terminal_and_non_partial(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    blocked = materialize_youtube_source_bundle(
        candidate,
        transcript,
        vault_context=vault,
        write_guard=WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"}),
    )

    assert blocked.status == "blocked"
    assert blocked.reason is not None
    assert "Writes blocked" in blocked.reason
    assert list((tmp_path / "vault").rglob("*.md")) == []


def test_bundle_write_blocked_between_members_cleans_up_partial_artifact(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    snapshots = iter(
        [
            {"state": "healthy"},
            {"state": "safe_mode", "reason": "mid-bundle block"},
        ]
    )

    blocked = materialize_youtube_source_bundle(
        candidate,
        transcript,
        vault_context=vault,
        write_guard=WriteGuard(lambda: next(snapshots)),
    )

    assert blocked.status == "blocked"
    assert list((tmp_path / "vault").rglob("*.md")) == []


def test_blocked_rollback_fsyncs_bundle_directory_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    opened: list[Path] = []
    unlinked: list[tuple[str, int | None]] = []
    synced: list[int] = []
    original_open = source_bundle_module.os.open
    original_unlink = source_bundle_module.os.unlink
    original_fsync = source_bundle_module.os.fsync

    def record_open(
        path: str | bytes | os.PathLike[str], flags: int, *args: object, **kwargs: object
    ) -> int:
        opened.append(Path(path))
        return original_open(path, flags, *args, **kwargs)

    def record_unlink(path: str | bytes | os.PathLike[str], *, dir_fd: int | None = None) -> None:
        unlinked.append((os.fspath(path), dir_fd))
        original_unlink(path, dir_fd=dir_fd)

    def record_fsync(descriptor: int) -> None:
        synced.append(descriptor)
        original_fsync(descriptor)

    monkeypatch.setattr(source_bundle_module.os, "open", record_open)
    monkeypatch.setattr(source_bundle_module.os, "unlink", record_unlink)
    monkeypatch.setattr(source_bundle_module.os, "fsync", record_fsync)
    snapshots = iter(
        [
            {"state": "healthy"},
            {"state": "safe_mode", "reason": "mid-bundle block"},
        ]
    )

    blocked = materialize_youtube_source_bundle(
        candidate,
        transcript,
        vault_context=vault,
        write_guard=WriteGuard(lambda: next(snapshots)),
    )

    assert blocked.status == "blocked"
    assert opened.count(Path(vault.active_vault_path, blocked.bundle_folder)) == 1
    assert unlinked and unlinked[0][0] == "transcript.md"
    assert unlinked[0][1] in synced
    assert not Path(vault.active_vault_path, blocked.transcript_path).exists()


def test_blocked_manifest_publication_removes_preexisting_orphan_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    complete = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard())
    Path(vault.active_vault_path, complete.manifest_path).unlink()
    snapshots = iter([
        {"state": "healthy"},
        {"state": "safe_mode", "reason": "manifest publication blocked"},
    ])
    blocked = materialize_youtube_source_bundle(
        candidate,
        transcript,
        vault_context=vault,
        write_guard=WriteGuard(lambda: next(snapshots)),
    )

    assert blocked.status == "blocked"
    assert not Path(vault.active_vault_path, blocked.transcript_path).exists()
    assert not Path(vault.active_vault_path, blocked.manifest_path).exists()


def test_blocked_manifest_publication_preserves_complete_preexisting_bundle(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    complete = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard())
    transcript_path = Path(vault.active_vault_path, complete.transcript_path)
    manifest_path = Path(vault.active_vault_path, complete.manifest_path)
    before = (transcript_path.read_bytes(), manifest_path.read_bytes())
    snapshots = iter([
        {"state": "healthy"},
        {"state": "safe_mode", "reason": "manifest publication blocked"},
    ])

    blocked = materialize_youtube_source_bundle(
        candidate,
        transcript,
        vault_context=vault,
        write_guard=WriteGuard(lambda: next(snapshots)),
    )

    assert blocked.status == "blocked"
    assert (transcript_path.read_bytes(), manifest_path.read_bytes()) == before


def test_transcript_projection_is_anchored_derived_and_never_replay_input(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    result = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard())
    body = Path(vault.active_vault_path, result.transcript_path).read_text(encoding="utf-8")
    assert "derived/rebuildable reference" in body
    assert "never replay input" in body
    assert "t000000000-t000002000-s0000" in body


def test_note_links_derived_transcript_from_synthesis_and_lineage(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    bundle = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard())
    linked = candidate.__class__(**{**candidate.__dict__, "derived_transcript_link": bundle.transcript_path})
    note = write_candidate_note(linked, vault_context=vault, write_guard=_guard())
    assert f"[[{bundle.transcript_path}]]" in Path(vault.active_vault_path, str(note.artifact_path)).read_text(encoding="utf-8")


def test_bundle_manifest_validates_resolved_metadata_bundle(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    bundle = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard())
    manifest = json.loads(Path(vault.active_vault_path, bundle.manifest_path).read_text(encoding="utf-8"))
    assert isinstance(manifest["scope_binding"], dict)
    assert manifest["object_type"] == "projection"
    assert_validates(manifest, "metadata-bundle.schema.json")


def test_existing_candidate_bundle_upgrade_uses_versioned_companion_without_note_mutation(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    _, transcript, candidate = _source_material(tmp_path)
    original = write_candidate_note(candidate, vault_context=vault, write_guard=_guard())
    original_path = Path(vault.active_vault_path, str(original.artifact_path))
    before = original_path.read_bytes()
    bundle = materialize_youtube_source_bundle(candidate, transcript, vault_context=vault, write_guard=_guard())
    linked = candidate.__class__(**{**candidate.__dict__, "derived_transcript_link": bundle.transcript_path, "extraction_artifact_ids": ("extract-1",)})
    proposal = write_candidate_note(linked, vault_context=vault, write_guard=_guard(), proposal_on_existing=True)
    assert proposal.status == "proposal_written"
    assert original_path.read_bytes() == before
    assert f"[[{bundle.transcript_path}]]" in Path(vault.active_vault_path, str(proposal.artifact_path)).read_text(encoding="utf-8")
