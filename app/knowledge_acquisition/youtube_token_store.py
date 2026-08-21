"""YSS-02 (#3917): encrypted-at-rest OAuth token store for YouTube bindings.

Implements ``docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Secrets and
private bindings``: refresh/access tokens live only inside an AES-256-GCM
encrypted file, keyed by the account binding id. The key discipline mirrors
``app/heimdal/raw_store.py`` exactly -- authenticated encryption, a fresh
random nonce per record, and fail-loud key resolution that refuses to write or
read plaintext when the key is absent.

Boundary (INV-YSS-5 / INV-YSS-7):

- The store file path is an **app-local** binding, defaulting under the
  canonical channel runtime-artifact root (``tmp*/knowledge_acquisition/``);
  it is independent of process CWD/worktree and is never placed
  inside a vault and never tracked by git. Per-channel isolation (dev/test/prod
  never share OAuth state) comes from the per-channel runtime dir / the
  ``YOUTUBE_TOKEN_STORE_PATH`` override, exactly as the dispatcher isolates its
  state dir per channel.
- The key comes from ``YOUTUBE_TOKEN_STORE_KEY`` (32 bytes, hex), resolved
  through the host secret-provisioning boundary. A missing key with an existing
  binding is a legible ``auth_key_missing`` degraded state upstream, never a
  plaintext fallback -- this module raises :class:`TokenStoreKeyMissingError`
  and the OAuth layer maps it to the reason code.
- The on-disk structure carries only non-secret keys (binding ids) mapping to
  ``{ciphertext, nonce}``; no token, code, or client secret is ever written in
  clear. The record index (which binding ids have tokens) is readable without
  the key so upstream can detect "a binding exists" and fail closed; decrypting
  a record's bytes always requires the key.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import stat
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config.environment import ENV_DEV, active_environment
from app.config.paths import resolve_runtime_artifact_path

KEY_ENV_VAR = "YOUTUBE_TOKEN_STORE_KEY"
PATH_ENV_VAR = "YOUTUBE_TOKEN_STORE_PATH"

_AES_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # standard AES-GCM nonce size
_SCHEMA = "youtube-token-store.v1"
_STATE_DIRECTORY = "knowledge_acquisition"
_TOKEN_STORE_FILENAME = "youtube_token_store.enc"
_WRITER_LOCK_FILENAME = "youtube_oauth_writer.lock"
_LEGACY_DEFAULT_REL_PATH = Path("runtime/knowledge_acquisition/youtube_token_store.enc")
_MIGRATION_STAGE_FILENAME = f".{_TOKEN_STORE_FILENAME}.migration-stage"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class TokenStoreKeyMissingError(RuntimeError):
    """No/invalid encryption key configured -- refuse, never read/write plaintext.

    Upstream (``youtube_oauth``) catches this and degrades the binding to the
    ``auth_key_missing`` reason code (INV-YSS-4); it is never swallowed into a
    silent plaintext path.
    """


class OAuthStateBoundaryError(RuntimeError):
    """The private channel OAuth state boundary is absent or unsafe."""


class OAuthStateMigrationError(OAuthStateBoundaryError):
    """Legacy and channel-rooted OAuth state cannot converge safely."""


class OAuthWriterAdmissionError(RuntimeError):
    """Another process owns the channel's one OAuth writer transition."""


def resolve_token_store_key() -> bytes:
    """Resolve the AES-256-GCM key, fail-loud (mirrors ``resolve_raw_store_key``).

    The key is a 64-char hex string (32 bytes) in ``YOUTUBE_TOKEN_STORE_KEY``;
    generate with ``python -c "import secrets; print(secrets.token_hex(32))"``.
    A missing or malformed key raises rather than falling back to plaintext or
    a fixed default key.
    """
    raw = os.environ.get(KEY_ENV_VAR)
    if not raw:
        raise TokenStoreKeyMissingError(
            f"{KEY_ENV_VAR} is not set: YouTube OAuth tokens are encrypted at rest and this "
            "store refuses to read or write plaintext or use a fixed default key. Set "
            f"{KEY_ENV_VAR} to a 64-char hex string (32 bytes)."
        )
    try:
        key = bytes.fromhex(raw.strip())
    except ValueError as exc:
        raise TokenStoreKeyMissingError(f"{KEY_ENV_VAR} is not valid hex: {exc}") from exc
    if len(key) != _AES_KEY_BYTES:
        raise TokenStoreKeyMissingError(
            f"{KEY_ENV_VAR} must decode to {_AES_KEY_BYTES} bytes (AES-256), got {len(key)}"
        )
    return key


