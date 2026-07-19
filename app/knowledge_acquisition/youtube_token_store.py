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
  ``{ciphertext, nonce}``; no token, code, or client secret is ever written in
  clear. The record index (which binding ids have tokens) is readable without
  the key so upstream can detect "a binding exists" and fail closed; decrypting
  a record's bytes always requires the key.
- A binding-scoped lifecycle lock combines a process-local ``RLock`` with an OS
  file lock so connect, reconnect, refresh, and disconnect can serialize across
  store instances and runtime processes. Lock filenames are SHA-256 digests of
  binding ids, and their private app-local files contain no identifiers or
  credential bytes.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ENV_VAR = "YOUTUBE_TOKEN_STORE_KEY"
PATH_ENV_VAR = "YOUTUBE_TOKEN_STORE_PATH"

_AES_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # standard AES-GCM nonce size
_SCHEMA = "youtube-token-store.v1"
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


class TokenStoreKeyMissingError(RuntimeError):
    """No/invalid encryption key configured -- refuse, never read/write plaintext.

    Upstream (``youtube_oauth``) catches this and degrades the binding to the
    ``auth_key_missing`` reason code (INV-YSS-4); it is never swallowed into a
    silent plaintext path.
    """


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


class YouTubeTokenStore:
    """AES-256-GCM encrypted token store, one JSON file, one record per binding.

    Individual file operations are thread-safe and writes use atomic replace.
    Multi-operation credential lifecycles use :meth:`binding_lifecycle_lock`
    for cross-instance and cross-process serialization.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else default_token_store_path()
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"YouTubeTokenStore(path={str(self._path)!r})"

    @property
    def path(self) -> Path:
        return self._path

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
        thread_lock = _lifecycle_thread_lock(lock_path)

        with thread_lock:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    # --- file helpers (no key required) -------------------------------------

    def _load_file(self) -> dict[str, Any]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"schema": _SCHEMA, "records": {}}
        data = json.loads(raw)
        if not isinstance(data, dict) or "records" not in data:
            raise ValueError(f"corrupt token store file at {self._path}")
        return data

    def _write_file(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)

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
    "PATH_ENV_VAR",
    "StoredToken",
    "TokenStoreKeyMissingError",
    "YouTubeTokenStore",
    "default_token_store_path",
    "resolve_token_store_key",
]
