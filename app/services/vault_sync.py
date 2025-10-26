from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg
import yaml
from psycopg.rows import dict_row

from app.agent.events import INGEST_OBJECT_CREATED, new_trace_id
from app.services.inbox import append_change, append_conflict
from app.services.outbox import insert_object_and_outbox
from app.services.settings import policy

MIGRATION_SQL_PATH = Path(__file__).resolve().parents[1] / "db" / "migrations_obsidian.sql"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:15432/app")


def _conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def ensure_schema(conn: psycopg.Connection) -> None:
    if not MIGRATION_SQL_PATH.exists():
        return
    statements = [stmt.strip() for stmt in MIGRATION_SQL_PATH.read_text(encoding="utf-8").split(';') if stmt.strip()]
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _get_state_by_path(conn: psycopg.Connection, path: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("select path, uuid, fm_hash, body_hash, mtime from file_state where path = %s", (path,))
        return cur.fetchone()


def _get_state_by_uuid(conn: psycopg.Connection, uuid_value: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("select path, uuid, fm_hash, body_hash, mtime from file_state where uuid = %s", (uuid_value,))
        return cur.fetchone()


def _upsert_file_state(conn: psycopg.Connection, *, path: str, uuid_value: str, fm_hash: str, body_hash: str, mtime: datetime) -> None:
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


def _update_path_only(conn: psycopg.Connection, *, old_path: str, new_path: str, uuid_value: str, fm_hash: str, body_hash: str, mtime: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update file_state set path=%s, fm_hash=%s, body_hash=%s, mtime=%s, last_seen=now() where path=%s",
            (new_path, fm_hash, body_hash, mtime, old_path),
        )
        cur.execute("update objects set path=%s where uuid=%s", (new_path, uuid_value))


def _enqueue(topic: str, payload: dict[str, Any]) -> None:
    trace_id = new_trace_id()
    insert_object_and_outbox(payload, topic, trace_id)


def active_edit(path: Path) -> bool:
    grace = policy().get("inactive_grace_s", 5)
    try:
        delta = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return delta < grace


def sync_markdown(path: str) -> dict[str, Any]:
    note_path = Path(path)
    frontmatter, body = _read_note(note_path)
    injected_uuid = False
    if "uuid" not in frontmatter or not frontmatter.get("uuid"):
        frontmatter["uuid"] = str(uuid.uuid4())
        injected_uuid = True
        _write_note(note_path, frontmatter, body)
    if active_edit(note_path):
        append_change(f"Skipped sync for active edit: {note_path}", vault_path=note_path)
        return {"status": "deferred", "uuid": frontmatter["uuid"], "injected_uuid": injected_uuid}
    fm_hash = _hash_dict(frontmatter)
    body_hash = _hash_text(body)
    mtime = datetime.fromtimestamp(note_path.stat().st_mtime, tz=timezone.utc)
    result = {"uuid": frontmatter["uuid"], "injected_uuid": injected_uuid, "reembedded": False, "renamed": False}
    with _conn() as conn:
        ensure_schema(conn)
        state = _get_state_by_path(conn, str(note_path))
        rename_state: Optional[dict[str, Any]] = None
        if state is None:
            rename_state = _get_state_by_uuid(conn, frontmatter["uuid"])
        if state is None and rename_state and rename_state["path"] != str(note_path):
            result["renamed"] = True
            _update_path_only(
                conn,
                old_path=rename_state["path"],
                new_path=str(note_path),
                uuid_value=frontmatter["uuid"],
                fm_hash=fm_hash,
                body_hash=body_hash,
                mtime=mtime,
            )
            conn.commit()
            return result
        changed = injected_uuid
        if state:
            if state["uuid"] and state["uuid"] != frontmatter["uuid"]:
                append_conflict(f"UUID mismatch for {note_path}", vault_path=note_path)
            if state["fm_hash"] != fm_hash or state["body_hash"] != body_hash:
                changed = True
        else:
            changed = True
        if not changed:
            _upsert_file_state(
                conn,
                path=str(note_path),
                uuid_value=frontmatter["uuid"],
                fm_hash=fm_hash,
                body_hash=body_hash,
                mtime=mtime,
            )
            conn.commit()
            return result
        obj_payload = {
            "uuid": frontmatter["uuid"],
            "title": frontmatter.get("title") or note_path.stem,
            "review_state": frontmatter.get("review_state", "inbox"),
            "content": body,
            "path": str(note_path),
        }
        topic = INGEST_OBJECT_CREATED if state is None else "ingest.object.updated"
        if state is not None and state["body_hash"] == body_hash:
            topic = "ingest.object.metadata"
        _enqueue(topic, obj_payload)
        if topic == "ingest.object.updated" and body_hash != (state or {}).get("body_hash") and policy().get("reembed_on_body_diff", True):
            result["reembedded"] = True
        _upsert_file_state(
            conn,
            path=str(note_path),
            uuid_value=frontmatter["uuid"],
            fm_hash=fm_hash,
            body_hash=body_hash,
            mtime=mtime,
        )
        conn.commit()
    return result


def handle_rename(old_path: str, new_path: str) -> dict[str, Any]:
    old = Path(old_path)
    new = Path(new_path)
    frontmatter, body = _read_note(new)
    if "uuid" not in frontmatter or not frontmatter["uuid"]:
        raise ValueError("Rename requires uuid in frontmatter")
    fm_hash = _hash_dict(frontmatter)
    body_hash = _hash_text(body)
    mtime = datetime.fromtimestamp(new.stat().st_mtime, tz=timezone.utc)
    result = {"uuid": frontmatter["uuid"], "updated": False}
    with _conn() as conn:
        ensure_schema(conn)
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
