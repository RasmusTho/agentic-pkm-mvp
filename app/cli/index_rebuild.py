from __future__ import annotations

import json
import os
import time
from typing import List
from uuid import UUID

import click

from app.components.embeddings import get_embedding_client
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


@click.group(help="Index maintenance commands.")
def index() -> None:
    """Index maintenance command group."""


@index.command("rebuild", help="Rebuild vector index embeddings from stored objects.")
@click.option("--profile", default="default", show_default=True, help="Embedding profile to use (default or deterministic/test)")
@click.option("--model", "override_model", default=None, help="Override embedding model for this run")
@click.option("--limit", type=int, default=None, help="Maximum number of objects to process")
@click.option("--dry-run", is_flag=True, default=False, help="Report counts without embedding")
def rebuild(profile: str, override_model: str | None, limit: int | None, dry_run: bool) -> None:
    os.environ.setdefault("LLM_PROVIDER", "mock")

    objects = _load_objects(limit)
    if not objects:
        click.echo("No objects available for indexing.")
        return

    client = get_embedding_client(profile=profile, override_model=override_model)
    identity = client.identity
    click.echo(
        f"Embedding {len(objects)} objects (provider={identity.provider} model={identity.model} dim={identity.dim} normalize={identity.normalize})"
    )

    if dry_run:
        click.echo("Dry run complete; no embeddings written.")
        return

    index_store = get_vector_index()
    processed = 0
    start = time.perf_counter()
    for domain_obj in objects:
        text = _extract_text(domain_obj.payload)
        if not text:
            continue
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
        processed += 1
        if processed % 25 == 0:
            click.echo(f"Indexed {processed}/{len(objects)} objects...")

    duration = time.perf_counter() - start
    click.echo(f"Rebuilt embeddings for {processed} objects in {duration:.2f}s")


