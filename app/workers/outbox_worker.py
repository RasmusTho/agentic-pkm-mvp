from __future__ import annotations

import errno
import hashlib
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.agents.panel_agent.execution import refresh_panel_note_object, run_panel_note_execution
from app.components.concurrency import OptimisticWriteGuard, VersionMismatch
from app.events.types import INGEST_OBJECT_CREATED, INGEST_OBJECT_DELETED, INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED, PROMOTE_INTENT_CREATED
from app.observability.tracer import start_span
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path, write_worker_heartbeat
from app.services.indexer import handle_ingest_object_created
from app.services.companion_note import CompanionNote, scan_attachments, write_companion
from app.services.note_uuid import ensure_note_uuid
from app.services.outbox import ack_outbox, bootstrap, poll_outbox_one
from app.vault.paths import get_vault_inbox_dir_rel
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import load_frontmatter

logger = logging.getLogger(__name__)
_WRITE_GUARD = OptimisticWriteGuard()


@dataclass
class WorkerIngestSummary:
    ingested: int


@dataclass
class WorkerPanelSummary:
    emitted: int
    deferred: bool = False


def handle_ingest_object_deleted(payload: Mapping[str, Any]) -> None:
    # Explicit no-op cleanup hook for delete events. Downstream index cleanup can
    # be added here later without changing worker dispatch contracts.
    logger.info(
        "handled ingest delete event uuid=%s path=%s deleted=%s",
        payload.get("uuid"),
        payload.get("path"),
        payload.get("deleted"),
    )


def _ensure_logging_configured() -> None:
    if logger.handlers:
        # pytest's capsys replaces sys.stderr; keep the handler stream aligned so tests
        # can assert on startup logging even if another test configured logging first.
        for h in logger.handlers:
            if isinstance(h, logging.StreamHandler):
                h.stream = sys.stderr
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _resolve_vault_root(vault_root: Path | None = None) -> Path:
    if vault_root is not None:
        return vault_root.expanduser().resolve()
    watcher_root = os.getenv("WATCHER_VAULT_PATH")
    if watcher_root:
        watcher_path = Path(watcher_root).expanduser()
        if watcher_path.exists():
            return watcher_path.resolve()
    env_root = os.getenv("VAULT_ROOT")
    if env_root:
        env_path = Path(env_root).expanduser()
        if env_path.exists():
            return env_path.resolve()
    mounted_root = Path("/app/vault")
    if mounted_root.exists():
        return mounted_root.resolve()
    return Path("vault").expanduser().resolve()


def _note_path_from_payload(payload: Mapping[str, Any], *, vault_root: Path) -> Path:
    rel_value = payload.get("relative_path")
    raw = payload.get("vault_path")

    if raw:
        candidate = Path(str(raw)).expanduser()
        try:
            resolved_candidate = candidate.resolve()
            resolved_root = vault_root.resolve()
            resolved_candidate.relative_to(resolved_root)
            return resolved_candidate
        except Exception:
            pass

    if not rel_value:
        raise ValueError("missing relative_path in ingest payload")

    note_path = vault_root / Path(str(rel_value))
    return note_path.expanduser().resolve()


def _normalize_uuid_value(raw: str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple)):
        if not raw:
            return ""
        return _normalize_uuid_value(raw[0])
    value = str(raw).strip()
    if value.startswith("[[") and value.endswith("]]"):
        value = value[2:-2].strip()
    return value


def _event_id_from_message(message: Mapping[str, Any]) -> str:
    evt = message.get("event")
    if hasattr(evt, "event_id"):
        return str(getattr(evt, "event_id") or "")
    payload = message.get("payload")
    if isinstance(payload, Mapping):
        event_id = payload.get("event_id")
        if event_id:
            return str(event_id)
    return ""


_WARNED_ONCE: set[str] = set()


def _warn_once(key: str, message: str, *args: object) -> None:
    if key in _WARNED_ONCE:
        return
    _WARNED_ONCE.add(key)
    logger.warning(message, *args)


