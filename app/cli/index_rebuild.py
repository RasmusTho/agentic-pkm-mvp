from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List
from uuid import UUID

import click

from app.components.embeddings import EmbeddingIdentity, get_embedding_client
from app.store import object_store as legacy_store
from app.stores import get_vector_index


def _extract_text(payload: dict | None) -> str:
    data = payload or {}
    for key in ("content", "text", "raw_text"):
        val = data.get(key)
        if val:
            return str(val)
    return ""


def _memory_objects(limit: int | None) -> List[legacy_store.DomainObject]:
    objs = list(legacy_store._MEMORY_STORE.values())
    if limit is not None:
        return objs[:limit]
    return objs


def _db_objects(limit: int | None) -> List[legacy_store.DomainObject]:
    if not legacy_store._pg_available():
        return []
    conn = legacy_store._db_connect()
    if conn is None:
        return []
    query = """
        SELECT id, uuid, kind, source_ref, payload, created_at
        FROM objects
        ORDER BY created_at ASC
    """
    params: tuple = ()
    if limit is not None:
        query += " LIMIT %s"
        params = (limit,)
    records: List[legacy_store.DomainObject] = []
    with conn:
        with conn.cursor() as cur:
            try:
                cur.execute(query, params)
            except Exception:
                return []
            rows = cur.fetchall()
            for row in rows:
                payload = row[4]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                records.append(
                    legacy_store.DomainObject(
                        uuid=str(row[1] or row[0]),
                        kind=row[2],
                        payload=payload or {},
                        source_ref=row[3],
                        created_at=row[5],
                    )
                )
    return records


def _load_objects(limit: int | None) -> List[legacy_store.DomainObject]:
    memory_objs = _memory_objects(limit)
    if memory_objs:
        return memory_objs
    return _db_objects(limit)


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
def rebuild(
    backend: str | None,
    outbox_path: Path | None,
    profile: str,
    override_model: str | None,
    limit: int | None,
    dry_run: bool,
    as_json: bool,
    strict: bool,
) -> None:
    if backend:
        os.environ["STORE_BACKEND"] = backend
    if outbox_path:
        os.environ["INDEX_OUTBOX_PATH"] = str(outbox_path)

    os.environ.setdefault("LLM_PROVIDER", "mock")

    objects = _load_objects(limit)
    summary: Dict[str, object] = {
        "total_objects": len(objects),
        "processed": 0,
        "skipped": 0,
        "errors": [],
    }

    if not objects:
        summary["message"] = "No objects available for indexing."
        _emit_summary(summary, as_json)
        return

    client = get_embedding_client(profile=profile, override_model=override_model)
    identity = client.identity
    summary["identity"] = {
        "provider": identity.provider,
        "model": identity.model,
        "dim": identity.dim,
        "normalize": identity.normalize,
    }

    if not as_json:
        click.echo(
            f"Embedding {len(objects)} objects (provider={identity.provider} model={identity.model} dim={identity.dim} normalize={identity.normalize})"
        )

    if dry_run:
        summary["message"] = "Dry run complete; no embeddings written."
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
        try:
            embedding = client.embed_text(text)
            index_store.upsert(
                object_id=UUID(str(domain_obj.uuid)),
                kind=str(domain_obj.kind or "note"),
                source_ref=str(domain_obj.source_ref or ""),
                payload=dict(domain_obj.payload or {}),
                embedding=embedding,
                model=identity.model,
                identity=identity,
            )
            summary["processed"] = int(summary["processed"]) + 1
        except Exception as exc:  # pragma: no cover - error path
            summary.setdefault("errors", []).append(str(exc))

    duration = time.perf_counter() - start
    summary["duration_seconds"] = round(duration, 2)

    if not as_json:
        if summary.get("errors"):
            click.echo(f"Completed with {len(summary['errors'])} error(s) after {duration:.2f}s")
        else:
            click.echo(
                f"Rebuilt embeddings for {summary['processed']} objects in {duration:.2f}s"
            )

    _emit_summary(summary, as_json)
    if strict and summary.get("errors"):
        raise SystemExit(2)


def _emit_summary(summary: Dict[str, object], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        if summary.get("message"):
            click.echo(str(summary["message"]))
        click.echo(
            f"total={summary.get('total_objects', 0)} processed={summary.get('processed', 0)} skipped={summary.get('skipped', 0)} errors={len(summary.get('errors', []))}"
        )
