from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Tuple, TypeVar
from uuid import UUID

import click

from app.components.embeddings import EmbeddingIdentity, get_embedding_client
from app.llm.embed_queue import EmbedDeadLetterError, embed_with_retry
from app.store import object_store as legacy_store
from app.stores import get_vector_index, resolve_store_backend

FAILURES_PATH_ENV = "INDEX_REBUILD_FAILURES_PATH"
MAX_RETRIES_ENV = "INDEX_REBUILD_MAX_RETRIES"
_DEFAULT_FAILURES_PATH = Path("/app/tmp/index-rebuild-failures.jsonl")
_DEFAULT_MAX_RETRIES = 2
_T = TypeVar("_T")
_RETRYABLE_TYPES = (ConnectionError, TimeoutError)
_RETRYABLE_KEYWORDS = {
    "timeout",
    "temporarily",
    "temporary",
    "rate limit",
    "rate-limited",
    "throttl",
    "deadlock",
    "locked",
    "connection reset",
    "429",
}
_RETRYABLE_NAMES = {"SerializationFailure", "DeadlockDetected", "TooManyRequests"}


def _extract_text(payload: dict | None) -> str:
    data = payload or {}
    for key in ("content", "text", "raw_text"):
        val = data.get(key)
        if val:
            return str(val)
    return ""


def _load_objects(limit: int | None) -> Tuple[List[legacy_store.DomainObject], str]:
    store = legacy_store.ObjectStore()
    objects = store.list_objects(limit=limit or 1000000)
    backend = resolve_store_backend()
    table = "memory" if backend == "memory" else "store_objects"
    return objects, table


def _maybe_reset_pg_index(index_store, identity: EmbeddingIdentity, *, as_json: bool) -> None:
    try:
        from app.stores.pg import PgVectorIndex, _connect, _load_index_identity, reset_vector_index
    except Exception:
        return
    if not isinstance(index_store, PgVectorIndex):
        return
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                stored = _load_index_identity(cur)
                if stored is None or stored != identity:
                    reset_vector_index(cur)
    except Exception as exc:
        if not as_json:
            click.echo(f"Warning: failed to reset pg vector index: {exc}")


def _prepare_failures_path(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_failures_path(path: Path | None) -> Path:
    if path is not None:
        return path
    env_value = os.getenv(FAILURES_PATH_ENV)
    if env_value:
        return Path(env_value)
    return _DEFAULT_FAILURES_PATH


def _resolve_max_retries(value: int | None) -> int:
    if value is not None:
        return max(value, 0)
    env_value = os.getenv(MAX_RETRIES_ENV)
    if env_value:
        try:
            parsed = int(env_value)
        except Exception:
            return _DEFAULT_MAX_RETRIES
        return max(parsed, 0)
    return _DEFAULT_MAX_RETRIES


def _identity_summary(identity: EmbeddingIdentity) -> Dict[str, object]:
    return {
        "provider": identity.provider,
        "model": identity.model,
        "dim": identity.dim,
        "normalize": identity.normalize,
    }


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, _RETRYABLE_TYPES):
        return True
    name = type(exc).__name__
    if name in _RETRYABLE_NAMES:
        return True
    msg = str(exc).lower()
    return any(keyword in msg for keyword in _RETRYABLE_KEYWORDS)


def _attempt_with_retries(action: Callable[[], _T], max_retries: int) -> Tuple[_T | None, int, Exception | None, bool]:
    attempts = 0
    while True:
        attempts += 1
        try:
            return action(), attempts, None, False
        except Exception as exc:
            retryable = _is_retryable_exception(exc)
            if not retryable or attempts > max_retries:
                return None, attempts, exc, retryable


def _write_failure_record(path: Path, payload: Dict[str, object]) -> None:
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _record_failure(
    summary: Dict[str, object],
    path: Path,
    identity: Dict[str, object],
    domain_obj: legacy_store.DomainObject,
    stage: str,
    exc: Exception,
    attempts: int,
    retryable: bool,
) -> None:
    error_entry = {
        "object_id": str(domain_obj.uuid),
        "kind": str(domain_obj.kind or "note"),
        "source_ref": str(domain_obj.source_ref or ""),
        "stage": stage,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "retryable": retryable,
        "attempts": attempts,
    }
    summary.setdefault("errors", []).append(error_entry)
    failure_record = {
        "timestamp": _current_timestamp(),
        "identity": identity,
        **error_entry,
    }
    _write_failure_record(path, failure_record)


def _emit_summary(summary: Dict[str, object], as_json: bool) -> None:
    summary["error_count"] = len(summary.get("errors", []))
    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if summary.get("message"):
        click.echo(str(summary["message"]))
    click.echo(
        f"total={summary.get('total_objects', 0)} processed={summary.get('processed', 0)} skipped={summary.get('skipped', 0)} errors={summary['error_count']}"
    )


@click.group(help="Index maintenance commands.")
def index() -> None:
    """Index maintenance command group."""


