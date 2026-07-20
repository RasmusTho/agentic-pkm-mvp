"""YSS-02 (#3917): encrypted-at-rest OAuth token store for YouTube bindings.

Implements ``docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Secrets and
private bindings``: refresh/access tokens live only inside an AES-256-GCM
encrypted file, keyed by the account binding id. The key discipline mirrors
``app/heimdal/raw_store.py`` exactly -- authenticated encryption, a fresh
random nonce per record, and fail-loud key resolution that refuses to write or
read plaintext when the key is absent.

Boundary (INV-YSS-5 / INV-YSS-7):

- The store file path is an **app-local** binding, defaulting under the
  channel runtime dir (``runtime/knowledge_acquisition/``); it is never placed
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
  ``{ciphertext, nonce, aad_version}``; every current ciphertext authenticates
  that exact outer id as AEAD associated data and repeats it inside the
  encrypted envelope. No token, code, or client secret is ever written in
  clear. The record index (which binding ids have tokens) is readable without
  the key so upstream can detect "a binding exists" and fail closed; decrypting
  a record's bytes always requires the key.
- A binding-scoped lifecycle lock combines a process-local ``RLock`` with an OS
  file lock so connect, reconnect, refresh, and disconnect can serialize across
  store instances and runtime processes. Lock filenames are SHA-256 digests of
  binding ids, and their private app-local files contain no identifiers or
  credential bytes.
- Every aggregate token-file read/modify/write also takes one store-wide lock,
  preventing distinct bindings from losing each other's records. The lock
  backend is guarded and portable across POSIX ``flock`` and Windows
  ``msvcrt.locking``; unsupported platforms fail closed.
- Device-flow completion proves key plus locked atomic write/read readiness
  before polling can issue a grant. An encrypted canary binds the configured
  key to the aggregate. Pre-AAD aggregates upgrade atomically only after the
  OAuth layer proves each decrypted record's binding/channel or pending-target
  identity; an unprovable or pre-swapped legacy association fails closed without
  mutation. Each POSIX aggregate write syncs the staged file,
  atomically replaces the live path, then syncs its parent directory; Windows
  uses write-through replacement. Visible readback after a failed barrier is
  not durable authority until a fresh barrier succeeds. Fresh grants can
  therefore be journaled immediately under an opaque pending id before
  identity/binding work.
"""

from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised through platform-path tests
    _fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - exercised through platform-path tests
    _msvcrt = None  # type: ignore[assignment]

KEY_ENV_VAR = "YOUTUBE_TOKEN_STORE_KEY"
PATH_ENV_VAR = "YOUTUBE_TOKEN_STORE_PATH"

_AES_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # standard AES-GCM nonce size
_SCHEMA = "youtube-token-store.v1"
_KEY_CHECK_PLAINTEXT = b"youtube-token-store-key-check.v1"
_RECORD_AAD_VERSION = "binding-id.v1"
_RECORD_ENVELOPE_VERSION = "youtube-token-record.v2"
_RECORD_AAD_PREFIX = b"agentic-pkm:youtube-token-store:binding-id:v1\0"
_DEFAULT_REL_PATH = Path("runtime/knowledge_acquisition/youtube_token_store.enc")

_LIFECYCLE_LOCKS_GUARD = threading.Lock()
_LIFECYCLE_THREAD_LOCKS: dict[str, threading.RLock] = {}


def _lifecycle_thread_lock(lock_path: Path) -> threading.RLock:
    """Return the process-local half of one cross-process lifecycle lock."""
    key = str(lock_path)
    with _LIFECYCLE_LOCKS_GUARD:
        lock = _LIFECYCLE_THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LIFECYCLE_THREAD_LOCKS[key] = lock
        return lock


