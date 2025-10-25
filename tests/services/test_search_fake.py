import threading
import time

import requests
import uvicorn

from app.api.app import app
from app.agent.events import INGEST_OBJECT_CREATED, new_trace_id
from app.services.outbox import bootstrap, insert_object_and_outbox
from app.workers.outbox_worker import run as worker_run


def start_worker():
    worker_run(0.05)


def start_api():
    uvicorn.run(app, host="127.0.0.1", port=18001, log_level="warning")


def test_search_roundtrip_fast() -> None:
    bootstrap()
    worker_thread = threading.Thread(target=start_worker, daemon=True)
    worker_thread.start()
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()
    time.sleep(0.4)
    insert_object_and_outbox(
        {"uuid": "u-s1", "title": "Alpha", "review_state": "inbox", "content": "alpha beta gamma"},
        INGEST_OBJECT_CREATED,
        new_trace_id(),
    )
    time.sleep(0.6)
    response = requests.get("http://127.0.0.1:18001/search", params={"q": "gamma"})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("results")
    t0 = time.time()
    response2 = requests.get("http://127.0.0.1:18001/search", params={"q": "alpha"})
    dt = time.time() - t0
    assert response2.status_code == 200
    assert dt < 0.25