@index.command("rebuild", help="Rebuild vector index embeddings from stored objects.")
@click.option("--backend", type=click.Choice(["memory", "pg"]), default=None, help="Override STORE_BACKEND for this run")
@click.option("--outbox", "outbox_path", type=click.Path(path_type=Path), default=None, help="Override INDEX_OUTBOX_PATH")
@click.option("--profile", default="default", show_default=True, help="Embedding profile to use (default or deterministic/test)")
@click.option("--model", "override_model", default=None, help="Override embedding model for this run")
@click.option("--limit", type=int, default=None, help="Maximum number of objects to process")
@click.option("--dry-run", is_flag=True, default=False, help="Report counts without embedding")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON summary")
@click.option("--strict/--no-strict", default=False, help="Exit non-zero when errors occur")
@click.option("--failures-path", type=click.Path(path_type=Path), default=None, help="Path to JSONL failure report (env INDEX_REBUILD_FAILURES_PATH)")
@click.option("--max-retries", type=int, default=None, help="Max retry attempts for embed/upsert (env INDEX_REBUILD_MAX_RETRIES, default 2)")
def rebuild(
    backend: str | None,
    outbox_path: Path | None,
    profile: str,
    override_model: str | None,
    limit: int | None,
    dry_run: bool,
    as_json: bool,
    strict: bool,
    failures_path: Path | None,
    max_retries: int | None,
) -> None:
    if backend:
        os.environ["STORE_BACKEND"] = backend
    if outbox_path:
        os.environ["INDEX_OUTBOX_PATH"] = str(outbox_path)

    os.environ.setdefault("LLM_PROVIDER", "mock")

    path = _resolve_failures_path(failures_path)
    _prepare_failures_path(path)
    retry_limit = _resolve_max_retries(max_retries)

    objects, object_table = _load_objects(limit)
    summary: Dict[str, object] = {
        "total_objects": len(objects),
        "processed": 0,
        "skipped": 0,
        "errors": [],
        "failures_path": str(path),
        "object_table": object_table,
        "backend": resolve_store_backend(),
    }

    client = get_embedding_client(profile=profile, override_model=override_model)
    identity = client.identity
    identity_info = _identity_summary(identity)
    summary["identity"] = identity_info

    if not objects:
        summary["message"] = "No objects available for indexing."
        summary["duration_ms"] = 0
        _emit_summary(summary, as_json)
        return

    if not as_json:
        click.echo(
            f"Embedding {len(objects)} objects (provider={identity.provider} model={identity.model} dim={identity.dim} normalize={identity.normalize})"
        )

    if dry_run:
        summary["message"] = "Dry run complete; no embeddings written."
        summary["duration_ms"] = 0
        _emit_summary(summary, as_json)
        return

    index_store = get_vector_index()
    _maybe_reset_pg_index(index_store, identity, as_json=as_json)
    start = time.perf_counter()

    for domain_obj in objects:
        text = _extract_text(domain_obj.payload)
        if not text:
            summary["skipped"] = int(summary["skipped"]) + 1
            continue

        embedding: list | None = None
        try:
            embedding = embed_with_retry(
                text,
                dim=identity.dim,
                object_id=str(domain_obj.uuid),
                # Retry the resolved client so non-registry providers (deterministic/
                # test/offline profiles) still rebuild; _embed_single only knows the
                # PROVIDER_REGISTRY adapters and would fail every deterministic object.
                embed_callable=lambda: client.embed_text(text),
                # Honor the rebuild's own retry budget (--max-retries / env) for embeds,
                # not just EMBED_RETRY_MAX. retry_limit is "retries", so attempts = +1.
                max_attempts=retry_limit + 1,
            )
        except EmbedDeadLetterError as _dead_exc:
            _record_failure(
                summary,
                path,
                identity_info,
                domain_obj,
                "embed",
                _dead_exc,
                retry_limit + 1,
                True,
            )
            continue
        except Exception as _embed_exc:
            _record_failure(
                summary,
                path,
                identity_info,
                domain_obj,
                "embed",
                _embed_exc,
                1,
                False,
            )
            continue

        def _upsert_action() -> None:
            index_store.upsert(
                object_id=UUID(str(domain_obj.uuid)),
                kind=str(domain_obj.kind or "note"),
                source_ref=str(domain_obj.source_ref or ""),
                payload=dict(domain_obj.payload or {}),
                embedding=embedding,
                model=identity.model,
                identity=identity,
            )

        _, upsert_attempts, upsert_exc, upsert_retryable = _attempt_with_retries(_upsert_action, retry_limit)
        if upsert_exc is not None:
            _record_failure(
                summary,
                path,
                identity_info,
                domain_obj,
                "upsert",
                upsert_exc,
                upsert_attempts,
                upsert_retryable,
            )
            continue

        summary["processed"] = int(summary["processed"]) + 1

    duration_ms = int((time.perf_counter() - start) * 1000)
    summary["duration_ms"] = duration_ms
    _emit_summary(summary, as_json)
    if strict and summary.get("error_count", 0) > 0:
        raise SystemExit(2)
