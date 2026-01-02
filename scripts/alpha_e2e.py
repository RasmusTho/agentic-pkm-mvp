#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_DEFAULT_API_BASE = "http://127.0.0.1:18000"
_REQUIRED_TOPIC = "promote.intent.created"


def _fetch_json(url: str, timeout: float = 5.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw) if raw else {}
    if not isinstance(payload, dict):
        raise ValueError("non-json payload")
    return payload


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_postgres_dsn(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith("postgres://")
        or lowered.startswith("postgresql://")
        or lowered.startswith("postgresql+")
    )


def _worker_heartbeat_path() -> Path:
    raw = os.getenv("WORKER_HEARTBEAT_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path("tmp") / "worker_heartbeat.json"


def _write_test_note(vault_root: Path) -> Path:
    inbox = vault_root / "@Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    note_path = inbox / "alpha_e2e_runtime.md"
    stamp = time.time()
    content = f"---\nuuid: alpha-e2e-{int(stamp)}\n---\n# Alpha E2E Runtime\n\n- [x] Make this note evergreen <!--ai:id=promote.evergreen-->\n"
    note_path.write_text(content, encoding="utf-8")
    return note_path


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


def validate_runtime_progress(
    *,
    baseline_pending: int | None,
    current_pending: int | None,
    baseline_processed: int,
    current_processed: int,
    processed_by_event: dict[str, int] | None,
    required_topic: str,
) -> list[str]:
    errors: list[str] = []
    if baseline_pending is not None and current_pending is not None:
        if current_pending < baseline_pending + 1:
            errors.append("worker_queue.pending did not increase")
    if current_processed < baseline_processed + 1:
        errors.append("worker processed_total did not increase")
    if processed_by_event is None or processed_by_event.get(required_topic, 0) < 1:
        errors.append(f"worker did not process {required_topic}")
    return errors


def _run(cmd: list[str], *, allow_fail: bool = False) -> None:
    result = subprocess.run(cmd, check=not allow_fail)
    if result.returncode != 0 and not allow_fail:
        raise subprocess.CalledProcessError(result.returncode, cmd)


def _wait_for(label: str, timeout_s: float, interval_s: float, predicate) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _run_golden_path(vault_root: Path, api_base: str) -> list[str]:
    status = _fetch_json(f"{api_base}/api/status")
    worker_queue = status.get("worker_queue") or {}
    if not isinstance(worker_queue, dict) or worker_queue.get("mode") != "db":
        return ["worker_queue.mode is not db"]

    baseline_pending = int(worker_queue.get("pending") or 0)
    heartbeat_path = _worker_heartbeat_path()
    heartbeat = _read_json_file(heartbeat_path) or {}
    baseline_processed = int(heartbeat.get("processed_total") or 0)

    note_path = _write_test_note(vault_root)

    pending_ok = _wait_for(
        "pending",
        timeout_s=30.0,
        interval_s=1.0,
        predicate=lambda: int((_fetch_json(f"{api_base}/api/status").get("worker_queue") or {}).get("pending") or 0)
        >= baseline_pending + 1,
    )
    if not pending_ok:
        return ["worker_queue.pending did not increase"]

    def _processed_ready() -> bool:
        hb = _read_json_file(heartbeat_path) or {}
        processed_total = int(hb.get("processed_total") or 0)
        processed_by_event = hb.get("processed_by_event")
        errors = validate_runtime_progress(
            baseline_pending=None,
            current_pending=None,
            baseline_processed=baseline_processed,
            current_processed=processed_total,
            processed_by_event=processed_by_event if isinstance(processed_by_event, dict) else None,
            required_topic=_REQUIRED_TOPIC,
        )
        return not errors

    processed_ok = _wait_for("processed", timeout_s=30.0, interval_s=1.0, predicate=_processed_ready)
    if not processed_ok:
        hb = _read_json_file(heartbeat_path) or {}
        processed_total = int(hb.get("processed_total") or 0)
        processed_by_event = hb.get("processed_by_event")
        errors = validate_runtime_progress(
            baseline_pending=None,
            current_pending=None,
            baseline_processed=baseline_processed,
            current_processed=processed_total,
            processed_by_event=processed_by_event if isinstance(processed_by_event, dict) else None,
            required_topic=_REQUIRED_TOPIC,
        )
        return errors or ["worker did not process event in time"]

    return []


def main() -> int:
    vault_root_raw = os.getenv("VAULT_ROOT")
    if not vault_root_raw:
        print("ALPHA_E2E: VAULT_ROOT is required", file=sys.stderr)
        return 2

    api_base = os.getenv("API_BASE_URL") or _DEFAULT_API_BASE
    vault_root = Path(vault_root_raw).expanduser()

    try:
        _run(["make", "alpha-down"], allow_fail=True)
        _run(["make", "alpha-up"])
        status = _fetch_json(f"{api_base}/api/status")
        health = _fetch_json(f"{api_base}/api/health")
        errors = validate_status_invariants(status, health)
        if errors:
            print(f"ALPHA_E2E: FAIL - {errors[0]}")
            return 2
        flow_errors = _run_golden_path(vault_root, api_base)
        if flow_errors:
            print(f"ALPHA_E2E: FAIL - {flow_errors[0]}")
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
