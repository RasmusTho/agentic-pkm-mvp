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
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Full, Queue
from typing import Any, Mapping, Sequence
from uuid import uuid4

import fcntl

logger = logging.getLogger(__name__)

SCHEMA = "ask_provenance_manifest.v1"
DEFAULT_PATH = Path("runtime/agent_memory/ask_provenance_manifests.jsonl")
DEFAULT_RETENTION_DAYS = 14
DEFAULT_MAX_RECORDS = 256
_JANITOR_PATHS: set[Path] = set()
_JANITOR_LOCK = threading.Lock()
_CAPTURE_QUEUE: Queue[dict[str, Any]] = Queue(maxsize=64)
_CAPTURE_WORKER_LOCK = threading.Lock()
_CAPTURE_WORKER_STARTED = False
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AuthorizationSnapshot:
    """The current, actual read context used to capture or compare a run."""

    scope_id: str
    principal_id: str | None
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
    path = explicit or (Path(configured).expanduser() if configured else DEFAULT_PATH)
    resolved = path.expanduser().resolve(strict=False)
    if explicit is None:
        lexical_root = (Path.cwd() / DEFAULT_PATH.parent).absolute()
        for candidate in (lexical_root, lexical_root.parent):
            if candidate.is_symlink():
                raise ValueError("ASK provenance runtime root cannot be a symlink")
        runtime_root = lexical_root.resolve(strict=False)
        if not resolved.is_relative_to(runtime_root):
            raise ValueError("ASK provenance path escapes its dedicated runtime root")
    elif "runtime" not in {part.casefold() for part in resolved.parts}:
        raise ValueError("explicit ASK provenance path must remain under a runtime directory")
    return resolved


