"""Portable, immutable vault projection for one YouTube source version (YSNV2-06)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.knowledge.write_ops import create_candidate_note_once
from app.knowledge_acquisition.candidate_writeback import Candidate
from app.knowledge_acquisition.extraction_persistence import PersistedTranscript
from app.vault.manager import VaultContext
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError

DEFAULT_YOUTUBE_ATTACHMENT_ROOT = "Sources/YouTube/_attachments"
SOURCE_BUNDLE_WRITE_ACTION = "knowledge_acquisition.youtube_source_bundle"


class SourceBundleError(RuntimeError):
    """The derived portable bundle could not be safely materialized."""


@dataclass(frozen=True)
class SourceBundleResult:
    source_folder: str
    bundle_folder: str
    transcript_path: str
    manifest_path: str
    status: str


def validate_youtube_attachment_root(value: str = DEFAULT_YOUTUBE_ATTACHMENT_ROOT) -> str:
    """Accept only a normalized, portable path relative to the selected vault."""
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SourceBundleError("youtube_attachment_root must be a portable vault-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise SourceBundleError("youtube_attachment_root must stay vault-relative")
    return path.as_posix()


def materialize_youtube_source_bundle(
    candidate: Candidate,
    transcript: PersistedTranscript,
    *,
    vault_context: VaultContext,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
    youtube_attachment_root: str = DEFAULT_YOUTUBE_ATTACHMENT_ROOT,
) -> SourceBundleResult:
    """Create immutable transcript and manifest members beneath a stable source folder."""
    root = validate_youtube_attachment_root(youtube_attachment_root)
    vault_root = _vault_root(vault_context)
    source_key = _source_key(candidate.item_ref)
    version_key = _version_key(candidate.content_identity, transcript.extensions.get("stage_version"))
    source_folder = (PurePosixPath(root) / source_key).as_posix()
    bundle_folder = (PurePosixPath(source_folder) / version_key).as_posix()
    transcript_path = (PurePosixPath(bundle_folder) / "transcript.md").as_posix()
    manifest_path = (PurePosixPath(bundle_folder) / "source.json").as_posix()
    manifest = _manifest(candidate, transcript, source_folder, bundle_folder, transcript_path)
    try:
        transcript_status = create_candidate_note_once(
            transcript_path, _render_transcript(candidate, transcript), vault_root=vault_root,
            action=SOURCE_BUNDLE_WRITE_ACTION, write_guard=write_guard,
        )
        manifest_status = create_candidate_note_once(
            manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n", vault_root=vault_root,
            action=SOURCE_BUNDLE_WRITE_ACTION, write_guard=write_guard,
        )
    except WritesBlockedError:
        return SourceBundleResult(
            source_folder, bundle_folder, transcript_path, manifest_path, "blocked"
        )
    except Exception as exc:  # noqa: BLE001
        raise SourceBundleError(f"source bundle materialization failed: {exc}") from exc
    return SourceBundleResult(source_folder, bundle_folder, transcript_path, manifest_path, "written" if "written" in {transcript_status, manifest_status} else "already_exists")


def _source_key(item_ref: str) -> str:
    if not isinstance(item_ref, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item_ref):
        raise SourceBundleError("YouTube source identity must be a safe stable item_ref")
    return f"yt-{item_ref}"


def _version_key(content_identity: str, stage_version: Any) -> str:
    if not isinstance(content_identity, str) or not content_identity:
        raise SourceBundleError("content_identity is required for immutable bundle versioning")
    payload = re.sub(r"[^A-Za-z0-9]+", "-", content_identity.split(":", 1)[-1]).strip("-")
    if not payload:
        payload = hashlib.sha256(content_identity.encode("utf-8")).hexdigest()
    if not isinstance(stage_version, int) or stage_version < 1:
        raise SourceBundleError("transcript stage_version is required for immutable bundle versioning")
    return f"content-{payload}-v{stage_version}"


def _manifest(candidate: Candidate, transcript: PersistedTranscript, source_folder: str, bundle_folder: str, transcript_path: str) -> dict[str, Any]:
    metadata = dict(transcript.metadata_bundle)
    metadata.update({
        "object_id": f"bundle:{candidate.content_identity}:{transcript.object_id}",
        "object_type": "projection",
        "source_role": "external_source",
        "authority_state": "derived",
        "evidence_role": "reference",
        "created_by": "app:knowledge_acquisition.source_bundle",
        "derived_from": [transcript.object_id, *transcript.derived_from],
        "provenance_event_ids": [f"bundle:{transcript.object_id}"],
        "scope_binding": {"bound": "unbound"},
        "extensions": {
            "artifact_kind": "youtube_source_bundle", "stable_source_folder": source_folder,
            "immutable_bundle_folder": bundle_folder, "content_identity": candidate.content_identity,
            "stage_version": transcript.extensions["stage_version"], "transcript_path": transcript_path,
            "transcript_anchors": list(transcript.anchors), "replay_input": "machine_side_raw_only",
        },
    })
    return metadata


def _render_transcript(candidate: Candidate, transcript: PersistedTranscript) -> str:
    lines = ["# Transcript (derived)", "", "This is a derived/rebuildable reference and is never replay input; replay reads machine-side raw evidence.", "", f"Content identity: `{candidate.content_identity}`", f"Normalized transcript: `{transcript.object_id}`", ""]
    for segment in transcript.extensions.get("segments", []):
        if isinstance(segment, dict):
            lines.append(f"- `{segment.get('anchor')}` {segment.get('text', '')}")
    return "\n".join(lines) + "\n"


def _vault_root(context: VaultContext) -> Path:
    if not context.active_vault_path:
        raise SourceBundleError("vault_context.active_vault_path is required")
    return Path(context.active_vault_path).expanduser().resolve()


__all__ = ["DEFAULT_YOUTUBE_ATTACHMENT_ROOT", "SOURCE_BUNDLE_WRITE_ACTION", "SourceBundleError", "SourceBundleResult", "materialize_youtube_source_bundle", "validate_youtube_attachment_root"]
