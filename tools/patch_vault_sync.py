from pathlib import Path
import re
import shutil

# where we patch
p = Path("app/services/vault_sync.py")
src = p.read_text(encoding="utf-8")

# backup first
shutil.copyfile(p, p.with_suffix(".py.bak"))

new_update_path_only = r'''
def _update_path_only(
    conn: psycopg.Connection, *, old_path: str, new_path: str, uuid_value: str, fm_hash: str, body_hash: str, mtime: datetime
) -> None:
    # 1) Make sure there's an objects row that matches this uuid (or id) and update its path.
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

    # Insert minimal row if nothing was updated (try (id,uuid), then id-only, then uuid-only)
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

    # 2) Update file_state last so object fallbacks don't poison this write.
    with conn.cursor() as cur:
        cur.execute(
            "update file_state set path=%s, fm_hash=%s, body_hash=%s, mtime=%s, last_seen=now() where path=%s",
            (new_path, fm_hash, body_hash, mtime, old_path),
        )
'''.lstrip("\n")

new_sync_markdown = r'''
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

        # Check body diff before deferral
        prev_body_hash = (state or {}).get("body_hash")
        body_changed = (prev_body_hash is not None) and (prev_body_hash != body_hash)

        # Defer if actively editing and no body change (incl. first sync). Always write baseline state.
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

        # Pure rename: had state but on another path → update only path (no re-embed)
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

        topic = INGEST_OBJECT_CREATED if state is None else "ingest.object.updated"
        if state is not None and state.get("body_hash") == body_hash:
            topic = "ingest.object.metadata"

        # Mark re-embed if body changed
        if body_changed and policy().get("reembed_on_body_diff", True):
            result["reembedded"] = True

        # Write a minimal row to `objects` (idempotent) with rollbacks between fallbacks.
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
'''.lstrip("\n")

def replace_def(name: str, new_code: str, text: str) -> str:
    # Replace a whole "def <name>(...):" block until the next top-level def or EOF
    pat = re.compile(rf'(?sm)^def\s+{name}\s*\(.*?\)\s*:\n(?:\s.*\n)*?((?=^def\s)|\Z)')
    if not pat.search(text):
        raise SystemExit(f"Couldn't find function {name} to patch.")
    return pat.sub(new_code + "\n", text, count=1)

src = replace_def("_update_path_only", new_update_path_only, src)
src = replace_def("sync_markdown", new_sync_markdown, src)

p.write_text(src, encoding="utf-8")
print("Patched:", p)
