"""Hazard-safe rebuild of the derived decision-calibration projection.

Outcome JSONL is canonical.  ``decision_outcomes`` and the generated markdown
profile are rebuildable views only.  In particular, a rebuild refuses before
deleting anything when the database has an outcome the canonical log cannot
explain; this prevents the historical Postgres-only-row data loss from being
repeated for calibration.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.paths import resolve_optional_vault_root
from app.db.db import conn_rw
from app.db.replay_projection_schema import assert_replay_projection_schema
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.receipts.outcome_receipt_log import OutcomeReceipt, iter_outcome_receipts
from app.vault.paths import NoVaultSelectedError, resolve_vault_system_dir_rel_or_default
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import load_frontmatter

CALIBRATION_PROFILE_WRITE_ACTION = "decision.calibration_profile"
_OUTCOMES = ("held", "partly_held", "did_not_hold", "unknown_yet")


class CalibrationProjectionHazardError(RuntimeError):
    """A rebuild would discard a database-only outcome receipt."""


@dataclass
class CalibrationRebuildSummary:
    total_receipts: int = 0
    inserted: int = 0
    markdown_written: bool = False
    rollup: dict[str, dict[str, Any]] = field(default_factory=dict)
    confidence_rollup: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class CalibrationDoctorReport:
    ok: bool
    db_rows: int
    log_rows: int
    missing_in_db: list[dict[str, Any]] = field(default_factory=list)
    extra_in_db: list[dict[str, Any]] = field(default_factory=list)


def _root(vault_root: Path | None) -> Path:
    root = vault_root if vault_root is not None else resolve_optional_vault_root()
    if root is None:
        raise NoVaultSelectedError("calibration projection requires a selected vault; VAULT_ROOT is unset")
    return root.expanduser()


def calibration_profile_path(vault_root: Path | None = None) -> Path:
    root = _root(vault_root)
    return root / resolve_vault_system_dir_rel_or_default(root) / "calibration" / "calibration-profile.md"


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _receipt_rows(vault_root: Path | None) -> list[tuple[str, str, int, str, str | None, str]]:
    rows: list[tuple[str, str, int, str, str | None, str]] = []
    for raw in iter_outcome_receipts(vault_root):
        receipt = OutcomeReceipt.model_validate(raw)
        rows.append(
            (
                str(receipt.decision_object_id),
                str(receipt.decision_uuid),
                receipt.rung_index,
                receipt.outcome,
                receipt.note,
                _timestamp(receipt.created_at),
            )
        )
    return sorted(rows)


def _db_rows_from_cursor(
    cur: Any, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> list[tuple[str, str, int, str, str | None, str]]:
    rows: list[tuple[str, str, int, str, str | None, str]] = []
    cur.execute(
        "SELECT decision_object_id, decision_uuid, rung_index, outcome, note, created_at "
        "FROM decision_outcomes WHERE vault_binding_id = %s",
        (vault_binding_id,),
    )
    for row in cur.fetchall():
        get = row.__getitem__
        rows.append((str(get("decision_object_id") if isinstance(row, dict) else get(0)),
                     str(get("decision_uuid") if isinstance(row, dict) else get(1)),
                     int(get("rung_index") if isinstance(row, dict) else get(2)),
                     str(get("outcome") if isinstance(row, dict) else get(3)),
                     (get("note") if isinstance(row, dict) else get(4)),
                     _timestamp(get("created_at") if isinstance(row, dict) else get(5))))
    return sorted(rows)


def _db_rows(*, vault_binding_id: str) -> list[tuple[str, str, int, str, str | None, str]]:
    with conn_rw() as conn:
        assert_replay_projection_schema(conn, "decision_outcomes")
        with conn.cursor() as cur:
            return _db_rows_from_cursor(cur, vault_binding_id=vault_binding_id)


def _row_dict(row: tuple[str, str, int, str, str | None, str]) -> dict[str, Any]:
    return {
        "decision_object_id": row[0], "decision_uuid": row[1], "rung_index": row[2],
        "outcome": row[3], "note": row[4], "created_at": row[5],
    }


def doctor_calibration_projection(
    vault_root: Path | None = None, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> CalibrationDoctorReport:
    """Compare the derived table to the vault-canonical receipt log exactly."""
    log_rows = _receipt_rows(vault_root)
    db_rows = _db_rows(vault_binding_id=vault_binding_id)
    return _doctor_report(log_rows, db_rows)


def _doctor_report(
    log_rows: list[tuple[str, str, int, str, str | None, str]],
    db_rows: list[tuple[str, str, int, str, str | None, str]],
) -> CalibrationDoctorReport:
    log_counter, db_counter = Counter(log_rows), Counter(db_rows)
    missing = list((log_counter - db_counter).elements())
    extra = list((db_counter - log_counter).elements())
    return CalibrationDoctorReport(
        ok=not missing and not extra,
        db_rows=len(db_rows), log_rows=len(log_rows),
        missing_in_db=[_row_dict(row) for row in missing],
        extra_in_db=[_row_dict(row) for row in extra],
    )


def _decision_frontmatter(vault_root: Path, decision_uuid: str) -> dict[str, Any]:
    """Read only owner-authored decision notes; never read the generated profile."""
    for path in vault_root.rglob("*.md"):
        if path == calibration_profile_path(vault_root):
            continue
        try:
            frontmatter, _ = load_frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if str(frontmatter.get("uuid") or "") == decision_uuid:
            return frontmatter
    return {}


def _labels(frontmatter: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for dimension in ("area", "project"):
        value = frontmatter.get(dimension)
        if value not in (None, ""):
            labels.append(f"{dimension}:{value}")
    tags = frontmatter.get("tags")
    if isinstance(tags, str) and tags.strip():
        labels.append(f"tag:{tags.strip()}")
    elif isinstance(tags, list):
        labels.extend(f"tag:{tag}" for tag in tags if str(tag).strip())
    return labels or ["ungrouped"]


def _counts_template() -> dict[str, int]:
    return {outcome: 0 for outcome in _OUTCOMES}


def _rollup_bucket(counts: dict[str, int]) -> dict[str, Any]:
    total = sum(counts.values())
    return {
        "total": total,
        "counts": dict(counts),
        "rates": {outcome: (counts[outcome] / total if total else 0.0) for outcome in _OUTCOMES},
    }


def _compute_rollup(vault_root: Path, rows: list[tuple[str, str, int, str, str | None, str]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    grouped: defaultdict[str, dict[str, int]] = defaultdict(_counts_template)
    confidence: defaultdict[str, dict[str, int]] = defaultdict(_counts_template)
    for _object_id, decision_uuid, _rung, outcome, _note, _created in rows:
        frontmatter = _decision_frontmatter(vault_root, decision_uuid)
        for label in _labels(frontmatter):
            grouped[label][outcome] += 1
        stated_confidence = frontmatter.get("confidence")
        if stated_confidence not in (None, ""):
            confidence[str(stated_confidence)][outcome] += 1
    return (
        {label: _rollup_bucket(counts) for label, counts in sorted(grouped.items())},
        {label: _rollup_bucket(counts) for label, counts in sorted(confidence.items())},
    )


def _markdown(rollup: dict[str, dict[str, Any]], confidence_rollup: dict[str, dict[str, Any]]) -> str:
    lines = ["# Decision Calibration Profile", "", "_Generated — do not edit by hand._", "", "## By decision signal"]
    for label, bucket in rollup.items():
        counts, rates, total = bucket["counts"], bucket["rates"], bucket["total"]
        rendered = ", ".join(
            f"{outcome.replace('_', '-')} {counts[outcome]} ({rates[outcome]:.0%})"
            for outcome in _OUTCOMES if counts[outcome]
        )
        lines.append(f"- {label}: {total} outcomes ({rendered})")
    if confidence_rollup:
        lines.extend(["", "## By stated confidence"])
        for value, bucket in confidence_rollup.items():
            counts, rates, total = bucket["counts"], bucket["rates"], bucket["total"]
            rendered = ", ".join(
                f"{outcome.replace('_', '-')} {counts[outcome]} ({rates[outcome]:.0%})"
                for outcome in _OUTCOMES if counts[outcome]
            )
            lines.append(f"- {value}: {total} outcomes ({rendered})")
    return "\n".join(lines) + "\n"


def _write_markdown(vault_root: Path, rollup: dict[str, dict[str, Any]], confidence_rollup: dict[str, dict[str, Any]]) -> None:
    target = calibration_profile_path(vault_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_markdown(rollup, confidence_rollup), encoding="utf-8")


def rebuild_calibration_projection(
    vault_root: Path | None = None, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> CalibrationRebuildSummary:
    """Rebuild the derived outcome table and markdown only after hazard refusal.

    Log-only rows are expected after a projection outage and are replayed.  The
    table lock, exact parity check, delete, and replay share one transaction so
    an outcome inserted by a concurrent projection writer cannot slip between
    doctor and delete.
    """
    root = _root(vault_root)
    # Check the generated-note write authority before changing either derived
    # surface, so a blocked write cannot leave a half-completed rebuild behind.
    DEFAULT_WRITE_GUARD.assert_writes_allowed(CALIBRATION_PROFILE_WRITE_ACTION)
    summary = CalibrationRebuildSummary()
    with conn_rw() as conn:
        assert_replay_projection_schema(conn, "decision_outcomes")
        with conn.cursor() as cur:
            # INSERT/UPDATE/DELETE take ROW EXCLUSIVE.  SHARE ROW EXCLUSIVE
            # conflicts with that lock, so concurrent projection writers wait
            # until this parity-checked delete/replay has committed.
            cur.execute("LOCK TABLE decision_outcomes IN SHARE ROW EXCLUSIVE MODE")
            rows = _receipt_rows(root)
            report = _doctor_report(rows, _db_rows_from_cursor(cur, vault_binding_id=vault_binding_id))
            if report.extra_in_db:
                raise CalibrationProjectionHazardError(
                    "calibration projection rebuild refused: Postgres has "
                    f"{len(report.extra_in_db)} outcome row(s) with no matching vault-canonical receipt"
                )
            summary.total_receipts = len(rows)
            cur.execute("DELETE FROM decision_outcomes WHERE vault_binding_id = %s", (vault_binding_id,))
            for object_id, decision_uuid, rung_index, outcome, note, created_at in rows:
                cur.execute(
                    "INSERT INTO decision_outcomes "
                    "(vault_binding_id, decision_object_id, decision_uuid, rung_index, outcome, note, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (vault_binding_id, object_id, decision_uuid, rung_index, outcome, note, created_at),
                )
                summary.inserted += 1
    summary.rollup, summary.confidence_rollup = _compute_rollup(root, rows)
    _write_markdown(root, summary.rollup, summary.confidence_rollup)
    summary.markdown_written = True
    return summary


__all__ = [
    "CALIBRATION_PROFILE_WRITE_ACTION", "CalibrationDoctorReport", "CalibrationProjectionHazardError",
    "CalibrationRebuildSummary", "calibration_profile_path", "doctor_calibration_projection",
    "rebuild_calibration_projection",
]