def _maybe_heal_uuid(note_path: Path, vault_root: Path) -> str:
    try:
        rel_path = note_path.relative_to(vault_root)
    except Exception:
        return ""

    inbox_rel = Path(get_vault_inbox_dir_rel(vault_root))
    try:
        rel_path.relative_to(inbox_rel)
    except Exception:
        return ""

    # iCloud File Provider paths can transiently deny writes (EPERM/EACCES) even when
    # the file later becomes writable; retry briefly to avoid leaving inbox notes uuid-less.
    max_attempts = 5
    base_sleep = 0.2

    for attempt in range(max_attempts):
        try:
            healed = ensure_note_uuid(note_path)
            if healed:
                logger.info("healed uuid for inbox note note_path=%s", note_path)
            return healed
        except OSError as exc:
            if exc.errno in {errno.EPERM, errno.EACCES, errno.EROFS}:
                if attempt + 1 < max_attempts:
                    time.sleep(base_sleep * (2**attempt))
                    continue
                _warn_once(
                    f"uuid_heal_perm:{note_path}",
                    "uuid heal skipped (permission) note_path=%s errno=%s",
                    note_path,
                    exc.errno,
                )
                return ""
            logger.warning("failed to ensure uuid for %s: %s", note_path, exc)
            return ""
        except Exception as exc:
            logger.warning("failed to ensure uuid for %s: %s", note_path, exc)
            return ""

    return ""
def _write_markdown_if_changed(note_path: Path, original: str, updated: str) -> bool:
    if original == updated:
        return False
    expected_version = _WRITE_GUARD.compute_version(original.encode("utf-8"))
    DEFAULT_WRITE_GUARD.assert_writes_allowed("panel worker update")
    try:
        _WRITE_GUARD.write_if_unchanged(note_path, expected_version, updated)
        return True
    except VersionMismatch:
        return False


def _stabilized_note_text(note_path: Path, *, attempts: int = 6, base_sleep: float = 0.25) -> str | None:
    previous_signature: tuple[float, int, str] | None = None
    for attempt in range(attempts):
        try:
            before = note_path.stat()
            raw_text = note_path.read_text(encoding="utf-8")
            after = note_path.stat()
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.EPERM, errno.EACCES, errno.EROFS}:
                if attempt + 1 < attempts:
                    time.sleep(base_sleep * (2**attempt))
                    continue
                return None
            raise
        signature = (
            float(after.st_mtime),
            int(after.st_size),
            hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        )
        if before.st_mtime == after.st_mtime and before.st_size == after.st_size:
            if signature == previous_signature:
                return raw_text
            previous_signature = signature
        if attempt + 1 < attempts:
            time.sleep(base_sleep * (2**attempt))
    return None



def handle_panel_scan_requested(
    payload: Mapping[str, Any], *, vault_root: Path | None = None
) -> WorkerPanelSummary:
    resolved_root = _resolve_vault_root(vault_root)
    note_path = _note_path_from_payload(payload, vault_root=resolved_root)

    raw_text = _stabilized_note_text(note_path)
    if raw_text is None:
        logger.info("panel scan deferred (file unstable) note_path=%s", note_path)
        return WorkerPanelSummary(emitted=0, deferred=True)

    frontmatter, _ = load_frontmatter(raw_text)
    note_uuid = _normalize_uuid_value(frontmatter.get("uuid") if isinstance(frontmatter, dict) else None)
    healed_uuid = ""
    if not note_uuid:
        healed_uuid = _maybe_heal_uuid(note_path, resolved_root)
        raw_text = _stabilized_note_text(note_path) or raw_text
        frontmatter, _ = load_frontmatter(raw_text)
        note_uuid = _normalize_uuid_value(frontmatter.get("uuid") if isinstance(frontmatter, dict) else None) or healed_uuid

    if not note_uuid:
        logger.info("panel scan skipped (missing uuid) note_path=%s", note_path)
        return WorkerPanelSummary(emitted=0, deferred=True)

    refresh_panel_note_object(
        note_uuid=note_uuid,
        note_path=note_path,
        raw_text=raw_text,
        trace_id=str(payload.get("trace_id") or ""),
    )

    trace_id = str(payload.get("trace_id") or "") or None
    execution = run_panel_note_execution(
        note_uuid,
        trace_id=trace_id,
        outbox_path=Path(os.getenv("INDEX_OUTBOX_PATH", "/app/tmp/index-outbox.jsonl")).expanduser(),
        persist_created_to_db=_use_db_outbox(),
    )
    emitted = execution.emitted_count
    if emitted:
        logger.info("panel scan handled note_path=%s note_uuid=%s emitted=%s", note_path, note_uuid, emitted)
    else:
        logger.info("panel scan produced no events note_path=%s note_uuid=%s", note_path, note_uuid)
    return WorkerPanelSummary(emitted=emitted)