def _canonical_repository_root() -> Path:
    """Resolve the shared checkout root when running from a Git worktree."""

    try:
        dot_git = _REPO_ROOT / ".git"
        if dot_git.is_dir():
            return _REPO_ROOT
        if dot_git.is_file():
            marker = dot_git.read_text(encoding="utf-8").strip()
            if marker.startswith("gitdir:"):
                git_dir = Path(marker.removeprefix("gitdir:").strip())
                if not git_dir.is_absolute():
                    git_dir = _REPO_ROOT / git_dir
                common_marker = git_dir / "commondir"
                if common_marker.is_file():
                    common = Path(common_marker.read_text(encoding="utf-8").strip())
                    if not common.is_absolute():
                        common = git_dir / common
                    return common.resolve(strict=True).parent
    except OSError:
        pass
    raise OAuthStateBoundaryError(
        "canonical channel runtime-artifact root is not configured"
    )


def canonical_oauth_state_root() -> Path:
    """Resolve one checkout-independent private root inside channel artifacts."""

    configured_outbox = (os.environ.get("INDEX_OUTBOX_PATH") or "").strip()
    if configured_outbox:
        outbox = Path(configured_outbox).expanduser()
        if not outbox.is_absolute():
            raise OAuthStateBoundaryError(
                "channel runtime-artifact authority must be an absolute path"
            )
        runtime_root = Path(os.path.abspath(outbox.parent))
    else:
        scoped = resolve_runtime_artifact_path(
            Path("tmp/index-outbox.jsonl"), environment=active_environment()
        )
        runtime_root = _canonical_repository_root() / scoped.parent
    if not runtime_root.is_absolute():
        raise OAuthStateBoundaryError(
            "channel runtime-artifact authority must be an absolute path"
        )
    return runtime_root / _STATE_DIRECTORY


def _token_store_path(state_root: Path) -> Path:
    override = (os.environ.get(PATH_ENV_VAR) or "").strip()
    candidate = Path(override).expanduser() if override else state_root / _TOKEN_STORE_FILENAME
    if not candidate.is_absolute():
        candidate = state_root / candidate
    candidate = Path(os.path.abspath(candidate))
    normalized_root = Path(os.path.abspath(state_root))
    if candidate.parent != normalized_root or candidate.name in {"", ".", ".."}:
        raise OAuthStateBoundaryError(
            "YouTube OAuth state must remain inside the private channel runtime boundary"
        )
    return candidate


def default_token_store_path() -> Path:
    """Channel-rooted path, optionally renamed only inside the same private root."""

    return _token_store_path(canonical_oauth_state_root())


def _legacy_default_token_store_paths() -> tuple[Path, ...]:
    """Resolve every bounded checkout/CWD location used by the old producer.

    The former default was process-CWD-relative.  The product producer was
    dev-only and normally launched from a repository checkout, so upgrade
    discovery covers the current launch CWD, this module's checkout, the
    canonical shared checkout, and every linked worktree registered there.
    Multiple surviving stores are ambiguous and are refused by the migration
    preflight rather than guessed or merged.
    """

    roots = [Path.cwd(), _REPO_ROOT]
    try:
        canonical_root = _canonical_repository_root()
    except OAuthStateBoundaryError:
        canonical_root = None
    if canonical_root is not None:
        roots.append(canonical_root)
        worktrees_root = canonical_root / ".git" / "worktrees"
        try:
            entries = tuple(worktrees_root.iterdir())
        except FileNotFoundError:
            entries = ()
        except OSError as exc:
            raise OAuthStateMigrationError(
                "registered legacy YouTube OAuth locations are unavailable"
            ) from exc
        for entry in entries:
            gitdir_marker = entry / "gitdir"
            try:
                marker = gitdir_marker.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise OAuthStateMigrationError(
                    "registered legacy YouTube OAuth location is unavailable"
                ) from exc
            if marker:
                roots.append(Path(marker).expanduser().parent)

    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        candidate = Path(os.path.abspath(root / _LEGACY_DEFAULT_REL_PATH))
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return tuple(candidates)


