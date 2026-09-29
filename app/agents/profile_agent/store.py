"""Vault-local persistence for the governed profile authority record stream."""

from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import tempfile
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

    def __init__(self, vault_root: Path | str, profile_note_id: str) -> None:
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

    def load_state(self) -> ProfileAuthorityState | None:
        records = self.load_records()
        return replay_profile_records(records) if records else None

    def initialize(self, identity: ProfileIdentityRecord) -> ProfileAuthorityState:
        if identity.profile_note_id != self.profile_note_id:
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
            resolved = directory.resolve(strict=True)
            if not resolved.is_relative_to(self.vault_root):
                raise ProfileAuthorityContractError(
                    "profile authority storage escaped the bound vault"
                )
        os.chmod(self.directory, 0o700)

    def _load_records_locked(self) -> tuple[ProfileAuthorityRecord, ...]:
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
            directory_fd = os.open(
                self.directory,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
