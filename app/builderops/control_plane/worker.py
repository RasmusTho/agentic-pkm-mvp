"""Independent BuilderOps worker heartbeat entrypoint.

External-effect execution is intentionally added by its governed slice. This
module supplies the BCP-02 worker process/liveness boundary without inventing
effect authority or touching Product workers.
"""

from __future__ import annotations

import os
import signal
import time

from app.builderops.control_plane.selection import database_environment, production_store


def main() -> int:
    store = production_store(database_environment(os.environ))
    interval = max(1.0, float(os.getenv("BUILDEROPS_WORKER_HEARTBEAT_SECONDS", "10")))
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        store.write_service_heartbeat(service_name="outbox-worker")
        time.sleep(interval)
    return 0


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    raise SystemExit(main())