def _normalized_path_identities(path: Path) -> frozenset[str]:
    """Path spellings that collapse on the default developer filesystem."""

    absolute = os.path.abspath(path)
    canonical = os.path.realpath(absolute)
    return frozenset(
        unicodedata.normalize("NFC", spelling).casefold()
        for spelling in (absolute, canonical)
    )


def _paths_alias(first: Path, second: Path) -> bool:
    """Detect lexical, case/Unicode, symlink, hard-link, and bind-mount aliases."""

    if _normalized_path_identities(first) & _normalized_path_identities(second):
        return True
    try:
        if os.path.samefile(first, second):
            return True
    except OSError:
        pass
    try:
        return os.path.samefile(first.parent, second.parent) and (
            unicodedata.normalize("NFC", first.name).casefold()
            == unicodedata.normalize("NFC", second.name).casefold()
        )
    except OSError:
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StoredToken:
    """The decrypted token material for one binding.

    ``refresh_token`` is a standing credential to the user's account; it and
    ``access_token`` never leave this object except through the encrypted store
    or the in-memory access-token provider. :meth:`__repr__` is redaction-aware
    so an accidental log/exception interpolation cannot leak the secret bytes.
    """

    refresh_token: str
    access_token: str | None
    expires_at: str | None  # ISO-8601 UTC access-token expiry, or None
    scopes: tuple[str, ...]
    obtained_at: str  # ISO-8601 UTC
    provider_channel_id: str | None

    def __repr__(self) -> str:  # redaction-aware (INV-YSS-5)
        return (
            "StoredToken(refresh_token=***, access_token=***, "
            f"expires_at={self.expires_at!r}, scopes={list(self.scopes)!r}, "
            f"obtained_at={self.obtained_at!r}, provider_channel_id={self.provider_channel_id!r})"
        )

    def with_expired_access(self) -> "StoredToken":
        """Return a copy whose access token is already expired (forces refresh)."""
        return StoredToken(
            refresh_token=self.refresh_token,
            access_token=self.access_token,
            expires_at="1970-01-01T00:00:00+00:00",
            scopes=self.scopes,
            obtained_at=self.obtained_at,
            provider_channel_id=self.provider_channel_id,
        )

    def _to_plain(self) -> dict[str, Any]:
        return {
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
            "expires_at": self.expires_at,
            "scopes": list(self.scopes),
            "obtained_at": self.obtained_at,
            "provider_channel_id": self.provider_channel_id,
        }

    @classmethod
    def _from_plain(cls, data: dict[str, Any]) -> "StoredToken":
        return cls(
            refresh_token=data["refresh_token"],
            access_token=data.get("access_token"),
            expires_at=data.get("expires_at"),
            scopes=tuple(data.get("scopes") or ()),
            obtained_at=data.get("obtained_at") or _now_iso(),
            provider_channel_id=data.get("provider_channel_id"),
        )


