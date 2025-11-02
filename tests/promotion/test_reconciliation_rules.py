from pathlib import Path
import time
from app.promotion.queue import enqueue, run_once

def test_changes_during_cooldown_defers_processing(tmp_path: Path, monkeypatch):
    qpath = tmp_path / "queue.jsonl"
    log   = tmp_path / "log.jsonl"
    settings = tmp_path / "settings.yaml"

    settings.write_text("promotion:\n  cooldown_seconds: 0\n  require_idle_seconds: 2\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n", encoding="utf-8")

    import app.promotion.queue as q
    monkeypatch.setattr(q, "QUEUE", qpath)
    monkeypatch.setattr(q, "LOG", log)
    monkeypatch.setattr(q, "SETTINGS", settings)

    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nX\n", encoding="utf-8")

    enqueue(p, uuid="U3", desired_state="promoted")
    p.write_text("---\nreview_state: inbox\n---\nY\n", encoding="utf-8")
    processed = run_once()
    assert processed == 0
