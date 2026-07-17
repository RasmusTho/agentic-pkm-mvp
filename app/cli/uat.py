from __future__ import annotations
import ctypes
import fcntl
import json
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Tuple
from uuid import uuid4

import yaml

from app.promotion.consumer import consume_promotion_intents
from app.receipts.settings_write import (
    ReceiptDurabilityUncertainError,
    SettingsWriteReceipt,
    durable_settings_write_receipt_exists,
    emit_settings_write_receipt,
)
from app.settings.locations import canonical_settings_root, resolve_settings_file
from app.testing.runtime_contract import failing_check_names, write_contract_report
from app.vault.layout import ensure_vault_layout, load_layout, normalize_md_filename
from app.watcher.vault_watcher import VaultWatcher, run_watcher_tick
from scripts.yaml_roundtrip import load_frontmatter

SEED_SOURCE = Path(__file__).resolve().parents[2] / "docs" / "examples" / "vault_test_seed"
DEFAULT_TARGET_SUBDIR = "Test"
DEFAULT_FOLDER_NAME = "AgenticPKM-UAT"
DEFAULT_MAX_NOTES = 50

logger = logging.getLogger(__name__)


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
            lines.append(f"ASSERTIONS_PASSED={passed}/{total}")
            lines.append(f"Checks: passed={passed}/{total}")
            if total > 0 and passed == total:
                lines.append("IDEMPOTENT=true")
        if self.report_path is not None:
            lines.append(f"Report: {self.report_path}")
        return lines


class UATAssertionError(Exception):
    pass


UATAssertMode = Literal["bootstrap", "converged"]


def seed_vault_test_notes(
    *,
    vault_root: Path,
    target_subdir: str = DEFAULT_TARGET_SUBDIR,
    folder: str = DEFAULT_FOLDER_NAME,
    overwrite: bool = False,
) -> SeedSummary:
    if not SEED_SOURCE.exists():
        raise FileNotFoundError(f"Seed source directory missing: {SEED_SOURCE}")

    resolved_root = vault_root.expanduser().resolve()
    ensure_vault_layout(resolved_root)
    _ensure_uat_ingest_scope(resolved_root, target_subdir=target_subdir)

    dest = resolved_root / target_subdir / folder
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


def _ingest_override_paths(vault_root: Path) -> tuple[Path, Path]:
    """Return the compatibility read path and canonical write path.

    Legacy settings are read-only during the compatibility release.  A UAT
    bootstrap may seed its values into the canonical artifact, but it must
    never mutate the retired location in place.
    """

    layout = load_layout(vault_root)
    filename = normalize_md_filename("ingest.override.md")
    read_path = resolve_settings_file(
        vault_root,
        filename,
        legacy_paths=(Path(layout.system_folder) / "settings" / filename,),
    )
    return read_path, canonical_settings_root(vault_root) / filename


def _read_existing_override(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_frontmatter_dict(path)


def _normalize_unique_folders(values: list[object]) -> list[str]:
    seen: set[str] = set()
    folders: list[str] = []
    for value in values:
        folder = str(value or "").strip()
        if not folder or folder in seen:
            continue
        seen.add(folder)
        folders.append(folder)
    return folders


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_durable_directory(path: Path, *, mode: int = 0o755) -> None:
    """Create a directory chain and durably link every newly created entry."""

    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.is_dir():
        raise NotADirectoryError(cursor)
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=mode)
        except FileExistsError:
            if not directory.is_dir():
                raise
        _fsync_directory(directory)
        _fsync_directory(directory.parent)


@contextmanager
def _settings_directory_lock(path: Path) -> Iterator[None]:
    """Serialize repo-supported UAT settings writers without a lock artifact."""

    descriptor = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_rename_noreplace(source: Path, target: Path) -> None:
    """Rename a same-filesystem file only when the target is still absent."""

    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    target_bytes = os.fsencode(target)
    if hasattr(libc, "renameatx_np"):
        rename = libc.renameatx_np
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-2, source_bytes, -2, target_bytes, 0x00000004)
    elif hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, source_bytes, -100, target_bytes, 0x00000001)
    else:
        raise RuntimeError("atomic no-replace publication requires renameatx_np or renameat2")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(source), str(target))


