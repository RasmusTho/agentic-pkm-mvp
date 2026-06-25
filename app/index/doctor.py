from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict

from app.components.embeddings import EmbeddingIdentity
from app.components.llm.fabric import LLMTaskIntent, get_embeddings_client
from app.stores import get_vector_index

try:  # Runtime type hints without hard dependencies at import time
    from app.stores.memory import MemoryVectorIndex
except Exception:  # pragma: no cover - memory backend optional in some contexts
    MemoryVectorIndex = None  # type: ignore

try:
    from app.stores.pg import PgVectorIndex, inspect_pg_index_state
except Exception:  # pragma: no cover - pg backend optional in some contexts
    PgVectorIndex = None  # type: ignore
    inspect_pg_index_state = None  # type: ignore


def _identity_to_dict(identity: EmbeddingIdentity | None) -> Dict[str, Any] | None:
    if identity is None:
        return None
    return {
        "provider": identity.provider,
        "model": identity.model,
        "dim": identity.dim,
        "normalize": identity.normalize,
    }


_DIAGNOSE_TTL_S = float(os.getenv("INDEX_DOCTOR_TTL_S", "10"))
_diagnose_cache: tuple[float, Dict[str, Any]] | None = None
_diagnose_lock = threading.Lock()


def _cached_diagnose() -> Dict[str, Any] | None:
    global _diagnose_cache
    cache = _diagnose_cache
    if cache is None:
        return None
    ts, value = cache
    if (time.monotonic() - ts) > _DIAGNOSE_TTL_S:
        return None
    return value


def diagnose_index(*, use_cache: bool = False) -> Dict[str, Any]:
    """Return embedding-index diagnostics.

    The status-request path passes ``use_cache=True`` to bound diagnostic
    work to one DB inspection per ``INDEX_DOCTOR_TTL_S`` seconds (default
    10s). Other callers default to fresh evaluation so changes in identity
    configuration are immediately visible.
    """
    global _diagnose_cache
    if use_cache:
        cached = _cached_diagnose()
        if cached is not None:
            return cached
    client = get_embeddings_client(LLMTaskIntent(task_kind="embed", determinism_required=False))
    expected_identity = client.identity
    vector_index = get_vector_index()
    stored_identity = None
    if hasattr(vector_index, "get_identity"):
        try:
            stored_identity = vector_index.get_identity()  # type: ignore[attr-defined]
        except Exception:
            stored_identity = None

    backend = vector_index.__class__.__name__
    issues: list[str] = []
    warnings: list[str] = []
    empty_index = False

    if stored_identity is None:
        warnings.append("VectorIndex has no recorded embedding identity (empty index or legacy backend).")
    else:
        for field in ("provider", "model", "dim", "normalize"):
            expected_val = getattr(expected_identity, field)
            stored_val = getattr(stored_identity, field)
            if expected_val != stored_val:
                issues.append(f"Identity mismatch for {field}: expected {expected_val}, stored {stored_val}.")

    pg_state: dict[str, Any] | None = None
    if PgVectorIndex is not None and isinstance(vector_index, PgVectorIndex):  # type: ignore[arg-type]
        if inspect_pg_index_state is not None:
            pg_state = inspect_pg_index_state()
            empty_index = int(pg_state.get("rows") or 0) == 0
            if not pg_state.get("identity_present"):
                if empty_index:
                    warnings.append("Vector index is empty; no stored embedding identity recorded yet.")
                else:
                    issues.append("vector_index_meta is missing; embeddings must be rebuilt.")
            dims = pg_state.get("dims") or []
            distinct_dims = sorted({d for d in dims if isinstance(d, int)})
            if len(distinct_dims) > 1:
                issues.append(f"Mixed embedding dimensions present in Postgres index: {distinct_dims}.")
            wrong_rows = pg_state.get("rows_wrong_dim")
            if isinstance(wrong_rows, int) and wrong_rows > 0:
                issues.append(f"{wrong_rows} rows have embeddings not matching the recorded dimension.")
            unembedded_count, unembedded_samples = inspect_unembedded_pg_objects()
            if unembedded_count:
                sample_text = ", ".join(unembedded_samples)
                if unembedded_count > len(unembedded_samples):
                    sample_text = f"{sample_text}, ..." if sample_text else "..."
                issues.append(
                    f"{unembedded_count} store_objects rows have no embedded "
                    f"store_vector_index row: {sample_text}"
                )

    status = "ok"
    if issues:
        status = "error"
    elif warnings:
        status = "warn"

    compatible_identity: bool | None
    if stored_identity is None:
        compatible_identity = None if (empty_index or pg_state is None) else False
    else:
        compatible_identity = not bool(issues)

    rebuild_required = bool(issues)
    rebuild_reason = issues[0] if issues else None

    result: Dict[str, Any] = {
        "timestamp": time.time(),
        "backend": backend,
        "expected_identity": _identity_to_dict(expected_identity),
        "stored_identity": _identity_to_dict(stored_identity),
        "stored_identity_present": stored_identity is not None,
        "compatible_identity": compatible_identity,
        "empty_index": empty_index,
        "rebuild_required": rebuild_required,
        "rebuild_reason": rebuild_reason,
        "issues": issues,
        "warnings": warnings,
        "status": status,
        "pg_state": pg_state,
    }
    with _diagnose_lock:
        _diagnose_cache = (time.monotonic(), result)
    return result


