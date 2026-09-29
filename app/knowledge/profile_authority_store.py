"""Vault-local persistence for the governed profile authority record stream."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.knowledge.profile_authority import (
    ProfileAuthorityConflict,
    ProfileAuthorityContractError,
    ProfileAuthorityRecord,
    ProfileAuthorityState,
    ProfileIdentityRecord,
    decode_profile_records,
    encode_profile_records,
    replay_profile_records,
    validate_profile_transition,
)


class ProfileAuthorityStore:
    """Serialize record appends with a locked, atomic JSONL replacement.

    Versioned authority records and their digests remain replayable alongside
    the candidate payload needed to recover a pending review after restart.
    The same payload is rendered in the vault-visible Profile Note panel.
    """

    def __init__(self, vault_root: Path | str, profile_note_id: str | None) -> None:
        root = Path(vault_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ProfileAuthorityContractError("profile vault root is not a directory")
        self.vault_root = root
        self.profile_note_id = profile_note_id
        # GOVPROF-01 models one authoritative Profile Note per vault. Key the
        # stream by the resolved vault so a second note cannot silently acquire
        # a parallel authority history.
        vault_key = hashlib.sha256(root.as_posix().encode("utf-8")).hexdigest()
        self.directory = root / ".mimer" / "profile-authority"
        self.path = self.directory / f"{vault_key}.jsonl"
        self.lock_path = self.directory / f"{vault_key}.lock"

    def load_records(self) -> tuple[ProfileAuthorityRecord, ...]:
        if not self.path.exists() and not self.path.is_symlink():
            return ()
        with self._locked():
            return self._load_records_locked()

    def load_state(self) -> ProfileAuthorityState | None:
        records = self.load_records()
        return replay_profile_records(records) if records else None

    def initialize(self, identity: ProfileIdentityRecord) -> ProfileAuthorityState:
        if self.profile_note_id is None or identity.profile_note_id != self.profile_note_id:
            raise ProfileAuthorityConflict(
                "profile authority identity does not match its storage key"
            )
        with self._locked():
            records = self._load_records_locked()
            if records:
                state = replay_profile_records(records)
                if (
                    state.identity.vault_id != identity.vault_id
                    or state.identity.profile_note_id != identity.profile_note_id
                    or state.identity.note_path != identity.note_path
                ):
                    raise ProfileAuthorityConflict(
                        "profile authority identity does not match the existing stream"
                    )
                return state
            self._atomic_replace(encode_profile_records((identity,)))
            return replay_profile_records((identity,))

    def append(
        self,
        record: ProfileAuthorityRecord,
        *,
        expected_revision: int,
        authority: object | None = None,
    ) -> ProfileAuthorityState:
        with self._locked():
            records = self._load_records_locked()
            if not records:
                raise ProfileAuthorityConflict("profile authority identity is not initialized")
            state = replay_profile_records(records)
            transition = validate_profile_transition(
                state,
                record,
                expected_revision=expected_revision,
                authority=authority,
            )
            self._atomic_replace(encode_profile_records(transition.next_state.records))
            return transition.next_state

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_directory()
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
        except OSError as exc:
            raise ProfileAuthorityContractError(
                "profile authority lock cannot be opened safely"
            ) from exc
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "a+b", closefd=False) as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def _ensure_directory(self) -> None:
        for directory in (self.vault_root / ".mimer", self.directory):
            if directory.exists() and directory.is_symlink():
                raise ProfileAuthorityContractError(
                    "profile authority storage does not follow symlink directories"
                )
            try:
                directory.mkdir(mode=0o700, exist_ok=True)
            except OSError as exc:
                raise ProfileAuthorityContractError(
                    "profile authority storage directory is unavailable"
                ) from exc
            # Retry parent-directory durability even when mkdir succeeded in a
            # previous call whose fsync was interrupted or failed.
            _fsync_directory(directory.parent)
            resolved = directory.resolve(strict=True)
            if not resolved.is_relative_to(self.vault_root):
                raise ProfileAuthorityContractError(
                    "profile authority storage escaped the bound vault"
                )
        os.chmod(self.directory, 0o700)

    def _load_records_locked(self) -> tuple[ProfileAuthorityRecord, ...]:
        # Re-establish directory-entry durability before any reader can
        # observe an atomic replacement that may have outlived a failed fsync.
        _fsync_directory(self.directory)
        try:
            descriptor = os.open(
                self.path,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError:
            return ()
        except OSError as exc:
            raise ProfileAuthorityContractError(
                "profile authority stream cannot be opened safely"
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ProfileAuthorityContractError(
                    "profile authority stream must be a regular file"
                )
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read()
        finally:
            os.close(descriptor)
        return decode_profile_records(raw)

    def _atomic_replace(self, content: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.directory,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
            _fsync_directory(self.directory)
        except Exception:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise


def _fsync_directory(path: Path) -> None:
    """Persist directory-entry changes made beneath this directory."""

    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def assert_profile_note_ingestible(
    vault_root: Path | str,
    note_path: str,
    note_uuid: str | None = None,
    *,
    source_text: str | None = None,
) -> None:
    """Reject unresolved writes and stale snapshots of the authority-bound note."""

    root = Path(vault_root).expanduser().resolve(strict=True)
    state = ProfileAuthorityStore(root, profile_note_id=None).load_state()
    if state is None:
        return
    matches_profile = _matches_profile_identity(
        state.identity, note_path=note_path, note_uuid=note_uuid
    )
    if state.pending_writes or state.unresolved_indeterminate_write_ids:
        stored_uuid = _canonical_uuid(state.identity.profile_note_id)
        if stored_uuid is None:
            # Without a valid durable identity, a moved Profile Note cannot be
            # distinguished from unrelated retained sources. Quarantine ingestion
            # until its active write outcome is reconciled.
            raise ProfileAuthorityConflict(
                "Profile Note identity is invalid while a ProfileAgent write is unresolved; "
                "vault ingestion is blocked"
            )
        if matches_profile or _canonical_uuid(note_uuid) is None:
            raise ProfileAuthorityConflict(
                "Profile Note or unidentified source has an unresolved ProfileAgent write; "
                "vault ingestion is blocked"
            )
        return
    if not matches_profile or source_text is None:
        return

    try:
        source_path = (root / note_path).resolve(strict=True)
        source_path.relative_to(root)
        current_text = source_path.read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise ProfileAuthorityConflict(
            "Profile Note source snapshot cannot be verified; vault ingestion is blocked"
        ) from exc
    if current_text != source_text:
        raise ProfileAuthorityConflict(
            "Profile Note changed during ingestion; stale source snapshot is blocked"
        )


def is_profile_note_source(
    vault_root: Path | str,
    note_path: str,
    note_uuid: str | None = None,
) -> bool:
    """Return whether a source path or UUID is bound to this vault's Profile Note."""

    state = ProfileAuthorityStore(vault_root, profile_note_id=None).load_state()
    if state is None:
        return False
    return _matches_profile_identity(
        state.identity, note_path=note_path, note_uuid=note_uuid
    )


def _matches_profile_identity(
    identity: ProfileIdentityRecord,
    *,
    note_path: str,
    note_uuid: str | None,
) -> bool:
    stored_uuid = _canonical_uuid(identity.profile_note_id)
    incoming_uuid = _canonical_uuid(note_uuid)
    return identity.note_path == note_path or (
        incoming_uuid is not None and stored_uuid == incoming_uuid
    )


def _canonical_uuid(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        return None
