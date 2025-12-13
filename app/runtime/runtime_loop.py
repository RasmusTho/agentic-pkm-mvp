from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from app.promotion.consumer import consume_promotion_intents
from app.watcher.vault_watcher import run_watcher_tick


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
    watcher_summary, messages = run_watcher_tick(
        vault_root=vault_root,
        snapshot_path=cfg.snapshot_path,
        skip_panel=not cfg.run_panels,
        emit_only=False,
        dry_run=cfg.dry_run,
        max_notes=cfg.max_notes,
        force=cfg.force,
    )

    for msg in messages:
        print(msg)

    promotion_summary: Dict[str, object] = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0}
    if cfg.run_promotion_consumer and not cfg.dry_run:
        promotion_summary = consume_promotion_intents(outbox_path=cfg.outbox_path)

    return RuntimeRunSummary(watcher=watcher_summary, promotion=promotion_summary)


def run_forever(vault_root: Path, cfg: RuntimeLoopConfig) -> None:
    while True:
        summary = run_once(vault_root, cfg)
        delay = cfg.cooldown_seconds if summary.watcher.get("changed", 0) else cfg.poll_seconds
        time.sleep(delay)


__all__ = ["RuntimeLoopConfig", "RuntimeRunSummary", "run_once", "run_forever"]
