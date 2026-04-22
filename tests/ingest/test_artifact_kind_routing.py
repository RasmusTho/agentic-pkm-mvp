from __future__ import annotations

from pathlib import Path

from app.agents.normalizer.agent import normalize_file


def _write_note(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_missing_kind_preserves_current_note_default(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    _write_note(note, "# Sample\n\nBody")

    result = normalize_file(str(note), trace_id="test-missing-kind")

    assert result["kind"] == "note"
    assert result["payload"]["artifact_kind"] == "note"
    assert result["payload"]["policy_profile_kind"] == "note"
    assert result["payload"].get("ingest_diagnostics", []) == []


def test_explicit_allowed_kind_routes_policy_without_identity_change(tmp_path: Path) -> None:
    note = tmp_path / "task-note.md"
    _write_note(
        note,
        "---\nartifact_kind: task\n---\n# Task note\n\nBody",
    )

    result = normalize_file(str(note), trace_id="test-explicit-kind")

    assert result["kind"] == "note"
    assert result["payload"]["artifact_kind"] == "task"
    assert result["payload"]["policy_profile_kind"] == "task"
    assert result["payload"].get("ingest_diagnostics", []) == []


def test_unknown_kind_fails_closed_without_path_inference(tmp_path: Path) -> None:
    note = tmp_path / "tasks" / "unknown.md"
    _write_note(
        note,
        "---\nartifact_kind: mystery\n---\n# Unknown\n\nBody",
    )

    result = normalize_file(str(note), trace_id="test-unknown-kind")

    assert result["kind"] == "note"
    assert result["payload"]["artifact_kind"] == "note"
    assert result["payload"]["policy_profile_kind"] == "note"
    diagnostics = result["payload"].get("ingest_diagnostics", [])
    assert diagnostics
    assert diagnostics[0]["code"] == "unsupported_artifact_kind"
    assert diagnostics[0]["requested_kind"] == "mystery"
    assert diagnostics[0]["fallback_kind"] == "note"
