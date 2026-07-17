"""YSS-01 (#3916): durable per-account YouTube source registry.

Typed registry rows per `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md ::
Source registry`: one durable row per followed collection (inbox/owned/liked/
public playlist, or subscription feed), per account binding. Every later
slice in this capability (YSS-02..11) reads or writes through this module --
it is the one durable substrate for "which collections does this account
follow, with what policy, cursor, and state", so no later slice invents
private persistence or ad-hoc config.

Dual backend, selected the same way existing stores select backends
(``STORE_BACKEND=memory|pg`` override, else resolved from
``DATABASE_URL``/``DB_DSN`` with fail-loud unreachable-Postgres handling --
the KERNEL-03 / I-S4 precedent, mirroring
``app.heimdal._backend.resolve_heimdal_backend`` and
``app.heimdal.cursor_store``). The memory backend exists for ``not_pg`` tests
only and is never selected in a configured runtime (Restart/Durability
Posture, `ESTABLISH_SOURCE_REGISTRY_AND_SETTINGS.md`).

Service-layer integrity rules are enforced IDENTICALLY on both backends (the
memory backend must never be a lesser contract than Postgres):

- unique ``(collection_kind, collection_ref, account_binding_id)`` -- no
  duplicate bindings (``DuplicateBindingError``).
- **exactly one enabled ``inbox_playlist`` per ``account_binding_id``** --
  newly registered inbox_playlist rows always start disabled; the ONLY way to
  activate one is the atomic :meth:`SourceRegistry.set_inbox` swap, which
  disables whichever inbox was previously enabled (if any) and enables the
  target in one atomic operation. This makes "more than one enabled inbox"
  structurally unreachable rather than merely checked.
- authenticated ``inbox_playlist``, ``owned_playlist``, and
  ``liked_videos`` bindings require ``account_binding_id``; only public
  playlists and RSS subscription feeds may be account-less. Every present
  account binding is validated and normalized to its canonical UUID text
  before either backend sees it.
- ``poll_interval_seconds`` validated to ``[60, 604800]`` (contract-wide
  bound; the finer per-kind bounds on the *settings* defaults --
  ``youtubeSync.inboxPollSeconds`` etc. -- are a separate, narrower
  validation owned by ``app.vault.settings_service``).
- Watch Later (``WL``) / Watch History (``HL``) are refused at registration
  with ``reason_code=source_unsupported`` and a legible explanation, checked
  on the raw ``collection_ref`` regardless of the requested
  ``collection_kind`` -- the official Data API does not expose either list;
  this product will not fall back to cookies or scraping.
- ``acquisition_policy`` (mode / extractor_ids / captions / media) is
  validated at write time; unknown keys or out-of-bounds/unknown values are
  refused loudly (``SourceRegistryValidationError``) rather than silently
  applied, while any field the caller omits still resolves to the
  per-``collection_kind`` contract default.
- ``title`` is display-only and rename-safe: :meth:`SourceRegistry.rename`
  changes only ``title`` (+ ``updated_at``); identity (``binding_id``,
  ``collection_kind``, ``collection_ref``, ``account_binding_id``), cursor,
  and policy are untouched.

Cursor discipline, request-queue draining, and scheduling are explicitly OUT
OF SCOPE for this slice (YSS-04/05/06/07) -- this module ships the row shape
(``cursor``, ``last_attempt_at``, ``last_success_at``, ``last_error`` all
present and correctly defaulted) without exposing mutation methods for them;
later slices add those call sites against this same table.
"""

from __future__ import annotations

import json
import math
import os
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from app.db.dsn import resolve_dsn

# --- Contract vocab ---------------------------------------------------------

VALID_COLLECTION_KINDS: frozenset[str] = frozenset(
    {"inbox_playlist", "owned_playlist", "liked_videos", "public_playlist", "subscription_feed"}
)
VALID_DISCOVERY_MODES: frozenset[str] = frozenset({"api_poll", "rss_poll", "backfill_only"})
VALID_PRIORITIES: frozenset[str] = frozenset({"high", "normal"})
VALID_ACQUISITION_MODES: frozenset[str] = frozenset(
    {"discover_only", "candidate_metadata_only", "acquire_transcript", "acquire_if_filter_matches"}
)
VALID_PROVENANCE_ORIGINS: frozenset[str] = frozenset({"user_pick", "takeout_import", "manual_add"})
_PROVENANCE_KEYS: frozenset[str] = frozenset({"origin", "at", "detail"})

_PLAYLIST_SHAPED_KINDS: frozenset[str] = frozenset(
    {"inbox_playlist", "owned_playlist", "liked_videos", "public_playlist"}
)
_ACCOUNT_BOUND_COLLECTION_KINDS: frozenset[str] = frozenset(
    {"inbox_playlist", "owned_playlist", "liked_videos"}
)

