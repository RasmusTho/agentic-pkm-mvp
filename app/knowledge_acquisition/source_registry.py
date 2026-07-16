"""YouTube source-sync source registry (YSS-01, #3916).

One durable row per followed collection, per account binding, in the channel
database — the substrate every later YSS slice reads or writes ("which
collections does this account follow, with what policy, cursor, and state").
Normative shape: ``docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md :: Source
registry`` (field names) and ``:: Acquisition policy`` (policy JSON).

Integrity rules are enforced in the service layer so the memory backend
behaves identically to Postgres, plus DB constraints where expressible
(unique binding triple, single enabled inbox, interval bounds, WL/HL
refusal):

- unique ``(collection_kind, collection_ref, account_binding_id)``;
- exactly one **enabled** ``inbox_playlist`` per ``account_binding_id`` —
  "change inbox" is an atomic swap (:meth:`SourceRegistry.set_inbox`), never
  a second enabled inbox;
- ``poll_interval_seconds`` validated to ``[60, 604800]`` (``None`` means
  "use the kind default from settings" — the registry stores only per-source
  overrides, so a later settings change keeps applying to non-overridden
  sources);
- Watch Later (``WL``) and Watch History (``HL``) are refused at
  registration with ``reason_code=source_unsupported`` — the official Data
  API does not expose them and no cookie/scraping fallback exists
  (INV-YSS-9 relative: the *title* is display-only; identity is the
  collection id + account binding).

Backend selection mirrors the Heimdal store convention
(``app/heimdal/_backend.py``): ``STORE_BACKEND=memory`` (or ``pg``) is an
explicit override, otherwise a resolvable Postgres DSN selects the real
``acquisition_source_registry`` table. Fail-loud (KERNEL-03 / I-S4): a
configured-but-unreachable Postgres raises rather than degrading to the
volatile memory backend, and the production path never auto-creates schema
(``STORE_SCHEMA_AUTOCREATE`` is the explicit test-fixture opt-in, KERNEL-04/
KERNEL-05 precedent).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from app.db.dsn import resolve_dsn

_TABLE = "acquisition_source_registry"

_MIGRATION_HINT = (
    "acquisition_source_registry schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/ (YSS-01 source registry migration)."
)

COLLECTION_KINDS = (
    "inbox_playlist",
    "owned_playlist",
    "liked_videos",
    "public_playlist",
    "subscription_feed",
)
DISCOVERY_MODES = ("api_poll", "rss_poll", "backfill_only")
PRIORITIES = ("high", "normal")
ACQUISITION_POLICY_MODES = (
    "discover_only",
    "candidate_metadata_only",
    "acquire_transcript",
    "acquire_if_filter_matches",
)
PROVENANCE_ORIGINS = ("user_pick", "takeout_import", "manual_add")

POLL_INTERVAL_MIN_SECONDS = 60
POLL_INTERVAL_MAX_SECONDS = 604800

_PLAYLIST_SHAPED_KINDS = frozenset(
    {"inbox_playlist", "owned_playlist", "liked_videos", "public_playlist"}
)

# Special YouTube list ids the official Data API does not expose. Refused at
# registration; the standard flow MUST NOT attempt cookies, scraping, or
# browser sessions for them (owner decision record 2026-07-16).
UNSUPPORTED_COLLECTION_REFS: dict[str, str] = {
    "WL": "Watch Later",
    "HL": "Watch History",
}

_KIND_DEFAULT_DISCOVERY_MODE: dict[str, str] = {
    "inbox_playlist": "api_poll",
    "owned_playlist": "api_poll",
    "liked_videos": "api_poll",
    "public_playlist": "api_poll",
    "subscription_feed": "rss_poll",
}

_MEDIA_POLICY_FIELD_TYPES: dict[str, type | tuple[type, ...]] = {
    "enabled": bool,
    "max_quality": str,
    "format": str,
    "storage_binding": str,
    "min_free_gb": (int, float),
    "retention_days": int,
    "checksum": bool,
}


class SourceRegistryError(RuntimeError):
    """Base class for source-registry failures."""


class SourceRegistrySchemaMissingError(SourceRegistryError):
    """Raised when the Postgres backend is selected but the table is absent."""


class RegistryValidationError(SourceRegistryError):
    """Raised when a registry write carries an invalid value.

    Loud by contract: invalid values are refused with a legible reason,
    never silently applied or silently defaulted.
    """

    def __init__(self, message: str, *, reason_code: str = "registry_validation") -> None:
        super().__init__(message)
        self.reason_code = reason_code


class SourceUnsupportedError(RegistryValidationError):
    """Raised for Watch Later / Watch History registration attempts."""

    def __init__(self, message: str) -> None:
        super().__init__(message, reason_code="source_unsupported")


class DuplicateBindingError(SourceRegistryError):
    """Raised when the unique binding triple already exists."""


class UnknownBindingError(LookupError):
    """Raised when a binding_id does not exist in the registry."""


@dataclass(frozen=True)
class SourceBinding:
    """One durable registry row (contract field set, normative names)."""

    binding_id: str
    account_binding_id: str | None
    collection_kind: str
    collection_ref: str
    title: str
    enabled: bool
    discovery_mode: str
    poll_interval_seconds: int | None
    priority: str
    cursor: dict[str, Any]
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: dict[str, Any] | None
    acquisition_policy: dict[str, Any]
    provenance: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_acquisition_policy(collection_kind: str) -> dict[str, Any]:
    """Kind-default policy per the contract's §Acquisition policy defaults."""
    mode = "acquire_transcript" if collection_kind in _PLAYLIST_SHAPED_KINDS else "discover_only"
    return {
        "mode": mode,
        "extractor_ids": [],
        "captions": True,
        "media": {"enabled": False},
        "policy_version": 1,
    }


