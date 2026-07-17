#!/usr/bin/env python3
"""Independent transition-based BuilderOps outage probe."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Protocol

BASE_URL = os.environ.get("BUILDEROPS_PROBE_BASE_URL", "http://127.0.0.1:18100")
TOKEN_FILE = Path(os.environ.get("BUILDEROPS_PROBE_TOKEN_FILE", ""))
STATUS_TOKEN_FILE = Path(os.environ.get("BUILDEROPS_STATUS_TOKEN_FILE", ""))
STATE_FILE = Path(os.environ.get("BUILDEROPS_PROBE_STATE_FILE", "/tmp/builderops-probe.state"))


class NotificationChannel(Protocol):
    def send(self, subject: str, body: str) -> None: ...


class NtfyChannel:
    def send(self, subject: str, body: str) -> None:
        server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        topic = os.environ.get("BUILDEROPS_NTFY_TOPIC", "builderops-alerts")
        request = urllib.request.Request(
            f"{server}/{topic}",
            data=body.encode(),
            headers={"Title": subject, "Priority": "high", "Tags": "warning,robot"},
            method="POST",
        )
        urllib.request.urlopen(request, timeout=10).close()


def _get(path: str, token: str) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode())


def run_probe(channel: NotificationChannel | None = None) -> bool:
    channel = channel or NtfyChannel()
    failures: list[str] = []
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        status_token = STATUS_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("health probe credential is empty")
        if not status_token:
            raise RuntimeError("status probe credential is empty")
        status, ready = _get("/readyz", token)
        if status != 200 or ready.get("ready") is not True:
            failures.append("readiness failed")
        _, control_status = _get("/status", status_token)
        recovery = control_status.get("recovery_pipeline", {})
        if isinstance(recovery, dict) and recovery.get("alert") is True:
            failures.append("backup/WAL recovery pipeline is stalled or lagging")
    except Exception as exc:
        failures.append(f"BuilderOps probe failed: {type(exc).__name__}")

    previous_down = STATE_FILE.exists()
    if failures:
        if not previous_down:
            channel.send("BuilderOps control plane down", "\n".join(failures))
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(
                json.dumps({"status": "down", "ts": int(time.time()), "failures": failures}),
                encoding="utf-8",
            )
        return False
    if previous_down:
        channel.send("BuilderOps control plane recovered", "Authenticated readiness is healthy.")
        STATE_FILE.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    raise SystemExit(0 if run_probe() else 1)
