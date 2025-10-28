from pathlib import Path
from textwrap import dedent
from app.promotion.queue import enqueue, run_once

def test_smoke(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    note = vault / "@Desk" / "draft.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(dedent("""\
    ---
    uuid: U7
    review_state: inbox
    ---
    - [x] Promote
    """), encoding="utf-8")

    import app.promotion.queue as q
    monkeypatch.setattr(q, "QUEUE", tmp_path / "queue.jsonl")
    monkeypatch.setattr(q, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(q, "SETTINGS", tmp_path / "settings.yaml")
    monkeypatch.setattr(q, "VAULT", vault)
    (tmp_path / "settings.yaml").write_text("promotion:\n  cooldown_seconds: 0\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n", encoding="utf-8")

    enqueue(note, uuid="U7", desired_state="promoted")
    assert run_once() == 1
    assert "review_state: promoted" in note.read_text(encoding="utf-8")
