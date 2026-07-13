"""Agent-facing dispatcher CLI.

Usage:
    python -m app.dispatcher.cli <command> [options] [--json]

All commands accept --json after the subcommand to emit compact JSON output
suitable for agent parsing.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from typing import Any

from app.dispatcher import leases as lease_module
from app.dispatcher import queue as queue_module
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import LeaseRecord, TaskRecord
from app.dispatcher.singleton import (
    DEFAULT_SINGLETON_TTL_SECONDS,
    DispatcherSingletonBusyError,
    singleton_status,
    start_singleton,
)
from app.dispatcher.store import SqliteStore
from app.dispatcher.sync_github import (
    PROVIDER_IDENTITY,
    GhCliIssueSource,
    PullSyncAdapter,
    get_sync_meta,
)

REQUIRED_COMMANDS = frozenset([
    "init", "queue", "next", "show", "claim",
    "heartbeat", "release", "update", "move", "block", "complete", "events", "pull",
    "export-signboard", "signboard-validate", "backup", "mode",
])


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _compact_task(task: TaskRecord) -> dict[str, Any]:
    """Compact task dict — omits sync_state to avoid large blobs."""
    return {
        "task_id": task.task_id,
        "issue_number": task.issue_number,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "claimed_by": task.claimed_by,
        "lease_id": task.lease_id,
        "lease_expires_at": task.lease_expires_at,
        "linked_pr": task.linked_pr,
        "blocked_reason": task.blocked_reason,
        "updated_at": task.updated_at,
    }


def _compact_lease(lease: LeaseRecord) -> dict[str, Any]:
    return {
        "lease_id": lease.lease_id,
        "resource": lease.resource,
        "holder": lease.holder,
        "expires_at": lease.expires_at,
        "heartbeat_at": lease.heartbeat_at,
        "released_at": lease.released_at,
    }


def _emit(data: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def _emit_error(msg: str, as_json: bool, code: int = 1) -> int:
    payload = {"ok": False, "error": msg}
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    return code


def _emit_payload(data: dict[str, Any], as_json: bool, code: int) -> int:
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)
    return code


def _coordination_payload(db_exists: bool) -> dict[str, Any]:
    if db_exists:
        return {
            "coordination_mode": "dispatcher-backed",
            "fallback_reason": None,
            "setup_command": None,
            "fallback_command": None,
        }
    return {
        "coordination_mode": "github-label-only-fallback",
        "fallback_reason": "dispatcher_db_missing",
        "setup_command": "python -m app.dispatcher start --agent <agent_id> --json",
        "fallback_command": (
            "scripts/issue_pickup_claim.sh --issue <ISSUE_NUMBER> --agent <agent_id> "
            "--session <session_id> --coordination-mode github-label-only-fallback "
            "--fallback-reason dispatcher_db_missing"
        ),
    }


def _make_store(env: dict[str, str] | None = None) -> SqliteStore:
    paths = load_paths(env)
    writer = JsonlEventWriter(paths.events_path)
    return SqliteStore(db_path=paths.db_path, event_writer=writer)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_init(args: argparse.Namespace, store: SqliteStore) -> int:
    paths = load_paths()
    try:
        singleton = start_singleton(
            paths,
            holder=args.agent,
            ttl_seconds=args.ttl_seconds,
        )
    except (DispatcherSingletonBusyError, ValueError) as exc:
        return _emit_error(str(exc), args.json)
    store.initialize()
    singleton.update(singleton_status(paths))
    _emit({
        "ok": True,
        **singleton,
    }, args.json)
    return 0


def _cmd_start(args: argparse.Namespace, store: SqliteStore) -> int:
    paths = load_paths()
    try:
        singleton = start_singleton(
            paths,
            holder=args.agent,
            ttl_seconds=args.ttl_seconds,
        )
    except (DispatcherSingletonBusyError, ValueError) as exc:
        return _emit_error(str(exc), args.json)
    store.initialize()
    singleton.update(singleton_status(paths))
    _emit({"ok": True, **singleton}, args.json)
    return 0


def _cmd_queue(args: argparse.Namespace, store: SqliteStore) -> int:
    tasks = store.list_tasks()
    by_status: dict[str, int] = {}
    for t in tasks:
        by_status[t.status] = by_status.get(t.status, 0) + 1
    _emit({
        "ok": True,
        "total": len(tasks),
        "by_status": by_status,
        "tasks": [_compact_task(t) for t in tasks],
    }, args.json)
    return 0


def _cmd_next(args: argparse.Namespace, store: SqliteStore) -> int:
    task = queue_module.next(store, agent_id=args.agent)
    if task is None:
        _emit({"ok": True, "task": None, "empty": True}, args.json)
    else:
        _emit({"ok": True, "task": _compact_task(task)}, args.json)
    return 0


def _cmd_show(args: argparse.Namespace, store: SqliteStore) -> int:
    task = store.get_task(args.task_id)
    if task is None:
        return _emit_error(f"Task {args.task_id} not found", args.json)
    _emit({"ok": True, "task": _compact_task(task)}, args.json)
    return 0


def _cmd_claim(args: argparse.Namespace, store: SqliteStore) -> int:
    try:
        task, lease = lease_module.claim(
            store,
            task_id=args.task_id,
            agent_id=args.agent,
            ttl_minutes=args.ttl_minutes,
            takeover_stale=args.takeover_stale,
        )
        _emit({
            "ok": True,
            "task": _compact_task(task),
            "lease": _compact_lease(lease),
        }, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_heartbeat(args: argparse.Namespace, store: SqliteStore) -> int:
    try:
        lease = lease_module.heartbeat(store, task_id=args.task_id, agent_id=args.agent)
        _emit({"ok": True, "lease": _compact_lease(lease)}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_release(args: argparse.Namespace, store: SqliteStore) -> int:
    try:
        task = lease_module.release(store, task_id=args.task_id, agent_id=args.agent)
        _emit({"ok": True, "task": _compact_task(task)}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_update(args: argparse.Namespace, store: SqliteStore) -> int:
    from app.dispatcher.services import update_task
    try:
        task = update_task(
            store,
            task_id=args.task_id,
            status=args.status,
            note=args.note,
            actor=args.agent,
        )
        _emit({"ok": True, "task": _compact_task(task)}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_move(args: argparse.Namespace, store: SqliteStore) -> int:
    from app.dispatcher.services import move_task
    try:
        task = move_task(
            store,
            task_id=args.task_id,
            status=args.status,
            note=args.note,
            actor=args.agent,
        )
        _emit({"ok": True, "task": _compact_task(task)}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_block(args: argparse.Namespace, store: SqliteStore) -> int:
    try:
        task = queue_module.block(
            store,
            task_id=args.task_id,
            reason=args.reason,
            actor=args.agent,
        )
        _emit({"ok": True, "task": _compact_task(task)}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_complete(args: argparse.Namespace, store: SqliteStore) -> int:
    try:
        task = queue_module.complete(
            store,
            task_id=args.task_id,
            actor=args.agent,
        )
        _emit({"ok": True, "task": _compact_task(task)}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_events(args: argparse.Namespace, store: SqliteStore) -> int:
    events = store.list_events()
    tail = args.tail
    events = events[-tail:]
    _emit({
        "ok": True,
        "count": len(events),
        "events": [e.to_dict() for e in events],
    }, args.json)
    return 0


def _cmd_link_pr(args: argparse.Namespace, store: SqliteStore) -> int:
    from app.dispatcher.services import link_pr
    try:
        task = link_pr(store, task_id=args.task_id, pr_number=args.pr, actor=args.agent)
        _emit({"ok": True, "task": _compact_task(task)}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_status(args: argparse.Namespace, store: SqliteStore) -> int:
    paths = load_paths()
    status = singleton_status(paths)
    control_plane: dict[str, Any]
    if status["db_exists"]:
        from app.dispatcher.control_plane import state
        try:
            control_plane = state(store)
        except (ValueError, sqlite3.Error) as exc:
            return _emit_error(str(exc), args.json)
    else:
        control_plane = {"mode": "unavailable", "revision": None}
    _emit({
        "ok": True,
        **status,
        "control_plane": control_plane,
        **_coordination_payload(bool(status["db_exists"])),
    }, args.json)
    return 0


def _cmd_pull(args: argparse.Namespace, store: SqliteStore) -> int:
    # With ``action="append"`` args.repo is a list; a single --repo X still
    # arrives as a one-element list.
    repos = args.repo
    if not repos:
        return _emit_error("--repo is required for pull command", args.json)

    source = GhCliIssueSource()
    adapter = PullSyncAdapter(store=store, source=source)

    total_upserted = 0
    total_reconciled = 0
    per_repo: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    last_sync_result: str | None = None
    last_sync_note: str | None = None
    try:
        for repo in repos:
            upserted = adapter.pull(repo)
            # Sync-meta is provider-scoped (shared across repos for one gh
            # identity), so inspect it immediately after each pull — before the
            # next iteration overwrites it — to attribute failures per repo.
            sync_meta = get_sync_meta(store, PROVIDER_IDENTITY) or {}
            reconciled = getattr(adapter, "last_reconciled_count", 0)
            result = sync_meta.get("sync_result")
            note = sync_meta.get("sync_note")
            last_sync_result = result
            last_sync_note = note
            repo_entry: dict[str, Any] = {
                "upserted": len(upserted),
                "reconciled": reconciled,
                "sync_result": result,
            }
            if result == "error":
                repo_entry["sync_note"] = note or "dispatcher pull source failed"
                failures.append(f"{repo}: {repo_entry['sync_note']}")
            else:
                total_upserted += len(upserted)
                total_reconciled += reconciled
            per_repo[repo] = repo_entry
    except Exception as exc:
        return _emit_error(f"pull failed: {exc}", args.json)

    if failures:
        # sync_note is the joined per-repo failure list, not last_sync_note:
        # in a mixed-outcome pull the last-processed repo can be a successful
        # one, which would leave sync_note blank while ok=False/error names a
        # real failure — the per-repo detail already lives in "repos".
        _emit({
            "ok": False,
            "error": "pull failed: " + "; ".join(failures),
            "upserted": total_upserted,
            "reconciled": total_reconciled,
            "skipped": 0,
            "provider": "github",
            "sync_result": "error",
            "sync_note": "; ".join(failures),
            "repos": per_repo,
        }, args.json)
        return 1

    _emit({
        "ok": True,
        "upserted": total_upserted,
        "reconciled": total_reconciled,
        "skipped": 0,
        "provider": "github",
        "sync_result": last_sync_result,
        "sync_note": last_sync_note,
        "repos": per_repo,
    }, args.json)
    return 0


def _cmd_export_signboard(args: argparse.Namespace, store: SqliteStore) -> int:
    from pathlib import Path

    from app.dispatcher.signboard import NoActiveVaultError, default_signboard_root, export_signboard

    if args.path:
        target_path = Path(args.path)
    else:
        try:
            target_path = default_signboard_root()
        except NoActiveVaultError as exc:
            return _emit_error(str(exc), args.json)

    result = export_signboard(store, target_path)
    _emit({"ok": True, **result}, args.json)
    return 0


def _cmd_signboard_validate(args: argparse.Namespace, store: SqliteStore) -> int:
    from pathlib import Path

    from app.dispatcher.signboard import (
        NoActiveVaultError,
        default_signboard_root,
        validate_signboard,
    )

    if args.path:
        target_path = Path(args.path)
    else:
        try:
            target_path = default_signboard_root()
        except NoActiveVaultError as exc:
            return _emit_error(str(exc), args.json)

    result = validate_signboard(store, target_path)
    if result["findings"]:
        _emit_payload({"ok": False, **result}, args.json, 1)
        return 1
    _emit({"ok": True, **result}, args.json)
    return 0


def _cmd_health(args: argparse.Namespace, store: SqliteStore) -> int:
    from app.dispatcher.control_plane import health
    result = health(load_paths())
    _emit({"ok": result["ok"], **result}, args.json)
    return 0 if result["ok"] else 1


def _cmd_backup(args: argparse.Namespace, store: SqliteStore) -> int:
    from pathlib import Path
    from app.dispatcher.control_plane import backup
    try:
        _emit({"ok": True, **backup(load_paths(), Path(args.destination))}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_restore(args: argparse.Namespace, store: SqliteStore) -> int:
    from pathlib import Path
    from app.dispatcher.config import load_paths as target_paths
    from app.dispatcher.control_plane import restore
    try:
        target = target_paths({"DISPATCHER_STATE_DIR": args.target_state_dir})
        _emit({"ok": True, **restore(Path(args.backup_dir), target)}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


def _cmd_mode(args: argparse.Namespace, store: SqliteStore) -> int:
    from app.dispatcher.control_plane import transition
    try:
        result = transition(store, load_paths(), args.mode, activation_id=args.activation_id, expected_revision=args.expected_revision)
        _emit({"ok": True, "control_plane": result}, args.json)
        return 0
    except ValueError as exc:
        return _emit_error(str(exc), args.json)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_COMMAND_MAP = {
    "init": _cmd_init,
    "start": _cmd_start,
    "queue": _cmd_queue,
    "next": _cmd_next,
    "show": _cmd_show,
    "claim": _cmd_claim,
    "heartbeat": _cmd_heartbeat,
    "release": _cmd_release,
    "update": _cmd_update,
    "move": _cmd_move,
    "block": _cmd_block,
    "complete": _cmd_complete,
    "events": _cmd_events,
    "link-pr": _cmd_link_pr,
    "status": _cmd_status,
    "pull": _cmd_pull,
    "export-signboard": _cmd_export_signboard,
    "signboard-validate": _cmd_signboard_validate,
    "health": _cmd_health,
    "backup": _cmd_backup,
    "restore": _cmd_restore,
    "mode": _cmd_mode,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.dispatcher.cli",
        description="Agent-facing dispatcher CLI",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("init", help="Initialize dispatcher state")
    p.add_argument("--agent", default="cli")
    p.add_argument("--ttl-seconds", type=int, default=DEFAULT_SINGLETON_TTL_SECONDS)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("start", help="Initialize dispatcher state and singleton status")
    p.add_argument("--agent", default="cli")
    p.add_argument("--ttl-seconds", type=int, default=DEFAULT_SINGLETON_TTL_SECONDS)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("queue", help="Show queue summary")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("next", help="Get next available task")
    p.add_argument("--agent", default="cli")
    p.add_argument("--capability", default=None, help="Capability hint (informational)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("show", help="Show task details")
    p.add_argument("task_id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("claim", help="Claim a task")
    p.add_argument("task_id")
    p.add_argument("--agent", required=True)
    p.add_argument("--ttl-minutes", type=int, default=90, dest="ttl_minutes")
    p.add_argument("--takeover-stale", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("heartbeat", help="Update lease heartbeat")
    p.add_argument("task_id")
    p.add_argument("--agent", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("release", help="Release a task lease")
    p.add_argument("task_id")
    p.add_argument("--agent", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("update", help="Update task status or add note")
    p.add_argument("task_id")
    p.add_argument("--status", default=None)
    p.add_argument("--note", default=None)
    p.add_argument("--agent", default="cli")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("move", help="Move a task to a lifecycle status")
    p.add_argument("task_id")
    p.add_argument("--status", required=True)
    p.add_argument("--note", default=None)
    p.add_argument("--agent", default="cli")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("block", help="Mark task as blocked")
    p.add_argument("task_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--agent", default="cli")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("complete", help="Complete a task (terminal)")
    p.add_argument("task_id")
    p.add_argument("--agent", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("events", help="Show recent events")
    p.add_argument("--tail", type=int, default=20)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("link-pr", help="Link a PR to a task")
    p.add_argument("task_id")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--agent", default="cli")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("status", help="Show dispatcher path/status information")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("health", help="Check dispatcher database and event-log health")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("backup", help="Create an online dispatcher backup")
    p.add_argument("destination")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("restore", help="Restore a backup into a separate state root")
    p.add_argument("backup_dir")
    p.add_argument("--target-state-dir", required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("mode", help="Make an explicit logical control-plane mode transition")
    p.add_argument("mode", choices=("normal", "degraded", "recovery"))
    p.add_argument("--activation-id", required=True)
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("pull", help="Pull open agent:ready issues from GitHub")
    p.add_argument(
        "--repo",
        required=True,
        action="append",
        help="GitHub repo (owner/repo); may be repeated for multiple repos",
    )
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("export-signboard", help="Export dispatcher queue as a Signboard Markdown board")
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help=(
            "Directory to write kanban columns into. Optional: defaults to "
            "BuilderOpsVault/agent-delivery inside the active vault "
            "(active-vault-selection mechanism); no path needs to be typed."
        ),
    )
    p.add_argument("--json", action="store_true")

    p = sub.add_parser(
        "signboard-validate",
        help="Validate generated Signboard cards without changing the board or dispatcher store",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help=(
            "Directory containing Signboard columns. Optional: defaults to "
            "BuilderOpsVault/agent-delivery inside the active vault."
        ),
    )
    p.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    handler = _COMMAND_MAP.get(args.command)
    if handler is None:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1

    # Guard: commands requiring a DB must exit clearly if DB doesn't exist
    if args.command in REQUIRED_COMMANDS and args.command != "init":
        paths = load_paths()
        if not paths.db_path.exists():
            msg = "dispatcher not initialised — run: make dispatcher-init"
            return _emit_payload(
                {
                    "ok": False,
                    "error": msg,
                    "state_dir": str(paths.state_dir),
                    "db_path": str(paths.db_path),
                    **_coordination_payload(False),
                },
                getattr(args, "json", False),
                1,
            )

    store = _make_store()
    return handler(args, store)


if __name__ == "__main__":
    sys.exit(main())
