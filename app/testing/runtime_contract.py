from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def is_postgres_dsn(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith("postgres://")
        or lowered.startswith("postgresql://")
        or lowered.startswith("postgresql+")
    )


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
            if (
                isinstance(total_lines, int)
                and isinstance(processed_total, int)
                and isinstance(pending, int)
            ):
                expected = max(total_lines - processed_total, 0)
                if pending != expected:
                    errors.append("worker_queue.pending does not match events_log total_lines")
            else:
                errors.append("worker_queue pending/processed_total/events_log total_lines must be integers for file queue")
    elif mode == "db":
        source_path = worker_queue.get("source_path") if isinstance(worker_queue, dict) else None
        if not isinstance(source_path, str) or not is_postgres_dsn(source_path):
            errors.append("worker_queue.source_path is not a postgres DSN")
    else:
        errors.append("worker_queue.mode is missing or unsupported")

    return errors


def validate_runtime_progress(
    *,
    baseline_processed: int,
    current_processed: int,
    processed_by_event: dict[str, int] | None,
    required_topic: str,
    baseline_promote_created: int | None,
    current_promote_created: int | None,
    baseline_promotion_executed: int | None,
    current_promotion_executed: int | None,
) -> list[str]:
    errors: list[str] = []
    processed_ok = False
    if current_processed >= baseline_processed + 1:
        if processed_by_event is not None:
            if processed_by_event.get(required_topic, 0) >= 1:
                processed_ok = True
            else:
                errors.append("worker processed_total increased but promote.intent.created not counted")
        else:
            processed_ok = True
    else:
        errors.append("worker processed_total did not increase")

    promote_created_ok = False
    if baseline_promote_created is not None and current_promote_created is not None:
        if current_promote_created > baseline_promote_created:
            promote_created_ok = True
        else:
            errors.append("status.intents.promote_created_total did not increase")
    else:
        errors.append("status.intents.promote_created_total missing")

    promotion_ok = False
    if baseline_promotion_executed is not None and current_promotion_executed is not None:
        if current_promotion_executed > baseline_promotion_executed:
            promotion_ok = True
        else:
            errors.append("status.events.promotion_executed_total did not increase")
    else:
        errors.append("status.events.promotion_executed_total missing")

    if processed_ok or promote_created_ok or promotion_ok:
        return []
    return errors


def failing_check_names(checks: Mapping[str, bool]) -> list[str]:
    return [name for name, passed in checks.items() if not passed]


def write_contract_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


__all__ = [
    "failing_check_names",
    "is_postgres_dsn",
    "validate_runtime_progress",
    "validate_status_invariants",
    "write_contract_report",
]
