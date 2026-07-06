"""Local, self-contained store-backend resolution for the Heimdal package.

``app.stores`` is a deprecated transitional layer (`docs/CODE_INVENTORY.md`
§Deprecated Packages, ADR-0013, guarded by
``tests/architecture/test_deprecated_store_callers.py``) -- new code must not
extend it. This module reimplements just the fail-loud backend-selection
semantics that convention establishes (``STORE_BACKEND=memory|pg`` override,
else resolve from ``DATABASE_URL``/``DB_DSN``, and a configured-but-
unreachable Postgres must raise rather than silently degrade to memory -- the
KERNEL-03 / I-S4 precedent), scoped to `app.heimdal`'s own tables instead
of routing through the deprecated shared provider.
"""

from __future__ import annotations

import os

from app.db.dsn import resolve_dsn

_ALLOWED_BACKENDS = {"memory", "pg"}


def resolve_heimdal_backend() -> str:
    """Return ``"memory"`` or ``"pg"`` for the Heimdal observation log/cursor stores.

    Fail-loud (KERNEL-03 / I-S4 precedent): an explicit but unsupported
    ``STORE_BACKEND`` value raises; a configured-but-unreachable Postgres
    raises rather than silently falling back to the volatile memory backend.
    """
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
        import psycopg

        conn = psycopg.connect(dsn, connect_timeout=1)
        conn.close()
    except Exception as exc:
        raise RuntimeError(
            "Store backend resolution failed: Postgres is configured "
            "(DATABASE_URL/DB_DSN) but unreachable. Refusing to fall back to a "
            f"volatile in-memory store. Underlying error: {exc}"
        ) from exc
    return "pg"


__all__ = ["resolve_heimdal_backend"]
