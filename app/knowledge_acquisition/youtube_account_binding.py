"""YSS-02 (#3917): durable, non-secret YouTube account-binding registry.

The account binding is the ``account_binding_id`` referenced by every
authenticated row in ``app/knowledge_acquisition/source_registry.py`` (YSS-01).
It records *which* Google/YouTube account is connected and its legible auth
state -- **never** any secret. Tokens live in the encrypted
``youtube_token_store``; client credentials live in host env. This row carries
only: the binding id, the provider channel id (source-native ``UC...`` id --
identity, never a title), a display label, the connected/degraded state + a
reason code, the granted scopes, a monotonic binding generation, and timestamps
(INV-YSS-5).  The generation is non-secret compare-and-set authority for OAuth
lifecycle recovery; wall-clock timestamps remain observational only.

Dual backend and store discipline mirror ``source_registry`` exactly: memory
backend for ``not_pg`` tests, Postgres for a configured runtime (fail-loud on
an unreachable DSN, never a silent volatile fallback), a migration-owned table
(``youtube_account_binding``) with a fail-loud schema preflight, and the
``STORE_SCHEMA_AUTOCREATE`` test-only autocreate opt-in. Channel isolation is
DB-per-channel (INV-YSS-7); this table carries no environment column.
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

PROVIDER_YOUTUBE = "youtube"
VALID_BINDING_STATES: frozenset[str] = frozenset({"connected", "degraded"})
# The auth reason codes a binding may carry (subset of the contract taxonomy
# that is auth-scoped). ``None`` means healthy/connected.
VALID_BINDING_REASON_CODES: frozenset[str] = frozenset(
    {
        "auth_missing",
        "auth_key_missing",
        "auth_expired",
        "auth_revoked",
        "auth_disconnected",
        "auth_refresh_pending",
        "auth_refresh_conflict",
        "auth_refresh_durability",
    }
)

_TABLE = "youtube_account_binding"
_MIGRATION_HINT = (
    "youtube_account_binding schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See "
    "app/alembic/versions/a2f1c3e4d5b6_yss02_youtube_account_binding.py and "
    "e1f2a3b4c5d6_yss02_binding_generation_cas.py."
)
_ALLOWED_BACKENDS = {"memory", "pg"}


class AccountBindingSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the binding table is absent."""


class AccountBindingValidationError(ValueError):
    """Raised for malformed/unknown account-binding field values (fail-loud)."""


class DuplicateAccountBindingError(ValueError):
    """Raised when a binding for the same provider channel id already exists."""


