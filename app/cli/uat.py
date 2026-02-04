from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from app.promotion.consumer import consume_promotion_intents
from app.watcher.vault_watcher import run_watcher_tick

SEED_SOURCE = Path(__file__).resolve().parents[2] / "docs" / "examples" / "vault_test_seed"
DEFAULT_TARGET_SUBDIR = "Test"
DEFAULT_FOLDER_NAME = "AgenticPKM-UAT"
DEFAULT_MAX_NOTES = 50


@dataclass
class SeedSummary:
    written: int
    skipped: int
    destination: Path


@dataclass
class UATSummary:
    watcher: Dict[str, object]
    promotion: Dict[str, object]

    def to_lines(self) -> list[str]:
        lines = [
            f"Watcher: changed={self.watcher.get('changed', 0)} ingest_attempted={self.watcher.get('ingest_attempted', 0)} ingested={self.watcher.get('ingested', 0)}",
            f"Panel: candidates={self.watcher.get('panel_candidates', 0)} runs={self.watcher.get('panel_runs', 0)} promote_intents={self.watcher.get('panel_promotions', 0)} skipped_policy={self.watcher.get('panel_skipped_policy', 0)}",
            f"Promotion consumer: intents_seen={self.promotion.get('intents_seen', 0)} applied={self.promotion.get('applied', 0)} errors={self.promotion.get('errors', 0)} emitted={self.promotion.get('emitted', 0)}",
        ]
        return lines


class UATAssertionError(Exception):
    pass


def seed_vault_test_notes(
    *,
    vault_root: Path,
    target_subdir: str = DEFAULT_TARGET_SUBDIR,
    folder: str = DEFAULT_FOLDER_NAME,
    overwrite: bool = False,
) -> SeedSummary:
    if not SEED_SOURCE.exists():
        raise FileNotFoundError(f"Seed source directory missing: {SEED_SOURCE}")

    dest = vault_root.expanduser().resolve() / target_subdir / folder
    dest.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    for seed_path in sorted(SEED_SOURCE.glob("*.md")):
        target_path = dest / seed_path.name
        if target_path.exists() and not overwrite:
            skipped += 1
            continue
        shutil.copy2(seed_path, target_path)
        written += 1

    return SeedSummary(written=written, skipped=skipped, destination=dest)


def _default_snapshot_path(scope: Path) -> Path:
    return scope / ".agentic-pkm" / "vault_watcher_uat_state.json"


def run_vault_test_flow(
    *,
    vault_root: Path,
    target_subdir: str = DEFAULT_TARGET_SUBDIR,
    folder: str = DEFAULT_FOLDER_NAME,
    max_notes: int = DEFAULT_MAX_NOTES,
    force: bool = False,
    dry_run: bool = False,
    run_panels: bool = True,
    consume_promotions: bool = True,
    assert_expectations: bool = False,
) -> UATSummary:
    scope = vault_root.expanduser().resolve() / target_subdir
    if not scope.exists() or not scope.is_dir():
        raise FileNotFoundError(f"Vault scope not found: {scope}")

    seeded_folder = scope / folder
    if not seeded_folder.exists():
        raise FileNotFoundError(f"Seed folder missing; run uat-seed-vault-test first: {seeded_folder}")

    snapshot_path = _default_snapshot_path(seeded_folder)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "index-outbox.jsonl"))

    watcher_summary, watcher_messages = run_watcher_tick(
        vault_root=scope,
        snapshot_path=snapshot_path,
        skip_panel=not run_panels,
        emit_only=False,
        dry_run=dry_run,
        max_notes=max_notes,
        force=force,
        outbox_path=outbox_path,
    )

    for msg in watcher_messages:
        print(msg)

    promotion_summary: Dict[str, object] = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0}
    if consume_promotions and not dry_run:
        outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "index-outbox.jsonl"))
        promotion_summary = consume_promotion_intents(outbox_path=outbox_path)

    summary = UATSummary(watcher=watcher_summary, promotion=promotion_summary)

    if assert_expectations and not dry_run:
        _assert_uat_expectations(summary)

    return summary


def _assert_uat_expectations(summary: UATSummary) -> None:
    failures: list[str] = []
    if summary.watcher.get("panel_promotions", 0) < 1:
        failures.append("Expected at least one promote.intent.created")
    if summary.promotion.get("applied", 0) < 1:
        failures.append("Expected at least one promotion to be applied by consumer")
    if failures:
        raise UATAssertionError("; ".join(failures))


__all__ = [
    "seed_vault_test_notes",
    "run_vault_test_flow",
    "UATSummary",
    "SeedSummary",
    "UATAssertionError",
    "SEED_SOURCE",
    "DEFAULT_TARGET_SUBDIR",
    "DEFAULT_FOLDER_NAME",
]
