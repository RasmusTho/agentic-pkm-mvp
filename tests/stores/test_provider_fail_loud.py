"""Fail-loud store backend resolution (KERNEL-03, issue #2765).

Audit invariant I-S4: a configured-but-unreachable Postgres must be fatal at
first store access, and the volatile in-memory backend is only reachable via
an explicit ``STORE_BACKEND=memory`` opt-in. Asserted through the production
call sites ``get_object_store()`` / ``get_vector_index()`` and the
``app.stores.provider.get_stores()`` seam.

Spec: docs/RUNTIME_CORRECTNESS_KERNEL/SINGLE_STORE_GENERATION.md
"""

from __future__ import annotations

import pytest

from app.stores import get_object_store, get_vector_index
from app.stores.provider import _resolved_backend, get_stores

# Nothing listens on port 1; connection is refused immediately.
_UNREACHABLE_DSN = "postgresql://app:app@127.0.0.1:1/app"


def _configure_unreachable_pg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE_DSN)
    monkeypatch.delenv("DB_DSN", raising=False)
    _resolved_backend.cache_clear()


def test_unreachable_pg_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Postgres configured but unreachable => first store access raises."""
    _configure_unreachable_pg(monkeypatch)

    with pytest.raises(RuntimeError, match="unreachable"):
        get_object_store()

    with pytest.raises(RuntimeError, match="unreachable"):
        get_vector_index()

    with pytest.raises(RuntimeError, match="unreachable"):
        get_stores()


def test_unreachable_pg_raises_via_db_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_DSN counts as 'Postgres configured' just like DATABASE_URL."""
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_DSN", _UNREACHABLE_DSN)
    _resolved_backend.cache_clear()

    with pytest.raises(RuntimeError, match="unreachable"):
        get_object_store()


def test_memory_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DSN and no explicit STORE_BACKEND => raises; explicit memory works."""
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    _resolved_backend.cache_clear()

    with pytest.raises(RuntimeError, match="STORE_BACKEND=memory"):
        get_object_store()

    with pytest.raises(RuntimeError, match="STORE_BACKEND=memory"):
        get_stores()

    monkeypatch.setenv("STORE_BACKEND", "memory")

    from app.stores.memory import MemoryObjectStore, MemoryVectorIndex

    assert isinstance(get_object_store(), MemoryObjectStore)
    assert isinstance(get_vector_index(), MemoryVectorIndex)
    # provider seam resolves to the in-process memory stores without raising
    objects, decisions = get_stores()
    assert objects is not None and decisions is not None


def test_unknown_backend_value_raises_in_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding on #2832: an explicit but unknown STORE_BACKEND value
    ('postgres', 'pgvector', a typo) must raise at the provider seam — never
    silently route get_stores() to the volatile in-memory backend."""
    monkeypatch.setenv("STORE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://demo:demo@localhost:5432/demo")
    monkeypatch.delenv("DB_DSN", raising=False)
    _resolved_backend.cache_clear()
    with pytest.raises(RuntimeError, match="not supported"):
        get_stores()


def test_unknown_backend_value_raises_in_store_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same contract at the app.stores resolution seam, which also feeds the
    resolve_store_backend() label consumers (index-rebuild receipts)."""
    from app.stores import resolve_store_backend

    monkeypatch.setenv("STORE_BACKEND", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "postgresql://demo:demo@localhost:5432/demo")
    monkeypatch.delenv("DB_DSN", raising=False)
    with pytest.raises(RuntimeError, match="not supported"):
        resolve_store_backend()


def test_backend_value_whitespace_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    """' memory ' (whitespace/case noise) resolves to the memory backend in the
    provider seam instead of silently mismatching the allowed set."""
    monkeypatch.setenv("STORE_BACKEND", " MEMORY ")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    _resolved_backend.cache_clear()
    stores = get_stores()
    assert stores is not None
