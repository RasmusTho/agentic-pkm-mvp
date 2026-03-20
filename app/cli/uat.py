from __future__ import annotations
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from app.promotion.consumer import consume_promotion_intents
from app.testing.runtime_contract import failing_check_names, write_contract_report
from app.watcher.vault_watcher import VaultWatcher, run_watcher_tick
from scripts.yaml_roundtrip import load_frontmatter

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
    rerun: Dict[str, Dict[str, object]] | None = None
    checks: Dict[str, bool] | None = None
    report_path: Path | None = None

    def to_lines(self) -> list[str]:
        lines = [
            f"Watcher: changed={self.watcher.get('changed', 0)} ingest_attempted={self.watcher.get('ingest_attempted', 0)} ingested={self.watcher.get('ingested', 0)}",
            f"Panel: candidates={self.watcher.get('panel_candidates', 0)} runs={self.watcher.get('panel_runs', 0)} promote_intents={self.watcher.get('panel_promotions', 0)} skipped_policy={self.watcher.get('panel_skipped_policy', 0)}",
            f"Promotion consumer: intents_seen={self.promotion.get('intents_seen', 0)} applied={self.promotion.get('applied', 0)} errors={self.promotion.get('errors', 0)} emitted={self.promotion.get('emitted', 0)}",
        ]
        if self.rerun:
            rerun_watcher = self.rerun.get("watcher", {})
            rerun_promotion = self.rerun.get("promotion", {})
            lines.append(
                "Rerun: "
                f"changed={rerun_watcher.get('changed', 0)} "
                f"panel_runs={rerun_watcher.get('panel_runs', 0)} "
                f"promote_intents={rerun_watcher.get('panel_promotions', 0)} "
                f"promotion_applied={rerun_promotion.get('applied', 0)}"
            )
        if self.checks:
            passed = sum(1 for value in self.checks.values() if value)
            total = len(self.checks)
            lines.append(f"Checks: passed={passed}/{total}")
        if self.report_path is not None:
            lines.append(f"Report: {self.report_path}")
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


def _default_report_path(scope: Path) -> Path:
    return scope / ".agentic-pkm" / "uat_report.json"


def _load_frontmatter_dict(path: Path) -> dict[str, object]:
    try:
        frontmatter, _ = load_frontmatter(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return frontmatter if isinstance(frontmatter, dict) else {}


def _build_uat_checks(
    *,
    seeded_folder: Path,
    summary: UATSummary,
) -> Dict[str, bool]:
    evergreen_path = seeded_folder / "evergreen-strategy.md"
    manual_path = seeded_folder / "manual-policy.md"
    mixed_actions_path = seeded_folder / "mixed-actions.md"

    evergreen_frontmatter = _load_frontmatter_dict(evergreen_path)
    manual_frontmatter = _load_frontmatter_dict(manual_path)
    mixed_actions_frontmatter = _load_frontmatter_dict(mixed_actions_path)

    rerun_watcher = (summary.rerun or {}).get("watcher", {})
    rerun_promotion = (summary.rerun or {}).get("promotion", {})

    return {
        "watcher_errors_zero": int(summary.watcher.get("errors", 0) or 0) == 0,
        "promotion_errors_zero": int(summary.promotion.get("errors", 0) or 0) == 0,
        "promote_intent_emitted": int(summary.watcher.get("panel_promotions", 0) or 0) >= 1,
        "promotion_applied": int(summary.promotion.get("applied", 0) or 0) >= 1,
        "manual_policy_skipped": int(summary.watcher.get("panel_skipped_policy", 0) or 0) >= 1,
        "evergreen_note_promoted": (
            str(evergreen_frontmatter.get("review_state") or "") == "reviewed"
            and str(evergreen_frontmatter.get("maturity") or "") == "evergreen"
        ),
        "manual_note_unchanged": (
            str(manual_frontmatter.get("ai_panel_auto_run") or "") == "manual"
            and "maturity" not in manual_frontmatter
        ),
        "mixed_actions_stays_safe": str(mixed_actions_frontmatter.get("review_state") or "") in {"", "reviewed"},
        "rerun_no_changes": int(rerun_watcher.get("changed", 0) or 0) == 0,
        "rerun_no_panel_side_effects": (
            int(rerun_watcher.get("panel_runs", 0) or 0) == 0
            and int(rerun_watcher.get("panel_promotions", 0) or 0) == 0
            and int(rerun_promotion.get("applied", 0) or 0) == 0
        ),
    }


def _write_uat_report(path: Path, summary: UATSummary) -> None:
    checks = summary.checks or {}
    payload = {
        "watcher": summary.watcher,
        "promotion": summary.promotion,
        "rerun": summary.rerun or {},
        "checks": checks,
        "failed_checks": failing_check_names(checks),
    }
    write_contract_report(path, payload)


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
        VaultWatcher(scope, snapshot_path=snapshot_path).refresh_snapshot()

    rerun_summary: Dict[str, Dict[str, object]] | None = None
    if not dry_run:
        rerun_watcher, rerun_messages = run_watcher_tick(
            vault_root=scope,
            snapshot_path=snapshot_path,
            skip_panel=not run_panels,
            emit_only=False,
            dry_run=False,
            max_notes=max_notes,
            force=force,
            outbox_path=outbox_path,
        )
        for msg in rerun_messages:
            print(msg)
        rerun_promotion = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0}
        if consume_promotions:
            rerun_promotion = consume_promotion_intents(outbox_path=outbox_path, snapshot_path=snapshot_path)
        rerun_summary = {"watcher": rerun_watcher, "promotion": rerun_promotion}

    summary = UATSummary(watcher=watcher_summary, promotion=promotion_summary, rerun=rerun_summary)
    if not dry_run:
        summary.checks = _build_uat_checks(seeded_folder=seeded_folder, summary=summary)
        summary.report_path = _default_report_path(seeded_folder)
        _write_uat_report(summary.report_path, summary)

    if assert_expectations and not dry_run:
        _assert_uat_expectations(summary)

    return summary


def _assert_uat_expectations(summary: UATSummary) -> None:
    failures: list[str] = []
    checks = summary.checks or {}
    failures.extend(f"failed check: {name}" for name in failing_check_names(checks))
    if not checks:
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
