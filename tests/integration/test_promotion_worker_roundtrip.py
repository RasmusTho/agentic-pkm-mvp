from pathlib import Path
from textwrap import dedent
from app.promotion.queue import enqueue, run_once

def test_roundtrip_promotes_and_cleans_intent(tmp_path: Path, monkeypatch):
    qpath = tmp_path / "queue.jsonl"
    log   = tmp_path / "log.jsonl"
    settings = tmp_path / "settings.yaml"
    vault = tmp_path / "vault"
    note  = vault / "Workbench" / "draft.md"
    vault.mkdir(parents=True, exist_ok=True)
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(dedent("""\
        ---
        uuid: 00000000-0000-0000-0000-000000000004
    review_state: inbox
    ---
    - [x] Promote
    Body
    """), encoding="utf-8")

    settings.write_text(dedent("""\
    promotion:
      cooldown_seconds: 0
      require_idle_seconds: 0
      max_retries: 1
      move_policy:
        enabled: false
        default_target: 2_Cards/Concepts
    """), encoding="utf-8")

    import app.promotion.queue as q
    monkeypatch.setattr(q, "QUEUE", qpath)
    monkeypatch.setattr(q, "LOG", log)
    monkeypatch.setattr(q, "SETTINGS", settings)
    monkeypatch.setattr(q, "VAULT", vault)
    monkeypatch.setenv("PROMOTION_ALLOW_ORPHANS", "1")
    monkeypatch.setenv("PROMOTION_ORPHAN_OVERRIDE_REASON", "tests")

    enqueue(note, uuid="00000000-0000-0000-0000-000000000004", desired_state="promoted")
    processed = run_once()
    assert processed == 1

    text = note.read_text(encoding="utf-8")
    assert "review_state: promoted" in text
    assert "Promote" not in text
