from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.agents.classifier.agent import run as classify_run
from app.agents.normalizer.agent import run as normalize_run
from app.agents.panel.filters import strip_ai_panels
from app.ingest.episode_ref import episode_ref_from_frontmatter
from app.index.outbox import append_jsonl
from app.observability.ingest_meta import record_ingest_failure, record_ingest_success
from app.observability.log import with_trace_id
from app.search.service import ingest_object as index_ingest_object
from app.stores import get_object_store, resolve_store_backend
from app.rebuildability import canonical_product_source_text, product_replay_provenance
from app.stores.provider import get_stores
from app.objects import resolve_canonical_object_id

logger = logging.getLogger(__name__)


def _stable_vault_root_object_id(
    path: Path, *, vault_root: Path, frontmatter: dict, source_body: str = ""
) -> str:
    """Resolve one canonical Product identity for a root-ingested retained note."""
    from app.ingest.vault_alpha import (
        resolve_vault_note_identity,
    )

    identity = resolve_vault_note_identity(
        path,
        vault_root=vault_root,
        frontmatter=frontmatter,
        body=source_body,
    )
    return resolve_canonical_object_id(identity.note_uuid)


def iter_vault_root_markdown(root: Path, limit: int | None = None) -> Iterable[Path]:
    """
    Yield up to `limit` markdown files in the vault root (non-recursive).
    Only regular `.md` files; ignore hidden files and directories.
    """
    if not root.exists() or not root.is_dir():
        return []
    files = [
        p
        for p in root.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() == ".md"
    ]
    files.sort(key=lambda p: p.name.lower())
    if limit is not None:
        files = files[:max(limit, 0)]
    return files


def product_replay_for_vault_note(
    note_path: Path, *, vault_root: Path, source_text: str | None = None
) -> dict[str, str]:
    """Build the Product replay tuple for a vault-root producer note."""
    root = vault_root.expanduser().resolve()
    path = note_path.expanduser().resolve()
    source_identity = path.relative_to(root).as_posix()
    return product_replay_provenance(
        source_identity=source_identity,
        source_text=canonical_product_source_text(
            source_text if source_text is not None else path.read_text(encoding="utf-8")
        ),
        allow_empty_source=True,
    )


