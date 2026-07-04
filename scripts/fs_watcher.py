from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Any

from app.knowledge.write_ops import advanced_uri_from_vault_path
from app.ports.filesystem_vault_adapter import FilesystemVaultAdapter
from app.ports.vault_port import VaultPort
from app.services.settings import policy
from app.services.vault_sync import active_edit

logger = logging.getLogger(__name__)

VAULT = Path(os.getenv("VAULT_DIR", "vault"))
STATE: dict[str, dict[str, Any]] = {}
UUID_INDEX: dict[str, str] = {}
# Paths whose sync is currently failing. run() re-invokes scan_once every ~1.2s,
# so a persistently non-transient fault would otherwise emit a full ERROR-level
# traceback on every scan (~50x/min), drowning real errors. We log the traceback
# only on the first observed failure per path (see _log_sync_failure) and clear
# the path here on the next successful sync so a recovered-then-failing note logs
# a fresh traceback again.
FAILED_SYNC_PATHS: set[str] = set()


def _log_sync_failure(path_str: str, message: str, *args: object) -> None:
    """Log a per-path sync failure, emitting a full traceback only the first time
    a given path fails since its last success.

    Mirrors ``app/services/note_watcher.py``: a first-class failure gets
    ``logger.exception`` (with traceback); recurring/expected failures get
    ``logger.warning`` (no traceback). Callers must invoke this from inside the
    active ``except`` block so ``logger.exception`` captures the live exception.
    """
    if path_str in FAILED_SYNC_PATHS:
        logger.warning(message + " (repeat; traceback suppressed until recovery)", *args)
        return
    FAILED_SYNC_PATHS.add(path_str)
    logger.exception(message, *args)


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
    return advanced_uri_from_vault_path(path, vault_root=VAULT)


def _ensure_uuid(path: Path, port: VaultPort) -> bool:
    note = port.read_note(path)
    result = port.ensure_uuid(note, expected_mtime_ns=note.mtime_ns)
    return result.deferred


def _handle_rename(path: Path, uuid_value: str, fm_hash: str, body_hash: str, port: VaultPort) -> bool:
    previous_path = UUID_INDEX.get(uuid_value)
    if previous_path and previous_path != str(path):
        port.rename_note(uuid_value, path)
        STATE.pop(previous_path, None)
        _record(path, uuid_value, fm_hash, body_hash)
        port.append_inbox_item(f"Updated path for {uuid_value} → {path.name}", vault_path=path, uri=_make_uri(path))
        return True
    return False


def _default_vault_port() -> VaultPort:
    backend_writes = bool(os.getenv("DATABASE_URL"))
    return FilesystemVaultAdapter(vault_root=VAULT, backend_writes_enabled=backend_writes)


def scan_once(port: VaultPort | None = None) -> None:
    resolved_port = port or _default_vault_port()
    VAULT.mkdir(parents=True, exist_ok=True)
    current_paths: set[str] = set()
    for note_path in VAULT.rglob("*.md"):
        if any(part.startswith(".obsidian") for part in note_path.parts):
            continue
        current_paths.add(str(note_path))
        if _ensure_uuid(note_path, resolved_port):
            continue
        note = resolved_port.read_note(note_path)
        uuid_value = str(note.frontmatter.get("uuid") or "")
        if not uuid_value:
            continue
        fm_hash = _hash_frontmatter(note.frontmatter)
        body_hash = _hash_body(note.body)
        if _handle_rename(note_path, uuid_value, fm_hash, body_hash, resolved_port):
            continue
        prior = STATE.get(str(note_path))
        if active_edit(note_path):
            resolved_port.append_inbox_item(
                f"Deferred sync (active edit) {note_path.name}",
                vault_path=note_path,
                uri=_make_uri(note_path),
            )
            continue
        changed_fm = prior is None or prior["fm"] != fm_hash
        changed_body = prior is None or prior["body"] != body_hash
        if not changed_fm and not changed_body:
            _record(note_path, uuid_value, fm_hash, body_hash)
            continue
        try:
            resolved_port.upsert_note_object(note_path, note.frontmatter, note.body, changed_fm, changed_body)
        except Exception:
            # A transient sync failure (e.g. DB error, or an outbox schema-validation
            # raise from the in-transaction enqueue after #2864) must not kill the scan
            # loop. Skip _record so STATE still shows the note as changed and the next
            # scan pass retries it; that periodic re-scan is the back-off. A persistent
            # fault would flood logs at ~50 tracebacks/min, so only the first failure
            # per path emits a traceback; repeats are downgraded until recovery.
            _log_sync_failure(str(note_path), "Vault sync failed for %s; skipping, will retry on next scan", note_path)
            continue
        FAILED_SYNC_PATHS.discard(str(note_path))
        _record(note_path, uuid_value, fm_hash, body_hash)

    stale_paths = set(STATE.keys()) - current_paths
    for path_str in stale_paths:
        entry = STATE[path_str]
        try:
            resolved_port.delete_note(Path(path_str), uuid_value=str(entry.get("uuid") or "") or None)
        except Exception:
            # Same resilience contract as the upsert path: leave STATE/UUID_INDEX intact
            # so the stale-path delete is retried on the next scan instead of being lost.
            # Same traceback-dedup as the upsert path: first failure per path only.
            _log_sync_failure(path_str, "Vault delete-sync failed for %s; skipping, will retry on next scan", path_str)
            continue
        FAILED_SYNC_PATHS.discard(path_str)
        STATE.pop(path_str, None)
        UUID_INDEX.pop(entry["uuid"], None)


def run() -> None:
    port = _default_vault_port()
    while True:
        scan_once(port)
        debounce_ms = policy().get("debounce_ms", 1200)
        interval = max(debounce_ms / 1000.0, 0.2)
        time.sleep(interval)


if __name__ == "__main__":
    run()
