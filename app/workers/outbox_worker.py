import time
from app.services.outbox import bootstrap, poll_outbox_one
from app.services.indexer import handle_ingest_object_created

def run(interval: float = 0.2) -> None:
    bootstrap()
    while True:
        message = poll_outbox_one()
        if message and message["topic"] == "ingest.object.created":
            handle_ingest_object_created(message["payload"])
        time.sleep(interval)

if __name__ == "__main__":
    run()
