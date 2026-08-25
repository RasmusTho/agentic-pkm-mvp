"""CAL-04 integration guarantees over the vault-canonical outcome log."""
from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

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
    name = f"scratch_calibration_integration_{uuid.uuid4().hex[:12]}"
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
    path = vault / "decisions" / f"{note_uuid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(["---", *(f"{key}: {value}" for key, value in fields.items()), "---", ""]),
        encoding="utf-8",
    )


def _append(vault: Path, object_id: str, decision_uuid: str, rung: int, outcome: str) -> None:
    from datetime import datetime, timezone

    append_outcome_receipt(
        decision_object_id=object_id,
        decision_uuid=decision_uuid,
        rung_index=rung,
        outcome=outcome,  # type: ignore[arg-type]
        created_at=datetime(2026, 8, 25, 12, rung, tzinfo=timezone.utc),
        vault_root=vault,
    )


@pytest.mark.pg
def test_rebuild_from_log_only_matches_populated_rebuild(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs.calibration_projection import doctor_calibration_projection, rebuild_calibration_projection
    import psycopg

    vault = tmp_path / "vault"
    vault.mkdir()
    _allow_writes(monkeypatch)
    decision_uuid = str(uuid.uuid4())
    _write_decision(vault, decision_uuid, area="architecture")
    _append(vault, str(uuid.uuid4()), decision_uuid, 0, "held")
    first = rebuild_calibration_projection(vault)
    with psycopg.connect(scratch_db, autocommit=True) as conn:
        conn.execute("TRUNCATE decision_outcomes")
    second = rebuild_calibration_projection(vault)
    assert second.rollup == first.rollup
    assert doctor_calibration_projection(vault).ok


@pytest.mark.pg
def test_answer_survives_projection_outage(
    scratch_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.jobs.calibration_projection import rebuild_calibration_projection
    import app.receipts.outcome_receipt_log as receipts

    vault = tmp_path / "vault"
    vault.mkdir()
    _allow_writes(monkeypatch)
    decision_uuid = str(uuid.uuid4())
    _write_decision(vault, decision_uuid, project="recovery")
    monkeypatch.setattr(receipts, "_insert_projection", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError, match="down"):
        _append(vault, str(uuid.uuid4()), decision_uuid, 0, "held")
    summary = rebuild_calibration_projection(vault)
    assert summary.inserted == 1
