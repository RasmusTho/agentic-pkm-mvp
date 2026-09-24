"""Runtime artifact identity resolution for active note workspace surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.config.paths import VaultRootMisconfiguredError
from app.knowledge.errors import KnowledgeWriteConflict
from app.knowledge.multiwriter import NoteClass, WriteOperation, classify_note
from app.rebuildability.product_total_loss import parse_bounded_frontmatter
from app.services.companion_note import companion_path
from app.services.note_uuid import ensure_note_uuid
from app.write_guard import WritesBlockedError
from scripts.yaml_roundtrip import load_frontmatter


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_id: str | None
    artifact_kind: str
    note_path: str
    identity_source: str
    identity_state: str
    companion_of: str | None = None
    owns_identity: bool = True


def resolve_note_artifact_identity(
    *,
    artifact_path: Path,
    vault_root: Path,
    safe_note_path: str,
    body: str | None = None,
    heal_missing_uuid: bool = True,
) -> ArtifactIdentity:
    """Resolve active workspace identity without path/hash fallbacks.

    A create-once note without a uuid is never rewritten here; it resolves to the
    retained-source recovery identity shared with ingest, not a workspace-local
    path or content hash.
    """
    companion_identity = _companion_identity(vault_root=vault_root, safe_note_path=safe_note_path)
    if companion_identity is not None:
        return companion_identity

    resolved_root = Path(vault_root).expanduser().resolve()
    contained_artifact_path = _contained_artifact_path(resolved_root, safe_note_path)
    frontmatter = _frontmatter(body if body is not None else contained_artifact_path.read_text(encoding="utf-8"))
    frontmatter_uuid = str(frontmatter.get("uuid") or "").strip()
    if frontmatter_uuid:
        return ArtifactIdentity(
            artifact_id=frontmatter_uuid,
            artifact_kind="human_note",
            note_path=safe_note_path,
            identity_source="frontmatter.uuid",
            identity_state="resolved",
        )

    legacy_id = str(frontmatter.get("id") or "").strip()
    if legacy_id:
        return ArtifactIdentity(
            artifact_id=legacy_id,
            artifact_kind="human_note",
            note_path=safe_note_path,
            identity_source="frontmatter.id",
            identity_state="legacy_resolved",
        )

    if _is_create_once(resolved_root, contained_artifact_path):
        # A create-once note (ADR-0055) is never rewritten, least of all by a read:
        # the backfill write would be refused. Use the same read-only, stable
        # recovery identity ingest derives for this retained note instead (#5660).
        return _recovery_identity(
            artifact_path=contained_artifact_path,
            vault_root=resolved_root,
            safe_note_path=safe_note_path,
            body=body,
        )

    if heal_missing_uuid:
        try:
            healed_uuid = ensure_note_uuid(contained_artifact_path, vault_root=resolved_root)
        except (
            OSError,
            ValueError,
            VaultRootMisconfiguredError,
            WritesBlockedError,
            KnowledgeWriteConflict,
        ):
            healed_uuid = ""
        if healed_uuid:
            return ArtifactIdentity(
                artifact_id=healed_uuid,
                artifact_kind="human_note",
                note_path=safe_note_path,
                identity_source="uuid_healing",
                identity_state="healed",
            )

    return ArtifactIdentity(
        artifact_id=None,
        artifact_kind="human_note",
        note_path=safe_note_path,
        identity_source="missing",
        identity_state="unresolved_missing_uuid",
    )


def _is_create_once(vault_root: Path, artifact_path: Path) -> bool:
    # Mirrors the filesystem knowledge adapter's write classification, which is
    # what refuses the expected-version uuid backfill for non-rewritten classes.
    relative = artifact_path.relative_to(vault_root).as_posix()
    return classify_note(relative, WriteOperation.WRITE) is NoteClass.CREATE_ONCE


def _recovery_identity(
    *,
    artifact_path: Path,
    vault_root: Path,
    safe_note_path: str,
    body: str | None,
) -> ArtifactIdentity:
    from app.ingest.vault_alpha import resolve_vault_note_identity

    text = body if body is not None else artifact_path.read_text(encoding="utf-8")
    frontmatter, note_body, _ = parse_bounded_frontmatter(text)
    identity = resolve_vault_note_identity(
        artifact_path,
        vault_root=vault_root,
        frontmatter=frontmatter,
        body=note_body,
    )
    return ArtifactIdentity(
        artifact_id=identity.note_uuid,
        artifact_kind="human_note",
        note_path=safe_note_path,
        identity_source="recovery_candidate",
        identity_state="recovered",
    )


def _frontmatter(markdown: str) -> dict:
    frontmatter, _ = load_frontmatter(markdown)
    return frontmatter if isinstance(frontmatter, dict) else {}


def _contained_artifact_path(vault_root: Path, safe_note_path: str) -> Path:
    candidate = PurePosixPath(safe_note_path)
    if (
        not safe_note_path
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() in {"", "."}
    ):
        raise ValueError(f"artifact path is outside vault root: {safe_note_path}")
    resolved_root = Path(vault_root).expanduser().resolve()
    resolved_path = (resolved_root / Path(*candidate.parts)).resolve()
    resolved_path.relative_to(resolved_root)
    return resolved_path


def _companion_identity(*, vault_root: Path, safe_note_path: str) -> ArtifactIdentity | None:
    candidate = PurePosixPath(safe_note_path)
    parts = candidate.parts
    if len(parts) < 3 or parts[-1].endswith(".md") is False:
        return None

    parent = PurePosixPath(*parts[:-1]).as_posix()
    companion_dirs = {
        companion_path("__placeholder__", vault_root).parent.as_posix(),
        PurePosixPath("_system/companions").as_posix(),
    }
    if parent not in companion_dirs:
        return None

    note_uuid = Path(parts[-1]).stem.strip()
    if not note_uuid:
        return ArtifactIdentity(
            artifact_id=None,
            artifact_kind="companion_note",
            note_path=safe_note_path,
            identity_source="companion_path",
            identity_state="unresolved_missing_companion_uuid",
            owns_identity=False,
        )
    return ArtifactIdentity(
        artifact_id=f"companion:{note_uuid}",
        artifact_kind="companion_note",
        note_path=safe_note_path,
        identity_source="companion_path",
        identity_state="companion_of_resolved",
        companion_of=note_uuid,
        owns_identity=False,
    )


__all__ = ["ArtifactIdentity", "resolve_note_artifact_identity"]
