import pytest

from app.agents.note_hygiene.agent import classify_and_act
from app.write_guard import WriteGuard, WritesBlockedError


def test_guarded_or_absent(tmp_path, monkeypatch):
    """The note_hygiene write seam must respect WriteGuard (#2810, formal-model F-F)."""
    calls = []
    monkeypatch.setattr(
        "app.agents.note_hygiene.agent.write_note_from_absolute",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    blocked = WriteGuard(snapshot_fn=lambda: {"state": "safe_mode", "reason": "test-blocked"})
    note = {"fm": {"uuid": "u-guard", "kind": "concept"}, "body": ""}
    with pytest.raises(WritesBlockedError):
        classify_and_act(note, archive_base_dir=tmp_path, write_guard=blocked)
    assert not calls
