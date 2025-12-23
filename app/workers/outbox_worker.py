import os
import time
from pathlib import Path

from app.events.types import INGEST_OBJECT_CREATED, INGEST_VAULT_CHANGED
from app.ingest.vault_alpha import run_vault_alpha_ingest_paths
from app.observability.tracer import start_span
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path, write_worker_heartbeat
from app.services.indexer import handle_ingest_object_created
from app.services.outbox import bootstrap, poll_outbox_one


def _resolve_vault_root(payload: dict, vault_root: Path | None) -> Path:
    if vault_root is not None:
        return vault_root
    for env_name in ("WATCHER_VAULT_PATH", "VAULT_ROOT", "VAULT_PATH"):
        raw = os.getenv(env_name)
        if raw and raw.strip():
            return Path(raw.strip()).expanduser()
    raw_root = payload.get("vault_root")
    if raw_root:
        return Path(str(raw_root)).expanduser()
    vault_path = payload.get("vault_path")
    rel_path = payload.get("relative_path")
    if vault_path and rel_path:
        note_path = Path(str(vault_path)).expanduser()
        rel_parts = Path(str(rel_path)).parts
        root = note_path
        for _ in rel_parts:
            root = root.parent
        return root
    if vault_path:
        return Path(str(vault_path)).expanduser().parent
    raise ValueError("vault root could not be resolved for ingest event")


def _resolve_note_path(payload: dict, vault_root: Path) -> Path:
    vault_path = payload.get("vault_path")
    if vault_path:
        return Path(str(vault_path)).expanduser()
    rel_path = payload.get("relative_path")
    if rel_path:
        return vault_root / Path(str(rel_path))
    raise ValueError("vault path missing from ingest event payload")


def handle_ingest_vault_changed(payload: dict, *, vault_root: Path | None = None) -> object:
    root = _resolve_vault_root(payload, vault_root)
    note_path = _resolve_note_path(payload, root)
    return run_vault_alpha_ingest_paths(root, [note_path])


def run(
    interval: float = 0.2,
    startup_retries: int = 30,
    retry_delay: float = 1.0,
    heartbeat_interval: float | None = None,
) -> None:
    for attempt in range(startup_retries):
        try:
            bootstrap()
            break
        except Exception:
            if attempt + 1 == startup_retries:
                raise
            time.sleep(retry_delay)

    ticks_total = 0
    errors_total = 0
    processed_total = 0
    processed_by_event: dict[str, int] = {}
    last_processed: dict[str, float] = {}
    last_heartbeat = 0.0
    heartbeat_interval = heartbeat_interval if heartbeat_interval is not None else float(
        os.getenv("WORKER_HEARTBEAT_INTERVAL", "1")
    )
    heartbeat_path = resolve_worker_heartbeat_path()
    outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "/app/tmp/index-outbox.jsonl")).expanduser()

    while True:
        ticks_total += 1
        try:
            message = poll_outbox_one()
            if message:
                processed_total += 1
                topic = str(message.get("topic") or "")
                processed_by_event[topic] = processed_by_event.get(topic, 0) + 1
                now = time.time()
                last_processed[topic] = now
                trace_id = (
                    message.get("payload", {}).get("trace_id")
                    or message.get("trace_id")
                    or "-"
                )
                with start_span("worker.consume", trace_id, {"topic": topic}):
                    if topic == INGEST_OBJECT_CREATED:
                        handle_ingest_object_created(message["payload"])
                    elif topic == INGEST_VAULT_CHANGED:
                        handle_ingest_vault_changed(message["payload"])
        except Exception:
            errors_total += 1
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

        time.sleep(interval)


if __name__ == "__main__":
    run()
