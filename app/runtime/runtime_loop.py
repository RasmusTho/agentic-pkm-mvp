from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from app.outbox.events import INDEX_OUTBOX_PATH
from app.promotion.consumer import consume_promotion_intents
from app.watcher.events import emit_watcher_run_event
from app.watcher.heartbeat import resolve_heartbeat_path, write_runtime_heartbeat
from app.watcher.vault_watcher import VaultWatcher, run_watcher_tick


class OutboxPathError(ValueError):
    """Raised when the outbox path cannot be resolved."""


Summary = dict[str, object]


def resolve_outbox_path(path: Path | str | None) -> Path:
    candidate = path
    if candidate is None:
        env_value = os.getenv("INDEX_OUTBOX_PATH")
        candidate = env_value.strip() if env_value and env_value.strip() else INDEX_OUTBOX_PATH

    resolved = Path(candidate).expanduser()
    if str(resolved).strip() == "":
        raise OutboxPathError("Outbox path is required and cannot be empty.")
    if resolved.exists() and resolved.is_dir():
        raise OutboxPathError(f"Outbox path points to a directory: {resolved}")
    return resolved


def _as_int(value: object | None) -> int:
    try:
        return int(value) if value is not None else 0
    except Exception:
        return 0


_runtime_heartbeat_ticks = 0


def _emit_runtime_heartbeat(summary: Summary) -> None:
    global _runtime_heartbeat_ticks
    _runtime_heartbeat_ticks += 1
    try:
        path = resolve_heartbeat_path()
    except Exception:
        return
    write_runtime_heartbeat(
        path=path,
        ticks=_runtime_heartbeat_ticks,
        changed=_as_int(summary.get("changed")),
        errors=_as_int(summary.get("errors")),
    )


class OutboxPathError(ValueError):
    """Raised when the outbox path cannot be resolved."""


def resolve_outbox_path(path: Path | str | None) -> Path:
    candidate = path
    if candidate is None:
        env_value = os.environ.get("INDEX_OUTBOX_PATH", "").strip()
        if not env_value:
            raise OutboxPathError("Outbox path is required; set INDEX_OUTBOX_PATH or pass --outbox-path.")
        candidate = env_value

    resolved = Path(candidate).expanduser()
    if str(resolved).strip() == "":
        raise OutboxPathError("Outbox path is required and cannot be empty.")
    if resolved.exists() and resolved.is_dir():
        raise OutboxPathError(f"Outbox path points to a directory: {resolved}")
    return resolved


@dataclass
class RuntimeLoopConfig:
    snapshot_path: Path | None = None
    poll_seconds: int = 30
    cooldown_seconds: int = 10
    max_notes: int = 50
    force: bool = False
    dry_run: bool = False
    run_panels: bool = True
    run_promotion_consumer: bool = True
    outbox_path: Path | None = None


@dataclass
class RuntimeRunSummary:
    watcher: Dict[str, object] = field(default_factory=dict)
    promotion: Dict[str, object] = field(default_factory=dict)


def run_once(vault_root: Path, cfg: RuntimeLoopConfig) -> RuntimeRunSummary:
    outbox_path = resolve_outbox_path(cfg.outbox_path)
    watcher_summary, messages = run_watcher_tick(
        vault_root=vault_root,
        snapshot_path=cfg.snapshot_path,
        skip_panel=not cfg.run_panels,
        emit_only=False,
        dry_run=cfg.dry_run,
        max_notes=cfg.max_notes,
        force=cfg.force,
        outbox_path=outbox_path,
    )

    _emit_runtime_heartbeat(watcher_summary)

    for msg in messages:
        print(msg)

    promotion_summary: Dict[str, object] = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0}
    cursor_path = None
    if cfg.snapshot_path is not None:
        cursor_path = Path(str(cfg.snapshot_path) + ".outbox_cursor.json")
    if cfg.run_promotion_consumer and not cfg.dry_run:
        promotion_summary = consume_promotion_intents(
            outbox_path=outbox_path, cursor_path=cursor_path, snapshot_path=cfg.snapshot_path
        )
        if cfg.snapshot_path is not None:
            VaultWatcher(vault_root, snapshot_path=cfg.snapshot_path).refresh_snapshot()

    emit_watcher_run_event(
        watcher_summary,
        vault_root=vault_root,
        snapshot_path=watcher_summary.get("snapshot_path") or cfg.snapshot_path,
        outbox_path=outbox_path,
        trigger="runtime_loop",
    )

    return RuntimeRunSummary(watcher=watcher_summary, promotion=promotion_summary)


def run_forever(vault_root: Path, cfg: RuntimeLoopConfig) -> None:
    while True:
        summary = run_once(vault_root, cfg)
        delay = cfg.cooldown_seconds if summary.watcher.get("changed", 0) else cfg.poll_seconds
        time.sleep(delay)


__all__ = [
    "RuntimeLoopConfig",
    "RuntimeRunSummary",
    "run_once",
    "run_forever",
    "resolve_outbox_path",
    "OutboxPathError",
]