def _validate_identity_record(record: Any, *, value_field: str) -> None:
    if not isinstance(record, Mapping):
        raise ValueError("identity record must be an object")
    if record.get("status") == "available":
        if (
            set(record) != {"status", value_field}
            or not isinstance(record.get(value_field), str)
            or not _DIGEST_PATTERN.fullmatch(record[value_field])
        ):
            raise ValueError("available identity requires a non-empty value")
        return
    if record.get("status") == "unavailable":
        if (
            set(record) != {"status", "reason"}
            or not isinstance(record.get("reason"), str)
            or not record["reason"]
        ):
            raise ValueError("unavailable identity requires a reason")
        return
    raise ValueError("identity status must be available or unavailable")


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
    for field in ("manifest_id", "captured_at", "expires_at"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            raise ValueError(f"invalid manifest field: {field}")
    for field in ("answer_hash", "query_hash"):
        if not isinstance(manifest.get(field), str) or not _DIGEST_PATTERN.fullmatch(
            manifest[field]
        ):
            raise ValueError(f"invalid manifest digest: {field}")
    captured_at = datetime.fromisoformat(manifest["captured_at"].replace("Z", "+00:00"))
    expires_at = datetime.fromisoformat(manifest["expires_at"].replace("Z", "+00:00"))
    if captured_at.utcoffset() is None or expires_at.utcoffset() is None:
        raise ValueError("manifest timestamps must be timezone-aware")
    if expires_at <= captured_at:
        raise ValueError("manifest expiry must follow capture")
    if not isinstance(manifest.get("ordered_evidence"), list):
        raise ValueError("ordered_evidence must be a list")
    authorization = manifest.get("authorization")
    if not isinstance(authorization, Mapping) or set(authorization) != {
        "scope_id",
        "principal_hash",
        "principal_unavailable_reason",
        "authorization_context_hash",
        "policy_hash",
    }:
        raise ValueError("invalid authorization snapshot")
    if not isinstance(authorization["scope_id"], str) or not authorization["scope_id"]:
        raise ValueError("scope identity unavailable")
    principal_hash = authorization["principal_hash"]
    principal_reason = authorization["principal_unavailable_reason"]
    if (principal_hash is None) == (principal_reason is None):
        raise ValueError("principal identity must be available xor unavailable")
    if principal_hash is not None and (
        not isinstance(principal_hash, str) or not _DIGEST_PATTERN.fullmatch(principal_hash)
    ):
        raise ValueError("invalid principal hash")
    if principal_reason is not None and (
        not isinstance(principal_reason, str) or not principal_reason
    ):
        raise ValueError("invalid principal unavailable reason")
    for field in ("authorization_context_hash", "policy_hash"):
        if not isinstance(authorization[field], str) or not _DIGEST_PATTERN.fullmatch(
            authorization[field]
        ):
            raise ValueError(f"invalid authorization field: {field}")
    for position, item in enumerate(manifest["ordered_evidence"]):
        if not isinstance(item, Mapping) or set(item) != {
            "position",
            "source_id_hash",
            "canonical_source_hash",
        }:
            raise ValueError("invalid ordered evidence")
        if item.get("position") != position:
            raise ValueError("evidence order is not canonical")
        if not isinstance(item.get("source_id_hash"), str) or not _DIGEST_PATTERN.fullmatch(
            item["source_id_hash"]
        ):
            raise ValueError("invalid evidence source hash")
        source_hash = item.get("canonical_source_hash")
        _validate_identity_record(source_hash, value_field="value")
    identities = manifest.get("identities")
    if not isinstance(identities, Mapping) or set(identities) != {
        "canonical_index",
        "synthesis",
    }:
        raise ValueError("invalid identity set")
    _validate_identity_record(identities["canonical_index"], value_field="value_hash")
    _validate_identity_record(identities["synthesis"], value_field="value_hash")
    encoded = _canonical_json(manifest)
    if "raw_text" in encoded or "source_ref" in encoded or "credential" in encoded:
        raise ValueError("forbidden raw field in ASK provenance manifest")


@contextmanager
def _exclusive_manifest_lock(path: Path):
    """Serialize read/retain/replace across threads and worker processes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        lock_path.chmod(0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _append_manifest(
    path: Path, manifest: Mapping[str, Any], *, max_records: int = DEFAULT_MAX_RECORDS
) -> None:
    # A configured vault/index destination would violate the local shadow-state
    # boundary.  The default and supported override are runtime-state paths.
    if any(part.casefold() in {"vault", "index"} for part in path.parts):
        raise ValueError("ASK provenance manifests cannot be stored in vault/index paths")
    _validate_manifest(manifest)
    with _exclusive_manifest_lock(path):
        existing = (
            [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
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
        # Publish the complete append atomically while the sidecar lock is held.
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
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Best-effort capture; every failure is isolated from the ASK result."""

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
            "answer_hash": _privacy_hash(answer, key),
            "query_hash": _privacy_hash(query, key),
            "authorization": {
                "scope_id": _normalize_scope(authorization.scope_id),
                "principal_hash": (
                    _privacy_hash(authorization.principal_id, key)
                    if authorization.principal_id
                    else None
                ),
                "principal_unavailable_reason": (
                    None if authorization.principal_id else "caller_principal_not_observed"
                ),
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
        _append_manifest(_manifest_path(path), manifest)
        return manifest
    except Exception as exc:
        logger.warning("ask.provenance capture skipped: %s", type(exc).__name__)
        return None


def schedule_ask_provenance_capture(**capture_kwargs: Any) -> None:
    """Detach local storage I/O from ASK's response-critical path.

    The daemon worker owns capture/storage failure isolation. Callers receive
    no manifest-derived state and never wait on locking, retention, or fsync.
    """

    try:
        path = _manifest_path(capture_kwargs.get("path"))
        _ensure_retention_janitor(path)
    except Exception as exc:
        logger.warning("ask.provenance scheduling skipped: %s", type(exc).__name__)
        return
    capture_kwargs["path"] = path
    _ensure_capture_worker()
    try:
        _CAPTURE_QUEUE.put_nowait(capture_kwargs)
    except Full:
        logger.warning("ask.provenance capture skipped: bounded_queue_full")


def _ensure_capture_worker() -> None:
    """Start the single bounded capture worker once per process."""

    global _CAPTURE_WORKER_STARTED
    with _CAPTURE_WORKER_LOCK:
        if _CAPTURE_WORKER_STARTED:
            return
        _CAPTURE_WORKER_STARTED = True

    def consume() -> None:
        while True:
            capture_kwargs = _CAPTURE_QUEUE.get()
            try:
                capture_ask_provenance(**capture_kwargs)
            finally:
                _CAPTURE_QUEUE.task_done()

    threading.Thread(
        target=consume,
        name="ask-provenance-capture-worker",
        daemon=True,
    ).start()


def _ensure_retention_janitor(path: Path) -> None:
    """Start one daemon janitor per local manifest file."""

    with _JANITOR_LOCK:
        if path in _JANITOR_PATHS:
            return
        _JANITOR_PATHS.add(path)

    def maintain() -> None:
        interval = max(60, int(os.getenv("ASK_PROVENANCE_RETENTION_SWEEP_SECONDS", "3600")))
        while True:
            time.sleep(interval)
            try:
                prune_expired_manifests(path)
            except Exception as exc:
                logger.warning("ask.provenance retention sweep skipped: %s", type(exc).__name__)

    threading.Thread(
        target=maintain,
        name="ask-provenance-retention",
        daemon=True,
    ).start()


def start_ask_provenance_runtime() -> None:
    """Initialize pruning and bounded workers from application lifespan."""

    if not shadow_capture_enabled():
        return
    try:
        path = _manifest_path(None)
        prune_expired_manifests(path)
        _ensure_retention_janitor(path)
        _ensure_capture_worker()
    except Exception as exc:
        logger.warning("ask.provenance runtime init skipped: %s", type(exc).__name__)


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
    now: datetime | None = None,
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

    instant = now or datetime.now(timezone.utc)
    if instant.utcoffset() is None:
        return {"classification": "indeterminate", "reason": "comparison_time_invalid"}
    if any(
        datetime.fromisoformat(manifest["expires_at"].replace("Z", "+00:00")) <= instant
        for manifest in (left, right)
    ):
        return {"classification": "indeterminate", "reason": "manifest_expired"}
    current_principal = current_authorization.principal_id
    if (
        left["authorization"]["principal_hash"] is None
        or right["authorization"]["principal_hash"] is None
        or not current_principal
    ):
        return {"classification": "indeterminate", "reason": "principal_identity_unavailable"}

    current = {
        "scope_id": _normalize_scope(current_authorization.scope_id),
        "principal_hash": _privacy_hash(current_principal, key),
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
    if left["query_hash"] != right["query_hash"]:
        return {"classification": "indeterminate", "reason": "query_changed"}

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

    with _exclusive_manifest_lock(path):
        if not path.exists():
            return 0
        instant = (
            datetime.fromisoformat(now.replace("Z", "+00:00"))
            if isinstance(now, str)
            else (now or datetime.now(timezone.utc))
        )
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
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
                "".join(_canonical_json(record) + "\n" for record in kept),
                encoding="utf-8",
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
    "schedule_ask_provenance_capture",
    "shadow_capture_enabled",
    "start_ask_provenance_runtime",
]