def _transaction_paths(path: Path) -> tuple[Path, Path]:
    transaction_dir = path.parent.parent / ".agentic-pkm" / "uat-settings-transactions"
    return transaction_dir, transaction_dir / "ingest-override.json"


def _write_transaction_marker(marker: Path, payload: dict[str, Any]) -> None:
    _ensure_durable_directory(marker.parent, mode=0o700)
    os.chmod(marker.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=marker.parent, prefix=f".{marker.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, marker)
        _fsync_directory(marker.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def _receipt_payload(receipt: SettingsWriteReceipt) -> dict[str, Any]:
    return {
        "key": receipt.key,
        "value": receipt.value,
        "surface": receipt.surface,
        "actor": receipt.actor,
        "operation_id": receipt.operation_id,
        "timestamp": receipt.timestamp,
        "is_runtime_gating": receipt.is_runtime_gating,
        "file": receipt.file,
        "old_value": receipt.old_value,
        "new_value": receipt.new_value,
    }


def _receipt_from_payload(payload: object) -> SettingsWriteReceipt:
    if not isinstance(payload, dict):
        raise RuntimeError("UAT settings transaction has invalid receipt payload")
    required_strings = ("key", "surface", "actor", "operation_id", "timestamp")
    if any(not isinstance(payload.get(key), str) for key in required_strings):
        raise RuntimeError("UAT settings transaction has invalid receipt identity")
    file_value = payload.get("file")
    if file_value is not None and not isinstance(file_value, str):
        raise RuntimeError("UAT settings transaction has invalid receipt file")
    return SettingsWriteReceipt(
        key=payload["key"],
        value=payload.get("value"),
        surface=payload["surface"],
        actor=payload["actor"],
        operation_id=payload["operation_id"],
        timestamp=payload["timestamp"],
        is_runtime_gating=bool(payload.get("is_runtime_gating", False)),
        file=file_value,
        old_value=payload.get("old_value"),
        new_value=payload.get("new_value"),
    )


def _build_uat_receipts(
    *,
    transaction_id: str,
    path: Path,
    previous: dict[str, Any],
    payload: dict[str, Any],
    source_path: Path,
) -> tuple[SettingsWriteReceipt, ...]:
    old_value = previous.get("include_folders")
    new_value = payload.get("include_folders")
    if old_value != new_value:
        return (
            SettingsWriteReceipt(
                key="ingest.override.include_folders",
                value=new_value,
                old_value=old_value,
                new_value=new_value,
                file=str(path),
                surface="uat-bootstrap",
                actor="uat-seed",
                operation_id=f"{transaction_id}:0",
            ),
        )
    return (
        SettingsWriteReceipt(
            key="ingest.override.__materialization__",
            value=str(path),
            old_value=str(source_path),
            new_value=str(path),
            file=str(path),
            surface="uat-bootstrap",
            actor="uat-seed",
            operation_id=f"{transaction_id}:0",
        ),
    )


def _owned_transaction_file(transaction_dir: Path, name: object) -> Path:
    if not isinstance(name, str) or Path(name).name != name:
        raise RuntimeError("UAT settings transaction has unsafe file name")
    return transaction_dir / name


def _cleanup_transaction(
    marker: Path, *, stage: Path | None = None, witness: Path | None = None
) -> None:
    for candidate in (stage, witness, marker):
        if candidate is not None:
            candidate.unlink(missing_ok=True)
    _fsync_directory(marker.parent)


def _reconcile_receipts(
    marker: Path,
    transaction: dict[str, Any],
    receipts: tuple[SettingsWriteReceipt, ...],
) -> None:
    for receipt in receipts:
        if durable_settings_write_receipt_exists(receipt):
            continue
        try:
            emit_settings_write_receipt(receipt, require_durable=True)
        except ReceiptDurabilityUncertainError:
            if durable_settings_write_receipt_exists(receipt):
                continue
            raise
        if not durable_settings_write_receipt_exists(receipt):
            raise RuntimeError("durable UAT settings receipt failed readback")
    transaction["state"] = "committed"
    _write_transaction_marker(marker, transaction)


def _reconcile_pending_transaction(path: Path) -> bool:
    transaction_dir, marker = _transaction_paths(path)
    if not marker.exists():
        return False
    try:
        transaction = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("UAT settings transaction journal is corrupt") from exc
    if not isinstance(transaction, dict) or transaction.get("version") != 1:
        raise RuntimeError("UAT settings transaction journal has unsupported shape")
    if transaction.get("target") != str(path):
        raise RuntimeError("UAT settings transaction target mismatch")

    stage = _owned_transaction_file(transaction_dir, transaction.get("stage"))
    witness = _owned_transaction_file(transaction_dir, transaction.get("witness"))
    raw_receipts = transaction.get("receipts")
    if not isinstance(raw_receipts, list) or not raw_receipts:
        raise RuntimeError("UAT settings transaction lacks receipt evidence")
    receipts = tuple(_receipt_from_payload(item) for item in raw_receipts)
    state = transaction.get("state")
    if state == "prepared" and stage.exists():
        transaction["state"] = "aborted"
        _write_transaction_marker(marker, transaction)
        _cleanup_transaction(marker, stage=stage, witness=witness)
        return False
    if state == "prepared":
        if not witness.is_file():
            raise RuntimeError("UAT settings publication state is ambiguous")
        transaction["state"] = "published_receipt_pending"
        _write_transaction_marker(marker, transaction)
        state = "published_receipt_pending"
    if state == "published_receipt_pending":
        try:
            _reconcile_receipts(marker, transaction, receipts)
        except Exception as exc:
            raise RuntimeError("UAT settings publication is receipt_pending") from exc
    elif state == "committed":
        if not all(durable_settings_write_receipt_exists(item) for item in receipts):
            raise RuntimeError("committed UAT settings transaction lacks durable receipt")
    elif state == "aborted":
        _cleanup_transaction(marker, stage=stage, witness=witness)
        return False
    else:
        raise RuntimeError("UAT settings transaction has invalid state")
    _cleanup_transaction(marker, stage=stage, witness=witness)
    return True


def _write_ingest_override(
    path: Path,
    payload: dict[str, Any],
    *,
    previous: dict[str, Any],
    source_path: Path,
) -> None:
    frontmatter = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip()
    body = (
        "# Ingest Override\n"
        "This file extends the ingest scope used by the repo-supported local test bootstrap.\n"
    )
    serialized = f"---\n{frontmatter}\n---\n\n{body}"
    if path.exists() and path.read_text(encoding="utf-8") == serialized:
        return

    _ensure_durable_directory(path.parent)
    transaction_dir, marker = _transaction_paths(path)
    _ensure_durable_directory(transaction_dir, mode=0o700)
    os.chmod(transaction_dir, 0o700)
    if marker.exists():
        raise RuntimeError("pending UAT settings transaction must be reconciled first")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=transaction_dir, prefix="stage-", suffix=".tmp"
    )
    stage = Path(temporary_name)
    witness = stage.with_name(f"{stage.name}.witness")
    transaction_id = uuid4().hex
    receipts = _build_uat_receipts(
        transaction_id=transaction_id,
        path=path,
        previous=previous,
        payload=payload,
        source_path=source_path,
    )
    transaction = {
        "version": 1,
        "state": "prepared",
        "transaction_id": transaction_id,
        "target": str(path),
        "stage": stage.name,
        "witness": witness.name,
        "receipts": [_receipt_payload(receipt) for receipt in receipts],
    }
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(stage, witness)
        _fsync_directory(transaction_dir)
        _write_transaction_marker(marker, transaction)
        had_canonical = path.exists()
        try:
            if had_canonical:
                os.replace(stage, path)
            else:
                _atomic_rename_noreplace(stage, path)
        except Exception:
            if stage.exists():
                transaction["state"] = "aborted"
                _write_transaction_marker(marker, transaction)
                _cleanup_transaction(marker, stage=stage, witness=witness)
            raise
        _fsync_directory(path.parent)
        _fsync_directory(transaction_dir)
        transaction["state"] = "published_receipt_pending"
        _write_transaction_marker(marker, transaction)
        try:
            _reconcile_receipts(marker, transaction, receipts)
        except Exception as exc:
            raise RuntimeError("UAT settings publication is receipt_pending") from exc
        _cleanup_transaction(marker, witness=witness)
    except Exception:
        if not marker.exists():
            _cleanup_transaction(marker, stage=stage, witness=witness)
            raise
        if not stage.exists():
            transaction["state"] = "published_receipt_pending"
            _write_transaction_marker(marker, transaction)
        raise


def _ensure_uat_ingest_scope(vault_root: Path, *, target_subdir: str) -> None:
    read_path, canonical_path = _ingest_override_paths(vault_root)
    _ensure_durable_directory(canonical_path.parent)
    with _settings_directory_lock(canonical_path.parent):
        if _reconcile_pending_transaction(canonical_path):
            return
        existing = _read_existing_override(read_path)
        include_folders = existing.get("include_folders")
        if isinstance(include_folders, list):
            merged = _normalize_unique_folders([*include_folders, target_subdir])
        elif include_folders is None:
            merged = [target_subdir]
        else:
            merged = _normalize_unique_folders([include_folders, target_subdir])

        payload = dict(existing)
        payload["include_folders"] = merged
        _write_ingest_override(
            canonical_path, payload, previous=existing, source_path=read_path
        )


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
    mode: UATAssertMode,
) -> Dict[str, bool]:
    evergreen_path = seeded_folder / "evergreen-strategy.md"
    manual_path = seeded_folder / "manual-policy.md"
    mixed_actions_path = seeded_folder / "mixed-actions.md"

    evergreen_frontmatter = _load_frontmatter_dict(evergreen_path)
    manual_frontmatter = _load_frontmatter_dict(manual_path)
    mixed_actions_frontmatter = _load_frontmatter_dict(mixed_actions_path)

    rerun_watcher = (summary.rerun or {}).get("watcher", {})
    rerun_promotion = (summary.rerun or {}).get("promotion", {})

    checks = {
        "watcher_errors_zero": int(summary.watcher.get("errors", 0) or 0) == 0,
        "promotion_errors_zero": int(summary.promotion.get("errors", 0) or 0) == 0,
        "rerun_no_changes": int(rerun_watcher.get("changed", 0) or 0) == 0,
        "rerun_no_panel_side_effects": (
            int(rerun_watcher.get("panel_runs", 0) or 0) == 0
            and int(rerun_watcher.get("panel_promotions", 0) or 0) == 0
            and int(rerun_promotion.get("applied", 0) or 0) == 0
        ),
    }
    if mode == "bootstrap":
        checks.update(
            {
                "promote_intent_emitted": int(summary.watcher.get("panel_promotions", 0) or 0) >= 1,
                "promotion_applied": int(summary.promotion.get("applied", 0) or 0) >= 1,
                "manual_policy_skipped": int(summary.watcher.get("panel_skipped_policy", 0) or 0) >= 1,
                "evergreen_note_promoted": (
                    str(evergreen_frontmatter.get("review_state") or "") == "reviewed"
                    and str(evergreen_frontmatter.get("maturity") or "") == "evergreen"
                ),
                "manual_note_unchanged": (
                    str(manual_frontmatter.get("ai_panel_auto_run") or "") == "never"
                    and "maturity" not in manual_frontmatter
                ),
                "mixed_actions_stays_safe": str(mixed_actions_frontmatter.get("review_state") or "") in {"", "reviewed"},
            }
        )
    elif mode != "converged":
        checks["unknown_mode"] = False

    return checks


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
    assert_mode: UATAssertMode = "bootstrap",
) -> UATSummary:
    resolved_root = vault_root.expanduser().resolve()
    scope = resolved_root / target_subdir
    if not scope.exists() or not scope.is_dir():
        raise FileNotFoundError(f"Vault scope not found: {scope}")

    seeded_folder = scope / folder
    if not seeded_folder.exists():
        raise FileNotFoundError(f"Seed folder missing; run uat-seed-vault-test first: {seeded_folder}")

    snapshot_path = _default_snapshot_path(seeded_folder)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "index-outbox.jsonl"))

    original_scope = os.environ.get("WATCHER_SCOPE_GLOB")
    os.environ["WATCHER_SCOPE_GLOB"] = f"{target_subdir}/{folder}/*.md,{target_subdir}/{folder}/**/*.md"
    try:
        watcher_summary, watcher_messages = run_watcher_tick(
            vault_root=resolved_root,
            snapshot_path=snapshot_path,
            skip_panel=not run_panels,
            emit_only=False,
            dry_run=dry_run,
            max_notes=max_notes,
            force=force,
            outbox_path=outbox_path,
        )
    finally:
        if original_scope is None:
            os.environ.pop("WATCHER_SCOPE_GLOB", None)
        else:
            os.environ["WATCHER_SCOPE_GLOB"] = original_scope

    for msg in watcher_messages:
        print(msg)

    promotion_summary: Dict[str, object] = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0}
    if consume_promotions and not dry_run:
        outbox_path = Path(os.getenv("INDEX_OUTBOX_PATH", "index-outbox.jsonl"))
        promotion_summary = consume_promotion_intents(outbox_path=outbox_path)
        VaultWatcher(resolved_root, snapshot_path=snapshot_path).refresh_snapshot()

    rerun_summary: Dict[str, Dict[str, object]] | None = None
    if not dry_run:
        original_scope = os.environ.get("WATCHER_SCOPE_GLOB")
        os.environ["WATCHER_SCOPE_GLOB"] = f"{target_subdir}/{folder}/*.md,{target_subdir}/{folder}/**/*.md"
        try:
            rerun_watcher, rerun_messages = run_watcher_tick(
                vault_root=resolved_root,
                snapshot_path=snapshot_path,
                skip_panel=not run_panels,
                emit_only=False,
                dry_run=False,
                max_notes=max_notes,
                force=force,
                outbox_path=outbox_path,
            )
        finally:
            if original_scope is None:
                os.environ.pop("WATCHER_SCOPE_GLOB", None)
            else:
                os.environ["WATCHER_SCOPE_GLOB"] = original_scope
        for msg in rerun_messages:
            print(msg)
        rerun_promotion = {"intents_seen": 0, "applied": 0, "errors": 0, "emitted": 0}
        if consume_promotions:
            rerun_promotion = consume_promotion_intents(outbox_path=outbox_path, snapshot_path=snapshot_path)
        rerun_summary = {"watcher": rerun_watcher, "promotion": rerun_promotion}

    summary = UATSummary(watcher=watcher_summary, promotion=promotion_summary, rerun=rerun_summary)
    if not dry_run:
        summary.checks = _build_uat_checks(seeded_folder=seeded_folder, summary=summary, mode=assert_mode)
        summary.report_path = _default_report_path(seeded_folder)
        _write_uat_report(summary.report_path, summary)

    if assert_expectations and not dry_run:
        _assert_uat_expectations(summary, mode=assert_mode)

    return summary


def _assert_uat_expectations(summary: UATSummary, *, mode: UATAssertMode = "bootstrap") -> None:
    failures: list[str] = []
    checks = summary.checks or {}
    if mode == "bootstrap":
        failures.extend(f"failed check: {name}" for name in failing_check_names(checks))
        if checks:
            return _raise_if_failures(failures)
        if summary.watcher.get("panel_promotions", 0) < 1:
            failures.append("Expected at least one promote.intent.created")
        if summary.promotion.get("applied", 0) < 1:
            failures.append("Expected at least one promotion to be applied by consumer")
        return _raise_if_failures(failures)

    if mode == "converged":
        if summary.watcher.get("panel_promotions", 0) != 0:
            failures.append("Expected no promote.intent.created during converged rerun")
        if summary.promotion.get("applied", 0) != 0:
            failures.append("Expected promotion consumer to be a no-op during converged rerun")
        if summary.promotion.get("errors", 0) != 0:
            failures.append("Expected no promotion consumer errors during converged rerun")
        return _raise_if_failures(failures)

    failures.append(f"Unknown UAT assert mode: {mode}")
    _raise_if_failures(failures)


def _raise_if_failures(failures: list[str]) -> None:
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
    "UATAssertMode",
]
