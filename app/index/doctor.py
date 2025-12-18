from __future__ import annotations

import time
from typing import Any, Dict

from app.components.embeddings import EmbeddingIdentity, get_embedding_client, get_embedding_identity
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


def diagnose_index() -> Dict[str, Any]:
    client = get_embedding_client()
    expected_identity = get_embedding_identity(client=client)
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
            if not pg_state.get("identity_present"):
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

    return {
        "timestamp": time.time(),
        "backend": backend,
        "expected_identity": _identity_to_dict(expected_identity),
        "stored_identity": _identity_to_dict(stored_identity),
        "issues": issues,
        "warnings": warnings,
        "status": status,
        "pg_state": pg_state,
    }


__all__ = ["diagnose_index"]