def _ingest_file(path: Path, *, trace_id: str, vault_root: Path | None = None) -> str:
    from scripts.yaml_roundtrip import load_frontmatter

    text = path.read_text(encoding="utf-8")
    frontmatter, _body = load_frontmatter(text)
    stripped_text = strip_ai_panels(text)
    root = (vault_root or path.parent).expanduser().resolve()
    replay = product_replay_for_vault_note(path, vault_root=root, source_text=text)
    # normalize_run normally persists its freshly allocated UUID. This producer owns a
    # stable retained-source identity on PG, so suppress the normalizer's transient
    # persistence there; the canonical upsert below is the only projection row. The
    # explicit memory backend has no shared canonical provider behind get_stores(),
    # so retain the legacy normalizer row there for classifier compatibility.
    store_backend = resolve_store_backend()
    normalize_res = normalize_run(
        str(path), trace_id=trace_id, persist=store_backend != "pg"
    )
    sanitize_normalize = dict(normalize_res)
    payload_copy = dict(normalize_res.get("payload") or {})
    if "raw_text" in payload_copy:
        payload_copy["raw_text"] = stripped_text
    payload_copy.setdefault("text", stripped_text)
    payload_copy.setdefault("source_path", str(path))
    payload_copy.setdefault("source_ref", str(path))
    sanitize_normalize["payload"] = payload_copy
    normalized_object_id = str(
        normalize_res.get("object_id") or normalize_res.get("uuid") or ""
    ).strip()
    if not normalized_object_id:
        raise RuntimeError("normalize did not return object_id")
    object_id = (
        _stable_vault_root_object_id(
            path, vault_root=root, frontmatter=frontmatter, source_body=_body
        )
        if store_backend == "pg"
        else normalized_object_id
    )
    core6 = dict(normalize_res.get("core6") or {})
    core6["id"] = object_id

    try:
        object_uuid = uuid.UUID(object_id)
    except Exception:
        object_uuid = uuid.uuid4()

    title = (normalize_res.get("core6") or {}).get("title")
    # Carry the note's vault-canonical episode_ref into the DB projection (ERE-03/ERE-05,
    # invariant->producers): index_ingest_object + store.put below full-overwrite the payload
    # column, so an absent episode_ref would blind-drop a stamped binding on reingest (round-3
    # audit: this producer was missed in round 2).
    ep_ref = episode_ref_from_frontmatter(frontmatter)
    payload = {
        "title": title,
        "origin": "vault",
        "source": str(path),
        "episode_ref": ep_ref,
        "replay": replay,
    }
    # canonical_payload also lands in the canonical store_objects table: objects_store.upsert ->
    # PgObjects.upsert -> PgObjectStore.put, a full-overwrite of the store_objects payload column
    # (not just the legacy `objects` table). It MUST carry episode_ref too (round-5 finding): the
    # store.put below that carries it is in a try/except-log-continue, so if that throws, the
    # canonical_payload row is the surviving store_objects row -- an absent episode_ref there is
    # blind-dropped to 'unbound' on the next cold rebuild (index_rebuild reads store_objects payload).
    canonical_payload = {
        **payload_copy,
        "core6": core6,
        "episode_ref": ep_ref,
        "replay": replay,
    }
    objects_store, _ = get_stores()
    upsert_kwargs = dict(kind="note", payload=canonical_payload, source_ref=str(path), path=str(path))
    try:
        objects_store.upsert(id=object_id, **upsert_kwargs)
    except TypeError as exc:
        msg = str(exc)
        if "unexpected keyword argument" in msg and "id" in msg:
            objects_store.upsert(**upsert_kwargs)
        else:
            raise

    classify_res = classify_run(object_id, trace_id=trace_id)
    append_jsonl(
        {
            "object_id": object_id,
            "kind": "pipeline",
            "source_ref": str(path),
            "payload": {"normalize": sanitize_normalize, "classify": classify_res},
        }
    )

    try:
        index_ingest_object(
            object_id=object_uuid,
            kind="note",
            source_ref=str(path),
            payload=payload,
            text=stripped_text,
        )
    except Exception:
        logger.exception("Vector index ingest failed for %s", path)

    try:
        store = get_object_store()
        store.put(
            object_uuid, kind="note", source_ref=str(path), payload={**payload, "text": stripped_text}
        )
    except Exception:
        logger.exception("Object store upsert failed for %s", path)

    return object_id


def ingest_vault_root(root: Path, limit: int | None = None) -> int:
    """
    Run the existing ingestion pipeline on up to `limit` markdown files
    in the vault root. Returns the number of files successfully ingested.
    """
    run_started = datetime.now(timezone.utc)
    processed = 0
    failures = 0
    files = list(iter_vault_root_markdown(root))
    try:
        # Once a vault has a layout, this producer must ingest only the same
        # retained source set used by Product readiness. Keep the historical
        # no-layout mode for small legacy/test vaults that predate layout.
        from app.ingest.vault_alpha import select_source_backed_rebuild_candidates

        admitted = {
            path.expanduser().resolve()
            for path in select_source_backed_rebuild_candidates(root)
        }
    except FileNotFoundError:
        admitted = None
    if admitted is not None:
        files = [path for path in files if path.expanduser().resolve() in admitted]
    if limit is not None:
        files = files[:max(limit, 0)]
    try:
        for path in files:
            trace_id = with_trace_id(None)
            try:
                _ingest_file(path, trace_id=trace_id, vault_root=root)
                processed += 1
            except Exception as exc:  # pragma: no cover - defensive logging
                failures += 1
                logger.exception("Failed to ingest %s: %s", path, exc)
        record_ingest_success(run_started)
    except Exception as exc:
        record_ingest_failure(run_started, str(exc))
        raise

    if failures:
        logger.warning("Vault root ingest completed with %s failures", failures)
    return processed


__all__ = ["iter_vault_root_markdown", "ingest_vault_root"]
