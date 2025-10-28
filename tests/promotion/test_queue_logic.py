from pathlib import Path
import time
import json

# expected API
from app.promotion.queue import enqueue, run_once

def test_enqueue_writes_single_jsonl_line(tmp_path: Path, monkeypatch):
    qpath = tmp_path / "queue.jsonl"
    log   = tmp_path / "log.jsonl"

    import app.promotion.queue as q
    monkeypatch.setattr(q, "QUEUE", qpath)
    monkeypatch.setattr(q, "LOG", log)
    monkeypatch.setattr(q, "SETTINGS", tmp_path / "settings.yaml")
    (tmp_path / "settings.yaml").write_text("promotion:\n  cooldown_seconds: 999\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n", encoding="utf-8")

    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nBody\n", encoding="utf-8")

    enqueue(p, uuid="U1", desired_state="promoted")
    lines = qpath.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["uuid"] == "U1"
    assert obj["path"].endswith("note.md")
    assert obj["desired_state"] == "promoted"

def test_run_once_requeues_before_cooldown(tmp_path: Path, monkeypatch):
    qpath = tmp_path / "queue.jsonl"
    log   = tmp_path / "log.jsonl"
    settings = tmp_path / "settings.yaml"

    settings.write_text("promotion:\n  cooldown_seconds: 10\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n", encoding="utf-8")

    import app.promotion.queue as q
    monkeypatch.setattr(q, "QUEUE", qpath)
    monkeypatch.setattr(q, "LOG", log)
    monkeypatch.setattr(q, "SETTINGS", settings)

    p = tmp_path / "vault" / "note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nreview_state: inbox\n---\nX\n", encoding="utf-8")

    enqueue(p, uuid="U2", desired_state="promoted")
    processed = run_once()
    assert processed == 0
    assert qpath.exists() and len(qpath.read_text(encoding="utf-8").splitlines()) == 1