class OAuthWriterAdmission:
    """Held file descriptor for one start-to-finish OAuth writer transition."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)

    def __repr__(self) -> str:
        return "OAuthWriterAdmission(path=***)"


class YouTubeTokenStore:
    """AES-256-GCM encrypted token store, one JSON file, one record per binding.

    Thread-safe for concurrent access within a process. Atomic replacement
    prevents partial records; the writer admission serializes connect/reconnect
    transitions across processes.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            configured_path = (os.environ.get(PATH_ENV_VAR) or "").strip()
            state_root = canonical_oauth_state_root()
            self._path = _token_store_path(state_root)
            self._channel_runtime_root: Path | None = state_root.parent
            migrate_legacy_default = (
                active_environment() == ENV_DEV
                and not configured_path
            )
            if (
                not configured_path
                and any(
                    _paths_alias(self._path, legacy_path)
                    for legacy_path in _legacy_default_token_store_paths()
                )
            ):
                raise OAuthStateBoundaryError(
                    "channel-rooted YouTube OAuth state aliases the unscoped legacy default"
                )
        else:
            explicit = Path(path).expanduser()
            if not explicit.is_absolute():
                raise OAuthStateBoundaryError("explicit OAuth state path must be absolute")
            self._path = Path(os.path.abspath(explicit))
            self._channel_runtime_root = None
            migrate_legacy_default = False
        self._lock = threading.Lock()
        if migrate_legacy_default:
            self._migrate_legacy_default()
        if path is None and not configured_path:
            self._preflight_existing_default_target()

    def __repr__(self) -> str:
        return "YouTubeTokenStore(path=***)"

    @property
    def path(self) -> Path:
        return self._path

    # --- file helpers (no key required) -------------------------------------

    @staticmethod
    def _assert_private_directory(metadata: os.stat_result) -> None:
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_mode & 0o777 != 0o700
            or metadata.st_uid != os.geteuid()
        ):
            raise OAuthStateBoundaryError(
                "YouTube OAuth state directory must be a current-user-owned mode-0700 directory"
            )

    @staticmethod
    def _assert_private_file(metadata: os.stat_result) -> None:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o777 != 0o600
            or metadata.st_uid != os.geteuid()
        ):
            raise OAuthStateBoundaryError(
                "YouTube OAuth state file must be a current-user-owned mode-0600 regular file"
            )

    @staticmethod
    def _assert_legacy_directory(metadata: os.stat_result) -> None:
        """Accept the old mkdir-produced directory without accepting writable peers."""

        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_mode & 0o022
            or metadata.st_uid != os.geteuid()
        ):
            raise OAuthStateMigrationError(
                "legacy YouTube OAuth state directory is not safely current-user-owned"
            )

    @staticmethod
    def _assert_legacy_file(metadata: os.stat_result) -> None:
        """Accept old umask-derived read bits, but never another writer."""

        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o022
            or metadata.st_uid != os.geteuid()
        ):
            raise OAuthStateMigrationError(
                "legacy YouTube OAuth state file is not a safe current-user-owned regular file"
            )

    @staticmethod
    def _assert_safe_runtime_directory(metadata: os.stat_result) -> None:
        """Accept a private root or the shipped sticky shared scratch root."""

        if not stat.S_ISDIR(metadata.st_mode):
            raise OAuthStateBoundaryError(
                "channel runtime-artifact root is not a safe directory"
            )
        writable_by_others = bool(metadata.st_mode & 0o022)
        sticky = bool(metadata.st_mode & stat.S_ISVTX)
        if writable_by_others and not sticky:
            raise OAuthStateBoundaryError(
                "channel runtime-artifact root is not a safe directory"
            )

    @staticmethod
    def _assert_no_symlink_ancestry(path: Path, *, allow_missing_leaf: bool) -> None:
        """Reject traversal through a symlink before opening private state."""

        if not path.is_absolute():
            raise OAuthStateBoundaryError("OAuth state boundary must be absolute")
        current = Path(path.anchor)
        parts = path.parts[1:]
        for index, component in enumerate(parts):
            current /= component
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                if allow_missing_leaf and index == len(parts) - 1:
                    return
                raise OAuthStateBoundaryError(
                    "OAuth state boundary has a missing ancestor"
                ) from None
            except OSError:
                raise OAuthStateBoundaryError(
                    "OAuth state boundary ancestry is unavailable"
                ) from None
            if stat.S_ISLNK(metadata.st_mode):
                raise OAuthStateBoundaryError(
                    "OAuth state boundary must not traverse symlinks"
                )
            if index != len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
                raise OAuthStateBoundaryError(
                    "OAuth state boundary ancestry must contain only directories"
                )

    def _open_state_directory(self) -> int:
        parent = self._path.parent
        self._assert_no_symlink_ancestry(parent, allow_missing_leaf=True)
        if self._channel_runtime_root is not None:
            try:
                self._assert_no_symlink_ancestry(
                    self._channel_runtime_root, allow_missing_leaf=False
                )
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                runtime_fd = os.open(self._channel_runtime_root, flags)
            except FileNotFoundError:
                raise OAuthStateBoundaryError(
                    "canonical channel runtime-artifact root does not exist"
                ) from None
            except OSError:
                raise OAuthStateBoundaryError(
                    "canonical channel runtime-artifact root is unavailable"
                ) from None
            runtime_metadata = os.fstat(runtime_fd)
            try:
                self._assert_safe_runtime_directory(runtime_metadata)
            except OAuthStateBoundaryError:
                os.close(runtime_fd)
                raise
            descriptor = -1
            try:
                try:
                    os.mkdir(_STATE_DIRECTORY, mode=0o700, dir_fd=runtime_fd)
                except FileExistsError:
                    pass
                descriptor = os.open(_STATE_DIRECTORY, flags, dir_fd=runtime_fd)
                # The credential file cannot become authoritative until the
                # private directory's entry is durable in its parent.  Fsync
                # even when the directory pre-existed so a retry after an
                # indeterminate earlier fsync closes that crash window.
                os.fsync(runtime_fd)
            except OSError:
                if descriptor >= 0:
                    os.close(descriptor)
                raise OAuthStateBoundaryError(
                    "private YouTube OAuth state directory is unavailable"
                ) from None
            finally:
                os.close(runtime_fd)
        else:
            try:
                metadata = parent.lstat()
            except FileNotFoundError:
                try:
                    parent.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                except OSError:
                    raise OAuthStateBoundaryError(
                        "private YouTube OAuth state directory is unavailable"
                    ) from None
                metadata = parent.lstat()
            self._assert_private_directory(metadata)
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                descriptor = os.open(parent, flags)
            except OSError:
                raise OAuthStateBoundaryError(
                    "private YouTube OAuth state directory is unavailable"
                ) from None
        try:
            self._assert_private_directory(os.fstat(descriptor))
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    @staticmethod
    def _entry_exists(path: Path, *, label: str) -> bool:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise OAuthStateMigrationError(f"{label} state is unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise OAuthStateMigrationError(f"{label} state must not be a symlink")
        return True

    def _open_legacy_directory(self, legacy_path: Path) -> int | None:
        parent = legacy_path.parent
        try:
            parent_metadata = parent.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise OAuthStateMigrationError(
                "legacy YouTube OAuth state directory is unavailable"
            ) from exc
        self._assert_no_symlink_ancestry(parent, allow_missing_leaf=False)
        self._assert_legacy_directory(parent_metadata)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(parent, flags)
        except OSError as exc:
            raise OAuthStateMigrationError(
                "legacy YouTube OAuth state directory is unavailable"
            ) from exc
        try:
            self._assert_legacy_directory(os.fstat(descriptor))
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def _open_checked_store_entry(
        self,
        directory_fd: int,
        name: str,
        *,
        legacy: bool,
        label: str,
    ) -> int | None:
        try:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise OAuthStateMigrationError(f"{label} state is unavailable") from exc
        if legacy:
            self._assert_legacy_file(metadata)
        else:
            self._assert_private_file(metadata)
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise OAuthStateMigrationError(f"{label} state is unavailable") from exc
        try:
            metadata = os.fstat(descriptor)
            if legacy:
                self._assert_legacy_file(metadata)
            else:
                self._assert_private_file(metadata)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        return descriptor

    def _read_store_entry(
        self,
        directory_fd: int,
        name: str,
        *,
        legacy: bool,
        label: str,
    ) -> bytes | None:
        descriptor = self._open_checked_store_entry(
            directory_fd,
            name,
            legacy=legacy,
            label=label,
        )
        if descriptor is None:
            return None
        with os.fdopen(descriptor, "rb") as handle:
            payload = handle.read()
        self._validate_migration_payload(payload, label=label)
        return payload

    def _preflight_existing_default_target(self) -> None:
        """Refuse an unsafe implicit target before status/refresh receives the store."""

        if not self._entry_exists(self._path, label="channel-rooted"):
            return
        directory_fd = self._open_state_directory()
        try:
            payload = self._read_store_entry(
                directory_fd,
                self._path.name,
                legacy=False,
                label="channel-rooted",
            )
            assert payload is not None
        finally:
            os.close(directory_fd)

    @staticmethod
    def _validate_migration_payload(payload: bytes, *, label: str) -> None:
        """Validate only encrypted structure; migration never decrypts or falls back."""

        try:
            data = json.loads(payload.decode("utf-8"))
            if not isinstance(data, dict) or data.get("schema") != _SCHEMA:
                raise ValueError("unexpected schema")
            records = data.get("records")
            if not isinstance(records, dict):
                raise ValueError("records must be an object")
            for binding_id, record in records.items():
                if not isinstance(binding_id, str) or not binding_id:
                    raise ValueError("invalid binding id")
                if not isinstance(record, dict):
                    raise ValueError("invalid encrypted record")
                ciphertext = record.get("ciphertext")
                nonce = record.get("nonce")
                if not isinstance(ciphertext, str) or not isinstance(nonce, str):
                    raise ValueError("invalid encrypted record fields")
                decoded_ciphertext = base64.b64decode(ciphertext, validate=True)
                decoded_nonce = base64.b64decode(nonce, validate=True)
                if len(decoded_nonce) != _NONCE_BYTES or len(decoded_ciphertext) < 16:
                    raise ValueError("invalid AES-GCM record")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise OAuthStateMigrationError(
                f"{label} encrypted YouTube token store failed migration preflight"
            ) from exc

    def _acquire_migration_admission(self) -> OAuthWriterAdmission:
        directory_fd = self._open_state_directory()
        try:
            descriptor = os.open(
                _WRITER_LOCK_FILENAME,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            try:
                self._assert_private_file(os.fstat(descriptor))
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except BaseException:
                os.close(descriptor)
                raise
            return OAuthWriterAdmission(descriptor)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _assert_equal_payloads(first: bytes, second: bytes, *, states: str) -> None:
        if first != second:
            raise OAuthStateMigrationError(
                f"ambiguous encrypted YouTube token stores exist in {states}"
            )

    def _remove_migration_entry(self, directory_fd: int, name: str, *, label: str) -> None:
        try:
            os.unlink(name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except OSError as exc:
            raise OAuthStateMigrationError(f"{label} failed") from exc

    def _publish_migration_payload(
        self,
        directory_fd: int,
        payload: bytes,
        *,
        staged_payload: bytes | None,
    ) -> bytes:
        # Rollback owns only entries created by this attempt.  A pre-existing
        # stage is independent recovery evidence and must survive any refusal.
        stage_created = False
        target_created = False
        try:
            if staged_payload is None:
                descriptor = os.open(
                    _MIGRATION_STAGE_FILENAME,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                stage_created = True
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                staged_payload = self._read_store_entry(
                    directory_fd,
                    _MIGRATION_STAGE_FILENAME,
                    legacy=False,
                    label="staged migration",
                )
                assert staged_payload is not None
            self._assert_equal_payloads(
                payload, staged_payload, states="legacy and staged state"
            )
            os.link(
                _MIGRATION_STAGE_FILENAME,
                self._path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            target_created = True
            os.fsync(directory_fd)
            published = self._read_store_entry(
                directory_fd,
                self._path.name,
                legacy=False,
                label="channel-rooted",
            )
            assert published is not None
            self._assert_equal_payloads(payload, published, states="legacy and channel state")
            self._remove_migration_entry(
                directory_fd,
                _MIGRATION_STAGE_FILENAME,
                label="staged migration cleanup",
            )
            stage_created = False
            return published
        except Exception as exc:
            rollback_error: OSError | None = None
            if target_created:
                try:
                    os.unlink(self._path.name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                except OSError as rollback_exc:
                    rollback_error = rollback_exc
            if stage_created:
                try:
                    os.unlink(_MIGRATION_STAGE_FILENAME, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                except OSError as cleanup_exc:
                    rollback_error = rollback_error or cleanup_exc
            if rollback_error is not None:
                raise OAuthStateMigrationError(
                    "target publication failed and rollback could not be verified"
                ) from exc
            if (
                not target_created
                and not stage_created
                and isinstance(exc, OAuthStateMigrationError)
            ):
                raise
            raise OAuthStateMigrationError(
                "target publication failed; encrypted legacy state was preserved"
            ) from exc

    def _migrate_legacy_default(self) -> None:
        """Converge the old default into this channel before any credential read."""

        legacy_candidates = _legacy_default_token_store_paths()
        if any(_paths_alias(self._path, path) for path in legacy_candidates):
            raise OAuthStateBoundaryError(
                "channel-rooted YouTube OAuth state aliases the unscoped legacy default"
            )
        legacy_paths = tuple(
            path
            for path in legacy_candidates
            if self._entry_exists(path, label="legacy")
        )
        if len(legacy_paths) > 1:
            raise OAuthStateMigrationError(
                "ambiguous encrypted YouTube token stores exist in multiple legacy locations"
            )
        legacy_path = legacy_paths[0] if legacy_paths else None
        stage_path = self._path.with_name(_MIGRATION_STAGE_FILENAME)
        stage_exists = self._entry_exists(stage_path, label="staged migration")
        if legacy_path is None and not stage_exists:
            return

        admission = self._acquire_migration_admission()
        legacy_fd: int | None = None
        target_fd: int | None = None
        try:
            legacy_fd = (
                self._open_legacy_directory(legacy_path)
                if legacy_path is not None
                else None
            )
            legacy = (
                self._read_store_entry(
                    legacy_fd,
                    _TOKEN_STORE_FILENAME,
                    legacy=True,
                    label="legacy",
                )
                if legacy_fd is not None
                else None
            )
            target_fd = self._open_state_directory()
            target = self._read_store_entry(
                target_fd,
                self._path.name,
                legacy=False,
                label="channel-rooted",
            )
            stage = self._read_store_entry(
                target_fd,
                _MIGRATION_STAGE_FILENAME,
                legacy=False,
                label="staged migration",
            )

            if legacy is None and stage is not None and target is None:
                raise OAuthStateMigrationError(
                    "orphaned staged migration has no legacy or channel authority"
                )
            if legacy is None:
                assert target is not None
                if stage is not None:
                    self._assert_equal_payloads(
                        target, stage, states="channel and staged state"
                    )
                    self._remove_migration_entry(
                        target_fd,
                        _MIGRATION_STAGE_FILENAME,
                        label="staged migration cleanup",
                    )
                return
            if target is None:
                target = self._publish_migration_payload(
                    target_fd,
                    legacy,
                    staged_payload=stage,
                )
            else:
                self._assert_equal_payloads(
                    legacy, target, states="legacy and channel-rooted state"
                )
                if stage is not None:
                    self._assert_equal_payloads(
                        target, stage, states="channel and staged state"
                    )
                    self._remove_migration_entry(
                        target_fd,
                        _MIGRATION_STAGE_FILENAME,
                        label="staged migration cleanup",
                    )
            try:
                # A visible target from an interrupted publication is not yet
                # authority proof.  Re-establish its directory-link durability
                # on every retry before the legacy authority can be removed.
                os.fsync(target_fd)
            except OSError as exc:
                raise OAuthStateMigrationError(
                    "channel-rooted durability verification failed"
                ) from exc
            assert legacy_fd is not None
            current_legacy = self._read_store_entry(
                legacy_fd,
                _TOKEN_STORE_FILENAME,
                legacy=True,
                label="legacy",
            )
            assert current_legacy is not None
            self._assert_equal_payloads(
                target, current_legacy, states="channel and final legacy state"
            )
            self._remove_migration_entry(
                legacy_fd,
                _TOKEN_STORE_FILENAME,
                label="legacy finalization",
            )
        finally:
            if target_fd is not None:
                os.close(target_fd)
            if legacy_fd is not None:
                os.close(legacy_fd)
            admission.release()

    def _load_file(self) -> dict[str, Any]:
        directory_fd = self._open_state_directory()
        try:
            descriptor = self._open_checked_store_entry(
                directory_fd,
                self._path.name,
                legacy=False,
                label="channel-rooted",
            )
            if descriptor is None:
                return {"schema": _SCHEMA, "records": {}}
            try:
                with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                    raw = handle.read()
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
        finally:
            os.close(directory_fd)
        data = json.loads(raw)
        if not isinstance(data, dict) or "records" not in data:
            raise ValueError("corrupt YouTube token store")
        return data

    def _write_file(self, data: dict[str, Any]) -> None:
        directory_fd = self._open_state_directory()
        temporary_name = f".{self._path.name}.{uuid.uuid4().hex}.tmp"
        descriptor: int | None = None
        try:
            existing = self._open_checked_store_entry(
                directory_fd,
                self._path.name,
                legacy=False,
                label="channel-rooted",
            )
            if existing is not None:
                os.close(existing)
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            payload = json.dumps(data, sort_keys=True).encode("utf-8")
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary_name,
                self._path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)

    def acquire_writer_admission(self) -> OAuthWriterAdmission:
        """Acquire the channel's nonblocking cross-process OAuth writer lease."""

        directory_fd = self._open_state_directory()
        try:
            descriptor = os.open(
                _WRITER_LOCK_FILENAME,
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            try:
                self._assert_private_file(os.fstat(descriptor))
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise OAuthWriterAdmissionError(
                        "another YouTube OAuth writer transition is active"
                    ) from None
            except BaseException:
                os.close(descriptor)
                raise
            return OAuthWriterAdmission(descriptor)
        finally:
            os.close(directory_fd)

    def has_record(self, binding_id: str) -> bool:
        """True if a token record exists for ``binding_id`` (no key required)."""
        with self._lock:
            return binding_id in self._load_file()["records"]

    def binding_ids(self) -> tuple[str, ...]:
        """All binding ids with a token record (no key required)."""
        with self._lock:
            return tuple(self._load_file()["records"].keys())

    def delete(self, binding_id: str) -> bool:
        """Remove one binding's token record. Returns True if a record existed.

        No key is required: deletion removes ciphertext, it does not read it.
        """
        with self._lock:
            data = self._load_file()
            existed = binding_id in data["records"]
            if existed:
                del data["records"][binding_id]
                self._write_file(data)
            return existed

    # --- encrypted record access (key required) -----------------------------

    def put(self, binding_id: str, token: StoredToken) -> None:
        """Encrypt and persist ``token`` for ``binding_id`` (requires the key)."""
        key = resolve_token_store_key()
        plaintext = json.dumps(token._to_plain(), sort_keys=True).encode("utf-8")
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
        with self._lock:
            data = self._load_file()
            data["records"][binding_id] = {
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
            }
            self._write_file(data)

    def get(self, binding_id: str) -> StoredToken | None:
        """Return the decrypted token for ``binding_id``, or None if absent.

        Returns None when no record exists (no key needed for that). When a
        record DOES exist, the key is required to decrypt it; a missing key
        raises :class:`TokenStoreKeyMissingError` -- there is no plaintext read
        path (fail closed, INV-YSS-4).
        """
        with self._lock:
            record = self._load_file()["records"].get(binding_id)
        if record is None:
            return None
        key = resolve_token_store_key()
        ciphertext = base64.b64decode(record["ciphertext"])
        nonce = base64.b64decode(record["nonce"])
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
        return StoredToken._from_plain(json.loads(plaintext.decode("utf-8")))


__all__ = [
    "KEY_ENV_VAR",
    "OAuthStateBoundaryError",
    "OAuthStateMigrationError",
    "OAuthWriterAdmission",
    "OAuthWriterAdmissionError",
    "PATH_ENV_VAR",
    "StoredToken",
    "TokenStoreKeyMissingError",
    "YouTubeTokenStore",
    "canonical_oauth_state_root",
    "default_token_store_path",
    "resolve_token_store_key",
]
