"""Issue #3894: swallowed exceptions in promotion paths must be logged.

These tests assert that when an exception is raised inside a previously
silent `except Exception` path in app/promotion/queue.py and
app/promotion/gates.py, the exception is logged (logger.exception or
logger.warning with exc_info) while the swallowing behavior itself is
preserved (no exception escapes, same return values, same JSONL receipts).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import app.promotion.gates as gates
import app.promotion.queue as q


def _exc_records(caplog: pytest.LogCaptureFixture, logger_name: str) -> list[logging.LogRecord]:
    """Records from `logger_name` at WARNING+ that carry exception info."""
    return [
        r
        for r in caplog.records
        if r.name == logger_name and r.levelno >= logging.WARNING and r.exc_info
    ]


def _setup_queue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    qpath = tmp_path / "queue.jsonl"
    log = tmp_path / "log.jsonl"
    settings = tmp_path / "settings.yaml"
    monkeypatch.setattr(q, "QUEUE", qpath)
    monkeypatch.setattr(q, "LOG", log)
    monkeypatch.setattr(q, "SETTINGS", settings)
    return qpath, log, settings


# --- app/promotion/queue.py -------------------------------------------------


def test_run_once_logs_exception_for_malformed_queue_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    qpath, log, _settings = _setup_queue(monkeypatch, tmp_path)
    qpath.write_text("this is not json\n", encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="app.promotion.queue"):
        processed = q.run_once()

    # Behavior unchanged: the bad line is swallowed, not raised.
    assert processed == 0
    # Behavior unchanged: the JSONL error receipt is still appended.
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert any("promote.error" in ln for ln in log_lines)
    # NEW: the swallowed exception is logged with traceback.
    assert _exc_records(caplog, "app.promotion.queue"), (
        "expected a WARNING+ log record with exc_info from app.promotion.queue "
        "when a queue line fails processing"
    )


def test_run_once_logs_exception_when_move_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    qpath, log, settings = _setup_queue(monkeypatch, tmp_path)
    settings.write_text(
        "promotion:\n  cooldown_seconds: 0\n  require_idle_seconds: 0\n  max_retries: 1\n"
        "  move_policy:\n    enabled: true\n    default_target: 2_Cards/Concepts\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(q, "VAULT", tmp_path / "vault")
    monkeypatch.setattr(q, "_NOTE_MOVES_ENABLED", True)
    monkeypatch.setattr(q, "prepare_relations_for_promotion", lambda *a, **k: None)
    monkeypatch.setattr(q, "ensure_object_has_relations", lambda *a, **k: None)
    monkeypatch.setenv("PROMOTION_ALLOW_ORPHANS", "1")
    monkeypatch.setenv("PROMOTION_ORPHAN_OVERRIDE_REASON", "tests")

    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")
    q.enqueue(p, uuid="00000000-0000-0000-0000-00000000a894", desired_state="promoted")

    def _boom_move(src: Path, dst_dir: Path) -> Path:
        raise OSError("disk went away")

    monkeypatch.setattr(q, "_safe_move", _boom_move)

    with caplog.at_level(logging.DEBUG, logger="app.promotion.queue"):
        processed = q.run_once()

    # Behavior unchanged: the move failure is swallowed and receipted.
    assert processed == 0
    log_lines = log.read_text(encoding="utf-8").splitlines()
    assert any(
        json.loads(ln).get("event") == "promote.error" for ln in log_lines if ln.strip()
    )
    # NEW: the swallowed move exception is logged with traceback.
    assert _exc_records(caplog, "app.promotion.queue")


def test_apply_global_settings_logs_and_defaults_on_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _RaisingGlobal:
        @property
        def note_moves_enable(self) -> bool:
            raise RuntimeError("settings backend exploded")

    class _Bundle:
        global_ = _RaisingGlobal()

    with caplog.at_level(logging.DEBUG, logger="app.promotion.queue"):
        q._apply_global_settings(_Bundle())  # type: ignore[arg-type]

    # Behavior unchanged: falls back to the permissive default.
    assert q._NOTE_MOVES_ENABLED is True
    # NEW: the swallowed exception is logged with traceback.
    assert _exc_records(caplog, "app.promotion.queue")


def test_select_target_logs_when_pick_target_raises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom(meta, policy):  # type: ignore[no-untyped-def]
        raise ValueError("no target rule matched")

    monkeypatch.setattr(q, "_pick_target", _boom)

    with caplog.at_level(logging.DEBUG, logger="app.promotion.queue"):
        target, reason = q._select_target({"tags": []}, {"enabled": True}, {}, True)

    # Behavior unchanged: swallowed into a (None, reason) skip.
    assert target is None
    assert reason == "no target rule matched"
    # NEW: the swallowed exception is logged with traceback.
    assert _exc_records(caplog, "app.promotion.queue")


# --- app/promotion/gates.py -------------------------------------------------


class _FakeRelationIndex:
    def has_any(self, src) -> bool:  # type: ignore[no-untyped-def]  # pragma: no cover - shim
        return True


def test_ensure_object_has_relations_logs_invalid_object_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.promotion.gates"):
        result = gates.ensure_object_has_relations(
            "not-a-uuid", relation_index=_FakeRelationIndex()
        )

    # Behavior unchanged: invalid ids are skipped, never raised.
    assert result is None
    # NEW: the swallowed parse failure is logged with traceback.
    assert _exc_records(caplog, "app.promotion.gates")


def test_prepare_relations_for_promotion_logs_invalid_object_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.promotion.gates"):
        added = gates.prepare_relations_for_promotion(
            "not-a-uuid", relation_index=_FakeRelationIndex()
        )

    # Behavior unchanged: invalid ids short-circuit to 0 added relations.
    assert added == 0
    # NEW: the swallowed parse failure is logged with traceback.
    assert _exc_records(caplog, "app.promotion.gates")
