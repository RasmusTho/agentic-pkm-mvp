from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.agents.note_hygiene.agent import classify_and_act
from app.write_guard import WriteGuard

_HEALTHY_GUARD = WriteGuard(snapshot_fn=lambda: {"state": "healthy"})

def test_title_url_only_salvaged():
    note = {"fm":{"uuid":"u1","kind":"concept"}, "body":"# Widgets\nhttps://example.com/x"}
    out = classify_and_act(note)
    assert "## Summary" in out["body"]
    assert out["action"] == "fix_structure"

def test_frontmatter_only_archived(tmp_path):
    note = {"fm":{"uuid":"u2","kind":"concept"}, "body":""}
    out = classify_and_act(note, archive_base_dir=tmp_path, write_guard=_HEALTHY_GUARD)
    assert out["action"] == "archive"
    written = Path(out["path"])
    assert written.is_relative_to(tmp_path)
    assert written.exists()
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    assert not (Path.cwd() / "Archive" / "Trash" / current_month).exists()

def test_archive_requires_base_dir():
    note = {"fm":{"uuid":"u2b","kind":"concept"}, "body":""}
    with pytest.raises(ValueError, match="archive_base_dir"):
        classify_and_act(note)

def test_large_json_moved_to_attachment():
    body = "# A\n```\n" + "x"*10000 + "\n```"
    note = {"fm":{"uuid":"u3","kind":"concept"}, "body":body}
    out = classify_and_act(note)
    assert out["action"] in ("fix_structure","keep")


def test_archive_write_uses_knowledge_port(tmp_path, monkeypatch):
    target = tmp_path / "Archive" / "Trash" / "2026-03" / "note.md"
    writes = []

    def _fake_write_note(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or tmp_path).resolve()
        resolved_path = Path(path).resolve()
        writes.append(resolved_path.relative_to(resolved_root).as_posix())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr("app.agents.note_hygiene.agent.archive_path", lambda *args, **kwargs: str(target))
    monkeypatch.setattr("app.agents.note_hygiene.agent.write_note_from_absolute", _fake_write_note)

    note = {"fm": {"uuid": "u4", "kind": "concept"}, "body": ""}
    out = classify_and_act(note, archive_base_dir=tmp_path, write_guard=_HEALTHY_GUARD)
    assert out["action"] == "archive"
    assert writes
    assert target.exists()
