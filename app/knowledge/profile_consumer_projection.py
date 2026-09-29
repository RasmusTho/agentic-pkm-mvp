"""Read-only projection of the governed Profile Note for scoped consumers.

The authority stream and the Profile Note remain the source of truth.  This
module rebuilds a small consumer view from those durable sources every time it
is called.  It deliberately does not cache approval, infer a scope from the
vault identity, or expose pending proposal material.

The scope marker is part of the receipt-digest-bound approved body::

    <!--mimer:profile-scope scope_id=scope:work/project-alpha-->

Frontmatter is intentionally not consulted for scope.  It is presentation
metadata outside the approved-content digest and therefore cannot authorize a
consumer.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from app.knowledge.profile_authority import ProfileAuthorityContractError
from app.knowledge.profile_authority_store import ProfileAuthorityStore
from app.knowledge.profile_note import load_profile_note_frontmatter, profile_note_parts


ProjectionStatus = Literal["available", "no-profile"]
_SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_SCOPE_MARKER_PATTERN = re.compile(
    r"^<!--mimer:profile-scope scope_id=(?P<scope>[A-Za-z0-9][A-Za-z0-9._:/-]*)-->$"
)
_SCOPE_MAX_LENGTH = 128


@dataclass(frozen=True)
class ProfileConsumerProjection:
    """One rebuildable, read-only consumer result."""

    status: ProjectionStatus
    reason: str
    profile_content: str | None = None
    scope_id: str | None = None
    vault_id: str | None = None
    profile_note_id: str | None = None
    version_id: str | None = None
    generation: int | None = None
    receipt_id: str | None = None
    content_digest: str | None = None

    @property
    def available(self) -> bool:
        """Whether approved profile content was admitted for the consumer."""

        return self.status == "available"

    @classmethod
    def no_profile(cls, reason: str) -> "ProfileConsumerProjection":
        return cls(status="no-profile", reason=reason)


def validate_consumer_scope(scope_id: object) -> str | None:
    """Return one explicit scope binding; never coerce or infer one."""

    if (
        not isinstance(scope_id, str)
        or len(scope_id) > _SCOPE_MAX_LENGTH
        or _SCOPE_PATTERN.fullmatch(scope_id) is None
    ):
        return None
    return scope_id


def rebuild_profile_projection(
    vault_root: Path | str,
    *,
    active_scope_id: str | None,
) -> ProfileConsumerProjection:
    """Rebuild a consumer projection from the authority stream and live note.

    Every refusal is represented as ``status == "no-profile"``.  In
    particular, this function never returns the latest body when the terminal
    receipt is missing, the body is stale, or the explicit scope binding does
    not match the active consumer scope.
    """

    scope_id = validate_consumer_scope(active_scope_id)
    if scope_id is None:
        return ProfileConsumerProjection.no_profile("missing_or_invalid_active_scope")

    try:
        root = Path(vault_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            return ProfileConsumerProjection.no_profile("vault_root_unavailable")
        state = ProfileAuthorityStore(root, profile_note_id=None).load_state()
        if state is None:
            return ProfileConsumerProjection.no_profile("authority_unavailable")
        version = state.receipt_bound_version
        if version is None:
            return ProfileConsumerProjection.no_profile("profile_not_receipt_bound")

        note_path = _resolve_note_path(root, state.identity.note_path)
        note_text = note_path.read_text(encoding="utf-8")
        frontmatter, _ = load_profile_note_frontmatter(note_text)
        if not isinstance(frontmatter, dict):
            return ProfileConsumerProjection.no_profile("profile_frontmatter_invalid")
        note_uuid = frontmatter.get("uuid")
        if not isinstance(note_uuid, str) or note_uuid != state.identity.profile_note_id:
            return ProfileConsumerProjection.no_profile("profile_note_identity_mismatch")

        approved_content = _approved_content(note_text)
        if approved_content is None:
            return ProfileConsumerProjection.no_profile("profile_content_malformed")
        if _digest(approved_content) != version.content_digest:
            return ProfileConsumerProjection.no_profile("profile_content_stale")
        if _digest(approved_content) != state.current_content_digest:
            return ProfileConsumerProjection.no_profile("profile_snapshot_mismatch")

        bound_scope, consumer_content = _extract_scope_and_content(approved_content)
        if bound_scope is None:
            return ProfileConsumerProjection.no_profile("profile_scope_missing_or_malformed")
        if bound_scope != scope_id:
            return ProfileConsumerProjection.no_profile("profile_scope_mismatch")
        if not consumer_content:
            return ProfileConsumerProjection.no_profile("profile_content_empty")

        return ProfileConsumerProjection(
            status="available",
            reason="approved_same_scope_profile",
            profile_content=consumer_content,
            scope_id=bound_scope,
            vault_id=state.identity.vault_id,
            profile_note_id=state.identity.profile_note_id,
            version_id=version.version_id,
            generation=version.generation,
            receipt_id=version.receipt_id,
            content_digest=version.content_digest,
        )
    except (OSError, RuntimeError, UnicodeError, ValueError, ProfileAuthorityContractError):
        return ProfileConsumerProjection.no_profile("profile_authority_unavailable")


def _resolve_note_path(root: Path, relative_path: str) -> Path:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not relative_path or "\\" in relative_path or ".." in path.parts:
        raise ProfileAuthorityContractError("Profile Note path is not vault-relative")
    lexical = root.joinpath(*path.parts)
    resolved = lexical.resolve(strict=True)
    if resolved != lexical.absolute() or not resolved.is_relative_to(root) or not resolved.is_file():
        raise ProfileAuthorityContractError("Profile Note path is outside its vault")
    return lexical


def _approved_content(note_text: str) -> str | None:
    """Use the producer's shared header and managed-panel digest boundary."""

    try:
        _, _, approved = profile_note_parts(note_text)
    except ProfileAuthorityContractError:
        return None
    return approved


def _extract_scope_and_content(approved_content: str) -> tuple[str | None, str]:
    lines = approved_content.splitlines()
    markers = [_SCOPE_MARKER_PATTERN.fullmatch(line.strip()) for line in lines]
    matches = [match for match in markers if match is not None]
    if len(matches) != 1:
        return None, ""
    scope_id = validate_consumer_scope(matches[0].group("scope"))
    if scope_id is None:
        return None, ""
    content = "\n".join(line for line, match in zip(lines, markers) if match is None).strip()
    return scope_id, content


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "ProfileConsumerProjection",
    "ProjectionStatus",
    "rebuild_profile_projection",
    "validate_consumer_scope",
]