def _use_db_outbox() -> bool:
    backend = (os.getenv("STORE_BACKEND") or "").strip().lower()
    return backend == "pg" or bool(os.getenv("DATABASE_URL") or os.getenv("DB_DSN"))

def handle_ingest_vault_changed(
    payload: Mapping[str, Any], *, vault_root: Path | None = None
) -> WorkerIngestSummary:
    resolved_root = _resolve_vault_root(vault_root)
    note_path = _note_path_from_payload(payload, vault_root=resolved_root)

    healed_uuid = _maybe_heal_uuid(note_path, resolved_root)

    try:
        raw_text = note_path.read_text(encoding="utf-8")
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            logger.warning("ingest skipped (missing note) note_path=%s", note_path)
            return WorkerIngestSummary(ingested=0)
        if exc.errno in {errno.EPERM, errno.EACCES, errno.EROFS}:
            _warn_once(
                f"ingest_read_perm:{note_path}",
                "ingest skipped (permission) note_path=%s errno=%s",
                note_path,
                exc.errno,
            )
            return WorkerIngestSummary(ingested=0)
        raise

    frontmatter, body = load_frontmatter(raw_text)
    content = (body or raw_text).strip()

    note_uuid = _normalize_uuid_value(frontmatter.get("uuid") or frontmatter.get("id"))
    if not note_uuid and healed_uuid:
        note_uuid = healed_uuid

    if not note_uuid:
        logger.debug("note missing uuid after heal attempt note_path=%s", note_path)
    else:
        try:
            rel_path = note_path.relative_to(resolved_root)
            text_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            write_companion(
                resolved_root,
                CompanionNote(
                    uuid=note_uuid,
                    source_ref=str(rel_path),
                    title=str(frontmatter.get("title") or note_path.stem),
                    content_hash=text_sha256,
                    ingest_state="tracked",
                    last_ingested=datetime.now(timezone.utc).isoformat(),
                    created_by_instance="",
                    attachments=scan_attachments(content),
                ),
            )
        except OSError as exc:
            if exc.errno in {errno.EPERM, errno.EACCES, errno.EROFS}:
                _warn_once(
                    f"companion_write_perm:{note_path}",
                    "companion write skipped (permission) note_path=%s errno=%s",
                    note_path,
                    exc.errno,
                )
            else:
                raise

    ingest_obj: dict[str, Any] = {
        "uuid": note_uuid,
        "content": content,
        "title": frontmatter.get("title") or note_path.stem,
        "review_state": frontmatter.get("review_state"),
        "trace_id": payload.get("trace_id"),
        "payload": {
            "frontmatter": frontmatter,
            "raw_text": raw_text,
            "hash": payload.get("hash"),
            "watcher": payload.get("watcher"),
        },
        "source_ref": str(note_path),
        "kind": "note",
    }

    handle_ingest_object_created(ingest_obj)
    return WorkerIngestSummary(ingested=1)


