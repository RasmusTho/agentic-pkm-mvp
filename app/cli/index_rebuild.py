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
from app.index.artifact_metadata import (
    build_indexed_unit_payload,
    canonicalize_indexable_text,
    compute_payload_content_hash,
)
from app.llm.embed_queue import EmbedDeadLetterError, embed_with_retry
from app import objects as domain_objects
from app.outbox.events import DEFAULT_EMBEDDING_VIEW
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
    return canonicalize_indexable_text(payload)


def _load_objects(limit: int | None) -> Tuple[List[domain_objects.DomainObject], str]:
    store = domain_objects.ObjectStore()
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
    domain_obj: domain_objects.DomainObject,
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

        indexed_payload = dict(domain_obj.payload or {})
        indexed_payload["content"] = text
        indexed_payload["text"] = text

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
                payload=build_indexed_unit_payload(
                    object_id=UUID(str(domain_obj.uuid)),
                    kind=str(domain_obj.kind or "note"),
                    source_ref=str(domain_obj.source_ref or ""),
                    payload=indexed_payload,
                    text=text,
                    embedding_identity=identity,
                ),
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


# ---------------------------------------------------------------------------
# index reconcile (EMBEDREL-06 Phase B, section (c))
# ---------------------------------------------------------------------------

_RECONCILE_DEFAULT_FAILURES_PATH = Path("/app/tmp/index-reconcile-failures.jsonl")
_RECONCILE_FAILURES_PATH_ENV = "INDEX_RECONCILE_FAILURES_PATH"


def _reconcile_failures_path(path: Path | None) -> Path:
    if path is not None:
        return path
    env_value = os.getenv(_RECONCILE_FAILURES_PATH_ENV)
    if env_value:
        return Path(env_value)
    return _RECONCILE_DEFAULT_FAILURES_PATH


def _mismatched_rows(primary: EmbeddingIdentity, limit: int | None) -> List[dict]:
    """Return store_vector_index rows whose full identity differs from ``primary``.

    Selection keys on the full ``(provider, model, dim, normalize)`` tuple — not
    provider alone — so a same-provider model/normalize swap at the same dim is a
    reconcile candidate too (CTI-1). Rows with a NULL provider (pre-migration) are
    treated as mismatched so they converge to the primary identity on reconcile.
    """
    from app.stores.pg import _connect  # local import: pg backend is optional

    with _connect() as conn:
        with conn.cursor() as cur:
            sql_text = """
                SELECT object_id, kind, source_ref, payload,
                       provider, model, dim, normalize
                FROM store_vector_index
                WHERE provider IS DISTINCT FROM %s
                   OR model IS DISTINCT FROM %s
                   OR dim IS DISTINCT FROM %s
                   OR normalize IS DISTINCT FROM %s
                ORDER BY object_id
            """
            params: list = [primary.provider, primary.model, primary.dim, primary.normalize]
            if limit is not None:
                sql_text += " LIMIT %s"
                params.append(limit)
            cur.execute(sql_text, params)
            return list(cur.fetchall())


def _stale_content_hash_rows(limit: int | None) -> List[dict]:
    """Return store_vector_index rows whose stored content_hash no longer
    matches the current store_objects text (KERNEL-06, #2768).

    Rows with no recorded content_hash (pre-KERNEL-06 rows) are excluded here
    — they need a rebuild to acquire a hash, not a content-drift re-embed;
    ``inspect_pg_content_hash_staleness`` reports them separately as
    ``unstamped_count`` for visibility.
    """
    from app.stores.pg import _connect  # local import: pg backend is optional

    with _connect() as conn:
        with conn.cursor() as cur:
            sql_text = """
                SELECT v.object_id AS object_id, v.kind AS kind, v.source_ref AS source_ref,
                       v.payload AS payload, v.provider AS provider, v.model AS model,
                       v.dim AS dim, v.normalize AS normalize,
                       v.payload->'provenance'->>'content_hash' AS stored_hash,
                       o.payload AS current_payload
                FROM store_vector_index AS v
                JOIN store_objects AS o ON o.object_id = v.object_id
                WHERE v.payload->'provenance'->>'content_hash' IS NOT NULL
                ORDER BY v.object_id
            """
            cur.execute(sql_text)
            candidates = list(cur.fetchall())

    stale = [
        row
        for row in candidates
        if compute_payload_content_hash(dict(row.get("current_payload") or {}))
        != row.get("stored_hash")
    ]
    if limit is not None:
        stale = stale[:limit]
    return stale


