from pathlib import Path

import pytest

from app.services.note_update import apply_promotion_frontmatter
from app.write_guard import DEFAULT_WRITE_GUARD, WritesBlockedError


def _note_path(tmp_path: Path) -> Path:
    target = tmp_path / "note.md"
    target.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")
    return target


def test_apply_promotion_blocked_in_safe_mode(monkeypatch, tmp_path: Path) -> None:
    path = _note_path(tmp_path)
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "safe_mode", "reason": "maintenance"},
    )
    with pytest.raises(WritesBlockedError) as exc:
        apply_promotion_frontmatter(path, "note-uuid", "evergreen")
    assert exc.value.state == "safe_mode"
    assert "evergreen" not in path.read_text(encoding="utf-8")


def test_apply_promotion_runs_when_allowed(monkeypatch, tmp_path: Path) -> None:
    path = _note_path(tmp_path)
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "running", "reason": "ok"},
    )
    result = apply_promotion_frontmatter(path, "note-uuid", "evergreen")
    assert result is True
    assert "evergreen" in path.read_text(encoding="utf-8")
    assert "maturity: evergreen" in path.read_text(encoding="utf-8")


def test_apply_promotion_writes_via_knowledge_port(monkeypatch, tmp_path: Path) -> None:
    path = _note_path(tmp_path)
    writes: list[str] = []

    def _fake_write(note_path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        writes.append(Path(note_path).resolve().relative_to(Path(note_path).anchor).as_posix())
        path.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": "running", "reason": "ok"},
    )
    monkeypatch.setattr("app.services.note_update.write_note_from_absolute", _fake_write)

    result = apply_promotion_frontmatter(path, "note-uuid", "evergreen")
    assert result is True
    assert writes
