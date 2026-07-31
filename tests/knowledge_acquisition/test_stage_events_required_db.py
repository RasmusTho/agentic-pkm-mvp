"""A skipped stage event may not be reported as "already recorded" (#4214).

`app/knowledge_acquisition/stage_events.py`'s emitters take an OPTIONAL `conn`
and the acquisition entrypoints forward their own `conn=None` default, so these
are self-owned writes at runtime. Left unclassified, the memory-mode skip branch
made them return `""` without connecting — and `acquire.py` / `replay.py` read
`event_row == ""` as `idempotent=True`, i.e. a receipt asserting the stage
transition was ALREADY durably recorded. The candidate note still lands in the
vault, so the acquisition completes with `ok=True` and no lineage trail: exactly
what `app/knowledge_acquisition/acquire.py`'s module docstring says must never
happen ("silently skipping it would produce an acquisition with no lineage
trail").
"""

from __future__ import annotations

from typing import Any

import pytest

from app.knowledge_acquisition import stage_events
from app.services import outbox as outbox_service

pytestmark = pytest.mark.not_pg


@pytest.fixture()
def memory_backend_with_a_named_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """The configuration `acquire.py` demands, under an explicit memory backend."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    def _unavailable(*args: object, **kwargs: object) -> Any:
        raise RuntimeError("stage outbox unavailable")

    monkeypatch.setattr(outbox_service, "_open_conn", _unavailable)


def test_stage_completed_fails_loud_instead_of_returning_a_false_dedup(
    memory_backend_with_a_named_database: None,
) -> None:
    with pytest.raises(RuntimeError, match="stage outbox unavailable"):
        stage_events.emit_stage_completed(
            stage="normalize",
            stage_version=1,
            content_identity="sha256:" + "a" * 64,
            trace_id="trace-4214",
        )


def test_stage_dead_letter_fails_loud_instead_of_returning_a_false_dedup(
    memory_backend_with_a_named_database: None,
) -> None:
    with pytest.raises(RuntimeError, match="stage outbox unavailable"):
        stage_events.emit_stage_dead_letter(
            stage="normalize",
            stage_version=1,
            content_identity="sha256:" + "b" * 64,
            reason="unreachable",
            error="stage outbox unavailable",
            trace_id="trace-4214",
        )


def test_a_supplied_connection_still_owns_its_transaction(
    memory_backend_with_a_named_database: None,
) -> None:
    """`required_db` must not disturb the caller-owned path."""

    class _Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def execute(self, _sql: str, params: tuple[object, ...]) -> None:
            self.calls.append(params)

        def fetchone(self) -> tuple[str]:
            return ("stage-row",)

    class _Connection:
        def __init__(self) -> None:
            self.autocommit = False
            self.closed = False
            self.cursor_instance = _Cursor()

        def cursor(self) -> _Cursor:
            return self.cursor_instance

        def close(self) -> None:
            self.closed = True

    conn = _Connection()
    row = stage_events.emit_stage_completed(
        stage="normalize",
        stage_version=1,
        content_identity="sha256:" + "c" * 64,
        trace_id="trace-4214",
        conn=conn,
    )

    assert row == "stage-row"
    assert conn.cursor_instance.calls
    assert conn.closed is False, "a supplied connection must stay caller-owned"
