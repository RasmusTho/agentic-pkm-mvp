from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg
import yaml

from app.db import conn_rw, ensure_schema

from app.events.models import new_trace_id
from app.events.types import INGEST_OBJECT_CREATED, INGEST_OBJECT_METADATA, INGEST_OBJECT_UPDATED
from app.knowledge.write_ops import default_vault_root_for_path, write_note_from_absolute
from app.write_guard import DEFAULT_WRITE_GUARD
from app.services.inbox import append_change, append_conflict
from app.services.outbox import insert_object_and_outbox
from app.services.settings import policy


def _conn():
    return conn_rw()


def _hash_dict(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_note(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    if raw.startswith("---"):
        _, fm_block, remainder = raw.split("---", 2)
        frontmatter = yaml.safe_load(fm_block) or {}
        body = remainder.lstrip("\n")
    else:
        frontmatter = {}
        body = raw
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, body


def _write_note(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    fm_dump = yaml.safe_dump(frontmatter, sort_keys=False).strip()
    rendered = f"---\n{fm_dump}\n---\n\n{body}" if body else f"---\n{fm_dump}\n---\n"
    DEFAULT_WRITE_GUARD.assert_writes_allowed("vault sync note write")
    resolved = path.resolve()
    root = default_vault_root_for_path(resolved)
    write_note_from_absolute(resolved, rendered, vault_root=root)


def _get_state_by_path(conn: psycopg.Connection, path: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("select path, uuid, fm_hash, body_hash, mtime from file_state where path = %s", (path,))
        row = cur.fetchone()
        return row if isinstance(row, dict) else (dict(row) if row else None)


def _get_state_by_uuid(conn: psycopg.Connection, uuid_value: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "select path, uuid, fm_hash, body_hash, mtime from file_state where uuid = %s",
            (uuid_value,),
        )
        row = cur.fetchone()
        return row if isinstance(row, dict) else (dict(row) if row else None)


def _upsert_file_state(
    conn: psycopg.Connection, *, path: str, uuid_value: str, fm_hash: str, body_hash: str, mtime: datetime
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into file_state(path, uuid, fm_hash, body_hash, mtime, last_seen)
            values(%s,%s,%s,%s,%s,now())
            on conflict (path) do update set
              uuid = excluded.uuid,
              fm_hash = excluded.fm_hash,
              body_hash = excluded.body_hash,
              mtime = excluded.mtime,
              last_seen = now()
            """,
            (path, uuid_value, fm_hash, body_hash, mtime),
        )


def _update_path_only(
    conn: psycopg.Connection, *, old_path: str, new_path: str, uuid_value: str, fm_hash: str, body_hash: str, mtime: datetime
) -> None:
    # Step 1: ensure an objects-row exists and has the new path. Do this first, with rollbacks between fallbacks.
    updated = 0

    # Try UUID
    with conn.cursor() as cur:
        try:
            cur.execute("update objects set path=%s where uuid=%s", (new_path, uuid_value))
            updated = cur.rowcount or 0
        except Exception:
            conn.rollback()

    # Try ID
    if updated == 0:
        with conn.cursor() as cur:
            try:
                cur.execute("update objects set path=%s where id=%s", (new_path, uuid_value))
                updated = cur.rowcount or 0
            except Exception:
                conn.rollback()

    # No row updated → insert minimal row. Try (id,uuid) → id-only → uuid-only
    if updated == 0:
        inserted = False
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "insert into objects(id, uuid, kind, payload, path) values(%s, %s, %s, '{}'::jsonb, %s)",
                    (uuid_value, uuid_value, "note", new_path),
                )
                inserted = True
            except Exception:
                conn.rollback()

        if not inserted:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "insert into objects(id, kind, payload, path) values(%s, %s, '{}'::jsonb, %s)",
                        (uuid_value, "note", new_path),
                    )
                    inserted = True
                except Exception:
                    conn.rollback()

        if not inserted:
            with conn.cursor() as cur:
                cur.execute(
                    "insert into objects(uuid, kind, payload, path) values(%s, %s, '{}'::jsonb, %s)",
                    (uuid_value, "note", new_path),
                )

    # Step 2: write/normalize file_state last (so it isn’t poisoned by a prior error)
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into file_state(path, uuid, fm_hash, body_hash, mtime, last_seen)
            values(%s,%s,%s,%s,%s,now())
            on conflict (path) do update set
              uuid = excluded.uuid,
              fm_hash = excluded.fm_hash,
              body_hash = excluded.body_hash,
              mtime = excluded.mtime,
              last_seen = now()
            """,
            (new_path, uuid_value, fm_hash, body_hash, mtime),
        )
        cur.execute(
            "delete from file_state where uuid = %s and path <> %s",
            (uuid_value, new_path),
        )


def _enqueue(topic: str, payload: dict[str, Any]) -> None:
    trace_id = new_trace_id()
    insert_object_and_outbox(payload, topic, trace_id)


def update_path(uuid_value: str, new_path: str) -> None:
    resolved_path = str(Path(new_path).resolve())
    with _conn() as conn:
        ensure_schema(conn)
        conn.commit()
        state = _get_state_by_uuid(conn, uuid_value)
        fm_hash = state["fm_hash"] if state else None
        body_hash = state["body_hash"] if state else None
        mtime = state["mtime"] if state else None
        with conn.cursor() as cur:
            try:
                cur.execute("update objects set path=%s where uuid=%s", (resolved_path, uuid_value))
            except Exception:
                cur.execute("update objects set path=%s where id=%s", (resolved_path, uuid_value))
            cur.execute(
                """
                insert into file_state(path, uuid, fm_hash, body_hash, mtime, last_seen)
                values(%s,%s,%s,%s,%s,now())
                on conflict (path) do update set
                  uuid = excluded.uuid,
                  fm_hash = coalesce(excluded.fm_hash, file_state.fm_hash),
                  body_hash = coalesce(excluded.body_hash, file_state.body_hash),
                  mtime = coalesce(excluded.mtime, file_state.mtime),
                  last_seen = now()
                """,
                (resolved_path, uuid_value, fm_hash, body_hash, mtime),
            )
            cur.execute(
                "delete from file_state where uuid = %s and path <> %s",
                (uuid_value, resolved_path),
            )
        conn.commit()


def delete_note(path: str, *, uuid_value: str | None = None) -> None:
    resolved_path = str(Path(path).resolve())
    with _conn() as conn:
        ensure_schema(conn)
        conn.commit()
        state = _get_state_by_path(conn, resolved_path)
        effective_uuid = (uuid_value or (state or {}).get("uuid") or "").strip() or None
        with conn.cursor() as cur:
            cur.execute("delete from file_state where path = %s", (resolved_path,))
            if effective_uuid:
                cur.execute("select count(*) from file_state where uuid = %s", (effective_uuid,))
                row = cur.fetchone()
                if isinstance(row, dict):
                    remaining = int(row.get("count", 0))
                else:
                    remaining = row[0] if row else 0
                if remaining == 0:
                    try:
                        cur.execute("update objects set path = null where uuid = %s", (effective_uuid,))
                    except Exception:
                        cur.execute("update objects set path = null where id = %s", (effective_uuid,))
        conn.commit()


def upsert_object_from_note(path: str, frontmatter: dict[str, Any], body: str, fm_changed: bool, body_changed: bool) -> None:
    note_path = Path(path).resolve()
    path_str = str(note_path)
    uuid_value = frontmatter["uuid"]
    title = frontmatter.get("title") or note_path.stem
    review_state = frontmatter.get("review_state", "inbox")
    fm_hash = _hash_dict(frontmatter)
    body_hash = _hash_text(body)
    mtime = datetime.fromtimestamp(note_path.stat().st_mtime, tz=timezone.utc) if note_path.exists() else datetime.now(timezone.utc)

    with _conn() as conn:
        ensure_schema(conn)
        conn.commit()
        state = _get_state_by_uuid(conn, uuid_value)
        with conn.cursor() as cur:
            payload_json = json.dumps(
                {
                    "title": title,
                    "review_state": review_state,
                    "content": body,
                    "frontmatter": frontmatter,
                }
            )
            try:
                cur.execute(
                    """
                    insert into objects(id, kind, payload, path)
                    values(%s,%s,%s::jsonb,%s)
                    on conflict (id) do update set
                      kind = excluded.kind,
                      payload = excluded.payload,
                      path = excluded.path
                    """,
                    (uuid_value, "note", payload_json, path_str),
                )
            except Exception:
                cur.execute(
                    """
                    insert into objects(uuid, kind, payload, path)
                    values(%s,%s,%s::jsonb,%s)
                    on conflict (uuid) do update set
                      kind = excluded.kind,
                      payload = excluded.payload,
                      path = excluded.path
                    """,
                    (uuid_value, "note", payload_json, path_str),
                )
        _upsert_file_state(
            conn,
            path=path_str,
            uuid_value=uuid_value,
            fm_hash=fm_hash,
            body_hash=body_hash,
            mtime=mtime,
        )
        conn.commit()

    topic = None
    if state is None:
        topic = INGEST_OBJECT_CREATED
    elif body_changed:
        topic = INGEST_OBJECT_UPDATED
    elif fm_changed:
        topic = INGEST_OBJECT_METADATA
    if topic:
        payload = {
            "uuid": uuid_value,
            "title": title,
            "review_state": review_state,
            "content": body,
            "path": path_str,
        }
        _enqueue(topic, payload)


def active_edit(path: Path) -> bool:
    grace = policy().get("inactive_grace_s", 5)
    try:
        delta = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return delta < grace


def sync_markdown(path: str) -> dict[str, Any]:
    note_path = Path(path).resolve()
    frontmatter, body = _read_note(note_path)
    is_active = active_edit(note_path)
    if "uuid" not in frontmatter or not frontmatter.get("uuid"):
        frontmatter["uuid"] = str(uuid.uuid4())
        _write_note(note_path, frontmatter, body)
        is_active = False

    uuid_value = frontmatter["uuid"]
    fm_hash = _hash_dict(frontmatter)
    body_hash = _hash_text(body)
    mtime = datetime.fromtimestamp(note_path.stat().st_mtime, tz=timezone.utc)

    result: dict[str, Any] = {
        "status": "ok",
        "reembedded": False,
        "id": uuid_value,
        "uuid": uuid_value,
        "path": str(note_path),
    }

    with _conn() as conn:
        ensure_schema(conn)
        conn.commit()

        # Previous state
        state = _get_state_by_path(conn, str(note_path))
        rename_state: Optional[dict[str, Any]] = None
        if state is None:
            rename_state = _get_state_by_uuid(conn, uuid_value)

        # Compare body before deferral
        prev_body_hash = (state or {}).get("body_hash")
        body_changed = (prev_body_hash is not None) and (prev_body_hash != body_hash)

        # Defer if active and no body change (incl. first sync). Always write baseline state.
        if is_active and not body_changed:
            _upsert_file_state(
                conn,
                path=str(note_path),
                uuid_value=uuid_value,
                fm_hash=fm_hash,
                body_hash=body_hash,
                mtime=mtime,
            )
            append_change(f"Skipped sync for active edit: {note_path}", vault_path=note_path)
            conn.commit()
            result["status"] = "deferred"
            return result

        # Pure rename: state known on another path → update only path (no re-embed).
        if state is None and rename_state and rename_state["path"] != str(note_path):
            _update_path_only(
                conn,
                old_path=rename_state["path"],
                new_path=str(note_path),
                uuid_value=uuid_value,
                fm_hash=fm_hash,
                body_hash=body_hash,
                mtime=mtime,
            )
            conn.commit()
            return result

        changed = state is None
        if state:
            if state["uuid"] and state["uuid"] != uuid_value:
                append_conflict(f"UUID mismatch for {note_path}", vault_path=note_path)
            if state["fm_hash"] != fm_hash or state["body_hash"] != body_hash:
                changed = True

        if not changed:
            _upsert_file_state(
                conn,
                path=str(note_path),
                uuid_value=uuid_value,
                fm_hash=fm_hash,
                body_hash=body_hash,
                mtime=mtime,
            )
            conn.commit()
            return result

        obj_payload = {
            "uuid": uuid_value,
            "title": frontmatter.get("title") or note_path.stem,
            "review_state": frontmatter.get("review_state", "inbox"),
            "content": body,
            "path": str(note_path),
        }

        topic = INGEST_OBJECT_CREATED if state is None else INGEST_OBJECT_UPDATED
        if state is not None and state.get("body_hash") == body_hash:
            topic = INGEST_OBJECT_METADATA

        # Mark for re-embed if body changed
        if body_changed and policy().get("reembed_on_body_diff", True):
            result["reembedded"] = True

        # Write a minimal row to objects (idempotent) with rollbacks between fallbacks.
        payload_json = json.dumps(
            {
                "title": obj_payload["title"],
                "review_state": obj_payload["review_state"],
                "content": obj_payload["content"],
                "frontmatter": frontmatter,
            }
        )
        wrote = False

        # (id, uuid) first
        with conn.cursor() as cur1:
            try:
                cur1.execute(
                    """
                    insert into objects(id, uuid, kind, payload, path)
                    values(%s,%s,%s,%s::jsonb,%s)
                    on conflict (id) do update set
                      uuid = excluded.uuid,
                      kind = excluded.kind,
                      payload = excluded.payload,
                      path = excluded.path
                    """,
                    (uuid_value, uuid_value, "note", payload_json, str(note_path)),
                )
                wrote = True
            except Exception:
                conn.rollback()

        # id-only
        if not wrote:
            with conn.cursor() as cur2:
                try:
                    cur2.execute(
                        """
                        insert into objects(id, kind, payload, path)
                        values(%s,%s,%s::jsonb,%s)
                        on conflict (id) do update set
                          kind = excluded.kind,
                          payload = excluded.payload,
                          path = excluded.path
                        """,
                        (uuid_value, "note", payload_json, str(note_path)),
                    )
                    wrote = True
                except Exception:
                    conn.rollback()

        # uuid-only
        if not wrote:
            with conn.cursor() as cur3:
                cur3.execute(
                    """
                    insert into objects(uuid, kind, payload, path)
                    values(%s,%s,%s::jsonb,%s)
                    on conflict (uuid) do update set
                      kind = excluded.kind,
                      payload = excluded.payload,
                      path = excluded.path
                    """,
                    (uuid_value, "note", payload_json, str(note_path)),
                )

        _enqueue(topic, obj_payload)

        _upsert_file_state(
            conn,
            path=str(note_path),
            uuid_value=uuid_value,
            fm_hash=fm_hash,
            body_hash=body_hash,
            mtime=mtime,
        )
        conn.commit()

    return result


def handle_rename(old_path: str, new_path: str) -> dict[str, Any]:
    old = Path(old_path).resolve()
    new = Path(new_path).resolve()
    frontmatter, body = _read_note(new)
    if "uuid" not in frontmatter or not frontmatter["uuid"]:
        raise ValueError("Rename requires uuid in frontmatter")
    fm_hash = _hash_dict(frontmatter)
    body_hash = _hash_text(body)
    mtime = datetime.fromtimestamp(new.stat().st_mtime, tz=timezone.utc)
    result = {"uuid": frontmatter["uuid"], "updated": False}
    with _conn() as conn:
        ensure_schema(conn)
        conn.commit()
        state = _get_state_by_path(conn, str(old))
        if not state:
            state = _get_state_by_uuid(conn, frontmatter["uuid"])
        if not state:
            append_change(f"Rename detected without state for {new_path}", vault_path=new)
            conn.commit()
            return result
        _update_path_only(
            conn,
            old_path=state["path"],
            new_path=str(new),
            uuid_value=frontmatter["uuid"],
            fm_hash=fm_hash,
            body_hash=body_hash,
            mtime=mtime,
        )
        conn.commit()
        result["updated"] = True
    return result


__all__ = ["sync_markdown", "handle_rename", "update_path", "delete_note", "upsert_object_from_note", "active_edit"]
