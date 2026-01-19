import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.components.concurrency import EventDedupStore, SystemClock
from app.events.types import INGEST_OBJECT_CREATED, INGEST_VAULT_CHANGED, PROMOTE_INTENT_CREATED
from app.promotion.consumer import consume_promotion_intent_payload
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path, write_worker_heartbeat
from app.services.indexer import handle_ingest_object_created
from app.services.outbox import ack_outbox, bootstrap, poll_outbox_one
from app.observability import setup_logging
from app.observability.tracer import start_span
from scripts.yaml_roundtrip import load_frontmatter

_EVENT_DEDUP = EventDedupStore(SystemClock(), ttl_seconds=3600.0)
logger = logging.getLogger(__name__)


@dataclass
class WorkerIngestSummary:
    ingested: int
    errors: int = 0


def _ensure_logging_configured() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        formatter = getattr(handler, "formatter", None)
        if (
            isinstance(handler, logging.StreamHandler)
            and handler.stream is sys.stdout
            and formatter is not None
            and formatter.__class__.__name__ == "JsonFormatter"
        ):
            return
    setup_logging()


def _resolve_vault_root(vault_root: Path | None = None) -> Path:
    if vault_root is not None:
        return vault_root
    env_value = os.getenv("VAULT_PATH") or os.getenv("VAULT_ROOT")
    if env_value:
        return Path(env_value).expanduser()
    return Path("vault")


def _note_path_from_payload(payload: Mapping[str, Any], *, vault_root: Path) -> Path:
    candidate = payload.get("vault_path")
    if candidate:
        note_path = Path(candidate)
        if not note_path.is_absolute():
            note_path = vault_root / note_path
    else:
        rel_value = payload.get("relative_path")
        if not rel_value:
            raise ValueError("missing relative_path in ingest payload")
        note_path = vault_root / Path(rel_value)
    return note_path.expanduser()


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


def handle_ingest_vault_changed(
    payload: Mapping[str, Any], *, vault_root: Path | None = None
) -> WorkerIngestSummary:
    resolved_root = _resolve_vault_root(vault_root)
    note_path = _note_path_from_payload(payload, vault_root=resolved_root)
    raw_text = note_path.read_text(encoding="utf-8")
    frontmatter, body = load_frontmatter(raw_text)
    content = (body or raw_text).strip()
    note_uuid = _normalize_uuid_value(frontmatter.get("uuid") or frontmatter.get("id"))
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

    ticks_total = 0
    errors_total = 0
    processed_total = 0
    last_heartbeat = 0.0
    last_log = 0.0
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
                trace_id = message.get("payload", {}).get("trace_id") or message.get("trace_id") or "-"
                with start_span("worker.consume", trace_id, {"topic": topic}):
                    if topic == INGEST_OBJECT_CREATED:
                        handle_ingest_object_created(message["payload"])
                    elif topic == INGEST_VAULT_CHANGED:
                        handle_ingest_vault_changed(message["payload"])
                    elif topic == PROMOTE_INTENT_CREATED:
                        consume_promotion_intent_payload(
                            message["payload"],
                            trace_id=trace_id,
                            event_id=event_id,
                        )
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


if __name__ == "__main__":
    run()
