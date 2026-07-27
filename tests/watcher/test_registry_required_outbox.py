"""Required DB-outbox policy coverage for watcher event producers (#4064)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.events.types import INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED
from app.watcher import registry
from app.watcher.state import WatcherState

pytestmark = pytest.mark.not_pg


@pytest.mark.parametrize("topic", [PANEL_SCAN_REQUESTED, INGEST_VAULT_CHANGED])
@pytest.mark.parametrize("fails", [False, True])
def test_required_db_intent_reaches_both_watcher_producers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    topic: str,
    fails: bool,
) -> None:
    """Both watcher topics must attempt and fail loud when DB delivery is required."""
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("WATCHER_REQUIRE_DB_OUTBOX", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    observed: list[bool] = []

    def _writer(*args: object, required_db: bool = False, **kwargs: object) -> str:
        observed.append(required_db)
        if fails:
            raise RuntimeError("required watcher DB write failed")
        return "inserted-key"

    if topic == PANEL_SCAN_REQUESTED:
        monkeypatch.setattr(registry, "write_outbox_event", _writer)
    else:
        monkeypatch.setattr(registry, "insert_object_and_outbox", _writer)

    state = WatcherState()
    spec = registry.WatcherSpec(
        name="required-db",
        scope_glob="**/*.md",
        debounce_ms=0,
        rate_limit_per_min=60,
        emit_event=topic,
    )
    def call() -> str | None:
        return registry._emit_watch_event(
            spec=spec,
            cfg=None,  # type: ignore[arg-type]  # `_emit_watch_event` does not read cfg.
            outbox_path=tmp_path / "outbox.jsonl",
            vault_root=tmp_path,
            rel_path=Path("note.md"),
            mtime=1.0,
            content_hash="hash",
            state=state,
        )

    if fails:
        with pytest.raises(RuntimeError, match="required watcher DB write failed"):
            call()
        assert state.enqueue_failures_total == 1
    else:
        assert call()
        assert state.enqueue_failures_total == 0

    assert observed == [True]
