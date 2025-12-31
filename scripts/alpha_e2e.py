#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any


def _fetch_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw) if raw else {}
    if not isinstance(payload, dict):
        raise ValueError("non-json payload")
    return payload


def _is_postgres_dsn(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("postgres://") or lowered.startswith("postgresql://")


def validate_status_invariants(status: dict[str, Any], health: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    if health.get("required_ok") is not True:
        errors.append("health.required_ok is not true")

    if "pending_from_events_log" in status:
        errors.append("status.pending_from_events_log must not be present")

    worker_queue = status.get("worker_queue") or {}
    if isinstance(worker_queue, dict) and "pending_from_events_log" in worker_queue:
        errors.append("worker_queue.pending_from_events_log must not be present")

    mode = worker_queue.get("mode") if isinstance(worker_queue, dict) else None
    if mode in {"file", "jsonl"}:
        events_log = status.get("events_log") or {}
        if isinstance(events_log, dict) and isinstance(worker_queue, dict):
            events_path = events_log.get("path")
            outbox = status.get("outbox") or {}
            outbox_path = outbox.get("path") if isinstance(outbox, dict) else None
            if events_path and outbox_path and events_path != outbox_path:
                errors.append("events_log.path does not match outbox.path")

            total_lines = events_log.get("total_lines")
            processed_total = worker_queue.get("processed_total")
            pending = worker_queue.get("pending")
            if isinstance(total_lines, int) and isinstance(processed_total, int) and isinstance(pending, int):
                expected = max(total_lines - processed_total, 0)
                if pending != expected:
                    errors.append("worker_queue.pending does not match events_log total_lines")
            else:
                errors.append("worker_queue pending/processed_total/events_log total_lines must be integers for file queue")
    elif mode == "db":
        source_path = worker_queue.get("source_path") if isinstance(worker_queue, dict) else None
        if not isinstance(source_path, str) or not _is_postgres_dsn(source_path):
            errors.append("worker_queue.source_path is not a postgres DSN")
    else:
        errors.append("worker_queue.mode is missing or unsupported")

    return errors


def _run(cmd: list[str], *, allow_fail: bool = False) -> None:
    result = subprocess.run(cmd, check=not allow_fail)
    if result.returncode != 0 and not allow_fail:
        raise subprocess.CalledProcessError(result.returncode, cmd)


def main() -> int:
    if not os.getenv("VAULT_ROOT"):
        print("ALPHA_E2E: VAULT_ROOT is required", file=sys.stderr)
        return 2

    try:
        _run(["make", "alpha-down"], allow_fail=True)
        _run(["make", "alpha-up"])
        status = _fetch_json("http://127.0.0.1:18000/api/status")
        health = _fetch_json("http://127.0.0.1:18000/api/health")
        errors = validate_status_invariants(status, health)
        if errors:
            print(f"ALPHA_E2E: FAIL - {errors[0]}")
            return 2
        print("ALPHA_E2E: OK")
        return 0
    except (urllib.error.URLError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"ALPHA_E2E: FAIL - {exc}")
        return 2
    finally:
        try:
            _run(["make", "alpha-down"], allow_fail=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
