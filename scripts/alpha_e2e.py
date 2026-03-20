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
import urllib.parse
import urllib.request
import uuid
from typing import Any, Sequence

from app.testing.runtime_contract import (
    failing_check_names,
    validate_runtime_progress,
    validate_status_invariants,
    write_contract_report,
)
from app.vault.layout import load_layout
from app.vault.paths import get_vault_inbox_dir_rel
from scripts.yaml_roundtrip import load_frontmatter

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


def _worker_heartbeat_path() -> Path:
    raw = os.getenv("WORKER_HEARTBEAT_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path("tmp") / "worker_heartbeat.json"


def _runtime_note_dir(vault_root: Path, inbox_dir_rel: str) -> Path:
    return (vault_root / inbox_dir_rel / "_alpha_e2e").expanduser()


def _default_report_path() -> Path:
    return _REPO_ROOT / "tmp" / "alpha_e2e_report.json"


def _select_layout_note_rel(vault_root: Path) -> str | None:
    try:
        layout = load_layout(vault_root)
    except Exception:
        return None
    try:
        return str(layout.note_path.relative_to(vault_root))
    except Exception:
        return None


def _layout_env_defaults(vault_root: Path, layout_note_rel: str | None) -> dict[str, str]:
    if not layout_note_rel:
        return {}
    note_path = (vault_root / layout_note_rel).expanduser()
    try:
        raw = note_path.read_text(encoding="utf-8")
        frontmatter, _ = load_frontmatter(raw)
    except Exception:
        return {}
    if not isinstance(frontmatter, dict):
        return {}
    env: dict[str, str] = {}
    system = str(frontmatter.get("system_folder") or "").strip()
    inbox = str(frontmatter.get("inbox_folder") or "").strip()
    desk = str(frontmatter.get("desk_folder") or "").strip()
    if system:
        env["VAULT_SYSTEM_DIR_REL"] = system
    if inbox:
        env["VAULT_INBOX_DIR_REL"] = inbox
    if desk:
        env["VAULT_DESK_DIR_REL"] = desk
    return env


def _resolve_e2e_inbox_dir_rel(vault_root: Path, layout_env: dict[str, str]) -> str:
    layout_inbox = (layout_env.get("VAULT_INBOX_DIR_REL") or "").strip()
    if layout_inbox:
        return layout_inbox
    return get_vault_inbox_dir_rel(vault_root)


def _write_runtime_note(note_path: Path, note_uuid: str, *, checked: bool) -> None:
    checked_mark = "x" if checked else " "
    action_line = f"- [{checked_mark}] Make this note evergreen <!--ai:id=promote.evergreen-->"
    content = (
        "---\n"
        f"uuid: {note_uuid}\n"
        "created_by: alpha_e2e\n"
        "ai_panel_auto_run: watcher\n"
        "---\n"
        f"<!-- alpha-e2e-write-ts:{time.time_ns()} -->\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "Promote this test note when checked.\n\n"
        "## AI-åtgärder\n"
        f"{action_line}\n\n"
        "## AI-logg\n"
        "%% AI:End %%\n"
    )
    note_path.write_text(content, encoding="utf-8")


def _create_runtime_note(vault_root: Path, inbox_dir_rel: str, note_uuid: str) -> Path:
    runtime_dir = _runtime_note_dir(vault_root, inbox_dir_rel)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    note_path = runtime_dir / f"alpha_e2e_runtime_{note_uuid}.md"
    # Seed unchecked first so watcher/panel can detect an explicit toggle-to-checked transition.
    _write_runtime_note(note_path, note_uuid, checked=False)
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


def _run(cmd: list[str], *, allow_fail: bool = False, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=not allow_fail, cwd=_REPO_ROOT, env=env)


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
    vault_root = os.getenv("VAULT_ROOT")
    if vault_root and note_paths:
        base = Path(vault_root).expanduser().resolve()
        for path in note_paths:
            try:
                note_rel = path.resolve().relative_to(base)
            except Exception:
                continue
            encoded = urllib.parse.quote(str(note_rel))
            _debug_cmd(["curl", "-sS", f"{api_base}/api/debug/panel?note_rel={encoded}"])
    if note_paths:
        print("ALPHA_E2E: runtime notes created:")
        for path in note_paths:
            print(f"  {path}")


def _write_alpha_report(
    *,
    checks: dict[str, bool],
    errors: Sequence[str],
    status: dict[str, Any] | None = None,
    health: dict[str, Any] | None = None,
    note_paths: Sequence[Path] | None = None,
) -> None:
    payload = {
        "checks": checks,
        "failed_checks": failing_check_names(checks),
        "errors": list(errors),
        "status": status or {},
        "health": health or {},
        "runtime_notes": [str(path) for path in (note_paths or [])],
    }
    write_contract_report(_default_report_path(), payload)


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

    def _seed_ingested() -> bool:
        hb = _read_json_file(heartbeat_path) or {}
        return int(hb.get("processed_total") or 0) > baseline_processed

    # Wait for the seed note to be ingested so old/current panel states differ on the next update.
    _wait_for("seed_ingest", timeout_s=20.0, interval_s=1.0, predicate=_seed_ingested)
    seed_hb = _read_json_file(heartbeat_path) or {}
    baseline_processed = int(seed_hb.get("processed_total") or 0)
    seed_status = _read_status_safe(api_base)
    baseline_promote_created = _intent_counter(seed_status, "promote_created_total")
    baseline_promotion_executed = _event_counter(seed_status, "promotion_executed_total")
    time.sleep(1.2)
    _write_runtime_note(note_path, note_uuid, checked=True)

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
    layout_rel = _select_layout_note_rel(vault_root)
    layout_env = _layout_env_defaults(vault_root, layout_rel)
    inbox_dir_rel = _resolve_e2e_inbox_dir_rel(vault_root, layout_env)
    note_paths: list[Path] = []
    report_checks: dict[str, bool] = {
        "status_invariants_ok": False,
        "worker_queue_mode_db": False,
        "runtime_progress_ok": False,
    }
    last_status: dict[str, Any] = {}
    last_health: dict[str, Any] = {}
    error_messages: list[str] = []

    auto_bootstrap_env = os.getenv("AUTO_BOOTSTRAP")
    if auto_bootstrap_env is None:
        auto_bootstrap_env = "1"

    try:
        _run(["make", "alpha-down"], allow_fail=True)
        env = os.environ.copy()
        env["AUTO_BOOTSTRAP"] = auto_bootstrap_env
        # Isolate watcher control/state for SIT so stale stop/state files cannot poison results.
        env.setdefault("WATCHER_STOP_FILE", "/app/tmp/WATCHER_STOP_ALPHA_E2E")
        env.setdefault("WATCHER_STATE_DIR", "/app/tmp/watcher-state-alpha-e2e")
        scope_prefix = inbox_dir_rel.strip("/").strip()
        if scope_prefix:
            e2e_scope = f"{scope_prefix}/_alpha_e2e"
            env.setdefault("WATCHER_SCOPE_GLOB", f"{e2e_scope}/*.md,{e2e_scope}/**/*.md")
        env.setdefault("WATCHER_MAX_SCANNED_FILES_PER_TICK", "5000")
        env.setdefault("BOOTSTRAP_INGEST_MAX_NOTES", "50")
        runtime_dir = _runtime_note_dir(vault_root, inbox_dir_rel)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        if runtime_dir.exists():
            for stale in runtime_dir.glob("alpha_e2e_runtime_*.md"):
                stale.unlink(missing_ok=True)
        state_dir = _REPO_ROOT / "tmp" / "watcher-state-alpha-e2e"
        state_dir.mkdir(parents=True, exist_ok=True)
        for stale in state_dir.glob("watcher_state_*.json"):
            stale.unlink(missing_ok=True)
        stop_host = _REPO_ROOT / "tmp" / "WATCHER_STOP_ALPHA_E2E"
        stop_host.unlink(missing_ok=True)
        if layout_rel and not env.get("VAULT_LAYOUT_NOTE_REL"):
            env["VAULT_LAYOUT_NOTE_REL"] = layout_rel
        for key, value in layout_env.items():
            env[key] = value
        _run(["make", "alpha-up"], env=env)
        status = _fetch_json(f"{api_base}/api/status")
        health = _fetch_json(f"{api_base}/api/health")
        last_status = status
        last_health = health
        auto_bootstrap = auto_bootstrap_env == "1"
        if auto_bootstrap:
            action = _index_rebuild_required(health)
            if action:
                message = action.get("message") or "Embedding/index identity mismatch detected"
                hint = action.get("command_hint") or "python -m app.cli index rebuild --profile default"
                raise RuntimeError(f"AUTO_BOOTSTRAP=1 but index_rebuild is still required. {message}. command_hint: {hint}")
        else:
            health = _maybe_auto_rebuild_index(api_base, health)
            last_health = health
        report_checks["worker_queue_mode_db"] = (
            isinstance(status.get("worker_queue"), dict) and status.get("worker_queue", {}).get("mode") == "db"
        )
        errors = validate_status_invariants(status, health)
        report_checks["status_invariants_ok"] = not errors
        if errors:
            error_messages = errors
            _write_alpha_report(
                checks=report_checks,
                errors=error_messages,
                status=last_status,
                health=last_health,
                note_paths=note_paths,
            )
            raise RuntimeError(errors[0])
        flow_errors, created_note = _run_golden_path(vault_root, inbox_dir_rel, api_base)
        if created_note:
            note_paths.append(created_note)
        report_checks["runtime_progress_ok"] = not flow_errors
        if flow_errors:
            error_messages = flow_errors
            _write_alpha_report(
                checks=report_checks,
                errors=error_messages,
                status=last_status,
                health=last_health,
                note_paths=note_paths,
            )
            raise RuntimeError(flow_errors[0])
        _write_alpha_report(
            checks=report_checks,
            errors=[],
            status=last_status,
            health=last_health,
            note_paths=note_paths,
        )
        print("ALPHA_E2E: OK")
        _cleanup_runtime_notes(note_paths)
        return 0
    except (urllib.error.URLError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError, RuntimeError) as exc:
        if not error_messages:
            error_messages = [str(exc)]
        _write_alpha_report(
            checks=report_checks,
            errors=error_messages,
            status=last_status,
            health=last_health,
            note_paths=note_paths,
        )
        print(f"ALPHA_E2E: FAIL - {exc}")
        debug_dump(api_base, note_paths)
        if args.teardown and note_paths:
            _cleanup_runtime_notes(note_paths)
        return 2
    finally:
        _maybe_teardown(args.teardown)


if __name__ == "__main__":
    sys.exit(main())