def run(
    interval: float = 0.2,
    startup_retries: int = 30,
    retry_delay: float = 1.0,
    heartbeat_interval: float | None = None,
    log_heartbeat_interval: float | None = None,
    stop_after_ticks: int | None = None,
) -> None:
    _ensure_logging_configured()

    for attempt in range(startup_retries):
        try:
            bootstrap()
            break
        except Exception as exc:
            if attempt + 1 == startup_retries:
                logger.exception("worker bootstrap failed after %s attempts", startup_retries)
                raise
            logger.warning(
                "worker bootstrap failed (attempt %s/%s): %s",
                attempt + 1,
                startup_retries,
                exc,
            )
            time.sleep(retry_delay)

    heartbeat_interval = heartbeat_interval if heartbeat_interval is not None else float(
        os.getenv("WORKER_HEARTBEAT_INTERVAL", "1")
    )
    heartbeat_path = resolve_worker_heartbeat_path()
    outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "/app/tmp/index-outbox.jsonl")).expanduser()

    if log_heartbeat_interval is None:
        raw_log_interval = os.getenv("WORKER_LOG_HEARTBEAT_SECONDS", "60")
        try:
            log_heartbeat_interval = float(raw_log_interval)
        except ValueError:
            log_heartbeat_interval = 60.0
    if log_heartbeat_interval is not None and log_heartbeat_interval <= 0:
        log_heartbeat_interval = None

    processed_by_event: dict[str, int] = {}
    last_processed: dict[str, float] = {}

    logger.info(
        "worker starting interval=%s heartbeat_interval=%s heartbeat_path=%s outbox_path=%s",
        interval,
        heartbeat_interval,
        heartbeat_path,
        outbox_path,
    )
    last_log = time.time()

    ticks_total = 0
    processed_total = 0
    errors_total = 0
    last_heartbeat = 0.0

    while True:
        ticks_total += 1
        try:
            message = poll_outbox_one()
            if message:
                processed_total += 1
                topic = message.get("topic")
                event_ts = time.time()
                if topic:
                    processed_by_event[topic] = processed_by_event.get(topic, 0) + 1
                    last_processed[topic] = event_ts

                event_id = _event_id_from_message(message)
                if event_id and _EVENT_DEDUP.seen(event_id):
                    continue

                payload = message.get("payload") or {}
                trace_id = payload.get("trace_id") or message.get("trace_id") or "-"

                handler_note_path: str | None = None
                if topic == INGEST_VAULT_CHANGED:
                    try:
                        resolved_root = _resolve_vault_root(None)
                        handler_note_path = str(_note_path_from_payload(payload, vault_root=resolved_root))
                    except Exception:
                        handler_note_path = None

                with start_span("worker.consume", trace_id, {"topic": topic}):
                    try:
                        if topic == INGEST_OBJECT_CREATED:
                            handle_ingest_object_created(payload)
                        elif topic == INGEST_VAULT_CHANGED:
                            handle_ingest_vault_changed(payload)
                        elif topic == INGEST_OBJECT_DELETED:
                            handle_ingest_object_deleted(payload)
                        elif topic == PANEL_SCAN_REQUESTED:
                            handle_panel_scan_requested(payload)
                        elif topic == PROMOTE_INTENT_CREATED:
                            from app.promotion.consumer import consume_promotion_intent_payload

                            consume_promotion_intent_payload(
                                payload,
                                trace_id=trace_id,
                                event_id=event_id,
                            )
                        else:
                            logger.debug("worker skipping unsupported topic=%s trace_id=%s", topic, trace_id)
                    except Exception:
                        logger.exception(
                            "worker handler failed topic=%s trace_id=%s note_path=%s",
                            topic,
                            trace_id,
                            handler_note_path or "-",
                        )
                        raise

                ack_outbox(message["id"])
        except Exception:
            errors_total += 1
            logger.exception("worker loop failed")
            raise

        now = time.time()
        if now - last_heartbeat >= heartbeat_interval:
            write_worker_heartbeat(
                path=heartbeat_path,
                ticks_total=ticks_total,
                errors_total=errors_total,
                processed_total=processed_total,
                processed_by_event=processed_by_event,
                last_processed=last_processed,
                outbox_path=outbox_path,
                now=now,
            )
            last_heartbeat = now

        if log_heartbeat_interval is not None and now - last_log >= log_heartbeat_interval:
            logger.info(
                "worker heartbeat ticks_total=%s processed_total=%s errors_total=%s",
                ticks_total,
                processed_total,
                errors_total,
            )
            last_log = now

        if stop_after_ticks is not None and ticks_total >= stop_after_ticks:
            break

        time.sleep(interval)


class _EventDedup:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, event_id: str) -> bool:
        if not event_id:
            return False
        if event_id in self._seen:
            return True
        self._seen.add(event_id)
        if len(self._seen) > 2048:
            self._seen = set(list(self._seen)[-1024:])
        return False


_EVENT_DEDUP = _EventDedup()


if __name__ == "__main__":
    run()
