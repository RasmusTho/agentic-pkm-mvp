import os
import time
from pathlib import Path

from app.events.types import INGEST_OBJECT_CREATED
from app.runtime.worker_heartbeat import resolve_worker_heartbeat_path, write_worker_heartbeat
from app.services.indexer import handle_ingest_object_created
from app.services.outbox import bootstrap, poll_outbox_one
from app.observability.tracer import start_span


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
    last_heartbeat = 0.0
    heartbeat_interval = heartbeat_interval if heartbeat_interval is not None else float(os.getenv("WORKER_HEARTBEAT_INTERVAL", "1"))
    heartbeat_path = resolve_worker_heartbeat_path()
    outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "/app/tmp/index-outbox.jsonl")).expanduser()

    while True:
        ticks_total += 1
        try:
            message = poll_outbox_one()
            if message:
                processed_total += 1
                trace_id = message.get("payload", {}).get("trace_id") or message.get("trace_id") or "-"
                with start_span("worker.consume", trace_id, {"topic": message.get("topic")}):
                    if message["topic"] == INGEST_OBJECT_CREATED:
                        handle_ingest_object_created(message["payload"])
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
                outbox_path=outbox_path,
                now=now,
            )
            last_heartbeat = now

        time.sleep(interval)


if __name__ == "__main__":
    run()