class AccountBindingGenerationConflictError(RuntimeError):
    """Raised when a state write no longer owns its expected binding generation."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AccountBinding:
    """One durable, non-secret account-binding row."""

    account_binding_id: str
    provider: str
    provider_channel_id: str
    display_label: str
    state: str
    reason_code: str | None
    scopes: tuple[str, ...]
    obtained_at: str
    created_at: str
    updated_at: str
    binding_generation: int


def _validate_state(state: str, reason_code: str | None) -> None:
    if state not in VALID_BINDING_STATES:
        raise AccountBindingValidationError(
            f"state must be one of {sorted(VALID_BINDING_STATES)}, got {state!r}"
        )
    if reason_code is not None and reason_code not in VALID_BINDING_REASON_CODES:
        raise AccountBindingValidationError(
            f"reason_code must be null or one of {sorted(VALID_BINDING_REASON_CODES)}, got {reason_code!r}"
        )
    if state == "connected" and reason_code is not None:
        raise AccountBindingValidationError("a connected binding must not carry a reason_code")


def _validate_scopes(scopes: Any) -> tuple[str, ...]:
    if not isinstance(scopes, (list, tuple)) or not scopes:
        raise AccountBindingValidationError("scopes must be a non-empty list of strings")
    resolved: list[str] = []
    for scope in scopes:
        if not isinstance(scope, str) or not scope.strip():
            raise AccountBindingValidationError("each scope must be a non-empty string")
        if "\x00" in scope:
            raise AccountBindingValidationError("scope must not contain NUL")
        resolved.append(scope)
    return tuple(resolved)


# --- Backend resolution (mirrors source_registry._resolve_backend) ----------


def _resolve_backend() -> str:
    override = (os.getenv("STORE_BACKEND") or "").strip().lower()
    if override:
        if override not in _ALLOWED_BACKENDS:
            raise RuntimeError(
                f"Store backend '{override}' is not supported for the account binding registry: "
                "set STORE_BACKEND to 'pg' or 'memory', or unset it to resolve from "
                "DATABASE_URL/DB_DSN."
            )
        return override
    dsn = resolve_dsn()
    if not dsn:
        raise RuntimeError(
            "No store backend configured for the account binding registry: set STORE_BACKEND=memory "
            "explicitly for the volatile in-memory backend, or configure DATABASE_URL/DB_DSN."
        )
    try:
        import psycopg  # noqa: PLC0415

        conn = psycopg.connect(dsn, connect_timeout=1)
        conn.close()
    except Exception as exc:
        raise RuntimeError(
            "Account binding backend resolution failed: Postgres is configured but unreachable. "
            f"Refusing to fall back to a volatile in-memory store. Underlying error: {exc}"
        ) from exc
    return "pg"


# --- Memory backend ----------------------------------------------------------


class _MemoryAccountBindingBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, AccountBinding] = {}

    def insert(self, binding: AccountBinding) -> AccountBinding:
        with self._lock:
            for row in self._rows.values():
                if row.provider_channel_id == binding.provider_channel_id:
                    raise DuplicateAccountBindingError(
                        f"a binding already exists for provider_channel_id={binding.provider_channel_id!r}"
                    )
            self._rows[binding.account_binding_id] = binding
            return binding

    def get(self, account_binding_id: str) -> AccountBinding | None:
        with self._lock:
            return self._rows.get(account_binding_id)

    def get_by_channel_id(self, provider_channel_id: str) -> AccountBinding | None:
        with self._lock:
            for row in self._rows.values():
                if row.provider_channel_id == provider_channel_id:
                    return row
            return None

    def list_all(self) -> tuple[AccountBinding, ...]:
        with self._lock:
            return tuple(self._rows.values())

    def set_state(
        self,
        account_binding_id: str,
        state: str,
        reason_code: str | None,
        expected_binding_generation: int | None = None,
    ) -> AccountBinding:
        with self._lock:
            row = self._rows.get(account_binding_id)
            if row is None:
                raise KeyError(f"no such account binding: {account_binding_id}")
            if (
                expected_binding_generation is not None
                and row.binding_generation != expected_binding_generation
            ):
                raise AccountBindingGenerationConflictError(
                    "account binding generation changed before state persistence"
                )
            updated = replace(
                row,
                state=state,
                reason_code=reason_code,
                updated_at=_now_iso(),
                binding_generation=row.binding_generation + 1,
            )
            self._rows[account_binding_id] = updated
            return updated

    def delete(self, account_binding_id: str) -> bool:
        with self._lock:
            return self._rows.pop(account_binding_id, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_MEMORY_BINDINGS = _MemoryAccountBindingBackend()


def reset_memory_account_bindings() -> None:
    """Test-only reset hook (mirrors reset_memory_source_registry)."""
    _MEMORY_BINDINGS.clear()


# --- Postgres backend --------------------------------------------------------

_COLUMNS = (
    "account_binding_id",
    "provider",
    "provider_channel_id",
    "display_label",
    "state",
    "reason_code",
    "scopes",
    "obtained_at",
    "created_at",
    "updated_at",
    "binding_generation",
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
    if not (row and row[0]):
        raise AccountBindingSchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "AND column_name = 'binding_generation' AND data_type = 'bigint' "
        "AND is_nullable = 'NO'",
        (_TABLE,),
    )
    if cur.fetchone() is None:
        raise AccountBindingSchemaMissingError(
            f"Table '{_TABLE}' lacks required BIGINT NOT NULL column "
            f"'binding_generation'. {_MIGRATION_HINT}"
        )


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            account_binding_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_channel_id TEXT NOT NULL,
            display_label TEXT NOT NULL,
            state TEXT NOT NULL,
            reason_code TEXT,
            scopes JSONB NOT NULL,
            obtained_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            binding_generation BIGINT NOT NULL DEFAULT 1,
            CONSTRAINT youtube_account_binding_state_chk CHECK (state IN ('connected', 'degraded')),
            CONSTRAINT youtube_account_binding_connected_reason_chk CHECK (
                state <> 'connected' OR reason_code IS NULL
            ),
            CONSTRAINT youtube_account_binding_generation_chk CHECK (
                binding_generation >= 1
            )
        )
        """
    )
    cur.execute(
        f"ALTER TABLE {_TABLE} ADD COLUMN IF NOT EXISTS "
        "binding_generation BIGINT NOT NULL DEFAULT 1"
    )
    cur.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'youtube_account_binding_generation_chk'
                  AND conrelid = '{_TABLE}'::regclass
            ) THEN
                ALTER TABLE {_TABLE}
                ADD CONSTRAINT youtube_account_binding_generation_chk
                CHECK (binding_generation >= 1);
            END IF;
        END $$;
        """
    )
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS youtube_account_binding_channel_uq "
        f"ON {_TABLE} (provider, provider_channel_id)"
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _row_to_binding(row: tuple[Any, ...]) -> AccountBinding:
    values = dict(zip(_COLUMNS, row))
    scopes = values["scopes"]
    if isinstance(scopes, str):
        scopes = json.loads(scopes)
    return AccountBinding(
        account_binding_id=values["account_binding_id"],
        provider=values["provider"],
        provider_channel_id=values["provider_channel_id"],
        display_label=values["display_label"],
        state=values["state"],
        reason_code=values["reason_code"],
        scopes=tuple(scopes or ()),
        obtained_at=_iso(values["obtained_at"]) or "",
        created_at=_iso(values["created_at"]) or "",
        updated_at=_iso(values["updated_at"]) or "",
        binding_generation=int(values["binding_generation"]),
    )


class _PgAccountBindingBackend:
    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def insert(self, binding: AccountBinding) -> AccountBinding:
        from psycopg.errors import UniqueViolation  # noqa: PLC0415

        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    f"""
                    INSERT INTO {_TABLE} (
                        account_binding_id, provider, provider_channel_id, display_label,
                        state, reason_code, scopes, obtained_at, created_at, updated_at,
                        binding_generation
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s::jsonb, %s::timestamptz,
                        %s::timestamptz, %s::timestamptz, %s
                    )
                    """,
                    (
                        binding.account_binding_id,
                        binding.provider,
                        binding.provider_channel_id,
                        binding.display_label,
                        binding.state,
                        binding.reason_code,
                        json.dumps(list(binding.scopes)),
                        binding.obtained_at,
                        binding.created_at,
                        binding.updated_at,
                        binding.binding_generation,
                    ),
                )
            except UniqueViolation as exc:
                raise DuplicateAccountBindingError(
                    f"a binding already exists for provider_channel_id={binding.provider_channel_id!r}"
                ) from exc
            return binding
        finally:
            conn.close()

    def get(self, account_binding_id: str) -> AccountBinding | None:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT {_COLUMNS_SQL} FROM {_TABLE} WHERE account_binding_id = %s",
                (account_binding_id,),
            )
            row = cur.fetchone()
            return _row_to_binding(tuple(row)) if row else None
        finally:
            conn.close()

    def get_by_channel_id(self, provider_channel_id: str) -> AccountBinding | None:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT {_COLUMNS_SQL} FROM {_TABLE} WHERE provider = %s AND provider_channel_id = %s",
                (PROVIDER_YOUTUBE, provider_channel_id),
            )
            row = cur.fetchone()
            return _row_to_binding(tuple(row)) if row else None
        finally:
            conn.close()

    def list_all(self) -> tuple[AccountBinding, ...]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT {_COLUMNS_SQL} FROM {_TABLE} ORDER BY created_at")
            return tuple(_row_to_binding(tuple(row)) for row in cur.fetchall())
        finally:
            conn.close()

    def set_state(
        self,
        account_binding_id: str,
        state: str,
        reason_code: str | None,
        expected_binding_generation: int | None = None,
    ) -> AccountBinding:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            params: list[Any] = [state, reason_code, _now_iso(), account_binding_id]
            generation_clause = ""
            if expected_binding_generation is not None:
                generation_clause = " AND binding_generation = %s"
                params.append(expected_binding_generation)
            cur.execute(
                f"UPDATE {_TABLE} SET state = %s, reason_code = %s, "
                "updated_at = %s::timestamptz, "
                "binding_generation = binding_generation + 1 "
                f"WHERE account_binding_id = %s{generation_clause} "
                f"RETURNING {_COLUMNS_SQL}",
                tuple(params),
            )
            row = cur.fetchone()
            if row is None:
                if expected_binding_generation is not None:
                    raise AccountBindingGenerationConflictError(
                        "account binding generation changed before state persistence"
                    )
                raise KeyError(f"no such account binding: {account_binding_id}")
            return _row_to_binding(tuple(row))
        finally:
            conn.close()

    def delete(self, account_binding_id: str) -> bool:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"DELETE FROM {_TABLE} WHERE account_binding_id = %s", (account_binding_id,))
            return cur.rowcount > 0
        finally:
            conn.close()


# --- Service layer -----------------------------------------------------------


class AccountBindingStore:
    """Service facade enforcing the same validation on both backends."""

    def __init__(self, backend: _MemoryAccountBindingBackend | _PgAccountBindingBackend) -> None:
        self._backend = backend

    @classmethod
    def for_runtime(cls) -> "AccountBindingStore":
        if _resolve_backend() == "pg":
            return cls(_PgAccountBindingBackend())
        return cls(_MEMORY_BINDINGS)

    def create(
        self,
        *,
        provider_channel_id: str,
        display_label: str,
        scopes: Any,
        account_binding_id: str | None = None,
        obtained_at: str | None = None,
    ) -> AccountBinding:
        if not isinstance(provider_channel_id, str) or not provider_channel_id.strip():
            raise AccountBindingValidationError("provider_channel_id must be a non-empty string")
        if not isinstance(display_label, str) or not display_label.strip():
            raise AccountBindingValidationError("display_label must be a non-empty string")
        resolved_scopes = _validate_scopes(scopes)
        now = _now_iso()
        binding = AccountBinding(
            account_binding_id=account_binding_id or str(uuid.uuid4()),
            provider=PROVIDER_YOUTUBE,
            provider_channel_id=provider_channel_id,
            display_label=display_label,
            state="connected",
            reason_code=None,
            scopes=resolved_scopes,
            obtained_at=obtained_at or now,
            created_at=now,
            updated_at=now,
            binding_generation=1,
        )
        return self._backend.insert(binding)

    def get(self, account_binding_id: str) -> AccountBinding | None:
        return self._backend.get(account_binding_id)

    def get_by_channel_id(self, provider_channel_id: str) -> AccountBinding | None:
        return self._backend.get_by_channel_id(provider_channel_id)

    def list_all(self) -> tuple[AccountBinding, ...]:
        return self._backend.list_all()

    def set_state(
        self,
        account_binding_id: str,
        *,
        state: str,
        reason_code: str | None = None,
        expected_binding_generation: int | None = None,
    ) -> AccountBinding:
        _validate_state(state, reason_code)
        if expected_binding_generation is not None and (
            isinstance(expected_binding_generation, bool)
            or not isinstance(expected_binding_generation, int)
            or expected_binding_generation < 1
        ):
            raise AccountBindingValidationError(
                "expected_binding_generation must be an integer >= 1"
            )
        return self._backend.set_state(
            account_binding_id,
            state,
            reason_code,
            expected_binding_generation,
        )

    def delete(self, account_binding_id: str) -> bool:
        return self._backend.delete(account_binding_id)


__all__ = [
    "AccountBinding",
    "AccountBindingGenerationConflictError",
    "AccountBindingSchemaMissingError",
    "AccountBindingStore",
    "AccountBindingValidationError",
    "DuplicateAccountBindingError",
    "PROVIDER_YOUTUBE",
    "VALID_BINDING_REASON_CODES",
    "VALID_BINDING_STATES",
    "reset_memory_account_bindings",
]
