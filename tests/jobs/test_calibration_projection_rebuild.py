"""CAL-04: hazard-safe rebuild of the derived calibration projection."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Any

import psycopg
import pytest

from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.receipts.outcome_receipt_log import append_outcome_receipt

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scratch_db(monkeypatch: pytest.MonkeyPatch):
    from app.db.dsn import resolve_dsn

    admin_dsn = resolve_dsn()
    if not admin_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()
    name = f"scratch_calibration_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
        conn.execute(f"ALTER DATABASE \"{name}\" SET lc_messages = 'C'")
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, "head")
    yield dsn
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        pass


def _allow_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.jobs.calibration_projection as projection
    import app.receipts.outcome_receipt_log as receipts

    monkeypatch.setattr(receipts.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)
    monkeypatch.setattr(projection.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda _: None)


def _write_decision(vault: Path, note_uuid: str, **frontmatter: object) -> None:
    fields = {"uuid": note_uuid, "title": frontmatter.pop("title", "Decision"), **frontmatter}
    lines = ["---", *(f"{key}: {value}" for key, value in fields.items()), "---", ""]
    path = vault / "decisions" / f"{note_uuid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _append(vault: Path, object_id: str, decision_uuid: str, rung: int, outcome: str) -> None:
    append_outcome_receipt(
        decision_object_id=object_id,
        decision_uuid=decision_uuid,
        rung_index=rung,
        outcome=outcome,  # type: ignore[arg-type]
        created_at=datetime(2026, 8, 25, 12, rung, tzinfo=timezone.utc),
        vault_root=vault,
    )


@pytest.mark.pg
def test_rollup_groups_by_available_kind_and_confidence(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs.calibration_projection import rebuild_calibration_projection

    vault = tmp_path / "vault"
    vault.mkdir()
    _allow_writes(monkeypatch)
    architecture = str(uuid.uuid4())
    product = str(uuid.uuid4())
    ungrouped = str(uuid.uuid4())
    _write_decision(vault, architecture, area="architecture", confidence="high")
    _write_decision(vault, product, project="product")
    _write_decision(vault, ungrouped)
    _append(vault, str(uuid.uuid4()), architecture, 0, "held")
    _append(vault, str(uuid.uuid4()), architecture, 1, "did_not_hold")
    _append(vault, str(uuid.uuid4()), product, 0, "partly_held")
    _append(vault, str(uuid.uuid4()), ungrouped, 0, "unknown_yet")

    summary = rebuild_calibration_projection(vault)
    architecture_bucket = summary.rollup["area:architecture"]
    assert architecture_bucket["total"] == 2
    assert architecture_bucket["counts"]["held"] == 1
    assert architecture_bucket["counts"]["did_not_hold"] == 1
    assert architecture_bucket["rates"]["held"] == 0.5
    assert architecture_bucket["rates"]["did_not_hold"] == 0.5
    assert summary.rollup["project:product"]["counts"]["partly_held"] == 1
    assert summary.rollup["ungrouped"]["counts"]["unknown_yet"] == 1
    assert summary.confidence_rollup["high"]["counts"]["held"] == 1
    assert summary.confidence_rollup["high"]["rates"]["held"] == 1.0


@pytest.mark.pg
def test_rebuild_replays_log_into_projection(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs.calibration_projection import doctor_calibration_projection, rebuild_calibration_projection

    vault = tmp_path / "vault"
    vault.mkdir()
    _allow_writes(monkeypatch)
    decision_uuid = str(uuid.uuid4())
    _write_decision(vault, decision_uuid, area="architecture")
    _append(vault, str(uuid.uuid4()), decision_uuid, 0, "held")
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("TRUNCATE decision_outcomes")
    summary = rebuild_calibration_projection(vault)
    assert summary.total_receipts == summary.inserted == 1
    assert doctor_calibration_projection(vault).ok


@pytest.mark.pg
def test_rebuild_refuses_when_db_has_unaccountable_rows(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real DB-only row survives: doctor runs before the rebuild DELETE."""
    from app.jobs.calibration_projection import (
        CalibrationProjectionHazardError,
        rebuild_calibration_projection,
    )

    vault = tmp_path / "vault"
    vault.mkdir()
    _allow_writes(monkeypatch)
    stray_decision = str(uuid.uuid4())
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO decision_outcomes "
            "(vault_binding_id, decision_object_id, decision_uuid, rung_index, outcome, created_at) "
            "VALUES (%s, %s, %s, 0, 'held', now())",
            (COMPATIBILITY_BINDING_ID, str(uuid.uuid4()), stray_decision),
        )
    with pytest.raises(CalibrationProjectionHazardError, match="refused"):
        rebuild_calibration_projection(vault)
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        count = conn.execute("SELECT count(*) FROM decision_outcomes").fetchone()
        assert count is not None and count[0] == 1


@pytest.mark.pg
def test_rebuild_locks_out_interleaving_db_only_write(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A projection writer cannot insert between parity check and DELETE."""
    import app.jobs.calibration_projection as projection

    vault = tmp_path / "vault"
    vault.mkdir()
    _allow_writes(monkeypatch)
    decision_uuid = str(uuid.uuid4())
    _write_decision(vault, decision_uuid, area="architecture")
    _append(vault, str(uuid.uuid4()), decision_uuid, 0, "held")

    entered, release = Event(), Event()
    original = projection._db_rows_from_cursor

    def pause_after_parity_read(
        cur: Any, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID
    ) -> list[tuple[str, str, int, str, str | None, str]]:
        rows = original(cur, vault_binding_id=vault_binding_id)
        entered.set()
        assert release.wait(timeout=5)
        return rows

    monkeypatch.setattr(projection, "_db_rows_from_cursor", pause_after_parity_read)
    failures: list[BaseException] = []

    def run_rebuild() -> None:
        try:
            projection.rebuild_calibration_projection(vault)
        except BaseException as exc:  # pragma: no cover - surfaced below
            failures.append(exc)

    thread = Thread(target=run_rebuild)
    thread.start()
    assert entered.wait(timeout=5)
    try:
        with psycopg.connect(scratch_db, autocommit=True) as conn:
            conn.execute("SET lock_timeout = '250ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                conn.execute(
                    "INSERT INTO decision_outcomes "
                    "(vault_binding_id, decision_object_id, decision_uuid, rung_index, outcome, created_at) "
                    "VALUES (%s, %s, %s, 0, 'held', now())",
                    (COMPATIBILITY_BINDING_ID, str(uuid.uuid4()), str(uuid.uuid4())),
                )
    finally:
        release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert not failures
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        count = conn.execute("SELECT count(*) FROM decision_outcomes").fetchone()
        assert count is not None and count[0] == 1


@pytest.mark.pg
def test_markdown_profile_written_on_rebuild(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs.calibration_projection import calibration_profile_path, rebuild_calibration_projection

    vault = tmp_path / "vault"
    vault.mkdir()
    _allow_writes(monkeypatch)
    decision_uuid = str(uuid.uuid4())
    _write_decision(vault, decision_uuid, area="architecture")
    _append(vault, str(uuid.uuid4()), decision_uuid, 0, "did_not_hold")
    rebuild_calibration_projection(vault)
    profile = calibration_profile_path(vault)
    assert profile.exists()
    assert "# Decision Calibration Profile" in profile.read_text(encoding="utf-8")
    assert "did-not-hold 1 (100%)" in profile.read_text(encoding="utf-8")
