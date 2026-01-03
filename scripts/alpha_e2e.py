#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Sequence

from app.vault.paths import ensure_vault_path_env_defaults, get_vault_inbox_dir_rel

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


def _runtime_note_dir(vault_root: Path, inbox_dir_rel: str) -> Path:
    return (vault_root / inbox_dir_rel / "_alpha_e2e").expanduser()


def _create_runtime_note(vault_root: Path, inbox_dir_rel: str, note_uuid: str) -> Path:
    runtime_dir = _runtime_note_dir(vault_root, inbox_dir_rel)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    note_path = runtime_dir / f"alpha_e2e_runtime_{note_uuid}.md"
    content = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "created_by: alpha_e2e\n"
        "---\n"
        "# Alpha E2E Runtime\n\n"
        "- [x] Make this note evergreen <!--ai:id=promote.evergreen-->\n"
    )
    note_path.write_text(content, encoding="utf-8")
    return note_path


def _cleanup_runtime_notes(paths: Sequence[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except Exception as exc:
            print(f"ALPHA_E2E: cleanup failed for {path}: {exc}", file=sys.stderr)


def _event_counter(status: dict[str, Any], key: str) -> int | None:
    events = status.get("events")
    if isinstance(events, dict):
        value = events.get(key)
        if isinstance(value, int):
            return value
    return None


def _intent_counter(status: dict[str, Any], key: str) -> int | None:
    intents = status.get("intents")
    if isinstance(intents, dict):
        value = intents.get(key)
        if isinstance(value, int):
            return value
    events = status.get("events")
    if isinstance(events, dict):
        value = events.get(key)
        if isinstance(value, int):
            return value
    return None


def _find_action(health: dict[str, Any], action_id: str) -> dict[str, Any] | None:
    actions = health.get("suggested_actions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict) and action.get("id") == action_id:
                return action
    return None


def _index_rebuild_command() -> list[str]:
    return [
        "docker",
        "compose",
        "exec",
        "-T",
        "api",
        "python",
        "-m",
        "app.cli",
        "index",
        "rebuild",
        "--profile",
        "default",
    ]


def _index_rebuild_required(health: dict[str, Any]) -> dict[str, Any] | None:
    action = _find_action(health, "index_rebuild")
    if not action:
        return None
    severity = str(action.get("severity") or "").lower()
    if severity != "required":
        return None
    return action


def _maybe_auto_rebuild_index(api_base: str, health: dict[str, Any]) -> dict[str, Any]:
    action = _index_rebuild_required(health)
    if not action:
        return health
    _run(_index_rebuild_command())
    refreshed = _fetch_json(f"{api_base}/api/health")
    if _index_rebuild_required(refreshed):
        message = action.get("message") or "Embedding/index identity mismatch detected"
        hint = action.get("command_hint") or "python -m app.cli index rebuild --profile default"
        raise RuntimeError(f"{message}. command_hint: {hint}")
    return refreshed


def _read_status_safe(api_base: str) -> dict[str, Any]:
    try:
        return _fetch_json(f"{api_base}/api/status")
    except Exception:
        return {}


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
        if not isinstance(source_path, str) or not _is_postgres_dsn(source_path):
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


def _run(cmd: list[str], *, allow_fail: bool = False) -> None:
    subprocess.run(cmd, check=not allow_fail, cwd=_REPO_ROOT)


def _debug_cmd(cmd: list[str]) -> None:
    print(f"ALPHA_E2E: DEBUG CMD: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, cwd=_REPO_ROOT, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())


def debug_dump(api_base: str, note_paths: Sequence[Path]) -> None:
    print("ALPHA_E2E: DEBUG DUMP")
    _debug_cmd(["curl", "-sS", f"{api_base}/api/status"])
    _debug_cmd(["curl", "-sS", f"{api_base}/api/health"])
    _debug_cmd(["docker", "compose", "ps"])
    _debug_cmd(["docker", "compose", "logs", "--tail=200", "watcher"])
    _debug_cmd(["docker", "compose", "logs", "--tail=200", "worker"])
    _debug_cmd(["docker", "compose", "logs", "--tail=200", "api"])
    if note_paths:
        print("ALPHA_E2E: runtime notes created:")
        for path in note_paths:
            print(f"  {path}")


def _wait_for(label: str, timeout_s: float, interval_s: float, predicate) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _run_golden_path(vault_root: Path, inbox_dir_rel: str, api_base: str) -> tuple[list[str], Path | None]:
    status = _fetch_json(f"{api_base}/api/status")
    worker_queue = status.get("worker_queue") or {}
    if not isinstance(worker_queue, dict) or worker_queue.get("mode") != "db":
        return ["worker_queue.mode is not db"], None

    baseline_promote_created = _intent_counter(status, "promote_created_total")
    baseline_promotion_executed = _event_counter(status, "promotion_executed_total")
    heartbeat_path = _worker_heartbeat_path()
    heartbeat = _read_json_file(heartbeat_path) or {}
    baseline_processed = int(heartbeat.get("processed_total") or 0)

    note_uuid = uuid.uuid4().hex
    note_path = _create_runtime_note(vault_root, inbox_dir_rel, note_uuid)

    def _processed_ready() -> bool:
        hb = _read_json_file(heartbeat_path) or {}
        processed_total = int(hb.get("processed_total") or 0)
        processed_by_event = hb.get("processed_by_event")
        current_status = _read_status_safe(api_base)
        current_promote_created = _intent_counter(current_status, "promote_created_total")
        current_promotion_executed = _event_counter(current_status, "promotion_executed_total")
        errors = validate_runtime_progress(
            baseline_processed=baseline_processed,
            current_processed=processed_total,
            processed_by_event=processed_by_event if isinstance(processed_by_event, dict) else None,
            required_topic=_REQUIRED_TOPIC,
            baseline_promote_created=baseline_promote_created,
            current_promote_created=current_promote_created,
            baseline_promotion_executed=baseline_promotion_executed,
            current_promotion_executed=current_promotion_executed,
        )
        return not errors

    processed_ok = _wait_for("processed", timeout_s=30.0, interval_s=1.0, predicate=_processed_ready)
    if not processed_ok:
        hb = _read_json_file(heartbeat_path) or {}
        processed_total = int(hb.get("processed_total") or 0)
        processed_by_event = hb.get("processed_by_event")
        current_status = _read_status_safe(api_base)
        current_promote_created = _intent_counter(current_status, "promote_created_total")
        current_promotion_executed = _event_counter(current_status, "promotion_executed_total")
        errors = validate_runtime_progress(
            baseline_processed=baseline_processed,
            current_processed=processed_total,
            processed_by_event=processed_by_event if isinstance(processed_by_event, dict) else None,
            required_topic=_REQUIRED_TOPIC,
            baseline_promote_created=baseline_promote_created,
            current_promote_created=current_promote_created,
            baseline_promotion_executed=baseline_promotion_executed,
            current_promotion_executed=current_promotion_executed,
        )
        return errors or ["worker did not process event in time"], note_path

    return [], note_path


def _maybe_teardown(teardown: bool) -> None:
    if teardown:
        _run(["make", "alpha-down"], allow_fail=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Alpha runtime e2e checks")
    parser.add_argument("--teardown", action="store_true", help="Tear down the Alpha stack after checks")
    args = parser.parse_args(argv)

    vault_root_raw = os.getenv("VAULT_ROOT")
    if not vault_root_raw:
        print("ALPHA_E2E: VAULT_ROOT is required", file=sys.stderr)
        return 2

    api_base = os.getenv("API_BASE_URL") or _DEFAULT_API_BASE
    vault_root = Path(vault_root_raw).expanduser()
    ensure_vault_path_env_defaults(vault_root)
    inbox_dir_rel = get_vault_inbox_dir_rel(vault_root)
    note_paths: list[Path] = []

    try:
        _run(["make", "alpha-down"], allow_fail=True)
        _run(["make", "alpha-up"])
        status = _fetch_json(f"{api_base}/api/status")
        health = _fetch_json(f"{api_base}/api/health")
        health = _maybe_auto_rebuild_index(api_base, health)
        errors = validate_status_invariants(status, health)
        if errors:
            raise RuntimeError(errors[0])
        flow_errors, created_note = _run_golden_path(vault_root, inbox_dir_rel, api_base)
        if created_note:
            note_paths.append(created_note)
        if flow_errors:
            raise RuntimeError(flow_errors[0])
        print("ALPHA_E2E: OK")
        _cleanup_runtime_notes(note_paths)
        return 0
    except (urllib.error.URLError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"ALPHA_E2E: FAIL - {exc}")
        debug_dump(api_base, note_paths)
        if args.teardown and note_paths:
            _cleanup_runtime_notes(note_paths)
        return 2
    finally:
        _maybe_teardown(args.teardown)


if __name__ == "__main__":
    sys.exit(main())
