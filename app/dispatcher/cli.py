"""Agent-facing dispatcher CLI.

Usage:
    python -m app.dispatcher.cli <command> [options] [--json]

All commands accept --json after the subcommand to emit compact JSON output
suitable for agent parsing.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.dispatcher import leases as lease_module
from app.dispatcher import queue as queue_module
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import LeaseRecord, TaskRecord
from app.dispatcher.store import SqliteStore

REQUIRED_COMMANDS = frozenset([
    "init", "queue", "next", "show", "claim",
    "heartbeat", "release", "update", "block", "events",
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


def _make_store(env: dict[str, str] | None = None) -> SqliteStore:
    paths = load_paths(env)
    writer = JsonlEventWriter(paths.events_path)
    return SqliteStore(db_path=paths.db_path, event_writer=writer)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_init(args: argparse.Namespace, store: SqliteStore) -> int:
    paths = load_paths()
    paths.ensure()
    store.initialize()
    _emit({
        "ok": True,
        "state_dir": str(paths.state_dir),
        "db_path": str(paths.db_path),
        "events_path": str(paths.events_path),
    }, args.json)
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


def _cmd_seed_demo(args: argparse.Namespace, store: SqliteStore) -> int:
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    _emit({
        "ok": True,
        "created": len(tasks),
        "tasks": [_compact_task(t) for t in tasks],
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
    _emit({
        "ok": True,
        "state_dir": str(paths.state_dir),
        "db_path": str(paths.db_path),
        "db_exists": paths.db_path.exists(),
        "events_path": str(paths.events_path),
        "events_exists": paths.events_path.exists(),
    }, args.json)
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_COMMAND_MAP = {
    "init": _cmd_init,
    "queue": _cmd_queue,
    "next": _cmd_next,
    "show": _cmd_show,
    "claim": _cmd_claim,
    "heartbeat": _cmd_heartbeat,
    "release": _cmd_release,
    "update": _cmd_update,
    "block": _cmd_block,
    "events": _cmd_events,
    "seed-demo": _cmd_seed_demo,
    "link-pr": _cmd_link_pr,
    "status": _cmd_status,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.dispatcher.cli",
        description="Agent-facing dispatcher CLI",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("init", help="Initialize dispatcher state")
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

    p = sub.add_parser("block", help="Mark task as blocked")
    p.add_argument("task_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--agent", default="cli")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("events", help="Show recent events")
    p.add_argument("--tail", type=int, default=20)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("seed-demo", help="Create demo tasks without GitHub access")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("link-pr", help="Link a PR to a task")
    p.add_argument("task_id")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--agent", default="cli")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("status", help="Show dispatcher path/status information")
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

    store = _make_store()
    return handler(args, store)


if __name__ == "__main__":
    sys.exit(main())