@contextmanager
def _portable_file_lock(lock_path: Path) -> Iterator[None]:
    """Exclusive portable file lock; fail closed on unsupported platforms."""
    thread_lock = _lifecycle_thread_lock(lock_path)
    with thread_lock:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            if _fcntl is not None:
                _fcntl.flock(descriptor, _fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    _fcntl.flock(descriptor, _fcntl.LOCK_UN)
            elif _msvcrt is not None:
                _msvcrt.locking(descriptor, _msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    _msvcrt.locking(descriptor, _msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - defensive unsupported-platform boundary
                raise RuntimeError("no supported cross-process file locking primitive")
        finally:
            os.close(descriptor)


class TokenStoreKeyMissingError(RuntimeError):
    """No/invalid encryption key configured -- refuse, never read/write plaintext.

    Upstream (``youtube_oauth``) catches this and degrades the binding to the
    ``auth_key_missing`` reason code (INV-YSS-4); it is never swallowed into a
    silent plaintext path.
    """


class TokenStoreKeyMismatchError(TokenStoreKeyMissingError):
    """The configured key cannot authenticate the existing aggregate.

    This is deliberately a subtype of :class:`TokenStoreKeyMissingError` so
    callers keep the existing fail-closed ``auth_key_missing`` reason-code
    contract for both absent and unusable key material.
    """


class TokenStoreDurabilityError(OSError):
    """An aggregate replacement lacks a confirmed persistence barrier."""


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
    invalid_hex = False
    try:
        key = bytes.fromhex(raw.strip())
    except ValueError:
        invalid_hex = True
        key = b""
    if invalid_hex:
        # Raised outside the secret-bearing parse handler so recursive
        # exception inspection cannot reach the rejected environment value.
        raise TokenStoreKeyMissingError(f"{KEY_ENV_VAR} is not valid hex")
    if len(key) != _AES_KEY_BYTES:
        raise TokenStoreKeyMissingError(
            f"{KEY_ENV_VAR} must decode to {_AES_KEY_BYTES} bytes (AES-256), got {len(key)}"
        )
    return key


def default_token_store_path() -> Path:
    """App-local default path, overridable per channel via ``YOUTUBE_TOKEN_STORE_PATH``."""
    override = (os.environ.get(PATH_ENV_VAR) or "").strip()
    if override:
        return Path(override).expanduser()
    return _DEFAULT_REL_PATH


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
    # Credential-authority generation and promotion evidence live only inside
    # this encrypted payload.  They let a retry distinguish the predecessor it
    # is allowed to replace from a newer independently rotated credential.
    authority_generation: int = 0
    promotion_target_binding_id: str | None = None
    promotion_predecessor_refresh_token: str | None = None
    promotion_predecessor_generation: int | None = None
    promotion_predecessor_binding_updated_at: str | None = None
    promotion_display_label: str | None = None
    # A rotated refresh journal must become non-promotable before provider
    # compensation. ``pending`` means revocation must be retried; ``compensated``
    # means provider authority is already gone and only encrypted cleanup remains.
    promotion_compensation_state: str | None = None

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
            authority_generation=self.authority_generation,
            promotion_target_binding_id=self.promotion_target_binding_id,
            promotion_predecessor_refresh_token=self.promotion_predecessor_refresh_token,
            promotion_predecessor_generation=self.promotion_predecessor_generation,
            promotion_predecessor_binding_updated_at=(
                self.promotion_predecessor_binding_updated_at
            ),
            promotion_display_label=self.promotion_display_label,
            promotion_compensation_state=self.promotion_compensation_state,
        )

    def _to_plain(self) -> dict[str, Any]:
        return {
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
            "expires_at": self.expires_at,
            "scopes": list(self.scopes),
            "obtained_at": self.obtained_at,
            "provider_channel_id": self.provider_channel_id,
            "authority_generation": self.authority_generation,
            "promotion_target_binding_id": self.promotion_target_binding_id,
            "promotion_predecessor_refresh_token": self.promotion_predecessor_refresh_token,
            "promotion_predecessor_generation": self.promotion_predecessor_generation,
            "promotion_predecessor_binding_updated_at": (
                self.promotion_predecessor_binding_updated_at
            ),
            "promotion_display_label": self.promotion_display_label,
            "promotion_compensation_state": self.promotion_compensation_state,
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
            authority_generation=int(data.get("authority_generation") or 0),
            promotion_target_binding_id=data.get("promotion_target_binding_id"),
            promotion_predecessor_refresh_token=data.get(
                "promotion_predecessor_refresh_token"
            ),
            promotion_predecessor_generation=(
                int(data["promotion_predecessor_generation"])
                if data.get("promotion_predecessor_generation") is not None
                else None
            ),
            promotion_predecessor_binding_updated_at=data.get(
                "promotion_predecessor_binding_updated_at"
            ),
            promotion_display_label=data.get("promotion_display_label"),
            promotion_compensation_state=data.get("promotion_compensation_state"),
        )


class YouTubeTokenStore:
    """AES-256-GCM encrypted token store, one JSON file, one record per binding.

    Individual file operations are thread-safe and writes sync the staged file,
    atomically replace the live path, then sync the parent directory.
    Multi-operation credential lifecycles use :meth:`binding_lifecycle_lock`
    for cross-instance and cross-process serialization.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_token_store_path()
        self._lock = threading.Lock()
        self._legacy_record_validator: Callable[[str, StoredToken], bool] | None = None

    def __repr__(self) -> str:
        return f"YouTubeTokenStore(path={str(self._path)!r})"

    @property
    def path(self) -> Path:
        return self._path

    def set_legacy_record_validator(
        self, validator: Callable[[str, StoredToken], bool]
    ) -> None:
        """Install the authority check required before rebinding legacy records.

        Pre-AAD ciphertext does not authenticate its outer record id. It may be
        upgraded only when the OAuth authority layer proves that the decrypted
        token belongs to that id. Merely decrypting with the configured key is
        intentionally insufficient because two valid legacy records could have
        been exchanged before migration.
        """
        if not callable(validator):
            raise TypeError("legacy record validator must be callable")
        self._legacy_record_validator = validator

    @contextmanager
    def binding_lifecycle_lock(self, binding_id: str) -> Iterator[None]:
        """Serialize one binding's credential lifecycle across actors.

        The process-local ``RLock`` serializes separate service/store instances
        in one runtime, while ``flock`` on an app-local hashed lock file extends
        the same critical section across runtime processes sharing this channel
        token store. The lock file contains no binding id or credential bytes.
        """
        if not isinstance(binding_id, str) or not binding_id:
            raise ValueError("binding_id must be a non-empty string")
        store_path = self._path.resolve(strict=False)
        lock_root = store_path.parent / f".{store_path.name}.locks"
        lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        binding_digest = hashlib.sha256(binding_id.encode("utf-8")).hexdigest()
        lock_path = lock_root / f"{binding_digest}.lock"
        with _portable_file_lock(lock_path):
            yield

    @contextmanager
    def _aggregate_file_lock(self) -> Iterator[None]:
        store_path = self._path.resolve(strict=False)
        lock_root = store_path.parent / f".{store_path.name}.locks"
        lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with _portable_file_lock(lock_root / "store.lock"):
            yield

    # --- file helpers (no key required) -------------------------------------

    def _load_file(self) -> dict[str, Any]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"schema": _SCHEMA, "records": {}}
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("schema") != _SCHEMA
            or not isinstance(data.get("records"), dict)
        ):
            raise ValueError(f"corrupt token store file at {self._path}")
        return data

    @staticmethod
    def _record_aad(binding_id: str) -> bytes:
        if not isinstance(binding_id, str) or not binding_id:
            raise ValueError("binding_id must be a non-empty string")
        return _RECORD_AAD_PREFIX + binding_id.encode("utf-8")

    @classmethod
    def _encrypted_record(
        cls,
        key: bytes,
        plaintext: bytes,
        *,
        binding_id: str | None = None,
    ) -> dict[str, str]:
        nonce = os.urandom(_NONCE_BYTES)
        aad = cls._record_aad(binding_id) if binding_id is not None else None
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
        record = {
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
        }
        if binding_id is not None:
            record["aad_version"] = _RECORD_AAD_VERSION
        return record

    @classmethod
    def _decrypt_record(
        cls,
        record: Any,
        key: bytes,
        *,
        binding_id: str | None = None,
        allow_legacy: bool = False,
    ) -> tuple[bytes, bool]:
        failed = False
        plaintext = b""
        legacy = False
        try:
            if not isinstance(record, dict):
                raise TypeError
            aad_version = record.get("aad_version")
            if binding_id is None:
                if aad_version is not None:
                    raise ValueError
                aad = None
            elif aad_version == _RECORD_AAD_VERSION:
                aad = cls._record_aad(binding_id)
            elif aad_version is None and allow_legacy:
                aad = None
                legacy = True
            else:
                raise ValueError
            ciphertext = base64.b64decode(record["ciphertext"], validate=True)
            nonce = base64.b64decode(record["nonce"], validate=True)
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
        except (InvalidTag, binascii.Error, KeyError, TypeError, ValueError):
            failed = True
        if failed:
            # Never chain the cryptography/base64 failure: even defensive error
            # walkers must not gain another route into credential-bearing data.
            raise TokenStoreKeyMismatchError(
                "configured YouTube token-store key cannot authenticate the encrypted aggregate"
            )
        return plaintext, legacy

    @staticmethod
    def _token_plaintext(binding_id: str, token: StoredToken) -> bytes:
        return json.dumps(
            {
                "envelope": _RECORD_ENVELOPE_VERSION,
                "record_binding_id": binding_id,
                "token": token._to_plain(),
            },
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def _decode_token_plaintext(
        cls,
        binding_id: str,
        plaintext: bytes,
        *,
        legacy: bool,
    ) -> StoredToken:
        malformed = False
        token: StoredToken | None = None
        try:
            decoded = json.loads(plaintext.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise TypeError
            if legacy:
                token_data = decoded
            else:
                if (
                    decoded.get("envelope") != _RECORD_ENVELOPE_VERSION
                    or decoded.get("record_binding_id") != binding_id
                    or not isinstance(decoded.get("token"), dict)
                ):
                    raise ValueError
                token_data = decoded["token"]
            token = StoredToken._from_plain(token_data)
        except (KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            malformed = True
        if malformed or token is None:
            raise TokenStoreKeyMismatchError(
                "configured YouTube token-store key cannot authenticate the encrypted aggregate"
            )
        return token

    @classmethod
    def _decode_token_record(
        cls,
        binding_id: str,
        record: Any,
        key: bytes,
        *,
        allow_legacy: bool,
    ) -> tuple[StoredToken, bool]:
        plaintext, legacy = cls._decrypt_record(
            record,
            key,
            binding_id=binding_id,
            allow_legacy=allow_legacy,
        )
        return (
            cls._decode_token_plaintext(
                binding_id,
                plaintext,
                legacy=legacy,
            ),
            legacy,
        )

    def _bind_or_verify_aggregate_key(
        self,
        data: dict[str, Any],
        key: bytes,
        *,
        initialize: bool,
    ) -> bool:
        """Cryptographically bind ``key`` to the whole existing aggregate.

        New/current aggregates carry an encrypted fixed canary and record-id
        bound envelopes. A legacy record is admitted only after both its
        ciphertext and its authority identity validate; initialization upgrades
        every admitted legacy record together and installs a missing canary.
        """
        key_check = data.get("key_check")
        if key_check is not None:
            key_check_plaintext, _ = self._decrypt_record(key_check, key)
            if key_check_plaintext != _KEY_CHECK_PLAINTEXT:
                raise TokenStoreKeyMismatchError(
                    "configured YouTube token-store key cannot authenticate the encrypted aggregate"
                )

        decoded_records: dict[str, StoredToken] = {}
        legacy_ids: list[str] = []
        for binding_id, record in data["records"].items():
            token, legacy = self._decode_token_record(
                binding_id,
                record,
                key,
                allow_legacy=True,
            )
            decoded_records[binding_id] = token
            if legacy:
                legacy_ids.append(binding_id)

        legacy_invalid = False
        if legacy_ids:
            validator = self._legacy_record_validator
            if validator is None:
                legacy_invalid = True
            else:
                try:
                    legacy_invalid = any(
                        not validator(binding_id, decoded_records[binding_id])
                        for binding_id in legacy_ids
                    )
                except Exception:
                    legacy_invalid = True
        if legacy_invalid:
            # Never retain a validator exception as hidden context: backend
            # detail and token material stay outside the public error chain.
            raise TokenStoreKeyMismatchError(
                "legacy YouTube token-store record identity cannot be authenticated"
            )

        changed = False
        if initialize:
            for binding_id in legacy_ids:
                data["records"][binding_id] = self._encrypted_record(
                    key,
                    self._token_plaintext(binding_id, decoded_records[binding_id]),
                    binding_id=binding_id,
                )
                changed = True
            if key_check is None:
                data["key_check"] = self._encrypted_record(
                    key, _KEY_CHECK_PLAINTEXT
                )
                changed = True
        return changed

    def _sync_parent_directory(self) -> None:
        """Confirm the complete directory-entry chain on POSIX.

        Windows takes the separate ``MoveFileExW(..., WRITE_THROUGH)`` path in
        :meth:`_replace_with_barrier`; opening/fsyncing a directory is not a
        portable Windows operation. On POSIX, syncing only the immediate parent
        is insufficient when first use created multiple nested parents: the
        file can be visible while a new directory link is absent after crash.
        """
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        parent = self._path.parent.resolve(strict=False)
        while True:
            directory_fd = os.open(parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            if parent.parent == parent:
                break
            parent = parent.parent

    def _replace_with_barrier(self, source: Path) -> None:
        if os.name != "nt":
            os.replace(source, self._path)
            self._sync_parent_directory()
            return

        # MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH. The latter is
        # Windows' supported persistence barrier for the rename itself; a
        # directory fsync emulation would be both unreliable and unportable.
        move_file_ex = getattr(ctypes, "windll").kernel32.MoveFileExW
        move_file_ex.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
        move_file_ex.restype = ctypes.c_int
        if not move_file_ex(str(source), str(self._path), 0x1 | 0x8):
            raise OSError("Windows write-through token-store replacement failed")

    def _write_file(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as staged:
            staged.write(json.dumps(data, sort_keys=True))
            staged.flush()
            # The staged ciphertext/index must reach stable storage before its
            # name can replace the last durable aggregate.
            os.fsync(staged.fileno())
        barrier_failed = False
        try:
            self._replace_with_barrier(tmp)
        except OSError:
            barrier_failed = True
        if barrier_failed:
            # A visible replacement is intentionally not treated as durable
            # authority. OAuth callers may retry the barrier explicitly before
            # accepting exact readback; otherwise they compensate or preserve
            # the prior pending journal.
            raise TokenStoreDurabilityError(
                "YouTube token-store replacement lacks a confirmed persistence barrier"
            )

    def has_record(self, binding_id: str) -> bool:
        """True if a token record exists for ``binding_id`` (no key required)."""
        with self._lock, self._aggregate_file_lock():
            return binding_id in self._load_file()["records"]

    def binding_ids(self) -> tuple[str, ...]:
        """All binding ids with a token record (no key required)."""
        with self._lock, self._aggregate_file_lock():
            return tuple(self._load_file()["records"].keys())

    def delete(self, binding_id: str) -> bool:
        """Remove one binding's token record. Returns True if a record existed.

        No key is required: deletion removes ciphertext, it does not read it.
        """
        with self._lock, self._aggregate_file_lock():
            data = self._load_file()
            existed = binding_id in data["records"]
            if existed:
                del data["records"][binding_id]
                self._write_file(data)
            return existed

    # --- encrypted record access (key required) -----------------------------

    def preflight_write_ready(self) -> None:
        """Prove key and atomic store I/O readiness before an OAuth grant.

        The unchanged aggregate is rewritten under the normal store lock and
        read back before any provider token poll may issue a standing grant.
        This catches a missing/invalid key, corrupt store, unwritable parent,
        failed temporary write, and failed atomic replacement without placing
        any secret material in a probe record.
        """
        key = resolve_token_store_key()
        # Exercise the configured key with the same primitive used by ``put``;
        # the probe remains in memory and contains no credential material.
        AESGCM(key).encrypt(os.urandom(_NONCE_BYTES), b"youtube-token-store-readiness", None)
        with self._lock, self._aggregate_file_lock():
            data = self._load_file()
            self._bind_or_verify_aggregate_key(data, key, initialize=True)
            self._write_file(data)
            verified = self._load_file()
            if verified != data:
                raise RuntimeError("YouTube token store readiness verification failed")
            self._bind_or_verify_aggregate_key(verified, key, initialize=False)

    def put(self, binding_id: str, token: StoredToken) -> None:
        """Encrypt and persist ``token`` for ``binding_id`` (requires the key)."""
        key = resolve_token_store_key()
        with self._lock, self._aggregate_file_lock():
            data = self._load_file()
            self._bind_or_verify_aggregate_key(data, key, initialize=True)
            data["records"][binding_id] = self._encrypted_record(
                key,
                self._token_plaintext(binding_id, token),
                binding_id=binding_id,
            )
            self._write_file(data)

    def confirm_record_durable(self, binding_id: str, expected: StoredToken) -> bool:
        """Retry the parent barrier, then authenticate exact record authority.

        Used only after :class:`TokenStoreDurabilityError`. Readback happens
        *after* the successful retry barrier; visibility alone never proves
        crash durability.
        """
        confirmed = False
        try:
            with self._lock, self._aggregate_file_lock():
                self._sync_parent_directory()
                data = self._load_file()
                record = data["records"].get(binding_id)
                if record is None:
                    return False
                key = resolve_token_store_key()
                self._bind_or_verify_aggregate_key(data, key, initialize=False)
                token, _ = self._decode_token_record(
                    binding_id,
                    record,
                    key,
                    allow_legacy=False,
                )
                confirmed = token == expected
        except Exception:
            confirmed = False
        return confirmed

    def get(self, binding_id: str) -> StoredToken | None:
        """Return the decrypted token for ``binding_id``, or None if absent.

        Returns None when no record exists (no key needed for that). When a
        record DOES exist, the key is required to decrypt it; a missing key
        raises :class:`TokenStoreKeyMissingError` -- there is no plaintext read
        path (fail closed, INV-YSS-4).
        """
        with self._lock, self._aggregate_file_lock():
            data = self._load_file()
            record = data["records"].get(binding_id)
            if record is None:
                return None
            key = resolve_token_store_key()
            changed = self._bind_or_verify_aggregate_key(
                data, key, initialize=True
            )
            if changed:
                self._write_file(data)
                data = self._load_file()
                self._bind_or_verify_aggregate_key(
                    data, key, initialize=False
                )
            token, _ = self._decode_token_record(
                binding_id,
                data["records"][binding_id],
                key,
                allow_legacy=False,
            )
            return token


__all__ = [
    "KEY_ENV_VAR",
    "PATH_ENV_VAR",
    "StoredToken",
    "TokenStoreDurabilityError",
    "TokenStoreKeyMissingError",
    "TokenStoreKeyMismatchError",
    "YouTubeTokenStore",
    "default_token_store_path",
    "resolve_token_store_key",
]