# Watch Later / Watch History: unsupported by the official Data API. Checked
# on the raw collection_ref regardless of the requested collection_kind, so a
# caller cannot route around the refusal by mis-declaring the kind.
UNSUPPORTED_COLLECTION_REFS: dict[str, str] = {
    "WL": "Watch Later",
    "HL": "Watch History",
}

MIN_POLL_INTERVAL_SECONDS = 60
MAX_POLL_INTERVAL_SECONDS = 604800  # 7 days

# Per-kind poll_interval_seconds default, matching the youtubeSync.* settings
# defaults (app/vault/settings_service.py) at contract-authoring time. This
# module does not read SettingsService directly (no vault/knowledge_acquisition
# coupling); a caller that wants the live-configured default passes it explicitly.
_KIND_DEFAULT_POLL_INTERVAL_SECONDS: dict[str, int] = {
    "inbox_playlist": 180,
    "owned_playlist": 3600,
    "liked_videos": 3600,
    "public_playlist": 3600,
    "subscription_feed": 21600,
}

_ALLOWED_POLICY_KEYS: frozenset[str] = frozenset({"mode", "policy_version", "extractor_ids", "captions", "media"})
_ALLOWED_MEDIA_KEYS: frozenset[str] = frozenset(
    {"enabled", "max_quality", "format", "storage_binding", "min_free_gb", "retention_days", "checksum"}
)

_TABLE = "acquisition_source_registry"
_NULL_ACCOUNT_SENTINEL = "__none__"
_MIGRATION_HINT = (
    "acquisition_source_registry schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See "
    "app/alembic/versions/bd79f3044759_yss01_acquisition_source_registry.py."
)


# --- Errors ------------------------------------------------------------------


class SourceRegistrySchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the registry table is absent."""


class SourceRegistryValidationError(ValueError):
    """Raised for malformed/out-of-bounds/unknown registry field values.

    Fail-loud: never silently coerced, clamped, or applied. Callers that omit
    a field get the contract default; callers that pass an invalid explicit
    value get this error and no row is created or mutated.
    """


class DuplicateBindingError(ValueError):
    """Raised when (collection_kind, collection_ref, account_binding_id) already exists."""


class SourceUnsupportedError(ValueError):
    """Raised when collection_ref names an unsupported special list (Watch Later / History)."""

    def __init__(self, collection_ref: str) -> None:
        self.collection_ref = collection_ref
        self.reason_code = "source_unsupported"
        name = UNSUPPORTED_COLLECTION_REFS.get(collection_ref, collection_ref)
        message = (
            f"{name} ('{collection_ref}') is not supported: the official YouTube Data API does "
            "not expose this list, and this product will not use cookie/browser-session "
            "scraping or any other unofficial fallback to read it."
        )
        super().__init__(message)


def _normalize_account_binding_id(account_binding_id: str | None) -> str | None:
    """Validate and canonicalize the contract UUID before backend selection."""
    if account_binding_id is None:
        return None
    if not isinstance(account_binding_id, str):
        raise SourceRegistryValidationError("account_binding_id must be a UUID string or None")
    raw = account_binding_id.strip()
    if raw == _NULL_ACCOUNT_SENTINEL:
        raise SourceRegistryValidationError(
            f"account_binding_id value {_NULL_ACCOUNT_SENTINEL!r} is reserved for SQL NULL indexing"
        )
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError) as exc:
        raise SourceRegistryValidationError(
            f"account_binding_id must be a valid UUID, got {account_binding_id!r}"
        ) from exc


# --- Row type ------------------------------------------------------------------


@dataclass(frozen=True)
class SourceBinding:
    """One durable registry row. See `SOURCE_SYNC_CONTRACT.md :: Source registry`."""

    binding_id: str
    account_binding_id: str | None
    collection_kind: str
    collection_ref: str
    title: str
    enabled: bool
    discovery_mode: str
    poll_interval_seconds: int
    priority: str
    cursor: dict[str, Any]
    last_attempt_at: str | None
    last_success_at: str | None
    last_error: dict[str, Any] | None
    acquisition_policy: dict[str, Any]
    provenance: dict[str, Any]
    created_at: str
    updated_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Validation helpers ---------------------------------------------------


def _validate_poll_interval_seconds(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise SourceRegistryValidationError(
            f"poll_interval_seconds must be an int, got {type(value).__name__}: {value!r}"
        )
    if value < MIN_POLL_INTERVAL_SECONDS or value > MAX_POLL_INTERVAL_SECONDS:
        raise SourceRegistryValidationError(
            "poll_interval_seconds must be within "
            f"[{MIN_POLL_INTERVAL_SECONDS}, {MAX_POLL_INTERVAL_SECONDS}], got {value}"
        )
    return value


def _default_media_policy() -> dict[str, Any]:
    # §Media retention policy: acquisition depth ships on; full media archival
    # ships OFF by default and is refused at enforcement elsewhere
    # (media_policy_disabled) while the archival engine is undelivered. This
    # slice only validates the shape.
    return {
        "enabled": False,
        "max_quality": None,
        "format": None,
        "storage_binding": None,
        "min_free_gb": None,
        "retention_days": None,
        "checksum": True,
    }


def _validate_media_policy(media: Any) -> None:
    if not isinstance(media, dict):
        raise SourceRegistryValidationError(f"acquisition_policy.media must be an object, got {media!r}")
    unknown = set(media) - _ALLOWED_MEDIA_KEYS
    if unknown:
        raise SourceRegistryValidationError(f"acquisition_policy.media has unknown keys: {sorted(unknown)}")
    if "enabled" in media and not isinstance(media["enabled"], bool):
        raise SourceRegistryValidationError("acquisition_policy.media.enabled must be a boolean")
    for key in ("max_quality", "format", "storage_binding"):
        if key in media and media[key] is not None and not isinstance(media[key], str):
            raise SourceRegistryValidationError(f"acquisition_policy.media.{key} must be a string or null")
    for key in ("min_free_gb", "retention_days"):
        if key in media and media[key] is not None:
            number = media[key]
            # ``bool`` passes ``isinstance(..., int)`` and NaN/infinity are
            # accepted by memory but rejected by Postgres jsonb. Refuse all
            # three before either backend sees the policy.
            if isinstance(number, bool) or not isinstance(number, int | float) or not math.isfinite(number):
                raise SourceRegistryValidationError(
                    f"acquisition_policy.media.{key} must be a finite number or null"
                )
            # Contract lower bounds (AC6): a negative free-space floor makes
            # the future media guard vacuous, and retention below one day has
            # no lifecycle meaning; ``min_free_gb=0`` legitimately means "no
            # reserved floor" while ``null`` means "unset".
            lower_bound = 0 if key == "min_free_gb" else 1
            if number < lower_bound:
                raise SourceRegistryValidationError(
                    f"acquisition_policy.media.{key} must be >= {lower_bound} or null"
                )
    if "checksum" in media and not isinstance(media["checksum"], bool):
        raise SourceRegistryValidationError("acquisition_policy.media.checksum must be a boolean")


def _default_acquisition_policy(collection_kind: str) -> dict[str, Any]:
    mode = "acquire_transcript" if collection_kind in _PLAYLIST_SHAPED_KINDS else "discover_only"
    return {
        "mode": mode,
        "policy_version": 1,
        "extractor_ids": [],
        "captions": True,
        "media": _default_media_policy(),
    }


def _validate_acquisition_policy_override(override: Any) -> None:
    if not isinstance(override, dict):
        raise SourceRegistryValidationError(f"acquisition_policy must be an object, got {override!r}")
    unknown = set(override) - _ALLOWED_POLICY_KEYS
    if unknown:
        raise SourceRegistryValidationError(f"acquisition_policy has unknown keys: {sorted(unknown)}")
    if "mode" in override and override["mode"] not in VALID_ACQUISITION_MODES:
        raise SourceRegistryValidationError(
            f"acquisition_policy.mode must be one of {sorted(VALID_ACQUISITION_MODES)}, "
            f"got {override['mode']!r}"
        )
    if "policy_version" in override:
        version = override["policy_version"]
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise SourceRegistryValidationError("acquisition_policy.policy_version must be a positive int")
    if "extractor_ids" in override:
        extractor_ids = override["extractor_ids"]
        if not isinstance(extractor_ids, list) or not all(isinstance(x, str) for x in extractor_ids):
            raise SourceRegistryValidationError("acquisition_policy.extractor_ids must be a list of strings")
    if "captions" in override and not isinstance(override["captions"], bool):
        raise SourceRegistryValidationError("acquisition_policy.captions must be a boolean")
    if "media" in override:
        _validate_media_policy(override["media"])


def _build_acquisition_policy(collection_kind: str, override: dict[str, Any] | None) -> dict[str, Any]:
    base = _default_acquisition_policy(collection_kind)
    if override is None:
        return base
    _validate_acquisition_policy_override(override)
    merged = dict(base)
    for key, value in override.items():
        if key == "media":
            continue
        merged[key] = value
    if "media" in override and override["media"] is not None:
        merged_media = dict(base["media"])
        merged_media.update(override["media"])
        merged["media"] = merged_media
    return merged


def _check_portable_string(text: str, path: str) -> None:
    """Reject strings PostgreSQL ``jsonb`` cannot store (NUL, unpaired surrogates).

    ``json.dumps`` and the memory backend both accept these, so without this
    shared check they would surface as raw backend failures on Postgres only,
    breaking the identical memory/PG validation contract.
    """
    if "\x00" in text:
        raise SourceRegistryValidationError(
            f"{path} must not contain NUL (\\u0000): PostgreSQL jsonb cannot store it"
        )
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SourceRegistryValidationError(
            f"{path} must be valid Unicode without unpaired surrogates"
        ) from exc


def _portable_json_copy(value: Any, *, field: str) -> Any:
    """Reject Python-only/non-finite values and return a detached JSON value."""

    def _validate(item: Any, path: str, active: set[int]) -> None:
        if item is None or isinstance(item, bool | int):
            return
        if isinstance(item, str):
            _check_portable_string(item, path)
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise SourceRegistryValidationError(f"{path} must contain only finite JSON numbers")
            return
        if isinstance(item, list):
            identity = id(item)
            if identity in active:
                raise SourceRegistryValidationError(f"{path} must not contain circular JSON values")
            active.add(identity)
            for index, child in enumerate(item):
                _validate(child, f"{path}[{index}]", active)
            active.remove(identity)
            return
        if isinstance(item, dict):
            identity = id(item)
            if identity in active:
                raise SourceRegistryValidationError(f"{path} must not contain circular JSON values")
            active.add(identity)
            for key, child in item.items():
                if not isinstance(key, str):
                    raise SourceRegistryValidationError(f"{path} object keys must be strings")
                _check_portable_string(key, f"{path} object key")
                _validate(child, f"{path}.{key}", active)
            active.remove(identity)
            return
        raise SourceRegistryValidationError(
            f"{path} contains unsupported non-JSON value {item!r}"
        )

    _validate(value, field, set())
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError, OverflowError) as exc:
        raise SourceRegistryValidationError(f"{field} must be portable JSON: {exc}") from exc


def _canonicalize_provenance_at(at: Any) -> str:
    """Parse ``provenance.at`` as RFC 3339 / ISO-8601 and canonicalize to UTC.

    ``at`` is the provenance timestamp: temporal lineage must be orderable and
    auditable, so an arbitrary string is refused, a timestamp without an
    explicit UTC offset is refused (its instant is ambiguous), and every
    accepted value is stored in one canonical form (UTC, ``+00:00``).
    """
    if not isinstance(at, str) or not at.strip():
        raise SourceRegistryValidationError("provenance.at must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(at.strip())
    except ValueError as exc:
        raise SourceRegistryValidationError(
            f"provenance.at must be an RFC 3339 / ISO-8601 timestamp, got {at!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise SourceRegistryValidationError(
            "provenance.at must carry an explicit UTC offset; a naive timestamp is not orderable"
        )
    return parsed.astimezone(timezone.utc).isoformat()


def _build_provenance(now: str, override: dict[str, Any] | None) -> dict[str, Any]:
    if override is None:
        return {"origin": "manual_add", "at": now, "detail": {}}
    if not isinstance(override, dict):
        raise SourceRegistryValidationError(f"provenance must be an object, got {override!r}")
    unknown = set(override) - _PROVENANCE_KEYS
    if unknown:
        raise SourceRegistryValidationError(f"provenance has unsupported keys: {sorted(unknown)}")
    origin = override.get("origin", "manual_add")
    if origin not in VALID_PROVENANCE_ORIGINS:
        raise SourceRegistryValidationError(
            f"provenance.origin must be one of {sorted(VALID_PROVENANCE_ORIGINS)}, got {origin!r}"
        )
    detail = override.get("detail", {})
    if not isinstance(detail, dict):
        raise SourceRegistryValidationError("provenance.detail must be an object")
    at = _canonicalize_provenance_at(override["at"]) if "at" in override else now
    portable = _portable_json_copy(
        {"origin": origin, "at": at, "detail": detail},
        field="provenance",
    )
    if not isinstance(portable, dict):  # pragma: no cover - fixed object above
        raise SourceRegistryValidationError("provenance must be a JSON object")
    return portable


# --- Backend resolution (mirrors app.heimdal._backend.resolve_heimdal_backend,
# scoped locally to this module's own table -- app.stores is a deprecated
# transitional layer, ADR-0013, new code must not extend it) ----------------

_ALLOWED_BACKENDS = {"memory", "pg"}


def _resolve_backend() -> str:
    override = (os.getenv("STORE_BACKEND") or "").strip().lower()
    if override:
        if override not in _ALLOWED_BACKENDS:
            raise RuntimeError(
                f"Store backend '{override}' is not supported for the source registry: set "
                "STORE_BACKEND to 'pg' or 'memory' (explicit opt-in to volatile state), or "
                "unset it to resolve from DATABASE_URL/DB_DSN."
            )
        return override

    dsn = resolve_dsn()
    if not dsn:
        raise RuntimeError(
            "No store backend configured for the source registry: set STORE_BACKEND=memory "
            "explicitly for the volatile in-memory backend, or configure DATABASE_URL/DB_DSN "
            "for Postgres."
        )

    try:
        import psycopg  # noqa: PLC0415

        conn = psycopg.connect(dsn, connect_timeout=1)
        conn.close()
    except Exception as exc:
        raise RuntimeError(
            "Source registry backend resolution failed: Postgres is configured "
            "(DATABASE_URL/DB_DSN) but unreachable. Refusing to fall back to a volatile "
            f"in-memory store. Underlying error: {exc}"
        ) from exc
    return "pg"


# --- Memory backend ----------------------------------------------------------


class _MemorySourceRegistryBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, SourceBinding] = {}

    def insert(self, binding: SourceBinding) -> SourceBinding:
        with self._lock:
            for row in self._rows.values():
                if (
                    row.collection_kind == binding.collection_kind
                    and row.collection_ref == binding.collection_ref
                    and row.account_binding_id == binding.account_binding_id
                ):
                    raise DuplicateBindingError(_duplicate_message(binding))
            stored = _copy_binding(binding)
            self._rows[binding.binding_id] = stored
            return _copy_binding(stored)

    def get(self, binding_id: str) -> SourceBinding | None:
        with self._lock:
            row = self._rows.get(binding_id)
            return _copy_binding(row) if row is not None else None

    def list_all(self) -> tuple[SourceBinding, ...]:
        with self._lock:
            return tuple(_copy_binding(row) for row in self._rows.values())

    def list_for_account(self, account_binding_id: str | None) -> tuple[SourceBinding, ...]:
        with self._lock:
            return tuple(
                _copy_binding(row) for row in self._rows.values() if row.account_binding_id == account_binding_id
            )

    def update_title(self, binding_id: str, title: str) -> SourceBinding:
        with self._lock:
            row = self._rows.get(binding_id)
            if row is None:
                raise KeyError(f"no such binding: {binding_id}")
            updated = replace(row, title=title, updated_at=_now_iso())
            self._rows[binding_id] = updated
            return _copy_binding(updated)

    def set_inbox(self, account_binding_id: str | None, binding_id: str) -> SourceBinding:
        with self._lock:
            target = self._rows.get(binding_id)
            if target is None:
                raise KeyError(f"no such binding: {binding_id}")
            if target.collection_kind != "inbox_playlist":
                raise ValueError(
                    f"binding {binding_id} is not an inbox_playlist (kind={target.collection_kind!r})"
                )
            if target.account_binding_id != account_binding_id:
                raise ValueError("binding does not belong to the given account_binding_id")

            now = _now_iso()
            for other_id, row in list(self._rows.items()):
                if (
                    other_id != binding_id
                    and row.collection_kind == "inbox_playlist"
                    and row.account_binding_id == account_binding_id
                    and row.enabled
                ):
                    self._rows[other_id] = replace(row, enabled=False, updated_at=now)

            updated_target = replace(target, enabled=True, updated_at=now)
            self._rows[binding_id] = updated_target
            return _copy_binding(updated_target)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_MEMORY_REGISTRY = _MemorySourceRegistryBackend()


def reset_memory_source_registry() -> None:
    """Test-only reset hook."""
    _MEMORY_REGISTRY.clear()


def _copy_binding(binding: SourceBinding) -> SourceBinding:
    """Return a binding whose nested JSON does not alias caller or store state.

    Postgres JSONB round-trips already produce fresh Python objects. The
    in-memory test backend must provide the same isolation: a caller may only
    persist cursor/policy/provenance changes through an explicit service write.
    """
    return replace(
        binding,
        cursor=deepcopy(binding.cursor),
        last_error=deepcopy(binding.last_error),
        acquisition_policy=deepcopy(binding.acquisition_policy),
        provenance=deepcopy(binding.provenance),
    )


def _duplicate_message(binding: SourceBinding) -> str:
    return (
        "binding already exists for (collection_kind="
        f"{binding.collection_kind!r}, collection_ref={binding.collection_ref!r}, "
        f"account_binding_id={binding.account_binding_id!r})"
    )


# --- Postgres backend ---------------------------------------------------------

_COLUMNS = (
    "binding_id",
    "account_binding_id",
    "collection_kind",
    "collection_ref",
    "title",
    "enabled",
    "discovery_mode",
    "poll_interval_seconds",
    "priority",
    "cursor",
    "last_attempt_at",
    "last_success_at",
    "last_error",
    "acquisition_policy",
    "provenance",
    "created_at",
    "updated_at",
)
_COLUMNS_SQL = ", ".join(_COLUMNS)


def _pg_connect() -> Any:
    import psycopg  # noqa: PLC0415

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


def _schema_autocreate_enabled() -> bool:
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (_TABLE,))
    row = cur.fetchone()
    oid = row[0] if row else None
    if not oid:
        raise SourceRegistrySchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            binding_id TEXT PRIMARY KEY,
            account_binding_id TEXT,
            collection_kind TEXT NOT NULL,
            collection_ref TEXT NOT NULL,
            title TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT false,
            discovery_mode TEXT NOT NULL,
            poll_interval_seconds INTEGER NOT NULL,
            priority TEXT NOT NULL,
            cursor JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            last_attempt_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            last_error JSONB,
            acquisition_policy JSONB NOT NULL,
            provenance JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT acquisition_source_registry_kind_chk CHECK (
                collection_kind IN (
                    'inbox_playlist', 'owned_playlist', 'liked_videos',
                    'public_playlist', 'subscription_feed'
                )
            ),
            CONSTRAINT acquisition_source_registry_discovery_mode_chk CHECK (
                discovery_mode IN ('api_poll', 'rss_poll', 'backfill_only')
            ),
            CONSTRAINT acquisition_source_registry_priority_chk CHECK (
                priority IN ('high', 'normal')
            ),
            CONSTRAINT acquisition_source_registry_poll_interval_chk CHECK (
                poll_interval_seconds >= 60 AND poll_interval_seconds <= 604800
            ),
            CONSTRAINT acquisition_source_registry_account_binding_chk CHECK (
                collection_kind IN ('public_playlist', 'subscription_feed')
                OR account_binding_id IS NOT NULL
            ),
            CONSTRAINT acquisition_source_registry_account_binding_uuid_chk CHECK (
                account_binding_id IS NULL OR account_binding_id ~
                '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
            )
        )
        """
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_binding_triple_uq "
        f"ON {_TABLE} (collection_kind, collection_ref, "
        f"COALESCE(account_binding_id, '{_NULL_ACCOUNT_SENTINEL}'))"
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_single_inbox_uq "
        f"ON {_TABLE} (COALESCE(account_binding_id, '{_NULL_ACCOUNT_SENTINEL}')) "
        "WHERE collection_kind = 'inbox_playlist' AND enabled = true"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS acquisition_source_registry_account_idx "
        f"ON {_TABLE} (account_binding_id)"
    )


