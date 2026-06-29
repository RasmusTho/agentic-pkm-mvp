"""Companion workspace orientation endpoint tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.api.routes.companion as companion_module
import app.panel.confirmation as confirm_module
from app.api.app import app
from app.observability.status_model import EventCounters, IngestionStatus, WorkerQueueStatus
from app.observability.status_service import OrientationSignals
from app.orientation.leave_point_cursor import clear_leave_point_trace
from app.resurfacing.runtime import (
    ResurfacingCandidate,
    ResurfacingEvaluation,
    ResurfacingSignal,
    ResurfacingWhyNow,
)
from tests.api._vault_test_helpers import bind_initialized_vault


@pytest.fixture(autouse=True)
def _clear_runtime_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The orientation entry projection requires a *selected* (initialized) vault
    # (#2653): a bare ``uninitialized`` directory now routes to the picker, so
    # these orientation-rendering tests bind an initialized vault. The
    # ``scope.vault_id`` still comes from the configured name below, so asserted
    # identity values are unchanged.
    bind_initialized_vault(monkeypatch, tmp_path, channel="test")
    monkeypatch.setenv("PKM_CHANNEL", "test")
    monkeypatch.setenv("LEAVE_POINT_TRACE_DB", str(tmp_path / "runtime" / "leave-point.sqlite3"))
    monkeypatch.setenv(
        "MEMORY_INTENT_TRACE_PATH",
        str(tmp_path / "runtime" / "orientation-memory-intents.jsonl"),
    )
    monkeypatch.setattr(companion_module, "_configured_vault_name", lambda: "vault-test")
    clear_leave_point_trace()
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    clear_leave_point_trace()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _signals(*, pending: int = 2, pending_promotions: int = 3) -> OrientationSignals:
    now = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)
    return OrientationSignals(
        events=EventCounters(
            watcher_runs_total=5,
            watcher_runs_24h=1,
            panel_runs_total=4,
            panel_runs_24h=1,
            promote_created_total=pending_promotions,
            promote_created_24h=1,
            promotion_executed_total=1,
            promotion_executed_24h=1,
            source_path="/tmp/raw-events-path",
        ),
        ingestion=IngestionStatus(
            last_run_at=now,
            last_run_ok=True,
            total_scanned=8,
            total_ingested=6,
        ),
        worker_queue=WorkerQueueStatus(
            mode="memory",
            pending=pending,
            processed_total=7,
            source_path="/tmp/raw-worker-path",
        ),
    )


def _fake_evaluation(count: int) -> ResurfacingEvaluation:
    candidates: list[ResurfacingCandidate] = []
    for index in range(count):
        candidates.append(
            ResurfacingCandidate(
                candidate_id=f"candidate-{index}",
                label=f"Candidate {index}",
                why_now=ResurfacingWhyNow(
                    explanation=f"why now {index}",
                    signals=[
                        ResurfacingSignal(
                            name="worker_queue_pending",
                            value=index,
                            source="/tmp/raw-worker-path",
                        )
                    ],
                ),
            )
        )
    return ResurfacingEvaluation(
        generated_at="2026-05-31T12:00:00Z",
        status_summary="test",
        candidates=candidates,
    )


def _orientation(client: TestClient):
    return client.get("/api/companion/orientation")


def test_orientation_snapshot_without_note(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"]["kind"] == "workspace"
    assert data["scope"]["artifact_ref"] is None
    assert data["scope"]["channel"] == "test"
    assert data["meta"]["contract_version"] == "workspace_orientation.v1"
    assert data["leave_point"]["status"] == "absent"
    assert data["leave_point"]["authority_role"] == "derived_runtime_projection"
    assert data["memory"]["pending_candidate_count"] == 0
    assert data["mutation_intents"]
    assert all(
        intent["kind"] == "MemoryCandidate"
        and intent["target_queue"] == "agent_memory.review_queue"
        for intent in data["mutation_intents"]
    )
    assert "artifact" not in data
    assert "body" not in data


def test_scope_freshness_and_bounded_candidates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())
    monkeypatch.setattr(
        companion_module,
        "evaluate_resurfacing_candidates",
        lambda signals=None: _fake_evaluation(9),
    )

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    caps = data["meta"]["caps"]
    assert data["scope"]["kind"] == "workspace"
    assert data["meta"]["freshness"] == "fresh"
    assert data["meta"]["as_of"]
    assert data["meta"]["stale_after"]
    assert caps["resurface_candidates"] == 5
    assert len(data["resurface"]["candidates"]) == caps["resurface_candidates"]


def test_orientation_is_read_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())
    write_note = MagicMock(side_effect=AssertionError("orientation must not write vault notes"))
    write_guard = MagicMock(side_effect=AssertionError("orientation must not evaluate WriteGuard"))
    monkeypatch.setattr(companion_module, "write_note_from_absolute", write_note)
    monkeypatch.setattr(companion_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", write_guard)

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["guards"]["read_only"] is True
    assert data["mutation_intents"]
    assert write_note.call_count == 0
    assert write_guard.call_count == 0
    assert canvas_module._sessions == {}
    assert getattr(confirm_module._idempotency_store, "_cache", {}) == {}


def test_items_carry_provenance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["leave_point"]["authority_role"]
    assert "kind" in data["leave_point"]["source_ref"]
    assert "trace_id" in data["leave_point"]["source_ref"]
    items = [
        *data["open_loops"],
        *data["notable_changes"],
        *data["resurface"]["candidates"],
        data["governance"],
        data["guards"],
    ]
    assert items
    for item in items:
        assert item["authority_role"]
        assert item["source_ref"]["kind"]
        assert item["source_ref"]["ref"]
        assert not item["source_ref"]["ref"].startswith("/")


def test_placeholder_open_loop_is_not_returned(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        companion_module,
        "get_orientation_signals",
        lambda: _signals(pending=0, pending_promotions=1),
    )

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["open_loops"] == []


def test_degraded_when_source_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())

    def _fail_resurfacing(signals=None):
        raise RuntimeError("resurfacing unavailable")

    monkeypatch.setattr(companion_module, "evaluate_resurfacing_candidates", _fail_resurfacing)

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["freshness"] == "partial"
    assert "resurfacing_source_unavailable" in data["meta"]["degraded_reasons"]
    assert data["guards"]["degraded"] is True
    assert "resurfacing_source_unavailable" in data["guards"]["reasons"]
    assert data["resurface"]["candidates"] == []


def test_runtime_unavailable_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_signals():
        raise RuntimeError("status unavailable")

    monkeypatch.setattr(companion_module, "get_orientation_signals", _fail_signals)

    resp = _orientation(client)

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error"] == "runtime_unavailable"
    assert detail["contract_version"] == "workspace_orientation.v1"


def test_recents_anchor_excludes_system_dir_and_uuid_only_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_orientation_recents_anchor must not surface system-dir files or bare-UUID labels.

    Covers two ACs from #2239:
    1. Files under VAULT_SYSTEM_DIR_REL are excluded from the recency projection.
    2. When the only candidate produces a bare-UUID display label (no H1, UUID stem),
       the anchor is omitted rather than surfaced with the UUID.
    """
    import time

    from app.api.routes.companion import _orientation_recents_anchor

    system_dir = "⚙️ System"
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", system_dir)

    # Create a system-dir note with a recent mtime
    sys_note = tmp_path / system_dir / "companions" / "952d5491-e098-43a2-85db-a01ee1fb34fe.md"
    sys_note.parent.mkdir(parents=True, exist_ok=True)
    sys_note.write_text("---\nuuid: 952d5491-e098-43a2-85db-a01ee1fb34fe\n---\n")

    # Give system note a later mtime than any human note so it would win without filtering
    time.sleep(0.01)
    sys_note.touch()

    # AC1: system-dir file is excluded even when it has the latest mtime — result is None
    # (vault has no human notes yet)
    result = _orientation_recents_anchor(tmp_path)
    assert result is None, "system-dir file must not surface as recents anchor"

    # AC2: a UUID-only human note (no H1, UUID stem) must also be omitted
    uuid_stem = "952d5491-e098-43a2-85db-a01ee1fb34fe"
    uuid_note = tmp_path / f"{uuid_stem}.md"
    uuid_note.write_text("---\nuuid: 952d5491-e098-43a2-85db-a01ee1fb34fe\n---\n")
    time.sleep(0.01)
    uuid_note.touch()  # newest mtime

    result = _orientation_recents_anchor(tmp_path)
    assert result is None, "bare-UUID-only note must not surface as recents anchor"

    # Sanity: a real human note with an H1 must surface correctly
    human_note = tmp_path / "My Project.md"
    human_note.write_text("# My Project\n\nSome content.\n")
    time.sleep(0.01)
    human_note.touch()  # newest mtime

    result = _orientation_recents_anchor(tmp_path)
    assert result is not None, "human note with H1 must surface as recents anchor"
    assert result.display_label == "My Project"
    assert result.note_path == "My Project.md"


