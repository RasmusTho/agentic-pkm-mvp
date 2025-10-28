from pathlib import Path
from textwrap import dedent
from app.promotion.queue import enqueue, run_once
from app.index.build import build_index

RULES = [
    {"when": {"review_state": "inbox"}, "action": "exclude"},
    {"when": {"review_state": "promoted"}, "action": "include", "weight": 1.0},
]

def test_intent_leads_to_index_visibility(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    note = vault / "@Desk" / "galaxy.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(dedent("""\
    ---
    uuid: U6
    review_state: inbox
    ---
    - [x] Promote
    Galaxy spiral structure
    """), encoding="utf-8")

    import app.promotion.queue as q
    monkeypatch.setattr(q, "QUEUE", tmp_path / "queue.jsonl")
    monkeypatch.setattr(q, "LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(q, "SETTINGS", tmp_path / "settings.yaml")
    monkeypatch.setattr(q, "VAULT", vault)
    (tmp_path / "settings.yaml").write_text("promotion:\n  cooldown_seconds: 0\n  require_idle_seconds: 0\n  max_retries: 1\n  move_policy:\n    enabled: false\n    default_target: 2_Cards/Concepts\n", encoding="utf-8")

    enqueue(note, uuid="U6", desired_state="promoted")
    assert run_once() == 1

    idx = build_index(vault, RULES, ignore_glob=["_system/**"])
    paths = [p["path"] for p in idx]
    assert any(Path(p).name == "galaxy.md" for p in paths)
