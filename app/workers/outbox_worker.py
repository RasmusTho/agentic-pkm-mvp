import time
from app.services.outbox import bootstrap, poll_outbox_one
from app.services.indexer import handle_ingest_object_created
from app.observability.tracer import start_span

def run(interval: float = 0.2) -> None:
    bootstrap()
    while True:
        message = poll_outbox_one()
        if message:
            trace_id = message.get("payload", {}).get("trace_id") or message.get("trace_id") or "-"
            with start_span("worker.consume", trace_id, {"topic": message.get("topic") } ):
                if message["topic"] == "ingest.object.created":
                    handle_ingest_object_created(message["payload"])
        time.sleep(interval)

if __name__ == "__main__":
    run()
