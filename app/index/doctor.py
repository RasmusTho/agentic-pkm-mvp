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


__all__ = ["diagnose_index", "reset_diagnose_cache"]