def test_recents_anchor_excludes_design_handoff_settings_scaffold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Design-Handoff ``settings/`` scaffold is machine config, not a human note.

    #2653: the orientation entry projection now runs only for an *initialized*
    vault, which always carries the committed ``settings/*.md`` scaffold
    (``vault.md``, ``local.md``, …). Those files must never surface as the
    "most recent note" — even when they have the newest mtime — exactly as the
    system-dir files are excluded.
    """
    import time

    from app.api.routes.companion import _orientation_recents_anchor

    # The autouse fixture initializes ``tmp_path`` itself (writing a settings
    # scaffold there), so use a clean sub-vault for this unit assertion.
    vault = tmp_path / "sub-vault"
    vault.mkdir()
    settings_dir = vault / "settings"
    settings_dir.mkdir()
    (settings_dir / "vault.md").write_text(
        "---\nschema: design-handoff.vault.v1\n---\n# Vault Settings\n", encoding="utf-8"
    )
    (settings_dir / "companion-ui.md").write_text(
        "---\nschema: design-handoff.companion-ui.v1\n---\n# Companion UI Settings\n",
        encoding="utf-8",
    )

    # With only the settings scaffold present, there is no human note → None,
    # even though the settings files have a fresh mtime.
    time.sleep(0.01)
    (settings_dir / "vault.md").touch()
    assert _orientation_recents_anchor(vault) is None, (
        "settings/*.md must not surface as the recents anchor"
    )

    # A real human note still wins over the (newer-touched) settings scaffold.
    human_note = vault / "My Project.md"
    human_note.write_text("# My Project\n\nContent.\n", encoding="utf-8")
    time.sleep(0.01)
    (settings_dir / "vault.md").touch()  # settings is newest on disk...
    result = _orientation_recents_anchor(vault)
    assert result is not None
    assert result.note_path == "My Project.md"  # ...but the human note still wins
    assert result.display_label == "My Project"


def test_recents_anchor_rejects_symlink_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A symlinked markdown file must not escape the active vault boundary."""
    import os

    from app.api.routes.companion import _orientation_recents_anchor

    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "System")

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    escaped_target = outside / "Escaped.md"
    escaped_target.write_text("# Escaped\n\nOutside vault.", encoding="utf-8")

    symlink_note = tmp_path / "Newest.md"
    symlink_note.symlink_to(escaped_target)
    human_note = tmp_path / "Older.md"
    human_note.write_text("# Older\n\nInside vault.", encoding="utf-8")

    shared = 1_700_000_000
    os.utime(human_note, (shared, shared))
    os.utime(escaped_target, (shared + 10, shared + 10))

    result = _orientation_recents_anchor(tmp_path)

    assert result is not None
    assert result.note_path == "Older.md"
    assert result.display_label == "Older"


def test_recents_anchor_rejects_system_dir_symlink_to_human_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A System-dir link must not surface even when it targets a valid note."""
    import os

    from app.api.routes.companion import _orientation_recents_anchor

    system_dir = "System"
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", system_dir)

    human_note = tmp_path / "Z-human.md"
    human_note.write_text("# Human Note\n\nInside vault.", encoding="utf-8")
    system_link = tmp_path / system_dir / "A-linked-human.md"
    system_link.parent.mkdir()
    system_link.symlink_to(human_note)

    shared = 1_700_000_010
    os.utime(human_note, (shared, shared))

    result = _orientation_recents_anchor(tmp_path)

    assert result is not None
    assert result.note_path == "Z-human.md"
    assert result.display_label == "Human Note"


def test_recents_anchor_skips_invalid_candidates_to_next_human_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid newest candidates are skipped so the next valid human note can win."""
    import os

    from app.api.routes.companion import _orientation_recents_anchor

    system_dir = "System"
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", system_dir)

    human_note = tmp_path / "Human.md"
    human_note.write_text("# Human Note\n\nInside vault.", encoding="utf-8")
    uuid_note = tmp_path / "952d5491-e098-43a2-85db-a01ee1fb34fe.md"
    uuid_note.write_text("---\nuuid: 952d5491-e098-43a2-85db-a01ee1fb34fe\n---\n", encoding="utf-8")
    system_note = tmp_path / system_dir / "system.md"
    system_note.parent.mkdir()
    system_note.write_text("# System Note\n\nMachine surface.", encoding="utf-8")

    os.utime(human_note, (1_700_000_000, 1_700_000_000))
    os.utime(uuid_note, (1_700_000_010, 1_700_000_010))
    os.utime(system_note, (1_700_000_020, 1_700_000_020))

    result = _orientation_recents_anchor(tmp_path)

    assert result is not None
    assert result.note_path == "Human.md"
    assert result.display_label == "Human Note"


def test_recents_anchor_skips_unreadable_candidate_to_next_human_note(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreadable newest candidates are skipped instead of emitted by filename."""
    import os

    from app.api.routes.companion import _orientation_recents_anchor

    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "System")

    human_note = tmp_path / "Readable.md"
    human_note.write_text("# Readable Note\n\nInside vault.", encoding="utf-8")
    unreadable_note = tmp_path / "Unreadable.md"
    unreadable_note.write_text("# Unreadable\n\nNo read permission.", encoding="utf-8")

    os.utime(human_note, (1_700_000_000, 1_700_000_000))
    os.utime(unreadable_note, (1_700_000_010, 1_700_000_010))

    original_read_text = Path.read_text

    def _read_text(path: Path, *args, **kwargs):
        if path == unreadable_note.resolve():
            raise PermissionError("simulated unreadable candidate")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _read_text)

    result = _orientation_recents_anchor(tmp_path)

    assert result is not None
    assert result.note_path == "Readable.md"
    assert result.display_label == "Readable Note"


def test_orientation_payload_includes_recent_target_with_deterministic_tiebreak(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """recents_anchor is present with correct path when vault has notes;
    tiebreak is path-sort (ascending) when multiple notes share the same mtime.
    """
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())
    vault = tmp_path
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    # Create two notes with identical mtime — path sort must resolve the tie.
    note_a = vault / "A-first.md"
    note_b = vault / "Z-second.md"
    note_a.write_text("# Alpha Note\n\nBody.", encoding="utf-8")
    note_b.write_text("# Zeta Note\n\nBody.", encoding="utf-8")
    # Force identical mtime so only path-sort distinguishes them.
    import os, time as _time
    shared_ts = _time.time() + 100  # future so they're clearly "most recent"
    os.utime(note_a, (shared_ts, shared_ts))
    os.utime(note_b, (shared_ts, shared_ts))

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    anchor = data.get("recents_anchor")
    assert anchor is not None, "recents_anchor must be present when vault has notes"
    # Path-sort tiebreak: A-first.md < Z-second.md → A-first.md wins.
    assert anchor["note_path"] == "A-first.md"
    assert anchor["display_label"] == "Alpha Note"
    # Explicitly NOT a leave_point: the field must not appear in leave_point.
    assert "recents_anchor" not in data.get("leave_point", {})
    # Must be a browser-safe relative path (no absolute filesystem path).
    assert not anchor["note_path"].startswith("/")


def test_orientation_payload_omits_recents_anchor_when_vault_empty(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """recents_anchor is absent (None) when the vault has no markdown files."""
    monkeypatch.setattr(companion_module, "get_orientation_signals", lambda: _signals())
    vault = tmp_path
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    # No .md files in the vault.

    resp = _orientation(client)

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("recents_anchor") is None
