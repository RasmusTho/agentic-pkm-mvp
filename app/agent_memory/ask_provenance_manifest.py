"""Local, read-only shadow manifests for grounded ASK executions.

The capture seam is deliberately downstream of ASK synthesis and never feeds
the response path.  Records contain hashes and observed identities only; an
unobserved identity is explicit and makes comparison fail closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

logger = logging.getLogger(__name__)

SCHEMA = "ask_provenance_manifest.v1"
DEFAULT_PATH = Path("runtime/agent_memory/ask_provenance_manifests.jsonl")
DEFAULT_RETENTION_DAYS = 14
DEFAULT_LATENCY_BUDGET_MS = 10
DEFAULT_MAX_RECORDS = 256


@dataclass(frozen=True)
class AuthorizationSnapshot:
    """The current, actual read context used to capture or compare a run."""

    scope_id: str
    principal_id: str
    authorization_context: Mapping[str, Any]
    policy: Mapping[str, Any]
    authorized_source_ids: tuple[str, ...] = ()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _privacy_hash(value: str, key: bytes) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_scope(value: str) -> str:
    return " ".join(value.strip().split()).casefold() or "scope:unscoped"


def _identity(value: Any, *, unavailable_reason: str) -> dict[str, str]:
    if value is None or value == "" or value == {}:
        return {"status": "unavailable", "reason": unavailable_reason}
    return {"status": "available", "value_hash": _sha256(_canonical_json(value))}


def _source_hash(value: Any) -> dict[str, str]:
    if not isinstance(value, str) or not value.strip():
        return {"status": "unavailable", "reason": "canonical_source_hash_not_observed"}
    return {"status": "available", "value": value.strip()}


def _privacy_key(explicit: bytes | None) -> bytes | None:
    if explicit:
        return explicit
    configured = os.getenv("ASK_PROVENANCE_PRIVACY_KEY", "").encode("utf-8")
    return configured or None


def _manifest_path(explicit: Path | None) -> Path:
    configured = os.getenv("ASK_PROVENANCE_MANIFEST_PATH")
    return explicit or (Path(configured).expanduser() if configured else DEFAULT_PATH)


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    required = {
        "schema",
        "manifest_id",
        "captured_at",
        "expires_at",
        "answer_hash",
        "query_hash",
        "authorization",
        "ordered_evidence",
        "identities",
    }
    if set(manifest) != required or manifest.get("schema") != SCHEMA:
        raise ValueError("invalid ASK provenance manifest shape")
    if not isinstance(manifest.get("ordered_evidence"), list):
        raise ValueError("ordered_evidence must be a list")
    authorization = manifest.get("authorization")
    if not isinstance(authorization, Mapping) or set(authorization) != {
        "scope_id",
        "principal_hash",
        "authorization_context_hash",
        "policy_hash",
    }:
        raise ValueError("invalid authorization snapshot")
    for position, item in enumerate(manifest["ordered_evidence"]):
        if not isinstance(item, Mapping) or set(item) != {
            "position",
            "source_id_hash",
            "canonical_source_hash",
        }:
            raise ValueError("invalid ordered evidence")
        if item.get("position") != position:
            raise ValueError("evidence order is not canonical")
        source_hash = item.get("canonical_source_hash")
        if not isinstance(source_hash, Mapping) or source_hash.get("status") not in {
            "available",
            "unavailable",
        }:
            raise ValueError("invalid canonical source hash")
    identities = manifest.get("identities")
    if not isinstance(identities, Mapping) or set(identities) != {
        "canonical_index",
        "synthesis",
    }:
        raise ValueError("invalid identity set")
    encoded = _canonical_json(manifest)
    if "raw_text" in encoded or "source_ref" in encoded or "credential" in encoded:
        raise ValueError("forbidden raw field in ASK provenance manifest")


def _append_manifest(
    path: Path, manifest: Mapping[str, Any], *, max_records: int = DEFAULT_MAX_RECORDS
) -> None:
    # A configured vault/index destination would violate the local shadow-state
    # boundary.  The default and supported override are runtime-state paths.
    if any(part.casefold() in {"vault", "index"} for part in path.parts):
        raise ValueError("ASK provenance manifests cannot be stored in vault/index paths")
    _validate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if path.exists()
        else []
    )
    for record in existing:
        _validate_manifest(record)
    captured_at = datetime.fromisoformat(str(manifest["captured_at"]).replace("Z", "+00:00"))
    retained = [
        record
        for record in existing
        if datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00")) > captured_at
    ]
    keep_count = max(0, max_records - 1)
    retained_tail = retained[-keep_count:] if keep_count else []
    records = [*retained_tail, manifest]
    # Publish the complete append atomically. A disk/process failure before
    # replace leaves the previous valid log untouched, never a partial record.
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("".join(_canonical_json(record) + "\n" for record in records))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def capture_ask_provenance(
    *,
    answer: str,
    query: str,
    evidence: Sequence[Mapping[str, Any]],
    authorization: AuthorizationSnapshot,
    retrieval_identity: Any = None,
    synthesis_identity: Any = None,
    path: Path | None = None,
    privacy_key: bytes | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    latency_budget_ms: int = DEFAULT_LATENCY_BUDGET_MS,
    clock: Callable[[], float] = time.monotonic,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Best-effort capture; every failure is isolated from the ASK result."""

    started = clock()
    try:
        key = _privacy_key(privacy_key)
        if key is None:
            raise ValueError("privacy key unavailable")
        captured_at = now or datetime.now(timezone.utc)
        ordered_evidence = []
        for position, item in enumerate(evidence):
            source_id = str(item.get("source_id") or "").strip()
            if not source_id:
                raise ValueError("evidence source identity unavailable")
            ordered_evidence.append(
                {
                    "position": position,
                    "source_id_hash": _privacy_hash(source_id, key),
                    "canonical_source_hash": _source_hash(item.get("canonical_source_hash")),
                }
            )
        manifest: dict[str, Any] = {
            "schema": SCHEMA,
            "manifest_id": f"ask-prov:{uuid4().hex}",
            "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
            "expires_at": (captured_at + timedelta(days=max(1, retention_days)))
            .isoformat()
            .replace("+00:00", "Z"),
            "answer_hash": _sha256(answer),
            "query_hash": _privacy_hash(query, key),
            "authorization": {
                "scope_id": _normalize_scope(authorization.scope_id),
                "principal_hash": _privacy_hash(authorization.principal_id, key),
                "authorization_context_hash": _sha256(
                    _canonical_json(authorization.authorization_context)
                ),
                "policy_hash": _sha256(_canonical_json(authorization.policy)),
            },
            "ordered_evidence": ordered_evidence,
            "identities": {
                "canonical_index": _identity(
                    retrieval_identity,
                    unavailable_reason="canonical_index_identity_not_observed",
                ),
                "synthesis": _identity(
                    synthesis_identity,
                    unavailable_reason="synthesis_identity_not_observed",
                ),
            },
        }
        _validate_manifest(manifest)
        if (clock() - started) * 1000 > max(0, latency_budget_ms):
            raise TimeoutError("ASK provenance capture latency budget exceeded")
        _append_manifest(_manifest_path(path), manifest)
        return manifest
    except Exception as exc:
        logger.warning("ask.provenance capture skipped: %s", type(exc).__name__)
        return None