def _row_to_binding(row: tuple[Any, ...]) -> SourceBinding:
    values = dict(zip(_COLUMNS, row))

    def _json_field(name: str) -> Any:
        value = values[name]
        if isinstance(value, str):
            return json.loads(value)
        return value

    def _iso(name: str) -> str | None:
        value = values[name]
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return SourceBinding(
        binding_id=values["binding_id"],
        account_binding_id=values["account_binding_id"],
        collection_kind=values["collection_kind"],
        collection_ref=values["collection_ref"],
        title=values["title"],
        enabled=bool(values["enabled"]),
        discovery_mode=values["discovery_mode"],
        poll_interval_seconds=int(values["poll_interval_seconds"]),
        priority=values["priority"],
        cursor=_json_field("cursor") or {},
        last_attempt_at=_iso("last_attempt_at"),
        last_success_at=_iso("last_success_at"),
        last_error=_json_field("last_error"),
        acquisition_policy=_json_field("acquisition_policy") or {},
        provenance=_json_field("provenance") or {},
        created_at=_iso("created_at") or "",
        updated_at=_iso("updated_at") or "",
    )


class _PgSourceRegistryBackend:
    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def insert(self, binding: SourceBinding) -> SourceBinding:
        from psycopg.errors import UniqueViolation  # noqa: PLC0415

        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    f"""
                    INSERT INTO {_TABLE} (
                        binding_id, account_binding_id, collection_kind, collection_ref, title,
                        enabled, discovery_mode, poll_interval_seconds, priority, cursor,
                        last_attempt_at, last_success_at, last_error, acquisition_policy,
                        provenance, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s::jsonb,
                        %s::timestamptz, %s::timestamptz, %s::jsonb, %s::jsonb,
                        %s::jsonb, %s::timestamptz, %s::timestamptz
                    )
                    """,
                    (
                        binding.binding_id,
                        binding.account_binding_id,
                        binding.collection_kind,
                        binding.collection_ref,
                        binding.title,
                        binding.enabled,
                        binding.discovery_mode,
                        binding.poll_interval_seconds,
                        binding.priority,
                        json.dumps(binding.cursor),
                        binding.last_attempt_at,
                        binding.last_success_at,
                        json.dumps(binding.last_error) if binding.last_error is not None else None,
                        json.dumps(binding.acquisition_policy),
                        json.dumps(binding.provenance),
                        binding.created_at,
                        binding.updated_at,
                    ),
                )
            except UniqueViolation as exc:
                raise DuplicateBindingError(_duplicate_message(binding)) from exc
            return binding
        finally:
            conn.close()

    def get(self, binding_id: str) -> SourceBinding | None:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT {_COLUMNS_SQL} FROM {_TABLE} WHERE binding_id = %s", (binding_id,))
            row = cur.fetchone()
            return _row_to_binding(tuple(row)) if row else None
        finally:
            conn.close()

    def list_all(self) -> tuple[SourceBinding, ...]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT {_COLUMNS_SQL} FROM {_TABLE} ORDER BY created_at")
            rows = cur.fetchall()
            return tuple(_row_to_binding(tuple(row)) for row in rows)
        finally:
            conn.close()

    def list_for_account(self, account_binding_id: str | None) -> tuple[SourceBinding, ...]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            if account_binding_id is None:
                cur.execute(
                    f"SELECT {_COLUMNS_SQL} FROM {_TABLE} WHERE account_binding_id IS NULL "
                    "ORDER BY created_at"
                )
            else:
                cur.execute(
                    f"SELECT {_COLUMNS_SQL} FROM {_TABLE} WHERE account_binding_id = %s "
                    "ORDER BY created_at",
                    (account_binding_id,),
                )
            rows = cur.fetchall()
            return tuple(_row_to_binding(tuple(row)) for row in rows)
        finally:
            conn.close()

    def update_title(self, binding_id: str, title: str) -> SourceBinding:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            now = _now_iso()
            cur = conn.cursor()
            cur.execute(
                f"UPDATE {_TABLE} SET title = %s, updated_at = %s::timestamptz WHERE binding_id = %s",
                (title, now, binding_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"no such binding: {binding_id}")
        finally:
            conn.close()
        result = self.get(binding_id)
        assert result is not None  # just wrote it
        return result

    def set_inbox(self, account_binding_id: str | None, binding_id: str) -> SourceBinding:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT collection_kind, account_binding_id FROM {_TABLE} WHERE binding_id = %s",
                (binding_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"no such binding: {binding_id}")
            kind, acct = row[0], row[1]
            if kind != "inbox_playlist":
                raise ValueError(f"binding {binding_id} is not an inbox_playlist (kind={kind!r})")
            if acct != account_binding_id:
                raise ValueError("binding does not belong to the given account_binding_id")

            now = _now_iso()
            # Two statements in one explicit transaction (disable-others, then
            # enable-target): with the partial unique index on (account,
            # enabled=true, kind='inbox_playlist'), this ordering never has more
            # than one row enabled at once, so the index is never transiently
            # violated -- unlike a single CASE-based UPDATE, whose intra-statement
            # row-processing order against a unique index is not something to
            # depend on.
            conn.autocommit = False
            try:
                cur.execute(
                    f"""
                    UPDATE {_TABLE}
                    SET enabled = false, updated_at = %s::timestamptz
                    WHERE collection_kind = 'inbox_playlist'
                      AND account_binding_id IS NOT DISTINCT FROM %s
                      AND binding_id != %s
                      AND enabled = true
                    """,
                    (now, account_binding_id, binding_id),
                )
                cur.execute(
                    f"UPDATE {_TABLE} SET enabled = true, updated_at = %s::timestamptz WHERE binding_id = %s",
                    (now, binding_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit = True
        finally:
            conn.close()
        result = self.get(binding_id)
        assert result is not None  # just wrote it
        return result


# --- Service layer -------------------------------------------------------


class SourceRegistry:
    """Service-layer facade over a memory or Postgres backend.

    See the module docstring for the integrity rules enforced here identically
    across both backends.
    """

    def __init__(self, backend: _MemorySourceRegistryBackend | _PgSourceRegistryBackend) -> None:
        self._backend = backend

    @classmethod
    def for_runtime(cls) -> "SourceRegistry":
        if _resolve_backend() == "pg":
            return cls(_PgSourceRegistryBackend())
        return cls(_MEMORY_REGISTRY)

    def register(
        self,
        *,
        collection_kind: str,
        collection_ref: str,
        title: str,
        account_binding_id: str | None = None,
        discovery_mode: str | None = None,
        poll_interval_seconds: int | None = None,
        priority: str | None = None,
        acquisition_policy: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> SourceBinding:
        """Register a new followed collection. Raises, never silently applies:

        - :class:`SourceUnsupportedError` for Watch Later / Watch History.
        - :class:`SourceRegistryValidationError` for an unknown
          ``collection_kind``/``discovery_mode``/``priority``, an
          out-of-bounds ``poll_interval_seconds``, or a malformed/unknown
          ``acquisition_policy``/``provenance``.
        - :class:`DuplicateBindingError` for an existing
          ``(collection_kind, collection_ref, account_binding_id)`` triple.

        ``inbox_playlist`` rows always start **disabled**; call
        :meth:`set_inbox` to activate one (atomic swap with any previously
        active inbox for the same account).
        """
        if not isinstance(collection_ref, str) or not collection_ref.strip():
            raise SourceRegistryValidationError("collection_ref must be a non-empty string")
        if collection_ref in UNSUPPORTED_COLLECTION_REFS:
            raise SourceUnsupportedError(collection_ref)
        if collection_kind not in VALID_COLLECTION_KINDS:
            raise SourceRegistryValidationError(
                f"collection_kind must be one of {sorted(VALID_COLLECTION_KINDS)}, got {collection_kind!r}"
            )
        resolved_account_binding_id = _normalize_account_binding_id(account_binding_id)
        if collection_kind in _ACCOUNT_BOUND_COLLECTION_KINDS and resolved_account_binding_id is None:
            raise SourceRegistryValidationError(
                f"account_binding_id is required for authenticated collection_kind {collection_kind!r}"
            )
        if not isinstance(title, str) or not title.strip():
            raise SourceRegistryValidationError("title must be a non-empty string")

        resolved_interval = (
            _KIND_DEFAULT_POLL_INTERVAL_SECONDS[collection_kind]
            if poll_interval_seconds is None
            else _validate_poll_interval_seconds(poll_interval_seconds)
        )

        resolved_discovery_mode = discovery_mode
        if resolved_discovery_mode is None:
            resolved_discovery_mode = "rss_poll" if collection_kind == "subscription_feed" else "api_poll"
        elif resolved_discovery_mode not in VALID_DISCOVERY_MODES:
            raise SourceRegistryValidationError(
                f"discovery_mode must be one of {sorted(VALID_DISCOVERY_MODES)}, got {resolved_discovery_mode!r}"
            )

        resolved_priority = priority
        if resolved_priority is None:
            resolved_priority = "high" if collection_kind == "inbox_playlist" else "normal"
        elif resolved_priority not in VALID_PRIORITIES:
            raise SourceRegistryValidationError(
                f"priority must be one of {sorted(VALID_PRIORITIES)}, got {resolved_priority!r}"
            )

        resolved_policy = _build_acquisition_policy(collection_kind, acquisition_policy)

        now = _now_iso()
        resolved_provenance = _build_provenance(now, provenance)

        binding = SourceBinding(
            binding_id=str(uuid.uuid4()),
            account_binding_id=resolved_account_binding_id,
            collection_kind=collection_kind,
            collection_ref=collection_ref,
            title=title,
            enabled=(collection_kind != "inbox_playlist"),
            discovery_mode=resolved_discovery_mode,
            poll_interval_seconds=resolved_interval,
            priority=resolved_priority,
            cursor={},
            last_attempt_at=None,
            last_success_at=None,
            last_error=None,
            acquisition_policy=resolved_policy,
            provenance=resolved_provenance,
            created_at=now,
            updated_at=now,
        )
        return self._backend.insert(binding)

    def set_inbox(self, account_binding_id: str | None, binding_id: str) -> SourceBinding:
        """Atomically make ``binding_id`` the one enabled inbox for ``account_binding_id``.

        Disables whichever ``inbox_playlist`` row was previously enabled for
        this account (if any) and enables the target, as a single atomic
        operation -- a second enabled inbox is structurally impossible.
        """
        return self._backend.set_inbox(_normalize_account_binding_id(account_binding_id), binding_id)

    def rename(self, binding_id: str, title: str) -> SourceBinding:
        """Change only ``title``; identity, cursor, and policy are untouched."""
        if not isinstance(title, str) or not title.strip():
            raise SourceRegistryValidationError("title must be a non-empty string")
        return self._backend.update_title(binding_id, title)

    def get(self, binding_id: str) -> SourceBinding | None:
        return self._backend.get(binding_id)

    def list_all(self) -> tuple[SourceBinding, ...]:
        return self._backend.list_all()

    def list_for_account(self, account_binding_id: str | None) -> tuple[SourceBinding, ...]:
        return self._backend.list_for_account(_normalize_account_binding_id(account_binding_id))


__all__ = [
    "DuplicateBindingError",
    "MAX_POLL_INTERVAL_SECONDS",
    "MIN_POLL_INTERVAL_SECONDS",
    "SourceBinding",
    "SourceRegistry",
    "SourceRegistrySchemaMissingError",
    "SourceRegistryValidationError",
    "SourceUnsupportedError",
    "UNSUPPORTED_COLLECTION_REFS",
    "VALID_ACQUISITION_MODES",
    "VALID_COLLECTION_KINDS",
    "VALID_DISCOVERY_MODES",
    "VALID_PRIORITIES",
    "VALID_PROVENANCE_ORIGINS",
    "reset_memory_source_registry",
]