def _validate_collection_kind(collection_kind: str) -> None:
    if collection_kind not in COLLECTION_KINDS:
        allowed = ", ".join(COLLECTION_KINDS)
        raise RegistryValidationError(
            f"unknown collection_kind {collection_kind!r}; must be one of: {allowed}"
        )


def _validate_collection_ref(collection_ref: str) -> None:
    if not isinstance(collection_ref, str) or not collection_ref.strip():
        raise RegistryValidationError("collection_ref must be a non-empty source-native id")
    unsupported = UNSUPPORTED_COLLECTION_REFS.get(collection_ref.strip())
    if unsupported:
        raise SourceUnsupportedError(
            f"{unsupported} ({collection_ref.strip()!r}) cannot be synced: the official "
            "YouTube Data API does not expose it, and this capability never uses "
            "cookies, scraping, or browser sessions to reach it. Pick one of your own "
            "playlists (or Liked Videos) instead."
        )


def _validate_poll_interval(value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise RegistryValidationError("poll_interval_seconds must be an integer number of seconds")
    if not POLL_INTERVAL_MIN_SECONDS <= value <= POLL_INTERVAL_MAX_SECONDS:
        raise RegistryValidationError(
            f"poll_interval_seconds must be within [{POLL_INTERVAL_MIN_SECONDS}, "
            f"{POLL_INTERVAL_MAX_SECONDS}], got {value}"
        )


def validate_acquisition_policy(
    policy: dict[str, Any] | None, *, collection_kind: str
) -> dict[str, Any]:
    """Validate and normalize an acquisition-policy JSON object.

    ``None`` yields the kind default. Partial objects are completed with the
    kind defaults for absent keys; present-but-invalid values are refused
    loudly (never silently applied, never silently replaced).
    """
    normalized = default_acquisition_policy(collection_kind)
    if policy is None:
        return normalized
    if not isinstance(policy, dict):
        raise RegistryValidationError("acquisition_policy must be a JSON object")

    unknown = set(policy) - {"mode", "extractor_ids", "captions", "media", "policy_version"}
    if unknown:
        raise RegistryValidationError(
            f"acquisition_policy has unknown keys: {', '.join(sorted(unknown))}"
        )
    if "mode" in policy:
        mode = policy["mode"]
        if mode not in ACQUISITION_POLICY_MODES:
            allowed = ", ".join(ACQUISITION_POLICY_MODES)
            raise RegistryValidationError(
                f"acquisition_policy.mode {mode!r} is unknown; must be one of: {allowed}"
            )
        normalized["mode"] = mode
    if "extractor_ids" in policy:
        extractor_ids = policy["extractor_ids"]
        if not isinstance(extractor_ids, list) or not all(
            isinstance(item, str) and item for item in extractor_ids
        ):
            raise RegistryValidationError(
                "acquisition_policy.extractor_ids must be a list of extractor id strings"
            )
        normalized["extractor_ids"] = list(extractor_ids)
    if "captions" in policy:
        captions = policy["captions"]
        if not isinstance(captions, bool):
            raise RegistryValidationError("acquisition_policy.captions must be a boolean")
        normalized["captions"] = captions
    if "media" in policy:
        media = policy["media"]
        if not isinstance(media, dict):
            raise RegistryValidationError("acquisition_policy.media must be a JSON object")
        unknown_media = set(media) - set(_MEDIA_POLICY_FIELD_TYPES)
        if unknown_media:
            raise RegistryValidationError(
                f"acquisition_policy.media has unknown keys: {', '.join(sorted(unknown_media))}"
            )
        for field_name, expected in _MEDIA_POLICY_FIELD_TYPES.items():
            if field_name not in media:
                continue
            value = media[field_name]
            if isinstance(value, bool) and expected is not bool and bool not in (
                expected if isinstance(expected, tuple) else (expected,)
            ):
                raise RegistryValidationError(
                    f"acquisition_policy.media.{field_name} has the wrong type"
                )
            if not isinstance(value, expected):
                raise RegistryValidationError(
                    f"acquisition_policy.media.{field_name} has the wrong type"
                )
        normalized_media: dict[str, Any] = {"enabled": bool(media.get("enabled", False))}
        for field_name in _MEDIA_POLICY_FIELD_TYPES:
            if field_name in media:
                normalized_media[field_name] = media[field_name]
        normalized["media"] = normalized_media
    if "policy_version" in policy:
        version = policy["policy_version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise RegistryValidationError(
                "acquisition_policy.policy_version must be a positive integer"
            )
        normalized["policy_version"] = version
    return normalized


# --- backend resolution (Heimdal `_backend.py` convention, scoped to KA) ---

_ALLOWED_BACKENDS = {"memory", "pg"}


def _resolve_backend_name() -> str:
    override = (os.getenv("STORE_BACKEND") or "").strip().lower()
    if override:
        if override not in _ALLOWED_BACKENDS:
            raise RuntimeError(
                f"Store backend '{override}' is not supported: set STORE_BACKEND to "
                "'pg' or 'memory' (explicit opt-in to volatile state), or unset it to "
                "resolve from DATABASE_URL/DB_DSN."
            )
        return override

    dsn = resolve_dsn()
    if not dsn:
        raise RuntimeError(
            "No store backend configured: set STORE_BACKEND=memory explicitly for the "
            "volatile in-memory backend, or configure DATABASE_URL/DB_DSN for Postgres."
        )

    try:
        import psycopg  # noqa: PLC0415

        conn = psycopg.connect(dsn, connect_timeout=1)
        conn.close()
    except Exception as exc:
        raise RuntimeError(
            "Store backend resolution failed: Postgres is configured "
            "(DATABASE_URL/DB_DSN) but unreachable. Refusing to fall back to a "
            f"volatile in-memory store. Underlying error: {exc}"
        ) from exc
    return "pg"


class _MemorySourceRegistryStore:
    """In-process backend. Test/dev only; never selected in a configured runtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, SourceBinding] = {}

    def insert(self, row: SourceBinding) -> None:
        with self._lock:
            self._assert_unique_triple(row)
            if row.collection_kind == "inbox_playlist" and row.enabled:
                self._assert_no_enabled_inbox(row.account_binding_id)
            self._rows[row.binding_id] = row

    def get(self, binding_id: str) -> SourceBinding | None:
        with self._lock:
            return self._rows.get(binding_id)

    def list(
        self,
        *,
        account_binding_id: str | None = None,
        collection_kind: str | None = None,
        enabled: bool | None = None,
    ) -> list[SourceBinding]:
        with self._lock:
            rows = list(self._rows.values())
        if account_binding_id is not None:
            rows = [r for r in rows if r.account_binding_id == account_binding_id]
        if collection_kind is not None:
            rows = [r for r in rows if r.collection_kind == collection_kind]
        if enabled is not None:
            rows = [r for r in rows if r.enabled == enabled]
        rows.sort(key=lambda r: (r.created_at, r.binding_id))
        return rows

    def update(self, binding_id: str, **changes: Any) -> SourceBinding | None:
        with self._lock:
            current = self._rows.get(binding_id)
            if current is None:
                return None
            updated = replace(current, updated_at=_utcnow(), **changes)
            if (
                updated.collection_kind == "inbox_playlist"
                and updated.enabled
                and not current.enabled
            ):
                self._assert_no_enabled_inbox(updated.account_binding_id)
            self._rows[binding_id] = updated
            return updated

    def swap_inbox(self, account_binding_id: str, binding_id: str) -> SourceBinding | None:
        with self._lock:
            target = self._rows.get(binding_id)
            if target is None:
                return None
            now = _utcnow()
            for row in list(self._rows.values()):
                if (
                    row.account_binding_id == account_binding_id
                    and row.collection_kind == "inbox_playlist"
                    and row.enabled
                    and row.binding_id != binding_id
                ):
                    self._rows[row.binding_id] = replace(row, enabled=False, updated_at=now)
            updated = replace(target, enabled=True, updated_at=now)
            self._rows[binding_id] = updated
            return updated

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()

    def _assert_unique_triple(self, row: SourceBinding) -> None:
        for existing in self._rows.values():
            if (
                existing.collection_kind == row.collection_kind
                and existing.collection_ref == row.collection_ref
                and existing.account_binding_id == row.account_binding_id
            ):
                raise DuplicateBindingError(
                    f"binding already exists for ({row.collection_kind}, "
                    f"{row.collection_ref}, {row.account_binding_id})"
                )

    def _assert_no_enabled_inbox(self, account_binding_id: str | None) -> None:
        for existing in self._rows.values():
            if (
                existing.account_binding_id == account_binding_id
                and existing.collection_kind == "inbox_playlist"
                and existing.enabled
            ):
                raise RegistryValidationError(
                    "an enabled inbox playlist already exists for this account binding; "
                    "use set_inbox for an atomic swap instead of enabling a second inbox"
                )


_MEMORY_STORE = _MemorySourceRegistryStore()


def reset_memory_source_registry() -> None:
    """Test-only reset hook, mirroring the other memory-backend reset helpers."""
    _MEMORY_STORE.clear()


def _pg_connect() -> Any:
    import psycopg  # noqa: PLC0415

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


def _schema_autocreate_enabled() -> bool:
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


_ROW_COLUMNS = (
    "binding_id, account_binding_id, collection_kind, collection_ref, title, enabled, "
    "discovery_mode, poll_interval_seconds, priority, cursor, last_attempt_at, "
    "last_success_at, last_error, acquisition_policy, provenance, created_at, updated_at"
)

# DDL kept in lockstep with the YSS-01 Alembic migration (the migration is the
# production owner; this autocreate path is the KERNEL-04 test-fixture opt-in).
_SCHEMA_DDL: tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS {_TABLE} (
        binding_id uuid PRIMARY KEY,
        account_binding_id uuid,
        collection_kind text NOT NULL CHECK (collection_kind IN (
            'inbox_playlist', 'owned_playlist', 'liked_videos',
            'public_playlist', 'subscription_feed')),
        collection_ref text NOT NULL CHECK (collection_ref NOT IN ('WL', 'HL')),
        title text NOT NULL DEFAULT '',
        enabled boolean NOT NULL DEFAULT true,
        discovery_mode text NOT NULL CHECK (discovery_mode IN (
            'api_poll', 'rss_poll', 'backfill_only')),
        poll_interval_seconds integer CHECK (
            poll_interval_seconds IS NULL
            OR (poll_interval_seconds >= 60 AND poll_interval_seconds <= 604800)),
        priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('high', 'normal')),
        cursor jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        last_attempt_at timestamptz,
        last_success_at timestamptz,
        last_error jsonb,
        acquisition_policy jsonb NOT NULL,
        provenance jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    f"""
    CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_triple_uq
        ON {_TABLE} (collection_kind, collection_ref, account_binding_id)
        WHERE account_binding_id IS NOT NULL
    """,
    f"""
    CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_triple_noacct_uq
        ON {_TABLE} (collection_kind, collection_ref)
        WHERE account_binding_id IS NULL
    """,
    f"""
    CREATE UNIQUE INDEX IF NOT EXISTS acquisition_source_registry_single_inbox_uq
        ON {_TABLE} (account_binding_id)
        WHERE collection_kind = 'inbox_playlist' AND enabled AND account_binding_id IS NOT NULL
    """,
    f"""
    CREATE INDEX IF NOT EXISTS acquisition_source_registry_account_idx
        ON {_TABLE} (account_binding_id)
    """,
)


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
    for statement in _SCHEMA_DDL:
        cur.execute(statement)


def _row_from_record(record: tuple[Any, ...]) -> SourceBinding:
    (
        binding_id,
        account_binding_id,
        collection_kind,
        collection_ref,
        title,
        enabled,
        discovery_mode,
        poll_interval_seconds,
        priority,
        cursor,
        last_attempt_at,
        last_success_at,
        last_error,
        acquisition_policy,
        provenance,
        created_at,
        updated_at,
    ) = record
    return SourceBinding(
        binding_id=str(binding_id),
        account_binding_id=str(account_binding_id) if account_binding_id is not None else None,
        collection_kind=str(collection_kind),
        collection_ref=str(collection_ref),
        title=str(title),
        enabled=bool(enabled),
        discovery_mode=str(discovery_mode),
        poll_interval_seconds=int(poll_interval_seconds) if poll_interval_seconds is not None else None,
        priority=str(priority),
        cursor=cursor if isinstance(cursor, dict) else json.loads(cursor),
        last_attempt_at=last_attempt_at,
        last_success_at=last_success_at,
        last_error=(
            last_error
            if isinstance(last_error, dict) or last_error is None
            else json.loads(last_error)
        ),
        acquisition_policy=(
            acquisition_policy
            if isinstance(acquisition_policy, dict)
            else json.loads(acquisition_policy)
        ),
        provenance=provenance if isinstance(provenance, dict) else json.loads(provenance),
        created_at=created_at,
        updated_at=updated_at,
    )


class _PgSourceRegistryStore:
    """Postgres backend; constraints mirror the service-layer integrity rules."""

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def insert(self, row: SourceBinding) -> None:
        import psycopg  # noqa: PLC0415

        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    f"""
                    INSERT INTO {_TABLE} ({_ROW_COLUMNS})
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb,
                            %s::jsonb, %s::jsonb, %s, %s)
                    """,
                    (
                        row.binding_id,
                        row.account_binding_id,
                        row.collection_kind,
                        row.collection_ref,
                        row.title,
                        row.enabled,
                        row.discovery_mode,
                        row.poll_interval_seconds,
                        row.priority,
                        json.dumps(row.cursor),
                        row.last_attempt_at,
                        row.last_success_at,
                        json.dumps(row.last_error) if row.last_error is not None else None,
                        json.dumps(row.acquisition_policy),
                        json.dumps(row.provenance),
                        row.created_at,
                        row.updated_at,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                if "single_inbox" in str(exc):
                    raise RegistryValidationError(
                        "an enabled inbox playlist already exists for this account binding; "
                        "use set_inbox for an atomic swap instead of enabling a second inbox"
                    ) from exc
                raise DuplicateBindingError(
                    f"binding already exists for ({row.collection_kind}, "
                    f"{row.collection_ref}, {row.account_binding_id})"
                ) from exc
        finally:
            conn.close()

    def get(self, binding_id: str) -> SourceBinding | None:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT {_ROW_COLUMNS} FROM {_TABLE} WHERE binding_id = %s",
                (binding_id,),
            )
            record = cur.fetchone()
            return _row_from_record(record) if record else None
        finally:
            conn.close()

    def list(
        self,
        *,
        account_binding_id: str | None = None,
        collection_kind: str | None = None,
        enabled: bool | None = None,
    ) -> list[SourceBinding]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            clauses: list[str] = []
            params: list[Any] = []
            if account_binding_id is not None:
                clauses.append("account_binding_id = %s")
                params.append(account_binding_id)
            if collection_kind is not None:
                clauses.append("collection_kind = %s")
                params.append(collection_kind)
            if enabled is not None:
                clauses.append("enabled = %s")
                params.append(enabled)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            cur = conn.cursor()
            cur.execute(
                f"SELECT {_ROW_COLUMNS} FROM {_TABLE}{where} ORDER BY created_at, binding_id",
                tuple(params),
            )
            return [_row_from_record(record) for record in cur.fetchall()]
        finally:
            conn.close()

    def update(self, binding_id: str, **changes: Any) -> SourceBinding | None:
        import psycopg  # noqa: PLC0415

        json_fields = {"cursor", "last_error", "acquisition_policy", "provenance"}
        assignments = ["updated_at = %s"]
        params: list[Any] = [_utcnow()]
        for field_name, value in changes.items():
            if field_name in json_fields:
                assignments.append(f"{field_name} = %s::jsonb")
                params.append(json.dumps(value) if value is not None else None)
            else:
                assignments.append(f"{field_name} = %s")
                params.append(value)
        params.append(binding_id)
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    f"UPDATE {_TABLE} SET {', '.join(assignments)} WHERE binding_id = %s "
                    f"RETURNING {_ROW_COLUMNS}",
                    tuple(params),
                )
            except psycopg.errors.UniqueViolation as exc:
                if "single_inbox" in str(exc):
                    raise RegistryValidationError(
                        "an enabled inbox playlist already exists for this account binding; "
                        "use set_inbox for an atomic swap instead of enabling a second inbox"
                    ) from exc
                raise
            record = cur.fetchone()
            return _row_from_record(record) if record else None
        finally:
            conn.close()

    def swap_inbox(self, account_binding_id: str, binding_id: str) -> SourceBinding | None:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            with conn.transaction():
                cur = conn.cursor()
                # Lock and verify the target before mutating anything, so an
                # unknown target returns None with zero rows changed instead
                # of committing a half-swap.
                cur.execute(
                    f"SELECT binding_id FROM {_TABLE} WHERE binding_id = %s FOR UPDATE",
                    (binding_id,),
                )
                if cur.fetchone() is None:
                    return None
                cur.execute(
                    f"""
                    UPDATE {_TABLE} SET enabled = false, updated_at = %s
                    WHERE account_binding_id = %s AND collection_kind = 'inbox_playlist'
                          AND enabled AND binding_id <> %s
                    """,
                    (_utcnow(), account_binding_id, binding_id),
                )
                cur.execute(
                    f"UPDATE {_TABLE} SET enabled = true, updated_at = %s "
                    f"WHERE binding_id = %s RETURNING {_ROW_COLUMNS}",
                    (_utcnow(), binding_id),
                )
                record = cur.fetchone()
                return _row_from_record(record) if record else None
        finally:
            conn.close()


class SourceRegistry:
    """Service layer over the registry store; integrity rules live here so the
    memory backend behaves identically to Postgres."""

    def __init__(self, store: Any) -> None:
        self._store = store

    @classmethod
    def for_runtime(cls) -> "SourceRegistry":
        if _resolve_backend_name() == "pg":
            return cls(_PgSourceRegistryStore())
        return cls(_MEMORY_STORE)

    def register(
        self,
        *,
        collection_kind: str,
        collection_ref: str,
        account_binding_id: str | None = None,
        title: str = "",
        enabled: bool = True,
        discovery_mode: str | None = None,
        poll_interval_seconds: int | None = None,
        priority: str | None = None,
        acquisition_policy: dict[str, Any] | None = None,
        provenance_origin: str = "manual_add",
        provenance_detail: str | None = None,
    ) -> SourceBinding:
        _validate_collection_kind(collection_kind)
        _validate_collection_ref(collection_ref)
        _validate_poll_interval(poll_interval_seconds)
        if collection_kind == "inbox_playlist" and account_binding_id is None:
            raise RegistryValidationError(
                "an inbox playlist requires an account binding (the single-enabled-inbox "
                "rule is scoped per account_binding_id)"
            )
        if discovery_mode is None:
            discovery_mode = _KIND_DEFAULT_DISCOVERY_MODE[collection_kind]
        elif discovery_mode not in DISCOVERY_MODES:
            allowed = ", ".join(DISCOVERY_MODES)
            raise RegistryValidationError(
                f"unknown discovery_mode {discovery_mode!r}; must be one of: {allowed}"
            )
        if priority is None:
            priority = "high" if collection_kind == "inbox_playlist" else "normal"
        elif priority not in PRIORITIES:
            allowed = ", ".join(PRIORITIES)
            raise RegistryValidationError(f"unknown priority {priority!r}; must be one of: {allowed}")
        if provenance_origin not in PROVENANCE_ORIGINS:
            allowed = ", ".join(PROVENANCE_ORIGINS)
            raise RegistryValidationError(
                f"unknown provenance origin {provenance_origin!r}; must be one of: {allowed}"
            )
        policy = validate_acquisition_policy(acquisition_policy, collection_kind=collection_kind)
        now = _utcnow()
        row = SourceBinding(
            binding_id=str(uuid.uuid4()),
            account_binding_id=account_binding_id,
            collection_kind=collection_kind,
            collection_ref=collection_ref.strip(),
            title=title,
            enabled=enabled,
            discovery_mode=discovery_mode,
            poll_interval_seconds=poll_interval_seconds,
            priority=priority,
            cursor={},
            last_attempt_at=None,
            last_success_at=None,
            last_error=None,
            acquisition_policy=policy,
            provenance={
                "origin": provenance_origin,
                "at": now.isoformat(),
                "detail": provenance_detail,
            },
            created_at=now,
            updated_at=now,
        )
        self._store.insert(row)
        return row

    def get(self, binding_id: str) -> SourceBinding:
        row = self._store.get(binding_id)
        if row is None:
            raise UnknownBindingError(f"unknown binding_id: {binding_id}")
        return row

    def list(
        self,
        *,
        account_binding_id: str | None = None,
        collection_kind: str | None = None,
        enabled: bool | None = None,
    ) -> list[SourceBinding]:
        return self._store.list(
            account_binding_id=account_binding_id,
            collection_kind=collection_kind,
            enabled=enabled,
        )

    def set_inbox(self, account_binding_id: str, binding_id: str) -> SourceBinding:
        """Atomically make ``binding_id`` the single enabled inbox for the account.

        The previously enabled inbox (if any) is disabled in the same
        operation; there is no observable state with two enabled inboxes and
        a failed swap leaves the registry unchanged.
        """
        target = self.get(binding_id)
        if target.collection_kind != "inbox_playlist":
            raise RegistryValidationError(
                f"binding {binding_id} is a {target.collection_kind}, not an inbox playlist"
            )
        if target.account_binding_id != account_binding_id:
            raise RegistryValidationError(
                "inbox swap must stay within one account binding; the target binding "
                "belongs to a different account"
            )
        updated = self._store.swap_inbox(account_binding_id, binding_id)
        if updated is None:
            raise UnknownBindingError(f"unknown binding_id: {binding_id}")
        return updated

    def rename(self, binding_id: str, title: str) -> SourceBinding:
        """Update the display title only (INV-YSS-9: title is never identity)."""
        if not isinstance(title, str):
            raise RegistryValidationError("title must be a string")
        return self._update_known(binding_id, title=title)

    def set_enabled(self, binding_id: str, enabled: bool) -> SourceBinding:
        return self._update_known(binding_id, enabled=bool(enabled))

    def update_poll_interval(self, binding_id: str, poll_interval_seconds: int | None) -> SourceBinding:
        _validate_poll_interval(poll_interval_seconds)
        return self._update_known(binding_id, poll_interval_seconds=poll_interval_seconds)

    def set_policy(self, binding_id: str, acquisition_policy: dict[str, Any]) -> SourceBinding:
        """Validate and apply a policy change, bumping ``policy_version``.

        The bump changes request identity for *future* discoveries only (per
        the contract there is no retroactive re-acquisition without explicit
        backfill).
        """
        current = self.get(binding_id)
        supplied = dict(acquisition_policy)
        supplied.pop("policy_version", None)
        normalized = validate_acquisition_policy(
            supplied, collection_kind=current.collection_kind
        )
        current_version = int(current.acquisition_policy.get("policy_version", 1))
        normalized["policy_version"] = current_version + 1
        return self._update_known(binding_id, acquisition_policy=normalized)

    def update_cursor(self, binding_id: str, cursor: dict[str, Any]) -> SourceBinding:
        if not isinstance(cursor, dict):
            raise RegistryValidationError("cursor must be a JSON object (opaque per adapter)")
        return self._update_known(binding_id, cursor=dict(cursor))

    def record_attempt(self, binding_id: str, *, at: datetime | None = None) -> SourceBinding:
        return self._update_known(binding_id, last_attempt_at=at or _utcnow())

    def record_success(self, binding_id: str, *, at: datetime | None = None) -> SourceBinding:
        """Successful poll: stamps ``last_success_at`` and clears ``last_error``."""
        return self._update_known(binding_id, last_success_at=at or _utcnow(), last_error=None)

    def record_error(
        self, binding_id: str, *, reason_code: str, detail: str, at: datetime | None = None
    ) -> SourceBinding:
        error = {
            "reason_code": reason_code,
            "detail": detail,
            "at": (at or _utcnow()).isoformat(),
        }
        return self._update_known(binding_id, last_error=error)

    def _update_known(self, binding_id: str, **changes: Any) -> SourceBinding:
        updated = self._store.update(binding_id, **changes)
        if updated is None:
            raise UnknownBindingError(f"unknown binding_id: {binding_id}")
        return updated


__all__ = [
    "ACQUISITION_POLICY_MODES",
    "COLLECTION_KINDS",
    "DISCOVERY_MODES",
    "DuplicateBindingError",
    "PRIORITIES",
    "RegistryValidationError",
    "SourceBinding",
    "SourceRegistry",
    "SourceRegistryError",
    "SourceRegistrySchemaMissingError",
    "SourceUnsupportedError",
    "UnknownBindingError",
    "default_acquisition_policy",
    "reset_memory_source_registry",
    "validate_acquisition_policy",
]
