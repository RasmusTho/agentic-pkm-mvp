"""Database schema/runtime error types shared across layers.

Lives in ``app.db`` (not ``app.stores``) so non-store layers — e.g. the outbox
worker's dispatch classification — can import the type without adding a new
caller of the deprecated ``app.stores`` package
(tests/architecture/test_deprecated_store_callers.py).
"""

from __future__ import annotations


class StoreSchemaMissingError(RuntimeError):
    """Migration-owned store schema is absent in a Postgres-backed runtime.

    Raised by the assert-only preflight (`app/stores/pg.py::_assert_tables`,
    KERNEL-04 #2766) when a store table or identity column is missing.
    Schema-missing is a boot-ordering condition, not a poison payload: alembic
    runs in the api/agent-service boot path while worker/watcher containers
    depend only on the db service, so a fresh stack can dispatch before
    migrations land. Dispatch classification treats this as transient
    (`app/workers/outbox_worker.py::_is_transient_dispatch_error`): the worker
    crash-retries under supervision and must never dead-letter on it.

    Classification rides the classifier's documented ``is_transient`` marker
    protocol (same as provider adapters like GeminiTransientError) rather than
    an isinstance import in the worker: layering guards forbid the worker from
    importing ``app.db``/``app.stores``
    (tests/guard/test_no_direct_db_imports.py,
    tests/architecture/test_deprecated_store_callers.py). The classification
    is asserted at the production site by
    tests/workers/test_outbox_worker.py::test_store_schema_missing_is_transient_never_dead_letters.
    """

    is_transient = True


class OutboxSchemaMissingError(RuntimeError):
    """Migration-owned outbox schema is absent in a Postgres-backed runtime.

    Raised by the assert-only preflight (`app/services/outbox.py::bootstrap`,
    KERNEL-05 #2850) when the `outbox` table or an expected column is missing.
    Mirrors `StoreSchemaMissingError` (KERNEL-04, #2766): schema-missing is a
    boot-ordering condition (alembic runs in the api/agent-service boot path
    while the worker only depends on the db service), not a poison payload, so
    it must crash-retry under supervision and never dead-letter/burn poison
    budget. It rides the same ``is_transient`` marker protocol the outbox
    worker's dispatch classifier (`_is_transient_dispatch_error`) already
    checks generically, so no worker-side change is needed for classification.
    """

    is_transient = True