def _present_non_indexable_rows(limit: int | None) -> List[dict]:
    """Return derived rows whose present source now has no canonical text.

    This candidate class is independent of identity and content hash.  Legacy
    panel-bearing vectors can already carry the current primary identity and a
    hash of the empty canonical body, so neither ordinary reconcile selector
    can prove that their stale retrieval bytes must be purged.
    """
    from app.stores.pg import _connect  # local import: pg backend is optional

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT v.object_id AS object_id, v.kind AS kind,
                       v.source_ref AS source_ref, v.payload AS payload,
                       v.provider AS provider, v.model AS model,
                       v.dim AS dim, v.normalize AS normalize,
                       o.payload AS current_payload
                FROM store_vector_index AS v
                JOIN store_objects AS o ON o.object_id = v.object_id
                ORDER BY v.object_id
                """
            )
            candidates = list(cur.fetchall())

    rows = [
        row
        for row in candidates
        if not canonicalize_indexable_text(dict(row.get("current_payload") or {}))
    ]
    if limit is not None:
        rows = rows[:limit]
    return rows


def _reconcile_object_payload(object_id, vector_payload: dict | None) -> Tuple[dict, bool]:
    """Resolve the authoritative payload to re-embed for a row.

    Prefer the authoritative ``store_objects`` payload (the durable object of
    record); fall back to the vector-index row payload when the object row is
    absent, so an orphaned index row can still be reconciled.
    """
    from app.stores.pg import _connect  # local import: pg backend is optional

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM store_objects WHERE object_id = %s LIMIT 1",
                (object_id,),
            )
            row = cur.fetchone()
    if row is not None:
        return dict(row.get("payload") or {}), True
    return dict(vector_payload or {}), False


@index.command("reconcile", help="Re-embed non-primary-identity vectors under the primary identity (converge a mixed index).")
@click.option("--backend", type=click.Choice(["memory", "pg"]), default=None, help="Override STORE_BACKEND for this run")
@click.option("--profile", default="default", show_default=True, help="Embedding profile to use for the primary identity")
@click.option("--limit", type=int, default=None, help="Maximum number of mismatched rows to process")
@click.option("--dry-run", is_flag=True, default=False, help="Report the mismatch count without re-embedding")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit machine-readable JSON summary")
@click.option("--strict/--no-strict", default=False, help="Exit non-zero when errors occur")
@click.option("--failures-path", type=click.Path(path_type=Path), default=None, help="Path to JSONL failure report (env INDEX_RECONCILE_FAILURES_PATH)")
@click.option("--max-retries", type=int, default=None, help="Max retry attempts for embed/upsert (default 2)")
def reconcile(
    backend: str | None,
    profile: str,
    limit: int | None,
    dry_run: bool,
    as_json: bool,
    strict: bool,
    failures_path: Path | None,
    max_retries: int | None,
) -> None:
    """Converge a mixed-identity vector index back to a single (primary) identity.

    Idempotency: candidate rows are selected by full-identity inequality against the
    primary identity. After a row is upserted under the primary identity it no longer
    matches the predicate, so a re-run on a converged index is a no-op.

    Resumability / no-corruption: rows are processed one at a time and each upsert is
    an atomic INSERT ... ON CONFLICT DO UPDATE that commits on its own connection. If
    the run is interrupted (SIGINT, crash, embed failure), already-processed rows carry
    the primary identity and unprocessed rows retain their prior (fallback) identity —
    the index is still mixed but never missing a vector or partially written. A row is
    never deleted because an embed/upsert failed; a failed re-embed leaves the original
    fallback vector in place and is dead-lettered for retry. The one semantic deletion
    is a derived vector
    whose present authoritative source has become canonically non-indexable;
    explicit reconcile purges that row so retrieval cannot serve stale bytes.
    """
    if backend:
        os.environ["STORE_BACKEND"] = backend

    resolved_backend = resolve_store_backend()
    summary: Dict[str, object] = {
        "backend": resolved_backend,
        "total_mismatched": 0,
        "total_present_non_indexable": 0,
        "reconciled": 0,
        "purged_non_indexable": 0,
        "skipped": 0,
        "errors": [],
    }

    # Reconcile is a Postgres-only migration primitive: the per-row provider column
    # and the reconcilable-fallback write path exist only on PgVectorIndex. The memory
    # backend has no per-row identity, so there is nothing to converge.
    if resolved_backend != "pg":
        summary["message"] = "index reconcile requires the Postgres backend (per-vector identity columns)."
        _emit_reconcile_summary(summary, as_json)
        if strict:
            raise SystemExit(2)
        return

    path = _reconcile_failures_path(failures_path)
    _prepare_failures_path(path)
    retry_limit = _resolve_max_retries(max_retries)

    client = get_embedding_client(profile=profile)
    primary = client.identity
    identity_info = _identity_summary(primary)
    summary["identity"] = identity_info

    identity_rows = _mismatched_rows(primary, limit)
    # KERNEL-06 (#2768): also re-embed rows whose content_hash no longer
    # matches the current store_objects text — incremental, content-drift
    # repair, distinct from (and additive to) identity convergence above.
    # De-dupe by object_id: a row already selected for identity convergence
    # is re-embedded once (the identity-convergence upsert also refreshes the
    # content_hash via build_indexed_unit_payload, so it is not stale after).
    seen_ids = {row["object_id"] for row in identity_rows}
    stale_content_rows = [
        row for row in _stale_content_hash_rows(limit) if row["object_id"] not in seen_ids
    ]
    seen_ids.update(row["object_id"] for row in stale_content_rows)
    present_non_indexable_rows = _present_non_indexable_rows(limit)
    additional_non_indexable_rows = [
        row for row in present_non_indexable_rows if row["object_id"] not in seen_ids
    ]
    rows = identity_rows + stale_content_rows + additional_non_indexable_rows
    summary["total_mismatched"] = len(identity_rows)
    summary["total_stale_content_hash"] = len(stale_content_rows)
    summary["total_present_non_indexable"] = len(present_non_indexable_rows)

    if not as_json:
        click.echo(
            f"Reconciling to primary identity provider={primary.provider} model={primary.model} "
            f"dim={primary.dim} normalize={primary.normalize}"
        )
        click.echo(f"Mismatched rows: {len(identity_rows)}")
        click.echo(f"Stale content-hash rows: {len(stale_content_rows)}")
        click.echo(f"Present non-indexable source rows: {len(present_non_indexable_rows)}")

    if dry_run:
        summary["message"] = "Dry run complete; no vectors re-embedded or purged."
        _emit_reconcile_summary(summary, as_json)
        return

    index_store = get_vector_index()
    start = time.perf_counter()

    for row in rows:
        object_id = row["object_id"]
        kind = str(row.get("kind") or "note")
        source_ref = str(row.get("source_ref") or "")
        vector_payload = dict(row.get("payload") or {})
        source_payload, authoritative_source_present = _reconcile_object_payload(
            object_id, vector_payload
        )
        domain_obj = domain_objects.DomainObject(
            uuid=str(object_id),
            kind=kind,
            source_ref=source_ref,
            payload=source_payload,
            created_at=datetime.now(timezone.utc),
        )

        text = _extract_text(source_payload)
        if not text:
            if authoritative_source_present:
                try:
                    classification = (
                        index_store.purge_vector_if_present_source_non_indexable(
                            UUID(str(object_id)), view=DEFAULT_EMBEDDING_VIEW
                        )
                    )
                except Exception as purge_exc:
                    _record_failure(
                        summary,
                        path,
                        identity_info,
                        domain_obj,
                        "purge",
                        purge_exc,
                        1,
                        False,
                    )
                    continue

                if classification.source_present and not classification.source_indexable:
                    summary["purged_non_indexable"] = int(
                        summary["purged_non_indexable"]
                    ) + int(classification.purged)
                    continue

                if classification.source_present:
                    # The source became indexable after the candidate read.
                    # Reclassify and embed the locked-read payload instead of
                    # deleting its derived row from stale evidence.
                    source_payload = dict(classification.source_payload or {})
                else:
                    # The source disappeared after the candidate read.  The
                    # present-source purge contract no longer applies; retain
                    # and, where possible, reconcile from vector fallback.
                    source_payload = vector_payload
                domain_obj = domain_objects.DomainObject(
                    uuid=str(object_id),
                    kind=kind,
                    source_ref=source_ref,
                    payload=source_payload,
                    created_at=datetime.now(timezone.utc),
                )
                text = _extract_text(source_payload)

            if not text:
                summary["skipped"] = int(summary["skipped"]) + 1
                continue

        # ``store_vector_index`` is a derived retrieval projection.  Keep both
        # compatibility aliases bound to the exact producer-selected source
        # text so a successful reconcile cannot leave retrieval serving a
        # stale legacy ``text`` value while provenance already reports clean.
        indexed_payload = dict(source_payload)
        indexed_payload["content"] = text
        indexed_payload["text"] = text

        embedding: list | None = None
        try:
            embedding = embed_with_retry(
                text,
                dim=primary.dim,
                object_id=str(object_id),
                embed_callable=lambda t=text: client.embed_text(t),
                max_attempts=retry_limit + 1,
            )
        except EmbedDeadLetterError as _dead_exc:
            _record_failure(summary, path, identity_info, domain_obj, "embed", _dead_exc, retry_limit + 1, True)
            continue
        except Exception as _embed_exc:
            _record_failure(summary, path, identity_info, domain_obj, "embed", _embed_exc, 1, False)
            continue

        def _upsert_action(
            _oid=object_id,
            _kind=kind,
            _source_ref=source_ref,
            _payload=indexed_payload,
            _text=text,
            _embedding=embedding,
        ) -> None:
            # Ordinary (non-fallback) upsert: the requested identity IS the primary
            # identity, so the index-level guard passes and the row is rewritten with
            # the primary (provider, model, dim, normalize) tuple in place.
            index_store.upsert(
                object_id=UUID(str(_oid)),
                kind=_kind,
                source_ref=_source_ref,
                payload=build_indexed_unit_payload(
                    object_id=UUID(str(_oid)),
                    kind=_kind,
                    source_ref=_source_ref,
                    payload=_payload,
                    text=_text,
                    embedding_identity=primary,
                ),
                embedding=_embedding,
                model=primary.model,
                identity=primary,
            )

        _, upsert_attempts, upsert_exc, upsert_retryable = _attempt_with_retries(_upsert_action, retry_limit)
        if upsert_exc is not None:
            _record_failure(summary, path, identity_info, domain_obj, "upsert", upsert_exc, upsert_attempts, upsert_retryable)
            continue

        summary["reconciled"] = int(summary["reconciled"]) + 1

    summary["duration_ms"] = int((time.perf_counter() - start) * 1000)
    _emit_reconcile_summary(summary, as_json)
    if strict and summary.get("error_count", 0) > 0:
        raise SystemExit(2)


def _emit_reconcile_summary(summary: Dict[str, object], as_json: bool) -> None:
    summary["error_count"] = len(summary.get("errors", []))
    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if summary.get("message"):
        click.echo(str(summary["message"]))
    click.echo(
        f"total_mismatched={summary.get('total_mismatched', 0)} "
        f"total_stale_content_hash={summary.get('total_stale_content_hash', 0)} "
        f"total_present_non_indexable={summary.get('total_present_non_indexable', 0)} "
        f"reconciled={summary.get('reconciled', 0)} "
        f"skipped={summary.get('skipped', 0)} "
        f"errors={summary['error_count']}"
    )