def reset_diagnose_cache() -> None:
    """Drop any cached diagnose_index result. Intended for tests."""
    global _diagnose_cache
    with _diagnose_lock:
        _diagnose_cache = None


class IndexDriftError(AssertionError):
    """Raised when durable objects exist with no embedded vector-index row.

    This is the #2252-class stall: a ``store_objects`` row is present but the
    outbox never drained, so no ``store_vector_index`` row with a non-empty
    embedding was written. The condition must fail loud rather than pass
    silently.
    """


def inspect_unembedded_pg_objects(*, limit: int = 5) -> tuple[int, list[str]]:
    """Return count and sample object ids present in ``store_objects`` but unembedded."""
    if PgVectorIndex is None:
        return 0, []

    from app.stores.pg import _connect  # local import: pg backend is optional

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*) AS total
                FROM store_objects AS o
                LEFT JOIN store_vector_index AS v
                  ON v.object_id = o.object_id
                 AND v.embedding IS NOT NULL
                 AND array_length(v.embedding, 1) > 0
                WHERE v.object_id IS NULL
                """
            )
            row = cur.fetchone()
            total = int((row.get("total") if isinstance(row, dict) else row[0]) or 0) if row else 0
            if not total:
                return 0, []
            cur.execute(
                """
                SELECT o.object_id AS object_id
                FROM store_objects AS o
                LEFT JOIN store_vector_index AS v
                  ON v.object_id = o.object_id
                 AND v.embedding IS NOT NULL
                 AND array_length(v.embedding, 1) > 0
                WHERE v.object_id IS NULL
                ORDER BY o.updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return total, [
                str(sample.get("object_id") if isinstance(sample, dict) else sample[0])
                for sample in cur.fetchall()
            ]


def verify_object_embedded(object_id: str) -> None:
    """Fail loud when ``object_id`` is present in ``store_objects`` but unembedded.

    Drives the durable Postgres backend (the same ``store_vector_index`` table the
    consumer writes and recall reads). Raises :class:`IndexDriftError` when the
    object has no ``store_vector_index`` row carrying a non-empty embedding.

    This is the production verification entrypoint for the objects-present /
    no-vector drift the worker stall produces; ``make verify`` style drift checks
    and the indexer regression tests call it rather than re-implementing the
    assertion inline.
    """
    if PgVectorIndex is None:
        raise RuntimeError("Postgres backend is required to verify embedding drift.")

    from app.stores.pg import _connect  # local import: pg backend is optional

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM store_objects WHERE object_id = %s LIMIT 1", (object_id,))
            if cur.fetchone() is None:
                return
            cur.execute(
                "SELECT 1 FROM store_vector_index "
                "WHERE object_id = %s "
                "AND embedding IS NOT NULL AND array_length(embedding, 1) > 0 "
                "LIMIT 1",
                (object_id,),
            )
            embedded = cur.fetchone() is not None

    if not embedded:
        raise IndexDriftError(
            f"object {object_id} present in store_objects but has no embedded "
            "store_vector_index row (processed_total=0; #2252-class stall)"
        )


__all__ = [
    "diagnose_index",
    "reset_diagnose_cache",
    "inspect_unembedded_pg_objects",
    "verify_object_embedded",
    "IndexDriftError",
]
