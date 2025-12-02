import time
from app.events.types import INGEST_OBJECT_CREATED
from app.services.outbox import bootstrap, poll_outbox_one
from app.services.indexer import handle_ingest_object_created
from app.observability.tracer import start_span

def run(interval: float = 0.2, startup_retries: int = 30, retry_delay: float = 1.0) -> None:
    for attempt in range(startup_retries):
        try:
            bootstrap()
            break
        except Exception:
            if attempt + 1 == startup_retries:
                raise
            time.sleep(retry_delay)
    while True:
        message = poll_outbox_one()
        if message:
            trace_id = message.get("payload", {}).get("trace_id") or message.get("trace_id") or "-"
            with start_span("worker.consume", trace_id, {"topic": message.get("topic") } ):
                if message["topic"] == INGEST_OBJECT_CREATED:
                    handle_ingest_object_created(message["payload"])
        time.sleep(interval)

if __name__ == "__main__":
    run()
