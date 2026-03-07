from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

from app.knowledge.locators import make_note_locator, make_note_locator_from_absolute
from app.knowledge.references import build_obsidian_advanced_uri
from app.knowledge.service import resolve_knowledge_port
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter
from app.ports.sink import DummySink, Sink
from app.services.inbox import append_change
from app.services.settings import policy
from app.services.vault_sync import active_edit

VAULT = Path(os.getenv("VAULT_DIR", "vault"))
STATE: dict[str, dict[str, Any]] = {}
UUID_INDEX: dict[str, str] = {}


def _hash_frontmatter(data: dict[str, Any]) -> str:
    normalized = {k: data.get(k) for k in sorted(data.keys())}
    import json as _json
    payload = _json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_body(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _record(path: Path, uuid_value: str, fm_hash: str, body_hash: str) -> None:
    STATE[str(path)] = {"uuid": uuid_value, "fm": fm_hash, "body": body_hash}
    UUID_INDEX[uuid_value] = str(path)


def _make_uri(path: Path) -> str:
    try:
        locator = make_note_locator_from_absolute(path, vault_root=VAULT)
    except ValueError:
        locator = make_note_locator(path.as_posix())
    return build_obsidian_advanced_uri(locator)


def _ensure_uuid(path: Path, frontmatter: dict[str, Any], body: str) -> bool:
    if frontmatter.get("uuid"):
        return False
    import uuid

    new_uuid = uuid.uuid4().hex
    if active_edit(path):
        append_change(f"Deferred UUID injection for {path.name}", vault_path=path, uri=_make_uri(path))
        return True
    frontmatter["uuid"] = new_uuid
    locator = make_note_locator_from_absolute(path, vault_root=VAULT)
    port = resolve_knowledge_port(vault_root=VAULT)
    port.write_note(locator, dump_frontmatter(frontmatter, body))
    append_change(f"Injected UUID in {path.name}", vault_path=path, uri=_make_uri(path))
    return False


def _handle_rename(path: Path, uuid_value: str, fm_hash: str, body_hash: str, sink: Sink) -> bool:
    previous_path = UUID_INDEX.get(uuid_value)
    if previous_path and previous_path != str(path):
        sink.update_path(uuid_value, str(path))
        STATE.pop(previous_path, None)
        _record(path, uuid_value, fm_hash, body_hash)
        append_change(f"Updated path for {uuid_value} → {path.name}", vault_path=path, uri=_make_uri(path))
        return True
    return False


def _default_sink() -> Sink:
    if os.getenv("DATABASE_URL"):
        from app.ports.pg_sink import PgSink

        return PgSink()
    return DummySink()


def scan_once(sink: Sink | None = None) -> None:
    resolved_sink = sink or _default_sink()
    VAULT.mkdir(parents=True, exist_ok=True)
    current_paths: set[str] = set()
    for note_path in VAULT.rglob("*.md"):
        if any(part.startswith(".obsidian") for part in note_path.parts):
            continue
        text = note_path.read_text(encoding="utf-8")
        current_paths.add(str(note_path))
        frontmatter, body = load_frontmatter(text)
        if _ensure_uuid(note_path, frontmatter, body):
            continue
        uuid_value = str(frontmatter.get("uuid"))
        fm_hash = _hash_frontmatter(frontmatter)
        body_hash = _hash_body(body)
        if _handle_rename(note_path, uuid_value, fm_hash, body_hash, resolved_sink):
            continue
        prior = STATE.get(str(note_path))
        if active_edit(note_path):
            append_change(f"Deferred sync (active edit) {note_path.name}", vault_path=note_path, uri=_make_uri(note_path))
            continue
        changed_fm = prior is None or prior["fm"] != fm_hash
        changed_body = prior is None or prior["body"] != body_hash
        resolved_sink.upsert_object_from_note(str(note_path), frontmatter, body, changed_fm, changed_body)
        _record(note_path, uuid_value, fm_hash, body_hash)

    stale_paths = set(STATE.keys()) - current_paths
    for path_str in stale_paths:
        entry = STATE.pop(path_str)
        UUID_INDEX.pop(entry["uuid"], None)


def run() -> None:
    sink = _default_sink()
    while True:
        scan_once(sink)
        debounce_ms = policy().get("debounce_ms", 1200)
        interval = max(debounce_ms / 1000.0, 0.2)
        time.sleep(interval)


if __name__ == "__main__":
    run()
