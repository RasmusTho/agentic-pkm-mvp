"""Regression tests for note selection latency fix (#1289).

Verifies:
- _find_workspace_note uses direct path lookup instead of vault-wide rglob.
- get_orientation_signals is called exactly once per workspace request.

R4: note selection MUST complete within 2s for ordinary notes on dev runtime.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import HTTPException


def _write_note(directory: Path, relative: str, content: str) -> Path:
    path = directory / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _find_workspace_note: O(1) path lookup, not O(N) rglob
# ---------------------------------------------------------------------------


class TestFindWorkspaceNoteDirectLookup:
    """_find_workspace_note must resolve by direct path, not vault-wide scan."""

    def test_returns_path_for_existing_note(self, tmp_path: Path) -> None:
        from app.api.routes.companion import _find_workspace_note

        note = _write_note(tmp_path, "Notes/my.md", "# My Note")
        result = _find_workspace_note(tmp_path, "Notes/my.md")
        assert result == note

    def test_returns_none_for_missing_note(self, tmp_path: Path) -> None:
        from app.api.routes.companion import _find_workspace_note

        result = _find_workspace_note(tmp_path, "Notes/missing.md")
        assert result is None

    def test_rejects_non_markdown_note(self, tmp_path: Path) -> None:
        # Workspace reads must stay restricted to markdown notes. The direct
        # lookup replaced an rglob("*.md") scan that was implicitly md-only;
        # without a suffix guard a request such as attachments/private.txt would
        # surface arbitrary non-note vault content.
        from app.api.routes.companion import _find_workspace_note

        _write_note(tmp_path, "attachments/private.txt", "secret content")
        result = _find_workspace_note(tmp_path, "attachments/private.txt")
        assert result is None

    def test_rejects_symlink_escape(self, tmp_path: Path) -> None:
        from app.api.routes.companion import _find_workspace_note

        vault = tmp_path / "vault"
        vault.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("# Outside\n", encoding="utf-8")
        link = vault / "linked.md"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlink unavailable: {exc}")

        with pytest.raises(HTTPException) as exc_info:
            _find_workspace_note(vault, "linked.md")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail["error"] == "path_escape"

    def test_lookup_is_sub_millisecond_with_many_vault_files(self, tmp_path: Path) -> None:
        from app.api.routes.companion import _find_workspace_note

        deep = tmp_path / "Deep"
        deep.mkdir()
        for i in range(500):
            (deep / f"note_{i}.md").write_text(f"# Note {i}")

        _write_note(tmp_path, "Notes/target.md", "# Target")

        elapsed = []
        for _ in range(5):
            start = time.perf_counter()
            result = _find_workspace_note(tmp_path, "Notes/target.md")
            elapsed.append(time.perf_counter() - start)
            assert result is not None

        avg_ms = sum(elapsed) / len(elapsed) * 1000
        assert avg_ms < 10, (
            f"_find_workspace_note averaged {avg_ms:.2f}ms across 5 runs — "
            "suggests O(N) rglob is still in use (O(1) direct lookup should be <1ms)"
        )


# ---------------------------------------------------------------------------
# get_orientation_signals: called exactly once per workspace request
# ---------------------------------------------------------------------------


class TestOrientationSignalsComputedOnce:
    """Orientation signals must be computed once per workspace request, not twice."""

    def test_orientation_signals_called_once_per_request(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from app.api.routes import companion as companion_module
        from app.observability import status_service
        from app.observability.status_service import OrientationSignals
        from app.observability.status_model import (
            EventCounters,
            IngestionStatus,
            WorkerQueueStatus,
        )

        _write_note(tmp_path, "Notes/x.md", "---\nuuid: test-uuid-x\n---\n# X\n")

        call_count = 0

        def _stub_signals() -> OrientationSignals:
            nonlocal call_count
            call_count += 1
            return OrientationSignals(
                events=EventCounters(),
                ingestion=IngestionStatus(),
                worker_queue=WorkerQueueStatus(mode="none"),
            )

        monkeypatch.setattr(status_service, "get_orientation_signals", _stub_signals)
        monkeypatch.setattr(companion_module, "get_orientation_signals", _stub_signals)
        monkeypatch.setattr(companion_module, "_active_companion_vault_root", lambda: tmp_path)

        companion_module.read_companion_workspace(note_path="Notes/x.md")

        assert call_count == 1, (
            f"get_orientation_signals called {call_count} times — "
            "expected exactly 1 (shared across build_orientation_frame and "
            "evaluate_resurfacing_candidates)"
        )