def _status_value(record: Mapping[str, Any]) -> str | None:
    return (
        str(record.get("value") or record.get("value_hash") or "")
        if record.get("status") == "available"
        else None
    )


def compare_manifests(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    current_authorization: AuthorizationSnapshot,
    privacy_key: bytes | None = None,
) -> dict[str, Any]:
    """Compare under current authorization, returning no side-specific detail."""

    key = _privacy_key(privacy_key)
    if key is None:
        return {"classification": "indeterminate", "reason": "privacy_key_unavailable"}
    try:
        _validate_manifest(left)
        _validate_manifest(right)
    except (TypeError, ValueError):
        return {"classification": "indeterminate", "reason": "manifest_invalid"}

    current = {
        "scope_id": _normalize_scope(current_authorization.scope_id),
        "principal_hash": _privacy_hash(current_authorization.principal_id, key),
        "authorization_context_hash": _sha256(
            _canonical_json(current_authorization.authorization_context)
        ),
        "policy_hash": _sha256(_canonical_json(current_authorization.policy)),
    }
    axes: list[str] = []
    axis_fields = (
        ("scope", "scope_id"),
        ("principal", "principal_hash"),
        ("authorization_context", "authorization_context_hash"),
        ("policy", "policy_hash"),
    )
    for axis, field in axis_fields:
        if (
            left["authorization"].get(field) != right["authorization"].get(field)
            or left["authorization"].get(field) != current[field]
        ):
            axes.append(axis)

    authorized = {
        _privacy_hash(source_id, key) for source_id in current_authorization.authorized_source_ids
    }
    referenced = {
        str(item.get("source_id_hash") or "")
        for manifest in (left, right)
        for item in manifest["ordered_evidence"]
    }
    if not referenced.issubset(authorized):
        axes.append("authorization")
    if axes:
        return {"classification": "scope_mismatch", "mismatch_axes": axes}

    left_index = _status_value(left["identities"]["canonical_index"])
    right_index = _status_value(right["identities"]["canonical_index"])
    if left_index is None or right_index is None:
        return {"classification": "indeterminate", "reason": "canonical_index_identity_unavailable"}

    left_evidence = left["ordered_evidence"]
    right_evidence = right["ordered_evidence"]
    if [item["source_id_hash"] for item in left_evidence] != [
        item["source_id_hash"] for item in right_evidence
    ]:
        return {"classification": "indeterminate", "reason": "admitted_evidence_changed"}
    left_hashes = [_status_value(item["canonical_source_hash"]) for item in left_evidence]
    right_hashes = [_status_value(item["canonical_source_hash"]) for item in right_evidence]
    if any(value is None for value in (*left_hashes, *right_hashes)):
        return {"classification": "indeterminate", "reason": "canonical_source_hash_unavailable"}
    if left_hashes != right_hashes:
        return {"classification": "source_drift"}
    if left_index != right_index:
        return {"classification": "index_drift"}

    left_synthesis = _status_value(left["identities"]["synthesis"])
    right_synthesis = _status_value(right["identities"]["synthesis"])
    if left_synthesis is None or right_synthesis is None:
        return {"classification": "indeterminate", "reason": "synthesis_identity_unavailable"}
    if left_synthesis != right_synthesis or left["answer_hash"] != right["answer_hash"]:
        return {
            "classification": "indeterminate",
            "reason": "unsupported_answer_or_synthesis_drift",
        }
    return {"classification": "reproducible"}


def prune_expired_manifests(path: Path, *, now: str | datetime | None = None) -> int:
    """Deterministically remove expired local records without any sync path."""

    if not path.exists():
        return 0
    instant = (
        datetime.fromisoformat(now.replace("Z", "+00:00"))
        if isinstance(now, str)
        else (now or datetime.now(timezone.utc))
    )
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for record in records:
        _validate_manifest(record)
    kept = [
        record
        for record in records
        if datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00")) > instant
    ]
    removed = len(records) - len(kept)
    if removed:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            "".join(_canonical_json(record) + "\n" for record in kept), encoding="utf-8"
        )
        temporary.chmod(0o600)
        temporary.replace(path)
    return removed


def shadow_capture_enabled() -> bool:
    return os.getenv("ASK_PROVENANCE_MANIFEST_ENABLED", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


__all__ = [
    "AuthorizationSnapshot",
    "capture_ask_provenance",
    "compare_manifests",
    "prune_expired_manifests",
    "shadow_capture_enabled",
]
