"""Container health probe for the independent API and worker processes."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.builderops.control_plane.selection import database_environment, production_store


def probe_liveness() -> bool:
    token_path = Path(
        os.getenv(
            "BUILDEROPS_PROBE_TOKEN_FILE",
            "/run/secrets/builderops_probe_token",
        )
    )
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    if not token:
        return False
    url = os.getenv("BUILDEROPS_PROBE_URL", "http://127.0.0.1:8000/healthz")
    timeout = max(0.1, float(os.getenv("BUILDEROPS_HEALTH_TIMEOUT_SECONDS", "2")))
    request = Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed/operator URL
            payload = json.loads(response.read())
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return False
    return response.status == 200 and payload == {"ok": True}


def probe_worker() -> bool:
    try:
        store = production_store(database_environment(os.environ))
        heartbeat = store.service_heartbeat("outbox-worker")
    except (OSError, RuntimeError, ValueError):
        return False
    if heartbeat is None or heartbeat.get("state") != "running":
        return False
    observed_at = heartbeat.get("observed_at")
    if not isinstance(observed_at, datetime):
        return False
    maximum_age = max(1.0, float(os.getenv("BUILDEROPS_WORKER_HEARTBEAT_MAX_AGE_SECONDS", "45")))
    age = (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
    return 0 <= age <= maximum_age


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["liveness"]:
        return 0 if probe_liveness() else 1
    if arguments == ["worker"]:
        return 0 if probe_worker() else 1
    return 2


if __name__ == "__main__":  # pragma: no cover - container entrypoint
    raise SystemExit(main())


__all__ = ["main", "probe_liveness", "probe_worker"]
